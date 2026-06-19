"""Orchestrate ingestion: raw JSON feeds -> validated/quarantined -> canonical
fact + commerce, with SKU resolution and detected data-quality issues.

Master/reference tables (dim_campaign, dim_sku, sku_alias) are internal, not
platform-API feeds, so they are loaded from the deterministic generator; only the
Meta/Google/Shopify ad+commerce feeds are ingested from the raw envelopes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from backend.decision_engine import config as C
from backend.decision_engine.ingestion import quality
from backend.decision_engine.ingestion.adapters import (
    AdapterResult,
    CampaignRef,
    ingest_google,
    ingest_meta,
    ingest_shopify,
    normalize_shopify_record,
    to_commerce_dataframe,
    to_fact_dataframe,
)
from backend.decision_engine.ingestion.sku_resolution import (
    SkuResolution,
    resolve,
    summarize,
)
from backend.decision_engine.ingestion.validation import QuarantinedRecord
from backend.decision_engine.synth import scenario as S
from backend.decision_engine.synth.generator import generate


@dataclass
class FeedStats:
    platform: str
    raw: int
    normalized: int
    quarantined: int


@dataclass
class IngestionReport:
    feeds: list[FeedStats]
    fact: pd.DataFrame
    commerce: pd.DataFrame
    dq_issues: list[dict]
    sku_resolutions: list[SkuResolution]
    quarantined: list[QuarantinedRecord]
    masters: dict[str, pd.DataFrame] = field(default_factory=dict)

    def feed(self, platform: str) -> FeedStats:
        return next(f for f in self.feeds if f.platform == platform)

    @property
    def sku_resolution_summary(self) -> dict[str, int]:
        return summarize(self.sku_resolutions)


def build_campaign_ref() -> CampaignRef:
    """campaign_id -> {segment, sku_id} (the account's campaign→product mapping)."""
    return {c.campaign_id: {"segment": c.segment, "sku_id": c.primary_sku}
            for c in S.CAMPAIGNS}


def load_raw_envelopes(raw_dir: Path | None = None) -> dict[str, dict]:
    raw_dir = raw_dir or C.RAW_DIR
    out: dict[str, dict] = {}
    for name in ("meta_insights", "google_ads", "shopify_commerce"):
        path = raw_dir / f"{name}.json"
        out[name] = json.loads(path.read_text())
    return out


def _pull_date(envelopes: dict[str, dict]) -> str:
    """Deterministic ingestion as-of: the latest metric date across the feeds."""
    dates: list[str] = []
    dates += [r["date_stop"] for r in envelopes["meta_insights"]["data"]]
    dates += [r["segments"]["date"] for r in envelopes["google_ads"]["results"]
              if r["segments"]["date"] is not None]
    dates += [r["date"] for r in envelopes["shopify_commerce"]["records"]]
    return max(dates)


def run_ingestion(
    raw_dir: Path | None = None,
    envelopes: dict[str, dict] | None = None,
) -> IngestionReport:
    envelopes = envelopes or load_raw_envelopes(raw_dir)
    ref = build_campaign_ref()
    as_of = _pull_date(envelopes)  # deterministic; used for quarantine provenance

    meta: AdapterResult = ingest_meta(envelopes["meta_insights"], ref, as_of=as_of)
    google: AdapterResult = ingest_google(envelopes["google_ads"], ref, as_of=as_of)
    shopify_vr = ingest_shopify(envelopes["shopify_commerce"], as_of=as_of)

    fact = to_fact_dataframe(meta.canonical_rows + google.canonical_rows)
    commerce_rows = [normalize_shopify_record(r) for r in shopify_vr.valid]
    commerce = to_commerce_dataframe(commerce_rows)

    quarantined = list(meta.quarantined) + list(google.quarantined) + list(shopify_vr.quarantined)
    fact, commerce, dq_issues = quality.detect(fact, commerce, quarantined)

    masters = generate().tables
    sku_resolutions = resolve(masters["sku_alias"], masters["dim_sku"])

    feeds = [
        FeedStats("meta", len(envelopes["meta_insights"]["data"]),
                  meta.n_rows, meta.n_quarantined),
        FeedStats("google", len(envelopes["google_ads"]["results"]),
                  google.n_rows, google.n_quarantined),
        FeedStats("shopify", len(envelopes["shopify_commerce"]["records"]),
                  shopify_vr.n_valid, shopify_vr.n_quarantined),
    ]
    return IngestionReport(
        feeds=feeds, fact=fact, commerce=commerce, dq_issues=dq_issues,
        sku_resolutions=sku_resolutions, quarantined=quarantined,
        masters={k: masters[k] for k in ("dim_campaign", "dim_sku", "sku_alias")},
    )
