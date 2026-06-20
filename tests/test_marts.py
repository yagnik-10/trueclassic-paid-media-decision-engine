"""Stage 4.5 — Looker-ready SQL marts over the durable audit ledger.

Asserts the marts are correct flattenings of the immutable decision rows: grains are
right, JSON-derived rollups reconcile to the line-level facts, and the provenance /
hash-chain mart matches the ledger exactly.
"""

from __future__ import annotations

import pytest

from backend.api.marts import MART_NAMES, marts_ddl
from backend.api.recommendation import build_recommendation
from backend.api.schemas import ConstraintParams
from backend.api.store import DurableDecisionStore


@pytest.fixture(scope="module")
def ledger():
    rec_a = build_recommendation()
    rec_b = build_recommendation(constraints=ConstraintParams(movement_bound=0.30))
    s = DurableDecisionStore(":memory:")
    s.decide(rec_a, "approve", "marketer", "ship")
    s.decide(rec_b, "reject", "analyst", None)
    return s, rec_a, rec_b


def test_marts_ddl_is_stable_and_covers_all_views():
    ddl = marts_ddl()
    assert marts_ddl() == ddl                       # deterministic
    for name in MART_NAMES:
        assert f"CREATE VIEW IF NOT EXISTS {name}" in ddl


def test_mart_decision_grain_and_rollups(ledger):
    s, rec_a, rec_b = ledger
    rows = {r["scenario_id"]: r for r in s.mart("mart_decision")}
    assert set(rows) == {rec_a.scenario_id, rec_b.scenario_id}

    a = rows[rec_a.scenario_id]
    assert a["status"] == "approved" and a["approver"] == "marketer"
    assert a["n_campaigns"] == len(rec_a.lines)
    assert a["total_recommended_spend"] == pytest.approx(
        sum(ln.recommended_spend for ln in rec_a.lines), rel=1e-9)
    # solver status surfaces through the JSON path
    assert a["solver_success"] == (1 if rec_a.binding.solver.success else 0)
    # base scenario has no calibration override -> not a sensitivity plan
    assert a["n_calibration_overrides"] == 0 and a["is_sensitivity_override"] == 0
    assert rows[rec_b.scenario_id]["status"] == "rejected"


def test_mart_decision_line_reconciles_to_decision(ledger):
    s, rec_a, _ = ledger
    lines = [r for r in s.mart("mart_decision_line") if r["scenario_id"] == rec_a.scenario_id]
    assert {ln["campaign_id"] for ln in lines} == {ln.campaign_id for ln in rec_a.lines}
    # line spend sums back to the decision total, and shares sum to 1
    total = sum(ln["recommended_spend"] for ln in lines)
    assert total == pytest.approx(sum(ln.recommended_spend for ln in rec_a.lines), rel=1e-9)
    assert sum(ln["spend_share"] for ln in lines) == pytest.approx(1.0, abs=1e-9)


def test_mart_binding_constraint_matches_report(ledger):
    s, rec_a, _ = ledger
    rows = [r for r in s.mart("mart_binding_constraint")
            if r["scenario_id"] == rec_a.scenario_id]
    assert {r["constraint_name"] for r in rows} == {b.name for b in rec_a.binding.portfolio}
    assert {r["constraint_status"] for r in rows} == {b.status for b in rec_a.binding.portfolio}


def test_mart_audit_chain_matches_ledger(ledger):
    s, _, _ = ledger
    chain = s.mart("mart_audit_chain")
    assert [r["seq"] for r in chain] == [1, 2]      # commit order
    # the head hash in the mart equals the verified chain head
    assert chain[-1]["row_hash"] == s.verify_chain()["head_hash"]
    assert all(r["config_fingerprint"] for r in chain)


def test_export_marts_writes_ddl_and_csv(tmp_path, ledger):
    s, _, _ = ledger
    written = s.export_marts(tmp_path)
    names = {p.name for p in written}
    assert "marts.sql" in names
    for view in MART_NAMES:
        assert f"{view}.csv" in names
    assert (tmp_path / "marts.sql").read_text().startswith("CREATE VIEW")
