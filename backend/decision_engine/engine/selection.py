"""Shared BAU model-selection policy (Model A).

ONE selector, used by BOTH the live engine (`bau_forecast.forecast`) and the
evaluation harness (`eval/harness.evaluate_forecast`), so the model the optimizer
actually uses and the model the report scores can never disagree.

Selection is frozen on PRE-TEST chronological folds only (gap-aware, t < the
harness test start) — the untouched test period is never consulted to pick a
model, preserving evaluation integrity. The report may still score the frozen
selection on the test period; it just cannot change it.

Policy (deliberately baseline-default): the trailing-14d baseline wins unless
XGBoost clears a *material* bar — it must beat the best baseline's pooled WAPE by
``MATERIAL_WAPE_IMPROVEMENT`` AND win a majority of folds AND not be materially
more biased. Each decision returns auditable metadata (per-fold wins, pooled
WAPE/bias, improvement, threshold, reason).

Deterministic: fixed seed + single-threaded XGBoost (see ``_xgb``).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from backend.decision_engine.config import LABEL_MATURITY_DAYS, MASTER_SEED
from backend.decision_engine.engine.baselines import same_weekday_last_week, trailing_14d

# Feature set + quantiles are defined HERE (the model's single source of truth);
# bau_forecast and the harness import them from this module.
_FEATURES = [
    "spend", "adstock_spend", "dow", "trend", "spend_lag1", "spend_roll7", "rev_roll7",
    "sin_7_1", "cos_7_1", "sin_7_2", "cos_7_2", "sin_365_1", "cos_365_1",
]
_GAP = LABEL_MATURITY_DAYS
_QUANTILES = (0.1, 0.5, 0.9)
MIN_TRAIN = 60

# Promotion bar (the marketer's trust knob): XGBoost is only promoted over the
# baseline when it beats the best baseline's pooled WAPE by at least this fraction.
MATERIAL_WAPE_IMPROVEMENT = 0.05
# Block promotion if XGBoost is BOTH more biased than the baseline AND its pooled
# |bias|/mean(y) exceeds this — a materially-worse-bias guard.
MAX_BIAS_FRACTION = 0.15

# Pre-test selection folds: (val_lo, val_hi) day-index windows; each fold trains on
# t <= val_lo - GAP. val_hi (161) + 6 == 167 < the harness test start (168), so no
# forward-7 target ever spans into the test period — selection is leakage-free.
_SELECTION_FOLDS: tuple[tuple[int, int], ...] = ((112, 126), (127, 147), (148, 161))

XGB_MODEL = "xgboost_quantile"
BASELINE_MODEL = "baseline_trailing_14d"        # default fallback name
SAME_WEEKDAY_MODEL = "baseline_same_weekday"
BASELINE_MODELS = (BASELINE_MODEL, SAME_WEEKDAY_MODEL)


@dataclass(frozen=True)
class ModelChoice:
    """Auditable per-campaign selection decision (frozen on pre-test folds)."""
    campaign_id: str
    selected_model: str
    xgb_wape: float | None        # pooled across selection folds
    baseline_wape: float | None
    improvement_pct: float | None  # (baseline - xgb) / baseline, pooled
    fold_wins: int                 # folds where xgb beat the best baseline
    n_folds: int                   # eligible folds (enough train rows)
    threshold: float
    reason: str


def _xgb(alpha: float) -> XGBRegressor:
    return XGBRegressor(
        n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.9,
        min_child_weight=5, random_state=MASTER_SEED, n_jobs=1,
        objective="reg:quantileerror", quantile_alpha=alpha,
        monotone_constraints={"spend": 1, "adstock_spend": 1},
    )


def _wape(y: np.ndarray, p: np.ndarray) -> float:
    d = float(np.abs(y).sum())
    return float(np.abs(p - y).sum() / d) if d else float("nan")


def decide(improvement: float, fold_wins: int, n_folds: int,
           xgb_bias_frac: float, base_bias_frac: float,
           baseline_model: str = BASELINE_MODEL) -> tuple[str, str]:
    """The pure promotion policy (no training) — XGBoost must clear ALL bars.

    Returns ``(selected_model, reason)``. The fallback is the *champion baseline*
    (``baseline_model`` — the specific simple model with the lower pooled WAPE), so
    the model compared against is exactly the model deployed. XGBoost is promoted
    only when it beats that champion's pooled WAPE by the material margin, wins a
    majority of folds, and is not materially more biased.
    """
    wins_majority = fold_wins * 2 >= n_folds
    worse_bias = xgb_bias_frac > base_bias_frac and xgb_bias_frac > MAX_BIAS_FRACTION
    short = baseline_model.replace("baseline_", "")
    if improvement >= MATERIAL_WAPE_IMPROVEMENT and wins_majority and not worse_bias:
        return XGB_MODEL, (f"promoted_xgb: beats {short} baseline by {improvement * 100:.1f}% "
                           f"WAPE, won {fold_wins}/{n_folds} folds")
    if improvement < MATERIAL_WAPE_IMPROVEMENT:
        why = f"improvement {improvement * 100:.1f}% < {MATERIAL_WAPE_IMPROVEMENT * 100:.0f}% bar"
    elif not wins_majority:
        why = f"won only {fold_wins}/{n_folds} folds"
    else:
        why = f"materially worse bias ({xgb_bias_frac:.2f} vs {base_bias_frac:.2f})"
    return baseline_model, f"fallback_{short}: {why}"


def _baseline_pred(g_full: pd.DataFrame, rows: pd.DataFrame) -> np.ndarray:
    """Best-baseline (trailing-14d / same-weekday) prediction per row, using only
    history up to each row's day index (no peeking forward)."""
    t14, tsw = [], []
    for t in rows["t"].to_numpy():
        hist = g_full[g_full["t"] <= t]
        v14 = trailing_14d(hist)
        vsw = same_weekday_last_week(hist)
        t14.append(float(v14) if v14 is not None else np.nan)
        tsw.append(float(vsw) if vsw is not None else np.nan)
    return np.asarray(t14, dtype=float), np.asarray(tsw, dtype=float)


