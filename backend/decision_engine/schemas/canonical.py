"""Pandera contracts for the 13 canonical tables (FINAL_PLAN section 12).

These are the unification target the adapters flatten into and the validation
gate that quarantines bad rows. Data tables (1-8) carry generated rows in
Stage 0; operational tables (9-13) are defined now but populated by later
stages, so we expose typed empty frames for them.

Nullability is deliberate: columns that a planted defect intentionally leaves
empty (e.g. ``extraction_date``, ``new_customer_value``) are ``nullable=True``
so the *defective* row still validates structurally and is caught by the
data-quality layer rather than the schema gate.
"""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
from pandera.pandas import Check, Column, DataFrameSchema

# Shared enumerations
PLATFORMS = ["meta", "google"]
SEGMENTS = ["meta_prospecting", "meta_retargeting", "google_brand", "google_nonbrand"]
MATCH_STATUS = ["auto_matched", "needs_approval", "quarantined"]
ISSUE_SEVERITY = ["low", "medium", "high"]


# 1 -----------------------------------------------------------------------
fact_ad_performance = DataFrameSchema(
    {
        "date": Column(pa.DateTime, coerce=True),
        "campaign_id": Column(str),
        "platform": Column(str, Check.isin(PLATFORMS)),
        "segment": Column(str, Check.isin(SEGMENTS)),
        "sku_id": Column(str, nullable=True),
        "spend": Column(float, Check.ge(0.0)),
        "impressions": Column(int, Check.ge(0)),
        "clicks": Column(int, Check.ge(0)),
        "platform_reported_revenue": Column(float, Check.ge(0.0)),
        "platform_reported_conversions": Column(float, Check.ge(0.0)),
        "new_customers": Column(float, Check.ge(0.0), nullable=True),
        "attribution_window": Column(str),
        "label_mature": Column(bool),
        # nullable: a planted defect omits the extraction date on some rows.
        "extraction_date": Column(pa.DateTime, coerce=True, nullable=True),
        "is_duplicate": Column(bool),
    },
    checks=Check(lambda df: (df["clicks"] <= df["impressions"]) | (df["impressions"] == 0),
                 element_wise=False, error="clicks exceed impressions"),
    strict=True,
    name="fact_ad_performance",
)

# 2 -----------------------------------------------------------------------
dim_campaign = DataFrameSchema(
    {
        "campaign_id": Column(str, unique=True),
        "campaign_name": Column(str),
        "platform": Column(str, Check.isin(PLATFORMS)),
        "segment": Column(str, Check.isin(SEGMENTS)),
        "objective": Column(str),
        "is_prospecting": Column(bool),
        "daily_cap": Column(float, Check.gt(0.0)),
    },
    strict=True,
    name="dim_campaign",
)

# 3 -----------------------------------------------------------------------
dim_sku = DataFrameSchema(
    {
        "sku_id": Column(str, unique=True),
        "product_name": Column(str),
        "unit_price": Column(float, Check.gt(0.0)),
        "unit_cost": Column(float, Check.ge(0.0)),
        "fulfillment_cost": Column(float, Check.ge(0.0)),
        "return_rate": Column(float, Check.in_range(0.0, 1.0)),
        "contribution_margin_rate": Column(float, Check.in_range(0.0, 1.0)),
    },
    strict=True,
    name="dim_sku",
)

# 4 -----------------------------------------------------------------------
sku_alias = DataFrameSchema(
    {
        "platform": Column(str, Check.isin(PLATFORMS)),
        "platform_product_id": Column(str),
        # nullable: a quarantined unknown ID maps to no canonical SKU.
        "sku_id": Column(str, nullable=True),
        "match_status": Column(str, Check.isin(MATCH_STATUS)),
        "confidence": Column(float, Check.in_range(0.0, 1.0)),
    },
    strict=True,
    name="sku_alias",
)

# 5 -----------------------------------------------------------------------
fact_commerce_truth = DataFrameSchema(
    {
        "date": Column(pa.DateTime, coerce=True),
        "sku_id": Column(str),
        "dtc_orders": Column(int, Check.ge(0)),
        "dtc_revenue": Column(float, Check.ge(0.0)),
        # nullable: a planted defect nulls new-customer revenue on some rows.
        "new_customer_revenue": Column(float, Check.ge(0.0), nullable=True),
        "returning_customer_revenue": Column(float, Check.ge(0.0)),
    },
    strict=True,
    name="fact_commerce_truth",
)

# 6 -----------------------------------------------------------------------
fact_inventory_snapshot = DataFrameSchema(
    {
        "date": Column(pa.DateTime, coerce=True),
        "sku_id": Column(str),
        "units_on_hand": Column(int, Check.ge(0)),
        "forecast_daily_demand": Column(float, Check.gt(0.0)),
        "lead_time_days": Column(int, Check.ge(0)),
        "safety_days": Column(int, Check.ge(0)),
        "days_of_cover": Column(float, Check.ge(0.0)),
        "stockout_risk": Column(bool),
    },
    strict=True,
    name="fact_inventory_snapshot",
)

# 7 -----------------------------------------------------------------------
data_quality_issue = DataFrameSchema(
    {
        "issue_id": Column(str, unique=True),
        "issue_type": Column(str),
        "severity": Column(str, Check.isin(ISSUE_SEVERITY)),
        "entity_type": Column(str),
        "entity_ref": Column(str),
        "description": Column(str),
        "detected_stage": Column(str),
        "resolution": Column(str),
    },
    strict=True,
    name="data_quality_issue",
)

