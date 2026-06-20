"""Contribution-economics contract (D-040, Phase 2).

Guards the explicit variable-cost margin formula:

    CM = [ P(1-r) - C(1 - r·ρ) - F - f·P - r·H ] / P

These are STRUCTURAL/MONOTONIC invariants (not pinned dollar values): the margin
must respond in the economically correct direction to every cost, the formula must
reconcile to its own waterfall, and returns/recovery must enter contribution ONLY
through the margin — never a second time in the generated revenue/orders/inventory.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

import backend.decision_engine.synth.scenario as S
from backend.decision_engine.config import MASTER_SEED
from backend.decision_engine.synth.generator import generate

_BASE = S.PRODUCT_BY_SKU["TC-POLO-CLS"]


def _cm(**overrides) -> float:
    return replace(_BASE, **overrides).contribution_margin_rate


def test_zero_returns_reduces_to_no_return_formula():
    """r=0 ⇒ CM = (P - C - F - f·P)/P (no return terms survive)."""
    P, C, F, f = _BASE.unit_price, _BASE.unit_cost, _BASE.fulfillment_cost, _BASE.payment_fee_rate
    expected = round((P - C - F - f * P) / P, 4)
    assert _cm(return_rate=0.0) == expected


def test_outbound_fulfillment_is_charged_on_returns():
    """The D-040 correction: with f=0, H=0, ρ=1 the new margin is exactly the OLD
    (P-C-F)(1-r)/P minus r·F/P — i.e. outbound is now paid on returned orders too."""
    p = _cm(payment_fee_rate=0.0, return_handling_cost=0.0, cogs_recovery_rate=1.0)
    P, C, F, r = _BASE.unit_price, _BASE.unit_cost, _BASE.fulfillment_cost, _BASE.return_rate
    old = (P - C - F) * (1.0 - r) / P
    assert old - p == pytest.approx(r * F / P, abs=1e-4)


@pytest.mark.parametrize("override,direction", [
    ({"payment_fee_rate": _BASE.payment_fee_rate + 0.02}, "down"),
    ({"return_handling_cost": _BASE.return_handling_cost + 10.0}, "down"),
    ({"return_rate": _BASE.return_rate + 0.10}, "down"),
    ({"unit_cost": _BASE.unit_cost + 5.0}, "down"),
    ({"fulfillment_cost": _BASE.fulfillment_cost + 2.0}, "down"),
    ({"cogs_recovery_rate": min(_BASE.cogs_recovery_rate + 0.15, 1.0)}, "up"),
])
def test_each_cost_moves_margin_in_the_right_direction(override, direction):
    base = _BASE.contribution_margin_rate
    moved = _cm(**override)
    if direction == "down":
        assert moved < base
    else:
        assert moved > base


def test_full_recovery_credits_returned_cogs():
    """ρ=1 ⇒ returned units pay no net COGS; raising ρ from baseline must raise margin."""
    assert _cm(cogs_recovery_rate=1.0) > _BASE.contribution_margin_rate


def test_waterfall_reconciles_to_margin():
    """Per-component contribution must sum to CM·P for every SKU (no hidden term)."""
    for p in S.PRODUCTS:
        P, C, F = p.unit_price, p.unit_cost, p.fulfillment_cost
        r, f, H, rho = p.return_rate, p.payment_fee_rate, p.return_handling_cost, p.cogs_recovery_rate
        contribution = P * (1 - r) - C * (1 - r * rho) - F - f * P - r * H
        assert p.contribution_margin_rate == pytest.approx(round(contribution / P, 4))
        assert 0.0 < p.contribution_margin_rate < 1.0


def test_weighted_return_rate_reported_both_ways():
    """Report revenue- and unit-weighted portfolio return rates; both land ≈13.5%."""
    rev = {p.sku_id: 0.0 for p in S.PRODUCTS}
    units = {p.sku_id: 0.0 for p in S.PRODUCTS}
    for c in S._UNIT_CAMPAIGNS:
        r = float(S.hill_revenue(c.base_spend, c))
        rev[c.primary_sku] += r
        units[c.primary_sku] += r / S.PRODUCT_BY_SKU[c.primary_sku].unit_price
    tot_rev, tot_u = sum(rev.values()), sum(units.values())
    rate = S.PRODUCT_BY_SKU
    rev_w = sum(rev[s] * rate[s].return_rate for s in rev) / tot_rev
    unit_w = sum(units[s] * rate[s].return_rate for s in units) / tot_u
    assert rev_w == pytest.approx(0.135, abs=0.01)
    assert unit_w == pytest.approx(0.133, abs=0.01)


def test_recovery_does_not_leak_into_generated_revenue(monkeypatch):
    """No double-counting: changing COGS recovery changes ONLY the margin (a dim_sku
    column). Generated fact / commerce / inventory tables must be byte-identical, i.e.
    returns/recovery are applied exactly once — in the contribution margin."""
    base = generate(MASTER_SEED, profile="golden")
    bumped_products = tuple(replace(p, cogs_recovery_rate=0.50) for p in S.PRODUCTS)
    monkeypatch.setattr(S, "PRODUCTS", bumped_products)
    monkeypatch.setattr(S, "PRODUCT_BY_SKU", {p.sku_id: p for p in bumped_products})
    bumped = generate(MASTER_SEED, profile="golden")
    for name, df in base.tables.items():
        if name == "dim_sku":
            continue  # only the margin column legitimately differs
        pd.testing.assert_frame_equal(df, bumped.tables[name], obj=name)
