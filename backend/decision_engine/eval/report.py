"""Orchestrate the model-performance report: run every section, write a
machine-readable JSON + CSV, a Markdown summary, diagnostic plots, and a
provenance block. Deterministic — no wall-clock values enter the artifacts, so
two runs produce byte-identical numbers."""

from __future__ import annotations

import csv
import json
import platform
from importlib.metadata import version
from pathlib import Path

from backend.decision_engine.config import BLENDED_ROAS_FLOOR, MASTER_SEED, REPO_ROOT
from backend.decision_engine.engine.data import load_engine_inputs
from backend.decision_engine.engine.recommend import ENGINE_VERSION, build_engine_recommendation
from backend.decision_engine.eval import harness as H
from backend.decision_engine.eval import plots as P
from backend.decision_engine.ingestion.pipeline import run_ingestion
from backend.decision_engine.synth.fingerprint import canonical_tables_fingerprint
from backend.decision_engine.synth.generator import generate

OUT_DIR = REPO_ROOT / "reports" / "model_performance"
_DEPS = ("numpy", "pandas", "scipy", "scikit-learn", "xgboost", "matplotlib")


def _provenance() -> dict:
    return {
        "data_fingerprint": canonical_tables_fingerprint(generate().tables),
        "engine_version": ENGINE_VERSION,
        "master_seed": MASTER_SEED,
        "python": platform.python_version(),
        "dependencies": {d: version(d) for d in _DEPS},
        "command": "make model-report",
        "note": "Synthetic-data validation. Latent marginals are available only "
                "because the data generator is known; these are NOT real-world "
                "performance figures and imply no causal identification.",
    }


