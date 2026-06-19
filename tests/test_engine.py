"""Stage 3 — the engine recovers the golden scenario from OBSERVABLE data.

Asserts business invariants and tolerances (directions, constraint satisfaction),
never one exact allocation. The engine is deterministic.
"""

from __future__ import annotations

import pytest

from backend.decision_engine.config import BLENDED_ROAS_FLOOR, PROSPECTING_MIN_SHARE
from backend.decision_engine.engine.recommend import build_engine_recommendation

_PROSPECTING = {"META_PROSPECTING", "META_ADV_SHOPPING"}


@pytest.fixture(scope="module")
def rec():
    return build_engine_recommendation("expected")


@pytest.fixture(scope="module")
def conservative():
    return build_engine_recommendation("conservative")


def _line(rec, cid):
    return next(ln for ln in rec.lines if ln.campaign_id == cid)


# --- recovered golden scenario ----------------------------------------------
def test_feasible(rec):
    assert rec.feasible and not rec.conflicts


def test_saturated_channels_pulled_back(rec):
    assert _line(rec, "META_RETARGETING").recommended_spend < _line(rec, "META_RETARGETING").current_spend
    assert _line(rec, "GOOGLE_BRAND").recommended_spend < _line(rec, "GOOGLE_BRAND").current_spend


def test_room_to_scale_increased(rec):
    nb = _line(rec, "GOOGLE_NONBRAND")
    assert nb.recommended_spend > nb.current_spend


def test_inventory_constrained_not_scaled_up(rec):
    pmax = _line(rec, "GOOGLE_PMAX")
    assert "inventory_no_scale" in pmax.risk_flags
    assert pmax.recommended_spend <= pmax.current_spend + 1e-6


def test_marginal_ordering_recovered(rec):
    # the room-to-scale channel's recovered marginal exceeds the saturated ones
    nb = _line(rec, "GOOGLE_NONBRAND").marginal_roas
    assert nb > _line(rec, "META_RETARGETING").marginal_roas
    assert nb > _line(rec, "GOOGLE_BRAND").marginal_roas


# --- constraints hold --------------------------------------------------------
def test_calibrated_roas_floor_enforced(rec):
    # the ENFORCED floor is the calibrated (incremental) blended ROAS (D-008)
    assert rec.feasible
    assert rec.blended_roas_projected >= BLENDED_ROAS_FLOOR - 1e-3
    assert rec.platform_blended_roas_projected >= BLENDED_ROAS_FLOOR  # reported also healthy


def test_no_below_floor_channel_is_increased(rec):
    for ln in rec.lines:
        if ln.marginal_roas < rec.marginal_scale_floor:
            assert ln.recommended_spend <= ln.current_spend + 1e-6


def test_conservative_no_more_aggressive(rec, conservative):
    exp_max = max(abs(ln.delta_pct) for ln in rec.lines)
    con_max = max(abs(ln.delta_pct) for ln in conservative.lines)
    assert con_max <= exp_max + 1e-6
    # ...and the two modes are not identical (the risk mode does something)
    assert any(abs(le.recommended_spend - lc.recommended_spend) > 1.0
               for le, lc in zip(rec.lines, conservative.lines))


def test_prospecting_floor_holds(rec):
    pros = sum(ln.recommended_spend for ln in rec.lines if ln.campaign_id in _PROSPECTING)
    assert pros / rec.total_recommended_spend >= PROSPECTING_MIN_SHARE - 1e-3


def test_movement_bounds_respected(rec):
    for ln in rec.lines:
        assert abs(ln.recommended_spend - ln.current_spend) <= ln.current_spend * 0.20 + 1e-6


def test_budget_conserved(rec):
    assert abs(rec.total_recommended_spend - rec.total_current_spend) <= max(1.0, rec.total_current_spend * 1e-3)


# --- uncertainty & policy ----------------------------------------------------
def test_conservative_uses_downside(rec, conservative):
    # per campaign, the downside marginal is <= the expected marginal
    for ln in rec.lines:
        assert _line(conservative, ln.campaign_id)
        assert ln.marginal_roas_downside <= ln.marginal_roas + 1e-6


def test_bau_forecast_quantiles_ordered(rec):
    assert rec.bau_forecast
    for f in rec.bau_forecast.values():
        assert f["p10"] <= f["p50"] <= f["p90"]
        assert f["model"] in ("xgboost_quantile", "baseline_trailing_14d")


def test_response_estimation_is_deterministic():
    from backend.decision_engine.engine.data import load_engine_inputs
    from backend.decision_engine.engine.response import estimate

    inp = load_engine_inputs()
    a = estimate(inp.panel, inp.current_spend)
    b = estimate(inp.panel, inp.current_spend)
    assert {k: v.marginal_roas for k, v in a.items()} == {k: v.marginal_roas for k, v in b.items()}


# --- infeasibility handling --------------------------------------------------
def test_optimizer_reports_constraint_conflict():
    from backend.decision_engine.engine.optimizer import OptCampaign, optimize

    # a single campaign whose ROAS (1.0) cannot meet the 4.0 reported floor
    c = OptCampaign(
        campaign_id="X", current_spend=1000.0, daily_cap=1200.0, margin=0.5,
        is_prospecting=True, inventory_constrained=False, nc_per_dollar=0.1,
        incrementality=1.0, marginal_now=1.0, marginal_floor=0.0,
        revenue_fn=lambda b: 1.0 * b, marginal_fn=lambda b: 1.0,
    )
    res = optimize([c])
    assert not res.feasible
    assert any("ROAS" in m for m in res.conflicts)  # explicit conflict, not an invalid plan
