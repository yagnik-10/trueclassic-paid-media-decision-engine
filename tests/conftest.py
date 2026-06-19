"""Shared fixtures: generate the golden dataset once per test session."""

from __future__ import annotations

import pytest

from backend.decision_engine.synth.generator import Dataset, generate


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    return generate()


@pytest.fixture(scope="session")
def tables(dataset: Dataset):
    return dataset.tables
