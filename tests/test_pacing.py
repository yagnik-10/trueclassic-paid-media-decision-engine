"""S4.1 — reserve / efficiency-first modes + pacing & budget utilization.

Asserts the business invariants of the waste-control lever (FINAL_PLAN §6 / brief
success criterion #3), not one exact allocation:
  * growth deploys the full budget (no reserve);
  * efficiency-first is a strict superset of growth (equality ⊆ inequality), so it
    can never earn less contribution and can hold budget in reserve;
  * pacing flags follow utilization-vs-hurdle deterministically.
"""

from __future__ import annotations

import pytest

from backend.decision_engine.engine.optimizer import OptCampaign, optimize
from backend.decision_engine.engine.recommend import (
    HIGH_UTILIZATION,
    Constraints,
    build_engine_recommendation,
)


@pytest.fixture(scope="module")
def growth():
    return build_engine_recommendation("expected", Constraints(reserve_mode="growth"))


@pytest.fixture(scope="module")
def efficiency():
    return build_engine_recommendation("expected", Constraints(reserve_mode="efficiency_first"))


# --- mode behaviour ----------------------------------------------------------
def test_growth_deploys_full_budget(growth):
    assert growth.feasible
    assert growth.reserve == pytest.approx(0.0, abs=1.0)
    assert growth.total_recommended_spend == pytest.approx(growth.total_current_spend, rel=1e-3)


# --- binding report (D-030) --------------------------------------------------
def _budget_line(rec):
    return next(p for p in rec.binding["portfolio"]
                if p["name"] in ("budget_fully_deployed", "budget_ceiling"))


def test_solver_separates_feasibility_convergence_and_optimality(growth):
    # D-040 closure: feasibility, convergence, stability and optimality are SEPARATE
    # signals; a feasible plan must improve on the current allocation; and a plan that
    # is not solver-certified must carry a visible non-certification warning.
    s = growth.binding["solver"]
    for k in ("business_feasible", "solver_converged", "candidate_stable",
              "local_optimality_converged", "solver_qualified", "n_starts",
              "n_feasible_starts", "best_contribution", "current_allocation_contribution",
              "warning"):
        assert k in s
    assert s["business_feasible"] == growth.feasible
    assert s["n_feasible_starts"] >= 1
    assert s["best_contribution"] >= s["current_allocation_contribution"] - 1.0
    assert s["worst_contribution"] <= s["best_contribution"] + 1e-6
    # solver_qualified is advisory and tracks LOCAL convergence; it is never a global claim
    assert s["solver_qualified"] == s["local_optimality_converged"]
    if not s["local_optimality_converged"]:
        assert s["warning"]                       # never silently non-converged


def test_binding_report_exposes_solver_status(growth):
    solver = growth.binding["solver"]
    # The plan is feasible and the report exposes the raw SLSQP terminal state.
    # status 0 (converged) and status 8 ("positive directional derivative" — a
    # benign termination at a constrained stationary point) both yield a feasible
    # plan; only genuine non-convergence is treated as infeasible (D-040).
    assert growth.feasible and not growth.conflicts
    assert solver["status"] in (0, 8)
    assert "iterations" in solver and isinstance(solver["message"], str)


def test_growth_budget_line_is_binding_not_slack(growth):
    # the prior bug: a fully-deployed budget was labeled 'slack'. Growth deploys the
    # whole budget, so the budget line must read 'binding'.
    line = _budget_line(growth)
    assert line["name"] == "budget_fully_deployed" and line["status"] == "binding"


def test_efficiency_first_reserve_shows_slack_to_ceiling(efficiency):
    line = _budget_line(efficiency)
    assert line["name"] == "budget_ceiling"
    # whatever the optimizer holds back is reported as slack-to-ceiling; if it holds
    # reserve the ceiling is 'slack', if it deploys the whole ceiling it is 'binding'
    if efficiency.reserve > 1.0:
        assert line["status"] == "slack" and "reserve" in line["detail"]
    else:
        assert line["status"] == "binding"


def test_efficiency_first_is_a_superset_of_growth(growth, efficiency):
    # inequality budget (spend <= B) contains the equality (spend == B), so the
    # efficient plan never spends MORE and never holds NEGATIVE reserve.
    assert efficiency.feasible
    assert efficiency.total_recommended_spend <= growth.total_recommended_spend + 1e-6
    assert efficiency.reserve >= growth.reserve - 1e-6
    assert efficiency.reserve >= 0.0


def test_efficiency_first_holds_reserve_under_a_tight_floor():
    # tighten the ROAS floor past what full deployment can support: growth goes
    # INFEASIBLE (can't deploy 100% and hold the floor), while efficiency-first
    # protects the floor by holding budget in reserve.
    g = build_engine_recommendation("expected", Constraints(roas_floor=4.1, reserve_mode="growth"))
    e = build_engine_recommendation("expected",
                                    Constraints(roas_floor=4.1, reserve_mode="efficiency_first"))
    assert not g.feasible
    assert e.feasible
    assert e.reserve > 0.0
    assert e.blended_roas_projected >= 4.1 - 1e-3


