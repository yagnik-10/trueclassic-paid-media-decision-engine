# Phase 4 — portfolio CM-ROAS floor policy sweep (READ-ONLY)

> Decision support only. No live default, `config.py` constant, or fingerprint is changed. The optimizer is called with the optional, default-OFF `cm_roas_floor` and the gross floor disabled (`roas_floor=0`); the enforced production floor remains the gross calibrated blended ROAS. Presets are deliberately **not** named until the numbers are reviewed.

## Headline finding

- **Growth: a portfolio CM floor is redundant.** Spend is fixed (Σbᵢ=B), so **maximizing net contribution already maximizes portfolio CM ROAS** — the objective does it. The achievable CM ROAS is pinned at **1.942×**; every floor ≤ that is a no-op (identical plan) and every floor above it is infeasible (the floor can only reject, never reshape).
- **Efficiency-first: a CM floor IS an actionable knob — but a costly, narrow one.** By withholding budget, floors are feasible up to a bisection ceiling of **1.971×**; above that, even maximal withholding fails the CM constraint only (no other constraint binds). Reaching the ceiling sacrifices **$-8,996/day** of net contribution and parks **$13,480** in reserve — each +0.01× of CM costs real contribution (see frontier).
- The legacy gross 4.0× floor is **slack** at today's optimum, so removing it changes the realistic plan by $0.
- **Robustness caveat:** a hard floor set near the point estimate (≤~1.94×) is violated by the realized latent response in ~100% of stress seeds — it gives false confidence, not protection. A *downside-adjusted* guardrail could be defensible later, but is not needed now.
- Implication: the **per-dollar marginal CM hurdle (1.05×)** + the existing efficiency-first reserve already provide the governing mechanism; exposing arbitrary portfolio CM-floor presets would add fragile, expensive, mostly-no-op behavior.

## Central sweep — growth mode

Reference (live gross-4.0× policy): CM **1.941×**, net **$130,180/day**, gross floor **slack**. Achievable CM ceiling (bisection) **1.94×**; highest floor preserving the reference plan **1.94×**; lowest floor that changes allocation **none**.
At the ceiling (1.94×): net **$130,180/day** (**$0** vs ref), reserve **$0** — the price of forcing maximal portfolio CM.

| CM floor | feasible | CM ROAS | net $/day | Δnet vs ref | spend | reserve | prosp. share | floor status | max allocΔ |
|---|:--:|--:|--:|--:|--:|--:|--:|:--:|--:|
| none | yes | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | off | $0 |
| 1.00× | yes | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | slack | $1 |
| 1.20× | yes | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | slack | $1 |
| 1.40× | yes | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | slack | $1 |
| 1.50× | yes | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | slack | $1 |
| 1.70× | yes | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | slack | $1 |
| 1.80× | yes | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | slack | $1 |
| 1.85× | yes | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | slack | $1 |
| 1.90× | yes | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | slack | $0 |
| 1.94× | yes | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | binding | $0 |
| 1.95× | no | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | violated | $2 |
| 1.96× | no | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | violated | $3 |
| 1.97× | no | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | violated | $0 |
| 1.98× | no | 1.941× | $130,180 | $-0 | $138,405 | $0 | 30.0% | violated | $4 |
| 2.00× | no | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | violated | $1 |

## Central sweep — efficiency_first mode

Reference (live gross-4.0× policy): CM **1.941×**, net **$130,180/day**, gross floor **slack**. Achievable CM ceiling (bisection) **1.97×**; highest floor preserving the reference plan **1.94×**; lowest floor that changes allocation **1.95×**.
At the ceiling (1.97×): net **$121,185/day** (**$-8,996** vs ref), reserve **$13,480** — the price of forcing maximal portfolio CM.

