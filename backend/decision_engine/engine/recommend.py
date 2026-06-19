"""Orchestrate the engine: data → residualized response → SLSQP → recommendation.

Produces the real, constraint-valid allocation that replaces the Stage 1 fixed
placeholder. All numeric decisions are deterministic; reason codes/risk flags are
derived from the recovered marginal economics, not hand-written.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache


from backend.decision_engine.config import HARD_FLOOR_SAFETY, MOVEMENT_BOUND
from backend.decision_engine.engine.bau_forecast import forecast
from backend.decision_engine.engine.data import load_engine_inputs
from backend.decision_engine.engine.optimizer import OptCampaign, optimize
from backend.decision_engine.engine.response import CampaignResponse, estimate
from backend.decision_engine.synth.generator import generate


@dataclass
class RecLine:
    campaign_id: str
    campaign_name: str
    platform: str
    segment: str
    current_spend: float
    recommended_spend: float
    delta_pct: float
    marginal_roas: float
    marginal_roas_downside: float
    current_revenue: float       # local response params for saturation/marginal charts
    response_slope: float
    response_quad: float
    reason_codes: list[str]
    risk_flags: list[str]


@dataclass
class EngineRecommendation:
    policy_mode: str
    feasible: bool
    conflicts: list[str]
    lines: list[RecLine]
    blended_roas_current: float            # calibrated (incremental) — decision lens
    blended_roas_projected: float
    platform_blended_roas_current: float   # platform-reported — the enforced headline KPI
    platform_blended_roas_projected: float
    total_current_spend: float
    total_recommended_spend: float
    reserve: float
    nc_cpa_projected: float
    marginal_scale_floor: float = 0.0   # economically-derived hard floor (for charts)
    bau_forecast: dict = field(default_factory=dict)  # filled by Stage-3 BAU module


def _nc_per_dollar(panel) -> dict[str, float]:
    """Observable new-customers-per-$ per campaign (Meta exposes none → estimated)."""
    have = panel.dropna(subset=["new_customers"])
    glob_nc_per_conv = (
        have["new_customers"].sum() / max(have["platform_reported_conversions"].sum(), 1e-9)
    )
    out: dict[str, float] = {}
    for cid, g in panel.groupby("campaign_id", sort=True):
        gv = g.dropna(subset=["new_customers"])
        spend = g["spend"].sum()
        if len(gv) and gv["new_customers"].sum() > 0:
            out[cid] = float(gv["new_customers"].sum() / max(gv["spend"].sum(), 1e-9))
        else:  # estimate from conversions × the global new-customer rate
            out[cid] = float(g["platform_reported_conversions"].sum() * glob_nc_per_conv
                             / max(spend, 1e-9))
    return out


def _reason_codes(c, resp: CampaignResponse, rec_spend: float, hard_floor: float,
                  inventory: bool) -> tuple[list[str], list[str]]:
    """Coherent reason codes — an increase below the marginal floor is labelled as
    constraint-driven, never 'room_to_scale'."""
    reasons, risks = [], []
    above_floor = resp.marginal_roas >= hard_floor
    reasons.append("marginal_above_floor" if above_floor else "saturated_low_marginal")
    moved_up = rec_spend > c["current_spend"] + 1.0
    moved_down = rec_spend < c["current_spend"] - 1.0
    if moved_down:
        reasons.append("pull_back")
    elif moved_up:
        reasons.append("room_to_scale" if above_floor else "constraint_driven_increase")
    else:
        reasons.append("hold")
    if c["is_prospecting"]:
        reasons.append("prospecting_support")
    if inventory:
        risks.append("inventory_no_scale")
    return reasons, risks


@lru_cache(maxsize=2)
def build_engine_recommendation(policy_mode: str = "expected") -> EngineRecommendation:
    inp = load_engine_inputs()
    panel = inp.panel
    responses = estimate(panel, inp.current_spend)

    masters = generate().tables
    dim_c = masters["dim_campaign"].set_index("campaign_id")
    dim_sku = masters["dim_sku"].set_index("sku_id")
    inv = masters["fact_inventory_snapshot"]
    stockout_skus = set(inv[inv["stockout_risk"]]["sku_id"])
    sku_of = panel.groupby("campaign_id")["sku_id"].first().to_dict()
    nc_pd = _nc_per_dollar(panel)
    hard_floor = (1.0 / float(dim_sku["contribution_margin_rate"].mean())) * HARD_FLOOR_SAFETY

    conservative = policy_mode == "conservative"
    camps: list[OptCampaign] = []
    meta: dict[str, dict] = {}
    for cid in sorted(responses):
        r = responses[cid]
        sku = sku_of[cid]
        margin = float(dim_sku.loc[sku, "contribution_margin_rate"])
        inventory = sku in stockout_skus
        # each campaign gates on ITS OWN break-even hurdle (1/its margin × safety)
        camp_floor = (1.0 / margin) * HARD_FLOOR_SAFETY
        # conservative mode shifts the response down to the downside marginal
        slope = r.marginal_roas_downside if conservative else r.slope
        resp = CampaignResponse(cid, r.segment, r.current_spend, r.current_revenue,
                                slope, r.marginal_roas_downside, slope, r.quad)
        camps.append(OptCampaign(
            campaign_id=cid, current_spend=r.current_spend,
            daily_cap=float(dim_c.loc[cid, "daily_cap"]), margin=margin,
            is_prospecting=bool(dim_c.loc[cid, "is_prospecting"]),
            inventory_constrained=inventory, nc_per_dollar=nc_pd[cid],
            incrementality=float(inp.calibration[r.segment]), marginal_now=slope,
            marginal_floor=camp_floor,
            revenue_fn=resp.incremental_revenue, marginal_fn=resp.marginal_at,
        ))
        meta[cid] = {"current_spend": r.current_spend, "is_prospecting": bool(dim_c.loc[cid, "is_prospecting"]),
                     "inventory": inventory, "name": str(dim_c.loc[cid, "campaign_name"]),
                     "platform": str(dim_c.loc[cid, "platform"]), "segment": r.segment,
                     "margin": margin, "floor": camp_floor}

    # Conservative: pessimistic (downside) response AND smaller, cautious steps
    # (±15%). When cautious movement can't reach the 4.0 floor it is reported as
    # infeasible — the plan's closest-feasible-with-shortfall behavior.
    movement = 0.15 if conservative else MOVEMENT_BOUND
    result = optimize(camps, movement=movement, reserve_allowed=False)

    lines: list[RecLine] = []
    total_cur = sum(r.current_spend for r in responses.values())
    rev_cur = sum(r.current_revenue for r in responses.values())
    plat_rev_cur = sum(r.current_revenue / float(inp.calibration[r.segment])
                       for r in responses.values())
    for cid in sorted(responses):
        r = responses[cid]
        m = meta[cid]
        rec = result.spend[cid]
        reasons, risks = _reason_codes(m, r, rec, m["floor"], m["inventory"])
        lines.append(RecLine(
            campaign_id=cid, campaign_name=m["name"], platform=m["platform"], segment=r.segment,
            current_spend=round(r.current_spend, 2), recommended_spend=round(rec, 2),
            delta_pct=round((rec / r.current_spend - 1.0) * 100, 1),
            marginal_roas=round(r.marginal_roas, 3),
            marginal_roas_downside=round(r.marginal_roas_downside, 3),
            current_revenue=round(r.current_revenue, 2),
            response_slope=round(r.slope, 5), response_quad=round(r.quad, 8),
            reason_codes=reasons, risk_flags=risks,
        ))

    fc = forecast(panel)
    bau = {cid: {"p10": f.p10, "p50": f.p50, "p90": f.p90, "model": f.model,
                 "xgb_mae": f.xgb_mae, "baseline_mae": f.baseline_mae}
           for cid, f in fc.items()}

    return EngineRecommendation(
        policy_mode=policy_mode, feasible=result.feasible, conflicts=result.conflicts,
        lines=lines, bau_forecast=bau,
        blended_roas_current=round(rev_cur / total_cur, 4) if total_cur else 0.0,
        blended_roas_projected=result.blended_roas,
        platform_blended_roas_current=round(plat_rev_cur / total_cur, 4) if total_cur else 0.0,
        platform_blended_roas_projected=result.platform_blended_roas,
        total_current_spend=round(total_cur, 2),
        total_recommended_spend=round(sum(result.spend.values()), 2),
        reserve=result.reserve, nc_cpa_projected=result.nc_cpa,
        marginal_scale_floor=round(hard_floor, 3),
    )
