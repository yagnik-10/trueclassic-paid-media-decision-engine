"""Canonical schema validation for all 13 tables."""

from __future__ import annotations

import pytest

from backend.decision_engine.schemas.canonical import (
    CANONICAL_SCHEMAS,
    OPERATIONAL_TABLES,
    empty_frame,
)


def test_all_thirteen_tables_present(tables):
    assert set(tables) == set(CANONICAL_SCHEMAS)
    assert len(CANONICAL_SCHEMAS) == 13


@pytest.mark.parametrize("table", list(CANONICAL_SCHEMAS))
def test_table_validates_against_schema(tables, table):
    CANONICAL_SCHEMAS[table].validate(tables[table], lazy=True)


def test_operational_tables_are_empty_but_typed(tables):
    for t in OPERATIONAL_TABLES:
        assert len(tables[t]) == 0
        CANONICAL_SCHEMAS[t].validate(empty_frame(t), lazy=True)


def test_strictness_rejects_extra_columns(tables):
    import pandera.errors

    bad = tables["dim_sku"].copy()
    bad["rogue_column"] = 1
    with pytest.raises(pandera.errors.SchemaErrors):
        CANONICAL_SCHEMAS["dim_sku"].validate(bad, lazy=True)


def test_nullable_columns_accept_nulls_required_do_not(tables):
    # nullable defect columns actually carry nulls
    assert tables["fact_ad_performance"]["extraction_date"].isna().any()
    assert tables["fact_ad_performance"]["new_customers"].isna().any()
    assert tables["sku_alias"]["sku_id"].isna().any()
    # required keys never null
    assert tables["fact_ad_performance"]["campaign_id"].notna().all()
    assert tables["dim_campaign"]["campaign_id"].notna().all()
