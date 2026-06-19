"""Observable-data tests: assert the scenario from the canonical tables alone.

Unlike test_business_invariants (which reads the analytic latent truth), these
derive everything from the observable canonical data a model would actually see.
"""

from __future__ import annotations

import pandas as pd

from backend.decision_engine.config import BLENDED_ROAS_FLOOR, LABEL_MATURITY_DAYS


def test_prospecting_caps_out_frequently(tables):
    fact, camp = tables["fact_ad_performance"], tables["dim_campaign"]
    cap = camp.set_index("campaign_id").loc["META_PROSPECTING", "daily_cap"]
    pr = fact[(fact["campaign_id"] == "META_PROSPECTING") & (~fact["is_duplicate"])]
    # spend sits within 5% of the daily cap on most days (early cap-out)
    near_cap = (pr["spend"] >= 0.95 * cap).mean()
    assert near_cap > 0.5


def test_platform_reported_blended_roas_above_calibrated(tables):
    fact = tables["fact_ad_performance"]
    f = fact[~fact["is_duplicate"]]
    cal = tables["calibration_registry"].set_index("segment")["coefficient"]
    spend = f["spend"].sum()
    platform_rev = f["platform_reported_revenue"].sum()
    calibrated_rev = (f["platform_reported_revenue"] * f["segment"].map(cal)).sum()
    platform_roas = platform_rev / spend
    calibrated_roas = calibrated_rev / spend
    # platform-reported clears the floor; calibrated is below it (the problem)
    assert platform_roas > BLENDED_ROAS_FLOOR
    assert calibrated_roas < platform_roas


def test_inventory_joins_cleanly_to_skus(tables):
    inv, sku = tables["fact_inventory_snapshot"], tables["dim_sku"]
    joined = inv.merge(sku, on="sku_id", how="left", indicator=True)
    assert (joined["_merge"] == "both").all()          # every inventory row maps to a SKU
    assert set(inv["sku_id"]) == set(sku["sku_id"])     # one snapshot per SKU


def test_duplicate_shares_natural_key_with_a_real_row(tables):
    fact = tables["fact_ad_performance"]
    key = ["campaign_id", "date"]
    dup = fact[fact["is_duplicate"]]
    assert len(dup) == 1
    # the duplicate's (campaign_id, date) also exists on a non-duplicate row
    non_dup_keys = set(map(tuple, fact[~fact["is_duplicate"]][key].values))
    assert tuple(dup[key].iloc[0]) in non_dup_keys


def test_dedup_on_natural_key_does_not_double_count_revenue(tables):
    fact = tables["fact_ad_performance"]
    with_dup = fact["platform_reported_revenue"].sum()
    deduped = fact.drop_duplicates(subset=["campaign_id", "date", "is_duplicate"])
    deduped = fact[~fact["is_duplicate"]]["platform_reported_revenue"].sum()
    assert with_dup > deduped  # the duplicate inflates the naive sum


def test_immature_labels_are_recent_or_planted(tables):
    fact = tables["fact_ad_performance"]
    immature = fact[~fact["label_mature"]]
    cutoff = fact["date"].max() - pd.Timedelta(days=LABEL_MATURITY_DAYS)
    natural = immature[immature["date"] > cutoff]
    planted = immature[immature["date"] <= cutoff]
    assert len(natural) > 0          # the natural maturity tail
    assert len(planted) == 4          # the planted mid-series immature rows
    assert (planted["campaign_id"] == "GOOGLE_NONBRAND").all()


def test_missing_extraction_dates_are_flagged_not_imputed(tables):
    fact = tables["fact_ad_performance"]
    miss = fact[fact["extraction_date"].isna()]
    assert len(miss) == 3
    assert (miss["platform"] == "google").all()
