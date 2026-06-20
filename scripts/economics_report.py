#!/usr/bin/env python
"""Reproducible contribution-economics report (D-040, Phase 2).

    make econ-report     # prints + writes reports/economics/ECONOMICS.md

Shows the explicit variable-cost stack that produces each SKU's contribution
margin, the revenue-/unit-weighted portfolio return rate, the per-campaign
break-even and marginal hurdles, and a sensitivity grid over the synthetic
reverse-logistics assumptions (COGS recovery, return rate, return handling).
All numbers are emergent from scenario.py — nothing here is tuned to a target.
"""

from __future__ import annotations

from pathlib import Path

from backend.decision_engine import economics as E
from backend.decision_engine.engine.recommend import engine_config
from backend.decision_engine.synth import scenario as S

OUT = Path("reports/economics/ECONOMICS.md")

# Pre-declared sensitivity grid (D-040) — declared BEFORE observing allocation.
RECOVERY = (0.50, 0.80, 1.00)
HANDLING = (4.0, 8.0, 12.0)
RETURNS_BASE = {"TC-CREW-BLK": 0.12, "TC-POLO-CLS": 0.14, "TC-JOG-BLK": 0.18, "TC-CREW-6PK": 0.12}
RETURNS_HIGH = {"TC-CREW-BLK": 0.15, "TC-POLO-CLS": 0.17, "TC-JOG-BLK": 0.22, "TC-CREW-6PK": 0.15}


def _cm(P, C, F, r, f, H, rho) -> float:
    return (P * (1 - r) - C * (1 - r * rho) - F - f * P - r * H) / P


def _revenue_weights() -> dict[str, float]:
    rev = {p.sku_id: 0.0 for p in S.PRODUCTS}
    for c in S._UNIT_CAMPAIGNS:
        rev[c.primary_sku] += float(S.hill_revenue(c.base_spend, c))
    return rev


def _weighted_cm(returns: dict[str, float], H: float, rho: float, rev: dict[str, float]) -> float:
    tot = sum(rev.values())
    return sum(
        rev[p.sku_id] * _cm(p.unit_price, p.unit_cost, p.fulfillment_cost,
                            returns[p.sku_id], p.payment_fee_rate, H, rho)
        for p in S.PRODUCTS
    ) / tot


