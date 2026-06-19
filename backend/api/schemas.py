"""Pydantic request/response models for the Stage 1 API."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


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
    current_revenue: float = 0.0      # local response params (saturation/marginal curves)
    response_slope: float = 0.0
    response_quad: float = 0.0
    forecast_p10: float = 0.0
    forecast_p50: float = 0.0
    forecast_p90: float = 0.0
    forecast_model: str = ""
    reason_codes: list[str]
    risk_flags: list[str]


class Kpis(BaseModel):
    # calibrated (incremental) — the decision lens
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


class Recommendation(BaseModel):
    rec_id: str
    run_id: str
    policy_mode: str
    generated_at: str
    # Lifecycle status reflected from the backend audit store, so a refreshed
    # page shows the true state (not just optimistic local UI state).
    status: Literal["pending", "approved", "rejected"] = "pending"
    # Stage 3: a real optimizer result (False). Kept for truth-in-advertising.
    is_fixed_placeholder: bool = True
    engine: str = "fixed"            # "fixed" (Stage 1) | "slsqp_optimizer" (Stage 3)
    feasible: bool = True
    conflicts: list[str] = Field(default_factory=list)
    marginal_scale_floor: float = 0.0
    lines: list[CampaignLine]
    kpis: Kpis


class DecisionRequest(BaseModel):
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
