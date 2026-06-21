"""In-memory snapshot + decision/audit store.

Each recalculation produces an IMMUTABLE scenario snapshot keyed by its
deterministic ``scenario_id``. Approval binds to a stored snapshot by id and never
re-solves the optimizer — so the marketer approves exactly the plan they saw, and
the audit records that plan's constraints, policy, allocation, and full
modeling/config provenance. Approval is idempotent; a rejected snapshot can never
produce execution events; an unknown (or evicted) id is stale; an approval whose
engine/config/data state has changed since the snapshot is rejected as stale by
the API layer. In-memory only (a durable audit store arrives in Stage 4).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from backend.api.marts import create_marts, export_marts, query_mart
from backend.api.schemas import (
    BindingReport,
    CampaignLine,
    ConstraintParams,
    DecisionResponse,
    ExecutionEvent,
    ExecutionPayloadChange,
    ExecutionPlatformPayload,
    ExecutionPreview,
    Recommendation,
)
from backend.decision_engine.config import DATA_DIR

# Default durable audit DB (gitignored). Override with the TC_AUDIT_DB env var.
DEFAULT_AUDIT_DB: Path = DATA_DIR / "audit" / "decisions.db"


class DecisionConflict(Exception):
    """A different decision already exists for this scenario."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SnapshotStore:
    """Immutable scenario snapshots, keyed by scenario_id.

    Bounded (LRU): a marketer dragging sliders generates many scenarios, so the
    store caps memory and lets very old snapshots expire (an evicted id then reads
    as stale → 404, the correct behavior)."""

    def __init__(self, maxsize: int = 512) -> None:
        self._lock = threading.Lock()
        self._snaps: OrderedDict[str, Recommendation] = OrderedDict()
        self._maxsize = maxsize
        self._latest: str | None = None   # the most-recently-computed scenario

    def put(self, rec: Recommendation) -> Recommendation:
        """Store (first write wins → immutable) and return the CANONICAL snapshot,
        so callers display exactly what is stored (no generated_at drift). The most
        recent put becomes the 'latest' (active) scenario for supersession."""
        with self._lock:
            self._latest = rec.scenario_id   # (re)computing a plan makes it active
            existing = self._snaps.get(rec.scenario_id)
            if existing is not None:
                self._snaps.move_to_end(rec.scenario_id)
                return existing
            self._snaps[rec.scenario_id] = rec
            if len(self._snaps) > self._maxsize:
                # the LRU victim is the oldest, never the just-added latest
                self._snaps.popitem(last=False)
            return rec

    def get(self, scenario_id: str) -> Recommendation | None:
        with self._lock:
            snap = self._snaps.get(scenario_id)
            if snap is not None:
                self._snaps.move_to_end(scenario_id)
            return snap

    def is_latest(self, scenario_id: str) -> bool:
        """True iff this scenario is the most-recently-computed (active) plan."""
        with self._lock:
            return self._latest == scenario_id


@dataclass
class _Decision:
    scenario_id: str
    rec_id: str
    policy: str
    constraints: ConstraintParams
    allocation: dict[str, float]
    data_fingerprint: str
    engine_version: str
    config_fingerprint: str
    calibration_fingerprint: str
    effective_calibration_fingerprint: str
    binding: BindingReport
    action: str  # approve | reject
    status: str  # approved | rejected
    approver: str
    decided_at: str
    notes: str | None
    execution_events: list[ExecutionEvent] = field(default_factory=list)
    # Hash-chain links — populated on append/read, surfaced for the audit ledger view.
    ledger_seq: int = 0
    prev_hash: str = ""
    row_hash: str = ""


def _canonical_platform_payloads(
    rec: Recommendation,
) -> list[tuple[str, list[CampaignLine], str]]:
    """(platform, changed_lines, payload_hash) per platform — the deterministic stubbed
    set-budget calls. Only changed, non-inventory-blocked lines are pushed. The hash is
    over the CANONICAL {campaign_id, new_daily_budget} list, so a PREVIEWED hash is
    byte-identical to the hash later COMMITTED to the audit ledger."""
    changed: dict[str, list[CampaignLine]] = {}
    for line in rec.lines:
        if line.recommended_spend != line.current_spend and "inventory_no_scale" not in line.risk_flags:
            changed.setdefault(line.platform, []).append(line)

    out: list[tuple[str, list[CampaignLine], str]] = []
    for platform, lines in sorted(changed.items()):
        canonical = {
            "platform": platform,
            "changes": [
                {"campaign_id": ln.campaign_id, "new_daily_budget": ln.recommended_spend}
                for ln in lines
            ],
        }
        payload_hash = hashlib.sha256(
            json.dumps(canonical, sort_keys=True).encode("utf-8")
        ).hexdigest()
        out.append((platform, lines, payload_hash))
    return out


