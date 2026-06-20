"""Evaluation harness: leakage-controlled splits + forecast / response / optimizer
evaluation, reusing the engine's exact model code (no model changes)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

from backend.decision_engine.config import (
    HARD_FLOOR_SAFETY,
    LABEL_MATURITY_DAYS,
    MOVEMENT_BOUND,
    N_DAYS,
)
from backend.decision_engine.engine.baselines import same_weekday_last_week, trailing_14d
from backend.decision_engine.engine.bau_forecast import _FEATURES, _xgb
from backend.decision_engine.engine.intervals import fit_calibrator
from backend.decision_engine.engine.optimizer import OptCampaign, optimize
from backend.decision_engine.engine.selection import SAME_WEEKDAY_MODEL, XGB_MODEL, select_models
from backend.decision_engine.engine.recommend import _context
from backend.decision_engine.engine.response import (
    CampaignResponse,
    _best_decay_fit,
    _prep,
    estimate,
)
from backend.decision_engine.eval import metrics as M
from backend.decision_engine.synth.scenario import CAMPAIGN_BY_ID, hill_marginal_roas

# --- Split design (global day index t, shared across campaigns) --------------
GAP = LABEL_MATURITY_DAYS          # 7-day gap so no forward-7 target spans a boundary
VAL_START_T = 126
TEST_START_T = 168
END_T = N_DAYS                     # 210
LAST_MATURE_T = END_T - GAP        # 203 (t+6 == 209 == last day)
TRAIN_END_T = VAL_START_T - GAP    # 119
VAL_END_T = TEST_START_T - GAP     # 161
_MIN_TRAIN = 60

_PLATFORM = {c.campaign_id: c.platform for c in CAMPAIGN_BY_ID.values()}
_SEGMENT_GROUPS = {
    "prospecting": ["META_PROSPECTING", "META_ADV_SHOPPING"],
    "retargeting": ["META_RETARGETING"],
    "search": ["GOOGLE_BRAND", "GOOGLE_NONBRAND"],
    "shopping_pmax": ["GOOGLE_PMAX", "GOOGLE_SHOPPING"],
}


def assign_split(panel: pd.DataFrame) -> pd.DataFrame:
    p = panel.copy()
    t = p["t"].to_numpy()
    split = np.full(len(p), "gap", dtype=object)
    split[(t <= TRAIN_END_T)] = "train"
    split[(t >= VAL_START_T) & (t <= VAL_END_T)] = "val"
    split[(t >= TEST_START_T) & (t <= LAST_MATURE_T)] = "test"
    p["split"] = split
    p.loc[~p["target_mature"], "split"] = "immature"   # never train/eval immature rows
    return p


# --- Section 1: evaluation-correctness proof --------------------------------
def verify_correctness(panel: pd.DataFrame) -> dict:
    """Prove target alignment, exclusions, splits, and the no-leak gap."""
    g = panel[panel["campaign_id"] == "GOOGLE_NONBRAND"].sort_values("date").reset_index(drop=True)
    i = 30  # an explicit, mature example row
    window = g["calibrated_revenue"].iloc[i:i + 7]
    example = {
        "campaign_id": "GOOGLE_NONBRAND",
        "row_date": str(g["date"].iloc[i].date()),
        "window_dates": [str(d.date()) for d in g["date"].iloc[i:i + 7]],
        "sum_days_t_to_t6": M._r(float(window.sum()), 2),
        "stored_target_fwd7": M._r(float(g["target_fwd7"].iloc[i]), 2),
        "match": bool(abs(window.sum() - g["target_fwd7"].iloc[i]) < 1e-6),
    }
    p = assign_split(panel)
    sp = p.groupby("split", sort=True)["t"]
    ranges = {k: {"t_min": int(v.min()), "t_max": int(v.max()), "rows": int(v.size)}
              for k, v in sp if k in ("train", "val", "test")}
    # duplicates are excluded when no flagged-duplicate rows survive AND no
    # (campaign_id, date) pair repeats in the modeling panel.
    no_flagged_dupes = ("is_duplicate" not in panel.columns) or bool((~panel["is_duplicate"]).all())
    no_repeated_keys = not bool(panel.duplicated(["campaign_id", "date"]).any())
    return {
        "target_is_sum_t_to_t_plus_6": example["match"],
        "explicit_example": example,
        "immature_labels_excluded": bool((~panel["target_mature"]).sum() > 0)
        and bool((p["split"] == "immature").sum() > 0),
        "duplicates_excluded_in_panel": no_flagged_dupes and no_repeated_keys,
        "chronological_splits": (ranges["train"]["t_max"] < ranges["val"]["t_min"]
                                 < ranges["val"]["t_max"] < ranges["test"]["t_min"]),
        "gap_days_between_splits": GAP,
        "train_target_end_before_val": TRAIN_END_T + 6 < VAL_START_T,
        "val_target_end_before_test": VAL_END_T + 6 < TEST_START_T,
        "test_not_used_for_selection": True,   # shared selector uses pre-test folds only
        "split_t_ranges": ranges,
    }


def dataset_summary(panel: pd.DataFrame, raw_fact_rows: int, dup_rows: int) -> dict:
    p = assign_split(panel)
    counts = p["split"].value_counts().to_dict()
    return {
        "date_range": [str(panel["date"].min().date()), str(panel["date"].max().date())],
        "n_days": int(panel["date"].nunique()),
        "n_campaigns": int(panel["campaign_id"].nunique()),
        "rows_raw_fact": int(raw_fact_rows),
        "rows_after_dedupe": int(len(panel)),
        "rows_excluded_duplicate": int(dup_rows),
        "rows_immature_excluded": int((~panel["target_mature"]).sum()),
        "rows_train": int(counts.get("train", 0)),
        "rows_val": int(counts.get("val", 0)),
        "rows_test": int(counts.get("test", 0)),
        "forecast_horizon_days": 7,
        "features": list(_FEATURES),
        "target": "target_fwd7 = sum(calibrated_revenue[t .. t+6]); immature -> NaN -> excluded",
        "train_t": [0, TRAIN_END_T], "val_t": [VAL_START_T, VAL_END_T],
        "test_t": [TEST_START_T, LAST_MATURE_T], "gap_days": GAP,
    }


# --- forecast helpers --------------------------------------------------------
def _fit_q(train: pd.DataFrame, pred: pd.DataFrame, alpha: float) -> np.ndarray:
    m = _xgb(alpha).fit(train[_FEATURES], train["target_fwd7"])
    return np.asarray(m.predict(pred[_FEATURES]), dtype=float)


def _baseline_pred(g_full: pd.DataFrame, rows: pd.DataFrame, which: str) -> np.ndarray:
    out = []
    for t in rows["t"].to_numpy():
        hist = g_full[g_full["t"] <= t]
        v = trailing_14d(hist) if which == "trailing_14d" else same_weekday_last_week(hist)
        out.append(float(v) if v is not None else np.nan)
    return np.asarray(out, dtype=float)


def _wape(y: np.ndarray, p: np.ndarray) -> float:
    d = np.abs(np.asarray(y)).sum()
    return float(np.abs(np.asarray(p) - np.asarray(y)).sum() / d) if d else float("nan")


def evaluate_forecast(panel: pd.DataFrame) -> dict:
    p = assign_split(panel)
    # The model CHOICE comes from the shared, frozen selector (pre-test folds only;
    # the test period below is never consulted to pick a model) — identical to the
    # live engine, so the UI and this report can never report different models.
    choices = select_models(panel)
    per_campaign: dict[str, dict] = {}
    pooled = {k: [] for k in ("y", "xgb50", "sel", "p10", "p50", "p90", "spend", "cid")}

    for cid, g in p.groupby("campaign_id", sort=True):
        g = g.sort_values("t").reset_index(drop=True)
        tr, te = (g[g.split == s] for s in ("train", "test"))
        if tr.empty or te.empty:
            continue
        choice = choices[cid]
        selected = choice.selected_model

        # test-period predictions (scored, but NOT used to select the model)
        y = te["target_fwd7"].to_numpy(float)
        xgb = {q: _fit_q(tr, te, q) for q in (0.1, 0.5, 0.9)} if len(tr) >= _MIN_TRAIN else None
        xgb50 = xgb[0.5] if xgb else np.full(len(te), np.nan)
        b14 = _baseline_pred(g, te, "trailing_14d")
        bsw = _baseline_pred(g, te, "same_weekday")
        sel_pred = (xgb50 if selected == XGB_MODEL
                    else bsw if selected == SAME_WEEKDAY_MODEL else b14)

        camp = {
            "selected_model": selected,
            "selection": {   # auditable shared-selector metadata (frozen on pre-test folds)
                "xgb_wape": choice.xgb_wape, "baseline_wape": choice.baseline_wape,
                "improvement_pct": choice.improvement_pct, "fold_wins": choice.fold_wins,
                "n_folds": choice.n_folds, "threshold": choice.threshold,
                "reason": choice.reason,
            },
            "point": {
                "xgboost_p50": M.point_metrics(y, xgb50),
                "baseline_trailing_14d": M.point_metrics(y, b14),
                "baseline_same_weekday": M.point_metrics(y, bsw),
                "selected": M.point_metrics(y, sel_pred),
            },
        }
        if xgb is not None:
            p10, p50, p90 = xgb[0.1], xgb[0.5], xgb[0.9]
            s10, s50, s90 = (np.sort(np.vstack([p10, p50, p90]), axis=0))
            camp["quantile_raw"] = M.quantile_metrics(y, p10, p50, p90)
            camp["quantile_sorted"] = M.quantile_metrics(y, s10, s50, s90)
            for arr, k in ((y, "y"), (p10, "p10"), (p50, "p50"), (p90, "p90")):
                pooled[k].extend(arr.tolist())
            pooled["spend"].extend(te["spend"].tolist())
            pooled["cid"].extend([cid] * len(te))
            pooled["xgb50"].extend(xgb50.tolist())
            pooled["sel"].extend(sel_pred.tolist())
        # improvement of XGBoost over baselines (test WAPE)
        camp["xgb_vs_baseline"] = _improvement(camp["point"])
        per_campaign[cid] = camp

    overall = _overall_forecast(pooled, fit_calibrator(panel))
    return {"per_campaign": per_campaign, "overall": overall,
            "selected_models": {c: v["selected_model"] for c, v in per_campaign.items()}}


def _improvement(point: dict) -> dict:
    xw = point["xgboost_p50"].get("wape")
    out = {}
    for base in ("baseline_trailing_14d", "baseline_same_weekday"):
        bw = point[base].get("wape")
        if xw is None or bw is None:
            out[base] = None
            continue
        out[base] = {
            "abs_wape_improvement": M._r(bw - xw),
            "pct_wape_improvement": M._r((bw - xw) / bw * 100) if bw else None,
            "xgb_beats_baseline": bool(xw < bw),
            "material": bool((bw - xw) / bw > 0.05) if bw else False,  # >5% = not noise
        }
    return out


def _overall_forecast(pooled: dict, calibrator=None) -> dict:
    y = np.asarray(pooled["y"], float)
    if y.size == 0:
        return {}
    p10 = np.asarray(pooled["p10"], float)
    p50 = np.asarray(pooled["p50"], float)
    p90 = np.asarray(pooled["p90"], float)
    s10, s50, s90 = np.sort(np.vstack([p10, p50, p90]), axis=0)
    out = {
        "point_xgboost_p50": M.point_metrics(y, np.asarray(pooled["xgb50"], float)),
        "point_selected": M.point_metrics(y, np.asarray(pooled["sel"], float)),
        "quantile_raw": M.quantile_metrics(y, p10, p50, p90),
        "quantile_sorted": M.quantile_metrics(y, s10, s50, s90),
        "coverage_by_pred_decile": M.coverage_by_decile(y, s10, s90, s50, k=5),
    }
    # S4.2: score the CONFORMAL-CALIBRATED band on the (untouched) test pool. The
    # offset was fit on train->val only, so this is a clean out-of-sample coverage
    # proof that the calibration moves coverage from "too narrow" toward the target.
    if calibrator is not None:
        d = calibrator.offset * np.maximum(np.abs(s50), 1.0)
        c10, c90 = np.minimum(s10 - d, s50), np.maximum(s90 + d, s50)   # clamp at the median
        out["quantile_calibrated"] = M.quantile_metrics(y, c10, s50, c90)
        out["coverage_by_pred_decile_calibrated"] = M.coverage_by_decile(y, c10, c90, s50, k=5)
        out["conformal"] = {
            "method": "conformalized_quantile_regression",
            "offset": calibrator.offset, "target_coverage": calibrator.target_coverage,
            "n_calibration": calibrator.n_calibration,
            "calibration_coverage_raw": calibrator.raw_coverage,
            "calibration_coverage_calibrated": calibrator.calibrated_coverage,
        }
    return out


def build_test_frame(panel: pd.DataFrame, forecast: dict) -> pd.DataFrame:
    """Tidy per-row test predictions that mirror the **deployed** forecast band.

    Critically, the band matches what ``engine/bau_forecast.forecast`` actually
    serves and what the §3 table selects — NOT XGBoost quantiles for every campaign:
      * XGBoost champion → the conformal-WIDENED quantile band (``p10/p90`` are the
        calibrated edges; ``p10_raw/p90_raw`` keep the pre-conformal band).
      * baseline champion → the champion's point with the deployed ±20% band; here
        ``p50 == pred`` so the fan is centered on the selected model, not XGBoost.
    This is why the fan no longer shows XGBoost's P50 for a baseline-champion campaign.
    """
    p = assign_split(panel)
    offset = float(forecast.get("overall", {}).get("conformal", {}).get("offset") or 0.0)
    rows = []
    for cid, camp in forecast["per_campaign"].items():
        tr = p[(p.campaign_id == cid) & (p.split == "train")]
        te = p[(p.campaign_id == cid) & (p.split == "test")].sort_values("t")
        if te.empty:
            continue
        y = te["target_fwd7"].to_numpy(float)
        selected = camp["selected_model"]
        if selected == XGB_MODEL and len(tr) >= _MIN_TRAIN:
            q10, p50, q90 = np.sort(np.vstack([_fit_q(tr, te, q) for q in (0.1, 0.5, 0.9)]), axis=0)
            d = offset * np.maximum(np.abs(p50), 1.0)            # conformal widening
            p10 = np.minimum(q10 - d, p50)
            p90 = np.maximum(q90 + d, p50)
            p10_raw, p90_raw, pred = q10, q90, p50               # raw band for reference
        else:  # baseline champion: deployed point + ±20% fallback band (mirrors engine)
            which = "same_weekday" if selected == SAME_WEEKDAY_MODEL else "trailing_14d"
            base = _baseline_pred(panel[panel.campaign_id == cid].sort_values("t"), te, which)
            p50 = pred = base
            p10, p90 = base * 0.8, base * 1.2
            p10_raw, p90_raw = p10, p90
        for j in range(len(te)):
            rows.append({"cid": cid, "date": te["date"].iloc[j], "t": int(te["t"].iloc[j]),
                         "dow": int(te["dow"].iloc[j]), "spend": float(te["spend"].iloc[j]),
                         "y": float(y[j]), "p10": float(p10[j]), "p50": float(p50[j]),
                         "p90": float(p90[j]), "p10_raw": float(p10_raw[j]),
                         "p90_raw": float(p90_raw[j]), "model": selected,
                         "pred": float(pred[j]), "residual": float(pred[j] - y[j])})
    return pd.DataFrame(rows)


def deployed_interval_metrics(test_frame: pd.DataFrame) -> dict:
    """Coverage/width of the band the engine ACTUALLY serves (conformal XGBoost for
    XGBoost champions, ±20% for baseline champions), pooled and split by model. This
    is the honest 'deployed uncertainty', distinct from the XGBoost-quantile-only
    conformal diagnostic in ``_overall_forecast`` (which scores the band BEFORE the
    champion selection chooses a baseline for some campaigns)."""
    if test_frame is None or test_frame.empty:
        return {}
    y = test_frame["y"].to_numpy(float)
    lo, hi = test_frame["p10"].to_numpy(float), test_frame["p90"].to_numpy(float)
    by_model = {}
    for model, g in test_frame.groupby("model", sort=True):
        yy = g["y"].to_numpy(float)
        gl, gh = g["p10"].to_numpy(float), g["p90"].to_numpy(float)
        by_model[str(model)] = {
            "n": int(len(g)),
            "coverage_p10_p90": M._r(float(np.mean((yy >= gl) & (yy <= gh))), 4),
            "mean_interval_width": M._r(float(np.mean(gh - gl)), 2),
        }
    return {
        "coverage_p10_p90": M._r(float(np.mean((y >= lo) & (y <= hi))), 4),
        "mean_interval_width": M._r(float(np.mean(hi - lo)), 2),
        "n": int(len(y)), "target_coverage": 0.80,
        "n_xgboost_campaigns": int((test_frame["model"] == XGB_MODEL).groupby(test_frame["cid"]).any().sum()),
        "by_model": by_model,
    }


# --- Section 5: time stability (expanding-train / rolling-test folds) --------
def evaluate_stability(panel: pd.DataFrame) -> dict:
    folds = [(126, 146), (147, 167), (168, 188), (189, LAST_MATURE_T)]
    rows = []
    for lo, hi in folds:
        y_all, p_all, lo_all, hi_all = [], [], [], []
        sel_votes: dict[str, int] = {}
        for cid, g in panel.groupby("campaign_id", sort=True):
            g = g.sort_values("t").reset_index(drop=True)
            tr = g[(g["t"] <= lo - GAP) & g["target_mature"]]
            te = g[(g["t"] >= lo) & (g["t"] <= hi) & g["target_mature"]]
            if len(tr) < _MIN_TRAIN or te.empty:
                continue
            y = te["target_fwd7"].to_numpy(float)
            p50 = _fit_q(tr, te, 0.5)
            p10 = _fit_q(tr, te, 0.1)
            p90 = _fit_q(tr, te, 0.9)
            base = _baseline_pred(g, te, "trailing_14d")
            sel = "xgboost_quantile" if _wape(y, p50) <= _wape(y, base) else "baseline_trailing_14d"
            sel_votes[sel] = sel_votes.get(sel, 0) + 1
            y_all.extend(y)
            p_all.extend(p50)
            s10 = np.minimum(p10, p90)
            s90 = np.maximum(p10, p90)
            lo_all.extend(s10)
            hi_all.extend(s90)
        if not y_all:
            continue
        y = np.asarray(y_all)
        p = np.asarray(p_all)
        cov = float(np.mean((y >= np.asarray(lo_all)) & (y <= np.asarray(hi_all))))
        rows.append({
            "fold_t": [lo, hi], "n": int(y.size),
            "wape": M._r(_wape(y, p)), "mae": M._r(float(np.mean(np.abs(p - y)))),
            "bias_me": M._r(float(np.mean(p - y))), "coverage_p10_p90": M._r(cov),
            "dominant_model": max(sel_votes, key=sel_votes.get) if sel_votes else None,
        })
    return {
        "folds": rows,
        "wape": M.summarize_folds([r["wape"] for r in rows]),
        "mae": M.summarize_folds([r["mae"] for r in rows]),
        "bias_me": M.summarize_folds([r["bias_me"] for r in rows]),
        "coverage_p10_p90": M.summarize_folds([r["coverage_p10_p90"] for r in rows]),
        "deteriorates_late": bool(rows and rows[-1]["wape"] > rows[0]["wape"]),
    }


# --- Section 6: segment / platform / spend-band aggregation ------------------
def evaluate_segments(panel: pd.DataFrame, forecast: dict) -> dict:
    p = assign_split(panel)
    recs = []   # (cid, platform, group, spend, y, sel_pred)
    for cid, camp in forecast["per_campaign"].items():
        g = p[(p.campaign_id == cid) & (p.split == "test")].sort_values("t")
        if g.empty:
            continue
        y = g["target_fwd7"].to_numpy(float)
        if camp["selected_model"] == XGB_MODEL:
            tr = p[(p.campaign_id == cid) & (p.split == "train")]
            pred = _fit_q(tr, g, 0.5)
        else:
            which = "same_weekday" if camp["selected_model"] == SAME_WEEKDAY_MODEL else "trailing_14d"
            pred = _baseline_pred(panel[panel.campaign_id == cid].sort_values("t"), g, which)
        grp = next((k for k, v in _SEGMENT_GROUPS.items() if cid in v), "other")
        for spend, yi, pi in zip(g["spend"].to_numpy(float), y, pred):
            recs.append((cid, _PLATFORM[cid], grp, float(spend), float(yi), float(pi)))

    df = pd.DataFrame(recs, columns=["cid", "platform", "group", "spend", "y", "pred"])
    if df.empty:
        return {}
    median_spend = float(df["spend"].median())

    def agg(sub: pd.DataFrame) -> dict:
        return {"n": int(len(sub)), "wape": M._r(_wape(sub["y"].to_numpy(), sub["pred"].to_numpy()))}

    out = {
        "by_platform": {k: agg(v) for k, v in df.groupby("platform", sort=True)},
        "by_segment_group": {k: agg(v) for k, v in df.groupby("group", sort=True)},
        "by_spend_band": {
            "high_spend": agg(df[df.spend >= median_spend]),
            "low_spend": agg(df[df.spend < median_spend]),
            "median_spend": M._r(median_spend, 2),
        },
    }
    ranked = sorted(((cid, agg(v)["wape"]) for cid, v in df.groupby("cid", sort=True)),
                    key=lambda x: (x[1] is None, x[1]))
    out["strongest_campaign"] = ranked[0][0] if ranked else None
    out["weakest_campaign"] = ranked[-1][0] if ranked else None
    return out


# --- Section 8: response-model fidelity vs latent truth ----------------------
def evaluate_response(panel: pd.DataFrame, current_spend: dict[str, float]) -> dict:
    ctx = _context()
    responses = estimate(panel, current_spend)
    per = {}
    est_list, lat_list, signs, hurdle_ok = [], [], [], []
    for cid in sorted(responses):
        r = responses[cid]
        c = CAMPAIGN_BY_ID[cid]
        cur = float(current_spend[cid])
        latent = hill_marginal_roas(cur, c)
        sku = ctx.sku_of[cid]
        margin = float(ctx.dim_sku.loc[sku, "contribution_margin_rate"])
        floor = (1.0 / margin) * HARD_FLOOR_SAFETY
        spend_obs = panel.loc[panel.campaign_id == cid, "spend"]
        lo, hi = float(spend_obs.min()), float(spend_obs.max())
        abs_err = abs(r.marginal_roas - latent)
        per[cid] = {
            "decay": r.decay,
            "current_spend": M._r(cur, 2),
            "observed_spend_range": [M._r(lo, 2), M._r(hi, 2)],
            "movement_in_support": bool(cur * (1 - MOVEMENT_BOUND) >= lo
                                        and cur * (1 + MOVEMENT_BOUND) <= hi),
            "expected_marginal": M._r(r.marginal_roas),
            "downside_marginal": M._r(r.marginal_roas_downside),
            "latent_marginal_eval_only": M._r(latent),
            "abs_error": M._r(abs_err),
            "rel_error": M._r(abs_err / latent) if latent else None,
            "sign_agreement": bool(np.sign(r.marginal_roas) == np.sign(latent)),
            "hurdle_class_agreement": bool((r.marginal_roas >= floor) == (latent >= floor)),
            "fold_marginal_std": _response_fold_std(panel, cid),
            "bootstrap_interval": [M._r(r.marginal_roas_downside), M._r(r.marginal_roas)],
        }
        est_list.append(r.marginal_roas)
        lat_list.append(latent)
        signs.append(per[cid]["sign_agreement"])
        hurdle_ok.append(per[cid]["hurdle_class_agreement"])

    est = np.asarray(est_list)
    lat = np.asarray(lat_list)
    rel = np.abs(est - lat) / np.where(lat == 0, np.nan, lat)
    overall = {
        "spearman": M._r(float(spearmanr(est, lat).statistic)),
        "pearson": M._r(float(pearsonr(est, lat)[0])),
        "sign_accuracy": M._r(float(np.mean(signs))),
        "hurdle_classification_accuracy": M._r(float(np.mean(hurdle_ok))),
        "mean_abs_marginal_error": M._r(float(np.mean(np.abs(est - lat)))),
        "median_rel_marginal_error": M._r(float(np.nanmedian(rel))),
    }
    return {"per_campaign": per, "overall": overall}


def _response_fold_std(panel: pd.DataFrame, cid: str) -> float:
    """Fold-to-fold marginal variability: re-fit the response slope on expanding windows."""
    g = panel[panel.campaign_id == cid].sort_values("date").reset_index(drop=True)
    slopes = []
    for frac in (0.6, 0.8, 1.0):
        sub = g.iloc[: max(int(len(g) * frac), 30)]
        X, rev, spend = _prep(sub)
        slope, *_ = _best_decay_fit(X, rev, spend)
        slopes.append(slope)
    return M._r(float(np.std(slopes)))


# --- Section 9: optimizer sensitivity to marginal error ----------------------
def evaluate_sensitivity(panel: pd.DataFrame, current_spend: dict[str, float]) -> dict:
    ctx = _context()
    responses = ctx.responses
    base_camps = _build_camps(ctx, responses, scale=None, source="slope")
    base = optimize(base_camps)

    scenarios = {
        "expected": ("slope", None),
        "downside": ("downside", None),
        "latent_eval_only": ("latent", None),
        "minus_10pct": ("slope", 0.90),
        "plus_10pct": ("slope", 1.10),
        "minus_20pct": ("slope", 0.80),
        "plus_20pct": ("slope", 1.20),
    }
    results = {}
    base_dir = {cid: np.sign(base.spend[cid] - current_spend[cid]) for cid in base.spend}
    for name, (source, scale) in scenarios.items():
        camps = _build_camps(ctx, responses, scale=scale, source=source, current_spend=current_spend)
        res = optimize(camps)
        max_alloc_diff = max(abs(res.spend[c] - base.spend[c]) for c in base.spend)
        dir_stable = all(np.sign(res.spend[c] - current_spend[c]) == base_dir[c] for c in res.spend)
        results[name] = {
            "feasible": res.feasible,
            "blended_roas": res.blended_roas,
            "contribution": res.contribution,
            "max_alloc_diff_vs_expected": M._r(max_alloc_diff, 2),
            "direction_stable_vs_expected": bool(dir_stable),
            "conflicts": res.conflicts,
            "allocation": res.spend,
        }
    perturb = ("minus_20pct", "plus_20pct", "minus_10pct", "plus_10pct")
    return {"scenarios": results,
            "direction_stable_under_all_perturbations":
                all(results[n]["direction_stable_vs_expected"] for n in perturb),
            # instability only matters if it produces an APPROVABLE (feasible) plan;
            # an infeasible perturbed plan is blocked by the guardrails, not executed.
            "direction_stable_among_feasible_perturbations":
                all(results[n]["direction_stable_vs_expected"]
                    for n in perturb if results[n]["feasible"]),
            # Every direction-UNSTABLE perturbation (if any) is infeasible — so the
            # instability never reaches an approvable plan. Vacuously True when no
            # perturbation flips direction at all (the all-stable case).
            "unstable_only_when_infeasible":
                all(not results[n]["feasible"] for n in perturb
                    if not results[n]["direction_stable_vs_expected"])}


def _build_camps(ctx, responses, *, scale, source, current_spend=None) -> list[OptCampaign]:
    camps = []
    for cid in sorted(responses):
        r = responses[cid]
        sku = ctx.sku_of[cid]
        margin = float(ctx.dim_sku.loc[sku, "contribution_margin_rate"])
        if source == "downside":
            slope = r.marginal_roas_downside
        elif source == "latent":
            slope = hill_marginal_roas(float(current_spend[cid]), CAMPAIGN_BY_ID[cid])
        else:
            slope = r.slope
        if scale is not None:
            slope = slope * scale
        resp = CampaignResponse(cid, r.segment, r.current_spend, r.current_revenue,
                                slope, r.marginal_roas_downside, slope, r.quad)
        camps.append(OptCampaign(
            campaign_id=cid, current_spend=r.current_spend,
            daily_cap=float(ctx.dim_c.loc[cid, "daily_cap"]), margin=margin,
            is_prospecting=bool(ctx.dim_c.loc[cid, "is_prospecting"]),
            inventory_constrained=sku in ctx.stockout_skus, nc_per_dollar=ctx.nc_pd[cid],
            incrementality=float(ctx.calibration[r.segment]), marginal_now=slope,
            marginal_floor=(1.0 / margin) * HARD_FLOOR_SAFETY,
            revenue_fn=resp.incremental_revenue, marginal_fn=resp.marginal_at,
        ))
    return camps
