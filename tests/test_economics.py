"""The scale-floor threshold is economically derived, not a magic number.

Stage 0 scope: only the break-even / hard-scale-floor economics used to
characterize the scenario's latent truth. Efficiency hurdles, reserve modes, and
optimizer policy belong to later stages and are intentionally absent here.
"""

from __future__ import annotations

import pytest

from backend.decision_engine import config as C
from backend.decision_engine import economics as E


def test_breakeven_is_inverse_margin():
    assert E.break_even_roas(0.5) == pytest.approx(2.0)
    assert E.break_even_roas(E.WEIGHTED_CONTRIBUTION_MARGIN) == pytest.approx(E.BREAKEVEN_ROAS)


def test_hard_floor_derives_from_breakeven_and_safety():
    assert E.HARD_SCALE_FLOOR == pytest.approx(E.BREAKEVEN_ROAS * C.HARD_FLOOR_SAFETY)
    assert E.HARD_SCALE_FLOOR > E.BREAKEVEN_ROAS   # a small cushion over break-even


def test_floor_increases_when_margin_shrinks():
    # Thinner margin -> higher break-even -> higher floor.
    assert E.hurdle(0.40, 1.05) > E.hurdle(0.60, 1.05)


def test_floor_increases_with_safety_multiplier():
    assert E.hurdle(0.55, 1.2) > E.hurdle(0.55, 1.05)


def test_weighted_margin_in_expected_band():
    assert 0.50 <= E.WEIGHTED_CONTRIBUTION_MARGIN <= 0.65
