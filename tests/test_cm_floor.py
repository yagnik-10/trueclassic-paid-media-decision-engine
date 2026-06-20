"""Phase-4 (D-041) read-only CM-ROAS floor mechanism + policy-sweep smoke test.

The portfolio CM-ROAS floor is an OPTIONAL, default-OFF optimizer input used only by
the read-only sweep. These tests lock its semantics (off = no-op, slack below the
operating point, infeasible above the achievable ceiling, reported in the binding
report only when active) and that the sweep artifact builds and reaches its headline
conclusion. No production default/policy is exercised here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from backend.decision_engine.engine.recommend import Constraints, build_engine_recommendation


def _rec(**kw):
    return build_engine_recommendation("expected", Constraints(**kw))


def test_cm_floor_off_by_default_is_noop():
    base = _rec()                      # live policy, CM floor implicitly off
    same = _rec(cm_roas_floor=0.0)     # explicitly off
    assert base.cm_roas_projected == same.cm_roas_projected
    assert ([ln.recommended_spend for ln in base.lines]
            == [ln.recommended_spend for ln in same.lines])


def test_cm_floor_absent_from_binding_report_when_off():
    names = {b["name"] for b in _rec().binding["portfolio"]}
    assert "cm_roas_floor" not in names


def test_cm_floor_below_operating_point_is_slack_and_keeps_plan():
    # gross floor disabled; a CM floor well below the ~1.94× operating point is slack
    none = _rec(roas_floor=0.0)
    low = _rec(roas_floor=0.0, cm_roas_floor=1.0)
    assert low.feasible
    port = {b["name"]: b for b in low.binding["portfolio"]}
    assert port["cm_roas_floor"]["status"] == "slack"
    for a, b in zip(none.lines, low.lines):
        assert abs(a.recommended_spend - b.recommended_spend) <= 2.0


def test_cm_floor_above_ceiling_is_infeasible_and_reported():
    high = _rec(roas_floor=0.0, cm_roas_floor=2.20)
    assert not high.feasible
    assert any("CM ROAS" in c for c in high.conflicts)
    port = {b["name"]: b for b in high.binding["portfolio"]}
    assert port["cm_roas_floor"]["status"] == "violated"


def test_growth_cm_floor_is_redundant_with_objective():
    # In growth, spend is fixed so max net contribution == max CM ROAS: a CM floor at the
    # achieved value can only bind, never improve — the plan must be unchanged.
    none = _rec(roas_floor=0.0)
    at = _rec(roas_floor=0.0, cm_roas_floor=round(none.cm_roas_projected, 2))
    assert at.cm_roas_projected == pytest.approx(none.cm_roas_projected, abs=2e-3)
    for a, b in zip(none.lines, at.lines):
        assert abs(a.recommended_spend - b.recommended_spend) <= 2.0


def _load_sweep():
    path = Path(__file__).resolve().parents[1] / "scripts" / "cm_floor_sweep.py"
    spec = importlib.util.spec_from_file_location("cm_floor_sweep", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sweep_builds_and_reaches_ceiling_conclusion():
    sweep = _load_sweep()
    md, payload = sweep.build(n_dev=2, n_acc=2)
    assert "portfolio CM-ROAS floor" in md
    g = payload["central"]["growth"]
    e = payload["central"]["efficiency_first"]
    assert g["gross_floor_status_at_reference"] in ("slack", "binding")
    # Growth ceiling = the objective's own max CM (redundant floor); efficiency-first can
    # withhold budget to clear a higher floor, so its ceiling is strictly higher.
    assert g["achievable_cm_ceiling"] is not None and e["achievable_cm_ceiling"] is not None
    assert e["achievable_cm_ceiling"] > g["achievable_cm_ceiling"] + 1e-3
    assert payload["robustness"]["n_dev"] == 2
