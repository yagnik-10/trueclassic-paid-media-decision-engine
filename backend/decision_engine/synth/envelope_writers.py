"""Project canonical frames back into raw API-envelope-shaped JSON.

Stage-2 adapters will consume exactly these shapes. The structural defects live
here: Meta emits numeric strings and a duplicate record; Google emits money in
micros and omits ``segments.date`` on the missing-extraction-date rows.

Every emitted envelope is validated against the Pydantic models in
schemas/envelopes.py before return, so the generator can never ship a
structurally-malformed feed (only the *intended* content defects).
"""

from __future__ import annotations

import pandas as pd

from backend.decision_engine.config import MICROS_PER_UNIT
from backend.decision_engine.schemas.envelopes import (
    GoogleAdsResponse,
    MetaInsightsEnvelope,
    ShopifyCommerceEnvelope,
)
from backend.decision_engine.synth import scenario as S

_CHANNEL_TYPE = {
    "brand_search_troas": "SEARCH",
    "nonbrand_search_troas": "SEARCH",
    "pmax_troas": "PERFORMANCE_MAX",
    "shopping_troas": "SHOPPING",
}


def build_meta_envelope(fact: pd.DataFrame) -> dict:
    """Meta insights ``data/paging`` envelope (numeric fields as strings)."""
    meta = fact[fact["platform"] == "meta"].sort_values(["campaign_id", "date"])
    records = []
    for _, r in meta.iterrows():
        date_str = r["date"].strftime("%Y-%m-%d")
        rec = {
            "campaign_id": r["campaign_id"],
            "campaign_name": S.CAMPAIGN_BY_ID[r["campaign_id"]].campaign_name,
            "date_start": date_str,
            "date_stop": date_str,
            "spend": f"{r['spend']:.2f}",
            "impressions": str(int(r["impressions"])),
            "clicks": str(int(r["clicks"])),
            "actions": [
                {"action_type": "purchase", "value": f"{r['platform_reported_conversions']:.2f}"}
            ],
            "action_values": [
                {"action_type": "purchase", "value": f"{r['platform_reported_revenue']:.2f}"}
            ],
            "attribution_setting": r["attribution_window"],
            "extraction_date": (
                None if pd.isna(r["extraction_date"])
                else r["extraction_date"].strftime("%Y-%m-%d")
            ),
        }
        records.append(rec)
    envelope = {
        "data": records,
        "paging": {"cursors": {"before": "MAA", "after": "MjMA"}, "next": None},
    }
    MetaInsightsEnvelope.model_validate(envelope)  # structural gate
    return envelope


def build_google_envelope(fact: pd.DataFrame) -> dict:
    """Google Ads nested ``results`` envelope (money in micros)."""
    goog = fact[fact["platform"] == "google"].sort_values(["campaign_id", "date"])
    results = []
    for _, r in goog.iterrows():
        c = S.CAMPAIGN_BY_ID[r["campaign_id"]]
        # missing-extraction-date defect drops segments.date on those rows
        seg_date = None if pd.isna(r["extraction_date"]) else r["date"].strftime("%Y-%m-%d")
        results.append(
            {
                "campaign": {
                    "id": r["campaign_id"],
                    "name": c.campaign_name,
                    "advertising_channel_type": _CHANNEL_TYPE.get(c.objective, "SEARCH"),
                    # observed attribution model (the planted GOOGLE_BRAND mismatch
                    # rides through here, not silently normalized at the boundary)
                    "attribution_model": r["attribution_window"],
                },
                "metrics": {
                    "cost_micros": int(round(r["spend"] * MICROS_PER_UNIT)),
                    "impressions": int(r["impressions"]),
                    "clicks": int(r["clicks"]),
                    "conversions": float(round(r["platform_reported_conversions"], 2)),
                    "conversions_value": float(round(r["platform_reported_revenue"], 2)),
                    "new_customers": (
                        None if pd.isna(r["new_customers"]) else float(round(r["new_customers"], 2))
                    ),
                },
                "segments": {"date": seg_date, "conversion_action_category": "PURCHASE"},
            }
        )
    envelope = {
        "results": results,
        "field_mask": "campaign.id,metrics.cost_micros,segments.date",
        "next_page_token": None,
    }
    GoogleAdsResponse.model_validate(envelope)
    return envelope


def build_shopify_envelope(commerce: pd.DataFrame) -> dict:
    """Shopify DTC commerce source-of-record envelope."""
    records = []
    for _, r in commerce.sort_values(["sku_id", "date"]).iterrows():
        records.append(
            {
                "date": r["date"].strftime("%Y-%m-%d"),
                "sku": r["sku_id"],
                "orders": int(r["dtc_orders"]),
                "gross_revenue": float(round(r["dtc_revenue"], 2)),
                "new_customer_revenue": (
                    None if pd.isna(r["new_customer_revenue"])
                    else float(round(r["new_customer_revenue"], 2))
                ),
                "returning_customer_revenue": float(round(r["returning_customer_revenue"], 2)),
            }
        )
    envelope = {"shop": "trueclassic-synthetic.myshopify.com", "records": records}
    ShopifyCommerceEnvelope.model_validate(envelope)
    return envelope


def build_all_envelopes(fact: pd.DataFrame, commerce: pd.DataFrame) -> dict[str, dict]:
    return {
        "meta_insights": build_meta_envelope(fact),
        "google_ads": build_google_envelope(fact),
        "shopify_commerce": build_shopify_envelope(commerce),
    }
