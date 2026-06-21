"""Evidence provenance: the comparable modeling-input identity of a model report.

Kept in its own light module (no matplotlib / harness import) so the API can compute
the live identity to decide fresh-vs-stale without dragging the whole report stack in.
"""

from __future__ import annotations

import hashlib
import json

from backend.decision_engine import config as C
from backend.decision_engine.engine.recommend import engine_provenance

# Bump when the report's SCHEMA/methodology changes in a way that should invalidate a
# previously-generated report even if data/config/calibration are unchanged. Folded into
# the evidence fingerprint so the Model Evidence page can tell a stale report from a fresh
# one. (Distinct from ENGINE_VERSION, which versions the decision engine itself.)
REPORT_VERSION = "report.v1"


def evidence_input_fingerprint() -> str:
    """One comparable hash of the MODELING-INPUT identity a model report was produced
    under: dataset profile + the recommendation's panel data fingerprint + config
    fingerprint + approved-calibration fingerprint + engine version + report version.

    Deliberately EXCLUDES any wall-clock timestamp: this is the identity the curated
    ``/api/model-evidence`` endpoint compares to the ACTIVE recommendation's modeling
    identity to decide fresh vs stale, so it must be reproducible from current engine
    state (a timestamp would make a fresh report read as perpetually stale). The report's
    headline ``data_fingerprint`` stays the CANONICAL-tables hash (mart reconciliation);
    here we use the PANEL hash from ``engine_provenance`` because that is the identity the
    recommendation/ledger carry, so the two sides are comparable."""
    prov = engine_provenance()
    payload = {
        "dataset_profile": C.DATASET_PROFILE,
        "data_fingerprint": prov["data_fingerprint"],
        "config_fingerprint": prov["config_fingerprint"],
        "calibration_fingerprint": prov["calibration_fingerprint"],
        "engine_version": prov["engine_version"],
        "report_version": REPORT_VERSION,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