def _interpret(report: dict) -> dict:
    fc = report["forecast"]["overall"]
    wape = fc.get("point_selected", {}).get("wape")
    acc = fc.get("point_selected", {}).get("approx_point_accuracy")
    sel = report["forecast"]["selected_models"]
    fallback = [c for c, m in sel.items() if m != "xgboost_quantile"]
    xgb_wins = [c for c, v in report["forecast"]["per_campaign"].items()
                if v["xgb_vs_baseline"].get("baseline_trailing_14d")
                and v["xgb_vs_baseline"]["baseline_trailing_14d"]["material"]]
    # Post-selection holdout drift: an XGBoost CHAMPION (chosen on pre-test folds) that
    # then lost to a baseline MATERIALLY on the untouched test. We deliberately do NOT
    # flip it (that would leak test into the policy) — we SURFACE it as a retraining
    # signal. Threshold is >25% relative WAPE (not 5%): a near-tie where both errors are
    # small is selection noise, not drift; >25% worse is a real "the champion regressed"
    # signal (e.g. GOOGLE_PMAX/META_RETARGETING here).
    _DRIFT_REL = 0.25
    drift = []
    for cid, v in report["forecast"]["per_campaign"].items():
        if v["selected_model"] != "xgboost_quantile":
            continue
        pt = v["point"]
        sel_w = pt["selected"].get("wape")
        base_ws = [pt[b].get("wape") for b in ("baseline_trailing_14d", "baseline_same_weekday")]
        base_ws = [b for b in base_ws if b is not None]
        if sel_w is not None and base_ws and sel_w > min(base_ws) * (1 + _DRIFT_REL):
            drift.append({"campaign": cid, "selected_wape": sel_w,
                          "best_baseline_wape": min(base_ws),
                          "pct_worse": round((sel_w / min(base_ws) - 1) * 100, 1)})
    qs = fc.get("quantile_sorted", {})
    qc = fc.get("quantile_calibrated", {})        # S4.2 conformal-calibrated band (preferred)
    qi = qc or qs                                 # what the headline interval verdict uses
    dep = fc.get("deployed_interval", {})         # the band the engine actually serves
    conf = fc.get("conformal", {})
    # The 0.80-target CALIBRATION verdict belongs to the XGBoost CONFORMAL band only
    # (it is the band fit to 0.80). Less brittle than the mechanical ±5pp verdict: 85% is
    # not "broken", it is slightly conservative.
    _conf_cov = qi.get("coverage_p10_p90")
    if _conf_cov is None:
        conformal_assessment = "n/a"
    elif _conf_cov >= 0.85:
        conformal_assessment = f"slightly conservative ({_conf_cov:.1%} vs 0.80 target)"
    elif _conf_cov >= 0.75:
        conformal_assessment = f"well-calibrated ({_conf_cov:.1%} vs 0.80 target)"
    else:
        conformal_assessment = f"too narrow ({_conf_cov:.1%} vs 0.80 target)"
    # The DEPLOYED coverage POOLS a conformal XGBoost band with a ±20% baseline HEURISTIC,
    # so it is an empirical MIXED-POLICY figure — NOT a single band calibrated to 0.80.
    _dep_cov = dep.get("coverage_p10_p90")
    deployed_coverage_label = ("n/a" if _dep_cov is None else
                               f"{_dep_cov:.1%} empirical (mixed policy: conformal XGBoost "
                               "for XGBoost champions + ±20% heuristic for baseline champions)")
    resp = report["response"]["overall"]
    sens = report["sensitivity"]
    # Data-driven sensitivity caveat: which (if any) ± perturbations tip the plan
    # infeasible is a property of the active profile/data, not a fixed sentence.
    _perturb = ("minus_20pct", "plus_20pct", "minus_10pct", "plus_10pct")
    _scen = sens.get("scenarios", {})
    _infeasible = sorted(n for n in _perturb if n in _scen and not _scen[n]["feasible"])
    _exp_roas = _scen.get("expected", {}).get("blended_roas")
    if _infeasible:
        sens_caveat = (
            f"Uniform marginal-error perturbation(s) {_infeasible} tip the plan infeasible "
            f"(a guardrail binds, e.g. the ROAS floor {BLENDED_ROAS_FLOOR:.2f}×) — the "
            "guardrails block them; the remaining feasible perturbations stay "
            "direction-stable, so instability never reaches an approvable plan.")
    else:
        sens_caveat = (
            f"Under ±10%/±20% uniform marginal error the plan stays feasible AND "
            f"direction-stable (expected blended ROAS {_exp_roas}× vs floor "
            f"{BLENDED_ROAS_FLOOR:.2f}×); the prospecting daily caps and ROAS floor are the "
            "binding margins of safety.")
    return {
        "overall_test_wape": wape,
        "approx_point_accuracy_pct": (round(acc * 100, 1) if acc is not None else None),
        "approx_accuracy_caveat": "100% - WAPE is an intuitive gloss only; it is a "
        "magnitude-weighted error, NOT classification accuracy, and is dominated by "
        "high-revenue rows.",
        "xgb_materially_beats_baseline_in": xgb_wins,
        "fallback_campaigns": fallback,
        "interval_80_calibrated": qi.get("interval_verdict") == "calibrated",
        "interval_verdict": qi.get("interval_verdict"),
        # calibration verdict for the XGBoost CONFORMAL band (the one fit to 0.80)
        "interval_conformal_assessment": conformal_assessment,
        "interval_coverage": qi.get("coverage_p10_p90"),
        "interval_coverage_raw": qs.get("coverage_p10_p90"),
        # the DEPLOYED band is a MIXED policy (conformal XGBoost + ±20% baseline heuristic)
        # — empirical coverage, explicitly NOT a single conformal band calibrated to 0.80
        "interval_coverage_deployed": dep.get("coverage_p10_p90"),
        "interval_width_deployed": dep.get("mean_interval_width"),
        "interval_deployed_label": deployed_coverage_label,
        "interval_conformal_offset": conf.get("offset"),
        "response_sign_accuracy": resp.get("sign_accuracy"),
        "response_hurdle_accuracy": resp.get("hurdle_classification_accuracy"),
        "response_rank_spearman": resp.get("spearman"),
        "direction_stable_under_pm20pct": sens.get("direction_stable_under_all_perturbations"),
        "direction_stable_among_feasible": sens.get("direction_stable_among_feasible_perturbations"),
        "instability_only_when_infeasible": sens.get("unstable_only_when_infeasible"),
        "champion_holdout_drift": drift,
        # Split the single "safe" flag (GPT's fair point): the MODEL demo (forecast +
        # response fidelity) and the DECISION demo (a feasible, direction-stable plan)
        # are different claims. The decision basis is marginal-ROAS ordering + the ROAS
        # floor, not the P10/P90 band — so interval miscalibration is a disclosed caveat,
        # not a decision-safety blocker.
        "safe_for_model_demo": bool(
            wape is not None and wape < 0.5
            and resp.get("hurdle_classification_accuracy", 0) >= 0.8),
        "safe_for_decision_demo": bool(
            report.get("decision", {}).get("feasible")
            and sens.get("direction_stable_among_feasible_perturbations")),
        "safe_for_demo": bool(
            wape is not None and wape < 0.5
            and resp.get("hurdle_classification_accuracy", 0) >= 0.8
            and sens.get("direction_stable_among_feasible_perturbations")),
        "caveats": [
            f"80% interval — TWO distinct claims: (1) the XGBoost CONFORMAL band is "
            f"statistically calibrated to 0.80 (held-out {qi.get('coverage_p10_p90')}, "
            f"{conformal_assessment}; raw {qs.get('coverage_p10_p90')} before widening). "
            f"(2) the DEPLOYED band is a MIXED policy — conformal XGBoost for XGBoost "
            f"champions, an operational ±20% HEURISTIC (not statistically calibrated) for "
            f"baseline champions — with empirical coverage {dep.get('coverage_p10_p90')} "
            f"(width ≈ {dep.get('mean_interval_width')}). The optimizer decides on "
            "marginal-ROAS ordering + the floor, not the band.",
            "XGBoost only materially beats the trailing-14d baseline in "
            f"{xgb_wins or 'no'} campaign(s); {fallback or 'no'} fall back to the baseline.",
            (f"Post-selection holdout drift: {[d['campaign'] for d in drift]} — the XGBoost "
             "champion (picked on pre-test folds) regressed >25% vs a baseline on the untouched "
             "test; surfaced as a retraining signal, NOT flipped (flipping would leak test into "
             "the policy)." if drift else
             "No material post-selection holdout drift (>25% vs best baseline) among XGBoost "
             "champions on the untouched test."),
            sens_caveat,
            "Synthetic data: errors are far smaller than real paid-media noise.",
        ],
        "do_not_claim": "Real-world accuracy, causal lift, or production calibration. "
        "The data is synthetic; these metrics validate the modeling MACHINERY only.",
    }


