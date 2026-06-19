"""Model B — residualized spend-response (the spend-change model).

Identifying media response from observational data is confounded: in this data
spend co-moves with day-of-week / promo / trend, so naively residualizing revenue
against those controls also strips the media effect. We therefore use
orthogonalization (Frisch–Waugh–Lovell / double-ML) on ADSTOCKED spend:

1. Chronological out-of-fold control models predict calibrated revenue and
   adstocked spend from non-media structure (day-of-week, trend, Fourier).
2. Regress the revenue residual on the (centered) adstocked-spend residual with a
   local quadratic — the slope is the orthogonalized marginal ROAS at the current
   operating point; the quadratic captures local saturation. Geometric-adstock
   decay is grid-searched per campaign (best residual fit). Using adstocked rather
   than raw spend removes the errors-in-variables attenuation that otherwise
   compresses the recovered magnitudes.
3. A block bootstrap gives a downside (Conservative) marginal.

At steady state a permanent spend change Δ shifts adstocked spend by Δ, so the
adstock-regression slope IS the marginal w.r.t. spend. This recovers a known
response process from synthetic data within the observed support (±~20%); it is
NOT a causal-identification claim — production still needs lift experiments.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.model_selection import TimeSeriesSplit

from backend.decision_engine.config import CONSERVATIVE_Z, MASTER_SEED

_CONTROL_FEATURES = [
    "dow_sin", "dow_cos", "trend",
    "sin_7_1", "cos_7_1", "sin_7_2", "cos_7_2",
    "sin_365_1", "cos_365_1", "sin_365_2", "cos_365_2",
]
_N_SPLITS = 5
_BOOTSTRAP = 200
_BLOCK = 14
_DECAY_GRID = (0.3, 0.4, 0.5, 0.6, 0.7)


@dataclass
class CampaignResponse:
    campaign_id: str
    segment: str
    current_spend: float
    current_revenue: float          # observed calibrated (incremental) revenue level
    marginal_roas: float            # orthogonalized dR/db at current spend
    marginal_roas_downside: float   # Conservative (block-bootstrap) marginal
    slope: float                    # local linear coef
    quad: float                     # local quadratic coef
    decay: float = 0.5              # grid-searched geometric-adstock decay

    def incremental_revenue(self, spend: float) -> float:
        """Local calibrated revenue at ``spend`` (anchored at the current point)."""
        d = spend - self.current_spend
        return self.current_revenue + self.slope * d + self.quad * d * d

    def marginal_at(self, spend: float) -> float:
        return self.slope + 2.0 * self.quad * (spend - self.current_spend)


def _oof_predict(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    pred = np.full(len(y), np.nan)
    for tr, te in TimeSeriesSplit(n_splits=_N_SPLITS).split(X):
        pred[te] = Ridge(alpha=10.0).fit(X[tr], y[tr]).predict(X[te])
    return pred


def _adstock(x: np.ndarray, decay: float) -> np.ndarray:
    out = np.empty_like(x, dtype=float)
    prev = x[0]
    for i in range(len(x)):
        prev = (1.0 - decay) * x[i] + decay * prev
        out[i] = prev
    return out


def _local_fit(rev_resid: np.ndarray, x_resid: np.ndarray) -> tuple[float, float, float]:
    """Local quadratic of revenue-residual on centered x-residual -> (slope, quad, sse)."""
    sc = x_resid - x_resid.mean()
    A = np.column_stack([np.ones_like(sc), sc, sc * sc])
    coef, *_ = np.linalg.lstsq(A, rev_resid, rcond=None)
    sse = float(np.sum((A @ coef - rev_resid) ** 2))
    return float(coef[1]), float(coef[2]), sse


def _prep(g: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (controls X, calibrated revenue, raw spend) sorted by date."""
    g = g.sort_values("date").reset_index(drop=True).copy()
    g["dow_sin"] = np.sin(2 * np.pi * g["dow"] / 7)
    g["dow_cos"] = np.cos(2 * np.pi * g["dow"] / 7)
    return (g[_CONTROL_FEATURES].to_numpy(float),
            g["calibrated_revenue"].to_numpy(float), g["spend"].to_numpy(float))


def _best_decay_fit(X, rev, spend) -> tuple[float, float, float, np.ndarray, np.ndarray]:
    """Grid-search adstock decay; return (slope, quad, decay, rev_resid, ad_resid)."""
    rev_resid = rev - _oof_predict(X, rev)
    best = None
    for decay in _DECAY_GRID:
        ad = _adstock(spend, decay)
        ad_resid = ad - _oof_predict(X, ad)
        mask = ~(np.isnan(rev_resid) | np.isnan(ad_resid))
        slope, quad, sse = _local_fit(rev_resid[mask], ad_resid[mask])
        if best is None or sse < best[0]:
            best = (sse, slope, quad, decay, rev_resid[mask], ad_resid[mask])
    return best[1], best[2], best[3], best[4], best[5]


def _bootstrap_downside(rev_resid: np.ndarray, x_resid: np.ndarray) -> float:
    """Block-bootstrap the local slope; return a downside (P10-style) marginal."""
    n = len(rev_resid)
    rng = np.random.default_rng(MASTER_SEED)
    if n < _BLOCK * 2:
        slope, _, _ = _local_fit(rev_resid, x_resid)
        return slope * 0.8
    starts = np.arange(0, n - _BLOCK)
    slopes = []
    for _ in range(_BOOTSTRAP):
        idx: list[int] = []
        while len(idx) < n:
            s0 = int(rng.choice(starts))
            idx.extend(range(s0, s0 + _BLOCK))
        sl, _, _ = _local_fit(rev_resid[idx[:n]], x_resid[idx[:n]])
        slopes.append(sl)
    arr = np.array(slopes)
    return float(arr.mean() - CONSERVATIVE_Z * arr.std())


def estimate(panel: pd.DataFrame, current_spend: dict[str, float]) -> dict[str, CampaignResponse]:
    out: dict[str, CampaignResponse] = {}
    for cid, g in panel.groupby("campaign_id", sort=True):
        seg = g["segment"].iloc[0]
        X, rev, spend = _prep(g)
        slope, quad, decay, rev_resid, ad_resid = _best_decay_fit(X, rev, spend)
        downside = _bootstrap_downside(rev_resid, ad_resid)
        cur = float(current_spend[cid])
        level = float(g.sort_values("date").tail(14)["calibrated_revenue"].mean())
        out[cid] = CampaignResponse(
            campaign_id=cid, segment=seg, current_spend=cur, current_revenue=level,
            marginal_roas=slope, marginal_roas_downside=downside,
            slope=slope, quad=quad, decay=decay,
        )
    return out
