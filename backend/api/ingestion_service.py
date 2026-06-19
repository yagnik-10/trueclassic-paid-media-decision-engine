"""API service over the Stage 2 ingestion pipeline.

Caches the (deterministic) ingestion report and overlays in-memory SKU-mapping
approvals — a marketer can approve a `needs_approval` candidate, which flips it to
`approved` (the schema still forbids any SKU outside the allowed-candidate list).
"""

from __future__ import annotations

import threading
from functools import lru_cache

from backend.api.schemas import (
    DqIssue,
    FeedStat,
    IngestionSummary,
    SkuResolutionItem,
)
from backend.decision_engine.ingestion.pipeline import IngestionReport, run_ingestion


class SkuApprovalError(Exception):
    """Approval was attempted on an invalid id, state, or candidate."""


@lru_cache(maxsize=1)
def _report() -> IngestionReport:
    return run_ingestion()


# in-memory approvals: platform_product_id -> approved sku_id
_lock = threading.Lock()
_approvals: dict[str, str] = {}


def reset_approvals() -> None:
    with _lock:
        _approvals.clear()


def _to_item(r) -> SkuResolutionItem:
    with _lock:
        approved = _approvals.get(r.platform_product_id)
    status = "approved" if approved else r.status
    sku = approved or r.sku_id
    return SkuResolutionItem(
        platform=r.platform, platform_product_id=r.platform_product_id,
        sku_id=sku, status=status, confidence=r.confidence,
        allowed_candidates=list(r.allowed_candidates),
    )


def summary() -> IngestionSummary:
    rep = _report()
    items = [_to_item(r) for r in rep.sku_resolutions]
    counts: dict[str, int] = {}
    for it in items:
        counts[it.status] = counts.get(it.status, 0) + 1
    return IngestionSummary(
        feeds=[FeedStat(platform=f.platform, raw=f.raw, normalized=f.normalized,
                        quarantined=f.quarantined) for f in rep.feeds],
        canonical_fact_rows=int(len(rep.fact)),
        canonical_commerce_rows=int(len(rep.commerce)),
        total_quarantined=len(rep.quarantined),
        dq_issues=[DqIssue(**i) for i in rep.dq_issues],
        sku_resolutions=items,
        sku_resolution_summary=counts,
    )


def approve_sku(platform_product_id: str, sku_id: str) -> SkuResolutionItem:
    rep = _report()
    match = next((r for r in rep.sku_resolutions
                 if r.platform_product_id == platform_product_id), None)
    if match is None:
        raise SkuApprovalError(f"unknown platform product id {platform_product_id}")
    if match.status == "auto_matched":
        raise SkuApprovalError(f"{platform_product_id} is already auto-matched")
    if sku_id not in match.allowed_candidates:
        # the schema forbids inventing a SKU outside the allowed-candidate list
        raise SkuApprovalError(
            f"{sku_id} is not an allowed candidate for {platform_product_id}"
        )
    with _lock:
        _approvals[platform_product_id] = sku_id
    return _to_item(match)
