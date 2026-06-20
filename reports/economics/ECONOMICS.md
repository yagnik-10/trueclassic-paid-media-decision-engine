# Contribution economics (D-040)

Explicit variable-cost stack; margins are **emergent**, not tuned. The specific payment-fee, return-handling and COGS-recovery values are synthetic assumptions, not verified True Classic ledger figures.

## Per-SKU cost waterfall ($/order and % of price)

| SKU | Price | COGS | Outbound | Pay fee | Exp. refund | Net COGS recov. | Return handling | Contribution | CM rate |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| TC-CREW-BLK | 30.00 | 8.50 | 4.00 | 0.90 | 3.60 | +0.82 | 0.96 | 12.86 | 42.9% |
| TC-POLO-CLS | 45.00 | 12.00 | 4.50 | 1.35 | 6.30 | +1.34 | 1.12 | 21.07 | 46.8% |
| TC-JOG-BLK | 65.00 | 19.00 | 5.50 | 1.95 | 11.70 | +2.74 | 1.44 | 28.15 | 43.3% |
| TC-CREW-6PK | 99.00 | 28.00 | 7.00 | 2.97 | 11.88 | +2.69 | 0.96 | 50.88 | 51.4% |

- **Revenue-weighted return rate:** 13.5%
- **Unit-weighted return rate:** 13.3%
- **Revenue-weighted portfolio CM:** 46.2%
- **Spend-weighted CM (optimizer):** 46.4% · break-even ROAS 2.157× · hard scale floor 2.264×

## Per-campaign break-even & marginal hurdle (rises as margin falls — D-040)

| Campaign | SKU | CM rate | break-even ROAS | marginal hurdle (×safety) |
|---|---|--:|--:|--:|
| META_PROSPECTING | TC-CREW-BLK | 42.9% | 2.334× | 2.450× |
| META_ADV_SHOPPING | TC-CREW-6PK | 51.4% | 1.946× | 2.043× |
| META_RETARGETING | TC-POLO-CLS | 46.8% | 2.135× | 2.242× |
| GOOGLE_BRAND | TC-CREW-BLK | 42.9% | 2.334× | 2.450× |
| GOOGLE_NONBRAND | TC-POLO-CLS | 46.8% | 2.135× | 2.242× |
| GOOGLE_PMAX | TC-JOG-BLK | 43.3% | 2.309× | 2.425× |
| GOOGLE_SHOPPING | TC-CREW-6PK | 51.4% | 1.946× | 2.043× |

## Contribution: current vs optimized allocation

Net contribution after ads is the optimizer objective, on calibrated/incremental revenue: **net = Σᵢ mᵢ·Rᵢ − Σᵢ bᵢ**; pre-ad contribution = Σᵢ mᵢ·Rᵢ. Both rows use the SAME post-D-040 margins, so the comparison isolates the allocation, not the cost model.

| Allocation | Pre-ad contribution | Ad spend | Net contribution after ads | CM ROAS |
|---|--:|--:|--:|--:|
| Current | $251,385 | $138,405 | $112,980 | 1.82× |
| Optimized candidate | $268,585 | $138,405 | $130,180 | 1.94× |

- **CM ROAS (primary success metric): 1.82× → 1.94×** — contribution dollars per ad dollar, break-even at 1.0× (gross calibrated ROAS 3.93× → 4.19× remains the enforced governance floor).
- Net-contribution improvement vs current allocation: **$17,201** (+15.2%) at equal-or-lower spend.
- Solver: business_feasible=True, solver_converged=True, candidate_stable=False, local_optimality_converged=True, solver_qualified=True (5 starts, 5 feasible, 5 near-best agreeing; worst feasible basin $130,180).

## Sensitivity grid — revenue-weighted portfolio CM

Reverse-logistics assumptions are the weakest; this shows how much CM depends on them. **Base = recovery 0.80, handling $8, base returns.**

### base returns (≈13.5%)

| handling \ recovery | ρ=0.50 | ρ=0.80 | ρ=1.00 |
|---|--:|--:|--:|
| $4 | 46.3% | 47.4% | 48.1% |
| $8 | 45.1% | 46.2% | 47.0% |
| $12 | 43.9% | 45.0% | 45.8% |

### high returns (≈17%)

| handling \ recovery | ρ=0.50 | ρ=0.80 | ρ=1.00 |
|---|--:|--:|--:|
| $4 | 43.3% | 44.7% | 45.6% |
| $8 | 41.9% | 43.2% | 44.2% |
| $12 | 40.4% | 41.8% | 42.7% |