def _stub_execution_events(rec: Recommendation) -> list[ExecutionEvent]:
    """One stubbed execution event per platform with a changed, non-blocked line."""
    return [
        ExecutionEvent(
            event_id=f"EXEC-{rec.scenario_id}-{i:02d}",
            rec_id=rec.rec_id, platform=platform, payload_hash=payload_hash,
            status="stubbed_no_live_write", is_stub=True, created_at=_now(),
        )
        for i, (platform, _lines, payload_hash) in enumerate(
            _canonical_platform_payloads(rec), start=1
        )
    ]


def build_execution_preview(rec: Recommendation) -> ExecutionPreview:
    """Pre-approval preview of the stubbed payloads — pure, records nothing. The per-
    platform `event_id` and `payload_hash` match exactly what approval commits, so the
    operator can verify the previewed plan is what lands in the ledger."""
    payloads: list[ExecutionPlatformPayload] = []
    total = 0
    for i, (platform, lines, payload_hash) in enumerate(
        _canonical_platform_payloads(rec), start=1
    ):
        changes = [
            ExecutionPayloadChange(
                campaign_id=ln.campaign_id, campaign_name=ln.campaign_name,
                platform=ln.platform, current_spend=ln.current_spend,
                new_daily_budget=ln.recommended_spend, delta_pct=ln.delta_pct,
            )
            for ln in lines
        ]
        total += len(changes)
        payloads.append(
            ExecutionPlatformPayload(
                event_id=f"EXEC-{rec.scenario_id}-{i:02d}",
                platform=platform, payload_hash=payload_hash, is_stub=True, changes=changes,
            )
        )
    held_flat = [
        ln.campaign_name for ln in rec.lines if ln.recommended_spend == ln.current_spend
    ]
    inventory_blocked = [
        ln.campaign_name for ln in rec.lines
        if ln.recommended_spend != ln.current_spend and "inventory_no_scale" in ln.risk_flags
    ]
    note = (
        "Stubbed set-budget calls that WOULD be sent to Meta/Google on approval. No live "
        "writes occur — this is a decision & governance layer. Each payload hash is "
        "byte-identical to the hash committed to the append-only audit ledger."
    )
    return ExecutionPreview(
        scenario_id=rec.scenario_id, total_changes=total, held_flat=held_flat,
        inventory_blocked=inventory_blocked, payloads=payloads, note=note,
    )


def _decision_to_response(d: _Decision, idempotent: bool = False) -> DecisionResponse:
    return DecisionResponse(
        rec_id=d.rec_id, scenario_id=d.scenario_id, policy=d.policy,
        constraints=d.constraints, allocation=dict(d.allocation),
        data_fingerprint=d.data_fingerprint, engine_version=d.engine_version,
        config_fingerprint=d.config_fingerprint,
        calibration_fingerprint=d.calibration_fingerprint,
        effective_calibration_fingerprint=d.effective_calibration_fingerprint,
        binding=d.binding,
        action=d.action, previous_status="pending", new_status=d.status,
        status=d.status, approver=d.approver, decided_at=d.decided_at, notes=d.notes,
        execution_events=list(d.execution_events), idempotent_replay=idempotent,
        ledger_seq=d.ledger_seq, prev_hash=d.prev_hash, row_hash=d.row_hash,
    )


def _decision_from_record(rec: Recommendation, action: str, approver: str,
                          notes: str | None) -> _Decision:
    status = "approved" if action == "approve" else "rejected"
    events = _stub_execution_events(rec) if status == "approved" else []
    return _Decision(
        scenario_id=rec.scenario_id, rec_id=rec.rec_id, policy=rec.policy_mode,
        constraints=rec.constraints,
        allocation={ln.campaign_id: ln.recommended_spend for ln in rec.lines},
        data_fingerprint=rec.data_fingerprint, engine_version=rec.engine_version,
        config_fingerprint=rec.config_fingerprint,
        calibration_fingerprint=rec.calibration_fingerprint,
        effective_calibration_fingerprint=rec.effective_calibration_fingerprint,
        binding=rec.binding, action=action, status=status, approver=approver,
        decided_at=_now(), notes=notes, execution_events=events,
    )