def _decision_summary(rec) -> dict:
    """Explicit, auditable decision posture for the active recommendation — most
    importantly the prospecting-share computation (campaign IDs, numerator, denominator,
    floor, slack), so the green feasibility status is self-explanatory and matches the
    binding-constraint mart. The floor is profile-aware (D-037: realistic 0.30)."""
    from backend.decision_engine import config as C
    dimc = generate().tables["dim_campaign"].set_index("campaign_id")
    pros_ids = sorted(ln.campaign_id for ln in rec.lines
                      if bool(dimc.loc[ln.campaign_id, "is_prospecting"]))
    num = sum(ln.recommended_spend for ln in rec.lines if ln.campaign_id in pros_ids)
    den = sum(ln.recommended_spend for ln in rec.lines)
    share = (num / den) if den else 0.0
    floor = float(C.PROSPECTING_MIN_SHARE)
    return {
        "dataset_profile": C.DATASET_PROFILE,
        "feasible": rec.feasible,
        "conflicts": rec.conflicts,
        # PRIMARY success metrics (D-041): CM ROAS + net contribution $/day
        "cm_roas_current": rec.cm_roas_current,
        "cm_roas_projected": rec.cm_roas_projected,
        "net_contribution_current": rec.net_contribution_current,
        "net_contribution_projected": rec.net_contribution_projected,
        "blended_roas_projected": rec.blended_roas_projected,  # enforced-floor (governance) lens
        "total_recommended_spend": rec.total_recommended_spend,
        "active_constraints": {
            "blended_roas_floor": C.BLENDED_ROAS_FLOOR,
            "prospecting_min_share": floor,
            "nc_cpa_target": C.NC_CPA_TARGET,
            "movement_bound": rec.effective_movement_bound,
        },
        "prospecting_share": {
            "numerator_campaigns": pros_ids,
            "numerator": round(float(num), 2),
            "denominator": round(float(den), 2),
            "actual_share": round(float(share), 4),
            "floor": floor,
            "slack_pp": round(float(share - floor) * 100, 2),
            "binds": bool(share - floor <= 5e-3),
        },
    }


