"""Stage 2 — real ingestion: adapters, validation/quarantine, SKU resolution, DQ."""

from __future__ import annotations

import collections
import copy

import pandas as pd
import pytest

from backend.decision_engine.ingestion.adapters import ingest_meta
from backend.decision_engine.ingestion.pipeline import build_campaign_ref, run_ingestion
from backend.decision_engine.ingestion.validation import (
    EnvelopeStructureError,
    validate_envelope_records,
)
from backend.decision_engine.schemas.canonical import (
    fact_ad_performance,
    fact_commerce_truth,
)
from backend.decision_engine.schemas.envelopes import MetaInsightRecord
from backend.decision_engine.synth.envelope_writers import build_all_envelopes
from backend.decision_engine.synth.generator import generate


@pytest.fixture(scope="module")
def report():
    return run_ingestion()


@pytest.fixture(scope="module")
def envelopes():
    ds = generate()
    return build_all_envelopes(ds.tables["fact_ad_performance"], ds.tables["fact_commerce_truth"])


# --- adapters produce schema-valid canonical output -------------------------
def test_canonical_frames_validate(report):
    fact_ad_performance.validate(report.fact, lazy=True)
    fact_commerce_truth.validate(report.commerce, lazy=True)
    assert report.fact["date"].notna().all()         # no un-placeable rows survived


def test_feed_counts_and_quarantine(report):
    meta, google, shopify = (report.feed(p) for p in ("meta", "google", "shopify"))
    assert meta.quarantined == 0
    assert google.quarantined == 3                    # missing-date rows can't be placed
    assert google.normalized == google.raw - 3
    assert shopify.quarantined == 0
    assert len(report.fact) == meta.normalized + google.normalized


def test_google_cost_micros_normalized(report, envelopes):
    g = envelopes["google_ads"]["results"]
    # first placeable google record (segments.date present)
    first = next(r for r in g if r["segments"]["date"] is not None)
    row = report.fact[
        (report.fact["campaign_id"] == first["campaign"]["id"])
        & (report.fact["date"] == first["segments"]["date"])
    ].iloc[0]
    assert row["spend"] == pytest.approx(first["metrics"]["cost_micros"] / 1_000_000)


# --- record-level validation & quarantine -----------------------------------
def test_mixed_envelope_quarantines_only_bad_records(envelopes):
    env = copy.deepcopy(envelopes["meta_insights"])
    n_valid = len(env["data"])
    env["data"].insert(3, {"campaign_id": "broken"})           # malformed
    env["data"].insert(9, {"campaign_id": "x", "actions": "y"})  # malformed
    vr = validate_envelope_records(
        env, outer_required_keys=("data", "paging"), records_key="data",
        record_model=MetaInsightRecord, platform="meta", key_field="campaign_id",
    )
    assert vr.n_valid == n_valid          # no valid record lost
    assert vr.n_quarantined == 2
    assert vr.quarantined[0].reason == "schema_invalid"


def test_malformed_envelope_raises(envelopes):
    with pytest.raises(EnvelopeStructureError):
        validate_envelope_records(
            {"paging": {}}, outer_required_keys=("data", "paging"), records_key="data",
            record_model=MetaInsightRecord, platform="meta",
        )


def test_bad_meta_record_never_reaches_canonical(envelopes):
    env = copy.deepcopy(envelopes["meta_insights"])
    env["data"].insert(0, {"campaign_id": "BAD"})
    res = ingest_meta(env, build_campaign_ref())
    assert res.n_quarantined == 1
    assert all(r["campaign_id"] != "BAD" for r in res.canonical_rows)


def test_google_mixed_validity_keeps_valid_quarantines_bad(envelopes):
    from backend.decision_engine.ingestion.adapters import ingest_google

    env = copy.deepcopy(envelopes["google_ads"])
    n_missing = sum(1 for r in env["results"] if r["segments"]["date"] is None)
    valid_placeable = len(env["results"]) - n_missing
    env["results"].insert(7, {"campaign": {"id": "BAD_GOOGLE"}})  # malformed nesting
    res = ingest_google(env, build_campaign_ref())
    schema_bad = [q for q in res.quarantined if q.reason == "schema_invalid"]
    assert len(schema_bad) == 1                       # the malformed record
    assert res.n_rows == valid_placeable              # every placeable valid row survived
    assert all(r["campaign_id"] != "BAD_GOOGLE" for r in res.canonical_rows)


