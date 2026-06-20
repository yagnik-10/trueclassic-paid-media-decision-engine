#!/usr/bin/env python
"""Realistic-volatility stress test — same golden truth, rising OBSERVATION noise.

    PYTHONPATH=. python scripts/volatility_stress_test.py [--seeds N]

The question this answers is NOT "does accuracy fall" (it must), but the
identifiability one: under realistic revenue noise, does the engine still recover
the planted adstock-Hill scenario well enough to make the RIGHT decision (marginal
ordering + hurdle classification), and do the conformal intervals still hold
OUT-OF-SAMPLE?

How it stays honest / safe:
  * The committed dataset, fingerprint, and tests are untouched. We perturb a COPY of
    the ingested `platform_reported_revenue` in memory and let `build_panel` re-derive
    `calibrated_revenue` / `target_fwd7` / `rev_roll7` from it — no source edits, no
    generator knob, no new committed scenario.
  * The latent truth (`CAMPAIGN_BY_ID` Hill response + incrementality) is FIXED, so the
    eval-only `hill_marginal_roas` target the engine is graded against never moves.
  * Noise is mean-preserving multiplicative lognormal + sparse two-sided shocks — pure
    observation noise, not injected day-of-week/promo SIGNAL (which would just flatter
    the learner — the trap to avoid).
  * RNG streams derive from `MASTER_SEED` via `SeedSequence(spawn_key=...)`; the global
    RNG is never touched. Multiple seeds -> mean +/- std (no single-realization claims).
  * Coverage is reported on the HELD-OUT test pool (the offset is fit on train->val),
    not the calibration set (where conformal coverage is ~target by construction).
"""

from __future__ import annotations

import argparse
import dataclasses

import numpy as np
import pandas as pd

from backend.decision_engine.config import MASTER_SEED
from backend.decision_engine.engine.data import build_panel
from backend.decision_engine.engine.selection import XGB_MODEL
from backend.decision_engine.eval.harness import evaluate_forecast, evaluate_response
from backend.decision_engine.ingestion.pipeline import run_ingestion

# (sigma, shock_prob, shock_magnitude) — smooth == committed pipeline (no perturbation)
REGIMES: dict[str, tuple[float, float, float]] = {
    "smooth (committed)": (0.00, 0.00, 1.0),
    "realistic":          (0.25, 0.03, 1.8),
    "severe":             (0.45, 0.06, 2.2),
}


def _perturb_revenue(rev: np.ndarray, rng: np.random.Generator,
                     sigma: float, shock_p: float, shock_mag: float) -> np.ndarray:
    """Mean-preserving multiplicative observation noise + sparse two-sided shocks."""
    if sigma <= 0.0 and shock_p <= 0.0:
        return rev
    n = len(rev)
    mult = np.exp(rng.normal(-0.5 * sigma * sigma, sigma, n))   # E[mult] = 1 (no drift)
    if shock_p > 0.0:
        hit = rng.random(n) < shock_p
        up = rng.random(n) < 0.5
        shock = np.where(up, shock_mag, 1.0 / shock_mag)
        mult = np.where(hit, mult * shock, mult)
    return rev * mult


def _revenue_cv(panel: pd.DataFrame) -> float:
    """Mean within-campaign coefficient of variation of the observed (calibrated) revenue."""
    cvs = []
    for _, g in panel.groupby("campaign_id"):
        r = g["calibrated_revenue"].to_numpy(float)
        m = r.mean()
        if m > 0:
            cvs.append(r.std() / m)
    return float(np.mean(cvs)) if cvs else float("nan")


