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
    contribution: float = 0.0            # projected NET contribution after ad spend ($/day)
    cm_roas: float = 0.0                 # projected contribution-margin ROAS (breaks even at 1.0×)
    current_contribution: float = 0.0    # NET contribution at the CURRENT allocation
    current_cm_roas: float = 0.0         # CM ROAS at the CURRENT allocation
    # structured "why this plan": which business constraints bind/slack and which
    # hard bound pins each campaign (positive reporting, not just unmet conflicts).
    binding: dict = field(default_factory=dict)


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
    pre_ad_contribution = contribution + total      # Σ marginᵢ·incremental_revenueᵢ
    return {
        "blended_roas": revenue / total if total else 0.0,
        "platform_blended_roas": platform_revenue / total if total else 0.0,
        "prospecting_share": pros / total if total else 0.0,
        "nc_cpa": (pros / nc) if nc else float("inf"),
        "contribution": contribution,            # NET of ad spend ($/day)
        # CM ROAS — contribution dollars per ad dollar (breaks even at 1.0×). Primary
        # success metric (D-041); gross blended_roas above stays the enforced floor.
        "cm_roas": pre_ad_contribution / total if total else 0.0,
        "revenue": revenue,
        "total": total,
    }


# Multi-start STABILITY CONTRACT (D-040 closure — explicit, auditable thresholds).
# A feasible start is "near-best" if its net contribution is within _NEARBEST_OBJ_TOL
# of the best feasible objective. The chosen plan is `candidate_stable` only when
#   • ≥ _MIN_AGREEING_STARTS near-best feasible starts exist, AND
#   • their allocations agree to ≤ max($1, _STABLE_ALLOC_TOL_FRAC × budget) per campaign.
# Stability is computed among NEAR-BEST FEASIBLE candidates only; the worst basin is
# reported separately (worst_contribution). These gate the optimality/stability FLAGS
# and the approval policy — never feasibility itself.
_NEARBEST_OBJ_TOL = 5e-4       # ≤0.05% of |best net contribution|
_STABLE_ALLOC_TOL_FRAC = 1e-4  # ≤0.01% of budget (or $1, whichever is larger) per campaign
_MIN_AGREEING_STARTS = 2


def _start_points(x0: np.ndarray, bounds, budget: float):
    """Deterministic multi-start set: the current plan plus bound/interior vertices.
    No RNG — reproducibility is preserved. Near-duplicate starts are dropped."""
    los = np.array([lo for lo, _ in bounds])
    his = np.array([hi for _, hi in bounds])
    cur = np.asarray(x0, dtype=float)
    raw = {
        "current": cur,
        "lower": los.copy(),
        "upper": his.copy(),
        "midpoint": (los + his) / 2.0,
        "proportional": (budget * cur / cur.sum()) if cur.sum() else cur.copy(),
    }
    # Local, budget-PRESERVING perturbations of the current plan (shift a fixed slice
    # of spend between adjacent campaigns, staying in-bounds). These probe LOCAL
    # stability: nearby feasible starts should re-converge to the same optimum, which
    # is the evidence that lets a non-solver-certified (status-8) plan be trusted.
    n = len(cur)
    for i in range(min(n - 1, 3)):
        a, b = i, i + 1
        step = min(0.05 * budget, his[a] - cur[a], cur[b] - los[b])
        if step > 1.0:
            p = cur.copy()
            p[a] += step
            p[b] -= step
            raw[f"perturb_{i}"] = p
    out: list[tuple[str, np.ndarray]] = []
    seen: list[np.ndarray] = []
    for name, p in raw.items():
        pc = np.clip(p, los, his)
        if any(np.allclose(pc, s, atol=1e-6) for s in seen):
            continue
        seen.append(pc)
        out.append((name, pc))
    return out, los, his


