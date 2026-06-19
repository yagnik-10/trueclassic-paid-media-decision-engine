"""Engine inputs: build the modeling panel from the OBSERVABLE canonical data.

The engine never sees latent generator truth — only the ingested canonical fact
(deduped, label-mature), the campaign/SKU dims, and the synthetic calibration
registry. Revenue is put on the *calibrated* (incremental) basis the optimizer
decides on: ``calibrated_revenue = platform_reported_revenue × incrementality``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backend.decision_engine.ingestion.pipeline import IngestionReport, run_ingestion

FORWARD_DAYS = 7
ADSTOCK_DECAY = 0.5  # feature-level adstock; the response module re-estimates decay


@dataclass
class EngineInputs:
    panel: pd.DataFrame                 # campaign-day modeling rows
    campaigns: pd.DataFrame             # dim_campaign
    calibration: dict[str, float]       # segment -> incrementality coefficient
    current_spend: dict[str, float]     # campaign_id -> current (recent mean) spend


def _geometric_adstock(x: np.ndarray, decay: float) -> np.ndarray:
    out = np.empty_like(x, dtype=float)
    prev = x[0]
    for i in range(len(x)):
        prev = (1.0 - decay) * x[i] + decay * prev
        out[i] = prev
    return out


def _fourier(t: np.ndarray, period: float, k: int) -> dict[str, np.ndarray]:
    cols = {}
    for n in range(1, k + 1):
        cols[f"sin_{int(period)}_{n}"] = np.sin(2 * np.pi * n * t / period)
        cols[f"cos_{int(period)}_{n}"] = np.cos(2 * np.pi * n * t / period)
    return cols


def build_panel(report: IngestionReport) -> EngineInputs:
    fact = report.fact
    fact = fact[~fact["is_duplicate"]].copy()
    calibration = _calibration_map()  # segment -> synthetic incrementality coefficient

    fact["date"] = pd.to_datetime(fact["date"])
    fact = fact.sort_values(["campaign_id", "date"]).reset_index(drop=True)
    fact["calibrated_revenue"] = (
        fact["platform_reported_revenue"] * fact["segment"].map(calibration).astype(float)
    )

    frames = []
    for cid, g in fact.groupby("campaign_id", sort=True):
        g = g.sort_values("date").reset_index(drop=True)
        t = np.arange(len(g))
        spend = g["spend"].to_numpy(dtype=float)
        g["t"] = t
        g["dow"] = g["date"].dt.dayofweek
        g["adstock_spend"] = _geometric_adstock(spend, ADSTOCK_DECAY)
        g["trend"] = t / max(len(g) - 1, 1)
        for name, col in {**_fourier(t, 7, 2), **_fourier(t, 365.25, 2)}.items():
            g[name] = col
        g["spend_lag1"] = g["spend"].shift(1).fillna(g["spend"].iloc[0])
        g["spend_roll7"] = g["spend"].rolling(7, min_periods=1).mean()
        g["rev_roll7"] = g["calibrated_revenue"].rolling(7, min_periods=1).mean()
        # forward 7-day calibrated revenue target: target_fwd7[i] = sum(rev[i .. i+6]).
        # rolling(7) at i sums i-6..i; shifting up by 6 makes it sum i..i+6 (immature
        # — NaN — when the window runs past the end of the data).
        g["target_fwd7"] = (
            g["calibrated_revenue"].rolling(FORWARD_DAYS, min_periods=FORWARD_DAYS)
            .sum().shift(-(FORWARD_DAYS - 1))
        )
        frames.append(g)

    panel = pd.concat(frames, ignore_index=True)
    panel["target_mature"] = panel["label_mature"] & panel["target_fwd7"].notna()

    current_spend = (
        fact.sort_values("date").groupby("campaign_id").tail(14)
        .groupby("campaign_id")["spend"].mean().to_dict()
    )
    return EngineInputs(
        panel=panel, campaigns=report.masters["dim_campaign"],
        calibration=calibration, current_spend=current_spend,
    )


def _calibration_map() -> dict[str, float]:
    """segment -> incrementality coefficient, from the synthetic calibration registry."""
    from backend.decision_engine.synth.generator import generate

    reg = generate().tables["calibration_registry"]
    return dict(zip(reg["segment"], reg["coefficient"].astype(float)))


def load_engine_inputs(report: IngestionReport | None = None) -> EngineInputs:
    return build_panel(report or run_ingestion())
