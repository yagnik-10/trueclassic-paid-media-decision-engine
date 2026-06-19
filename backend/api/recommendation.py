"""Build the API recommendation from the Stage 3 engine (SLSQP optimizer).

Replaces the Stage 1 fixed placeholder: numbers now come from the deterministic
forecast + residualized response + constrained optimizer (engine.recommend).
"""

from __future__ import annotations

from datetime import datetime, timezone

from backend.api.schemas import CampaignLine, Kpis, Recommendation
from backend.decision_engine.engine.recommend import build_engine_recommendation

REC_ID = "REC-OPT-0001"
RUN_ID = "RUN-STAGE3-SLSQP"


def build_recommendation(policy_mode: str = "expected") -> Recommendation:
    eng = build_engine_recommendation(policy_mode)
    bau = eng.bau_forecast
    lines = []
    for ln in eng.lines:
        f = bau.get(ln.campaign_id, {})
        lines.append(CampaignLine(
            campaign_id=ln.campaign_id, campaign_name=ln.campaign_name,
            platform=ln.platform, segment=ln.segment,
            current_spend=ln.current_spend, recommended_spend=ln.recommended_spend,
            delta_pct=ln.delta_pct, marginal_roas=ln.marginal_roas,
            marginal_roas_downside=ln.marginal_roas_downside,
            current_revenue=ln.current_revenue, response_slope=ln.response_slope,
            response_quad=ln.response_quad,
            forecast_p10=f.get("p10", 0.0), forecast_p50=f.get("p50", 0.0),
            forecast_p90=f.get("p90", 0.0), forecast_model=f.get("model", ""),
            reason_codes=ln.reason_codes, risk_flags=ln.risk_flags,
        ))
    kpis = Kpis(
        blended_roas_current=eng.blended_roas_current,
        blended_roas_projected=eng.blended_roas_projected,
        reported_roas_current=eng.platform_blended_roas_current,
        reported_roas_projected=eng.platform_blended_roas_projected,
        total_current_spend=eng.total_current_spend,
        total_recommended_spend=eng.total_recommended_spend,
        reserve=eng.reserve, nc_cpa_projected=eng.nc_cpa_projected,
    )
    return Recommendation(
        rec_id=REC_ID, run_id=RUN_ID, policy_mode=eng.policy_mode,
        generated_at=datetime.now(timezone.utc).isoformat(),
        is_fixed_placeholder=False, engine="slsqp_optimizer",
        feasible=eng.feasible, conflicts=eng.conflicts,
        marginal_scale_floor=eng.marginal_scale_floor,
        lines=lines, kpis=kpis,
    )
