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

import pytest

from backend.decision_engine.config import MASTER_SEED
from backend.decision_engine.synth import scenario as S
from backend.decision_engine.synth.fingerprint import (
    canonical_tables_fingerprint,
    dataset_fingerprint,
    envelope_fingerprint,
    frame_fingerprint,
    full_artifact_fingerprint,
)
from backend.decision_engine.synth.generator import generate
from backend.decision_engine.synth.manifest import GENERATOR_VERSION, SCHEMA_VERSION, build_manifest

# golden-v4: new-customer derivation recalibrated (D-048 — new_customers derived from
# INCREMENTAL revenue, net of returns, not platform-inflated conversions; _NEW_CUST_RATE
# lowered so portfolio NC-CPA lands ~$29 instead of an implausible ~$5). Only the
# new_customers column changes; ROAS/contribution/allocation are unchanged. Prior fixtures:
#   golden-v1 ($24K)    canonical 8873f413…890a4 · full aa27fe98…6e7e3
#   golden-v2 (scale)   canonical 08643f3f…731e9 · full de83a25f…892a59
#   golden-v3 (econ)    canonical 8a302b78…896c9b0 · full 637647ff…11fe73c2
EXPECTED_CANONICAL_TABLES_FINGERPRINT = (
    "f5eae5f04c8073c8e7b202ec5af7db66efc553d94770e945b6d8a6f50dbbc3fd"
)
EXPECTED_FULL_ARTIFACT_FINGERPRINT = (
    "b49eda30aefc8c92a3804eea31be18e09ca308bd51662d73e9975a0eb177dc0d"
)

# The 'realistic' profile (D-034) shares the latent response truth but adds
# structured volatility + exogenous spend variation. It is pinned separately so
# its reproducibility is guarded WITHOUT making it the regression anchor (golden
# stays the tight known-truth benchmark above). Prior fixtures:
#   realistic-v1 ($24K)  canonical 66b5dd59…a6cc5 · full a7644691…1fe10
#   realistic-v2 (scale) canonical 4fa2a271…30d4a3 · full a31fefee…49ffcf
#   realistic-v3 (econ)  canonical 7ebbdf0b…950b2b · full 399eefaa…acc276
EXPECTED_REALISTIC_CANONICAL_TABLES_FINGERPRINT = (
    "11250e90f2fffea304af8ee446a39513bfa6e81c6973ed86a900165bdc12435a"
)
EXPECTED_REALISTIC_FULL_ARTIFACT_FINGERPRINT = (
    "a0f765f67ba75a7b50776ca99a84ecd449a4e46d141b35056122c0881602068a"
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


def test_realistic_profile_fingerprint_is_pinned_and_distinct():
    # realistic is deterministic and pinned, golden stays unchanged, and the two
    # differ (shared latent truth, different observable data).
    g = build_manifest(generate(MASTER_SEED, profile="golden"))
    r = build_manifest(generate(MASTER_SEED, profile="realistic"))
    assert r["canonical_tables_fingerprint"] == EXPECTED_REALISTIC_CANONICAL_TABLES_FINGERPRINT
    assert r["full_artifact_fingerprint"] == EXPECTED_REALISTIC_FULL_ARTIFACT_FINGERPRINT
    assert g["full_artifact_fingerprint"] == EXPECTED_FULL_ARTIFACT_FINGERPRINT
    assert r["full_artifact_fingerprint"] != g["full_artifact_fingerprint"]


def test_realistic_profile_passes_canonical_schema():
    from backend.decision_engine.schemas.canonical import CANONICAL_SCHEMAS

    ds = generate(MASTER_SEED, profile="realistic")
    for name, df in ds.tables.items():
        schema = CANONICAL_SCHEMAS.get(name)
        if schema is not None:
            schema.validate(df, lazy=True)


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


# --- portfolio-scale mathematical contract (D-039) --------------------------
@pytest.mark.parametrize("k", [1.0, 6.0, 13.0])
def test_portfolio_scale_is_economically_invariant(k):
    """Homogeneous dollar scaling of (s, gamma, beta, ...) must scale revenue by k
    while leaving every RATIO unchanged — average ROAS, marginal ROAS, utilization
    and spend/gamma. This is the analytic contract behind ``PORTFOLIO_SCALE``; it
    guards the migration even if the scenario generator is edited later. Uses the
    production ``_scale_campaign`` helper so the helper itself stays homogeneous."""
    for base in S._UNIT_CAMPAIGNS:
        scaled = S._scale_campaign(base, k)
        # revenue at the operating point scales by exactly k
        assert S.hill_revenue(scaled.base_spend, scaled) == pytest.approx(
            k * S.hill_revenue(base.base_spend, base), rel=1e-9)
        # average + marginal ROAS are invariant
        assert S.average_incremental_roas(scaled.base_spend, scaled) == pytest.approx(
            S.average_incremental_roas(base.base_spend, base), rel=1e-9)
        assert S.hill_marginal_roas(scaled.base_spend, scaled) == pytest.approx(
            S.hill_marginal_roas(base.base_spend, base), rel=1e-9)
        # utilization and spend/gamma ratios are invariant
        assert scaled.base_spend / scaled.daily_cap == pytest.approx(
            base.base_spend / base.daily_cap, rel=1e-12)
        assert scaled.base_spend / scaled.gamma == pytest.approx(
            base.base_spend / base.gamma, rel=1e-12)
        # the dollar LEVELS scale by k
        assert scaled.base_spend == pytest.approx(k * base.base_spend)
        assert scaled.daily_cap == pytest.approx(k * base.daily_cap)
        assert scaled.organic_base == pytest.approx(k * base.organic_base)


def test_active_portfolio_scale_matches_pinned_fixture():
    """Guard the active scale so a stray change to PORTFOLIO_SCALE can't silently
    regenerate the dataset at a different magnitude without a fingerprint bump."""
    assert S.PORTFOLIO_SCALE == 6.0
    assert sum(c.base_spend for c in S.CAMPAIGNS) == pytest.approx(130_800.0)
    assert sum(c.daily_cap for c in S.CAMPAIGNS) == pytest.approx(202_800.0)