def test_shopify_mixed_validity_keeps_valid_quarantines_bad(envelopes):
    from backend.decision_engine.ingestion.adapters import ingest_shopify

    env = copy.deepcopy(envelopes["shopify_commerce"])
    n_valid = len(env["records"])
    env["records"].insert(9, {"sku": "BAD_SHOPIFY"})  # missing required fields
    vr = ingest_shopify(env)
    assert vr.n_valid == n_valid                      # no valid record lost
    assert vr.n_quarantined == 1
    assert vr.quarantined[0].reason == "schema_invalid"


# --- deduplication & maturity -----------------------------------------------
def test_duplicate_flagged_not_double_counted(report):
    fact = report.fact
    assert fact["is_duplicate"].sum() == 1
    with_dup = fact["platform_reported_revenue"].sum()
    deduped = fact[~fact["is_duplicate"]]["platform_reported_revenue"].sum()
    assert with_dup > deduped


def test_label_maturity_exact_final_seven_days(report):
    fact = report.fact
    cutoff = fact["date"].max() - pd.Timedelta(days=6)   # last 7 calendar days inclusive
    immature = fact[~fact["label_mature"]]
    mature = fact[fact["label_mature"]]
    assert (immature["date"] >= cutoff).all()             # immature == the maturity tail
    assert (mature["date"] < cutoff).all()                # nothing in the tail is mature
    # the policy applies uniformly across every platform present
    assert set(immature["platform"].unique()) == set(fact["platform"].unique())


def test_ingestion_report_is_deterministic():
    a, b = run_ingestion(), run_ingestion()
    # the blocking fix: quarantine provenance is deterministic (pull date, not wall-clock)
    assert [q.detected_at for q in a.quarantined] == [q.detected_at for q in b.quarantined]
    assert all(q.detected_at is not None for q in a.quarantined)
    # source positions are preserved (not -1) for every quarantine
    assert all(q.source_index >= 0 for q in a.quarantined)
    # the rest of the report is identical run-to-run
    assert a.dq_issues == b.dq_issues
    assert [f.__dict__ for f in a.feeds] == [f.__dict__ for f in b.feeds]


# --- SKU resolution ----------------------------------------------------------
def test_sku_resolution_states(report):
    summary = report.sku_resolution_summary
    assert summary.get("needs_approval") == 1
    assert summary.get("quarantined") == 1
    needs = next(s for s in report.sku_resolutions if s.status == "needs_approval")
    assert needs.platform_product_id == "GG_TC-JOG-BLU"
    assert needs.allowed_candidates and "TC-JOG-BLK" in needs.allowed_candidates
    quar = next(s for s in report.sku_resolutions if s.status == "quarantined")
    assert quar.sku_id is None
    assert quar.allowed_candidates                      # ranked candidates offered


def test_unknown_sku_never_auto_resolves(report):
    quar = [s for s in report.sku_resolutions if s.status == "quarantined"]
    assert all(s.sku_id is None for s in quar)


# --- data-quality detection from the feeds ----------------------------------
def test_detected_defects_present(report):
    counts = collections.Counter(i["issue_type"] for i in report.dq_issues)
    assert counts["duplicate_meta_record"] == 1
    assert counts["missing_google_extraction_date"] == 3
    assert counts["null_new_customer_value"] == 5
    assert counts["google_cost_micros_normalization"] == 1
    assert counts["platform_revenue_exceeds_shopify"] >= 1
    assert counts["inconsistent_date_coverage"] >= 1


def test_dq_issue_ids_unique(report):
    ids = [i["issue_id"] for i in report.dq_issues]
    assert len(ids) == len(set(ids))