def _run_once(base_report, current_spend, regime: tuple[float, float, float],
              seed_idx: int, regime_idx: int) -> dict:
    sigma, shock_p, shock_mag = regime
    rng = np.random.default_rng(
        np.random.SeedSequence(entropy=MASTER_SEED, spawn_key=(regime_idx, seed_idx)))

    fact = base_report.fact.copy()
    fact["platform_reported_revenue"] = _perturb_revenue(
        fact["platform_reported_revenue"].to_numpy(float), rng, sigma, shock_p, shock_mag)
    report = dataclasses.replace(base_report, fact=fact)

    inp = build_panel(report)
    fc = evaluate_forecast(inp_panel := inp.panel)
    resp = evaluate_response(inp_panel, inp.current_spend)

    ov = fc["overall"]
    selected = fc["selected_models"]
    n_xgb = sum(1 for m in selected.values() if m == XGB_MODEL)
    n_material = 0
    for camp in fc["per_campaign"].values():
        vs = camp.get("xgb_vs_baseline", {})
        if any((vs.get(b) or {}).get("material") for b in vs):
            n_material += 1

    # decision recovery: does the estimated argmax-marginal land on the true argmax?
    per = resp["per_campaign"]
    est_top = max(per, key=lambda c: per[c]["expected_marginal"])
    lat_top = max(per, key=lambda c: per[c]["latent_marginal_eval_only"])

    cal = ov.get("quantile_calibrated", {})
    raw = ov.get("quantile_raw", {})
    ro = resp["overall"]
    return {
        "revenue_cv": _revenue_cv(inp_panel),
        "selected_wape": ov["point_selected"]["wape"],
        "xgb_p50_wape": ov["point_xgboost_p50"]["wape"],
        "n_xgb_shipped": float(n_xgb),
        "n_xgb_material": float(n_material),
        "raw_coverage": raw.get("coverage_p10_p90", float("nan")),
        "calibrated_coverage_heldout": cal.get("coverage_p10_p90", float("nan")),
        "spearman": ro["spearman"],
        "sign_accuracy": ro["sign_accuracy"],
        "hurdle_accuracy": ro["hurdle_classification_accuracy"],
        "mean_abs_marginal_error": ro["mean_abs_marginal_error"],
        "argmax_marginal_recovered": float(est_top == lat_top),
    }


_ROWS = [
    ("revenue_cv", "observed revenue CV (the lever)", 3),
    ("selected_wape", "— FORECAST — selected-model WAPE (lower=better)", 3),
    ("xgb_p50_wape", "XGBoost-P50 pooled WAPE", 3),
    ("n_xgb_shipped", "# campaigns ship XGBoost (of 7)", 1),
    ("n_xgb_material", "# XGBoost materially beats baseline (of 7)", 1),
    ("raw_coverage", "— INTERVALS — raw P10-P90 coverage (target 0.80)", 3),
    ("calibrated_coverage_heldout", "conformal coverage, HELD-OUT test (target 0.80)", 3),
    ("spearman", "— RESPONSE vs TRUTH — marginal rank Spearman", 3),
    ("sign_accuracy", "sign accuracy", 3),
    ("hurdle_accuracy", "hurdle-class accuracy (the DECISION)", 3),
    ("mean_abs_marginal_error", "mean abs marginal error (magnitude)", 3),
    ("argmax_marginal_recovered", "top room-to-scale recovered (frac of seeds)", 2),
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", type=int, default=5, help="seeds per noisy regime")
    args = ap.parse_args()

    base_report = run_ingestion()                       # deterministic; perturb copies of it
    base_inp = build_panel(base_report)

    print("\nRealistic-volatility stress test — same golden truth, rising observation "
          f"noise\n(seeds/regime: {args.seeds}; latent Hill truth fixed; committed data "
          "untouched)\n")

    results: dict[str, list[dict]] = {}
    for ri, (name, regime) in enumerate(REGIMES.items()):
        # smooth has no randomness -> one run suffices; noisy regimes use N seeds
        n = 1 if regime[0] <= 0 and regime[1] <= 0 else args.seeds
        results[name] = [_run_once(base_report, base_inp.current_spend, regime, si, ri)
                         for si in range(n)]

    names = list(REGIMES)
    header = f"{'metric':<52s}" + "".join(f"{n[:22]:>24s}" for n in names)
    print(header)
    print("-" * len(header))
    for key, label, prec in _ROWS:
        cells = ""
        for name in names:
            vals = np.asarray([r[key] for r in results[name]], float)
            mean = np.nanmean(vals)
            if len(vals) > 1:
                cell = f"{mean:.{prec}f}±{np.nanstd(vals):.{prec}f}"
            else:
                cell = f"{mean:.{prec}f}"
            cells += f"{cell:>24s}"
        print(f"{label:<52s}{cells}")

    print("\nRead: forecast WAPE SHOULD rise (honest). The test is whether hurdle-class "
          "accuracy\nand the held-out conformal coverage survive — and whether XGBoost "
          "starts beating\nthe naive baselines once the data is no longer trivially smooth.")


if __name__ == "__main__":
    main()
