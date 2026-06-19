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
    reason_codes: list[str]
    risk_flags: list[str]


class Kpis(BaseModel):
    blended_roas_current: float
    blended_roas_projected: float
    total_current_spend: float
    total_recommended_spend: float
    reserve: float


class Recommendation(BaseModel):
    rec_id: str
    run_id: str
    policy_mode: str
    generated_at: str
    # Lifecycle status reflected from the backend audit store, so a refreshed
    # page shows the true state (not just optimistic local UI state).
    status: Literal["pending", "approved", "rejected"] = "pending"
    # Stage 1 truth-in-advertising: this is a FIXED placeholder, not an optimizer result.
    is_fixed_placeholder: bool = True
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
