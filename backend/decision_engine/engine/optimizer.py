"""SLSQP allocator — risk-adjusted net contribution subject to business constraints.

Objective: maximize Σ [ R_i(b_i)·m_i − b_i ]  (m_i = pre-ad contribution margin),
where R_i is the local residualized response (calibrated/incremental revenue).

Constraints: total budget (with an optional reserve line); blended calibrated
ROAS ≥ floor; prospecting share ≥ min; NC-CPA ≤ target; per-campaign movement
≤ ±20%; inventory-risk campaigns cannot scale up. A pre-solve feasibility check
runs first; mutually-infeasible constraints yield an explicit conflict report,
never an invalid plan. Deterministic (SLSQP from a fixed start).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from scipy.optimize import minimize

from backend.decision_engine.config import (
    BLENDED_ROAS_FLOOR,
    MOVEMENT_BOUND,
    NC_CPA_TARGET,
    PROSPECTING_MIN_SHARE,
)


@dataclass
class OptCampaign:
    campaign_id: str
    current_spend: float
    daily_cap: float
    margin: float                       # pre-ad contribution-margin rate
    is_prospecting: bool
    inventory_constrained: bool
    nc_per_dollar: float                # estimated new customers per $ (observable)
    incrementality: float               # calibrated/platform-reported (in (0,1])
    marginal_now: float                 # marginal ROAS at current spend (no-increase gate)
    marginal_floor: float               # THIS campaign's hurdle (1/its_margin × safety)
    revenue_fn: Callable[[float], float]   # local calibrated (incremental) R_i(b)
    marginal_fn: Callable[[float], float]  # local dR/db


@dataclass
class OptResult:
    feasible: bool
    spend: dict[str, float]
    reserve: float
    budget: float
    conflicts: list[str] = field(default_factory=list)
    blended_roas: float = 0.0            # calibrated (incremental) — the decision lens
    platform_blended_roas: float = 0.0   # platform-reported — the enforced headline KPI
    prospecting_share: float = 0.0
    nc_cpa: float = 0.0
    contribution: float = 0.0


def _bounds(camps: list[OptCampaign], movement: float) -> list[tuple[float, float]]:
    out = []
    for c in camps:
        # movement bound = the in-support cap; the lower bound also protects the
        # minimum learning budget (a campaign keeps ≥(1-movement) of its spend).
        lo = c.current_spend * (1.0 - movement)
        hi = min(c.current_spend * (1.0 + movement), c.daily_cap)
        if c.inventory_constrained:
            hi = min(hi, c.current_spend)   # no scale-up on stockout-risk SKUs
        if c.marginal_now < c.marginal_floor:
            hi = min(hi, c.current_spend)   # below THIS campaign's hurdle → no increase
        out.append((lo, max(lo, hi)))
    return out


def _platform_revenue(camps, b) -> float:
    return float(sum(c.revenue_fn(bi) / c.incrementality for c, bi in zip(camps, b)))


def _metrics(camps: list[OptCampaign], b: np.ndarray) -> dict[str, float]:
    total = float(b.sum())
    revenue = float(sum(c.revenue_fn(bi) for c, bi in zip(camps, b)))
    platform_revenue = _platform_revenue(camps, b)
    pros = float(sum(bi for c, bi in zip(camps, b) if c.is_prospecting))
    nc = float(sum(c.nc_per_dollar * bi for c, bi in zip(camps, b)))
    contribution = float(sum(c.revenue_fn(bi) * c.margin - bi for c, bi in zip(camps, b)))
    return {
        "blended_roas": revenue / total if total else 0.0,
        "platform_blended_roas": platform_revenue / total if total else 0.0,
        "prospecting_share": pros / total if total else 0.0,
        "nc_cpa": (pros / nc) if nc else float("inf"),
        "contribution": contribution,
        "revenue": revenue,
        "total": total,
    }


def optimize(camps: list[OptCampaign], *, movement: float = MOVEMENT_BOUND,
             reserve_allowed: bool = False) -> OptResult:
    budget = float(sum(c.current_spend for c in camps))
    bounds = _bounds(camps, movement)
    x0 = np.array([c.current_spend for c in camps], dtype=float)

    def neg_contribution(b):
        return -float(sum(c.revenue_fn(bi) * c.margin - bi for c, bi in zip(camps, b)))

    pros = np.array([1.0 if c.is_prospecting else 0.0 for c in camps])
    nc_pd = np.array([c.nc_per_dollar for c in camps])

    cons = [
        # CALIBRATED (incremental) blended ROAS >= floor — the decision basis (D-008)
        {"type": "ineq", "fun": lambda b: float(sum(c.revenue_fn(bi) for c, bi in zip(camps, b)))
            - BLENDED_ROAS_FLOOR * float(b.sum())},
        # prospecting share >= min
        {"type": "ineq", "fun": lambda b: float((pros * b).sum()) - PROSPECTING_MIN_SHARE * float(b.sum())},
        # NC-CPA <= target  ->  target * new_customers - prospecting_spend >= 0
        {"type": "ineq", "fun": lambda b: NC_CPA_TARGET * float((nc_pd * b).sum()) - float((pros * b).sum())},
    ]
    if reserve_allowed:
        cons.append({"type": "ineq", "fun": lambda b: budget - float(b.sum())})  # spend <= budget
    else:
        cons.append({"type": "eq", "fun": lambda b: float(b.sum()) - budget})    # deploy full budget

    res = minimize(neg_contribution, x0, method="SLSQP", bounds=bounds,
                   constraints=cons, options={"maxiter": 300, "ftol": 1e-6})

    b = np.clip(res.x, [lo for lo, _ in bounds], [hi for _, hi in bounds])
    m = _metrics(camps, b)
    conflicts = _check_feasibility(camps, b, m, reserve_allowed, budget, res.success)
    spend = {c.campaign_id: round(float(bi), 2) for c, bi in zip(camps, b)}
    return OptResult(
        feasible=not conflicts, spend=spend,
        reserve=round(max(budget - m["total"], 0.0), 2), budget=round(budget, 2),
        conflicts=conflicts, blended_roas=round(m["blended_roas"], 4),
        platform_blended_roas=round(m["platform_blended_roas"], 4),
        prospecting_share=round(m["prospecting_share"], 4),
        nc_cpa=round(m["nc_cpa"], 2), contribution=round(m["contribution"], 2),
    )


def _check_feasibility(camps, b, m, reserve_allowed, budget, solver_success) -> list[str]:
    tol = 1e-3
    conflicts = []
    if not solver_success:
        conflicts.append("SLSQP did not converge to a feasible optimum")
    if m["blended_roas"] < BLENDED_ROAS_FLOOR - tol:
        conflicts.append(
            f"calibrated blended ROAS {m['blended_roas']:.2f} < floor {BLENDED_ROAS_FLOOR}")
    if m["prospecting_share"] < PROSPECTING_MIN_SHARE - tol:
        conflicts.append(f"prospecting share {m['prospecting_share']:.2f} < min {PROSPECTING_MIN_SHARE}")
    if m["nc_cpa"] > NC_CPA_TARGET + tol:
        conflicts.append(f"NC-CPA {m['nc_cpa']:.2f} > target {NC_CPA_TARGET}")
    if not reserve_allowed and abs(m["total"] - budget) > max(1.0, budget * 1e-3):
        conflicts.append("could not deploy the full budget within movement/inventory bounds")
    return conflicts