# --- Stage 4.4: durable, append-only, hash-chained audit store ---------------
_GENESIS_HASH = "0" * 64

_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id TEXT NOT NULL UNIQUE,
    rec_id TEXT NOT NULL,
    policy TEXT NOT NULL,
    constraints_json TEXT NOT NULL,
    allocation_json TEXT NOT NULL,
    data_fingerprint TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    config_fingerprint TEXT NOT NULL,
    calibration_fingerprint TEXT NOT NULL,
    effective_calibration_fingerprint TEXT NOT NULL,
    binding_json TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    approver TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    notes TEXT,
    execution_events_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    row_hash TEXT NOT NULL
);
-- append-only: terminal decisions are immutable, so block in-place edits/deletes
-- at the DB level (tamper-evidence on top of the hash chain).
CREATE TRIGGER IF NOT EXISTS decisions_no_update BEFORE UPDATE ON decisions
BEGIN SELECT RAISE(ABORT, 'audit log is append-only: UPDATE is forbidden'); END;
CREATE TRIGGER IF NOT EXISTS decisions_no_delete BEFORE DELETE ON decisions
BEGIN SELECT RAISE(ABORT, 'audit log is append-only: DELETE is forbidden'); END;
"""


def _row_payload(d: _Decision) -> dict:
    """The canonical, order-stable content that the hash chain commits to."""
    return {
        "scenario_id": d.scenario_id, "rec_id": d.rec_id, "policy": d.policy,
        "constraints": d.constraints.model_dump(), "allocation": d.allocation,
        "data_fingerprint": d.data_fingerprint, "engine_version": d.engine_version,
        "config_fingerprint": d.config_fingerprint,
        "calibration_fingerprint": d.calibration_fingerprint,
        "effective_calibration_fingerprint": d.effective_calibration_fingerprint,
        "binding": d.binding.model_dump(),
        "action": d.action, "status": d.status, "approver": d.approver,
        "decided_at": d.decided_at, "notes": d.notes,
        "execution_events": [e.model_dump() for e in d.execution_events],
    }


def _chain_hash(prev_hash: str, payload: dict) -> str:
    body = prev_hash + json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class DurableDecisionStore:
    """Decisions keyed by scenario_id, persisted to SQLite as an append-only,
    hash-chained ledger (Stage 4.4).

    Each row commits to ``sha256(prev_row_hash + canonical_payload)``, so the full
    history is tamper-evident (``verify_chain``) and survives process restarts. The
    decision contract is unchanged from the in-memory store: first write wins,
    idempotent replay of the same action returns the stored decision, a conflicting
    action raises ``DecisionConflict``, and terminal records never mutate (enforced
    by DB triggers). Pass ``":memory:"`` for an ephemeral per-test ledger."""

    def __init__(self, db_path: str | Path = DEFAULT_AUDIT_DB) -> None:
        self._lock = threading.Lock()
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_AUDIT_SCHEMA)
        create_marts(self._conn)   # Looker-ready views live alongside the ledger
        self._conn.commit()

    def _fetch(self, scenario_id: str) -> _Decision | None:
        row = self._conn.execute(
            "SELECT * FROM decisions WHERE scenario_id = ?", (scenario_id,)).fetchone()
        return self._row_to_decision(row) if row is not None else None

    @staticmethod
    def _row_to_decision(row: sqlite3.Row) -> _Decision:
        return _Decision(
            scenario_id=row["scenario_id"], rec_id=row["rec_id"], policy=row["policy"],
            constraints=ConstraintParams(**json.loads(row["constraints_json"])),
            allocation=json.loads(row["allocation_json"]),
            data_fingerprint=row["data_fingerprint"], engine_version=row["engine_version"],
            config_fingerprint=row["config_fingerprint"],
            calibration_fingerprint=row["calibration_fingerprint"],
            effective_calibration_fingerprint=row["effective_calibration_fingerprint"],
            binding=BindingReport(**json.loads(row["binding_json"])),
            action=row["action"], status=row["status"], approver=row["approver"],
            decided_at=row["decided_at"], notes=row["notes"],
            execution_events=[ExecutionEvent(**e)
                              for e in json.loads(row["execution_events_json"])],
            ledger_seq=row["seq"], prev_hash=row["prev_hash"], row_hash=row["row_hash"],
        )

    def get(self, scenario_id: str) -> DecisionResponse | None:
        with self._lock:
            d = self._fetch(scenario_id)
            return _decision_to_response(d) if d else None

    def status(self, scenario_id: str) -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT status FROM decisions WHERE scenario_id = ?", (scenario_id,)).fetchone()
            return row["status"] if row is not None else "pending"

    def decide(self, rec: Recommendation, action: str, approver: str,
               notes: str | None) -> DecisionResponse:
        status = "approved" if action == "approve" else "rejected"
        with self._lock:
            existing = self._fetch(rec.scenario_id)
            if existing is not None:
                if existing.status != status:
                    raise DecisionConflict(
                        f"{rec.scenario_id} already {existing.status}; cannot {action}")
                return _decision_to_response(existing, idempotent=True)  # idempotent replay
            d = _decision_from_record(rec, action, approver, notes)
            self._append(d)
            return _decision_to_response(d)

    def _append(self, d: _Decision) -> None:
        last = self._conn.execute(
            "SELECT seq, row_hash FROM decisions ORDER BY seq DESC LIMIT 1").fetchone()
        prev_hash = last["row_hash"] if last is not None else _GENESIS_HASH
        row_hash = _chain_hash(prev_hash, _row_payload(d))
        # surface the chain links on the just-committed decision (audit ledger view)
        d.prev_hash, d.row_hash = prev_hash, row_hash
        d.ledger_seq = (last["seq"] + 1) if last is not None else 1
        self._conn.execute(
            """INSERT INTO decisions (
                scenario_id, rec_id, policy, constraints_json, allocation_json,
                data_fingerprint, engine_version, config_fingerprint, calibration_fingerprint,
                effective_calibration_fingerprint, binding_json, action, status, approver,
                decided_at, notes, execution_events_json, prev_hash, row_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (d.scenario_id, d.rec_id, d.policy, json.dumps(d.constraints.model_dump()),
             json.dumps(d.allocation), d.data_fingerprint, d.engine_version,
             d.config_fingerprint, d.calibration_fingerprint,
             d.effective_calibration_fingerprint, json.dumps(d.binding.model_dump()),
             d.action, d.status, d.approver, d.decided_at, d.notes,
             json.dumps([e.model_dump() for e in d.execution_events]), prev_hash, row_hash))
        self._conn.commit()

    def reset(self) -> int:
        """DEMO/admin reset: wipe the entire ledger and start a fresh hash chain.

        This is intentionally OUTSIDE the governed decision flow — terminal decisions
        are otherwise immutable (the DROP below clears the append-only triggers with
        the table, then the schema is recreated). It exists so the prototype can be
        re-run from a clean slate; a production deploy would gate or remove it. Returns
        the number of decisions that were cleared."""
        with self._lock:
            cleared = self._conn.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()["n"]
            # dropping the table also drops its append-only triggers; recreate fresh
            self._conn.execute("DROP TABLE IF EXISTS decisions")
            self._conn.executescript(_AUDIT_SCHEMA)
            create_marts(self._conn)
            self._conn.commit()
            return int(cleared)

    def all_decisions(self) -> list[DecisionResponse]:
        """The full ledger in commit order (newest decisions last) — feeds the audit
        view and the Looker-ready marts (Stage 4.5)."""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM decisions ORDER BY seq ASC").fetchall()
            return [_decision_to_response(self._row_to_decision(r)) for r in rows]

    def verify_chain(self) -> dict:
        """Recompute the hash chain over the stored history; report integrity. A
        broken link means a row was altered out-of-band (the DB triggers forbid the
        normal UPDATE/DELETE paths, so this catches direct-file tampering)."""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM decisions ORDER BY seq ASC").fetchall()
            prev_hash = _GENESIS_HASH
            for row in rows:
                expected = _chain_hash(prev_hash, _row_payload(self._row_to_decision(row)))
                if row["prev_hash"] != prev_hash or row["row_hash"] != expected:
                    return {"ok": False, "count": len(rows), "broken_seq": row["seq"]}
                prev_hash = row["row_hash"]
            return {"ok": True, "count": len(rows), "head_hash": prev_hash}

    def mart(self, name: str) -> list[dict]:
        """Rows of a Looker-ready mart view (Stage 4.5) over the ledger."""
        with self._lock:
            return query_mart(self._conn, name)

    def export_marts(self, out_dir) -> list:
        """Write the mart DDL + CSV extracts (offline BI / review)."""
        with self._lock:
            return export_marts(self._conn, out_dir)
