"""Deterministic SKU reconciliation across mismatched platform product IDs.

Reads the `sku_alias` table and surfaces three states:
  * auto_matched   — high-confidence, used as-is;
  * needs_approval — a similar-but-not-certain candidate; a HUMAN must approve;
  * quarantined    — unknown id, mapped to no canonical SKU until resolved.

Matching is deterministic. For non-auto rows it computes an `allowed_candidates`
list (closest canonical SKUs) — the bounded set a Stage-5 LLM would later *rank*.
The schema forbids inventing a SKU outside this list.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

import pandas as pd


@dataclass
class SkuResolution:
    platform: str
    platform_product_id: str
    sku_id: str | None
    status: str            # auto_matched | needs_approval | quarantined | approved
    confidence: float
    allowed_candidates: list[str]


def _candidates(platform_product_id: str, known_skus: list[str], k: int = 3) -> list[str]:
    """Deterministic closest canonical SKUs for a fuzzy/unknown platform id."""
    norm = platform_product_id.upper().replace("_", "").replace("-", "")
    scored = sorted(
        known_skus,
        key=lambda s: (
            -difflib.SequenceMatcher(None, norm, s.upper().replace("-", "")).ratio(),
            s,
        ),
    )
    return scored[:k]


def resolve(alias_df: pd.DataFrame, dim_sku_df: pd.DataFrame) -> list[SkuResolution]:
    known = sorted(dim_sku_df["sku_id"].tolist())
    out: list[SkuResolution] = []
    for _, r in alias_df.sort_values(["platform", "platform_product_id"]).iterrows():
        status = r["match_status"]
        sku = None if pd.isna(r["sku_id"]) else str(r["sku_id"])
        cands: list[str] = []
        if status == "needs_approval":
            cands = [sku] if sku else _candidates(r["platform_product_id"], known)
        elif status == "quarantined":
            cands = _candidates(r["platform_product_id"], known)
        out.append(
            SkuResolution(
                platform=str(r["platform"]),
                platform_product_id=str(r["platform_product_id"]),
                sku_id=sku,
                status=status,
                confidence=float(r["confidence"]),
                allowed_candidates=cands,
            )
        )
    return out


def summarize(resolutions: list[SkuResolution]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in resolutions:
        counts[r.status] = counts.get(r.status, 0) + 1
    return counts
