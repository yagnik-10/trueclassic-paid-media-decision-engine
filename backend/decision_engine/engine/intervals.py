"""Split-conformal interval calibration (CQR) for the BAU quantile forecast.

The raw XGBoost P10/P90 band is too narrow (~43% empirical coverage vs an 80%
target). We correct it with Conformalized Quantile Regression (Romano, Patterson &
Candès, 2019): on a held-out CALIBRATION window — chronologically between train and
test, separated by the label-maturity gap — score how far each realized value falls
outside its predicted ``[P10, P90]`` band, then widen every band by the (1-alpha)
empirical quantile of those scores. Scores are normalized by the predicted level so
campaigns of very different revenue scale pool into one portfolio offset.

Leakage safety: the offset is fit on train -> calibration only; the test period is
never consulted (the report then *scores* the calibrated band on test). Deterministic
(fixed-seed, single-threaded XGBoost; pure-numpy quantile).

Scope: this only changes the displayed UNCERTAINTY band. The optimizer anchors on
P50 (/horizon) and decides on marginal-ROAS ordering + the ROAS floor, so calibrated
intervals never move an allocation — they make the band trustworthy.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.decision_engine.config import LABEL_MATURITY_DAYS
from backend.decision_engine.engine.selection import _FEATURES, _QUANTILES, _xgb

# Calibration window mirrors the harness "val" split: chronological and gap-separated
# from BOTH train and test, so the conformal offset is fit with no test leakage.
GAP = LABEL_MATURITY_DAYS          # 7-day maturity gap
CALIB_TRAIN_END_T = 119            # fit calibration models on t <= 119 (== harness train end)
CALIB_START_T = 126                # score on the val window 126..161
CALIB_END_T = 161
_MIN_TRAIN = 60                    # min mature train rows before trusting XGBoost
_SCALE_FLOOR = 1.0                 # guards the level-normalization denominator
DEFAULT_TARGET_COVERAGE = 0.80


@dataclass(frozen=True)
class ConformalCalibrator:
    """A level-normalized symmetric widening of the P10/P90 band.

    ``offset`` is a fraction of the predicted level: the calibrated band is
    ``[p10 - offset*scale, p90 + offset*scale]`` with ``scale = max(|p50|, 1)``.
    A positive offset widens (raw band too narrow); negative narrows.
    """
    offset: float
    target_coverage: float
    n_calibration: int
    raw_coverage: float          # pooled coverage on the calibration set BEFORE widening
    calibrated_coverage: float   # ...AFTER widening (~= target by construction)

    def widen(self, p10: float, p50: float, p90: float) -> tuple[float, float, float]:
        d = self.offset * max(abs(p50), _SCALE_FLOOR)
        # a negative offset NARROWS; clamp so the band can never cross the median
        return (min(p10 - d, p50), p50, max(p90 + d, p50))


def _conformity_scores(y: np.ndarray, p10: np.ndarray, p50: np.ndarray,
                       p90: np.ndarray) -> np.ndarray:
    """CQR score, level-normalized: how far y falls outside [p10, p90] (negative = inside)."""
    scale = np.maximum(np.abs(p50), _SCALE_FLOOR)
    return np.maximum(p10 - y, y - p90) / scale


def conformal_offset(scores: np.ndarray, target_coverage: float) -> float:
    """Finite-sample-valid (1-alpha) empirical quantile: the ceil((n+1)*cov)/n order stat."""
    n = int(len(scores))
    if n == 0:
        return 0.0
    rank = int(np.ceil((n + 1) * target_coverage))
    rank = min(max(rank, 1), n)              # clamp into [1, n]
    return float(np.sort(scores)[rank - 1])


def _calibration_predictions(panel):
    """Per-campaign train->calibration-window XGBoost QUANTILE predictions.

    Conformal calibration targets the XGBoost quantile band specifically (the band
    that is miscalibrated). We pool the raw XGBoost quantiles for every campaign with
    enough train rows — identical to what the report scores as ``quantile_sorted`` —
    so the calibration window and the test window are EXCHANGEABLE (same model, same
    quantile estimator). Baseline-fallback campaigns keep their own ±20% heuristic
    band and are not conformalized here.
    """
    ys, p10s, p50s, p90s = [], [], [], []
    for cid, g in panel.groupby("campaign_id", sort=True):
        g = g.sort_values("t").reset_index(drop=True)
        tr = g[(g["t"] <= CALIB_TRAIN_END_T) & g["target_mature"]]
        va = g[(g["t"] >= CALIB_START_T) & (g["t"] <= CALIB_END_T) & g["target_mature"]]
        if va.empty or len(tr) < _MIN_TRAIN:
            continue
        y = va["target_fwd7"].to_numpy(float)
        preds = {q: np.asarray(_xgb(q).fit(tr[_FEATURES], tr["target_fwd7"])
                               .predict(va[_FEATURES]), dtype=float) for q in _QUANTILES}
        p10, p50, p90 = np.sort(np.vstack([preds[0.1], preds[0.5], preds[0.9]]), axis=0)
        ok = ~np.isnan(y) & ~np.isnan(p50)
        ys.append(y[ok])
        p10s.append(p10[ok])
        p50s.append(p50[ok])
        p90s.append(p90[ok])
    if not ys or sum(len(a) for a in ys) == 0:
        return None
    return (np.concatenate(ys), np.concatenate(p10s),
            np.concatenate(p50s), np.concatenate(p90s))


def fit_calibrator(panel,
                   target_coverage: float = DEFAULT_TARGET_COVERAGE) -> ConformalCalibrator:
    """Fit the portfolio conformal offset on the train->calibration split (no test leakage)."""
    data = _calibration_predictions(panel)
    if data is None:
        return ConformalCalibrator(0.0, target_coverage, 0, float("nan"), float("nan"))
    y, p10, p50, p90 = data
    raw_cov = float(np.mean((y >= p10) & (y <= p90)))
    offset = conformal_offset(_conformity_scores(y, p10, p50, p90), target_coverage)
    d = offset * np.maximum(np.abs(p50), _SCALE_FLOOR)
    c10, c90 = np.minimum(p10 - d, p50), np.maximum(p90 + d, p50)   # clamp at the median
    cal_cov = float(np.mean((y >= c10) & (y <= c90)))
    return ConformalCalibrator(
        offset=round(offset, 6), target_coverage=target_coverage,
        n_calibration=int(len(y)), raw_coverage=round(raw_cov, 4),
        calibrated_coverage=round(cal_cov, 4),
    )
