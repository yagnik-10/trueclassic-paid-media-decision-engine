# data/

Generated artifacts. **All synthetic and deterministic** — regenerate with
`make generate` (or `python scripts/generate_synthetic_data.py`). These files are
gitignored; only `.gitkeep` placeholders are tracked.

**Two profiles** share the same latent truth (selected via `TC_DATASET_PROFILE`):
the smooth `golden` benchmark lives here under `raw/` + `canonical/` (the test
anchor); the **`realistic`** profile — the primary data the engine/API/report use
— lives under `realistic/` (same layout). `make generate` writes both. The runtime
decision/audit ledger is a separate durable SQLite store under `audit/`.

## `raw/` — API-envelope-shaped JSON (Stage-2 adapter inputs)
- `meta_insights.json` — Meta Marketing API `data/paging` envelope; numeric
  fields are strings; conversions in `actions` / `action_values`. Carries the
  duplicate-record defect.
- `google_ads.json` — Google Ads nested `results` (`campaign`/`metrics`/`segments`);
  money in `cost_micros`; some rows omit `segments.date` (missing-extraction-date defect).
- `shopify_commerce.json` — DTC source-of-record daily revenue per SKU; some
  `new_customer_revenue` are null (planted null defect).

## `canonical/` — unified, model-ready tables (CSV + Parquet + DuckDB)
The 13 canonical tables (`fact_ad_performance`, `dim_campaign`, `dim_sku`,
`sku_alias`, `fact_commerce_truth`, `fact_inventory_snapshot`,
`data_quality_issue`, `calibration_registry`, `model_run`, `model_evaluation`,
`recommendation`, `approval`, `execution_event`) plus `decision_engine.duckdb`
(SQL-queryable copy) and `manifest.json` (seed, versions, row counts, logical
fingerprints).

Operational tables (`model_run` … `execution_event`) are intentionally **empty
canonical placeholders**: live recommendations, approvals, and stubbed executions
flow through the API and the durable, hash-chained audit ledger (`data/audit/`),
not these CSVs.

## `internal/latent/` — internal latent generator truth (NOT a model input)
`scenario_truth.json` (marginal ROAS, incrementality, noise — the known response
process) is written here **only** with the explicit `--write-latent-truth` flag.
It is gitignored and never appears under `canonical/` or `raw/`, so no adapter,
DuckDB load, or feature-discovery path can pick it up. It exists for debugging
and for tests that verify the system can recover the planted truth.

> Nothing here is measured. Incrementality coefficients are synthetic; execution
> is stubbed. See the repo README for the real-vs-stubbed boundary.
