"""Stage 1 API: recommendation seam + approve/reject audit."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import main
from backend.api.store import DecisionStore

REC_ID = "REC-OPT-0001"


@pytest.fixture
def client():
    # fresh in-memory audit store + SKU approvals per test
    from backend.api import ingestion_service

    main.store = DecisionStore()
    ingestion_service.reset_approvals()
    return TestClient(main.app)


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_recommendation_shape_and_directions(client):
    rec = client.get("/api/recommendation").json()
    assert rec["rec_id"] == REC_ID
    assert rec["status"] == "pending"            # fresh store
    assert rec["is_fixed_placeholder"] is False  # Stage 3: a real optimizer result
    assert rec["engine"] == "slsqp_optimizer" and rec["feasible"] is True
    lines = {ln["campaign_id"]: ln for ln in rec["lines"]}
    assert len(lines) == 7
    # the optimizer recovers the golden scenario from observable data
    assert lines["META_RETARGETING"]["recommended_spend"] < lines["META_RETARGETING"]["current_spend"]
    assert lines["GOOGLE_NONBRAND"]["recommended_spend"] > lines["GOOGLE_NONBRAND"]["current_spend"]
    # inventory-constrained campaign is flagged and not scaled up
    pmax = lines["GOOGLE_PMAX"]
    assert "inventory_no_scale" in pmax["risk_flags"]
    assert pmax["recommended_spend"] <= pmax["current_spend"]
    # the enforced headline (reported) ROAS clears the floor
    assert rec["kpis"]["reported_roas_projected"] >= 4.0


def test_approve_generates_stub_execution(client):
    r = client.post(f"/api/recommendation/{REC_ID}/decision",
                    json={"action": "approve", "approver": "marketer@tc"})
    assert r.status_code == 200
    body = r.json()
    assert body["action"] == "approve"
    assert body["previous_status"] == "pending"
    assert body["new_status"] == "approved" and body["status"] == "approved"
    assert body["execution_events"], "approval must emit stubbed execution events"
    assert all(e["is_stub"] for e in body["execution_events"])
    # the inventory-blocked PMax change is not executed
    assert all("PMAX" not in e["event_id"] for e in body["execution_events"])


def test_reject_records_no_execution(client):
    r = client.post(f"/api/recommendation/{REC_ID}/decision",
                    json={"action": "reject", "approver": "marketer@tc", "notes": "too aggressive"})
    body = r.json()
    assert body["action"] == "reject"
    assert body["new_status"] == "rejected" and body["status"] == "rejected"
    assert body["execution_events"] == []


def test_get_recommendation_reflects_decision_status(client):
    assert client.get("/api/recommendation").json()["status"] == "pending"
    client.post(f"/api/recommendation/{REC_ID}/decision",
                json={"action": "approve", "approver": "m"})
    # a refreshed GET now reports the lifecycle state from the audit store
    assert client.get("/api/recommendation").json()["status"] == "approved"


def test_rejected_recommendation_cannot_execute(client):
    client.post(f"/api/recommendation/{REC_ID}/decision",
                json={"action": "reject", "approver": "m"})
    audit = client.get(f"/api/recommendation/{REC_ID}/audit").json()
    assert audit["status"] == "rejected"
    assert audit["execution_events"] == []


def test_approval_is_idempotent(client):
    first = client.post(f"/api/recommendation/{REC_ID}/decision",
                        json={"action": "approve", "approver": "m"}).json()
    second = client.post(f"/api/recommendation/{REC_ID}/decision",
                         json={"action": "approve", "approver": "m"}).json()
    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True
    assert len(first["execution_events"]) == len(second["execution_events"])


def test_conflicting_decision_returns_409(client):
    client.post(f"/api/recommendation/{REC_ID}/decision",
                json={"action": "reject", "approver": "m"})
    r = client.post(f"/api/recommendation/{REC_ID}/decision",
                    json={"action": "approve", "approver": "m"})
    assert r.status_code == 409


def test_unknown_recommendation_404(client):
    r = client.post("/api/recommendation/REC-NOPE/decision",
                    json={"action": "approve", "approver": "m"})
    assert r.status_code == 404


def test_infeasible_recommendation_cannot_be_approved(client, monkeypatch):
    # an infeasible plan must never be approved/executed (but can still be rejected)
    base = main.build_recommendation()
    base.feasible = False
    base.conflicts = ["calibrated blended ROAS 3.9 < floor 4.0"]
    monkeypatch.setattr(main, "build_recommendation", lambda *a, **k: base)
    approve = client.post(f"/api/recommendation/{REC_ID}/decision",
                          json={"action": "approve", "approver": "m"})
    assert approve.status_code == 422
    reject = client.post(f"/api/recommendation/{REC_ID}/decision",
                         json={"action": "reject", "approver": "m"})
    assert reject.status_code == 200  # rejecting an infeasible plan is allowed


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
    # reflected in a subsequent summary
    s = client.get("/api/ingestion").json()
    assert s["sku_resolution_summary"].get("approved") == 1


def test_approve_sku_rejects_invalid_candidate(client):
    r = client.post("/api/sku-resolution/GG_TC-JOG-BLU/approve",
                    json={"sku_id": "TC-CREW-BLK", "approver": "m"})
    assert r.status_code == 400  # not in allowed candidates


def test_approve_auto_matched_is_rejected(client):
    r = client.post("/api/sku-resolution/FB_TC-CREW-BLK/approve",
                    json={"sku_id": "TC-CREW-BLK", "approver": "m"})
    assert r.status_code == 400
