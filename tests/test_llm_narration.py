"""Stage 5 bounded narrator: deterministic fallback + grounded facts + endpoint.

These tests exercise the OFFLINE path only (no API key) — the narration must be a
self-contained, grounded, deterministic template so the demo never depends on a
live LLM. The live Anthropic path is intentionally not network-tested here.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import llm, main
from backend.api.store import DurableDecisionStore, SnapshotStore


@pytest.fixture
def client(monkeypatch):
    # force the fallback path regardless of the developer's real environment
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from backend.api import ingestion_service

    main.store = DurableDecisionStore(":memory:")
    main.snapshots = SnapshotStore()
    ingestion_service.reset_approvals()
    return TestClient(main.app)


def _snapshot(client):
    rec = client.get("/api/recommendation").json()
    return rec["scenario_id"], rec


def test_narration_endpoint_falls_back_without_key(client):
    sid, _ = _snapshot(client)
    body = client.get(f"/api/recommendation/{sid}/narration").json()
    assert body["source"] == "fallback"          # no key → deterministic template
    assert body["model"]                          # model string still reported
    assert 40 < len(body["text"]) < 800           # a real 2-3 sentence paragraph


def test_narration_is_grounded_in_snapshot_numbers(client):
    sid, rec = _snapshot(client)
    text = client.get(f"/api/recommendation/{sid}/narration").json()["text"]
    k = rec["kpis"]
    # the prose must quote the engine's OWN projected figure (numbers from app state)
    assert f"{k['blended_roas_projected']:.2f}\u00d7" in text
    # executive style: describes the move and ends with the approval line
    assert "approval" in text.lower()
    assert "shift" in text.lower() or "trim" in text.lower() or "scal" in text.lower()


def test_narration_unknown_scenario_404(client):
    assert client.get("/api/recommendation/SCN-deadbeef/narration").status_code == 404


def test_deterministic_narration_is_pure_and_stable(client):
    # same snapshot → identical narration (no RNG, no clock), and no latent-truth leak
    _, rec_json = _snapshot(client)
    rec = main.snapshots.get(rec_json["scenario_id"])
    a = llm.deterministic_narration(rec)
    b = llm.deterministic_narration(rec)
    assert a == b
    facts = llm.grounding_facts(rec)
    leaky = {"marginal_roas_truth", "incrementality_truth", "beta", "scenario_truth"}
    assert leaky.isdisjoint(facts.keys())


def test_narrate_returns_fallback_source_offline(client):
    rec = main.snapshots.get(_snapshot(client)[0])
    out = llm.narrate(rec)
    assert out.source == "fallback" and out.text


def test_deterministic_narration_passes_its_own_guardrail(client):
    # the fallback must ALWAYS clear the grounding check, or live rejection has no safe net
    rec = main.snapshots.get(_snapshot(client)[0])
    assert llm.is_grounded(llm.deterministic_narration(rec), rec) is True


def test_guardrail_rejects_fabricated_campaign(client):
    rec = main.snapshots.get(_snapshot(client)[0])
    # a platform-prefixed campaign that is NOT in the plan = hallucination → reject
    bad = ("The optimizer recommends to scale Google — Imaginary Quantum Ads aggressively "
           "and trim spend elsewhere while staying within policy guardrails.")
    assert llm.is_grounded(bad, rec) is False


def test_guardrail_rejects_overclaims_and_bad_length(client):
    rec = main.snapshots.get(_snapshot(client)[0])
    assert llm.is_grounded("This plan guarantees a risk-free profit.", rec) is False
    assert llm.is_grounded("This plan proves causal lift in revenue.", rec) is False
    assert llm.is_grounded("", rec) is False
    assert llm.is_grounded("Too short.", rec) is False
    assert llm.is_grounded("word " * 400, rec) is False


def test_guardrail_accepts_grounded_prose(client):
    rec = main.snapshots.get(_snapshot(client)[0])
    good = ("The optimizer recommends scaling Google — Nonbrand Search and Google — Shopping "
            "while trimming Meta — Dynamic Retargeting, lifting blended ROAS toward the floor "
            "and increasing net contribution within the binding budget and prospecting limits.")
    assert llm.is_grounded(good, rec) is True
