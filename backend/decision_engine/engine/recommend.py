"""Orchestrate the engine: data → residualized response → SLSQP → recommendation.

Produces the real, constraint-valid allocation that replaces the Stage 1 fixed
placeholder. All numeric decisions are deterministic; reason codes/risk flags are
derived from the recovered marginal economics, not hand-written.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from functools import lru_cache


from backend.decision_engine.config import (
    BLENDED_ROAS_FLOOR,
    FORECAST_HORIZON_DAYS,
    MOVEMENT_BOUND,
    NC_CPA_TARGET,
    PROSPECTING_MIN_SHARE,
)
from backend.decision_engine.calibration.registry import load_registry, registry_fingerprint
from backend.decision_engine.engine.bau_forecast import forecast
from backend.decision_engine.engine.data import load_engine_inputs
from backend.decision_engine.engine.optimizer import OptCampaign, optimize
from backend.decision_engine.engine.response import CampaignResponse, estimate
from backend.decision_engine.synth.fingerprint import frame_fingerprint
from backend.decision_engine.synth.generator import generate

# 'stage3.5' = ONE shared frozen model-selector (engine/selection.py) drives both
# the live forecast and the eval report, so the UI and the report can never report
# different "selected models" (D-026). 'stage3.4' = the SELECTED BAU forecast
# (÷ horizon) is the response level anchor, so Model A feeds Model B/optimizer
# (M2→M3). 'stage3.3' = panel-derived data fingerprint + live config fingerprint.
ENGINE_VERSION = "stage3.5"

# How the optimizer's per-campaign revenue LEVEL is anchored (audit/provenance):
# the selected BAU model's forward-horizon P50 converted to an average daily level.
LEVEL_ANCHOR_SOURCE = "selected_bau_p50_over_horizon"

# The Conservative policy trims movement to 75% of the requested bound (this knob
# lives in the engine, not config.py, so it is folded into the config fingerprint).
CONSERVATIVE_MOVEMENT_FACTOR = 0.75

# Utilization (spend / daily_cap) at/above which a campaign is "near its cap": an
# efficient capped campaign is leaving revenue on the table; an inefficient one is
# burning its full budget. A display/derived threshold (NOT a scenario constant),
# so it stays out of config.py and the fingerprints.
HIGH_UTILIZATION = 0.90


@dataclass(frozen=True)
class EngineConfig:
    """Immutable snapshot of the FIXED policy/economics constants the engine runs
    under. Built ONCE per process from ``config.py`` (a config change takes effect
    only on restart). Both the optimizer's consumed floors/movement AND
    ``config_fingerprint()`` read from THIS object, so the fingerprint can never
    claim a config the engine isn't actually consuming (the prior bug: a live module
    re-read drifted from import-frozen constants). See D-030."""
    blended_roas_floor: float
    nc_cpa_target: float
    prospecting_min_share: float
    movement_bound: float
    hard_floor_safety: float
    conservative_z: float
    conservative_movement_factor: float
    label_maturity_days: int
    inventory_lead_time_days: int
    inventory_safety_days: int

    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]


@lru_cache(maxsize=1)
def engine_config() -> EngineConfig:
    """Process-lifetime config snapshot. ``cache_clear()`` simulates a restart."""
    from backend.decision_engine import config as C
    return EngineConfig(
        blended_roas_floor=C.BLENDED_ROAS_FLOOR, nc_cpa_target=C.NC_CPA_TARGET,
        prospecting_min_share=C.PROSPECTING_MIN_SHARE, movement_bound=C.MOVEMENT_BOUND,
        hard_floor_safety=C.HARD_FLOOR_SAFETY, conservative_z=C.CONSERVATIVE_Z,
        conservative_movement_factor=CONSERVATIVE_MOVEMENT_FACTOR,
        label_maturity_days=C.LABEL_MATURITY_DAYS,
        inventory_lead_time_days=C.INVENTORY_LEAD_TIME_DAYS,
        inventory_safety_days=C.INVENTORY_SAFETY_DAYS,
    )


def config_fingerprint() -> str:
    """Fingerprint of the IMMUTABLE config snapshot actually consumed by the engine.

    Folded into ``scenario_id`` so a config change cannot collide with an existing
    scenario, and checked at approval so a snapshot computed under a different config
    is rejected as stale. Because it shares the snapshot with the optimizer, the
    fingerprint and the consumed constants always move together (only on restart)."""
    return engine_config().fingerprint()


def _effective_calibration_fingerprint(overrides: tuple[tuple[str, float], ...]) -> str:
    """hash(APPROVED registry + normalized overrides). A registry revision or a
    different override set yields a distinct effective identity (D-030)."""
    payload = {"approved_registry": registry_fingerprint(),
               "overrides": sorted(overrides)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def engine_provenance() -> dict[str, str]:
    """Current (data, engine, config, approved-calibration) identity. Approval
    compares a snapshot's stored provenance to this to detect a stale plan (state
    changed since it was computed). The data fingerprint is the actual modeling
    panel; the config fingerprint is the immutable engine-config snapshot; the
    calibration fingerprint is the APPROVED registry (so a registry revision —
    including a provenance-only one with unchanged coefficients — makes older
    pending snapshots stale)."""
    return {"data_fingerprint": _context().data_fingerprint,
            "engine_version": ENGINE_VERSION, "config_fingerprint": config_fingerprint(),
            "calibration_fingerprint": registry_fingerprint()}


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
    # THIS campaign's own break-even hurdle = (1/its SKU margin)×safety. The pacing
    # flag is judged against this per-campaign hurdle, NOT the portfolio scale floor
    # (the two diverge once SKU margins spread — D-040).
    marginal_hurdle: float
    current_revenue: float       # local response params for saturation/marginal charts
    response_slope: float
    response_quad: float
    reason_codes: list[str]
    risk_flags: list[str]
    # S4.1 pacing/utilization (success criterion #3: waste & underspend)
    daily_cap: float = 0.0
    current_utilization: float = 0.0       # current_spend / daily_cap
    recommended_utilization: float = 0.0   # recommended_spend / daily_cap
    # scale_opportunity | capped_constrained | waste_risk | healthy
    pacing_flag: str = "healthy"
    # S4.3 platform vs calibrated sensitivity (at current spend)
    incrementality: float = 1.0
    calibrated_roas_current: float = 0.0
    platform_roas_current: float = 0.0
    # CM (contribution-margin) marginal economics — the PRIMARY decision lens (D-041).
    # CM units rescale the calibrated-ROAS marginal by this campaign's SKU margin, so
    # break-even is exactly 1.0× and the hurdle is a single safety multiple
    # (HARD_FLOOR_SAFETY) for EVERY campaign, regardless of margin spread:
    #     marginal_cm_roas   = contribution_margin_rate × marginal_roas
    #     marginal_cm_hurdle = margin × marginal_hurdle = HARD_FLOOR_SAFETY  (rec-level)
    contribution_margin_rate: float = 0.0
    marginal_cm_roas: float = 0.0
    marginal_cm_roas_downside: float = 0.0


@dataclass
class EngineRecommendation:
    policy_mode: str
    feasible: bool
    conflicts: list[str]
    lines: list[RecLine]
    # PRIMARY success metrics (D-041): contribution-margin ROAS + net contribution $.
    cm_roas_current: float                 # pre-ad contribution / spend (breaks even at 1.0×)
    cm_roas_projected: float
    net_contribution_current: float        # contribution after ad spend, $/day
    net_contribution_projected: float
    # Governance lens: calibrated (incremental) gross blended ROAS is the ENFORCED floor.
    blended_roas_current: float            # calibrated (incremental) — enforced-floor lens
    blended_roas_projected: float
    platform_blended_roas_current: float   # platform-reported — context (over-attribution gap)
    platform_blended_roas_projected: float
    total_current_spend: float
    total_recommended_spend: float
    reserve: float
    nc_cpa_projected: float
    marginal_scale_floor: float = 0.0   # economically-derived hard floor (for charts)
    # CM-unit decision thresholds (constant across campaigns — D-041 primary lens). The
    # hurdle is the config safety knob (HARD_FLOOR_SAFETY), NOT a hardcoded number.
    marginal_cm_hurdle: float = 0.0     # = HARD_FLOOR_SAFETY (CM units; break-even×safety)
    cm_break_even: float = 1.0          # CM ROAS break-even (contribution exactly covers spend)
    data_fingerprint: str = ""          # fingerprint of the actual modeling panel
    engine_version: str = ENGINE_VERSION
    config_fingerprint: str = ""        # live config fingerprint (set in build)
    effective_movement_bound: float = MOVEMENT_BOUND   # actual ± used (Conservative shrinks it)
    reserve_mode: str = "growth"                       # growth | efficiency_first (S4.1)
    calibration_overrides: tuple[tuple[str, float], ...] = ()  # S4.3 sensitivity what-ifs
    is_sensitivity_override: bool = False              # True iff any override active (not registry-approved)
    calibration_fingerprint: str = ""                  # fingerprint of the APPROVED registry (base)
    effective_calibration_fingerprint: str = ""        # hash(approved registry + normalized overrides)
    binding: dict = field(default_factory=dict)        # structured "why this plan"
    bau_forecast: dict = field(default_factory=dict)  # filled by Stage-3 BAU module
    level_anchor: str = LEVEL_ANCHOR_SOURCE           # how the revenue level is anchored (audit)
    calibration_registry: list = field(default_factory=list)  # provenance rows (S4.3)
    interval_calibration: dict = field(default_factory=dict)   # conformal summary (S4.2)


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


def _pacing_flag(util_cur: float, above_hurdle: bool, inventory: bool, *,
                 is_prospecting: bool = False, being_reduced: bool = False,
                 strategically_required: bool = False) -> str:
    """Per-campaign daily pacing diagnosis, reconciled with the optimizer's bounds AND
    the binding strategic constraints (D-040). Below-hurdle is no longer collapsed to a
    single ``waste_risk``: a campaign retained because a binding prospecting-share floor
    can't be met elsewhere is materially different from genuine waste.

    - ``scale_opportunity``  near cap, above its hurdle, free to scale (leaving profit).
    - ``capped_constrained`` near cap, above its hurdle, but inventory-blocked (e.g. PMax).
    - ``strategic_floor``    below its hurdle but RETAINED to satisfy a binding
      prospecting-share requirement that other prospecting campaigns cannot absorb —
      marginal CM ROAS is above break-even, just below the 1.05× safety hurdle. NOT waste.
    - ``pullback_candidate`` below its hurdle and the optimizer is already reducing it.
    - ``waste_risk``         near cap, below its hurdle, held without a strategic reason.
    - ``healthy``            comfortable headroom (utilization below the near-cap band).
    """
    if util_cur < HIGH_UTILIZATION:
        return "healthy"
    if above_hurdle:
        return "capped_constrained" if inventory else "scale_opportunity"
    if is_prospecting and strategically_required:
        return "strategic_floor"
    if being_reduced:
        return "pullback_candidate"
    return "waste_risk"


@dataclass(frozen=True)
class Constraints:
    """Marketer-adjustable optimizer constraints (defaults = config policy)."""
    roas_floor: float = BLENDED_ROAS_FLOOR
    nc_cpa_target: float = NC_CPA_TARGET
    prospecting_min_share: float = PROSPECTING_MIN_SHARE
    movement_bound: float = MOVEMENT_BOUND
    # "growth" deploys the full budget (clearest reallocation story); "efficiency_first"
    # lets the optimizer HOLD budget in reserve when the next dollar can't clear its
    # own contribution hurdle (the waste-control story — FINAL_PLAN §6).
    reserve_mode: str = "growth"
    # segment → coefficient overrides for sensitivity what-ifs (folded into scenario_id)
    calibration_overrides: tuple[tuple[str, float], ...] = ()
    # OPTIONAL portfolio CM-ROAS floor — OFF by default (0.0). Exposed for the read-only
    # Phase-4 policy sweep only; the enforced production floor stays the gross roas_floor.
    # Kept LAST so the positional Constraints(...) call in the API stays correct.
    cm_roas_floor: float = 0.0


@dataclass
class _Context:
    """Constraint-INDEPENDENT engine state (expensive; cached once)."""
    responses: dict
    bau: dict
    calibration: dict
    dim_c: object
    dim_sku: object
    stockout_skus: set
    sku_of: dict
    nc_pd: dict
    portfolio_floor: float
    data_fingerprint: str
    interval_calibration: dict = field(default_factory=dict)  # S4.2 conformal summary


@lru_cache(maxsize=1)
def _context() -> _Context:
    return _build_context(None)


def _build_context(calibration_overrides: dict[str, float] | None) -> _Context:
    inp = load_engine_inputs(calibration_overrides=calibration_overrides)
    panel = inp.panel
    responses = estimate(panel, inp.current_spend)
    masters = generate().tables
    dim_c = masters["dim_campaign"].set_index("campaign_id")
    dim_sku = masters["dim_sku"].set_index("sku_id")
    inv = masters["fact_inventory_snapshot"]
    fc, cal = forecast(panel)
    bau = {cid: {"p10": f.p10, "p50": f.p50, "p90": f.p90, "model": f.model,
                 # raw (pre-conformal) band kept for transparency next to the calibrated one
                 "p10_raw": f.p10_raw, "p90_raw": f.p90_raw,
                 # auditable shared-selector metadata (same policy as the report)
                 "selection_reason": f.selection.reason,
                 "xgb_wape": f.selection.xgb_wape, "baseline_wape": f.selection.baseline_wape,
                 "improvement_pct": f.selection.improvement_pct}
           for cid, f in fc.items()}
    interval_calibration = {
        "method": "conformalized_quantile_regression",
        "offset": cal.offset, "target_coverage": cal.target_coverage,
        "n_calibration": cal.n_calibration,
        "calibration_coverage_raw": cal.raw_coverage,
        "calibration_coverage_calibrated": cal.calibrated_coverage,
    }

    # --- M2 → M3: anchor the response LEVEL on the SELECTED BAU forecast --------
    # The response curve already has the plan's anchored-delta form
    #     ScenarioRevenue(b) = level + [R(b) − R(b_current)]   (delta = 0 at b_current).
    # Previously `level` was a trailing-14d daily mean, so the forecast never fed the
    # optimizer. We now set it to the SELECTED BAU model's forward-horizon P50 (the
    # 7-day total) converted to an AVERAGE DAILY level (÷ FORECAST_HORIZON_DAYS) — the
    # daily basis the optimizer's daily-spend objective/ROAS require (NOT the raw 7-day
    # total, which would inflate revenue ~Hx). Only the level moves; the response
    # slope/quad/downside (the spend-change delta) and the marginal at current spend are
    # untouched. For fallback campaigns BAU_p50/H == the trailing-14d daily mean by
    # construction (zero shift); XGBoost-promoted campaigns shift by the forecast gap.
    for cid, r in responses.items():
        r.current_revenue = round(bau[cid]["p50"] / FORECAST_HORIZON_DAYS, 2)

    return _Context(
        responses=responses, bau=bau, calibration=inp.calibration,
        dim_c=dim_c, dim_sku=dim_sku,
        stockout_skus=set(inv[inv["stockout_risk"]]["sku_id"]),
        sku_of=panel.groupby("campaign_id")["sku_id"].first().to_dict(),
        nc_pd=_nc_per_dollar(panel),
        portfolio_floor=(1.0 / float(dim_sku["contribution_margin_rate"].mean()))
        * engine_config().hard_floor_safety,
        # fingerprint the ACTUAL modeling panel (post-ingestion/dedup/feature-build),
        # so the data identity reflects the real model inputs — not a parallel
        # re-generation of the master tables.
        data_fingerprint=frame_fingerprint(panel),
        interval_calibration=interval_calibration,
    )


def build_engine_recommendation(policy_mode: str = "expected",
                                constraints: Constraints | None = None) -> EngineRecommendation:
    """Fast: reuses the cached context and re-solves only the SLSQP optimizer, so
    the marketer can adjust constraints and re-run live."""
    cons = constraints or Constraints()
    overrides = dict(cons.calibration_overrides) if cons.calibration_overrides else None
    # data_fingerprint = identity of the INGESTED canonical data (override-independent).
    # A calibration override is a decision PARAMETER (captured in scenario_id +
    # calibration_fingerprint + constraints), not new data — so a sensitivity scenario
    # must not read as "stale" against the live (base) data identity at decision time.
    base_data_fingerprint = _context().data_fingerprint
    ctx = _context() if not overrides else _build_context(overrides)
    responses = ctx.responses
    conservative = policy_mode == "conservative"
    reserve_allowed = cons.reserve_mode == "efficiency_first"

    camps: list[OptCampaign] = []
    meta: dict[str, dict] = {}
    for cid in sorted(responses):
        r = responses[cid]
        sku = ctx.sku_of[cid]
        margin = float(ctx.dim_sku.loc[sku, "contribution_margin_rate"])
        inventory = sku in ctx.stockout_skus
        camp_floor = (1.0 / margin) * engine_config().hard_floor_safety   # each campaign's own hurdle
        slope = r.marginal_roas_downside if conservative else r.slope
        resp = CampaignResponse(cid, r.segment, r.current_spend, r.current_revenue,
                                slope, r.marginal_roas_downside, slope, r.quad)
        camps.append(OptCampaign(
            campaign_id=cid, current_spend=r.current_spend,
            daily_cap=float(ctx.dim_c.loc[cid, "daily_cap"]), margin=margin,
            is_prospecting=bool(ctx.dim_c.loc[cid, "is_prospecting"]),
            inventory_constrained=inventory, nc_per_dollar=ctx.nc_pd[cid],
            incrementality=float(ctx.calibration[r.segment]), marginal_now=slope,
            marginal_floor=camp_floor,
            revenue_fn=resp.incremental_revenue, marginal_fn=resp.marginal_at,
        ))
        meta[cid] = {"current_spend": r.current_spend, "name": str(ctx.dim_c.loc[cid, "campaign_name"]),
                     "is_prospecting": bool(ctx.dim_c.loc[cid, "is_prospecting"]),
                     "platform": str(ctx.dim_c.loc[cid, "platform"]),
                     "inventory": inventory, "floor": camp_floor, "margin": margin,
                     "daily_cap": float(ctx.dim_c.loc[cid, "daily_cap"])}

    # Conservative: pessimistic (downside) response AND smaller, cautious steps
    # (75% of the chosen movement bound) — never more aggressive than Expected.
    movement = (cons.movement_bound * engine_config().conservative_movement_factor
                if conservative else cons.movement_bound)
    result = optimize(camps, roas_floor=cons.roas_floor, nc_cpa_target=cons.nc_cpa_target,
                      prospecting_min_share=cons.prospecting_min_share, movement=movement,
                      reserve_allowed=reserve_allowed, cm_roas_floor=cons.cm_roas_floor)

    # Counterfactual evidence for `strategic_floor` attribution (D-040): a below-hurdle
    # prospecting campaign is only "strategically required" if the prospecting-share
    # floor is binding AND the OTHER prospecting campaigns lack the upper-bound headroom
    # to absorb cutting this one. We reconstruct each campaign's optimizer upper bound
    # (movement/cap, pinned at current when inventory- or hurdle-blocked) to measure it.
    prospecting_floor_binding = any(
        p["name"] == "prospecting_min_share" and p["status"] in ("binding", "violated")
        for p in result.binding.get("portfolio", []))

    def _upper_bound(cid: str) -> float:
        cur, cap = meta[cid]["current_spend"], meta[cid]["daily_cap"]
        hi = min(cur * (1.0 + movement), cap)
        if meta[cid]["inventory"] or (responses[cid].marginal_roas < meta[cid]["floor"]):
            hi = cur                       # inventory- or hurdle-blocked: cannot scale up
        return hi

    prospecting_headroom = {
        cid: max(0.0, _upper_bound(cid) - result.spend[cid])
        for cid in responses if meta[cid]["is_prospecting"]}

    lines: list[RecLine] = []
    total_cur = sum(r.current_spend for r in responses.values())
    rev_cur = sum(r.current_revenue for r in responses.values())
    plat_rev_cur = sum(r.current_revenue / float(ctx.calibration[r.segment])
                       for r in responses.values())
    for cid in sorted(responses):
        r = responses[cid]
        m = meta[cid]
        rec = result.spend[cid]
        reasons, risks = _reason_codes(m, r, rec, m["floor"], m["inventory"])
        cap = m["daily_cap"]
        util_cur = r.current_spend / cap if cap else 0.0
        util_rec = rec / cap if cap else 0.0
        # waste/underspend (success #3) — coherent with the optimizer's OWN bounds, so
        # we never call a held-flat campaign a scale opportunity. NOTE: this is a DAILY
        # utilization signal (spend/cap); the synthetic feeds carry no intraday pacing,
        # so we do not claim "hit cap by noon"-style intraday behaviour.
        # Is cutting THIS prospecting campaign offsettable elsewhere within bounds? If
        # not (and the floor binds), it is strategically required, not waste.
        drop_i = max(0.0, rec - r.current_spend * (1.0 - movement))
        offset_avail = sum(h for j, h in prospecting_headroom.items() if j != cid)
        strategically_required = (prospecting_floor_binding and m["is_prospecting"]
                                  and offset_avail < drop_i - 1.0)
        pacing = _pacing_flag(
            util_cur, r.marginal_roas >= m["floor"], m["inventory"],
            is_prospecting=m["is_prospecting"],
            being_reduced=rec < r.current_spend - 1.0,
            strategically_required=strategically_required)
        incr = float(ctx.calibration[r.segment])
        cal_roas = r.current_revenue / r.current_spend if r.current_spend else 0.0
        margin = m["margin"]   # this campaign's SKU contribution-margin rate
        lines.append(RecLine(
            campaign_id=cid, campaign_name=m["name"], platform=m["platform"], segment=r.segment,
            current_spend=round(r.current_spend, 2), recommended_spend=round(rec, 2),
            delta_pct=round((rec / r.current_spend - 1.0) * 100, 1),
            marginal_roas=round(r.marginal_roas, 3),
            marginal_roas_downside=round(r.marginal_roas_downside, 3),
            marginal_hurdle=round(m["floor"], 3),
            current_revenue=round(r.current_revenue, 2),
            response_slope=round(r.slope, 5), response_quad=round(r.quad, 8),
            reason_codes=reasons, risk_flags=risks,
            daily_cap=round(cap, 2), current_utilization=round(util_cur, 4),
            recommended_utilization=round(util_rec, 4), pacing_flag=pacing,
            incrementality=round(incr, 4),
            calibrated_roas_current=round(cal_roas, 3),
            platform_roas_current=round(cal_roas / incr, 3) if incr else 0.0,
            contribution_margin_rate=round(margin, 4),
            marginal_cm_roas=round(margin * r.marginal_roas, 4),
            marginal_cm_roas_downside=round(margin * r.marginal_roas_downside, 4),
        ))

    return EngineRecommendation(
        policy_mode=policy_mode, feasible=result.feasible, conflicts=result.conflicts,
        lines=lines, bau_forecast=ctx.bau,
        cm_roas_current=result.current_cm_roas,
        cm_roas_projected=result.cm_roas,
        net_contribution_current=result.current_contribution,
        net_contribution_projected=result.contribution,
        blended_roas_current=round(rev_cur / total_cur, 4) if total_cur else 0.0,
        blended_roas_projected=result.blended_roas,
        platform_blended_roas_current=round(plat_rev_cur / total_cur, 4) if total_cur else 0.0,
        platform_blended_roas_projected=result.platform_blended_roas,
        total_current_spend=round(total_cur, 2),
        total_recommended_spend=round(sum(result.spend.values()), 2),
        reserve=result.reserve, nc_cpa_projected=result.nc_cpa,
        marginal_scale_floor=round(ctx.portfolio_floor, 3),
        marginal_cm_hurdle=round(engine_config().hard_floor_safety, 4), cm_break_even=1.0,
        data_fingerprint=base_data_fingerprint, engine_version=ENGINE_VERSION,
        config_fingerprint=config_fingerprint(),
        effective_movement_bound=round(movement, 4), reserve_mode=cons.reserve_mode,
        calibration_overrides=cons.calibration_overrides,
        is_sensitivity_override=bool(overrides),
        calibration_fingerprint=registry_fingerprint(),
        effective_calibration_fingerprint=_effective_calibration_fingerprint(cons.calibration_overrides),
        interval_calibration=ctx.interval_calibration,
        binding=result.binding, level_anchor=LEVEL_ANCHOR_SOURCE,
        calibration_registry=[
            {"registry_id": e.registry_id, "segment": e.segment,
             "coefficient": ctx.calibration[e.segment],
             "approved_coefficient": e.coefficient,
             "source": e.source, "effective_start": e.effective_start,
             "effective_end": e.effective_end, "confidence": e.confidence,
             "scope": e.scope, "is_synthetic": e.is_synthetic,
             "overridden": e.segment in (overrides or {})}
            for e in load_registry()
        ],
    )
