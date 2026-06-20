#!/usr/bin/env python
"""Read-only Phase-4 policy sweep — what does a PORTFOLIO contribution-margin-ROAS
floor actually do to the realistic portfolio?

    make cm-sweep      # writes reports/economics/CM_FLOOR_SWEEP.{md,json}

This artifact is DECISION SUPPORT only. It changes no live default, no `config.py`
constant, and no fingerprint: it merely calls the optimizer with the optional,
default-OFF `cm_roas_floor` (with the gross floor disabled, `roas_floor=0`) across a
grid of candidate CM floors and both budget modes, then stress-tests a focused set of
floors under deterministic model-error realizations. The enforced production floor
remains the gross calibrated blended ROAS. Per the review: run the numbers BEFORE
naming Growth/Balanced/Conservative presets.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from backend.decision_engine import config as C
from backend.decision_engine.engine.optimizer import OptCampaign, optimize
from backend.decision_engine.engine.recommend import _context
from backend.decision_engine.engine.response import CampaignResponse
from backend.decision_engine.synth.scenario import CAMPAIGN_BY_ID, hill_marginal_roas

OUT_DIR = Path("reports/economics")
# Dense grid around the ~1.94× operating point — that is where a floor can begin to
# bind. `None` = no portfolio CM floor (pure contribution-max baseline).
GRID: list[float | None] = [None, 1.00, 1.20, 1.40, 1.50, 1.70, 1.80, 1.85, 1.90,
                            1.94, 1.95, 1.96, 1.97, 1.98, 2.00]
MODES = ("growth", "efficiency_first")
# Focused floors for the (slower) model-error robustness pass.
ROBUST_FLOORS: list[float | None] = [None, 1.90, 1.94, 1.96]
TOL = 1e-3
_SWEEP_KEY = 4041          # fixed namespace for deterministic stress seeds (D-041/Phase 4)


# --- production-faithful campaign construction -------------------------------
def _build_camps(ctx, *, source: str = "slope", mult: dict | None = None) -> list[OptCampaign]:
    """OptCampaign list matching the engine's own construction. ``source='latent'``
    uses generator truth (Hill marginal at current spend); ``mult`` applies a
    per-campaign slope multiplier (a model-error realization)."""
    camps: list[OptCampaign] = []
    for cid in sorted(ctx.responses):
        r = ctx.responses[cid]
        sku = ctx.sku_of[cid]
        margin = float(ctx.dim_sku.loc[sku, "contribution_margin_rate"])
        slope = (hill_marginal_roas(float(r.current_spend), CAMPAIGN_BY_ID[cid])
                 if source == "latent" else r.slope)
        if mult is not None:
            slope = slope * mult[cid]
        resp = CampaignResponse(cid, r.segment, r.current_spend, r.current_revenue,
                                slope, r.marginal_roas_downside, slope, r.quad)
        camps.append(OptCampaign(
            campaign_id=cid, current_spend=r.current_spend,
            daily_cap=float(ctx.dim_c.loc[cid, "daily_cap"]), margin=margin,
            is_prospecting=bool(ctx.dim_c.loc[cid, "is_prospecting"]),
            inventory_constrained=sku in ctx.stockout_skus, nc_per_dollar=ctx.nc_pd[cid],
            incrementality=float(ctx.calibration[r.segment]), marginal_now=slope,
            marginal_floor=(1.0 / margin) * C.HARD_FLOOR_SAFETY,
            revenue_fn=resp.incremental_revenue, marginal_fn=resp.marginal_at))
    return camps


def _solve(camps, floor: float | None, mode: str):
    """Solve with the GROSS floor disabled and only the candidate CM floor active."""
    return optimize(camps, roas_floor=0.0, cm_roas_floor=(0.0 if floor is None else floor),
                    reserve_allowed=(mode == "efficiency_first"))


def _max_feasible_floor(camps, mode: str, lo: float = 1.0, hi: float = 2.5) -> float | None:
    """Deterministic bisection for the highest CM floor that is still feasible — the true
    achievable-CM ceiling (the coarse grid can straddle it). Returns None if even ``lo``
    is infeasible."""
    if not _solve(camps, lo, mode).feasible:
        return None
    if _solve(camps, hi, mode).feasible:
        return hi
    for _ in range(40):
        mid = (lo + hi) / 2.0
        if _solve(camps, mid, mode).feasible:
            lo = mid
        else:
            hi = mid
    return lo


def _vec(camps, spend: dict) -> np.ndarray:
    return np.array([spend[c.campaign_id] for c in camps], dtype=float)


def _net(camps, b: np.ndarray) -> float:
    return float(sum(c.revenue_fn(bi) * c.margin - bi for c, bi in zip(camps, b)))


def _cm(camps, b: np.ndarray) -> float:
    tot = float(b.sum())
    return ((_net(camps, b) + tot) / tot) if tot else 0.0


def _pros_share(camps, b: np.ndarray) -> float:
    tot = float(b.sum())
    pr = float(sum(bi for c, bi in zip(camps, b) if c.is_prospecting))
    return pr / tot if tot else 0.0


def _cm_status(res, floor: float | None) -> str:
    if floor is None:
        return "off"
    port = {p["name"]: p for p in res.binding["portfolio"]}
    return port.get("cm_roas_floor", {}).get("status", "off")


# --- central deterministic sweep --------------------------------------------
def _central(ctx) -> dict:
    est = _build_camps(ctx)
    out: dict = {}
    for mode in MODES:
        # reference = the LIVE policy (gross 4.0× floor, no CM floor)
        ref = optimize(est, reserve_allowed=(mode == "efficiency_first"))
        ref_vec = _vec(est, ref.spend)
        gross_status = {p["name"]: p for p in ref.binding["portfolio"]}["blended_roas_floor"]["status"]
        rows = []
        for f in GRID:
            res = _solve(est, f, mode)
            b = _vec(est, res.spend)
            rows.append({
                "floor": f,
                "feasible": bool(res.feasible),
                "cm_roas": round(res.cm_roas, 4),
                "net_contribution": round(res.contribution, 0),
                "delta_net_vs_ref": round(res.contribution - ref.contribution, 0),
                "spend": round(float(b.sum()), 0),
                "reserve": round(res.reserve, 0),
                "prospecting_share": round(_pros_share(est, b), 4),
                "cm_floor_status": _cm_status(res, f),
                "max_alloc_delta_vs_ref": round(float(np.max(np.abs(b - ref_vec))), 0),
            })
        changed = [r for r in rows if r["feasible"] and r["max_alloc_delta_vs_ref"] > 1.0
                   and r["floor"] is not None]
        preserved = [r for r in rows if r["feasible"] and r["max_alloc_delta_vs_ref"] <= 1.0
                     and r["floor"] is not None]
        # true achievable-CM ceiling via bisection (the coarse grid can straddle it)
        ceiling = _max_feasible_floor(est, mode)
        ceil_row = None
        if ceiling is not None:
            cres = _solve(est, ceiling, mode)
            ceil_row = {"floor": round(ceiling, 4), "cm_roas": round(cres.cm_roas, 4),
                        "net_contribution": round(cres.contribution, 0),
                        "delta_net_vs_ref": round(cres.contribution - ref.contribution, 0),
                        "reserve": round(cres.reserve, 0)}
        out[mode] = {
            "reference_cm_roas": round(ref.cm_roas, 4),
            "reference_net_contribution": round(ref.contribution, 0),
            "gross_floor_status_at_reference": gross_status,
            "achievable_cm_ceiling": round(ceiling, 4) if ceiling is not None else None,
            "ceiling_detail": ceil_row,   # net contribution / reserve cost at the ceiling
            "lowest_floor_changing_allocation": (min(r["floor"] for r in changed) if changed else None),
            "highest_floor_preserving_reference": (max(r["floor"] for r in preserved) if preserved else None),
            "rows": rows,
        }
    return out


# --- deterministic model-error robustness -----------------------------------
def _seed_mults(ctx, split_id: int, n: int) -> list[dict]:
    """``n`` deterministic per-campaign slope multipliers (lognormal, mean≈1, σ = the
    campaign's noise_cv). Derived from MASTER_SEED so the report is reproducible; never
    touches the global RNG. dev split_id=0, acceptance split_id=1 (disjoint streams)."""
    cids = sorted(ctx.responses)
    sigmas = {cid: float(CAMPAIGN_BY_ID[cid].noise_cv) for cid in cids}
    out = []
    for i in range(n):
        rng = np.random.default_rng(np.random.SeedSequence(C.MASTER_SEED,
                                                            spawn_key=(_SWEEP_KEY, split_id, i)))
        out.append({cid: float(np.exp(rng.normal(-0.5 * sigmas[cid] ** 2, sigmas[cid])))
                    for cid in cids})
    return out


def _robust(ctx, *, n_dev: int, n_acc: int) -> dict:
    est = _build_camps(ctx)
    dev = _seed_mults(ctx, 0, n_dev)
    acc = _seed_mults(ctx, 1, n_acc)

    def assess(floor, mode, seeds):
        plan = _solve(est, floor, mode)            # the engine commits from its ESTIMATE
        b_est = _vec(est, plan.spend)
        est_feasible = bool(plan.feasible)
        realized_cm, regret, dir_match, oracle_feas = [], [], [], []
        for m in seeds:
            truth = _build_camps(ctx, source="latent", mult=m)
            rcm = _cm(truth, b_est)
            realized_cm.append(rcm)
            oracle = _solve(truth, floor, mode)
            b_or = _vec(truth, oracle.spend)
            oracle_feas.append(bool(oracle.feasible))
            regret.append(_net(truth, b_or) - _net(truth, b_est))
            cur = np.array([c.current_spend for c in truth])
            dir_match.append(float(np.mean(
                np.sign(np.round(b_est - cur)) == np.sign(np.round(b_or - cur)))))
        rc = np.array(realized_cm)
        viol = ([rc_i < floor - TOL for rc_i in rc] if (floor is not None and est_feasible)
                else [False] * len(rc))
        return {
            "floor": floor, "mode": mode, "est_feasible": est_feasible,
            "realized_cm_p10": round(float(np.percentile(rc, 10)), 4),
            "realized_cm_median": round(float(np.median(rc)), 4),
            "realized_cm_p90": round(float(np.percentile(rc, 90)), 4),
            "true_floor_violation_rate": round(float(np.mean(viol)), 3),
            "oracle_feasibility_rate": round(float(np.mean(oracle_feas)), 3),
            "net_regret_median": round(float(np.median(regret)), 0),
            "net_regret_p90": round(float(np.percentile(regret, 90)), 0),
            "direction_match_mean": round(float(np.mean(dir_match)), 3),
        }

    dev_rows = [assess(f, mode, dev) for mode in MODES for f in ROBUST_FLOORS]
    # acceptance check on the held-out seeds for the tightest still-interesting floor
    acc_rows = [assess(f, "efficiency_first", acc) for f in (1.90, 1.94)]
    return {"n_dev": n_dev, "n_acc": n_acc, "dev": dev_rows, "acceptance": acc_rows}


# --- rendering ---------------------------------------------------------------
def _fmt_floor(f) -> str:
    return "none" if f is None else f"{f:.2f}×"


def build(*, n_dev: int, n_acc: int) -> tuple[str, dict]:
    ctx = _context()
    central = _central(ctx)
    robust = _robust(ctx, n_dev=n_dev, n_acc=n_acc)
    md: list[str] = []
    a = md.append

    a("# Phase 4 — portfolio CM-ROAS floor policy sweep (READ-ONLY)\n")
    a("> Decision support only. No live default, `config.py` constant, or fingerprint is "
      "changed. The optimizer is called with the optional, default-OFF `cm_roas_floor` "
      "and the gross floor disabled (`roas_floor=0`); the enforced production floor "
      "remains the gross calibrated blended ROAS. Presets are deliberately **not** named "
      "until the numbers are reviewed.\n")

    a("## Headline finding\n")
    g, e = central["growth"], central["efficiency_first"]
    ed = e["ceiling_detail"] or {}
    a(f"- **Growth: a portfolio CM floor is redundant.** Spend is fixed (Σbᵢ=B), so "
      f"**maximizing net contribution already maximizes portfolio CM ROAS** — the "
      f"objective does it. The achievable CM ROAS is pinned at **{g['achievable_cm_ceiling']:.3f}×**; "
      f"every floor ≤ that is a no-op (identical plan) and every floor above it is "
      f"infeasible (the floor can only reject, never reshape).")
    a(f"- **Efficiency-first: a CM floor IS an actionable knob — but a costly, narrow one.** "
      f"By withholding budget, floors are feasible up to a bisection ceiling of "
      f"**{e['achievable_cm_ceiling']:.3f}×**; above that, even maximal withholding fails "
      f"the CM constraint only (no other constraint binds). Reaching the ceiling sacrifices "
      f"**${ed.get('delta_net_vs_ref', 0):,.0f}/day** of net contribution and parks "
      f"**${ed.get('reserve', 0):,.0f}** in reserve — each +0.01× of CM costs real "
      f"contribution (see frontier).")
    a(f"- The legacy gross 4.0× floor is **{g['gross_floor_status_at_reference']}** at "
      f"today's optimum, so removing it changes the realistic plan by $0.")
    a("- **Robustness caveat:** a hard floor set near the point estimate (≤~1.94×) is "
      "violated by the realized latent response in ~100% of stress seeds — it gives "
      "false confidence, not protection. A *downside-adjusted* guardrail could be "
      "defensible later, but is not needed now.")
    a("- Implication: the **per-dollar marginal CM hurdle (1.05×)** + the existing "
      "efficiency-first reserve already provide the governing mechanism; exposing "
      "arbitrary portfolio CM-floor presets would add fragile, expensive, mostly-no-op "
      "behavior.\n")

    for mode in MODES:
        d = central[mode]
        a(f"## Central sweep — {mode} mode\n")
        a(f"Reference (live gross-4.0× policy): CM **{d['reference_cm_roas']:.3f}×**, net "
          f"**${d['reference_net_contribution']:,.0f}/day**, gross floor "
          f"**{d['gross_floor_status_at_reference']}**. Achievable CM ceiling (bisection) "
          f"**{_fmt_floor(d['achievable_cm_ceiling'])}**; highest floor preserving the "
          f"reference plan **{_fmt_floor(d['highest_floor_preserving_reference'])}**; "
          f"lowest floor that changes allocation "
          f"**{_fmt_floor(d['lowest_floor_changing_allocation'])}**.")
        cd = d["ceiling_detail"]
        if cd and d["highest_floor_preserving_reference"] != d["achievable_cm_ceiling"]:
            a(f"At the ceiling ({_fmt_floor(cd['floor'])}): net **${cd['net_contribution']:,.0f}/day** "
              f"(**${cd['delta_net_vs_ref']:,.0f}** vs ref), reserve **${cd['reserve']:,.0f}** — "
              f"the price of forcing maximal portfolio CM.")
        a("")
        a("| CM floor | feasible | CM ROAS | net $/day | Δnet vs ref | spend | reserve | prosp. share | floor status | max allocΔ |")
        a("|---|:--:|--:|--:|--:|--:|--:|--:|:--:|--:|")
        for r in d["rows"]:
            a(f"| {_fmt_floor(r['floor'])} | {'yes' if r['feasible'] else 'no'} | "
              f"{r['cm_roas']:.3f}× | ${r['net_contribution']:,.0f} | "
              f"${r['delta_net_vs_ref']:,.0f} | ${r['spend']:,.0f} | ${r['reserve']:,.0f} | "
              f"{r['prospecting_share']*100:.1f}% | {r['cm_floor_status']} | "
              f"${r['max_alloc_delta_vs_ref']:,.0f} |")
        a("")

    a("## Marginal CM hurdle (separate object — do not conflate)\n")
    a("The per-campaign **marginal** CM hurdle is a uniform **1.05×** in CM-ROAS units: "
      "each campaign's gross hurdle is `(1/mᵢ)×1.05`, so the marginal *contribution* "
      "return at that hurdle is `mᵢ × (1/mᵢ) × 1.05 = 1.05×` for every campaign. That "
      "is the live scale/hold/cut rule and stays independent of any portfolio floor.\n")

    a("## Model-error robustness (deterministic stress seeds)\n")
    a(f"The engine commits a plan from its ESTIMATE; each seed realizes a different "
      f"latent response (per-campaign lognormal slope multiplier, σ = campaign noise_cv, "
      f"derived from MASTER_SEED). Development seeds (n={robust['n_dev']}) below; "
      f"acceptance seeds (n={robust['n_acc']}) are held out for the final check.\n")
    a("| mode | CM floor | est. feasible | realized CM p10/med/p90 | true-floor violations | oracle feas. | net regret med / p90 | dir. match |")
    a("|---|---|:--:|---|--:|--:|--:|--:|")
    for r in robust["dev"]:
        a(f"| {r['mode']} | {_fmt_floor(r['floor'])} | {'yes' if r['est_feasible'] else 'no'} | "
          f"{r['realized_cm_p10']:.3f} / {r['realized_cm_median']:.3f} / {r['realized_cm_p90']:.3f} | "
          f"{r['true_floor_violation_rate']*100:.0f}% | {r['oracle_feasibility_rate']*100:.0f}% | "
          f"${r['net_regret_median']:,.0f} / ${r['net_regret_p90']:,.0f} | "
          f"{r['direction_match_mean']*100:.0f}% |")
    a("")
    a(f"### Acceptance seeds (held out, n={robust['n_acc']}) — efficiency-first\n")
    a("| CM floor | realized CM p10/med/p90 | true-floor violations | net regret med / p90 |")
    a("|---|---|--:|--:|")
    for r in robust["acceptance"]:
        a(f"| {_fmt_floor(r['floor'])} | "
          f"{r['realized_cm_p10']:.3f} / {r['realized_cm_median']:.3f} / {r['realized_cm_p90']:.3f} | "
          f"{r['true_floor_violation_rate']*100:.0f}% | "
          f"${r['net_regret_median']:,.0f} / ${r['net_regret_p90']:,.0f} |")
    a("")
    a("## Recommendation for Phase 4\n")
    a("- Do **not** ship portfolio CM-ROAS *floor* presets: in Growth a floor is redundant "
      "with the objective; in Efficiency-first it works only by withholding budget at a "
      "steep, monotone contribution cost, and a floor near the point estimate is violated "
      "by the realized latent response in ~all stress seeds (false confidence).")
    a("- Make CM ROAS / net contribution the **objective + headline** (done, D-041); keep "
      "the **1.05× marginal CM hurdle** as the governing rule; if a guard rail is wanted, "
      "prefer an **efficiency-first reserve** trigger over a portfolio-ratio floor.")
    a("- Treat the gross 4.0× floor as a legacy governance constraint that is currently "
      "slack; removing it does not change the realistic plan.\n")

    payload = {"grid": [(_fmt_floor(f)) for f in GRID], "central": central,
               "robustness": robust,
               "provenance": {"profile": C.DATASET_PROFILE, "master_seed": C.MASTER_SEED,
                              "gross_floor": C.BLENDED_ROAS_FLOOR, "sweep_key": _SWEEP_KEY}}
    return "\n".join(md) + "\n", payload


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase-4 CM-ROAS floor policy sweep (read-only)")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    ap.add_argument("--dev-seeds", type=int, default=16)
    ap.add_argument("--acc-seeds", type=int, default=8)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    md, payload = build(n_dev=args.dev_seeds, n_acc=args.acc_seeds)
    (args.out / "CM_FLOOR_SWEEP.md").write_text(md)
    (args.out / "CM_FLOOR_SWEEP.json").write_text(json.dumps(payload, indent=2))
    print(f"CM-floor sweep → {args.out}/CM_FLOOR_SWEEP.md (+ .json)")
    g = payload["central"]["growth"]
    e = payload["central"]["efficiency_first"]
    print(f"  growth ceiling {g['achievable_cm_ceiling']}× (redundant) · "
          f"efficiency-first ceiling {e['achievable_cm_ceiling']}× · "
          f"gross floor {g['gross_floor_status_at_reference']}")


if __name__ == "__main__":
    main()
