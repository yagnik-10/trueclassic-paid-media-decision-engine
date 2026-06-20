"""Raw API-envelope structure and the structural defects they carry."""

from __future__ import annotations

import pytest

from backend.decision_engine.config import MICROS_PER_UNIT
from backend.decision_engine.schemas.envelopes import (
    GoogleAdsResponse,
    MetaInsightsEnvelope,
    ShopifyCommerceEnvelope,
)
from backend.decision_engine.synth.envelope_writers import (
    build_google_envelope,
    build_meta_envelope,
    build_shopify_envelope,
)


@pytest.fixture(scope="module")
def envelopes(tables):
    fact, commerce = tables["fact_ad_performance"], tables["fact_commerce_truth"]
    return {
        "meta": build_meta_envelope(fact),
        "google": build_google_envelope(fact),
        "shopify": build_shopify_envelope(commerce),
    }


def test_meta_envelope_valid_and_string_typed(envelopes):
    env = MetaInsightsEnvelope.model_validate(envelopes["meta"])
    assert env.paging.cursors is not None
    rec = env.data[0]
    # Meta returns numerics as strings; conversions live in `actions`.
    assert isinstance(rec.spend, str) and float(rec.spend) >= 0
    assert any(a.action_type == "purchase" for a in rec.action_values)


def test_google_envelope_valid_and_nested(envelopes):
    env = GoogleAdsResponse.model_validate(envelopes["google"])
    row = env.results[0]
    assert row.campaign.id and row.metrics.cost_micros >= 0
    assert row.segments.conversion_action_category == "PURCHASE"


def test_google_cost_micros_normalizes_to_canonical_spend(envelopes, tables):
    fact = tables["fact_ad_performance"]
    goog = fact[(fact["platform"] == "google")].sort_values(["campaign_id", "date"])
    first = goog.iloc[0]
    row = envelopes["google"]["results"][0]
    assert abs(row["metrics"]["cost_micros"] / MICROS_PER_UNIT - first["spend"]) < 0.01


def test_missing_google_extraction_date_present_in_raw(envelopes):
    missing = [r for r in envelopes["google"]["results"] if r["segments"]["date"] is None]
    assert len(missing) == 3  # the planted missing-extraction-date rows


def test_google_carries_observed_attribution_model(envelopes):
    # the feed carries the OBSERVED attribution model per campaign (not normalized),
    # so the boundary preserves the planted GOOGLE_BRAND mismatch
    results = envelopes["google"]["results"]
    assert all("attribution_model" in r["campaign"] for r in results)
    models = {r["campaign"]["id"]: r["campaign"]["attribution_model"] for r in results}
    assert models["GOOGLE_BRAND"] == "last_click"          # the planted conflict
    others = {m for cid, m in models.items() if cid != "GOOGLE_BRAND"}
    assert others == {"data_driven"}                       # everyone else on policy


def test_duplicate_meta_record_present_in_raw(envelopes, tables):
    fact = tables["fact_ad_performance"]
    n_meta_rows = (fact["platform"] == "meta").sum()
    # the duplicate is emitted as an extra Meta record
    assert len(envelopes["meta"]["data"]) == n_meta_rows


def test_shopify_envelope_valid(envelopes):
    env = ShopifyCommerceEnvelope.model_validate(envelopes["shopify"])
    assert env.shop.endswith("myshopify.com")
    assert any(r.new_customer_revenue is None for r in env.records)  # planted null


def test_malformed_envelope_is_rejected():
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        # missing required `paging`
        MetaInsightsEnvelope.model_validate({"data": []})
    with pytest.raises(pydantic.ValidationError):
        # cost_micros must be int-like, nesting required
        GoogleAdsResponse.model_validate({"results": [{"metrics": {}}], "field_mask": "x"})
