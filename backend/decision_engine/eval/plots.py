"""Diagnostic plots (Section 7). Deterministic Agg rendering.

Rebalanced (D-036) so the plot set matches what a DECISION engine must prove, not
just forecast accuracy. Four forecast diagnostics (calibration of the point model)
plus four decision/causal plots fed from the response / interval / sensitivity /
recommendation results — the parts that carry the project's thesis.

Numbers come from the same report dict / tidy test frame used for the JSON metrics,
so the charts never disagree with the tables. The latent-marginal recovery chart is
legitimate here because this is the eval/report context (already used for the §8
grading), never the model-input path.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

from backend.decision_engine.config import BLENDED_ROAS_FLOOR
from backend.decision_engine.engine.selection import XGB_MODEL

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams.update({"figure.dpi": 110, "font.size": 9, "axes.grid": True,
                     "grid.alpha": 0.25, "figure.autolayout": True})

_EXP_COLOR = "#1f77b4"      # identified (movement within observed spend support)
_OBS_COLOR = "#d62728"      # extrapolation-constrained
_OK_COLOR = "#2ca02c"
_BAD_COLOR = "#d62728"


def _save(fig, path: Path) -> str:
    fig.savefig(path)
    plt.close(fig)
    return path.name


def _short(cid: str) -> str:
    return cid.replace("GOOGLE_", "G:").replace("META_", "M:").title()


def generate_plots(report: dict, test_frame: pd.DataFrame, out_dir: Path,
                   recommendation=None) -> list[str]:
    """Write the rebalanced plot set; return the saved filenames (ordered).

    ``report`` is the full model-performance report dict (forecast / response /
    sensitivity), ``test_frame`` the tidy per-row test predictions, and
    ``recommendation`` the optional live ``EngineRecommendation`` (for the scale-floor
    reference and the allocation chart).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.png"):       # never leave dropped plots behind
        stale.unlink()
    saved: list[str] = []

    df = test_frame
    if df is not None and not df.empty:
        df = df.sort_values(["cid", "t"]).reset_index(drop=True)
        saved += _forecast_plots(df, report, out_dir, recommendation)

    saved += _decision_plots(report, out_dir, recommendation)
    return saved


# --- forecast diagnostics ---------------------------------------------------
def _forecast_plots(df: pd.DataFrame, report: dict, out_dir: Path,
                    recommendation=None) -> list[str]:
    saved = []

    # 01. actual vs predicted (overall point calibration)
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.scatter(df["y"], df["pred"], s=12, alpha=0.6)
    lim = [0, max(df["y"].max(), df["pred"].max()) * 1.05]
    ax.plot(lim, lim, "r--", lw=1, label="perfect")
    ax.set(xlabel="actual 7-day revenue", ylabel="predicted", title="Actual vs Predicted",
           xlim=lim, ylim=lim)
    ax.legend(fontsize=7)
    saved.append(_save(fig, out_dir / "01_actual_vs_predicted.png"))

    # 02. residuals vs predicted — heteroscedasticity (proves the realistic noise)
    fig, ax = plt.subplots(figsize=(5, 3.5))
    ax.scatter(df["pred"], df["residual"], s=12, alpha=0.6)
    ax.axhline(0, color="r", lw=1)
    ax.set(xlabel="predicted", ylabel="residual (pred-actual)",
           title="Residuals vs Predicted (heteroscedasticity)")
    saved.append(_save(fig, out_dir / "02_residuals_vs_predicted.png"))

    # 03. error by campaign (WAPE)
    fig, ax = plt.subplots(figsize=(6, 3.5))
    wape = df.groupby("cid").apply(
        lambda g: float(np.abs(g["pred"] - g["y"]).sum() / np.abs(g["y"]).sum()),
        include_groups=False).sort_values()
    ax.barh([_short(c) for c in wape.index], wape.values, color=_EXP_COLOR)
    ax.set(xlabel="WAPE", title="Forecast error by campaign")
    saved.append(_save(fig, out_dir / "03_error_by_campaign.png"))

    # 04. forecast fan — the DEPLOYED band (already in the frame), centered on the
    # SELECTED champion's P50. The displayed campaign is chosen by a FIXED, pre-evaluation
    # BUSINESS criterion — the highest CURRENT-SPEND XGBoost champion (the main
    # room-to-scale channel) — NOT by test WAPE, so the illustrative chart is not
    # cherry-picked on the metric it is meant to illustrate. p50 == the selected model,
    # so it never shows XGBoost for a baseline-champion campaign (the prior bug).
    xgb_models = {c for c in df["cid"].unique() if str(df[df.cid == c]["model"].iloc[0]) == XGB_MODEL}
    spend = {}
    if recommendation is not None:
        spend = {ln.campaign_id: ln.current_spend for ln in recommendation.lines}
    if not spend:                                  # fallback: test-window mean spend
        spend = df.groupby("cid")["spend"].mean().to_dict()
    ranked = {c: spend.get(c, 0.0) for c in (xgb_models or set(df["cid"].unique()))}
    cid = max(ranked, key=ranked.get)
    g = df[df.cid == cid].sort_values("date")
    is_xgb = str(g["model"].iloc[0]) == XGB_MODEL
    lo, hi = g["p10"].to_numpy(float), g["p90"].to_numpy(float)
    cov = float(np.mean((g["y"].to_numpy(float) >= lo) & (g["y"].to_numpy(float) <= hi)))
    band_label = ("conformal P10–P90 (calibrated)" if is_xgb
                  else "operational ±20% band (heuristic, not calibrated)")
    model_label = "XGBoost-quantile" if is_xgb else _short(g["model"].iloc[0].replace("baseline_", "baseline:"))
    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.fill_between(g["date"], lo, hi, alpha=0.25, label=band_label)
    if is_xgb:   # show the pre-conformal band only when conformal widening applies
        ax.plot(g["date"], g["p10_raw"], color="gray", lw=0.6, ls=":", label="raw P10/P90")
        ax.plot(g["date"], g["p90_raw"], color="gray", lw=0.6, ls=":")
    ax.plot(g["date"], g["p50"], lw=1.2, label="P50 (selected)")
    ax.plot(g["date"], g["y"], "k.", ms=5, label="actual")
    ax.set(xlabel="date", ylabel="7-day revenue",
           title=f"Forecast fan — {_short(cid)} · {model_label} (highest-spend champion, coverage {cov:.0%})")
    ax.legend(fontsize=7, ncol=2)
    fig.autofmt_xdate()
    saved.append(_save(fig, out_dir / "04_forecast_fan.png"))
    return saved


