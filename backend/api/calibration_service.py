"""API service for the incrementality calibration registry (S4.3)."""

from __future__ import annotations

from backend.api.schemas import CalibrationRegistryEntry, CalibrationRegistryResponse
from backend.decision_engine.calibration.registry import load_registry


def registry() -> CalibrationRegistryResponse:
    entries = [
        CalibrationRegistryEntry(
            registry_id=e.registry_id,
            segment=e.segment,
            coefficient=e.coefficient,
            source=e.source,
            effective_start=e.effective_start,
            effective_end=e.effective_end,
            confidence=e.confidence,
            scope=e.scope,
            is_synthetic=e.is_synthetic,
        )
        for e in load_registry()
    ]
    return CalibrationRegistryResponse(
        entries=entries,
        note="Every coefficient is explicitly synthetic — standing in for geo-lift / "
             "conversion-lift / MMM / finance-approved factors. The optimizer decides on "
             "calibrated (incremental) revenue; platform-reported revenue is context only.",
    )