def select_models(panel: pd.DataFrame) -> dict[str, ModelChoice]:
    """Frozen per-campaign model selection on pre-test folds (test never used)."""
    out: dict[str, ModelChoice] = {}
    for cid, g in panel.groupby("campaign_id", sort=True):
        g = g.sort_values("t").reset_index(drop=True)
        xgb_err, b14_err, bsw_err, y_all = [], [], [], []
        n_folds = 0
        enough_train = False
        for val_lo, val_hi in _SELECTION_FOLDS:
            tr = g[(g["t"] <= val_lo - _GAP) & g["target_mature"]]
            va = g[(g["t"] >= val_lo) & (g["t"] <= val_hi) & g["target_mature"]]
            if len(tr) < MIN_TRAIN or va.empty:
                continue
            enough_train = True
            n_folds += 1
            xp = np.asarray(_xgb(0.5).fit(tr[_FEATURES], tr["target_fwd7"])
                            .predict(va[_FEATURES]), dtype=float)
            b14, bsw = _baseline_pred(g, va)
            xgb_err.append(xp)
            b14_err.append(b14)
            bsw_err.append(bsw)
            y_all.append(va["target_fwd7"].to_numpy(float))

        if not enough_train or n_folds == 0:
            out[cid] = ModelChoice(cid, BASELINE_MODEL, None, None, None, 0, 0,
                                   MATERIAL_WAPE_IMPROVEMENT,
                                   "fallback_trailing_14d: insufficient pre-test training data")
            continue

        y = np.concatenate(y_all)
        xp = np.concatenate(xgb_err)
        b14, bsw = np.concatenate(b14_err), np.concatenate(bsw_err)
        # champion baseline = the single simple model with the lower POOLED WAPE; it is
        # both the comparison baseline AND the deployed fallback (D-030 coherence).
        w14, wsw = _wape(y, b14), _wape(y, bsw)
        if np.isnan(wsw) or w14 <= wsw:
            baseline_model, bp = BASELINE_MODEL, b14
        else:
            baseline_model, bp = SAME_WEEKDAY_MODEL, bsw
        # fold wins are counted against that same champion baseline (consistent basis)
        champ_err = b14_err if baseline_model == BASELINE_MODEL else bsw_err
        fold_wins = sum(1 for xe, be, ye in zip(xgb_err, champ_err, y_all)
                        if _wape(ye, xe) < _wape(ye, be))

        xgb_wape, base_wape = _wape(y, xp), _wape(y, bp)
        mean_y = float(np.abs(y).mean()) or 1.0
        xgb_bias_frac = abs(float(np.mean(xp - y))) / mean_y
        base_bias_frac = abs(float(np.mean(bp - y))) / mean_y
        improvement = (base_wape - xgb_wape) / base_wape if base_wape else 0.0
        model, reason = decide(improvement, fold_wins, n_folds, xgb_bias_frac,
                               base_bias_frac, baseline_model)

        out[cid] = ModelChoice(
            campaign_id=cid, selected_model=model,
            xgb_wape=round(xgb_wape, 4), baseline_wape=round(base_wape, 4),
            improvement_pct=round(improvement * 100, 2), fold_wins=fold_wins,
            n_folds=n_folds, threshold=MATERIAL_WAPE_IMPROVEMENT, reason=reason,
        )
    return out
