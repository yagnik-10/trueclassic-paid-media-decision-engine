"""Pydantic request/response models for the Stage 1 API."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from backend.decision_engine.config import (
    BLENDED_ROAS_FLOOR,
    MOVEMENT_BOUND,
    NC_CPA_TARGET,
    PROSPECTING_MIN_SHARE,
)


class ConstraintParams(BaseModel):
    """Marketer-adjustable optimizer constraints (defaults = config policy).

    Bounded + finite so unsafe values (NaN/inf, negatives, extreme movement that
    would produce negative spend) are rejected with 422 before reaching the solver.
    """
    roas_floor: float = Field(default=BLENDED_ROAS_FLOOR, ge=1.0, le=10.0, allow_inf_nan=False)
    nc_cpa_target: float = Field(default=NC_CPA_TARGET, ge=5.0, le=200.0, allow_inf_nan=False)
    prospecting_min_share: float = Field(default=PROSPECTING_MIN_SHARE, ge=0.0, le=0.80, allow_inf_nan=False)
    movement_bound: float = Field(default=MOVEMENT_BOUND, ge=0.05, le=0.40, allow_inf_nan=False)
    # growth = deploy full budget; efficiency_first = allow an explicit reserve line
    reserve_mode: Literal["growth", "efficiency_first"] = "growth"
    # S4.3 sensitivity what-ifs: segment → coefficient override (merged onto registry)
    calibration_overrides: dict[str, float] = Field(default_factory=dict)


class CampaignLine(BaseModel):
    campaign_id: str
    campaign_name: str
    platform: str
    segment: str
    current_spend: float
    recommended_spend: float
    delta_pct: float
    marginal_roas: float = 0.0
    marginal_roas_downside: float = 0.0
    marginal_hurdle: float = 0.0   # THIS campaign's break-even hurdle (1/SKU margin × safety)
    current_revenue: float = 0.0      # local response params (saturation/marginal curves)
    response_slope: float = 0.0
    response_quad: float = 0.0
    forecast_p10: float = 0.0          # S4.2 conformal-CALIBRATED band
    forecast_p50: float = 0.0
    forecast_p90: float = 0.0
    forecast_p10_raw: float = 0.0      # raw (pre-calibration) band — transparency
    forecast_p90_raw: float = 0.0
    forecast_model: str = ""
    reason_codes: list[str]
    risk_flags: list[str]
    # S4.1 pacing / utilization (waste & underspend)
    daily_cap: float = 0.0
    current_utilization: float = 0.0
    recommended_utilization: float = 0.0
    pacing_flag: str = "healthy"   # scale_opportunity | capped_constrained | waste_risk | healthy
    # S4.3 platform vs calibrated (at current spend)
    incrementality: float = 1.0
    calibrated_roas_current: float = 0.0
    platform_roas_current: float = 0.0


class Kpis(BaseModel):
    # PRIMARY success metrics (D-041): contribution-margin ROAS (breaks even at 1.0×)
    # and net contribution $ after ad spend. CM ROAS uses the calibrated (incremental)
    # revenue lens; net_contribution = (cm_roas − 1) × deployed spend.
    cm_roas_current: float = 0.0
    cm_roas_projected: float = 0.0
    net_contribution_current: float = 0.0
    net_contribution_projected: float = 0.0
    # calibrated (incremental) gross ROAS — the ENFORCED floor / governance lens
    blended_roas_current: float
    blended_roas_projected: float
    # platform-reported — shown as context (the over-attribution gap); the
    # ENFORCED floor is the calibrated blended ROAS above (D-008)
    reported_roas_current: float = 0.0
    reported_roas_projected: float = 0.0
    total_current_spend: float
    total_recommended_spend: float
    reserve: float
    nc_cpa_projected: float = 0.0


class BindingItem(BaseModel):
    name: str
    status: str       # binding | slack | violated
    detail: str       # human-readable with exact margins


class CampaignBound(BaseModel):
    campaign_id: str
    limits: list[str]  # e.g. ["inventory_no_scale"], ["movement_up_cap"]
    detail: str


class SolverStatus(BaseModel):
    """SLSQP terminal status + multi-start evidence, surfaced so a plan's feasibility is
    kept DISTINCT from its solver convergence and (local) optimality (D-040). A status-8
    plan can be business_feasible and candidate_stable yet not local_optimality_converged;
    ``warning`` carries the human-readable note. NOTE: status 0 is only a LOCAL
    convergence certificate (the feasible set is not provably convex), so nothing here
    claims a global/"certified" optimum, and solver_qualified is ADVISORY — execution
    always requires human approval (M3)."""
    success: bool = True            # raw SLSQP res.success of the CHOSEN start
    status: int = 0                 # raw SLSQP terminal status (0 converged, 8 = pos. dir. deriv.)
    message: str = ""
    iterations: int = 0
    # decomposed signals (D-040 closure)
    business_feasible: bool = True
    solver_converged: bool = True   # did ANY start return normal (local) convergence (status 0)
    candidate_stable: bool = True   # ≥2 near-best feasible starts agree on allocation
    local_optimality_converged: bool = True  # a converged start REACHED the chosen objective (LOCAL)
    solver_qualified: bool = True   # advisory precondition; NEVER sufficient — approval still required
    improves_on_current: bool = True
    # multi-start audit trail
    n_starts: int = 1
    n_feasible_starts: int = 1
    n_near_best: int = 1
    chosen_start: str = "current"
    best_contribution: float = 0.0
    median_contribution: float = 0.0
    worst_contribution: float = 0.0          # the worst basin, reported separately
    near_best_alloc_spread: float = 0.0      # USD per-campaign max range among near-best
    near_best_alloc_tol: float = 0.0         # USD stability threshold actually applied
    current_allocation_contribution: float = 0.0
    warning: str = ""


class BindingReport(BaseModel):
    """Structured 'why this plan': active business constraints + per-campaign bounds."""
    portfolio: list[BindingItem] = Field(default_factory=list)
    per_campaign: list[CampaignBound] = Field(default_factory=list)
    solver: SolverStatus = Field(default_factory=SolverStatus)


class CalibrationRegistryEntry(BaseModel):
    registry_id: str
    segment: str
    coefficient: float
    source: str
    effective_start: str
    effective_end: str | None = None
    confidence: str
    scope: str
    is_synthetic: bool


class CalibrationRegistryResponse(BaseModel):
    entries: list[CalibrationRegistryEntry]
    note: str = ""


class CalibrationProvenanceRow(BaseModel):
    """Registry row as applied to this plan (may include sensitivity overrides)."""
    registry_id: str
    segment: str
    coefficient: float              # effective coefficient used by the engine
    approved_coefficient: float     # value in the approved registry
    source: str
    effective_start: str
    effective_end: str | None = None
    confidence: str
    scope: str
    is_synthetic: bool
    overridden: bool = False


class IntervalCalibration(BaseModel):
    """S4.2 conformal-interval-calibration summary (portfolio offset + measured coverage)."""
    method: str = ""
    offset: float = 0.0                          # level-normalized widening fraction
    target_coverage: float = 0.80
    n_calibration: int = 0
    calibration_coverage_raw: float = 0.0        # held-out coverage BEFORE calibration
    calibration_coverage_calibrated: float = 0.0  # ...AFTER (~= target by construction)


class Recommendation(BaseModel):
    rec_id: str
    run_id: str
    policy_mode: str
    generated_at: str
    # Lifecycle status reflected from the backend audit store, so a refreshed
    # page shows the true state (not just optimistic local UI state).
    # Deterministic content id of this exact (policy + constraints + data + config)
    # plan. Approval binds to this; editing constraints yields a new scenario_id.
    scenario_id: str = ""
    data_fingerprint: str = ""
    engine_version: str = ""
    config_fingerprint: str = ""
    effective_movement_bound: float = MOVEMENT_BOUND   # actual ± used (Conservative shrinks it)
    status: Literal["pending", "approved", "rejected"] = "pending"
    # Stage 3: a real optimizer result (False). Kept for truth-in-advertising.
    is_fixed_placeholder: bool = True
    engine: str = "fixed"            # "fixed" (Stage 1) | "slsqp_optimizer" (Stage 3)
    feasible: bool = True
    # 'conflicts' lists the UNMET soft constraints with their exact shortfalls. When
    # infeasible the allocation is a DIAGNOSTIC candidate (the clipped solver
    # iterate), not a proven closest-feasible plan. (Hard bounds — movement, caps,
    # inventory, marginal floor — are enforced directly and so never appear here.)
    conflicts: list[str] = Field(default_factory=list)
    marginal_scale_floor: float = 0.0
    # How the per-campaign revenue LEVEL is anchored: the selected BAU forecast's
    # forward-horizon P50 ÷ horizon (an average daily level). So Model A feeds the
    # optimizer; per-line forecast_model + forecast_p50 expose the source.
    level_anchor: str = ""
    constraints: ConstraintParams = Field(default_factory=ConstraintParams)
    lines: list[CampaignLine]
    kpis: Kpis
    # Positive "why this plan": which business constraints bind/slack and which
    # hard bound pins each campaign (movement / cap / inventory / below-hurdle).
    binding: BindingReport = Field(default_factory=BindingReport)
    calibration_registry: list[CalibrationProvenanceRow] = Field(default_factory=list)
    # S4.3 safety: a sensitivity scenario uses coefficients NOT in the approved
    # registry — it is a what-if and must never be approvable/executed.
    is_sensitivity_override: bool = False
    calibration_fingerprint: str = ""   # fingerprint of the APPROVED registry (base)
    effective_calibration_fingerprint: str = ""   # hash(approved registry + normalized overrides)
    interval_calibration: IntervalCalibration = Field(default_factory=IntervalCalibration)


class DecisionRequest(BaseModel):
    # The plan is identified by the scenario_id in the URL (an immutable stored
    # snapshot) — approval never re-solves the optimizer.
    action: Literal["approve", "reject"]
    approver: str = Field(min_length=1)
    notes: Optional[str] = None


class ExecutionEvent(BaseModel):
    event_id: str
    rec_id: str
    platform: str
    payload_hash: str
    status: str
    is_stub: bool
    created_at: str


class AuditChainStatus(BaseModel):
    """Integrity report for the append-only, hash-chained decision ledger (Stage 4.4)."""
    ok: bool
    count: int
    head_hash: str = ""
    broken_seq: Optional[int] = None


# --- Stage 2: ingestion & reconciliation ------------------------------------
class FeedStat(BaseModel):
    platform: str
    raw: int
    normalized: int
    quarantined: int


class DqIssue(BaseModel):
    issue_id: str
    issue_type: str
    severity: str
    entity_type: str
    entity_ref: str
    description: str
    resolution: str


class SkuResolutionItem(BaseModel):
    platform: str
    platform_product_id: str
    sku_id: Optional[str] = None
    status: str  # auto_matched | needs_approval | quarantined | approved
    confidence: float
    allowed_candidates: list[str] = Field(default_factory=list)


class IngestionSummary(BaseModel):
    feeds: list[FeedStat]
    canonical_fact_rows: int
    canonical_commerce_rows: int
    total_quarantined: int
    dq_issues: list[DqIssue]
    sku_resolutions: list[SkuResolutionItem]
    sku_resolution_summary: dict[str, int]


class SkuApprovalRequest(BaseModel):
    sku_id: str = Field(min_length=1)
    approver: str = Field(min_length=1)


class DecisionResponse(BaseModel):
    rec_id: str
    scenario_id: str = ""                      # the immutable snapshot that was decided
    policy: str = "expected"
    constraints: ConstraintParams = Field(default_factory=ConstraintParams)
    allocation: dict[str, float] = Field(default_factory=dict)  # campaign -> approved spend
    # full modeling/config provenance of the approved plan (audit completeness)
    data_fingerprint: str = ""
    engine_version: str = ""
    config_fingerprint: str = ""
    calibration_fingerprint: str = ""             # approved registry identity at decision time
    effective_calibration_fingerprint: str = ""   # approved registry + any overrides
    binding: BindingReport = Field(default_factory=BindingReport)  # 'why this plan' at decision
    action: Literal["approve", "reject"]      # the action that established the decision
    previous_status: Literal["pending"] = "pending"
    new_status: Literal["approved", "rejected"]
    status: Literal["approved", "rejected"]   # == new_status (current state)
    approver: str
    decided_at: str
    notes: Optional[str] = None
    execution_events: list[ExecutionEvent]
    idempotent_replay: bool = False
    # NOTE: a durable, append-only, multi-entry audit history is Stage 4. This is
    # the single decision record for the Stage 1 thin shell.
