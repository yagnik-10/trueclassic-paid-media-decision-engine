"""Evaluation-harness correctness: target alignment, no-leak splits, metric math.

Asserts the report's evaluation is *correct* (not that the model hits a number).
Keeps it fast — no XGBoost training here (that is exercised by `make model-report`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.decision_engine.engine.data import load_engine_inputs
from backend.decision_engine.eval import harness as H
from backend.decision_engine.eval import metrics as M


@pytest.fixture(scope="module")
def panel():
    return load_engine_inputs().panel


def test_target_is_sum_of_days_t_to_t_plus_6(panel):
    co = H.verify_correctness(panel)
    assert co["target_is_sum_t_to_t_plus_6"] is True
    ex = co["explicit_example"]
    assert len(ex["window_dates"]) == 7
    assert abs(ex["sum_days_t_to_t6"] - ex["stored_target_fwd7"]) < 1e-6


def test_exclusions_and_chronology(panel):
    co = H.verify_correctness(panel)
    assert co["immature_labels_excluded"] is True
    assert co["duplicates_excluded_in_panel"] is True
    assert co["chronological_splits"] is True


def test_splits_have_no_forward_target_leakage(panel):
    p = H.assign_split(panel)
    tr = p[p.split == "train"]["t"].max()
    va_lo, va_hi = p[p.split == "val"]["t"].min(), p[p.split == "val"]["t"].max()
    te_lo = p[p.split == "test"]["t"].min()
    # a 7-day-forward target from the last train row must end before val starts
    assert tr + 6 < va_lo
    assert va_hi + 6 < te_lo
    assert (va_lo - tr) >= H.GAP and (te_lo - va_hi) >= H.GAP


def test_immature_rows_never_in_train_val_test(panel):
    p = H.assign_split(panel)
    modeling = p[p.split.isin(["train", "val", "test"])]
    assert bool(modeling["target_mature"].all())


def test_point_metrics_are_well_defined():
    y = np.array([100.0, 200.0, 300.0, 400.0])
    perfect = M.point_metrics(y, y.copy())
    assert perfect["wape"] == 0.0 and perfect["mae"] == 0.0 and perfect["bias_me"] == 0.0
    biased = M.point_metrics(y, y + 10.0)             # systematic over-prediction
    assert biased["bias_me"] == 10.0 and biased["wape"] > 0
    assert biased["approx_point_accuracy"] == M._r(1.0 - biased["wape"])


def test_quantile_metrics_count_raw_crossings_without_sorting():
    y = np.array([100.0, 100.0, 100.0])
    p10 = np.array([90.0, 110.0, 80.0])   # row 2 crosses (p10 > p90)
    p50 = np.array([100.0, 100.0, 100.0])
    p90 = np.array([110.0, 105.0, 120.0])
    q = M.quantile_metrics(y, p10, p50, p90)
    assert q["raw_crossings"] == 1
    assert 0.0 <= q["coverage_p10_p90"] <= 1.0
    assert q["calibration_error"] == M._r(q["coverage_p10_p90"] - 0.80)


def test_deployed_interval_metrics_pool_and_split_by_model():
    """The DEPLOYED-band coverage (what the engine serves per champion) pools all test
    rows and splits by model — the honest interval figure, distinct from the
    XGBoost-quantile-only conformal diagnostic. Pure aggregation; no training."""
    # 2 XGBoost rows (both covered) + 2 baseline rows (one covered, one not).
    frame = pd.DataFrame({
        "y":     [100.0, 100.0, 100.0, 100.0],
        "p10":   [ 90.0,  95.0,  80.0, 200.0],   # last baseline row excludes y=100
        "p90":   [110.0, 105.0, 120.0, 300.0],
        "model": ["xgboost_quantile", "xgboost_quantile",
                  "baseline_trailing_14d", "baseline_trailing_14d"],
        "cid":   ["A", "A", "B", "B"],
    })
    dep = H.deployed_interval_metrics(frame)
    assert dep["n"] == 4
    assert dep["coverage_p10_p90"] == 0.75                 # 3 of 4 covered
    assert dep["by_model"]["xgboost_quantile"]["coverage_p10_p90"] == 1.0
    assert dep["by_model"]["baseline_trailing_14d"]["coverage_p10_p90"] == 0.5
    assert dep["by_model"]["xgboost_quantile"]["mean_interval_width"] == 15.0
    assert dep["n_xgboost_campaigns"] == 1                 # only campaign A is XGBoost
    assert H.deployed_interval_metrics(pd.DataFrame()) == {}


def test_pinball_loss_minimized_at_true_quantile():
    rng = np.random.default_rng(0)
    y = rng.normal(0, 1, 2000)
    q90 = float(np.quantile(y, 0.9))
    at_true = M.pinball_loss(y, np.full_like(y, q90), 0.9)
    off = M.pinball_loss(y, np.full_like(y, q90 + 0.5), 0.9)
    assert at_true < off