def optimize(camps: list[OptCampaign], *,
             roas_floor: float = BLENDED_ROAS_FLOOR,
             nc_cpa_target: float = NC_CPA_TARGET,
             prospecting_min_share: float = PROSPECTING_MIN_SHARE,
             movement: float = MOVEMENT_BOUND,
             reserve_allowed: bool = False,
             cm_roas_floor: float = 0.0) -> OptResult:
    # cm_roas_floor is an OPTIONAL portfolio contribution-margin-ROAS floor, OFF by
    # default (0.0) — exposed for the read-only Phase-4 policy sweep only. It does NOT
    # change any live default, config constant, or fingerprint. The enforced production
    # floor remains the gross calibrated blended ROAS (roas_floor).
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
            - roas_floor * float(b.sum())},
        # prospecting share >= min
        {"type": "ineq", "fun": lambda b: float((pros * b).sum()) - prospecting_min_share * float(b.sum())},
        # NC-CPA <= target  ->  target * new_customers - prospecting_spend >= 0
        {"type": "ineq", "fun": lambda b: nc_cpa_target * float((nc_pd * b).sum()) - float((pros * b).sum())},
    ]
    if cm_roas_floor > 0.0:
        # portfolio CM ROAS >= floor  ->  Σ mᵢ·Rᵢ(bᵢ) - cm_floor·Σbᵢ >= 0 (Phase-4 sweep)
        cons.append({"type": "ineq",
                     "fun": lambda b: float(sum(c.revenue_fn(bi) * c.margin
                                                for c, bi in zip(camps, b)))
                     - cm_roas_floor * float(b.sum())})
    if reserve_allowed:
        cons.append({"type": "ineq", "fun": lambda b: budget - float(b.sum())})  # spend <= budget
    else:
        cons.append({"type": "eq", "fun": lambda b: float(b.sum()) - budget})    # deploy full budget

    # --- deterministic multi-start (D-040 closure) --------------------------------
    # SLSQP consistently terminates at status 8 ("positive directional derivative")
    # for this constrained geometry — a benign stop at a vertex-like optimum, not a
    # solver-CERTIFIED first-order optimum. We solve from several deterministic
    # starts, keep every business-feasible candidate, and select the best by net
    # contribution. Feasibility, convergence, stability and optimality are reported
    # as SEPARATE signals (see SolverStatus): a status-8 plan is approvable only with
    # a visible "not solver-certified" warning, never labelled a certified optimum.
    starts, los, his = _start_points(x0, bounds, budget)
    cand = []
    for name, s in starts:
        r = minimize(neg_contribution, s, method="SLSQP", bounds=bounds,
                     constraints=cons, options={"maxiter": 300, "ftol": 1e-6})
        bc = np.clip(r.x, los, his)
        mm = _metrics(camps, bc)
        conf = _business_conflicts(mm, reserve_allowed, budget,
                                   roas_floor, nc_cpa_target, prospecting_min_share,
                                   cm_roas_floor=cm_roas_floor)
        cand.append({"name": name, "b": bc, "res": r, "m": mm,
                     "contribution": mm["contribution"], "feasible": not conf, "conflicts": conf})

    feas = [c for c in cand if c["feasible"]]
    cur_metrics = _metrics(camps, np.clip(x0, los, his))
    current_contribution = cur_metrics["contribution"]
    if feas:
        chosen = max(feas, key=lambda c: c["contribution"])
        conflicts: list[str] = []
    else:
        # No business-feasible candidate: fall back to the current-plan solve and
        # report its unmet constraints (a diagnostic candidate, not a proven plan).
        chosen = next(c for c in cand if c["name"] == "current")
        conflicts = chosen["conflicts"]

    b, m, res = chosen["b"], chosen["m"], chosen["res"]
    best = chosen["contribution"]
    near_best = [c for c in feas if best - c["contribution"] <= abs(best) * _NEARBEST_OBJ_TOL]
    alloc_tol = max(1.0, _STABLE_ALLOC_TOL_FRAC * budget)
    alloc_spread = _alloc_spread([c["b"] for c in near_best])   # USD, per-campaign max range
    candidate_stable = len(near_best) >= _MIN_AGREEING_STARTS and alloc_spread <= alloc_tol
    solver_converged = any(c["res"].success for c in cand)
    # SLSQP status 0 is only a LOCAL convergence certificate. The feasible set is not
    # provably convex (the calibrated blended-ROAS-floor constraint over a concave
    # response is a non-convex region), so we claim LOCAL convergence — never a global
    # or "certified" optimum (would require a separate convexity proof / global method).
    local_optimality_converged = any(
        c["res"].success and best - c["contribution"] <= abs(best) * _NEARBEST_OBJ_TOL
        for c in feas)
    improves_on_current = bool(feas) and best >= current_contribution - 1.0

    basins = feas if feas else cand     # objective spread over the FEASIBLE basins
    contribs = [c["contribution"] for c in basins]
    convergence = {
        "business_feasible": not conflicts,
        "solver_converged": bool(solver_converged),
        "candidate_stable": bool(candidate_stable),
        "local_optimality_converged": bool(local_optimality_converged),
        # ADVISORY precondition only — execution ALWAYS requires human approval (M3).
        # This never triggers automatic execution and is never sufficient on its own.
        "solver_qualified": bool(local_optimality_converged),
        "n_starts": len(cand),
        "n_feasible_starts": len(feas),
        "n_near_best": len(near_best),
        "chosen_start": chosen["name"],
        "best_contribution": round(best, 2),                       # best FEASIBLE objective
        "median_contribution": round(float(np.median(contribs)), 2),   # over feasible basins
        "worst_contribution": round(min(contribs), 2),            # worst FEASIBLE basin
        "near_best_alloc_spread": round(alloc_spread, 2),   # USD
        "near_best_alloc_tol": round(alloc_tol, 2),         # USD threshold actually applied
        "current_allocation_contribution": round(current_contribution, 2),
        "improves_on_current": bool(improves_on_current),
        "warning": _convergence_warning(conflicts, local_optimality_converged, candidate_stable,
                                        int(res.status), len(near_best), len(feas), len(cand)),
    }

    binding = _binding_report(camps, b, bounds, m, reserve_allowed=reserve_allowed,
                              roas_floor=roas_floor, nc_cpa_target=nc_cpa_target,
                              prospecting_min_share=prospecting_min_share, budget=budget,
                              res=res, convergence=convergence, cm_roas_floor=cm_roas_floor)
    spend = {c.campaign_id: round(float(bi), 2) for c, bi in zip(camps, b)}
    return OptResult(
        feasible=not conflicts, spend=spend,
        reserve=round(max(budget - m["total"], 0.0), 2), budget=round(budget, 2),
        conflicts=conflicts, blended_roas=round(m["blended_roas"], 4),
        platform_blended_roas=round(m["platform_blended_roas"], 4),
        prospecting_share=round(m["prospecting_share"], 4),
        nc_cpa=round(m["nc_cpa"], 2), contribution=round(m["contribution"], 2),
        cm_roas=round(m["cm_roas"], 4),
        current_contribution=round(current_contribution, 2),
        current_cm_roas=round(cur_metrics["cm_roas"], 4),
        binding=binding,
    )


