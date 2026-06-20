"""Model A — XGBoost quantile BAU forecast (P10/P50/P90 of 7-day net revenue).

Predicts the 7-day-forward calibrated revenue at the current operating point.
Monotonic in spend, trained only on label-mature rows. The model CHOICE (XGBoost
vs the trailing-14d baseline) is made by the shared, frozen selector in
``engine/selection.py`` — the exact same policy the evaluation report uses, so
the model the optimizer consumes and the model the report scores never disagree.
Deterministic: fixed seed + single-threaded.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.decision_engine.engine.baselines import same_weekday_last_week, trailing_14d
from backend.decision_engine.engine.intervals import ConformalCalibrator, fit_calibrator
from backend.decision_engine.engine.selection import (  # re-exported for the harness
    _FEATURES,
    _QUANTILES,
    SAME_WEEKDAY_MODEL,
    XGB_MODEL,
    ModelChoice,
    _xgb,
    select_models,
)

__all__ = ["CampaignForecast", "forecast", "_FEATURES", "_xgb"]


@dataclass
class CampaignForecast:
    campaign_id: str
    p10: float            # CALIBRATED P10/P90 band (conformal-widened)
    p50: float
    p90: float
    model: str            # "xgboost_quantile" or "baseline_trailing_14d"
    selection: ModelChoice  # auditable shared-selector metadata (frozen on pre-test folds)
    p10_raw: float = 0.0  # pre-conformal band (transparency)
    p90_raw: float = 0.0


def forecast(panel) -> tuple[dict[str, CampaignForecast], ConformalCalibrator]:
    """Returns per-campaign forecasts (with conformal-CALIBRATED P10/P90) plus the
    portfolio conformal calibrator (offset + measured coverage), for audit/UI."""
    choices = select_models(panel)        # one frozen decision per campaign
    cal = fit_calibrator(panel)           # portfolio conformal offset (train->val, no leakage)
    out: dict[str, CampaignForecast] = {}
    for cid, g in panel.groupby("campaign_id", sort=True):
        g = g.sort_values("date").reset_index(drop=True)
        train = g[g["target_mature"]]
        feat_now = g.iloc[[-1]][_FEATURES]   # current operating point
        choice = choices[cid]

        if choice.selected_model == XGB_MODEL:
            preds = {q: float(_xgb(q).fit(train[_FEATURES], train["target_fwd7"]).predict(feat_now)[0])
                     for q in _QUANTILES}
            p10, p50, p90 = sorted((preds[0.1], preds[0.5], preds[0.9]))  # monotone safety guard
            model = XGB_MODEL
            # conformal calibration is fit on, and corrects, the XGBoost quantile band
            c10, _, c90 = cal.widen(p10, p50, p90)
        else:  # safe fallback: the SELECTED champion baseline, ±20% heuristic band
            model = choice.selected_model
            p50 = same_weekday_last_week(g) if model == SAME_WEEKDAY_MODEL else trailing_14d(g)
            p10, p90 = p50 * 0.8, p50 * 1.2
            c10, c90 = p10, p90

        out[cid] = CampaignForecast(
            campaign_id=cid, p10=round(c10, 2), p50=round(p50, 2), p90=round(c90, 2),
            model=model, selection=choice,
            p10_raw=round(p10, 2), p90_raw=round(p90, 2),
        )
    return out, cal
