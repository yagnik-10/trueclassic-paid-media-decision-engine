"""Determinism: a pinned seed reproduces the dataset exactly."""

from __future__ import annotations

from backend.decision_engine.config import MASTER_SEED
from backend.decision_engine.synth.fingerprint import combined_fingerprint, dataset_fingerprint
from backend.decision_engine.synth.generator import generate


def test_two_runs_same_seed_identical():
    a = generate(MASTER_SEED)
    b = generate(MASTER_SEED)
    assert dataset_fingerprint(a.tables) == dataset_fingerprint(b.tables)


def test_row_counts_stable_across_runs():
    a = generate(MASTER_SEED)
    b = generate(MASTER_SEED)
    assert {k: len(v) for k, v in a.tables.items()} == {k: len(v) for k, v in b.tables.items()}


def test_different_seed_changes_values_not_shape():
    a = generate(MASTER_SEED)
    b = generate(MASTER_SEED + 1)
    # Shapes/defect structure are seed-independent...
    assert {k: len(v) for k, v in a.tables.items()} == {k: len(v) for k, v in b.tables.items()}
    assert a.defect_counts == b.defect_counts
    # ...but the stochastic content differs.
    assert combined_fingerprint(a.tables) != combined_fingerprint(b.tables)


def test_defect_counts_deterministic():
    a = generate(MASTER_SEED)
    b = generate(MASTER_SEED)
    assert a.defect_counts == b.defect_counts