def _alloc_spread(bs: list[np.ndarray]) -> float:
    """Max per-campaign DOLLAR spread across a set of allocations (0 if <2)."""
    if len(bs) < 2:
        return 0.0
    arr = np.array(bs)
    return float(np.max(arr.max(axis=0) - arr.min(axis=0)))


def _convergence_warning(conflicts, local_optimality_converged, candidate_stable,
                         status, n_near_best, n_feasible, n_starts) -> str:
    """Human-readable non-convergence note (empty when infeasible or solver-converged).
    Reports the EXACT multi-start structure — never conflates feasibility with agreement."""
    if conflicts or local_optimality_converged:
        return ""
    note = (f"Feasible improving candidate — SLSQP solver convergence not achieved "
            f"(status {status}). Multi-start: {n_starts} starts attempted, {n_feasible} "
            f"feasible, {n_near_best} near-best agreeing within tolerance; chosen = best "
            f"feasible objective")
    if candidate_stable:
        note += " (stability thresholds met)"
    return note + "."


def _business_conflicts(m, reserve_allowed, budget,
                        roas_floor, nc_cpa_target, prospecting_min_share,
                        cm_roas_floor: float = 0.0) -> list[str]:
    """The UNMET business (soft) constraints with their EXACT shortfalls — this is
    the sole definition of (in)feasibility. Hard bounds (movement, daily cap,
    inventory no-scale, marginal-floor no-increase) are enforced directly and cannot
    be violated, so they never appear here. Solver convergence is NOT a feasibility
    condition: it is reported separately as solver_converged / local_optimality_converged
    (D-040), so a benign SLSQP status-8 termination never fabricates an infeasibility."""
    tol = 1e-3
    conflicts = []
    if m["blended_roas"] < roas_floor - tol:
        conflicts.append(
            f"calibrated blended ROAS {m['blended_roas']:.3f}× < floor {roas_floor:.2f}× "
            f"(short {roas_floor - m['blended_roas']:.3f}×)")
    if cm_roas_floor > 0.0 and m["cm_roas"] < cm_roas_floor - tol:
        conflicts.append(
            f"portfolio CM ROAS {m['cm_roas']:.3f}× < CM floor {cm_roas_floor:.2f}× "
            f"(short {cm_roas_floor - m['cm_roas']:.3f}×)")
    if m["prospecting_share"] < prospecting_min_share - tol:
        conflicts.append(
            f"prospecting share {m['prospecting_share']:.4f} < min {prospecting_min_share:.4f} "
            f"(short {prospecting_min_share - m['prospecting_share']:.4f})")
    if m["nc_cpa"] > nc_cpa_target + tol:
        conflicts.append(
            f"NC-CPA ${m['nc_cpa']:.2f} > target ${nc_cpa_target:.2f} "
            f"(over ${m['nc_cpa'] - nc_cpa_target:.2f})")
    if not reserve_allowed and abs(m["total"] - budget) > max(1.0, budget * 1e-3):
        conflicts.append(
            f"could not deploy the full budget within ±movement/inventory bounds "
            f"(${m['total']:.0f} of ${budget:.0f})")
    return conflicts


