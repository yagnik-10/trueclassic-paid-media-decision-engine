"""API: optimizer recommendation, adjustable constraints, snapshot approval, audit."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import main
from backend.api.store import DurableDecisionStore, SnapshotStore


@pytest.fixture
def client():
    # fresh snapshot store + an ISOLATED in-memory durable audit ledger per test
    from backend.api import ingestion_service

    main.store = DurableDecisionStore(":memory:")
    main.snapshots = SnapshotStore()
    ingestion_service.reset_approvals()
    return TestClient(main.app)


def _scenario(client, **q):
    return client.get("/api/recommendation", params=q or None).json()


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_recommendation_shape_and_directions(client):
    rec = _scenario(client)
    assert rec["scenario_id"].startswith("SCN-")
    assert rec["data_fingerprint"] and rec["engine_version"]
    assert rec["status"] == "pending"
    assert rec["is_fixed_placeholder"] is False
    assert rec["engine"] == "slsqp_optimizer" and rec["feasible"] is True
    lines = {ln["campaign_id"]: ln for ln in rec["lines"]}
    assert len(lines) == 7
    assert lines["META_RETARGETING"]["recommended_spend"] < lines["META_RETARGETING"]["current_spend"]
    assert lines["GOOGLE_NONBRAND"]["recommended_spend"] > lines["GOOGLE_NONBRAND"]["current_spend"]
    pmax = lines["GOOGLE_PMAX"]
    assert "inventory_no_scale" in pmax["risk_flags"]
    assert pmax["recommended_spend"] <= pmax["current_spend"]
    assert rec["kpis"]["blended_roas_projected"] >= 4.0 - 1e-6   # calibrated floor enforced


def test_primary_kpis_cm_roas_and_net_contribution_present(client):
    # D-041: CM ROAS + net contribution are first-class KPIs on the API surface,
    # and obey the net = (cm_roas − 1) × spend identity end-to-end.
    k = _scenario(client)["kpis"]
    for f in ("cm_roas_current", "cm_roas_projected",
              "net_contribution_current", "net_contribution_projected"):
        assert f in k
    assert 1.0 < k["cm_roas_current"] < k["blended_roas_current"]     # margin-weighted < gross
    assert 1.0 < k["cm_roas_projected"] < k["blended_roas_projected"]
    assert k["net_contribution_projected"] == pytest.approx(
        (k["cm_roas_projected"] - 1.0) * k["total_recommended_spend"], rel=1e-3)
    assert k["net_contribution_projected"] >= k["net_contribution_current"] - 1.0


def test_binding_report_positive_why_this_plan(client):
    # the structured "why this plan" report: portfolio constraints with statuses,
    # and the hard bound that pins the inventory-constrained campaign.
    rec = _scenario(client)
    binding = rec["binding"]
    portfolio = {b["name"]: b for b in binding["portfolio"]}
    assert {"budget_fully_deployed", "blended_roas_floor",
            "prospecting_min_share", "nc_cpa_target"} <= set(portfolio)
    assert all(b["status"] in ("binding", "slack", "violated") for b in binding["portfolio"])
    assert all(b["detail"] for b in binding["portfolio"])
    # full budget is deployed (the equality constraint in expected mode) → binding,
    # and no soft constraint is reported as violated in the feasible default plan
    assert portfolio["budget_fully_deployed"]["status"] == "binding"
    assert all(b["status"] != "violated" for b in binding["portfolio"])
    # PMax (inventory-constrained) is pinned no-scale and surfaced as an active bound
    bounds = {c["campaign_id"]: c["limits"] for c in binding["per_campaign"]}
    assert "inventory_no_scale" in bounds.get("GOOGLE_PMAX", [])


def test_approve_records_snapshot_and_stub_execution(client):
    scn = _scenario(client)["scenario_id"]
    r = client.post(f"/api/recommendation/{scn}/decision",
                    json={"action": "approve", "approver": "marketer@tc"})
    assert r.status_code == 200
    body = r.json()
    assert body["scenario_id"] == scn and body["status"] == "approved"
    assert body["new_status"] == "approved" and body["previous_status"] == "pending"
    assert body["allocation"] and body["constraints"]["roas_floor"] == 4.0  # audit records the plan
    assert body["execution_events"] and all(e["is_stub"] for e in body["execution_events"])
    assert all("PMAX" not in e["event_id"] for e in body["execution_events"])  # inventory-blocked


def test_execution_preview_matches_committed_events(client):
    # the pre-approval preview must be byte-identical (event_id + payload_hash) to what
    # approval commits to the ledger — the operator verifies what they approve.
    scn = _scenario(client)["scenario_id"]
    preview = client.get(f"/api/recommendation/{scn}/execution-preview").json()
    assert preview["is_stub"] and preview["status"] == "preview_no_live_write"
    assert preview["payloads"] and preview["total_changes"] > 0
    # preview records nothing — the scenario stays pending until an explicit decision
    assert _scenario(client)["status"] == "pending"
    committed = client.post(f"/api/recommendation/{scn}/decision",
                            json={"action": "approve", "approver": "m"}).json()["execution_events"]
    assert [(p["event_id"], p["payload_hash"]) for p in preview["payloads"]] == \
           [(e["event_id"], e["payload_hash"]) for e in committed]


def test_execution_preview_unknown_scenario_404(client):
    assert client.get("/api/recommendation/SCN-nope/execution-preview").status_code == 404


def test_decision_exposes_hash_chain_links(client):
    # the ledger row's chain links must be surfaced for the audit view, and the audit
    # log + verify endpoint must agree on the same head hash.
    scn = _scenario(client)["scenario_id"]
    d = client.post(f"/api/recommendation/{scn}/decision",
                    json={"action": "approve", "approver": "m"}).json()
    assert d["ledger_seq"] >= 1
    assert len(d["row_hash"]) == 64 and len(d["prev_hash"]) == 64
    log = client.get("/api/audit/log").json()
    assert log[-1]["row_hash"] == d["row_hash"]              # newest ledger row == this decision
    verify = client.get("/api/audit/verify").json()
    assert verify["ok"] and verify["head_hash"] == d["row_hash"]


def test_reject_records_no_execution(client):
    scn = _scenario(client)["scenario_id"]
    body = client.post(f"/api/recommendation/{scn}/decision",
                       json={"action": "reject", "approver": "m", "notes": "too aggressive"}).json()
    assert body["status"] == "rejected" and body["execution_events"] == []


def test_get_reflects_decision_status(client):
    rec = _scenario(client)
    assert rec["status"] == "pending"
    client.post(f"/api/recommendation/{rec['scenario_id']}/decision",
                json={"action": "approve", "approver": "m"})
    assert _scenario(client)["status"] == "approved"


def test_scenario_identity_is_isolated(client):
    # approving ONE scenario must not mark a DIFFERENT one approved (Codex blocker #1)
    default = _scenario(client)
    modified = _scenario(client, movement_bound=0.30)
    assert default["scenario_id"] != modified["scenario_id"]
    # 'modified' is now the active plan; approving 'default' is rejected (superseded)
    assert client.post(f"/api/recommendation/{default['scenario_id']}/decision",
                       json={"action": "approve", "approver": "m"}).status_code == 409
    assert _scenario(client, movement_bound=0.30)["status"] == "pending"  # not contaminated


def test_rejected_scenario_cannot_execute(client):
    scn = _scenario(client)["scenario_id"]
    client.post(f"/api/recommendation/{scn}/decision", json={"action": "reject", "approver": "m"})
    audit = client.get(f"/api/recommendation/{scn}/audit").json()
    assert audit["status"] == "rejected" and audit["execution_events"] == []


def test_approval_is_idempotent(client):
    scn = _scenario(client)["scenario_id"]
    first = client.post(f"/api/recommendation/{scn}/decision",
                        json={"action": "approve", "approver": "m"}).json()
    second = client.post(f"/api/recommendation/{scn}/decision",
                         json={"action": "approve", "approver": "m"}).json()
    assert first["idempotent_replay"] is False and second["idempotent_replay"] is True


def test_conflicting_decision_returns_409(client):
    scn = _scenario(client)["scenario_id"]
    client.post(f"/api/recommendation/{scn}/decision", json={"action": "reject", "approver": "m"})
    r = client.post(f"/api/recommendation/{scn}/decision", json={"action": "approve", "approver": "m"})
    assert r.status_code == 409


def test_unknown_or_stale_scenario_404(client):
    r = client.post("/api/recommendation/SCN-doesnotexist/decision",
                    json={"action": "approve", "approver": "m"})
    assert r.status_code == 404


# --- adjustable constraints + safety ----------------------------------------
def test_adjust_constraints_re_solves(client):
    default = _scenario(client)
    assert default["feasible"] is True and default["constraints"]["roas_floor"] == 4.0
    tight = _scenario(client, roas_floor=5.0)
    assert tight["constraints"]["roas_floor"] == 5.0 and tight["feasible"] is False
    assert any("ROAS" in c and "short" in c for c in tight["conflicts"])  # exact shortfall


def test_conservative_no_more_aggressive_via_api(client):
    exp = max(abs(ln["delta_pct"]) for ln in _scenario(client, policy="expected")["lines"])
    con = max(abs(ln["delta_pct"]) for ln in _scenario(client, policy="conservative")["lines"])
    assert con <= exp + 1e-6


def test_cannot_approve_infeasible_scenario(client):
    scn = _scenario(client, roas_floor=5.0)["scenario_id"]
    assert client.post(f"/api/recommendation/{scn}/decision",
                       json={"action": "approve", "approver": "m"}).status_code == 422
    # ...but it can be rejected
    assert client.post(f"/api/recommendation/{scn}/decision",
                       json={"action": "reject", "approver": "m"}).status_code == 200


def test_constraint_validation_rejects_unsafe_values(client):
    assert client.get("/api/recommendation?movement_bound=10").status_code == 422  # would be negative spend
    assert client.get("/api/recommendation?movement_bound=-0.2").status_code == 422
    assert client.get("/api/recommendation?roas_floor=-1").status_code == 422
    assert client.get("/api/recommendation?prospecting_min_share=33").status_code == 422
    assert client.get("/api/recommendation?policy=banana").status_code == 422


# --- review remediation: identity / staleness / provenance / messaging ------
def test_nc_cpa_conflict_text_is_numerically_true(client):
    # a fractional NC-CPA target must not be rounded in the conflict message
    # (the old ':.0f' produced false claims like "$5.73 > target $6").
    import re
    rec = _scenario(client, nc_cpa_target=5.5)
    nc = [c for c in rec["conflicts"] if "NC-CPA" in c]
    if nc:  # only assert when the NC-CPA constraint actually binds
        assert "target $5.50" in nc[0] and "$6" not in nc[0]
        m = re.search(r"NC-CPA \$([\d.]+) > target \$([\d.]+)", nc[0])
        assert float(m.group(1)) > float(m.group(2))  # the displayed claim is TRUE


def test_audit_records_full_provenance(client):
    rec = _scenario(client)
    body = client.post(f"/api/recommendation/{rec['scenario_id']}/decision",
                       json={"action": "approve", "approver": "m"}).json()
    assert body["data_fingerprint"] == rec["data_fingerprint"]
    assert body["engine_version"] == rec["engine_version"] and body["engine_version"]
    assert body["config_fingerprint"] == rec["config_fingerprint"] and body["config_fingerprint"]


def test_get_returns_stored_snapshot_without_drift(client):
    a = _scenario(client)
    b = _scenario(client)   # same inputs
    # returned == stored: identical id, generated_at, and allocation across GETs
    assert a["scenario_id"] == b["scenario_id"]
    assert a["generated_at"] == b["generated_at"]
    assert ([ln["recommended_spend"] for ln in a["lines"]]
            == [ln["recommended_spend"] for ln in b["lines"]])


def test_stale_scenario_rejected_when_engine_state_changes(client, monkeypatch):
    scn = _scenario(client)["scenario_id"]
    # simulate a config/data/model change AFTER the snapshot was computed
    monkeypatch.setattr(main, "engine_provenance", lambda: {
        "data_fingerprint": "CHANGED", "engine_version": "stage9.9",
        "config_fingerprint": "CHANGED", "calibration_fingerprint": "CHANGED"})
    r = client.post(f"/api/recommendation/{scn}/decision",
                    json={"action": "approve", "approver": "m"})
    assert r.status_code == 409 and "stale" in r.json()["detail"]


def test_stale_rejected_on_real_config_change(client, monkeypatch):
    # PRODUCTION mechanism under the immutable-config-snapshot contract (D-030): a
    # config change takes effect on RESTART (clear the engine_config + context
    # caches). After restart, the consumed floor AND the fingerprint move together,
    # so a snapshot computed under the old config is rejected as stale at approval.
    from backend.decision_engine import config as C
    from backend.decision_engine.engine import recommend

    scn = _scenario(client)["scenario_id"]
    monkeypatch.setattr(C, "HARD_FLOOR_SAFETY", 9.9)   # a genuine config change
    recommend.engine_config.cache_clear()              # simulate the required restart
    recommend._context.cache_clear()
    r = client.post(f"/api/recommendation/{scn}/decision",
                    json={"action": "approve", "approver": "m"})
    assert r.status_code == 409 and "stale" in r.json()["detail"]
    recommend.engine_config.cache_clear()
    recommend._context.cache_clear()


def test_runtime_config_mutation_does_not_falsely_reversion(client, monkeypatch):
    # D-030 regression (the Codex blocker): mutating config WITHOUT a restart must
    # change NEITHER the config fingerprint NOR the consumed floor — the engine and
    # the fingerprint share one immutable snapshot, so a plan can never be falsely
    # versioned (fingerprint claiming a config the optimizer isn't running).
    from backend.decision_engine import config as C

    rec = _scenario(client)
    fp_before, floor_before = rec["config_fingerprint"], rec["marginal_scale_floor"]
    monkeypatch.setattr(C, "HARD_FLOOR_SAFETY", 2.0)   # live mutation, NO restart
    rec2 = _scenario(client)
    assert rec2["config_fingerprint"] == fp_before     # fingerprint frozen...
    assert rec2["marginal_scale_floor"] == floor_before  # ...and so is the consumed floor
    # the original snapshot therefore stays approvable (not falsely stale)
    r = client.post(f"/api/recommendation/{rec['scenario_id']}/decision",
                    json={"action": "approve", "approver": "m"})
    assert r.status_code == 200


def test_config_change_yields_new_scenario_id(client, monkeypatch):
    from backend.decision_engine import config as C
    from backend.decision_engine.engine import recommend

    base = _scenario(client)["scenario_id"]
    monkeypatch.setattr(C, "BLENDED_ROAS_FLOOR", 3.9)
    recommend.engine_config.cache_clear()   # restart: snapshot + fingerprint rebuild
    recommend._context.cache_clear()
    changed = _scenario(client)["scenario_id"]
    assert base != changed       # config folds into the id -> no collision
    recommend.engine_config.cache_clear()
    recommend._context.cache_clear()
    recommend._context.cache_clear()


def test_superseded_scenario_rejected_but_rejectable(client):
    # supersession contract: only the most-recently-computed (active) plan is
    # approvable; an older one is rejected with 409 — but can still be REJECTED.
    default = _scenario(client)
    _scenario(client, movement_bound=0.30)            # newer plan becomes active
    approve = client.post(f"/api/recommendation/{default['scenario_id']}/decision",
                          json={"action": "approve", "approver": "m"})
    assert approve.status_code == 409 and "superseded" in approve.json()["detail"]
    assert client.post(f"/api/recommendation/{default['scenario_id']}/decision",
                       json={"action": "reject", "approver": "m"}).status_code == 200


def test_approved_plan_stays_idempotent_after_supersession(client):
    # D-030: an ALREADY-approved scenario must remain idempotently approvable even
    # after a newer scenario is computed (a recorded decision is immutable; the
    # terminal-state replay must precede the supersession guard).
    b = _scenario(client)["scenario_id"]
    first = client.post(f"/api/recommendation/{b}/decision",
                        json={"action": "approve", "approver": "m"})
    assert first.status_code == 200 and first.json()["idempotent_replay"] is False
    _scenario(client, movement_bound=0.30)            # C supersedes B
    retry = client.post(f"/api/recommendation/{b}/decision",
                        json={"action": "approve", "approver": "m"})
    assert retry.status_code == 200 and retry.json()["idempotent_replay"] is True
    # a CONFLICTING action on the terminal scenario still 409s
    assert client.post(f"/api/recommendation/{b}/decision",
                       json={"action": "reject", "approver": "m"}).status_code == 409


def test_recomputing_a_scenario_makes_it_active_again(client):
    a = _scenario(client)
    _scenario(client, movement_bound=0.30)            # supersedes a
    assert client.post(f"/api/recommendation/{a['scenario_id']}/decision",
                       json={"action": "approve", "approver": "m"}).status_code == 409
    _scenario(client)                                  # recompute a -> active again
    assert client.post(f"/api/recommendation/{a['scenario_id']}/decision",
                       json={"action": "approve", "approver": "m"}).status_code == 200


def test_reserve_mode_roundtrips_and_changes_scenario(client):
    # efficiency-first is its own scenario (folds into the id) and exposes the mode
    growth = _scenario(client, reserve_mode="growth")
    eff = _scenario(client, reserve_mode="efficiency_first")
    assert growth["constraints"]["reserve_mode"] == "growth"
    assert eff["constraints"]["reserve_mode"] == "efficiency_first"
    assert growth["scenario_id"] != eff["scenario_id"]
    assert eff["kpis"]["total_recommended_spend"] <= growth["kpis"]["total_recommended_spend"] + 1e-6


def test_efficiency_first_holds_reserve_under_tight_floor_via_api(client):
    g = _scenario(client, roas_floor=4.1, reserve_mode="growth")
    e = _scenario(client, roas_floor=4.1, reserve_mode="efficiency_first")
    assert g["feasible"] is False
    assert e["feasible"] is True and e["kpis"]["reserve"] > 0.0


def test_pacing_fields_present_and_consistent(client):
    rec = _scenario(client)
    assert any(ln["pacing_flag"] == "scale_opportunity" for ln in rec["lines"])
    for ln in rec["lines"]:
        assert ln["daily_cap"] > 0
        assert ln["pacing_flag"] in (
            "scale_opportunity", "capped_constrained", "strategic_floor",
            "pullback_candidate", "waste_risk", "healthy")
        assert ln["current_utilization"] == pytest.approx(
            ln["current_spend"] / ln["daily_cap"], abs=1e-3)


def test_invalid_reserve_mode_rejected(client):
    assert client.get("/api/recommendation?reserve_mode=hoard").status_code == 422


def test_calibration_registry_endpoint(client):
    body = client.get("/api/calibration/registry").json()
    assert len(body["entries"]) == 4
    assert all(e["is_synthetic"] for e in body["entries"])
    assert "synthetic" in body["note"].lower()


def test_calibration_override_roundtrips_and_changes_scenario(client):
    import json
    base = _scenario(client)
    ov = _scenario(client, calibration_overrides=json.dumps({"meta_retargeting": 0.25}))
    assert base["scenario_id"] != ov["scenario_id"]
    assert ov["constraints"]["calibration_overrides"]["meta_retargeting"] == 0.25
    row = next(r for r in ov["calibration_registry"] if r["segment"] == "meta_retargeting")
    assert row["overridden"] is True and row["coefficient"] == 0.25
    assert ov["lines"][0]["platform_roas_current"] > 0


def test_invalid_calibration_override_rejected(client):
    assert client.get('/api/recommendation?calibration_overrides={"bad_seg":0.5}').status_code == 422


def test_platform_calibrated_fields_on_lines(client):
    rec = _scenario(client)
    rt = next(ln for ln in rec["lines"] if ln["campaign_id"] == "META_RETARGETING")
    assert rt["platform_roas_current"] > rt["calibrated_roas_current"]
    assert 0 < rt["incrementality"] <= 1


def test_feasible_sensitivity_override_cannot_be_approved(client):
    # raising retargeting's coefficient keeps the plan FEASIBLE but it is still a
    # sensitivity what-if (non-registry-approved) → approval blocked (422), but the
    # plan is rejectable. (GPT safety pass: an overridden plan must not look approved.)
    import json
    rec = _scenario(client, calibration_overrides=json.dumps({"meta_retargeting": 0.45}))
    assert rec["feasible"] is True
    assert rec["is_sensitivity_override"] is True
    r = client.post(f"/api/recommendation/{rec['scenario_id']}/decision",
                    json={"action": "approve", "approver": "m"})
    assert r.status_code == 422 and "sensitivity" in r.json()["detail"]
    # ...but it can still be rejected
    assert client.post(f"/api/recommendation/{rec['scenario_id']}/decision",
                       json={"action": "reject", "approver": "m"}).status_code == 200


def test_infeasible_override_returns_422_on_approve(client):
    # the 0.35 → 0.25 case: lowering retargeting incrementality pushes calibrated
    # blended ROAS below the 4.0 floor → infeasible → approve 422.
    import json
    rec = _scenario(client, calibration_overrides=json.dumps({"meta_retargeting": 0.25}))
    assert rec["feasible"] is False
    assert any("ROAS" in c for c in rec["conflicts"])
    r = client.post(f"/api/recommendation/{rec['scenario_id']}/decision",
                    json={"action": "approve", "approver": "m"})
    assert r.status_code == 422


def test_default_plan_is_not_a_sensitivity_override(client):
    rec = _scenario(client)
    assert rec["is_sensitivity_override"] is False
    assert rec["calibration_fingerprint"]   # registry fingerprint pinned on the snapshot


def test_registry_revision_makes_old_plan_stale_and_new_id(client, monkeypatch):
    # D-030: an approved-registry revision (even provenance-only, coefficients
    # unchanged) must invalidate older pending snapshots and yield a new scenario id.
    from backend.decision_engine.engine import recommend

    scn = _scenario(client)["scenario_id"]
    monkeypatch.setattr(recommend, "registry_fingerprint", lambda: "REGISTRY-REVISION")
    r = client.post(f"/api/recommendation/{scn}/decision",
                    json={"action": "approve", "approver": "m"})
    assert r.status_code == 409 and "stale" in r.json()["detail"]
    assert _scenario(client)["scenario_id"] != scn   # rebinds to the revised registry


def test_effective_calibration_fingerprint_reflects_overrides(client):
    import json
    base = _scenario(client)
    ov = _scenario(client, calibration_overrides=json.dumps({"meta_retargeting": 0.45}))
    assert base["effective_calibration_fingerprint"]
    # overrides change the EFFECTIVE identity but not the APPROVED-registry base
    assert base["effective_calibration_fingerprint"] != ov["effective_calibration_fingerprint"]
    assert base["calibration_fingerprint"] == ov["calibration_fingerprint"]
    # audit carries both calibration identities (approve the LATEST plan to avoid supersession)
    latest = _scenario(client)
    body = client.post(f"/api/recommendation/{latest['scenario_id']}/decision",
                       json={"action": "approve", "approver": "m"}).json()
    assert body["calibration_fingerprint"] == latest["calibration_fingerprint"]
    assert body["effective_calibration_fingerprint"] == latest["effective_calibration_fingerprint"]


def test_effective_movement_bound_exposed_for_conservative(client):
    exp = _scenario(client, policy="expected", movement_bound=0.20)
    con = _scenario(client, policy="conservative", movement_bound=0.20)
    assert exp["effective_movement_bound"] == 0.20
    assert con["effective_movement_bound"] == 0.15   # 75% of the displayed bound


# --- Stage 2 ingestion endpoints --------------------------------------------
def test_ingestion_summary(client):
    s = client.get("/api/ingestion").json()
    assert {f["platform"] for f in s["feeds"]} == {"meta", "google", "shopify"}
    assert s["canonical_fact_rows"] > 0 and s["canonical_commerce_rows"] > 0
    assert s["dq_issues"]
    assert s["sku_resolution_summary"].get("needs_approval") == 1
    assert s["sku_resolution_summary"].get("quarantined") == 1


def test_approve_sku_mapping(client):
    r = client.post("/api/sku-resolution/GG_TC-JOG-BLU/approve",
                    json={"sku_id": "TC-JOG-BLK", "approver": "marketer@tc"})
    assert r.status_code == 200
    assert r.json()["status"] == "approved" and r.json()["sku_id"] == "TC-JOG-BLK"
    assert client.get("/api/ingestion").json()["sku_resolution_summary"].get("approved") == 1


def test_approve_sku_rejects_invalid_candidate(client):
    r = client.post("/api/sku-resolution/GG_TC-JOG-BLU/approve",
                    json={"sku_id": "TC-CREW-BLK", "approver": "m"})
    assert r.status_code == 400


def test_approve_auto_matched_is_rejected(client):
    r = client.post("/api/sku-resolution/FB_TC-CREW-BLK/approve",
                    json={"sku_id": "TC-CREW-BLK", "approver": "m"})
    assert r.status_code == 400


def test_admin_reset_clears_ledger_and_sku_approvals(client):
    # approve a plan + an SKU mapping so there is state to clear
    rec = _scenario(client)
    sid = rec["scenario_id"]
    assert client.post(f"/api/recommendation/{sid}/decision",
                       json={"action": "approve", "approver": "m"}).status_code == 200
    client.post("/api/sku-resolution/GG_TC-JOG-BLU/approve",
                json={"sku_id": "TC-JOG-BLK", "approver": "m"})
    assert len(client.get("/api/audit/log").json()) == 1

    out = client.post("/api/admin/reset").json()
    assert out["ok"] is True and out["decisions_cleared"] == 1

    # ledger is empty, the scenario reads pending again, and the chain is valid
    assert client.get("/api/audit/log").json() == []
    assert client.get("/api/audit/verify").json()["count"] == 0
    assert _scenario(client)["status"] == "pending"
    assert "approved" not in client.get("/api/ingestion").json()["sku_resolution_summary"]
    # a fresh approval works after reset (new chain from genesis)
    sid2 = _scenario(client)["scenario_id"]
    assert client.post(f"/api/recommendation/{sid2}/decision",
                       json={"action": "approve", "approver": "m"}).status_code == 200
