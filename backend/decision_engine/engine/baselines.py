"""Simple, visible forecasting baselines for the 7-day calibrated-revenue target.

The learned BAU model is promoted only if it beats these on time-aware
validation; otherwise the safe baseline is the fallback (FINAL_PLAN section 5).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FORWARD_DAYS = 7


def _walk_forward_mae(g: pd.DataFrame, predict) -> float:
    """Mean abs error of a 7-day-forward predictor over a chronological holdout."""
    g = g.sort_values("date").reset_index(drop=True)
    y = g["target_fwd7"].to_numpy(float)
    errs = []
    for i in range(21, len(g)):
        if not g["target_mature"].iloc[i] or np.isnan(y[i]):
            continue
        pred = predict(g.iloc[:i])
        if pred is not None and not np.isnan(pred):
            errs.append(abs(pred - y[i]))
    return float(np.mean(errs)) if errs else float("nan")


def trailing_14d(history: pd.DataFrame) -> float:
    """Mean daily calibrated revenue over the last 14 days × 7."""
    tail = history.tail(14)["calibrated_revenue"]
    return float(tail.mean() * FORWARD_DAYS)


def same_weekday_last_week(history: pd.DataFrame) -> float | None:
    """Sum of the calibrated revenue over the previous 7 days (same weekdays)."""
    if len(history) < 7:
        return None
    return float(history.tail(7)["calibrated_revenue"].sum())


def baseline_maes(panel: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Per-campaign walk-forward MAE for each baseline."""
    out: dict[str, dict[str, float]] = {}
    for cid, g in panel.groupby("campaign_id", sort=True):
        out[cid] = {
            "trailing_14d": _walk_forward_mae(g, trailing_14d),
            "same_weekday": _walk_forward_mae(g, same_weekday_last_week),
        }
    return out
