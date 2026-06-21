"""Curated, versioned view over the deterministic model-performance report.

NOT a passthrough of ``reports/model_performance/metrics.json``: it exposes only the
fields the Model Evidence page needs, on a stable contract, with latent generator-truth
stripped. It also stamps a fresh/stale verdict by comparing the report's
``evidence_input_fingerprint`` to the LIVE engine identity — so the page can warn when a
report predates a data/config/calibration change behind the active recommendation.

v1 surfaces Champion Selection only (pre-test selection evidence + the separate
untouched-test panel + holdout drift). Deeper workbenches (intervals, response, latent
marginal recovery, optimizer perturbation) are deferred.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from backend.api.schemas import (
    ChampionCampaign,
    ChampionPreTest,
    EvidenceProvenance,
    EvidenceSummary,
    ForecastSeriesPoint,
    ModelEvidenceResponse,
    ModelTestPoint,
)
from backend.decision_engine.eval.provenance import REPORT_VERSION, evidence_input_fingerprint
from backend.decision_engine.eval.report import OUT_DIR

SCHEMA_VERSION = "model-evidence.v2"   # v2 adds row-level untouched-test series (Phase D)
_METRICS_PATH = OUT_DIR / "metrics.json"
_PREDICTIONS_PATH = OUT_DIR / "test_predictions.csv"
# the three models scored on the untouched test (champion mirrors one of them)
_TEST_MODELS = ("xgboost_p50", "baseline_trailing_14d", "baseline_same_weekday")


class ReportNotFound(Exception):
    """metrics.json has not been generated yet (run `make model-report`)."""


def _load_series(path: Path) -> dict[str, list[ForecastSeriesPoint]]:
    """Per-campaign untouched-test series from the row-level artifact (Phase D). Returns
    an empty map when the file is absent (report predates the artifact) — the endpoint
    then reports ``series_available=False`` and the UI falls back to bars only."""
    if not path.exists():
        return {}
    by_cid: dict[str, list[ForecastSeriesPoint]] = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            try:
                y, p10, p50, p90 = (float(row["y"]), float(row["p10"]),
                                    float(row["p50"]), float(row["p90"]))
                pred = float(row["pred"])
            except (KeyError, ValueError):
                continue
            by_cid.setdefault(row["cid"], []).append(ForecastSeriesPoint(
                date=row["date"], actual=y, pred=pred, p10=p10, p50=p50, p90=p90,
                residual=float(row.get("residual", pred - y)),
                covered=bool(p10 <= y <= p90),
            ))
    for pts in by_cid.values():
        pts.sort(key=lambda p: p.date)
    return by_cid


def _load_metrics(path: Path) -> tuple[dict, str]:
    if not path.exists():
        raise ReportNotFound(
            f"no model report at {path}; run `make model-report` to generate it"
        )
    report = json.loads(path.read_text())
    generated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    return report, generated_at


def _champion_campaigns(forecast: dict, drift_by_cid: dict[str, dict],
                        series_by_cid: dict[str, list[ForecastSeriesPoint]]) -> list[ChampionCampaign]:
    out: list[ChampionCampaign] = []
    for cid, pc in sorted(forecast["per_campaign"].items()):
        selected = pc["selected_model"]
        is_xgb = selected == "xgboost_quantile"
        sel = pc.get("selection") or {}
        # pre-test selection evidence only exists when XGBoost was a promote/keep candidate;
        # the two persisted bars are the XGBoost candidate and the BEST baseline.
        pretest = None
        if sel.get("xgb_wape") is not None and sel.get("baseline_wape") is not None:
            pretest = ChampionPreTest(
                xgb_wape=sel["xgb_wape"], best_baseline_wape=sel["baseline_wape"],
                improvement_pct=sel.get("improvement_pct", 0.0),
                fold_wins=sel.get("fold_wins", 0), n_folds=sel.get("n_folds", 0),
                threshold=sel.get("threshold", 0.05), reason=sel.get("reason", ""),
            )
        point = pc.get("point", {})
        test_points = [
            ModelTestPoint(model=m, wape=point.get(m, {}).get("wape"),
                           mae=point.get(m, {}).get("mae"),
                           bias_me=point.get(m, {}).get("bias_me"))
            for m in _TEST_MODELS
        ]
        champion_wape = point.get("selected", {}).get("wape")
        baseline_wapes = [point.get(m, {}).get("wape")
                          for m in ("baseline_trailing_14d", "baseline_same_weekday")]
        baseline_wapes = [w for w in baseline_wapes if w is not None]
        best_baseline = min(baseline_wapes) if baseline_wapes else None
        drift = drift_by_cid.get(cid)
        series = series_by_cid.get(cid, [])
        coverage = (round(sum(p.covered for p in series) / len(series), 4)
                    if series else None)
        out.append(ChampionCampaign(
            campaign_id=cid, selected_model=selected, is_xgb_champion=is_xgb,
            pretest=pretest, test_points=test_points,
            champion_test_wape=champion_wape, best_baseline_test_wape=best_baseline,
            holdout_drift=drift is not None,
            drift_pct_worse=(drift.get("pct_worse") if drift else None),
            test_series=series, test_coverage=coverage,
        ))
    return out


def model_evidence() -> ModelEvidenceResponse:
    report, generated_at = _load_metrics(_METRICS_PATH)
    prov = report.get("provenance", {})
    interp = report.get("interpretation", {})
    forecast = report.get("forecast", {})

    drift_by_cid = {d["campaign"]: d for d in interp.get("champion_holdout_drift", [])}
    series_by_cid = _load_series(_PREDICTIONS_PATH)

    # fresh vs stale: the report's frozen identity vs the LIVE engine identity. A report
    # generated before a data/config/calibration change behind the active recommendation
    # no longer describes the models the engine now serves.
    report_fp = prov.get("evidence_input_fingerprint", "")
    live_fp = evidence_input_fingerprint()
    stale = bool(report_fp) and report_fp != live_fp
    stale_reason = (
        "report modeling-input identity differs from the active engine "
        "(data / config / calibration / engine changed since it was generated); regenerate via `make model-report`"
        if stale else None
    )

    provenance = EvidenceProvenance(
        dataset_profile=prov.get("dataset_profile", ""),
        engine_version=prov.get("engine_version", ""),
        report_version=prov.get("report_version", REPORT_VERSION),
        data_fingerprint=prov.get("data_fingerprint", ""),
        panel_data_fingerprint=prov.get("panel_data_fingerprint", ""),
        config_fingerprint=prov.get("config_fingerprint", ""),
        calibration_fingerprint=prov.get("calibration_fingerprint", ""),
        evidence_input_fingerprint=report_fp,
        master_seed=int(prov.get("master_seed", 0)),
        note=prov.get("note", ""),
    )
    summary = EvidenceSummary(
        overall_test_wape=interp.get("overall_test_wape"),
        approx_point_accuracy_pct=interp.get("approx_point_accuracy_pct"),
        xgb_materially_beats_baseline_in=list(interp.get("xgb_materially_beats_baseline_in", [])),
        fallback_campaigns=list(interp.get("fallback_campaigns", [])),
        champion_holdout_drift_campaigns=[d["campaign"] for d in interp.get("champion_holdout_drift", [])],
        safe_for_model_demo=bool(interp.get("safe_for_model_demo", False)),
        safe_for_decision_demo=bool(interp.get("safe_for_decision_demo", False)),
    )
    return ModelEvidenceResponse(
        schema_version=SCHEMA_VERSION,
        report_version=provenance.report_version,
        generated_at=generated_at,
        stale=stale, stale_reason=stale_reason,
        active_evidence_input_fingerprint=live_fp,
        series_available=bool(series_by_cid),
        provenance=provenance, summary=summary,
        campaigns=_champion_campaigns(forecast, drift_by_cid, series_by_cid),
    )
