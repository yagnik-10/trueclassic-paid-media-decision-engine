"""Cross-layer consistency gates for the report / engine / marts.

These encode the *trust* invariants an external review asked for — but with the
CORRECT invariant. The displayed/evaluated/served forecasts must agree on the SELECTED
MODEL per campaign; they do NOT (and must not) agree on the numeric P50, because the
evaluation frame is a holdout (trained on pre-test rows, scored on the test window)
while the live forecast predicts the *current operating point* trained on all mature
rows. Asserting numeric P50 equality there would be a methodological error.
"""

from __future__ import annotations

from backend.decision_engine import config as C
from backend.decision_engine.engine.bau_forecast import forecast as live_forecast
from backend.decision_engine.engine.data import load_engine_inputs
from backend.decision_engine.eval import harness as H
from backend.decision_engine.synth.fingerprint import (
    canonical_tables_fingerprint,
    frame_fingerprint,
)
from backend.decision_engine.synth.generator import generate


def test_selected_model_agrees_across_eval_chart_and_live_engine():
    """The frozen selector picks ONE champion per campaign; the evaluation frame (chart
    source), the pooled forecast, and the LIVE engine must all serve that same model.
    Also: in the eval frame the centered series equals the selected model's prediction
    (``p50 == pred``) — the fix that stopped the fan showing XGBoost for a baseline
    champion. This is the campaign-by-campaign integrity gate."""
    panel = load_engine_inputs().panel
    fc = H.evaluate_forecast(panel)
    tf = H.build_test_frame(panel, fc)
    live, _ = live_forecast(panel)
    sel = fc["selected_models"]
    assert set(sel) == set(live)

    for cid, model in sel.items():
        g = tf[tf.cid == cid]
        assert not g.empty, f"no test rows for {cid}"
        # one model per campaign in the eval frame, and it is the selected champion
        assert set(g["model"].unique()) == {model}
        # the centered series IS the selected model's point (not XGBoost-by-default)
        assert (abs(g["p50"] - g["pred"]) < 1e-9).all(), f"{cid}: p50 != selected pred"
        # the live engine serves the SAME model choice (model identity, not numeric P50)
        assert live[cid].model == model, f"{cid}: live model != selected"


def test_report_and_mart_fingerprints_reconcile_by_design():
    """The model report headline uses the CANONICAL-tables fingerprint; the ledger/mart
    (and the recommendation) use the modeling-PANEL fingerprint. They are deliberately
    different hashes of the same profile — the marts MANIFEST carries both so they
    reconcile. This gate guards that mapping (and that they are NOT accidentally equal)."""
    from backend.api.recommendation import build_recommendation
    from backend.decision_engine.eval.report import _provenance

    inputs = load_engine_inputs()
    panel_fp = frame_fingerprint(inputs.panel)
    canonical_fp = canonical_tables_fingerprint(generate().tables)

    # report headline == canonical-tables fingerprint
    assert _provenance()["data_fingerprint"] == canonical_fp
    # recommendation / ledger / mart fingerprint == modeling-panel fingerprint
    rec = build_recommendation("expected")
    assert rec.data_fingerprint == panel_fp
    # the two are different by design (why the manifest must surface both)
    assert panel_fp != canonical_fp
    assert C.DATASET_PROFILE in ("golden", "realistic")


def test_baseline_champion_band_is_the_heuristic_not_conformal():
    """The deployed band for a BASELINE champion is the operational ±20% heuristic
    (p10 = 0.8·p50, p90 = 1.2·p50), NOT a conformal-calibrated interval. Guards the
    honest labeling: only XGBoost champions get the calibrated band."""
    panel = load_engine_inputs().panel
    live, _ = live_forecast(panel)
    baseline = [f for f in live.values() if not f.model.startswith("xgboost")]
    assert baseline, "expected at least one baseline champion in the realistic profile"
    for f in baseline:
        # ±20% heuristic (tolerant of the engine's 2-decimal rounding)
        assert abs(f.p10 / f.p50 - 0.8) < 1e-3
        assert abs(f.p90 / f.p50 - 1.2) < 1e-3
        # heuristic band is NOT conformal-widened: raw == served edges
        assert f.p10 == f.p10_raw and f.p90 == f.p90_raw