| CM floor | feasible | CM ROAS | net $/day | Δnet vs ref | spend | reserve | prosp. share | floor status | max allocΔ |
|---|:--:|--:|--:|--:|--:|--:|--:|:--:|--:|
| none | yes | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | off | $2 |
| 1.00× | yes | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | slack | $1 |
| 1.20× | yes | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | slack | $1 |
| 1.40× | yes | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | slack | $1 |
| 1.50× | yes | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | slack | $1 |
| 1.70× | yes | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | slack | $1 |
| 1.80× | yes | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | slack | $1 |
| 1.85× | yes | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | slack | $1 |
| 1.90× | yes | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | slack | $1 |
| 1.94× | yes | 1.941× | $130,180 | $0 | $138,405 | $0 | 30.0% | binding | $1 |
| 1.95× | yes | 1.950× | $128,395 | $-1,785 | $135,153 | $3,252 | 30.0% | binding | $1,686 |
| 1.96× | yes | 1.960× | $125,367 | $-4,813 | $130,591 | $7,815 | 30.0% | binding | $4,526 |
| 1.97× | yes | 1.970× | $121,899 | $-8,281 | $125,670 | $12,736 | 30.0% | binding | $4,526 |
| 1.98× | no | 1.955× | $127,172 | $-3,008 | $133,149 | $5,256 | 30.0% | violated | $3,084 |
| 2.00× | no | 1.955× | $127,173 | $-3,007 | $133,153 | $5,252 | 30.0% | violated | $3,084 |

## Marginal CM hurdle (separate object — do not conflate)

The per-campaign **marginal** CM hurdle is a uniform **1.05×** in CM-ROAS units: each campaign's gross hurdle is `(1/mᵢ)×1.05`, so the marginal *contribution* return at that hurdle is `mᵢ × (1/mᵢ) × 1.05 = 1.05×` for every campaign. That is the live scale/hold/cut rule and stays independent of any portfolio floor.

## Model-error robustness (deterministic stress seeds)

The engine commits a plan from its ESTIMATE; each seed realizes a different latent response (per-campaign lognormal slope multiplier, σ = campaign noise_cv, derived from MASTER_SEED). Development seeds (n=16) below; acceptance seeds (n=8) are held out for the final check.

| mode | CM floor | est. feasible | realized CM p10/med/p90 | true-floor violations | oracle feas. | net regret med / p90 | dir. match |
|---|---|:--:|---|--:|--:|--:|--:|
| growth | none | yes | 1.880 / 1.895 / 1.912 | 0% | 100% | $1,287 / $2,039 | 73% |
| growth | 1.90× | yes | 1.880 / 1.895 / 1.912 | 62% | 88% | $1,583 / $2,040 | 71% |
| growth | 1.94× | yes | 1.880 / 1.895 / 1.912 | 100% | 0% | $1,187 / $1,842 | 75% |
| growth | 1.96× | no | 1.880 / 1.895 / 1.912 | 0% | 0% | $1,187 / $1,841 | 75% |
| efficiency_first | none | yes | 1.880 / 1.895 / 1.912 | 0% | 100% | $1,611 / $2,041 | 70% |
| efficiency_first | 1.90× | yes | 1.880 / 1.895 / 1.912 | 62% | 100% | $1,611 / $2,042 | 70% |
| efficiency_first | 1.94× | yes | 1.880 / 1.895 / 1.912 | 100% | 100% | $732 / $1,568 | 55% |
| efficiency_first | 1.96× | yes | 1.927 / 1.939 / 1.953 | 100% | 100% | $667 / $2,028 | 88% |

### Acceptance seeds (held out, n=8) — efficiency-first

| CM floor | realized CM p10/med/p90 | true-floor violations | net regret med / p90 |
|---|---|--:|--:|
| 1.90× | 1.890 / 1.899 / 1.920 | 50% | $1,164 / $1,408 |
| 1.94× | 1.890 / 1.899 / 1.920 | 100% | $816 / $1,200 |

## Recommendation for Phase 4

- Do **not** ship portfolio CM-ROAS *floor* presets: in Growth a floor is redundant with the objective; in Efficiency-first it works only by withholding budget at a steep, monotone contribution cost, and a floor near the point estimate is violated by the realized latent response in ~all stress seeds (false confidence).
- Make CM ROAS / net contribution the **objective + headline** (done, D-041); keep the **1.05× marginal CM hurdle** as the governing rule; if a guard rail is wanted, prefer an **efficiency-first reserve** trigger over a portfolio-ratio floor.
- Treat the gross 4.0× floor as a legacy governance constraint that is currently slack; removing it does not change the realistic plan.

