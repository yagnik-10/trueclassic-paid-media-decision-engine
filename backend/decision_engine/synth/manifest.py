"""Generated manifest: versions, row counts, and logical fingerprints.

The manifest is the single artifact a reviewer (or CI) checks to confirm a
generation reproduced the pinned dataset. It records the seed, generator/schema
version, Python and key dependency versions, per-table and per-envelope logical
fingerprints, calibration/reference fingerprints, an optional latent-truth
fingerprint, and a combined fingerprint.
"""

from __future__ import annotations

import json
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from backend.decision_engine import config as C
from backend.decision_engine.synth.envelope_writers import build_all_envelopes
from backend.decision_engine.synth.fingerprint import (
    canonical_tables_fingerprint,
    dataset_fingerprint,
    envelope_fingerprint,
    frame_fingerprint,
    full_artifact_fingerprint,
)
from backend.decision_engine.synth.generator import Dataset

GENERATOR_VERSION = "stage0.1"
SCHEMA_VERSION = "stage0.1"
_DEP_PACKAGES = ("numpy", "pandas", "pyarrow", "pydantic", "pandera", "duckdb")


def _dep_versions() -> dict[str, str]:
    out: dict[str, str] = {}
    for pkg in _DEP_PACKAGES:
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            out[pkg] = "not-installed"
    return out


def build_manifest(ds: Dataset, *, seed: int = C.MASTER_SEED, include_latent: bool = False) -> dict:
    envelopes = build_all_envelopes(
        ds.tables["fact_ad_performance"], ds.tables["fact_commerce_truth"]
    )
    table_fps = dataset_fingerprint(ds.tables)
    deps = _dep_versions()
    manifest = {
        "seed": seed,
        "generator_version": GENERATOR_VERSION,
        "schema_version": SCHEMA_VERSION,
        "python_version": platform.python_version(),
        "dependency_versions": deps,
        "row_counts": {name: int(len(df)) for name, df in ds.tables.items()},
        "table_fingerprints": table_fps,
        "envelope_fingerprints": {
            name: envelope_fingerprint(env) for name, env in envelopes.items()
        },
        "reference_fingerprints": {
            "calibration_registry": table_fps["calibration_registry"],
            "dim_sku": table_fps["dim_sku"],
            "dim_campaign": table_fps["dim_campaign"],
        },
        # canonical-tables-only fingerprint and the MAIN full-artifact fingerprint
        "canonical_tables_fingerprint": canonical_tables_fingerprint(ds.tables),
        "full_artifact_fingerprint": full_artifact_fingerprint(
            ds.tables, envelopes, seed=seed,
            generator_version=GENERATOR_VERSION, schema_version=SCHEMA_VERSION,
            dependency_versions=deps,
        ),
    }
    if include_latent:
        # explicit opt-in only; latent truth never ships in the normal path
        manifest["latent_truth_fingerprint"] = frame_fingerprint(ds.scenario_truth)
    return manifest


def write_manifest(ds: Dataset, path: Path | None = None, *, include_latent: bool = False) -> Path:
    path = path or (C.CANONICAL_DIR / "manifest.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(ds, include_latent=include_latent)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return path