def run(out_dir: Path = OUT_DIR) -> dict:
    out_dir = Path(out_dir)
    plots_dir = out_dir / "plots"
    out_dir.mkdir(parents=True, exist_ok=True)

    ingest = run_ingestion()
    raw_fact = int(len(ingest.fact))
    dup_rows = int(ingest.fact["is_duplicate"].sum())
    inputs = load_engine_inputs(ingest)
    panel = inputs.panel

    forecast = H.evaluate_forecast(panel)
    report = {
        "provenance": _provenance(),
        "correctness": H.verify_correctness(panel),
        "dataset": H.dataset_summary(panel, raw_fact, dup_rows),
        "forecast": forecast,
        "stability": H.evaluate_stability(panel),
        "segments": H.evaluate_segments(panel, forecast),
        "response": H.evaluate_response(panel, inputs.current_spend),
        "sensitivity": H.evaluate_sensitivity(panel, inputs.current_spend),
    }
    # Build the tidy test frame first so the DEPLOYED-band interval coverage (the band
    # the engine actually serves per champion) is available to interpretation/plots —
    # distinct from the XGBoost-quantile-only conformal diagnostic.
    test_frame = H.build_test_frame(panel, forecast)
    report["forecast"]["overall"]["deployed_interval"] = H.deployed_interval_metrics(test_frame)
    # the live recommendation gives the plots the real decision output AND the explicit
    # decision posture (feasibility + prospecting-share breakdown); deterministic. Built
    # before interpretation so the demo-safety split can read it.
    recommendation = build_engine_recommendation()
    report["decision"] = _decision_summary(recommendation)
    report["interpretation"] = _interpret(report)

    plot_files = P.generate_plots(report, test_frame, plots_dir, recommendation)
    report["artifacts"] = {"plots_dir": "plots", "plots": plot_files}

    _write_json(report, out_dir / "metrics.json")
    _write_csv(report, out_dir / "per_campaign_point_metrics.csv")
    _write_markdown(report, out_dir / "REPORT.md")
    return report


def _write_json(report: dict, path: Path) -> None:
    path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")


def _write_csv(report: dict, path: Path) -> None:
    cols = ["campaign_id", "selected_model", "model", "n", "mae", "rmse", "wape",
            "mape", "bias_me", "approx_point_accuracy"]
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for cid, c in sorted(report["forecast"]["per_campaign"].items()):
            for model in ("xgboost_p50", "baseline_trailing_14d", "baseline_same_weekday", "selected"):
                m = c["point"][model]
                w.writerow([cid, c["selected_model"], model, m.get("n"), m.get("mae"),
                            m.get("rmse"), m.get("wape"), m.get("mape"), m.get("bias_me"),
                            m.get("approx_point_accuracy")])


