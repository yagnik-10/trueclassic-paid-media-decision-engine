"""Model A — XGBoost quantile BAU forecast (P10/P50/P90 of 7-day net revenue).

Predicts the 7-day-forward calibrated revenue at the current operating point.
Monotonic in spend, trained only on label-mature rows, validated with a
gap-aware chronological walk-forward (7-day gap so future labels can't leak), and
promoted only if it beats the simple baselines (else the baseline is the
fallback). Deterministic: fixed seed + single-threaded.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from backend.decision_engine.config import LABEL_MATURITY_DAYS, MASTER_SEED
from backend.decision_engine.engine.baselines import baseline_maes, trailing_14d

_FEATURES = [
    "spend", "adstock_spend", "dow", "trend", "spend_lag1", "spend_roll7", "rev_roll7",
    "sin_7_1", "cos_7_1", "sin_7_2", "cos_7_2", "sin_365_1", "cos_365_1",
]
_GAP = LABEL_MATURITY_DAYS
_QUANTILES = (0.1, 0.5, 0.9)


@dataclass
class CampaignForecast:
    campaign_id: str
    p10: float
    p50: float
    p90: float
    model: str            # "xgboost_quantile" or "baseline_trailing_14d"
    xgb_mae: float
    baseline_mae: float


def _xgb(alpha: float) -> XGBRegressor:
    return XGBRegressor(
        n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.9,
        min_child_weight=5, random_state=MASTER_SEED, n_jobs=1,
        objective="reg:quantileerror", quantile_alpha=alpha,
        monotone_constraints={"spend": 1, "adstock_spend": 1},
    )


def _walk_forward_mae(g: pd.DataFrame) -> float:
    """Gap-aware chronological walk-forward MAE of the P50 model."""
    g = g.sort_values("date").reset_index(drop=True)
    n = len(g)
    errs = []
    for cut in (int(n * 0.6), int(n * 0.75), int(n * 0.9)):
        train = g.iloc[: cut - _GAP]
        test = g.iloc[cut: cut + 7]
        tr = train[train["target_mature"]]
        te = test.dropna(subset=["target_fwd7"])
        if len(tr) < 40 or te.empty:
            continue
        m = _xgb(0.5).fit(tr[_FEATURES], tr["target_fwd7"])
        pred = m.predict(te[_FEATURES])
        errs.append(float(np.mean(np.abs(pred - te["target_fwd7"].to_numpy(float)))))
    return float(np.mean(errs)) if errs else float("nan")


def forecast(panel: pd.DataFrame) -> dict[str, CampaignForecast]:
    base = baseline_maes(panel)
    out: dict[str, CampaignForecast] = {}
    for cid, g in panel.groupby("campaign_id", sort=True):
        g = g.sort_values("date").reset_index(drop=True)
        train = g[g["target_mature"]]
        feat_now = g.iloc[[-1]][_FEATURES]   # current operating point
        xgb_mae = _walk_forward_mae(g)
        base_mae = min(v for v in base[cid].values() if not np.isnan(v))

        if len(train) >= 60 and not np.isnan(xgb_mae) and xgb_mae <= base_mae:
            preds = {q: float(_xgb(q).fit(train[_FEATURES], train["target_fwd7"]).predict(feat_now)[0])
                     for q in _QUANTILES}
            p10, p50, p90 = sorted((preds[0.1], preds[0.5], preds[0.9]))  # monotone safety guard
            model = "xgboost_quantile"
        else:  # safe fallback to the baseline
            p50 = trailing_14d(g)
            p10, p90 = p50 * 0.8, p50 * 1.2
            model = "baseline_trailing_14d"

        out[cid] = CampaignForecast(
            campaign_id=cid, p10=round(p10, 2), p50=round(p50, 2), p90=round(p90, 2),
            model=model, xgb_mae=round(xgb_mae, 2) if not np.isnan(xgb_mae) else float("nan"),
            baseline_mae=round(base_mae, 2),
        )
    return out