# 8 -----------------------------------------------------------------------
calibration_registry = DataFrameSchema(
    {
        "registry_id": Column(str, unique=True),
        "segment": Column(str, Check.isin(SEGMENTS)),
        "coefficient": Column(float, Check.in_range(0.0, 2.0)),
        "source": Column(str),
        "effective_start": Column(pa.DateTime, coerce=True),
        "effective_end": Column(pa.DateTime, coerce=True, nullable=True),
        "confidence": Column(str),
        "scope": Column(str),
        "is_synthetic": Column(bool, Check.eq(True)),  # every value labelled synthetic
    },
    strict=True,
    name="calibration_registry",
)

# 9 -----------------------------------------------------------------------
model_run = DataFrameSchema(
    {
        "run_id": Column(str, unique=True),
        "model_type": Column(str),
        "created_at": Column(pa.DateTime, coerce=True),
        "seed": Column(int),
        "params_json": Column(str),
        "status": Column(str),
    },
    strict=True,
    coerce=True,
    name="model_run",
)

# 10 ----------------------------------------------------------------------
model_evaluation = DataFrameSchema(
    {
        "eval_id": Column(str, unique=True),
        "run_id": Column(str),
        "metric_name": Column(str),
        "metric_value": Column(float),
        "fold": Column(str),
        "baseline_name": Column(str, nullable=True),
    },
    strict=True,
    coerce=True,
    name="model_evaluation",
)

# 11 ----------------------------------------------------------------------
recommendation = DataFrameSchema(
    {
        "rec_id": Column(str, unique=True),
        "run_id": Column(str),
        "campaign_id": Column(str),
        "current_spend": Column(float, Check.ge(0.0)),
        "recommended_spend": Column(float, Check.ge(0.0)),
        "delta_pct": Column(float),
        "marginal_roas": Column(float),
        "reason_codes": Column(str),
        "risk_flags": Column(str),
        "policy_mode": Column(str),
    },
    strict=True,
    coerce=True,
    name="recommendation",
)

# 12 ----------------------------------------------------------------------
approval = DataFrameSchema(
    {
        "approval_id": Column(str, unique=True),
        "rec_id": Column(str),
        "status": Column(str),
        "approver": Column(str),
        "decided_at": Column(pa.DateTime, coerce=True, nullable=True),
        "notes": Column(str, nullable=True),
    },
    strict=True,
    coerce=True,
    name="approval",
)

# 13 ----------------------------------------------------------------------
execution_event = DataFrameSchema(
    {
        "event_id": Column(str, unique=True),
        "rec_id": Column(str),
        "platform": Column(str, Check.isin(PLATFORMS)),
        "payload_hash": Column(str),
        "status": Column(str),
        "created_at": Column(pa.DateTime, coerce=True),
        "is_stub": Column(bool, Check.eq(True)),  # Stage 0-5: execution is always stubbed
    },
    strict=True,
    coerce=True,
    name="execution_event",
)


CANONICAL_SCHEMAS: dict[str, DataFrameSchema] = {
    "fact_ad_performance": fact_ad_performance,
    "dim_campaign": dim_campaign,
    "dim_sku": dim_sku,
    "sku_alias": sku_alias,
    "fact_commerce_truth": fact_commerce_truth,
    "fact_inventory_snapshot": fact_inventory_snapshot,
    "data_quality_issue": data_quality_issue,
    "calibration_registry": calibration_registry,
    "model_run": model_run,
    "model_evaluation": model_evaluation,
    "recommendation": recommendation,
    "approval": approval,
    "execution_event": execution_event,
}

# Operational tables defined now but populated by later stages.
OPERATIONAL_TABLES: tuple[str, ...] = (
    "model_run",
    "model_evaluation",
    "recommendation",
    "approval",
    "execution_event",
)


def empty_frame(table: str) -> pd.DataFrame:
    """Return a typed, empty DataFrame with the schema's columns."""
    schema = CANONICAL_SCHEMAS[table]
    return pd.DataFrame({col: pd.Series(dtype=object) for col in schema.columns})


# --- Explicit storage typing -----------------------------------------------
# Empty operational tables must NOT let pandas object/null inference pick their
# stored types. These maps give deterministic Arrow / DuckDB types per column.
def _type_kind(column) -> str:
    d = str(column.dtype).lower()
    if "datetime" in d or "timestamp" in d:
        return "datetime"
    if "bool" in d:
        return "bool"
    if "int" in d:
        return "int"
    if "float" in d:
        return "float"
    return "str"


_ARROW = {"int": "int64", "float": "float64", "bool": "bool_",
          "datetime": ("timestamp", "ns"), "str": "string"}
_DUCKDB = {"int": "BIGINT", "float": "DOUBLE", "bool": "BOOLEAN",
           "datetime": "TIMESTAMP", "str": "VARCHAR"}


def arrow_schema(table: str):
    """A pyarrow schema for ``table`` derived from its Pandera contract."""
    import pyarrow as pa

    fields = []
    for name, col in CANONICAL_SCHEMAS[table].columns.items():
        kind = _type_kind(col)
        if kind == "datetime":
            fields.append((name, pa.timestamp("ns")))
        else:
            fields.append((name, getattr(pa, _ARROW[kind])()))
    return pa.schema(fields)


def duckdb_columns(table: str) -> dict[str, str]:
    """Column -> DuckDB type for an explicit ``CREATE TABLE`` DDL."""
    return {name: _DUCKDB[_type_kind(col)]
            for name, col in CANONICAL_SCHEMAS[table].columns.items()}
