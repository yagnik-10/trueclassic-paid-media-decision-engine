"""Stage 1 API: recommendation seam + approve/reject audit."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import main
from backend.api.store import DecisionStore

REC_ID = "REC-FIXED-0001"


@pytest.fixture
def client():
    # fresh in-memory audit store per test
    main.store = DecisionStore()
    return TestClient(main.app)


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_recommendation_shape_and_directions(client):
    rec = client.get("/api/recommendation").json()
    assert rec["rec_id"] == REC_ID
    assert rec["status"] == "pending"            # fresh store
    assert rec["is_fixed_placeholder"] is True
    lines = {ln["campaign_id"]: ln for ln in rec["lines"]}
    assert len(lines) == 7
    # directional fixture mirrors the golden scenario
    assert lines["META_RETARGETING"]["recommended_spend"] < lines["META_RETARGETING"]["current_spend"]
    assert lines["GOOGLE_NONBRAND"]["recommended_spend"] > lines["GOOGLE_NONBRAND"]["current_spend"]
    # inventory-constrained campaign is flagged and held flat
    pmax = lines["GOOGLE_PMAX"]
    assert "inventory_no_scale" in pmax["risk_flags"]
    assert pmax["recommended_spend"] == pmax["current_spend"]
    assert rec["kpis"]["blended_roas_current"] > 0


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
