"""Stage 3 — the engine recovers the golden scenario from OBSERVABLE data.

Asserts business invariants and tolerances (directions, constraint satisfaction),
never one exact allocation. The engine is deterministic.
"""

from __future__ import annotations

import pytest

from backend.decision_engine.config import (
    BLENDED_ROAS_FLOOR,
    HARD_FLOOR_SAFETY,
    PROSPECTING_MIN_SHARE,
)
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


# --- CM-unit marginal economics (D-041 primary lens) ------------------------
# CM units rescale the calibrated-ROAS marginal by each campaign's SKU margin so the
# decision threshold is a single safety multiple, no matter the margin spread. The UI
# renders these verbatim — the conversion lives here, not in React.
def test_marginal_cm_roas_is_margin_times_gross(rec):
    for ln in rec.lines:
        assert ln.marginal_cm_roas == pytest.approx(
            ln.contribution_margin_rate * ln.marginal_roas, abs=5e-3)
        assert ln.marginal_cm_roas_downside == pytest.approx(
            ln.contribution_margin_rate * ln.marginal_roas_downside, abs=5e-3)


def test_cm_thresholds_are_derived_constants(rec):
    # the hurdle is the config safety knob (NOT a hardcoded 1.05) and break-even is 1.0×
    assert rec.marginal_cm_hurdle == pytest.approx(HARD_FLOOR_SAFETY, abs=1e-9)
    assert rec.cm_break_even == pytest.approx(1.0, abs=1e-9)
    # per campaign, margin × gross-ROAS hurdle collapses to that single safety multiple
    for ln in rec.lines:
        assert ln.contribution_margin_rate * ln.marginal_hurdle == pytest.approx(
            rec.marginal_cm_hurdle, abs=5e-3)


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


def test_prospecting_floor_is_profile_aware():
    """D-037: the prospecting floor is a profile-aware policy minimum. Golden keeps
    0.33 (binds, feasible against its caps); realistic sits below its ~0.319
    cap-implied ceiling so the growth-mode plan is feasible. Guards the constant
    from a silent edit that would re-break realistic feasibility."""
    from backend.decision_engine import config as C
    assert C.prospecting_min_share("golden") == 0.33
    assert C.prospecting_min_share("realistic") == 0.30
    # realistic floor must stay strictly below its cap-implied ceiling (~0.319)
    assert C.prospecting_min_share("realistic") < 0.319
    # the suite is pinned to golden, so the module-level constant resolves to 0.33
    assert PROSPECTING_MIN_SHARE == C.prospecting_min_share("golden")


def test_movement_bounds_respected(rec):
    # The ±MOVEMENT_BOUND cap is enforced on the optimizer's *continuous* dollars;
    # recommended_spend is then rounded to 2 decimals, which can sit up to half a
    # cent past the bound at portfolio scale. Allow a 1-cent tolerance so the gate
    # tests the business constraint, not display rounding (D-039).
    for ln in rec.lines:
        assert abs(ln.recommended_spend - ln.current_spend) <= ln.current_spend * 0.20 + 0.01


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
        assert f["model"] in ("xgboost_quantile", "baseline_trailing_14d", "baseline_same_weekday")


# --- M2 → M3: the selected BAU forecast IS the optimizer's level anchor -------
def test_level_anchor_is_selected_bau_over_horizon():
    # the response curve's level == the SELECTED BAU model's forward-horizon P50
    # converted to an average DAILY level (÷ horizon), for every campaign.
    from backend.decision_engine.config import FORECAST_HORIZON_DAYS as H
    from backend.decision_engine.engine.recommend import _context

    ctx = _context()
    for cid, r in ctx.responses.items():
        assert abs(r.current_revenue - round(ctx.bau[cid]["p50"] / H, 2)) < 0.01


def test_no_7x_scale_error(rec):
    # if the raw 7-day BAU total leaked into the daily objective, blended ROAS
    # would be ~Hx too large (~26x). A sane daily band proves the ÷-horizon fix.
    assert 2.0 < rec.blended_roas_current < 8.0
    assert 2.0 < rec.blended_roas_projected < 8.0


def test_cm_roas_and_net_contribution_are_primary_kpis(rec):
    # D-041: CM ROAS + net contribution are exposed as portfolio headline metrics.
    # CM ROAS is margin-weighted, so it sits BELOW the gross blended ROAS but ABOVE
    # the 1.0× break-even (a profitable portfolio earns >$1 contribution per ad $).
    assert 1.0 < rec.cm_roas_current < rec.blended_roas_current
    assert 1.0 < rec.cm_roas_projected < rec.blended_roas_projected
    # net = (cm_roas − 1) × deployed spend, current and projected alike (identity).
    assert rec.net_contribution_current == pytest.approx(
        (rec.cm_roas_current - 1.0) * rec.total_current_spend, rel=1e-3)
    assert rec.net_contribution_projected == pytest.approx(
        (rec.cm_roas_projected - 1.0) * rec.total_recommended_spend, rel=1e-3)
    # the recommended plan does not destroy contribution vs the current allocation.
    assert rec.net_contribution_projected >= rec.net_contribution_current - 1.0


def test_response_delta_is_zero_at_current_spend():
    # scenario revenue at current spend == the anchor level (delta = 0 by design)
    from backend.decision_engine.engine.recommend import _context

    ctx = _context()
    for r in ctx.responses.values():
        assert abs(r.incremental_revenue(r.current_spend) - r.current_revenue) < 1e-6


def test_fallback_campaigns_anchor_on_baseline_xgb_on_xgb():
    # fallback campaigns' anchor == the trailing-14d daily mean (the baseline level);
    # xgboost-promoted campaigns are anchored on the (different) xgboost P50.
    from backend.decision_engine.engine.data import load_engine_inputs
    from backend.decision_engine.engine.recommend import _context
    from backend.decision_engine.engine.response import estimate

    inp = load_engine_inputs()
    trailing = estimate(inp.panel, inp.current_spend)   # trailing-14d anchored
    ctx = _context()
    saw_fallback = saw_xgb = False
    for cid, r in ctx.responses.items():
        model = ctx.bau[cid]["model"]
        if model == "xgboost_quantile":
            saw_xgb = True
        else:
            saw_fallback = True
            # trailing-14d fallbacks anchor on the trailing-14d daily mean; same-weekday
            # fallbacks anchor on a (different) baseline level, so only check trailing here
            if model == "baseline_trailing_14d":
                assert abs(r.current_revenue - round(trailing[cid].current_revenue, 2)) < 0.5
    assert saw_fallback and saw_xgb   # the scenario exercises both paths


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