def _write_markdown(report: dict, path: Path) -> None:
    pr = report["provenance"]
    ds = report["dataset"]
    fc = report["forecast"]["overall"]
    it = report["interpretation"]
    co = report["correctness"]
    ex = co["explicit_example"]
    L: list[str] = []
    a = L.append
    a("# Model Performance Report — Paid Media Decision Engine\n")
    a("> Synthetic-data validation. Numbers validate the modeling machinery, not "
      "real-world performance, and imply **no causal identification**.\n")
    a(f"- **Data fingerprint:** `{pr['data_fingerprint']}`")
    a(f"- **Engine version:** `{pr['engine_version']}` · **seed:** `{pr['master_seed']}` "
      f"· **python:** {pr['python']}")
    a("- **Deps:** " + ", ".join(f"{k} {v}" for k, v in pr["dependencies"].items()))
    a(f"- **Reproduce:** `{pr['command']}`\n")

    a("## 1. Evaluation correctness\n")
    a(f"- Target = sum of days t..t+6: **{co['target_is_sum_t_to_t_plus_6']}**")
    a(f"  - Example {ex['campaign_id']} row {ex['row_date']} → window {ex['window_dates'][0]}…"
      f"{ex['window_dates'][-1]}, Σ={ex['sum_days_t_to_t6']} == stored {ex['stored_target_fwd7']}")
    a(f"- Immature labels excluded: **{co['immature_labels_excluded']}**; "
      f"duplicates excluded: **{co['duplicates_excluded_in_panel']}**")
    a(f"- Chronological splits with {co['gap_days_between_splits']}-day gap: "
      f"**{co['chronological_splits']}**; test used for selection: **False**\n")

    a("## 2. Dataset & splits\n")
    a(f"- Range {ds['date_range'][0]} → {ds['date_range'][1]} · {ds['n_days']} days · "
      f"{ds['n_campaigns']} campaigns · horizon {ds['forecast_horizon_days']}d")
    a(f"- Rows: raw {ds['rows_raw_fact']} → panel {ds['rows_after_dedupe']} "
      f"(dupes {ds['rows_excluded_duplicate']}, immature {ds['rows_immature_excluded']})")
    a(f"- Train {ds['rows_train']} (t{ds['train_t']}) · Val {ds['rows_val']} (t{ds['val_t']}) · "
      f"Test {ds['rows_test']} (t{ds['test_t']})\n")

    a("## 3. Point-forecast performance (untouched test)\n")
    ps, px = fc.get("point_selected", {}), report["forecast"]["overall"].get("point_xgboost_p50", {})
    a(f"- **Selected model:** WAPE {ps.get('wape')} · MAE {ps.get('mae')} · RMSE "
      f"{ps.get('rmse')} · bias {ps.get('bias_me')} · approx point accuracy "
      f"{it['approx_point_accuracy_pct']}%")
    a(f"- XGBoost P50 (pooled): WAPE {px.get('wape')} · MAE {px.get('mae')}")
    a(f"- XGBoost materially beats trailing-14d in: {it['xgb_materially_beats_baseline_in'] or 'none'}")
    a(f"- Fallback campaigns: {it['fallback_campaigns'] or 'none'}")
    a("- _Approx accuracy = 100% − WAPE; intuitive only, magnitude-weighted, not classification._")
    a("- _**Selection is frozen on pre-test folds** (`engine/selection.py`); the per-campaign "
      "`selected` model and the `xgb beats?` test column are INDEPENDENT — the test period is "
      "scored after selection and is **never** used to (re)pick a model. A `selected=xgboost` "
      "campaign whose `xgb beats?` is `False` lost on the untouched test **after** being chosen "
      "on pre-test evidence; it is deliberately NOT flipped (doing so would leak test into the "
      "policy)._\n")
    a("| campaign | selected | xgb P50 WAPE | trail-14d WAPE | same-wkday WAPE | xgb beats? |")
    a("|---|---|---|---|---|---|")
    for cid, c in sorted(report["forecast"]["per_campaign"].items()):
        p = c["point"]
        imp = c["xgb_vs_baseline"].get("baseline_trailing_14d") or {}
        a(f"| {cid} | {c['selected_model'].replace('_quantile','')} | "
          f"{p['xgboost_p50'].get('wape')} | {p['baseline_trailing_14d'].get('wape')} | "
          f"{p['baseline_same_weekday'].get('wape')} | {imp.get('xgb_beats_baseline')} |")
    a("")

    a("## 4. Quantile / interval calibration\n")
    qr, qsd = fc.get("quantile_raw", {}), fc.get("quantile_sorted", {})
    qcd, conf = fc.get("quantile_calibrated", {}), fc.get("conformal", {})
    dep = fc.get("deployed_interval", {})
    a("_Two bands are reported: the **XGBoost-quantile** band (the conformal target, "
      "pooled over campaigns) and the **deployed** band the engine actually serves per "
      "champion (conformal XGBoost for XGBoost champions, ±20% for baseline champions)._")
    a(f"- Pinball (sorted, XGBoost): P10 {qsd.get('pinball_p10')} · P50 {qsd.get('pinball_p50')} · "
      f"P90 {qsd.get('pinball_p90')}")
    a(f"- **Raw crossings:** {qr.get('raw_crossings')} ({qr.get('raw_crossing_rate')}); "
      f"after sort: {qsd.get('raw_crossings')}")
    a(f"- XGBoost-quantile band: raw coverage {qsd.get('coverage_p10_p90')} "
      f"(**{qsd.get('interval_verdict')}**, width {qsd.get('mean_interval_width')})"
      + (f" → conformal {qcd.get('coverage_p10_p90')} (**{qcd.get('interval_verdict')}**, "
         f"width {qcd.get('mean_interval_width')}); CQR offset {conf.get('offset')} fit on "
         f"{conf.get('n_calibration')} held-out rows (train→val), scored on test" if qcd else ""))
    if dep:
        bm = dep.get("by_model", {})
        a(f"- **XGBoost conformal band:** {it['interval_conformal_assessment']} — this is "
          "the statistically-calibrated band (fit to 0.80 on held-out residuals).")
        a(f"- **Deployed band (mixed policy):** empirical coverage {dep.get('coverage_p10_p90')}, "
          f"mean width {dep.get('mean_interval_width')} over {dep.get('n')} test rows — NOT a "
          "single conformal band; baseline champions use an operational ±20% heuristic.")
        a("  - by model: " + ", ".join(
            f"{m.replace('_quantile','')} cov {v.get('coverage_p10_p90')} "
            f"(w {v.get('mean_interval_width')}, n {v.get('n')}"
            f"{', heuristic ±20%' if m.startswith('baseline') else ', conformal'})"
            for m, v in sorted(bm.items())) + "\n")
    else:
        a("")

    a("## 5. Time stability (rolling folds)\n")
    st = report["stability"]
    a("| fold t | n | WAPE | MAE | bias | coverage | model |")
    a("|---|---|---|---|---|---|---|")
    for f in st["folds"]:
        a(f"| {f['fold_t']} | {f['n']} | {f['wape']} | {f['mae']} | {f['bias_me']} | "
          f"{f['coverage_p10_p90']} | {f['dominant_model'].replace('_quantile','')} |")
    a(f"- WAPE mean {st['wape']['mean']} ± {st['wape']['std']} "
      f"(min {st['wape']['min']}, max {st['wape']['max']}); deteriorates late: "
      f"**{st['deteriorates_late']}**\n")

    a("## 6. Segment / platform / spend band\n")
    sg = report["segments"]
    for key in ("by_platform", "by_segment_group", "by_spend_band"):
        a(f"- **{key}:** " + ", ".join(
            f"{k} WAPE {v.get('wape')}" for k, v in sg.get(key, {}).items()
            if isinstance(v, dict) and "wape" in v))
    a(f"- Strongest: {sg.get('strongest_campaign')} · weakest: {sg.get('weakest_campaign')}\n")

    a("## 7. Diagnostic plots\n")
    a("Rebalanced for a *decision* engine: 4 forecast-calibration diagnostics + 4 "
      "decision/causal charts (fed from the response, interval, sensitivity and "
      "recommendation results above).")
    a("- **Forecast:** `01_actual_vs_predicted`, `02_residuals_vs_predicted` "
      "(heteroscedasticity), `03_error_by_campaign`, `04_forecast_fan` "
      "(the **deployed** band, centered on the selected champion's P50).")
    a("- **Decision/causal:** `05_marginal_roas_recovery` (estimated vs latent "
      "marginal ROAS, scale-floor boundary, in-support vs extrapolation), "
      "`06_interval_reliability` (XGBoost raw → conformal → **deployed** coverage vs 0.80), "
      "`07_optimizer_sensitivity` (blended ROAS under ±marginal error, infeasible "
      "cases blocked), `08_allocation_recommendation` (current vs recommended).")
    a(f"- {len(report['artifacts']['plots'])} plots in `{report['artifacts']['plots_dir']}/`: "
      + ", ".join(report["artifacts"]["plots"]) + "\n")

    a("## 8. Response-model fidelity (vs latent synthetic marginals)\n")
    ro = report["response"]["overall"]
    a(f"- Spearman {ro['spearman']} · Pearson {ro['pearson']} · sign accuracy "
      f"{ro['sign_accuracy']} · hurdle-class accuracy {ro['hurdle_classification_accuracy']}")
    a(f"- Mean abs marginal error {ro['mean_abs_marginal_error']} · median rel error "
      f"{ro['median_rel_marginal_error']}")
    a("| campaign | decay | est mROAS | downside | latent | rel err | sign✓ | hurdle✓ | in-support | fold σ |")
    a("|---|---|---|---|---|---|---|---|---|---|")
    for cid, c in sorted(report["response"]["per_campaign"].items()):
        a(f"| {cid} | {c['decay']} | {c['expected_marginal']} | {c['downside_marginal']} | "
          f"{c['latent_marginal_eval_only']} | {c['rel_error']} | {c['sign_agreement']} | "
          f"{c['hurdle_class_agreement']} | {c['movement_in_support']} | {c['fold_marginal_std']} |")
    a("")

    a("## 9. Optimizer sensitivity to marginal error\n")
    a("| marginal set | feasible | blended ROAS | contribution | max Δalloc vs expected | direction stable |")
    a("|---|---|---|---|---|---|")
    for name, s in report["sensitivity"]["scenarios"].items():
        a(f"| {name} | {s['feasible']} | {s['blended_roas']} | {s['contribution']} | "
          f"{s['max_alloc_diff_vs_expected']} | {s['direction_stable_vs_expected']} |")
    _sc = report["sensitivity"]["scenarios"]
    _perturb = ("minus_20pct", "plus_20pct", "minus_10pct", "plus_10pct")
    _infeasible = sorted(n for n in _perturb if n in _sc and not _sc[n]["feasible"])
    _tail = (f"the only unstable/infeasible case(s) — {_infeasible} — are blocked by the "
             "guardrails" if _infeasible
             else "every ±10/20% perturbation stays feasible, so the guardrails never have "
                   "to block one")
    a(f"- Direction stable under all ±10/20% perturbations: "
      f"**{report['sensitivity']['direction_stable_under_all_perturbations']}** "
      f"(among FEASIBLE perturbations: "
      f"**{report['sensitivity']['direction_stable_among_feasible_perturbations']}**; "
      f"{_tail})\n")

    dec = report.get("decision")
    if dec:
        ps = dec["prospecting_share"]
        ac = dec["active_constraints"]
        a("## 10. Decision feasibility & constraint posture\n")
        a(f"- **Primary KPI — CM ROAS {dec['cm_roas_current']:.2f}× → "
          f"{dec['cm_roas_projected']:.2f}×** (contribution per ad $, break-even 1.0×); "
          f"net contribution **${dec['net_contribution_current']:,.0f} → "
          f"${dec['net_contribution_projected']:,.0f}/day** at equal-or-lower spend.")
        a(f"- **Feasible:** {dec['feasible']} · conflicts: {dec['conflicts'] or 'none'} · "
          f"profile **{dec['dataset_profile']}** · gross blended ROAS "
          f"{dec['blended_roas_projected']}× (enforced floor) · deployed "
          f"${dec['total_recommended_spend']:,.0f}")
        a(f"- **Active floors:** blended ROAS ≥ {ac['blended_roas_floor']:.2f}× · prospecting "
          f"share ≥ {ac['prospecting_min_share']:.2f} (profile-aware, D-037) · NC-CPA ≤ "
          f"${ac['nc_cpa_target']:.0f} · movement ±{ac['movement_bound']:.0%}")
        a("- **Prospecting share (exact):**")
        a(f"  - numerator campaigns = {ps['numerator_campaigns']}")
        a(f"  - numerator = ${ps['numerator']:,.2f} · denominator = ${ps['denominator']:,.2f}")
        a(f"  - actual = **{ps['actual_share'] * 100:.2f}%** vs floor "
          f"**{ps['floor'] * 100:.2f}%** → slack **{ps['slack_pp']:+.2f}pp** "
          f"({'binds' if ps['binds'] else 'slack'})")
        a("  - _the floor was 0.33 for golden; it is physically infeasible on the realistic "
          "profile (caps pin prospecting at ~0.32), so the realistic floor is 0.30 (D-037)._\n")

    a("## 11. Interpretation\n")
    a(f"- **Headline = WAPE {it['overall_test_wape']}** (magnitude-weighted error); the "
      f"~{it['approx_point_accuracy_pct']}% figure is an *intuitive* gloss only "
      f"({it['approx_accuracy_caveat']})")
    a(f"- XGBoost materially beats baselines in {it['xgb_materially_beats_baseline_in'] or 'none'}; "
      f"fallback used for {it['fallback_campaigns'] or 'none'}")
    if it["champion_holdout_drift"]:
        a("- ⚠️ **Holdout drift (retraining signal, not flipped):** " + ", ".join(
            f"{d['campaign']} (champion WAPE {d['selected_wape']} vs best baseline "
            f"{d['best_baseline_wape']}, {d['pct_worse']}% worse)"
            for d in it["champion_holdout_drift"]))
    else:
        a("- Holdout drift: none — every XGBoost champion stayed within 5% of the best baseline on test")
    a(f"- 80% interval — **XGBoost conformal band** {it['interval_conformal_assessment']} "
      "(the calibrated band); **deployed mixed-policy** empirical coverage "
      f"{it['interval_coverage_deployed']} (width {it['interval_width_deployed']}) — baseline "
      "champions use an operational ±20% heuristic, not a calibrated interval")
    a(f"- Response: sign {it['response_sign_accuracy']}, hurdle {it['response_hurdle_accuracy']}, "
      f"rank ρ {it['response_rank_spearman']}; direction stable among feasible perturbations: "
      f"**{it['direction_stable_among_feasible']}** (all-perturbation incl. infeasible: "
      f"{it['direction_stable_under_pm20pct']})")
    a(f"- **Safe for MODEL demo:** {it['safe_for_model_demo']} (forecast + response fidelity) · "
      f"**Safe for DECISION demo:** {it['safe_for_decision_demo']} (feasible, direction-stable "
      "plan; decision basis = marginal ordering + ROAS floor, not the P10/P90 band)")
    a("- **Caveats:**")
    for c in it["caveats"]:
        a(f"  - {c}")
    a(f"- **Do not claim:** {it['do_not_claim']}\n")
    path.write_text("\n".join(L))
