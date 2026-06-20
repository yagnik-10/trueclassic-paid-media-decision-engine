"""Pure metric functions. Each measures ONE thing; nothing is collapsed into a
single vague "accuracy". All return plain floats/ints (JSON-serializable)."""

from __future__ import annotations

import numpy as np

# Revenue floor below which a percentage error is not meaningful (denominator ~0).
_MAPE_FLOOR = 50.0


def _r(x: float, nd: int = 6) -> float:
    """Round for stable, diff-able JSON (kills float64 last-bit noise)."""
    return float(round(float(x), nd))


def point_metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    """Point-forecast metrics for a P50 prediction vs the matured target."""
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    n = int(len(y))
    if n == 0:
        return {"n": 0}
    err = p - y
    abs_err = np.abs(err)
    denom = np.abs(y).sum()
    wape = abs_err.sum() / denom if denom else float("nan")
    # MAPE only on rows where |y| is large enough to be meaningful; report coverage.
    big = np.abs(y) >= _MAPE_FLOOR
    mape = float(np.mean(abs_err[big] / np.abs(y[big]))) if big.any() else float("nan")
    mdape = float(np.median(abs_err[big] / np.abs(y[big]))) if big.any() else float("nan")
    ss_res = float(np.sum(err ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot else float("nan")
    return {
        "n": n,
        "mae": _r(abs_err.mean()),
        "rmse": _r(np.sqrt(np.mean(err ** 2))),
        "wape": _r(wape),
        "mape": _r(mape) if not np.isnan(mape) else None,
        "mape_rows": int(big.sum()),
        "mdape": _r(mdape) if not np.isnan(mdape) else None,
        "bias_me": _r(err.mean()),          # mean error (pred - actual); + = over-predict
        "r2": _r(r2) if not np.isnan(r2) else None,
        "approx_point_accuracy": _r(1.0 - wape) if not np.isnan(wape) else None,
    }


def pinball_loss(y: np.ndarray, q_pred: np.ndarray, alpha: float) -> float:
    y = np.asarray(y, dtype=float)
    q = np.asarray(q_pred, dtype=float)
    d = y - q
    return float(np.mean(np.maximum(alpha * d, (alpha - 1.0) * d)))


def quantile_metrics(y: np.ndarray, p10: np.ndarray, p50: np.ndarray,
                     p90: np.ndarray, target_coverage: float = 0.80) -> dict[str, float]:
    """Interval calibration WITHOUT hiding raw crossings by sorting."""
    y = np.asarray(y, dtype=float)
    p10 = np.asarray(p10, dtype=float)
    p50 = np.asarray(p50, dtype=float)
    p90 = np.asarray(p90, dtype=float)
    n = int(len(y))
    if n == 0:
        return {"n": 0}
    raw_cross = int(np.sum((p10 > p50) | (p50 > p90)))
    inside = (y >= p10) & (y <= p90)
    coverage = float(np.mean(inside))
    width = float(np.mean(p90 - p10))
    return {
        "n": n,
        "pinball_p10": _r(pinball_loss(y, p10, 0.1)),
        "pinball_p50": _r(pinball_loss(y, p50, 0.5)),
        "pinball_p90": _r(pinball_loss(y, p90, 0.9)),
        "raw_crossings": raw_cross,
        "raw_crossing_rate": _r(raw_cross / n),
        "coverage_p10_p90": _r(coverage),
        "target_coverage": target_coverage,
        "calibration_error": _r(coverage - target_coverage),
        "mean_interval_width": _r(width),
        "interval_verdict": (
            "too_narrow" if coverage < target_coverage - 0.05
            else "too_wide" if coverage > target_coverage + 0.05 else "calibrated"),
    }


def coverage_by_decile(y: np.ndarray, p10: np.ndarray, p90: np.ndarray,
                       pred: np.ndarray, k: int = 5) -> list[dict[str, float]]:
    """Empirical P10-P90 coverage bucketed by predicted-value quantile (k buckets)."""
    y = np.asarray(y, dtype=float)
    pred = np.asarray(pred, dtype=float)
    n = len(y)
    if n < k:
        return []
    order = np.argsort(pred, kind="stable")
    out = []
    for b in range(k):
        idx = order[b * n // k:(b + 1) * n // k]
        inside = (y[idx] >= np.asarray(p10)[idx]) & (y[idx] <= np.asarray(p90)[idx])
        out.append({"bucket": b + 1, "n": int(len(idx)),
                    "pred_lo": _r(pred[idx].min()), "pred_hi": _r(pred[idx].max()),
                    "coverage": _r(float(np.mean(inside)))})
    return out


def summarize_folds(values: list[float]) -> dict[str, float]:
    arr = np.asarray([v for v in values if v is not None and not np.isnan(v)], dtype=float)
    if arr.size == 0:
        return {"mean": None, "std": None, "min": None, "max": None, "n_folds": 0}
    return {"mean": _r(arr.mean()), "std": _r(arr.std()),
            "min": _r(arr.min()), "max": _r(arr.max()), "n_folds": int(arr.size)}
