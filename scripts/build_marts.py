"""Stage 4.5 — build the Looker-ready SQL marts from the durable audit ledger.

Opens the marts ledger, SEEDS it (once) with the current engine recommendation if it
is empty, (re)creates the mart views, prints a row-count summary, and exports the DDL
+ a CSV extract per mart to ``reports/marts/`` plus a ``MANIFEST.json`` stamping the
dataset profile / fingerprint / report version so the committed marts can never be
silently mistaken for a different dataset (D-038).

Ledger choice: by default a DEDICATED demo ledger (``data/audit/demo_marts.db``), so
the committed marts are reproducible and isolated from any runtime API ledger. Override
with ``TC_AUDIT_DB``. Seeding is idempotent (only when the ledger is empty), so re-runs
against the same ledger are stable; the decision ``decided_at`` is wall-clock and frozen
at first seed.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from backend.api.marts import MART_NAMES
from backend.api.recommendation import RUN_ID, build_recommendation
from backend.api.store import DurableDecisionStore
from backend.decision_engine import config as C
from backend.decision_engine.config import DATA_DIR, REPO_ROOT
from backend.decision_engine.synth.fingerprint import canonical_tables_fingerprint
from backend.decision_engine.synth.generator import generate

# Dedicated, reproducible demo ledger for the committed marts (gitignored runtime dir).
DEFAULT_MARTS_DB: Path = DATA_DIR / "audit" / "demo_marts.db"


def _seed_if_empty(store: DurableDecisionStore) -> dict | None:
    """Record the current (active-profile) EXPECTED recommendation as an approved
    decision when the ledger is empty. Returns the seeded recommendation provenance."""
    if store.all_decisions():
        return None
    rec = build_recommendation("expected")
    store.decide(rec, "approve", approver="demo",
                 notes=f"seeded for marts export ({C.DATASET_PROFILE} profile)")
    return {"scenario_id": rec.scenario_id, "rec_id": rec.rec_id, "run_id": RUN_ID,
            "data_fingerprint": rec.data_fingerprint, "engine_version": rec.engine_version,
            "config_fingerprint": rec.config_fingerprint, "feasible": rec.feasible,
            "policy_mode": rec.policy_mode, "decided_at": rec.generated_at}


def _write_manifest(out_dir: Path, store: DurableDecisionStore, seeded: dict | None) -> Path:
    decisions = store.all_decisions()
    head = decisions[-1] if decisions else None
    manifest = {
        "dataset_profile": C.DATASET_PROFILE,
        "report_version": "stage4.5",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_decisions": len(decisions),
        "marts": list(MART_NAMES),
        # TWO fingerprints of the SAME profile, surfaced so the marts reconcile with the
        # model report (which are otherwise different hashes and look mismatched):
        #   panel_fingerprint     — the modeling panel the decision was computed on
        #                           (what the ledger / mart_decision.data_fingerprint stores)
        #   canonical_tables_...  — the report's headline data fingerprint (canonical tables)
        "panel_fingerprint": (head.data_fingerprint if head else None),
        "canonical_tables_fingerprint": canonical_tables_fingerprint(generate().tables),
        "engine_version": (head.engine_version if head else None),
        "config_fingerprint": (head.config_fingerprint if head else None),
        "head_scenario_id": (head.scenario_id if head else None),
        "run_id": RUN_ID,
        "chain": store.verify_chain(),
        "seeded_this_run": seeded,
    }
    path = out_dir / "MANIFEST.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path


def _assert_report_identity(out_dir: Path) -> str | None:
    """Generation-time GATE (stronger than the manifest): if a model report exists,
    the marts' canonical-tables fingerprint MUST equal the report's headline fingerprint
    — otherwise the marts and the report describe different datasets. Raises on mismatch."""
    report_metrics = REPO_ROOT / "reports" / "model_performance" / "metrics.json"
    if not report_metrics.exists():
        return None
    report_fp = json.loads(report_metrics.read_text())["provenance"]["data_fingerprint"]
    marts_fp = canonical_tables_fingerprint(generate().tables)
    if report_fp != marts_fp:
        raise SystemExit(
            f"marts↔report identity gate FAILED: report canonical fingerprint {report_fp[:12]}… "
            f"!= marts canonical fingerprint {marts_fp[:12]}…. Regenerate the model report "
            "(`make model-report`) and the marts from the SAME active profile.")
    return report_fp


def main() -> None:
    db = os.environ.get("TC_AUDIT_DB", str(DEFAULT_MARTS_DB))
    store = DurableDecisionStore(db)             # opening the ledger creates the views
    seeded = _seed_if_empty(store)
    out_dir = REPO_ROOT / "reports" / "marts"
    matched_report_fp = _assert_report_identity(out_dir)
    written = store.export_marts(out_dir)
    manifest_path = _write_manifest(out_dir, store, seeded)
    if matched_report_fp:
        print(f"identity gate: marts ↔ model report fingerprints match "
              f"({matched_report_fp[:12]}…)")

    print(f"audit ledger: {db}  (profile: {C.DATASET_PROFILE})")
    if seeded:
        print(f"seeded decision: {seeded['scenario_id']} "
              f"(feasible={seeded['feasible']}, fp={seeded['data_fingerprint'][:12]}…)")
    print("marts (Looker-ready views over the append-only ledger):")
    for name in MART_NAMES:
        print(f"  {name:<24s} {len(store.mart(name)):>6d} rows")
    print("written:")
    for path in [*written, manifest_path]:
        print(f"  {path}")


if __name__ == "__main__":
    main()
