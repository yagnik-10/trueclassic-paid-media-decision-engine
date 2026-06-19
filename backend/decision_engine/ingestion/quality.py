"""Detect data-quality issues from the ingested feeds (the 'real' version of the
Stage 0 planted defects). Produces `data_quality_issue`-shaped rows, marks
duplicates on the natural key, and applies the label-maturity policy.

Only feed-observable signals are detected here. A few Stage 0 canonical-level
defects (e.g. the Google attribution-window mismatch, the Meta new-customer
nulls) are NOT carried by the raw API envelopes and so are out of scope for
feed-level detection — see docs/DECISIONS.md.
"""

from __future__ import annotations

import pandas as pd

from backend.decision_engine.config import LABEL_MATURITY_DAYS
from backend.decision_engine.ingestion.validation import QuarantinedRecord
from backend.decision_engine.synth.defects import DEFECT_BY_TYPE

_NATURAL_KEY = ["platform", "campaign_id", "date"]  # platform-scoped: vendor IDs aren't global


def _issue(issue_type: str, seq: int, entity_type: str, entity_ref: str,
           description: str) -> dict:
    spec = DEFECT_BY_TYPE.get(issue_type)
    severity = spec.severity if spec else "medium"
    stage = "ingestion"
    resolution = spec.default_resolution if spec else "flag"
    return {
        "issue_id": f"DQ-{issue_type}-{seq:03d}",
        "issue_type": issue_type,
        "severity": severity,
        "entity_type": entity_type,
        "entity_ref": entity_ref,
        "description": description,
        "detected_stage": stage,
        "resolution": resolution,
    }


def mark_duplicates(fact: pd.DataFrame) -> pd.DataFrame:
    """Flag rows that repeat a platform's natural key (campaign_id, date)."""
    fact = fact.copy()
    dup_mask = fact.duplicated(subset=_NATURAL_KEY, keep="first")
    fact["is_duplicate"] = dup_mask
    return fact


def apply_label_maturity(fact: pd.DataFrame) -> pd.DataFrame:
    """A 7-day outcome needs 7 days to mature: extraction_date - date >= 7d."""
    fact = fact.copy()
    has_ext = fact["extraction_date"].notna()
    age = (fact["extraction_date"] - fact["date"]).dt.days
    fact.loc[has_ext, "label_mature"] = age[has_ext] >= LABEL_MATURITY_DAYS
    return fact


def detect(
    fact: pd.DataFrame,
    commerce: pd.DataFrame,
    adapter_quarantines: list[QuarantinedRecord],
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    """Return (deduped+matured fact, commerce, detected data_quality_issue rows)."""
    issues: list[dict] = []
    fact = apply_label_maturity(mark_duplicates(fact))

    # 1. duplicate platform records on the natural key
    for i, (_, r) in enumerate(fact[fact["is_duplicate"]].iterrows(), start=1):
        issues.append(_issue("duplicate_meta_record", i, "fact_ad_performance",
                             f"{r['campaign_id']}@{r['date'].date()}",
                             "duplicate platform record on natural key — dedupe"))

    # 2. missing extraction date (rows the adapters could not place)
    miss = [q for q in adapter_quarantines if q.reason == "missing_extraction_date"]
    for i, q in enumerate(miss, start=1):
        issues.append(_issue("missing_google_extraction_date", i, "raw_google_feed",
                             str(q.source_key), "extraction date missing — flag, not impute"))

    # 3. cost_micros normalization — only when Google rows were actually ingested
    if (fact["platform"] == "google").any():
        issues.append(_issue("google_cost_micros_normalization", 1, "raw_google_feed",
                             "metrics.cost_micros", "Google cost in micros — divided by 1e6 on ingest"))

    # 4. null new-customer value (Shopify source of record)
    nc_null = commerce[commerce["new_customer_revenue"].isna()]
    for i, (_, r) in enumerate(nc_null.iterrows(), start=1):
        issues.append(_issue("null_new_customer_value", i, "fact_commerce_truth",
                             f"{r['sku_id']}@{r['date'].date()}",
                             "new-customer revenue null — impute low-confidence"))

    # 5. immature conversion labels (maturity tail)
    n_immature = int((~fact["label_mature"]).sum())
    if n_immature:
        issues.append(_issue("immature_conversion_labels", 1, "fact_ad_performance",
                             f"{n_immature}_rows",
                             f"{n_immature} rows with un-matured 7-day labels — exclude/downweight"))

    # 6. platform revenue exceeds Shopify DTC (per over-attributed SKU)
    plat = (fact[~fact["is_duplicate"]].groupby(["sku_id", "date"])["platform_reported_revenue"]
            .sum().rename("plat"))
    shop = commerce.groupby(["sku_id", "date"])["dtc_revenue"].sum().rename("shop")
    j = pd.concat([plat, shop], axis=1).dropna()
    over = j[j["plat"] > j["shop"]]
    over_counts = pd.Series(over.index.get_level_values("sku_id")).astype("object").value_counts()
    for i, sku in enumerate(sorted(over_counts.index), start=1):
        n = int(over_counts[sku])
        issues.append(_issue("platform_revenue_exceeds_shopify", i, "reconciliation",
                             str(sku), f"platform-reported revenue exceeds Shopify DTC on {n} days"))

    # 7. inconsistent date coverage (gaps within a campaign's active range)
    seq = 1
    for cid, g in fact[~fact["is_duplicate"]].groupby("campaign_id"):
        dates = pd.to_datetime(g["date"]).dt.normalize()
        full = pd.date_range(dates.min(), dates.max(), freq="D")
        gap = len(full) - dates.nunique()
        if gap > 0:
            issues.append(_issue("inconsistent_date_coverage", seq, "fact_ad_performance",
                                 str(cid), f"{gap}-day coverage gap in active range"))
            seq += 1

    return fact, commerce, issues