def _binding_report(camps, b, bounds, m, *, reserve_allowed, roas_floor,
                    nc_cpa_target, prospecting_min_share, budget, res, convergence=None,
                    cm_roas_floor: float = 0.0) -> dict:
    """Positive 'why this plan' report: portfolio business constraints (binding /
    slack / violated, with exact margins), the hard bound that pins each campaign,
    and the solver's terminal status. Hard bounds can't be violated — this surfaces
    which ones are ACTIVE."""
    tol = 1e-3

    def soft_status(margin: float) -> str:
        if margin < -tol:
            return "violated"
        return "binding" if margin <= 5e-3 else "slack"

    # The budget line is mode-aware. Growth: budget is an EQUALITY (deploy it all) →
    # binding when fully deployed. Efficiency-first: budget is a CEILING (spend ≤ it)
    # → reserve is the slack to the ceiling; the ceiling binds only when reserve ≈ 0.
    deployed = m["total"]
    reserve = max(budget - deployed, 0.0)
    near_ceiling = reserve <= max(1.0, budget * tol)
    if reserve_allowed:
        budget_item = {
            "name": "budget_ceiling",
            "status": "binding" if near_ceiling else "slack",
            "detail": f"deployed ${deployed:,.0f} of ${budget:,.0f} ceiling · "
                      f"reserve ${reserve:,.0f} · slack to ceiling ${reserve:,.0f}"}
    else:
        budget_item = {
            "name": "budget_fully_deployed",
            "status": "binding" if near_ceiling else "slack",
            "detail": f"deployed ${deployed:,.0f} of ${budget:,.0f} · reserve ${reserve:,.0f}"}

    portfolio = [
        budget_item,
        {"name": "blended_roas_floor", "status": soft_status(m["blended_roas"] - roas_floor),
         "detail": f"{m['blended_roas']:.3f}× vs floor {roas_floor:.2f}× "
                   f"(margin {m['blended_roas'] - roas_floor:+.3f}×)"},
        {"name": "prospecting_min_share",
         "status": soft_status(m["prospecting_share"] - prospecting_min_share),
         "detail": f"{m['prospecting_share'] * 100:.2f}% vs min {prospecting_min_share * 100:.2f}% "
                   f"(margin {(m['prospecting_share'] - prospecting_min_share) * 100:+.2f}pp)"},
        {"name": "nc_cpa_target", "status": soft_status(nc_cpa_target - m["nc_cpa"]),
         "detail": f"${m['nc_cpa']:.2f} vs target ${nc_cpa_target:.2f} "
                   f"(margin ${nc_cpa_target - m['nc_cpa']:+.2f})"},
    ]
    if cm_roas_floor > 0.0:   # Phase-4 sweep only (off in production)
        portfolio.append(
            {"name": "cm_roas_floor", "status": soft_status(m["cm_roas"] - cm_roas_floor),
             "detail": f"{m['cm_roas']:.3f}× vs CM floor {cm_roas_floor:.2f}× "
                       f"(margin {m['cm_roas'] - cm_roas_floor:+.3f}×)"})

    per_campaign = []
    for c, bi, (lo, hi) in zip(camps, b, bounds):
        at_current = hi <= c.current_spend + max(1.0, c.current_spend * tol)
        limits = []
        if abs(bi - hi) <= max(1.0, abs(hi) * tol):
            if c.inventory_constrained and at_current:
                limits.append("inventory_no_scale")
            elif c.marginal_now < c.marginal_floor and at_current:
                limits.append("below_hurdle_no_increase")
            elif abs(hi - c.daily_cap) <= max(1.0, c.daily_cap * tol):
                limits.append("daily_cap")
            else:
                limits.append("movement_up_cap")
        if (abs(bi - lo) <= max(1.0, abs(lo) * tol)
                and bi < c.current_spend - max(1.0, c.current_spend * tol)):
            limits.append("movement_down_floor")
        if limits:
            per_campaign.append({"campaign_id": c.campaign_id, "limits": limits,
                                 "detail": f"${bi:,.0f} (was ${c.current_spend:,.0f})"})

    solver = {"success": bool(res.success), "status": int(res.status),
              "message": str(res.message).strip(), "iterations": int(res.nit)}
    if convergence:
        solver.update(convergence)   # business_feasible / solver_converged / stability / optimality / multi-start stats
    return {"portfolio": portfolio, "per_campaign": per_campaign, "solver": solver}
