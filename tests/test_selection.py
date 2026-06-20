"""Shared BAU model-selection policy (engine/selection.py).

One frozen selector is used by BOTH the live engine and the evaluation report, so
they can never disagree on the selected model. These tests cover the pure
promotion policy (no XGBoost training — that lives in `make model-report`) and the
leakage-free fold design.
"""

from __future__ import annotations

from backend.decision_engine.engine import selection as SEL


# --- pure promotion policy (baseline-default, XGBoost must clear every bar) ---
def test_material_win_promotes_xgb():
    model, reason = SEL.decide(improvement=0.24, fold_wins=2, n_folds=3,
                               xgb_bias_frac=0.05, base_bias_frac=0.05)
    assert model == SEL.XGB_MODEL
    assert "promoted_xgb" in reason


def test_immaterial_improvement_falls_back():
    # beats the baseline, but by less than the material bar → baseline wins
    model, reason = SEL.decide(improvement=0.02, fold_wins=3, n_folds=3,
                               xgb_bias_frac=0.05, base_bias_frac=0.05)
    assert model == SEL.BASELINE_MODEL
    assert "< 5% bar" in reason


def test_promotion_threshold_is_inclusive_and_uses_raw_fraction():
    # exactly at the bar promotes; just under does not (the gate uses the RAW
    # fraction, never the rounded display %, so a 4.96% case cannot be promoted)
    assert SEL.decide(0.0500, 3, 3, 0.05, 0.05)[0] == SEL.XGB_MODEL
    assert SEL.decide(0.0499, 3, 3, 0.05, 0.05)[0] == SEL.BASELINE_MODEL
    # rounds to "5.0%" for display but is < 0.05 raw → MUST still fall back
    just_under = 0.04996
    assert round(just_under * 100, 2) == 5.0          # display would read 5.0%
    assert SEL.decide(just_under, 3, 3, 0.05, 0.05)[0] == SEL.BASELINE_MODEL


def test_minority_fold_wins_falls_back():
    model, reason = SEL.decide(improvement=0.30, fold_wins=1, n_folds=3,
                               xgb_bias_frac=0.05, base_bias_frac=0.05)
    assert model == SEL.BASELINE_MODEL
    assert "won only 1/3 folds" in reason


def test_materially_worse_bias_blocks_promotion():
    model, reason = SEL.decide(improvement=0.30, fold_wins=3, n_folds=3,
                               xgb_bias_frac=0.40, base_bias_frac=0.05)
    assert model == SEL.BASELINE_MODEL
    assert "worse bias" in reason


def test_selection_folds_are_leakage_free():
    # every fold's 7-day-forward target must end strictly before the harness test
    # start (168), so selecting a model never consults the untouched test period
    from backend.decision_engine.eval.harness import TEST_START_T

    last_val_target_end = max(hi for _, hi in SEL._SELECTION_FOLDS) + (SEL._GAP - 1)
    assert last_val_target_end < TEST_START_T


def test_engine_and_report_use_the_same_selector():
    # structural guarantee: both call select_models, so a single selection drives
    # the optimizer's anchor AND the report's "selected_model" column
    import inspect

    from backend.decision_engine.engine import bau_forecast
    from backend.decision_engine.eval import harness

    assert "select_models" in inspect.getsource(bau_forecast.forecast)
    assert "select_models" in inspect.getsource(harness.evaluate_forecast)
    assert bau_forecast.select_models is harness.select_models is SEL.select_models
