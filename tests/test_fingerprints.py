"""Stable logical fingerprints + manifest, with drift detection.

The MAIN reproducibility fingerprint is the FULL-ARTIFACT fingerprint (canonical
tables + Meta/Google/Shopify envelopes + versions + seed + dependency versions).
A separate canonical-tables-only fingerprint is also pinned.

Regression guard tied to the pinned dependency set (requirements-lock.txt). If a
bump changes logical rendering or dependency versions, regenerate with
``python scripts/generate_synthetic_data.py`` and update the constants below,
recording the bump in docs/DECISIONS.md.
"""

from __future__ import annotations

from backend.decision_engine.config import MASTER_SEED
from backend.decision_engine.synth.fingerprint import (
    canonical_tables_fingerprint,
    dataset_fingerprint,
    envelope_fingerprint,
    frame_fingerprint,
    full_artifact_fingerprint,
)
from backend.decision_engine.synth.generator import generate
from backend.decision_engine.synth.manifest import GENERATOR_VERSION, SCHEMA_VERSION, build_manifest

EXPECTED_CANONICAL_TABLES_FINGERPRINT = (
    "8873f4137c3a3079e22553476de7c1687610b27aea1c6800cbf90cdbb14890a4"
)
EXPECTED_FULL_ARTIFACT_FINGERPRINT = (
    "16d51091b48a889d57d0f8a33136115fe1a1f58a8e16f73afafc82f3f48892a5"
)


def _envelopes(tables):
    from backend.decision_engine.synth.envelope_writers import build_all_envelopes

    return build_all_envelopes(tables["fact_ad_performance"], tables["fact_commerce_truth"])


def _full(tables, deps):
    return full_artifact_fingerprint(
        tables, _envelopes(tables), seed=MASTER_SEED,
        generator_version=GENERATOR_VERSION, schema_version=SCHEMA_VERSION,
        dependency_versions=deps,
    )


def test_canonical_tables_fingerprint_matches_pinned_value():
    ds = generate(MASTER_SEED)
    assert canonical_tables_fingerprint(ds.tables) == EXPECTED_CANONICAL_TABLES_FINGERPRINT


def test_full_artifact_fingerprint_matches_pinned_value(dataset):
    # The full-artifact fingerprint is computed by the manifest (the canonical place).
    m = build_manifest(dataset)
    assert m["full_artifact_fingerprint"] == EXPECTED_FULL_ARTIFACT_FINGERPRINT


def test_per_table_fingerprints_present(tables):
    fps = dataset_fingerprint(tables)
    assert len(fps) == 13
    assert all(isinstance(v, str) and len(v) == 64 for v in fps.values())


# --- drift detection on the FULL fingerprint --------------------------------
def test_canonical_drift_changes_full_fingerprint(tables):
    deps = {"numpy": "x"}
    base = _full(tables, deps)
    mutated = {k: v.copy() for k, v in tables.items()}
    mutated["fact_ad_performance"].loc[mutated["fact_ad_performance"].index[0], "spend"] += 1.0
    assert _full(mutated, deps) != base


def test_raw_envelope_drift_changes_full_fingerprint(tables):
    from backend.decision_engine.synth.envelope_writers import build_all_envelopes

    deps = {"numpy": "x"}
    base = full_artifact_fingerprint(
        tables, _envelopes(tables), seed=MASTER_SEED,
        generator_version=GENERATOR_VERSION, schema_version=SCHEMA_VERSION,
        dependency_versions=deps,
    )
    envs = build_all_envelopes(tables["fact_ad_performance"], tables["fact_commerce_truth"])
    envs["meta_insights"]["data"][0]["spend"] = "999999.00"
    drifted = full_artifact_fingerprint(
        tables, envs, seed=MASTER_SEED, generator_version=GENERATOR_VERSION,
        schema_version=SCHEMA_VERSION, dependency_versions=deps,
    )
    assert drifted != base


def test_dependency_version_drift_changes_full_fingerprint(tables):
    assert _full(tables, {"numpy": "1"}) != _full(tables, {"numpy": "2"})


def test_serialization_formatting_does_not_change_logical_fingerprint(tables):
    # Reordering rows and round-tripping through CSV must not change the logical
    # fingerprint (it hashes normalized content, not storage bytes).
    df = tables["dim_sku"]
    shuffled = df.sample(frac=1.0, random_state=7).reset_index(drop=True)
    assert frame_fingerprint(shuffled) == frame_fingerprint(df)
    env = _envelopes(tables)["shopify_commerce"]
    import json

    reparsed = json.loads(json.dumps(env))  # formatting round-trip
    assert envelope_fingerprint(reparsed) == envelope_fingerprint(env)


# --- manifest ---------------------------------------------------------------
def test_manifest_has_required_sections(dataset):
    m = build_manifest(dataset)
    for key in (
        "seed", "generator_version", "schema_version", "python_version",
        "dependency_versions", "row_counts", "table_fingerprints",
        "envelope_fingerprints", "reference_fingerprints",
        "canonical_tables_fingerprint", "full_artifact_fingerprint",
    ):
        assert key in m
    assert m["canonical_tables_fingerprint"] == EXPECTED_CANONICAL_TABLES_FINGERPRINT
    assert m["full_artifact_fingerprint"] == EXPECTED_FULL_ARTIFACT_FINGERPRINT
    assert set(m["envelope_fingerprints"]) == {"meta_insights", "google_ads", "shopify_commerce"}
    assert "latent_truth_fingerprint" not in m


def test_manifest_latent_fingerprint_only_on_opt_in(dataset):
    assert "latent_truth_fingerprint" in build_manifest(dataset, include_latent=True)
