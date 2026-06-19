"""Latent generator truth must never reach the canonical/model-input path."""

from __future__ import annotations

import tempfile
from pathlib import Path


from backend.decision_engine import config as C
from backend.decision_engine.synth.generator import generate
from backend.decision_engine.synth.persistence import write_all, write_latent_truth

# Fields that are LATENT generator truth and must not appear in model INPUT
# tables (the observable data a model would train on). Note: `marginal_roas`
# legitimately appears on the `recommendation` OUTPUT table as an optimizer
# result, so the check is scoped to input tables only.
LATENT_FIELDS = {
    "marginal_roas",
    "conservative_marginal_roas",
    "spend_to_hard_floor",
    "incremental_avg_roas",
    "platform_avg_roas",
    "noise_cv",
    "beta",
    "alpha",
    "gamma",
    "decay",
}

# Observable, model-input canonical tables (excludes operational OUTPUT tables
# like `recommendation`, which are produced by later stages, not training inputs).
INPUT_TABLES = {
    "fact_ad_performance",
    "dim_campaign",
    "dim_sku",
    "sku_alias",
    "fact_commerce_truth",
    "fact_inventory_snapshot",
    "data_quality_issue",
    "calibration_registry",
}


def test_scenario_truth_available_in_memory(dataset):
    # Tests may access latent truth through the in-memory dataset object only.
    assert not dataset.scenario_truth.empty
    assert "marginal_roas" in dataset.scenario_truth.columns


def test_normal_generation_does_not_persist_latent_truth():
    ds = generate()
    with tempfile.TemporaryDirectory() as d:
        canon = Path(d) / "canonical"
        raw = Path(d) / "raw"
        # mimic the normal write path into a temp location
        import backend.decision_engine.synth.persistence as P

        orig_canon, orig_raw = C.CANONICAL_DIR, C.RAW_DIR
        try:
            P.C.CANONICAL_DIR = canon
            P.C.RAW_DIR = raw
            write_all(ds)  # default: no latent
            files = [p.name for p in canon.rglob("*")] + [p.name for p in raw.rglob("*")]
            assert not any("scenario_truth" in f or "latent" in f for f in files)
        finally:
            P.C.CANONICAL_DIR, P.C.RAW_DIR = orig_canon, orig_raw


def test_latent_fields_absent_from_input_tables(tables):
    for name in INPUT_TABLES:
        leaked = LATENT_FIELDS.intersection(tables[name].columns)
        assert not leaked, f"latent field(s) {leaked} leaked into input table {name}"


def test_canonical_dir_on_disk_has_no_latent_artifacts():
    # The committed/generated canonical dir must not contain scenario_truth.*
    if C.CANONICAL_DIR.exists():
        names = [p.name for p in C.CANONICAL_DIR.iterdir()]
        assert not any("scenario_truth" in n for n in names)


def test_latent_truth_writes_only_under_internal_path():
    ds = generate()
    with tempfile.TemporaryDirectory() as d:
        latent_dir = Path(d) / "internal" / "latent"
        out = write_latent_truth(ds, latent_dir=latent_dir)
        assert out.exists()
        assert "internal" in out.parts and "latent" in out.parts
        assert "canonical" not in out.parts and "raw" not in out.parts
