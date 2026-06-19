"""Two-level envelope/record validation with quarantine.

1. Validate the OUTER envelope structure (keys present, records is a list).
2. Validate each contained record INDEPENDENTLY against its Pydantic model.
3. Keep valid records flowing; quarantine invalid ones with full provenance
   (platform, source index/key, validation errors, raw payload, timestamp).

A single malformed record must not discard the whole export.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pydantic


class EnvelopeStructureError(ValueError):
    """The outer envelope itself is malformed (not merely a bad record)."""


@dataclass
class QuarantinedRecord:
    platform: str
    source_index: int
    source_key: str | None
    reason: str
    errors: list[dict[str, Any]]
    raw_payload: Any
    # Deterministic ingestion as-of timestamp (the feed pull date), NOT wall-clock,
    # so the ingestion report is reproducible. None when validated standalone.
    detected_at: str | None = None
    resolution_status: str = "quarantined"


@dataclass
class ValidationResult:
    platform: str
    valid: list[Any] = field(default_factory=list)
    valid_indices: list[int] = field(default_factory=list)  # source position of each valid record
    quarantined: list[QuarantinedRecord] = field(default_factory=list)

    @property
    def n_valid(self) -> int:
        return len(self.valid)

    @property
    def n_quarantined(self) -> int:
        return len(self.quarantined)


def quarantine(platform: str, index: int, key: str | None, reason: str,
               errors: list[dict[str, Any]], raw: Any,
               detected_at: str | None = None) -> QuarantinedRecord:
    return QuarantinedRecord(
        platform=platform, source_index=index, source_key=key, reason=reason,
        errors=errors, raw_payload=raw, detected_at=detected_at,
    )


def validate_records(
    records: list[Any],
    record_model: type[pydantic.BaseModel],
    platform: str,
    key_field: str | None = None,
    as_of: str | None = None,
) -> ValidationResult:
    """Validate each record independently; quarantine failures, keep successes."""
    result = ValidationResult(platform=platform)
    for i, rec in enumerate(records):
        try:
            result.valid.append(record_model.model_validate(rec))
            result.valid_indices.append(i)
        except pydantic.ValidationError as exc:
            key = rec.get(key_field) if key_field and isinstance(rec, dict) else None
            result.quarantined.append(
                quarantine(
                    platform, i, key, "schema_invalid",
                    [{"loc": list(e["loc"]), "type": e["type"], "msg": e["msg"]}
                     for e in exc.errors()],
                    rec, detected_at=as_of,
                )
            )
    return result


def validate_envelope_records(
    payload: dict,
    *,
    outer_required_keys: tuple[str, ...],
    records_key: str,
    record_model: type[pydantic.BaseModel],
    platform: str,
    key_field: str | None = None,
    as_of: str | None = None,
) -> ValidationResult:
    """Accept a structurally-valid envelope; validate records (bad ones quarantined)."""
    if not isinstance(payload, dict):
        raise EnvelopeStructureError(f"{platform}: envelope is not an object")
    missing = [k for k in outer_required_keys if k not in payload]
    if missing:
        raise EnvelopeStructureError(f"{platform}: envelope missing keys {missing}")
    records = payload.get(records_key)
    if not isinstance(records, list):
        raise EnvelopeStructureError(f"{platform}: '{records_key}' is not a list")
    return validate_records(records, record_model, platform, key_field, as_of=as_of)