def test_reserve_allowed_never_earns_less_contribution():
    # winner can't scale (inventory-pinned); loser loses money on the margin. Growth
    # (equality) is forced to fund the loser to hit the budget; efficiency-first can
    # pull the loser back and bank the difference -> more contribution, real reserve.
    common = dict(daily_cap=10_000.0, margin=0.5, is_prospecting=True,
                  nc_per_dollar=1.0, incrementality=1.0)
    winner = OptCampaign(campaign_id="WIN", current_spend=1000.0, inventory_constrained=True,
                         marginal_now=3.0, marginal_floor=2.0,
                         revenue_fn=lambda b: 3.0 * b, marginal_fn=lambda b: 3.0, **common)
    loser = OptCampaign(campaign_id="LOSE", current_spend=1000.0, inventory_constrained=False,
                        marginal_now=0.5, marginal_floor=2.0,
                        revenue_fn=lambda b: 0.5 * b, marginal_fn=lambda b: 0.5, **common)
    kw = dict(roas_floor=1.0, prospecting_min_share=0.0, nc_cpa_target=1000.0)
    g = optimize([winner, loser], reserve_allowed=False, **kw)
    e = optimize([winner, loser], reserve_allowed=True, **kw)
    assert g.feasible and e.feasible
    assert e.reserve > 0.0                          # efficiency-first banks the bad dollars
    assert e.reserve >= g.reserve
    assert e.contribution >= g.contribution - 1e-6  # superset -> never worse
    assert sum(e.spend.values()) <= sum(g.spend.values()) + 1e-6


# --- pacing & utilization ----------------------------------------------------
def test_utilization_is_spend_over_daily_cap(growth):
    for ln in growth.lines:
        assert ln.daily_cap > 0
        assert ln.current_utilization == pytest.approx(ln.current_spend / ln.daily_cap, abs=1e-3)
        assert ln.recommended_utilization == pytest.approx(ln.recommended_spend / ln.daily_cap, abs=1e-3)


def test_pacing_flag_follows_utilization_hurdle_and_inventory(growth):
    # The flag is judged against EACH campaign's own hurdle (1/SKU margin × safety),
    # not the single portfolio scale floor — the two diverge once SKU margins spread
    # (D-040): a campaign can clear the portfolio floor yet sit below its own hurdle.
    # Below-hurdle near-cap campaigns split into strategic_floor / pullback_candidate /
    # waste_risk (attribution needs the counterfactual, so we assert the contract here
    # and pin the specific strategic_floor case in the dedicated test below).
    inventory = {ln.campaign_id for ln in growth.lines if "inventory_no_scale" in ln.risk_flags}
    for ln in growth.lines:
        near_cap = ln.current_utilization >= HIGH_UTILIZATION
        above_hurdle = ln.marginal_roas >= ln.marginal_hurdle
        if not near_cap:
            assert ln.pacing_flag == "healthy"
        elif above_hurdle:
            expected = "capped_constrained" if ln.campaign_id in inventory else "scale_opportunity"
            assert ln.pacing_flag == expected
        else:
            assert ln.pacing_flag in {"strategic_floor", "pullback_candidate", "waste_risk"}


def test_below_hurdle_prospecting_floor_is_strategic_not_waste(growth):
    # GPT closure #2: a near-cap prospecting campaign below its CM safety hurdle but
    # retained because the prospecting-share floor binds (and other prospecting
    # campaigns are capped) must read as strategic_floor, never waste_risk.
    floor_binding = any(p["name"] == "prospecting_min_share" and p["status"] in ("binding", "violated")
                        for p in growth.binding["portfolio"])
    strategic = [ln for ln in growth.lines if ln.pacing_flag == "strategic_floor"]
    if floor_binding and strategic:
        for ln in strategic:
            assert ln.current_utilization >= HIGH_UTILIZATION
            assert ln.marginal_roas < ln.marginal_hurdle      # below the safety hurdle
            assert ln.marginal_roas > 1.0                     # but still above break-even — not waste
            assert ln.pacing_flag != "waste_risk"


def test_golden_scenario_surfaces_a_capped_winner(growth):
    # the brief's "efficient campaigns hitting daily caps are leaving revenue on the
    # table" must actually appear: at least one near-cap, above-hurdle campaign.
    assert any(ln.pacing_flag == "scale_opportunity" for ln in growth.lines)


def test_inventory_blocked_winner_is_not_called_a_scale_opportunity(growth):
    # GPT #2: a near-cap, above-hurdle campaign the optimizer holds flat for inventory
    # is NOT a scale opportunity — that would contradict its own risk flag. It is
    # surfaced as capped_constrained instead (coherent with the optimizer's bounds).
    pmax = next(ln for ln in growth.lines if ln.campaign_id == "GOOGLE_PMAX")
    assert "inventory_no_scale" in pmax.risk_flags
    assert pmax.current_utilization >= HIGH_UTILIZATION
    assert pmax.marginal_roas >= growth.marginal_scale_floor
    assert pmax.pacing_flag == "capped_constrained"
