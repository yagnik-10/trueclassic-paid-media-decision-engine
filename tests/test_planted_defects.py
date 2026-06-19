"""Exactly the 11 planted defects are present, each with the expected count.

Expectations come from an INDEPENDENT contract fixture
(tests/fixtures/expected_defects.json), not from the production constants — so
changing a backend constant without updating the contract fails by design.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

_CONTRACT = json.loads(
    (Path(__file__).parent / "fixtures" / "expected_defects.json").read_text()
)
EXPECTED_TYPES = set(_CONTRACT["expected_types"])
EXPECTED_COUNTS = _CONTRACT["expected_counts"]
TOTAL_EXPECTED = _CONTRACT["total_expected_issues"]


def test_eleven_distinct_defect_types(tables):
    dq = tables["data_quality_issue"]
    assert dq["issue_type"].nunique() == 11
    assert set(dq["issue_type"]) == EXPECTED_TYPES


def test_defect_counts_match_contract(dataset):
    assert dataset.defect_counts == EXPECTED_COUNTS


def test_issue_table_counts_match_contract(tables):
    dq = tables["data_quality_issue"]
    counts = dq["issue_type"].value_counts().to_dict()
    assert counts == EXPECTED_COUNTS
    assert len(dq) == TOTAL_EXPECTED


def test_production_constants_agree_with_contract():
    # The production constants must match the independent contract. If someone
    # edits the backend without updating the fixture, this fails.
    from backend.decision_engine.synth.defects import (
        EXPECTED_DEFECT_COUNTS,
        TOTAL_EXPECTED_ISSUES,
    )

    assert EXPECTED_DEFECT_COUNTS == EXPECTED_COUNTS
    assert TOTAL_EXPECTED_ISSUES == TOTAL_EXPECTED


def test_issue_ids_unique(tables):
    dq = tables["data_quality_issue"]
    assert dq["issue_id"].is_unique


# --- Each defect is realized in the data, not merely registered --------------
def test_duplicate_meta_record_realized(tables):
    fact = tables["fact_ad_performance"]
    assert fact["is_duplicate"].sum() == 1


def test_missing_google_extraction_date_realized(tables):
    fact = tables["fact_ad_performance"]
    miss = fact[(fact["platform"] == "google") & (fact["extraction_date"].isna())]
    assert len(miss) == 3


def test_null_new_customer_realized(tables):
    fact = tables["fact_ad_performance"]
    assert fact["new_customers"].isna().sum() == 5


def test_immature_planted_labels_realized(tables):
    fact = tables["fact_ad_performance"]
    # 4 planted immature rows on GOOGLE_NONBRAND that are NOT in the natural tail
    cutoff = fact["date"].max() - pd.Timedelta(days=7)
    planted = fact[
        (fact["campaign_id"] == "GOOGLE_NONBRAND")
        & (~fact["label_mature"])
        & (fact["date"] <= cutoff)
    ]
    assert len(planted) == 4


def test_attribution_window_mismatch_realized(tables):
    fact = tables["fact_ad_performance"]
    brand = fact[fact["campaign_id"] == "GOOGLE_BRAND"]
    assert (brand["attribution_window"] == "last_click").all()


def test_sku_alias_defects_realized(tables):
    alias = tables["sku_alias"]
    assert (alias["match_status"] == "needs_approval").sum() == 1
    assert (alias["match_status"] == "quarantined").sum() == 1
    assert alias.loc[alias["match_status"] == "quarantined", "sku_id"].isna().all()
    # low-confidence fuzzy mismatches
    assert ((alias["match_status"] == "auto_matched") & (alias["confidence"] < 0.7)).sum() == 2


def test_inconsistent_date_coverage_realized(tables):
    fact = tables["fact_ad_performance"]
    adv = fact[fact["campaign_id"] == "META_ADV_SHOPPING"]["date"]
    full = pd.date_range(adv.min(), adv.max(), freq="D")
    assert len(full) - adv.nunique() == 7  # the dropped 7-day block