# --- decision / causal plots ------------------------------------------------
def _decision_plots(report: dict, out_dir: Path, recommendation) -> list[str]:
    saved = []
    resp = report.get("response", {}).get("per_campaign", {})
    floor = float(getattr(recommendation, "marginal_scale_floor", 0.0) or 0.0)

    # 05. estimated vs latent marginal ROAS — the identifiability money-shot (§8)
    if resp:
        cids = sorted(resp)
        lat = np.array([resp[c]["latent_marginal_eval_only"] for c in cids], float)
        est = np.array([resp[c]["expected_marginal"] for c in cids], float)
        dn = np.array([resp[c]["downside_marginal"] for c in cids], float)
        in_support = [bool(resp[c]["movement_in_support"]) for c in cids]
        fig, ax = plt.subplots(figsize=(5.5, 5))
        lo = min(lat.min(), est.min(), dn.min(), 0.0)
        hi = max(lat.max(), est.max(), 0.0)
        if 0 < floor <= hi * 1.3:
            hi = max(hi, floor)
            ax.axhline(floor, color="k", lw=0.8, ls="--", alpha=0.6)
            ax.axvline(floor, color="k", lw=0.8, ls="--", alpha=0.6)
            ax.text(floor, lo, " scale floor", fontsize=6, rotation=90, va="bottom")
        pad = (hi - lo) * 0.08 + 1e-6
        rng = [lo - pad, hi + pad]
        ax.plot(rng, rng, "r--", lw=1, label="perfect recovery")
        for i, c in enumerate(cids):
            col = _EXP_COLOR if in_support[i] else _OBS_COLOR
            ax.errorbar(lat[i], est[i], yerr=[[est[i] - dn[i]], [0]], fmt="o", ms=6,
                        color=col, ecolor=col, elinewidth=0.8, capsize=2)
            ax.annotate(_short(c), (lat[i], est[i]), fontsize=6,
                        xytext=(3, 3), textcoords="offset points")
        ax.scatter([], [], color=_EXP_COLOR, label="movement in support")
        ax.scatter([], [], color=_OBS_COLOR, label="extrapolation")
        ax.set(xlabel="latent marginal ROAS (eval-only truth)",
               ylabel="estimated marginal ROAS (↧ to downside)",
               title="Marginal-ROAS recovery vs latent truth", xlim=rng, ylim=rng)
        ax.legend(fontsize=6, loc="best")
        saved.append(_save(fig, out_dir / "05_marginal_roas_recovery.png"))

    # 06. interval reliability — XGBoost raw → conformal, plus the DEPLOYED band (what
    # the engine actually serves per champion: conformal XGBoost + ±20% for baselines).
    ov = report.get("forecast", {}).get("overall", {})
    qs, qc = ov.get("quantile_sorted", {}), ov.get("quantile_calibrated", {})
    dep = ov.get("deployed_interval", {})
    if qs:
        labels = ["XGBoost raw\n(sorted)", "XGBoost\nconformal", "deployed\n(mixed policy)"]
        covs = [qs.get("coverage_p10_p90", 0.0), qc.get("coverage_p10_p90", 0.0),
                dep.get("coverage_p10_p90", 0.0)]
        widths = [qs.get("mean_interval_width"), qc.get("mean_interval_width"),
                  dep.get("mean_interval_width")]
        fig, ax = plt.subplots(figsize=(5.6, 3.5))
        bars = ax.bar(labels, covs, color=[_BAD_COLOR, _OK_COLOR, _EXP_COLOR], alpha=0.85)
        ax.axhline(0.80, color="k", lw=1, ls="--", label="target 0.80")
        ax.set(ylabel="P10–P90 coverage", title="Interval reliability (XGBoost → conformal → deployed)",
               ylim=[0, 1.0])
        for b, c, w in zip(bars, covs, widths):
            tag = f"{c:.0%}" + (f"\nw≈{w:,.0f}" if w else "")
            ax.text(b.get_x() + b.get_width() / 2, c + 0.02, tag, ha="center", fontsize=7)
        ax.legend(fontsize=7)
        saved.append(_save(fig, out_dir / "06_interval_reliability.png"))

    # 07. optimizer sensitivity to marginal error (§9). Blended ROAS stays in a tight
    # band just above the floor under ±perturbation (decision-robust); marker shape
    # flags feasibility, colour flags whether the allocation DIRECTION holds. Axis is
    # zoomed near the floor on purpose — the story is the thin headroom.
    scen = report.get("sensitivity", {}).get("scenarios", {})
    if scen:
        names = list(scen)
        roas = [scen[n].get("blended_roas", 0.0) for n in names]
        stable = [bool(scen[n].get("direction_stable_vs_expected")) for n in names]
        feas = [bool(scen[n].get("feasible")) for n in names]
        x = np.arange(len(names))
        fig, ax = plt.subplots(figsize=(6.5, 3.6))
        for i in range(len(names)):
            ax.scatter(x[i], roas[i], s=80, zorder=3, linewidth=0.6, edgecolor="k",
                       color=(_OK_COLOR if stable[i] else "#ff7f0e"),
                       marker=("o" if feas[i] else "X"))
        ax.axhline(BLENDED_ROAS_FLOOR, color="k", lw=1, ls="--",
                   label=f"ROAS floor {BLENDED_ROAS_FLOOR:g}")
        ax.scatter([], [], color=_OK_COLOR, marker="o", edgecolor="k", label="direction holds")
        ax.scatter([], [], color="#ff7f0e", marker="o", edgecolor="k", label="direction flips")
        ax.scatter([], [], color="gray", marker="X", edgecolor="k", label="infeasible (constraint slack)")
        ax.set_xticks(x, names)
        ax.set(ylabel="blended ROAS", title="Optimizer stability under ±marginal error",
               ylim=[min(BLENDED_ROAS_FLOOR, min(roas)) - 0.06, max(roas) + 0.10])
        ax.legend(fontsize=6, ncol=2)
        fig.autofmt_xdate(rotation=20)
        saved.append(_save(fig, out_dir / "07_optimizer_sensitivity.png"))

    # 08. recommended vs current allocation — the actual decision output
    lines = list(getattr(recommendation, "lines", []) or [])
    if lines:
        lines = sorted(lines, key=lambda r: r.campaign_id)
        labels = [_short(r.campaign_id) for r in lines]
        cur = [r.current_spend for r in lines]
        rec = [r.recommended_spend for r in lines]
        y = np.arange(len(labels))
        fig, ax = plt.subplots(figsize=(6, 3.8))
        ax.barh(y - 0.2, cur, height=0.4, label="current", color="#9ecae1")
        ax.barh(y + 0.2, rec, height=0.4, label="recommended", color=_EXP_COLOR)
        ax.set_yticks(y, labels)
        ax.set(xlabel="daily spend", title="Recommended vs current allocation")
        ax.legend(fontsize=7)
        saved.append(_save(fig, out_dir / "08_allocation_recommendation.png"))

    return saved
