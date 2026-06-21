"""Build the API recommendation from the Stage 3 engine (SLSQP optimizer).

Replaces the Stage 1 fixed placeholder: numbers now come from the deterministic
forecast + residualized response + constrained optimizer (engine.recommend).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from backend.api.schemas import (
    BindingReport,
    CalibrationProvenanceRow,
    CampaignLine,
    ConstraintParams,
    IntervalCalibration,
    Kpis,
    Recommendation,
)
from backend.decision_engine.engine.recommend import Constraints, build_engine_recommendation

REC_ID = "REC-OPT-0001"
RUN_ID = "RUN-STAGE3-SLSQP"


def _scenario_id(policy: str, cp: ConstraintParams, data_fp: str,
                 version: str, config_fp: str, calibration_fp: str = "") -> str:
    """Deterministic content id of a plan: same inputs -> same id (immutable).

    Includes the CONFIG fingerprint so a policy/economics change cannot collide
    with an existing scenario id, and the APPROVED-registry calibration fingerprint
    so a registry revision (even a provenance-only one whose coefficients — and thus
    data_fingerprint — are unchanged) yields a new id rather than silently reusing an
    old plan's identity. Overrides already enter via ``cp`` (D-030)."""
    payload = {"policy": policy, "constraints": cp.model_dump(),
               "data_fingerprint": data_fp, "engine_version": version,
               "config_fingerprint": config_fp, "calibration_fingerprint": calibration_fp}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return f"SCN-{digest[:16]}"


def build_recommendation(policy_mode: str = "expected",
                         constraints: ConstraintParams | None = None) -> Recommendation:
    cp = constraints or ConstraintParams()
    cal_tuple = tuple(sorted((k, float(v)) for k, v in cp.calibration_overrides.items()))
    eng = build_engine_recommendation(
        policy_mode,
        Constraints(roas_floor=cp.roas_floor, nc_cpa_target=cp.nc_cpa_target,
                    prospecting_min_share=cp.prospecting_min_share,
                    movement_bound=cp.movement_bound, reserve_mode=cp.reserve_mode,
                    calibration_overrides=cal_tuple),
    )
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
            marginal_hurdle=ln.marginal_hurdle,
            current_revenue=ln.current_revenue, response_slope=ln.response_slope,
            response_quad=ln.response_quad,
            forecast_p10=f.get("p10", 0.0), forecast_p50=f.get("p50", 0.0),
            forecast_p90=f.get("p90", 0.0), forecast_model=f.get("model", ""),
            forecast_p10_raw=f.get("p10_raw", 0.0), forecast_p90_raw=f.get("p90_raw", 0.0),
            reason_codes=ln.reason_codes, risk_flags=ln.risk_flags,
            daily_cap=ln.daily_cap, current_utilization=ln.current_utilization,
            recommended_utilization=ln.recommended_utilization, pacing_flag=ln.pacing_flag,
            incrementality=ln.incrementality,
            calibrated_roas_current=ln.calibrated_roas_current,
            platform_roas_current=ln.platform_roas_current,
            contribution_margin_rate=ln.contribution_margin_rate,
            marginal_cm_roas=ln.marginal_cm_roas,
            marginal_cm_roas_downside=ln.marginal_cm_roas_downside,
        ))
    kpis = Kpis(
        cm_roas_current=eng.cm_roas_current,
        cm_roas_projected=eng.cm_roas_projected,
        net_contribution_current=eng.net_contribution_current,
        net_contribution_projected=eng.net_contribution_projected,
        blended_roas_current=eng.blended_roas_current,
        blended_roas_projected=eng.blended_roas_projected,
        reported_roas_current=eng.platform_blended_roas_current,
        reported_roas_projected=eng.platform_blended_roas_projected,
        total_current_spend=eng.total_current_spend,
        total_recommended_spend=eng.total_recommended_spend,
        reserve=eng.reserve, nc_cpa_projected=eng.nc_cpa_projected,
    )
    scenario_id = _scenario_id(eng.policy_mode, cp, eng.data_fingerprint,
                               eng.engine_version, eng.config_fingerprint,
                               eng.calibration_fingerprint)
    return Recommendation(
        rec_id=REC_ID, run_id=RUN_ID, policy_mode=eng.policy_mode,
        scenario_id=scenario_id, data_fingerprint=eng.data_fingerprint,
        engine_version=eng.engine_version, config_fingerprint=eng.config_fingerprint,
        effective_movement_bound=eng.effective_movement_bound,
        generated_at=datetime.now(timezone.utc).isoformat(),
        is_fixed_placeholder=False, engine="slsqp_optimizer",
        feasible=eng.feasible, conflicts=eng.conflicts,
        marginal_scale_floor=eng.marginal_scale_floor, level_anchor=eng.level_anchor,
        marginal_cm_hurdle=eng.marginal_cm_hurdle, cm_break_even=eng.cm_break_even,
        constraints=cp,
        lines=lines, kpis=kpis,
        # eng.binding is {"portfolio": [...], "per_campaign": [...]} of plain dicts;
        # Pydantic coerces the nested dicts into BindingItem / CampaignBound.
        binding=BindingReport(**eng.binding) if eng.binding else BindingReport(),
        calibration_registry=[CalibrationProvenanceRow(**row) for row in eng.calibration_registry],
        is_sensitivity_override=eng.is_sensitivity_override,
        calibration_fingerprint=eng.calibration_fingerprint,
        effective_calibration_fingerprint=eng.effective_calibration_fingerprint,
        interval_calibration=IntervalCalibration(**eng.interval_calibration)
        if eng.interval_calibration else IntervalCalibration(),
    )