def build() -> str:
    rev = _revenue_weights()
    tot_rev = sum(rev.values())
    units = {p.sku_id: rev[p.sku_id] / p.unit_price for p in S.PRODUCTS}
    tot_u = sum(units.values())
    safety = engine_config().hard_floor_safety
    L: list[str] = []
    a = L.append

    a("# Contribution economics (D-040)\n")
    a("Explicit variable-cost stack; margins are **emergent**, not tuned. The "
      "specific payment-fee, return-handling and COGS-recovery values are synthetic "
      "assumptions, not verified True Classic ledger figures.\n")

    a("## Per-SKU cost waterfall ($/order and % of price)\n")
    a("| SKU | Price | COGS | Outbound | Pay fee | Exp. refund | Net COGS recov. | Return handling | Contribution | CM rate |")
    a("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for p in S.PRODUCTS:
        P, C, F = p.unit_price, p.unit_cost, p.fulfillment_cost
        r, f, H, rho = p.return_rate, p.payment_fee_rate, p.return_handling_cost, p.cogs_recovery_rate
        refund = r * P
        recov = r * rho * C            # COGS value credited back
        handling = r * H
        contribution = P * (1 - r) - C * (1 - r * rho) - F - f * P - r * H
        a(f"| {p.sku_id} | {P:.2f} | {C:.2f} | {F:.2f} | {f*P:.2f} | {refund:.2f} | "
          f"+{recov:.2f} | {handling:.2f} | {contribution:.2f} | {p.contribution_margin_rate*100:.1f}% |")
    a("")
    a(f"- **Revenue-weighted return rate:** {sum(rev[s]*S.PRODUCT_BY_SKU[s].return_rate for s in rev)/tot_rev*100:.1f}%")
    a(f"- **Unit-weighted return rate:** {sum(units[s]*S.PRODUCT_BY_SKU[s].return_rate for s in units)/tot_u*100:.1f}%")
    a(f"- **Revenue-weighted portfolio CM:** {_weighted_cm(RETURNS_BASE, 8.0, 0.80, rev)*100:.1f}%")
    a(f"- **Spend-weighted CM (optimizer):** {E.WEIGHTED_CONTRIBUTION_MARGIN*100:.1f}% · "
      f"break-even ROAS {E.BREAKEVEN_ROAS:.3f}× · hard scale floor {E.HARD_SCALE_FLOOR:.3f}×\n")

    a("## Per-campaign break-even & marginal hurdle (rises as margin falls — D-040)\n")
    a("| Campaign | SKU | CM rate | break-even ROAS | marginal hurdle (×safety) |")
    a("|---|---|--:|--:|--:|")
    for c in S.CAMPAIGNS:
        m = S.PRODUCT_BY_SKU[c.primary_sku].contribution_margin_rate
        a(f"| {c.campaign_id} | {c.primary_sku} | {m*100:.1f}% | {1/m:.3f}× | {1/m*safety:.3f}× |")
    a("")

    a("## Contribution: current vs optimized allocation\n")
    a("Net contribution after ads is the optimizer objective, on calibrated/incremental "
      "revenue: **net = Σᵢ mᵢ·Rᵢ − Σᵢ bᵢ**; pre-ad contribution = Σᵢ mᵢ·Rᵢ. Both rows use "
      "the SAME post-D-040 margins, so the comparison isolates the allocation, not the "
      "cost model.\n")
    try:
        from backend.decision_engine.engine.recommend import build_engine_recommendation
        rec = build_engine_recommendation("expected")
        sv = rec.binding["solver"]
        cur_spend, opt_spend = rec.total_current_spend, rec.total_recommended_spend
        cur_net = sv["current_allocation_contribution"]
        opt_net = sv["best_contribution"]
        a("| Allocation | Pre-ad contribution | Ad spend | Net contribution after ads | CM ROAS |")
        a("|---|--:|--:|--:|--:|")
        a(f"| Current | ${cur_net + cur_spend:,.0f} | ${cur_spend:,.0f} | ${cur_net:,.0f} | {rec.cm_roas_current:.2f}× |")
        a(f"| Optimized candidate | ${opt_net + opt_spend:,.0f} | ${opt_spend:,.0f} | ${opt_net:,.0f} | {rec.cm_roas_projected:.2f}× |")
        a("")
        a(f"- **CM ROAS (primary success metric): {rec.cm_roas_current:.2f}× → "
          f"{rec.cm_roas_projected:.2f}×** — contribution dollars per ad dollar, break-even "
          f"at 1.0× (gross calibrated ROAS {rec.blended_roas_current:.2f}× → "
          f"{rec.blended_roas_projected:.2f}× remains the enforced governance floor).")
        a(f"- Net-contribution improvement vs current allocation: **${opt_net - cur_net:,.0f}** "
          f"(+{(opt_net / cur_net - 1) * 100:.1f}%) at equal-or-lower spend.")
        a(f"- Solver: business_feasible={sv['business_feasible']}, "
          f"solver_converged={sv['solver_converged']}, candidate_stable={sv['candidate_stable']}, "
          f"local_optimality_converged={sv['local_optimality_converged']}, "
          f"solver_qualified={sv['solver_qualified']} "
          f"({sv['n_starts']} starts, {sv['n_feasible_starts']} feasible, {sv['n_near_best']} "
          f"near-best agreeing; worst feasible basin ${sv['worst_contribution']:,.0f}).")
        if sv.get("warning"):
            a(f"- ⚠️ {sv['warning']}\n")
        else:
            a("")
    except Exception as exc:  # pragma: no cover - engine deps optional for the static report
        a(f"_(engine recommendation unavailable: {exc})_\n")

    a("## Sensitivity grid — revenue-weighted portfolio CM\n")
    a("Reverse-logistics assumptions are the weakest; this shows how much CM depends "
      "on them. **Base = recovery 0.80, handling $8, base returns.**\n")
    for label, returns in (("base returns (≈13.5%)", RETURNS_BASE), ("high returns (≈17%)", RETURNS_HIGH)):
        a(f"### {label}\n")
        a("| handling \\ recovery | " + " | ".join(f"ρ={x:.2f}" for x in RECOVERY) + " |")
        a("|---|" + "|".join(["--:"] * len(RECOVERY)) + "|")
        for H in HANDLING:
            cells = " | ".join(f"{_weighted_cm(returns, H, rho, rev)*100:.1f}%" for rho in RECOVERY)
            a(f"| ${H:.0f} | {cells} |")
        a("")
    return "\n".join(L) + "\n"


def main() -> None:
    text = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print(text)
    print(f"written: {OUT}")


if __name__ == "__main__":
    main()
