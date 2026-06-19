"""The single FIXED (placeholder) recommendation for the Stage 1 shell.

It is built deterministically from the Stage 0 canonical dataset (dim_campaign +
each campaign's current spend) plus a STATIC per-campaign delta fixture. The
deltas mirror the golden scenario's directional story but are NOT computed by an
optimizer — Stage 3 replaces this with the real SLSQP result. Displayed KPIs that
can be read straight from the observable canonical data are computed; the
projected ROAS is a labelled fixture.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from backend.api.schemas import CampaignLine, Kpis, Recommendation
from backend.decision_engine.synth import scenario as S
from backend.decision_engine.synth.generator import generate

REC_ID = "REC-FIXED-0001"
RUN_ID = "RUN-STAGE1-FIXED"
POLICY_MODE = "growth_plan"

# Static delta fixture: (delta_pct, reason_codes, risk_flags). Mirrors the golden
# scenario tensions; deliberately NOT an optimizer allocation.
FIXED_DELTAS: dict[str, tuple[float, list[str], list[str]]] = {
    "META_PROSPECTING": (0.0, ["prospecting_floor_binding"], []),
    "META_ADV_SHOPPING": (0.0, ["prospecting_support"], []),
    "META_RETARGETING": (-0.20, ["saturated_low_marginal", "over_attribution_flagged"], []),
    "GOOGLE_BRAND": (-0.20, ["saturated", "low_utilization"], []),
    "GOOGLE_NONBRAND": (0.20, ["room_to_scale", "high_marginal_in_support"], []),
    "GOOGLE_PMAX": (0.0, ["attractive_economics", "blocked_by_inventory"], ["inventory_no_scale"]),
    "GOOGLE_SHOPPING": (0.10, ["attractive_economics"], []),
}


@lru_cache(maxsize=1)
def _dataset():
    return generate()


def _blended_platform_roas() -> float:
    """Observable current blended ROAS (platform-reported), from the canonical fact."""
    fact = _dataset().tables["fact_ad_performance"]
    f = fact[~fact["is_duplicate"]]
    return round(float(f["platform_reported_revenue"].sum() / f["spend"].sum()), 4)


def build_recommendation() -> Recommendation:
    lines: list[CampaignLine] = []
    total_current = 0.0
    total_recommended = 0.0
    for c in S.CAMPAIGNS:
        delta, reasons, risks = FIXED_DELTAS[c.campaign_id]
        current = round(c.base_spend, 2)
        recommended = round(min(current * (1.0 + delta), c.daily_cap), 2)
        total_current += current
        total_recommended += recommended
        lines.append(
            CampaignLine(
                campaign_id=c.campaign_id,
                campaign_name=c.campaign_name,
                platform=c.platform,
                segment=c.segment,
                current_spend=current,
                recommended_spend=recommended,
                delta_pct=round((recommended / current - 1.0) * 100, 1),
                reason_codes=reasons,
                risk_flags=risks,
            )
        )

    current_roas = _blended_platform_roas()
    kpis = Kpis(
        blended_roas_current=current_roas,
        # labelled projection for the fixed plan (Stage 3 computes this for real)
        blended_roas_projected=round(current_roas + 0.25, 4),
        total_current_spend=round(total_current, 2),
        total_recommended_spend=round(total_recommended, 2),
        reserve=round(max(total_current - total_recommended, 0.0), 2),
    )
    return Recommendation(
        rec_id=REC_ID,
        run_id=RUN_ID,
        policy_mode=POLICY_MODE,
        generated_at=datetime.now(timezone.utc).isoformat(),
        is_fixed_placeholder=True,
        lines=lines,
        kpis=kpis,
    )
