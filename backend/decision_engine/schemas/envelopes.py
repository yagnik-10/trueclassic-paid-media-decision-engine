"""Pydantic models for the *raw* platform API envelopes (pre-flattening).

These mirror the real shapes the Stage-2 adapters will consume:

* Meta Marketing API insights: a ``{"data": [...], "paging": {...}}`` envelope
  where numeric fields arrive as STRINGS and conversions live in an ``actions``
  list. (https://developers.facebook.com/docs/marketing-api/insights)
* Google Ads API searchStream: a ``{"results": [...]}`` envelope with each row
  nested into ``campaign`` / ``metrics`` / ``segments`` objects, money in micros.
* Shopify: the DTC source-of-record commerce outcomes.

Design notes for Stage 0:
* Fields that a planted defect intentionally nulls/omits are ``Optional`` here so
  the structurally-valid-but-incomplete record still parses; the data-quality
  layer (not the parser) flags it. Fields whose *shape* must always hold are
  required, so malformed nesting is rejected.
* Money is modelled as ``str`` for Meta and as micros for Google to force the
  adapters to normalize — exactly the planted ``cost_micros`` defect.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# =========================================================================
# Meta Marketing API — data/paging envelope
# =========================================================================
class MetaAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_type: str
    value: str  # Meta returns numeric values as strings


class MetaInsightRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_id: str
    campaign_name: str
    date_start: str
    date_stop: str
    # Numeric metrics are strings in the real API.
    spend: str
    impressions: str
    clicks: str
    # Conversions/revenue arrive inside lists keyed by action_type.
    actions: list[MetaAction] = Field(default_factory=list)
    action_values: list[MetaAction] = Field(default_factory=list)
    # Attribution setting echoed by the API, e.g. "7d_click,1d_view".
    attribution_setting: str
    # Date the export was pulled. A planted defect omits this on some rows.
    extraction_date: Optional[str] = None


class MetaPagingCursors(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before: Optional[str] = None
    after: Optional[str] = None


class MetaPaging(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cursors: MetaPagingCursors
    next: Optional[str] = None


class MetaInsightsEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: list[MetaInsightRecord]
    paging: MetaPaging


# =========================================================================
# Google Ads API — nested results envelope
# =========================================================================
class GoogleCampaign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    advertising_channel_type: str


class GoogleMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Money in micros (1_000_000 micros == 1 unit). Adapters must normalize.
    cost_micros: int
    impressions: int
    clicks: int
    conversions: float
    conversions_value: float
    # New-customer COUNT (Google's `metrics.new_customers`); null in the raw feed
    # on the planted null-new-customer rows.
    new_customers: Optional[float] = None


class GoogleSegments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # A planted defect omits this date on some rows (missing extraction/segment date).
    date: Optional[str] = None
    conversion_action_category: str


class GoogleAdsRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign: GoogleCampaign
    metrics: GoogleMetrics
    segments: GoogleSegments


class GoogleAdsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    results: list[GoogleAdsRow]
    field_mask: str
    next_page_token: Optional[str] = None


# =========================================================================
# Shopify — DTC commerce source of record
# =========================================================================
class ShopifyDailyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: str
    sku: str
    orders: int
    gross_revenue: float
    new_customer_revenue: Optional[float] = None  # planted null defect
    returning_customer_revenue: float


class ShopifyCommerceEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shop: str
    records: list[ShopifyDailyRecord]
