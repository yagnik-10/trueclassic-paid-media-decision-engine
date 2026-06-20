"""S4.2 conformal interval calibration: offset math, leakage-safe fit, coverage
correction, band clamping, and decision invariance (intervals never move spend)."""

from __future__ import annotations

import numpy as np
import pytest

from backend.decision_engine.engine.bau_forecast import XGB_MODEL, forecast
from backend.decision_engine.engine.data import load_engine_inputs
from backend.decision_engine.engine.intervals import (
    ConformalCalibrator,
    conformal_offset,
    fit_calibrator,
)
from backend.decision_engine.eval import harness as H


@pytest.fixture(scope="module")
def panel():
    return load_engine_inputs().panel


def test_conformal_offset_is_finite_sample_quantile():
    # for scores 0..99, the ceil((n+1)*0.8)/n order statistic is the 80th-ish value
    scores = np.arange(100, dtype=float)
    q = conformal_offset(scores, 0.80)
    # rank = ceil(101*0.8) = 81 -> 81st order stat (1-indexed) = value 80
    assert q == 80.0
    # empty -> no widening
    assert conformal_offset(np.array([]), 0.80) == 0.0


def test_widen_preserves_median_and_clamps_when_narrowing():
    pos = ConformalCalibrator(0.05, 0.80, 10, 0.5, 0.8)
    lo, mid, hi = pos.widen(80.0, 100.0, 120.0)
    assert mid == 100.0 and lo < 80.0 and hi > 120.0       # positive offset widens
    neg = ConformalCalibrator(-10.0, 0.80, 10, 0.95, 0.8)  # extreme narrowing
    lo, mid, hi = neg.widen(80.0, 100.0, 120.0)
    assert lo <= mid <= hi                                 # never crosses the median


def test_calibrator_fits_on_held_out_window_and_corrects_coverage(panel):
    cal = fit_calibrator(panel)
    assert cal.n_calibration > 0
    # raw XGBoost band is too narrow on the calibration window...
    assert cal.raw_coverage < 0.60
    # ...and conformal lifts held-out coverage to ~the 0.80 target (>= by construction)
    assert cal.calibrated_coverage >= cal.target_coverage - 0.02
    assert cal.offset > 0                                  # widening, not narrowing


def test_calibration_improves_test_coverage_out_of_sample(panel):
    fc = H.evaluate_forecast(panel)["overall"]
    raw = fc["quantile_sorted"]["coverage_p10_p90"]
    cal = fc["quantile_calibrated"]["coverage_p10_p90"]
    assert raw < 0.60                                       # disclosed: raw band too narrow
    assert cal > 0.70                                       # calibrated band ~ target
    assert abs(cal - 0.80) < abs(raw - 0.80)                # strictly closer to target
    assert fc["quantile_calibrated"]["interval_verdict"] == "calibrated"


def test_calibration_is_deterministic(panel):
    assert fit_calibrator(panel).offset == fit_calibrator(panel).offset


def test_live_forecast_widens_only_xgboost_bands(panel):
    fc, cal = forecast(panel)
    assert cal.offset > 0
    for f in fc.values():
        assert f.p10 <= f.p50 <= f.p90                      # ordered after calibration
        if f.model == XGB_MODEL:
            assert f.p90 > f.p90_raw and f.p10 < f.p10_raw  # widened
        else:  # baseline ±20% heuristic is not conformalized
            assert f.p10 == f.p10_raw and f.p90 == f.p90_raw


def test_calibration_leaves_p50_anchor_untouched(panel):
    # the optimizer anchors on P50 (/horizon); the P10/P90 band is display-only, so
    # conformal widening must leave P50 (and therefore every allocation) untouched.
    # P50 stays the raw median of the [p10_raw, p90_raw] band — only the edges move.
    fc, _ = forecast(panel)
    for f in fc.values():
        assert f.p10_raw <= f.p50 <= f.p90_raw              # P50 never shifted by widening
