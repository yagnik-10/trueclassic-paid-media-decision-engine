"""The golden business scenario, asserted as invariants & tolerance RANGES.

These encode FINAL_PLAN section 12. They assert *directions and ranges*, never
one exact optimizer allocation, so a Stage-3 optimizer has room to solve while
the scenario's tensions remain guaranteed. The decision hurdles are the
economically-derived values from :mod:`backend.decision_engine.economics`.
"""

from __future__ import annotations

import pandas as pd

from backend.decision_engine import economics as E
from backend.decision_engine.config import BLENDED_ROAS_FLOOR
from backend.decision_engine.synth import scenario as S

HARD_FLOOR = E.HARD_SCALE_FLOOR


def _truth(dataset):
    return dataset.scenario_truth.set_index("campaign_id")


# --- Per-campaign tensions ---------------------------------------------------
def test_meta_retargeting_high_platform_roas_low_marginal(dataset):
    t = _truth(dataset).loc["META_RETARGETING"]
    assert t["platform_avg_roas"] > 8.0           # looks strong on platform ROAS
    assert t["marginal_roas"] < HARD_FLOOR        # but should DECREASE


def test_google_brand_high_avg_roas_saturated_low_utilization(dataset):
    t = _truth(dataset).loc["GOOGLE_BRAND"]
    assert t["platform_avg_roas"] > 10.0
    assert t["marginal_roas"] < HARD_FLOOR            # saturated
    assert t["utilization"] < 0.40                    # low utilization


def test_google_nonbrand_has_room_to_scale(dataset):
    t = _truth(dataset).loc["GOOGLE_NONBRAND"]
    assert t["marginal_roas"] > HARD_FLOOR            # should INCREASE
    assert t["utilization"] < 0.80                    # headroom under the cap


def test_meta_prospecting_caps_out_and_must_stay_funded(dataset, tables):
    t = _truth(dataset).loc["META_PROSPECTING"]
    assert t["utilization"] > 0.90                    # repeatedly caps out
    assert t["marginal_roas"] > HARD_FLOOR            # productive -> keep funded
    camp = tables["dim_campaign"].set_index("campaign_id").loc["META_PROSPECTING"]
    assert bool(camp["is_prospecting"]) is True


def test_pmax_attractive_but_inventory_constrained(dataset):
    t = _truth(dataset).loc["GOOGLE_PMAX"]
    assert t["marginal_roas"] > HARD_FLOOR            # attractive economics
    assert t["utilization"] > 0.80                    # noon cap-outs
    pmax = S.CAMPAIGN_BY_ID["GOOGLE_PMAX"]
    assert pmax.primary_sku == S.INVENTORY_CONSTRAINED_SKU


def test_exactly_one_inventory_constrained_sku_blocks_scale(tables):
    inv = tables["fact_inventory_snapshot"]
    at_risk = inv[inv["stockout_risk"]]["sku_id"].tolist()
    assert at_risk == [S.INVENTORY_CONSTRAINED_SKU]
    promoters = [c.campaign_id for c in S.CAMPAIGNS
                 if c.primary_sku == S.INVENTORY_CONSTRAINED_SKU]
    assert "GOOGLE_PMAX" in promoters


# --- Policy-level tensions ---------------------------------------------------
def test_expected_vs_conservative_can_diverge(dataset):
    # At least one campaign clears the floor at Expected (P50) marginal but not
    # at the Conservative downside -> the two policies must eventually differ.
    flippers = [
        c.campaign_id for c in S.CAMPAIGNS
        if S.hill_marginal_roas(c.base_spend, c) > HARD_FLOOR
        and E.conservative_marginal(c) < HARD_FLOOR
    ]
    assert flippers, "no campaign flips between Expected and Conservative"


def test_calibration_downgrades_retargeting_more_than_nonbrand(tables):
    cal = tables["calibration_registry"].set_index("segment")
    assert cal.loc["meta_retargeting", "coefficient"] < cal.loc["google_nonbrand", "coefficient"]


# --- Blended ROAS story (broad scenario properties; NO optimizer allocation) -
# Stage 0 only proves the scenario is *designed to support* a future feasible
# optimization. It does NOT compute or advertise an optimizer allocation — that
# is Stage 3. The properties below are the ingredients a future optimizer needs.
def test_platform_reported_overstates_calibrated_blended(dataset):
    blended_incr, blended_platform, _ = _blended_roas()
    assert blended_platform > blended_incr + 0.5   # clear over-attribution gap


def test_current_calibrated_blended_below_target(dataset):
    blended_incr, _, _ = _blended_roas()
    # Calibrated blended ROAS starts below the primary-metric floor (the problem
    # the eventual optimizer will address), in a comfortable band.
    assert 3.70 <= blended_incr <= 3.95
    assert blended_incr < BLENDED_ROAS_FLOOR


def test_scenario_supports_a_future_feasible_optimization(dataset, tables):
    # The tensions a future optimizer would exploit all exist simultaneously:
    t = _truth(dataset)
    saturated = t[t["marginal_roas"] < HARD_FLOOR]            # channels to pull back
    headroom = t[t["marginal_roas"] > HARD_FLOOR]             # channels to scale into
    assert len(saturated) >= 1 and len(headroom) >= 1
    # ...prospecting stays fundable and at least one SKU blocks unsafe scale-up.
    prospecting = [c for c in S.CAMPAIGNS if c.is_prospecting]
    assert prospecting, "no prospecting campaign to keep funded"
    inv = tables["fact_inventory_snapshot"]
    assert inv["stockout_risk"].sum() == 1
    # No allocation is computed or asserted here.


def test_platform_revenue_exceeds_shopify_for_over_attributed_sku(tables):
    fact, com = tables["fact_ad_performance"], tables["fact_commerce_truth"]
    sku = "TC-POLO-CLS"
    plat = fact[fact["sku_id"] == sku].groupby("date")["platform_reported_revenue"].sum()
    shop = com[com["sku_id"] == sku].set_index("date")["dtc_revenue"]
    j = pd.concat([plat, shop], axis=1).dropna()
    assert (j["platform_reported_revenue"] > j["dtc_revenue"]).sum() > 0


# --- helpers -----------------------------------------------------------------
def _blended_roas():
    spend = sum(c.base_spend for c in S.CAMPAIGNS)
    incr = sum(float(S.hill_revenue(c.base_spend, c)) for c in S.CAMPAIGNS)
    platform = sum(float(S.hill_revenue(c.base_spend, c)) / c.incrementality for c in S.CAMPAIGNS)
    return incr / spend, platform / spend, spend
