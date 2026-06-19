"""Platform adapters: validated raw records -> canonical rows (+ quarantine).

Meta `data/paging` and Google nested `results` flatten into
`fact_ad_performance`; Shopify flattens into `fact_commerce_truth`. Missing-date
records cannot be placed on the timeline and are quarantined (flag, don't impute).
Campaign segment/SKU are enriched from the campaign reference (a real adapter
gets these from the account's campaign→product mapping).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from backend.decision_engine.config import MICROS_PER_UNIT
from backend.decision_engine.ingestion.validation import (
    QuarantinedRecord,
    ValidationResult,
    quarantine,
    validate_envelope_records,
)
from backend.decision_engine.schemas.canonical import (
    fact_ad_performance,
    fact_commerce_truth,
)
from backend.decision_engine.schemas.envelopes import (
    GoogleAdsRow,
    MetaInsightRecord,
    ShopifyDailyRecord,
)

_CANONICAL_WINDOW = {"meta": "7d_click_1d_view", "google": "data_driven"}
# Defaults for canonical fields not carried by a raw platform record at ingest:
_DEFAULT_LABEL_MATURE = True      # the label-maturity stage sets this later
_DEFAULT_IS_DUPLICATE = False     # deduplication is a later pipeline step

CampaignRef = dict[str, dict[str, str]]  # campaign_id -> {"segment":..., "sku_id":...}


@dataclass
class AdapterResult:
    platform: str
    canonical_rows: list[dict] = field(default_factory=list)
    quarantined: list[QuarantinedRecord] = field(default_factory=list)

    @property
    def n_rows(self) -> int:
        return len(self.canonical_rows)

    @property
    def n_quarantined(self) -> int:
        return len(self.quarantined)


def _action_value(items, action_type: str) -> float:
    for a in items:
        if a.action_type == action_type:
            return float(a.value)
    return 0.0


def normalize_meta_record(rec: MetaInsightRecord, ref: CampaignRef) -> dict:
    cr = ref.get(rec.campaign_id, {})
    return {
        "date": rec.date_start,
        "campaign_id": rec.campaign_id,
        "platform": "meta",
        "segment": cr.get("segment"),
        "sku_id": cr.get("sku_id"),
        "spend": float(rec.spend),                       # string -> float
        "impressions": int(rec.impressions),
        "clicks": int(rec.clicks),
        "platform_reported_revenue": _action_value(rec.action_values, "purchase"),
        "platform_reported_conversions": _action_value(rec.actions, "purchase"),
        "new_customers": None,                           # not exposed by Meta insights
        "attribution_window": rec.attribution_setting,
        "label_mature": _DEFAULT_LABEL_MATURE,
        "extraction_date": rec.extraction_date,
        "is_duplicate": _DEFAULT_IS_DUPLICATE,
    }


def normalize_google_record(rec: GoogleAdsRow, ref: CampaignRef) -> dict | None:
    """Returns None if the row has no usable date (caller quarantines it)."""
    if rec.segments.date is None:
        return None
    cr = ref.get(rec.campaign.id, {})
    return {
        "date": rec.segments.date,
        "campaign_id": rec.campaign.id,
        "platform": "google",
        "segment": cr.get("segment"),
        "sku_id": cr.get("sku_id"),
        "spend": rec.metrics.cost_micros / MICROS_PER_UNIT,   # micros -> currency
        "impressions": int(rec.metrics.impressions),
        "clicks": int(rec.metrics.clicks),
        "platform_reported_revenue": float(rec.metrics.conversions_value),
        "platform_reported_conversions": float(rec.metrics.conversions),
        "new_customers": rec.metrics.new_customers,
        "attribution_window": _CANONICAL_WINDOW["google"],
        "label_mature": _DEFAULT_LABEL_MATURE,
        # Google rows carry no pull timestamp; ingest_google backfills the
        # extraction date as the feed's latest metric date (the pull happened
        # on/after the last day of data).
        "extraction_date": None,
        "is_duplicate": _DEFAULT_IS_DUPLICATE,
    }


def normalize_shopify_record(rec: ShopifyDailyRecord) -> dict:
    return {
        "date": rec.date,
        "sku_id": rec.sku,
        "dtc_orders": int(rec.orders),
        "dtc_revenue": float(rec.gross_revenue),
        "new_customer_revenue": rec.new_customer_revenue,
        "returning_customer_revenue": float(rec.returning_customer_revenue),
    }


# --- envelope-level adapters -------------------------------------------------
def ingest_meta(payload: dict, ref: CampaignRef, as_of: str | None = None) -> AdapterResult:
    vr = validate_envelope_records(
        payload, outer_required_keys=("data", "paging"), records_key="data",
        record_model=MetaInsightRecord, platform="meta", key_field="campaign_id",
        as_of=as_of,
    )
    rows = [normalize_meta_record(r, ref) for r in vr.valid]
    return AdapterResult("meta", rows, list(vr.quarantined))


def ingest_google(payload: dict, ref: CampaignRef, as_of: str | None = None) -> AdapterResult:
    vr = validate_envelope_records(
        payload, outer_required_keys=("results", "field_mask"), records_key="results",
        record_model=GoogleAdsRow, platform="google", as_of=as_of,
    )
    rows: list[dict] = []
    quarantined = list(vr.quarantined)
    for src_index, rec in zip(vr.valid_indices, vr.valid):
        row = normalize_google_record(rec, ref)
        if row is None:
            quarantined.append(quarantine(
                "google", src_index, rec.campaign.id, "missing_extraction_date",
                [{"loc": ["segments", "date"], "type": "missing",
                  "msg": "no usable date; cannot place on timeline (not imputed)"}],
                rec.model_dump(), detected_at=as_of,
            ))
        else:
            rows.append(row)
    # backfill the feed-level pull date (latest metric date) as extraction_date
    if rows:
        pull_date = max(r["date"] for r in rows)
        for r in rows:
            r["extraction_date"] = pull_date
    return AdapterResult("google", rows, quarantined)


def ingest_shopify(payload: dict, as_of: str | None = None) -> ValidationResult:
    return validate_envelope_records(
        payload, outer_required_keys=("shop", "records"), records_key="records",
        record_model=ShopifyDailyRecord, platform="shopify", key_field="sku",
        as_of=as_of,
    )


# --- typed canonical frames --------------------------------------------------
def to_fact_dataframe(rows: list[dict]) -> pd.DataFrame:
    cols = list(fact_ad_performance.columns)
    df = pd.DataFrame(rows, columns=cols)
    df["date"] = pd.to_datetime(df["date"])
    df["extraction_date"] = pd.to_datetime(df["extraction_date"])
    for c in ("spend", "platform_reported_revenue",
              "platform_reported_conversions", "new_customers"):
        df[c] = df[c].astype("float64")
    for c in ("impressions", "clicks"):
        df[c] = df[c].astype("int64")
    for c in ("label_mature", "is_duplicate"):
        df[c] = df[c].astype("bool")
    for c in ("campaign_id", "platform", "segment", "sku_id", "attribution_window"):
        df[c] = df[c].astype("string")
    return df


def to_commerce_dataframe(rows: list[dict]) -> pd.DataFrame:
    cols = list(fact_commerce_truth.columns)
    df = pd.DataFrame(rows, columns=cols)
    df["date"] = pd.to_datetime(df["date"])
    for c in ("dtc_revenue", "new_customer_revenue", "returning_customer_revenue"):
        df[c] = df[c].astype("float64")
    df["dtc_orders"] = df["dtc_orders"].astype("int64")
    df["sku_id"] = df["sku_id"].astype("string")
    return df
