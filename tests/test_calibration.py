"""S4.3 — calibration registry + platform-vs-calibrated sensitivity."""

from __future__ import annotations

import pytest

from backend.decision_engine.calibration.registry import (
    apply_overrides,
    calibration_map,
    load_registry,
)
from backend.decision_engine.engine.recommend import Constraints, build_engine_recommendation


def test_registry_has_provenance_for_all_segments():
    entries = load_registry()
    segments = {e.segment for e in entries}
    assert segments == {
        "meta_prospecting", "meta_retargeting", "google_brand", "google_nonbrand",
    }
    for e in entries:
        assert e.is_synthetic is True
        assert e.source and e.confidence and e.scope
        assert e.effective_start


def test_apply_overrides_validates_segment_and_bounds():
    base = calibration_map()
    with pytest.raises(ValueError, match="unknown calibration segment"):
        apply_overrides(base, {"amazon_dsp": 0.5})
    with pytest.raises(ValueError, match="must be in"):
        apply_overrides(base, {"meta_retargeting": 0.0})


def test_retargeting_platform_roas_exceeds_calibrated():
    rec = build_engine_recommendation("expected")
    rt = next(ln for ln in rec.lines if ln.campaign_id == "META_RETARGETING")
    assert rt.platform_roas_current > rt.calibrated_roas_current + 1.0
    assert rt.incrementality < 0.5


def test_calibration_override_changes_recommendation():
    base = build_engine_recommendation("expected")
    perturbed = build_engine_recommendation(
        "expected",
        Constraints(calibration_overrides=(("meta_retargeting", 0.25),)),
    )
    assert perturbed.calibration_registry
    row = next(r for r in perturbed.calibration_registry if r["segment"] == "meta_retargeting")
    assert row["overridden"] is True
    assert row["coefficient"] == pytest.approx(0.25)
    assert perturbed.blended_roas_projected != base.blended_roas_projected


def test_provenance_lists_effective_coefficients():
    rec = build_engine_recommendation("expected")
    assert len(rec.calibration_registry) == 4
    for row in rec.calibration_registry:
        assert row["coefficient"] == row["approved_coefficient"]
        assert row["overridden"] is False


def test_override_sets_sensitivity_flag_but_base_keeps_fingerprint():
    base = build_engine_recommendation("expected")
    ov = build_engine_recommendation(
        "expected", Constraints(calibration_overrides=(("meta_retargeting", 0.45),)))
    assert base.is_sensitivity_override is False
    assert ov.is_sensitivity_override is True
    # the registry fingerprint pins the APPROVED base version; an override (which is
    # NOT written to the registry) must not change it — both reference the same base.
    assert ov.calibration_fingerprint == base.calibration_fingerprint
    assert base.calibration_fingerprint


def test_platform_roas_stays_comparison_only_under_override():
    # sliders change the CALIBRATED decision basis; the optimizer's enforced floor is
    # the calibrated blended ROAS, never platform ROAS. Platform ROAS at current spend
    # is fixed by the feed (revenue/spend) and is invariant to the coefficient.
    base = build_engine_recommendation("expected")
    ov = build_engine_recommendation(
        "expected", Constraints(calibration_overrides=(("meta_retargeting", 0.5),)))
    b_rt = next(ln for ln in base.lines if ln.campaign_id == "META_RETARGETING")
    o_rt = next(ln for ln in ov.lines if ln.campaign_id == "META_RETARGETING")
    assert o_rt.platform_roas_current == pytest.approx(b_rt.platform_roas_current, abs=1e-3)
    assert o_rt.calibrated_roas_current != b_rt.calibrated_roas_current  # calibrated DID move
