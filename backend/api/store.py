"""In-memory decision/audit store for the Stage 1 shell.

Records approve/reject decisions and, on approval, generates STUBBED execution
events (no real OAuth, no live media writes). Approval is idempotent; a rejected
recommendation can never produce execution events. Persistence is in-memory only
(a real audit store arrives in Stage 4).
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from backend.api.schemas import (
    CampaignLine,
    DecisionResponse,
    ExecutionEvent,
    Recommendation,
)


class DecisionConflict(Exception):
    """A different decision already exists for this recommendation."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _Decision:
    rec_id: str
    action: str  # approve | reject
    status: str  # approved | rejected
    approver: str
    decided_at: str
    notes: str | None
    execution_events: list[ExecutionEvent] = field(default_factory=list)


def _stub_execution_events(rec: Recommendation) -> list[ExecutionEvent]:
    """One stubbed execution payload per platform with a changed, non-blocked line."""
    changed: dict[str, list[CampaignLine]] = {}
    for line in rec.lines:
        if line.recommended_spend != line.current_spend and "inventory_no_scale" not in line.risk_flags:
            changed.setdefault(line.platform, []).append(line)

    events: list[ExecutionEvent] = []
    for i, (platform, lines) in enumerate(sorted(changed.items()), start=1):
        payload = {
            "platform": platform,
            "changes": [
                {"campaign_id": ln.campaign_id, "new_daily_budget": ln.recommended_spend}
                for ln in lines
            ],
        }
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        events.append(
            ExecutionEvent(
                event_id=f"EXEC-{rec.rec_id}-{i:02d}",
                rec_id=rec.rec_id,
                platform=platform,
                payload_hash=payload_hash,
                status="stubbed_no_live_write",
                is_stub=True,
                created_at=_now(),
            )
        )
    return events


class DecisionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._decisions: dict[str, _Decision] = {}

    def get(self, rec_id: str) -> DecisionResponse | None:
        with self._lock:
            d = self._decisions.get(rec_id)
            return self._to_response(d) if d else None

    def status(self, rec_id: str) -> str:
        """Current lifecycle status: 'pending' until a decision is recorded."""
        with self._lock:
            d = self._decisions.get(rec_id)
            return d.status if d else "pending"

    def decide(
        self, rec: Recommendation, action: str, approver: str, notes: str | None
    ) -> DecisionResponse:
        status = "approved" if action == "approve" else "rejected"
        with self._lock:
            existing = self._decisions.get(rec.rec_id)
            if existing is not None:
                if existing.status != status:
                    raise DecisionConflict(
                        f"{rec.rec_id} already {existing.status}; cannot {action}"
                    )
                # idempotent replay of the same decision
                return self._to_response(existing, idempotent=True)

            events = _stub_execution_events(rec) if status == "approved" else []
            d = _Decision(
                rec_id=rec.rec_id, action=action, status=status, approver=approver,
                decided_at=_now(), notes=notes, execution_events=events,
            )
            self._decisions[rec.rec_id] = d
            return self._to_response(d)

    @staticmethod
    def _to_response(d: _Decision, idempotent: bool = False) -> DecisionResponse:
        return DecisionResponse(
            rec_id=d.rec_id, action=d.action, previous_status="pending",
            new_status=d.status, status=d.status, approver=d.approver,
            decided_at=d.decided_at, notes=d.notes,
            execution_events=list(d.execution_events), idempotent_replay=idempotent,
        )
