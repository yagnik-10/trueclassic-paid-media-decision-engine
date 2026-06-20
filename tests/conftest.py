"""Shared fixtures: generate the golden dataset once per test session.

The runtime default profile is ``realistic`` (D-035, the primary data), but the
test suite is the deterministic REGRESSION BENCHMARK for the golden known-truth
scenario. We therefore hard-pin the session to ``golden`` BEFORE importing any
backend module (so ``config`` resolves golden paths/default at import). Tests that
exercise the realistic profile pass ``profile="realistic"`` explicitly, which is
env-independent.
"""

from __future__ import annotations

import os

os.environ["TC_DATASET_PROFILE"] = "golden"  # must precede the backend import below

import pytest  # noqa: E402

from backend.decision_engine.synth.generator import Dataset, generate  # noqa: E402


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    return generate()


@pytest.fixture(scope="session")
def tables(dataset: Dataset):
    return dataset.tables
