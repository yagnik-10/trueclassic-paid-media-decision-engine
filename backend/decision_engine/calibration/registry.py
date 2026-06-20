"""Synthetic incrementality calibration registry (FINAL_PLAN §6).

Every coefficient carries source, effective period, confidence, scope, and an explicit
``is_synthetic`` flag. The engine decides on *calibrated* (incremental) revenue;
platform-reported revenue is recovered by dividing by the segment coefficient.

Sensitivity what-ifs merge marketer-supplied overrides onto the approved registry —
never silently replacing provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from backend.decision_engine.schemas.canonical import SEGMENTS

_REGISTRY_TABLE = "calibration_registry"


@dataclass(frozen=True)
class CalibrationEntry:
    registry_id: str
    segment: str
    coefficient: float
    source: str
    effective_start: str
    effective_end: str | None
    confidence: str
    scope: str
    is_synthetic: bool


def registry_fingerprint() -> str:
    """Deterministic fingerprint of the APPROVED registry table.

    Pins the base calibration version into a recommendation snapshot, so a stored
    sensitivity result (base registry + recorded overrides) is reproducible and a
    later registry revision is detectable.
    """
    from backend.decision_engine.synth.fingerprint import frame_fingerprint
    from backend.decision_engine.synth.generator import generate

    return frame_fingerprint(generate().tables[_REGISTRY_TABLE])[:16]


def load_registry() -> list[CalibrationEntry]:
    """Full registry rows with provenance (from the deterministic synthetic dataset)."""
    from backend.decision_engine.synth.generator import generate

    reg = generate().tables[_REGISTRY_TABLE]
    out: list[CalibrationEntry] = []
    for row in reg.itertuples(index=False):
        end = row.effective_end
        out.append(CalibrationEntry(
            registry_id=str(row.registry_id),
            segment=str(row.segment),
            coefficient=float(row.coefficient),
            source=str(row.source),
            effective_start=pd.Timestamp(row.effective_start).date().isoformat(),
            effective_end=pd.Timestamp(end).date().isoformat() if pd.notna(end) else None,
            confidence=str(row.confidence),
            scope=str(row.scope),
            is_synthetic=bool(row.is_synthetic),
        ))
    return sorted(out, key=lambda e: e.segment)


def calibration_map(overrides: Mapping[str, float] | None = None) -> dict[str, float]:
    """segment → coefficient, optionally merged with sensitivity overrides."""
    base = {e.segment: e.coefficient for e in load_registry()}
    return apply_overrides(base, overrides)


def apply_overrides(base: Mapping[str, float],
                    overrides: Mapping[str, float] | None) -> dict[str, float]:
    """Merge validated overrides onto the approved registry map."""
    if not overrides:
        return dict(base)
    merged = dict(base)
    for seg, coef in overrides.items():
        if seg not in SEGMENTS:
            raise ValueError(f"unknown calibration segment {seg!r}; expected one of {SEGMENTS}")
        if not (0.0 < coef <= 2.0):
            raise ValueError(f"coefficient for {seg!r} must be in (0, 2], got {coef}")
        merged[seg] = float(coef)
    return merged


def overrides_tuple(overrides: Mapping[str, float] | None) -> tuple[tuple[str, float], ...]:
    """Hashable, deterministic key for scenario identity / cache keys."""
    if not overrides:
        return ()
    return tuple(sorted((seg, float(coef)) for seg, coef in overrides.items()))
