"""No negative spend or impossible revenue/volume values."""

from __future__ import annotations


def test_no_negative_spend(tables):
    assert (tables["fact_ad_performance"]["spend"] >= 0).all()


def test_clicks_within_impressions(tables):
    f = tables["fact_ad_performance"]
    assert (f["clicks"] <= f["impressions"]).all()


def test_non_negative_revenue_and_conversions(tables):
    f = tables["fact_ad_performance"]
    assert (f["platform_reported_revenue"] >= 0).all()
    assert (f["platform_reported_conversions"] >= 0).all()


def test_commerce_truth_consistent(tables):
    c = tables["fact_commerce_truth"]
    assert (c["dtc_orders"] >= 0).all()
    assert (c["dtc_revenue"] >= 0).all()
    assert (c["returning_customer_revenue"] >= 0).all()
    # new + returning never exceeds gross (within rounding); nulls excluded
    sub = c.dropna(subset=["new_customer_revenue"])
    assert (sub["new_customer_revenue"] + sub["returning_customer_revenue"]
            <= sub["dtc_revenue"] + 0.05).all()


def test_inventory_values_sane(tables):
    inv = tables["fact_inventory_snapshot"]
    assert (inv["units_on_hand"] >= 0).all()
    assert (inv["days_of_cover"] >= 0).all()
    assert (inv["forecast_daily_demand"] > 0).all()


def test_margins_in_unit_interval(tables):
    sku = tables["dim_sku"]
    assert sku["contribution_margin_rate"].between(0, 1).all()
    assert sku["return_rate"].between(0, 1).all()


def test_calibration_coefficients_synthetic_and_bounded(tables):
    cal = tables["calibration_registry"]
    assert cal["is_synthetic"].all()
    assert cal["coefficient"].between(0, 2).all()
