"""Catalog of the 11 deliberately-planted data-quality defects.

Each defect is realized in the generated data (not merely asserted) and
registered as one-or-more rows in the ``data_quality_issue`` canonical table.
The expected per-type counts are frozen here and asserted by
tests/test_planted_defects.py, so any drift in generation is caught.

Defects map 1:1 to FINAL_PLAN section 12's "deliberately inserted data defects".
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DefectSpec:
    issue_type: str
    severity: str          # low | medium | high
    detected_stage: str    # which pipeline stage surfaces it
    default_resolution: str
    expected_count: int     # number of data_quality_issue rows planted


# Order is stable and meaningful (used for deterministic issue_id assignment).
DEFECT_SPECS: tuple[DefectSpec, ...] = (
    DefectSpec(
        "duplicate_meta_record", "high", "ingestion",
        "deduplicate_on_natural_key", 1,
    ),
    DefectSpec(
        "missing_google_extraction_date", "medium", "ingestion",
        "flag_not_impute", 3,
    ),
    DefectSpec(
        "google_cost_micros_normalization", "low", "adapter",
        "divide_by_1e6", 1,
    ),
    DefectSpec(
        "sku_alias_mismatch", "medium", "sku_resolution",
        "fuzzy_match_low_confidence", 2,
    ),
    DefectSpec(
        "sku_candidate_needs_approval", "high", "sku_resolution",
        "human_approval_required", 1,
    ),
    DefectSpec(
        "unknown_sku_quarantine", "high", "sku_resolution",
        "quarantine_until_mapped", 1,
    ),
    DefectSpec(
        "null_new_customer_value", "medium", "validation",
        "impute_low_confidence", 5,
    ),
    DefectSpec(
        "immature_conversion_labels", "medium", "label_maturity",
        "exclude_or_downweight", 4,
    ),
    DefectSpec(
        "attribution_window_mismatch", "medium", "attribution_normalization",
        "normalize_to_canonical_window", 1,
    ),
    DefectSpec(
        "platform_revenue_exceeds_shopify", "high", "reconciliation",
        "use_shopify_source_of_record", 1,
    ),
    DefectSpec(
        "inconsistent_date_coverage", "medium", "ingestion",
        "flag_coverage_gap", 1,
    ),
)

DEFECT_BY_TYPE: dict[str, DefectSpec] = {d.issue_type: d for d in DEFECT_SPECS}

# Frozen expectation asserted by the test-suite.
EXPECTED_DEFECT_COUNTS: dict[str, int] = {d.issue_type: d.expected_count for d in DEFECT_SPECS}

TOTAL_EXPECTED_ISSUES: int = sum(EXPECTED_DEFECT_COUNTS.values())


class IssueLog:
    """Accumulates data_quality_issue rows with deterministic ids."""

    def __init__(self) -> None:
        self._rows: list[dict] = []
        self._counts: dict[str, int] = {d.issue_type: 0 for d in DEFECT_SPECS}

    def add(self, issue_type: str, entity_type: str, entity_ref: str, description: str) -> None:
        spec = DEFECT_BY_TYPE[issue_type]
        self._counts[issue_type] += 1
        seq = self._counts[issue_type]
        self._rows.append(
            {
                "issue_id": f"DQ-{issue_type}-{seq:03d}",
                "issue_type": issue_type,
                "severity": spec.severity,
                "entity_type": entity_type,
                "entity_ref": entity_ref,
                "description": description,
                "detected_stage": spec.detected_stage,
                "resolution": spec.default_resolution,
            }
        )

    @property
    def rows(self) -> list[dict]:
        return list(self._rows)

    @property
    def counts(self) -> dict[str, int]:
        return dict(self._counts)
