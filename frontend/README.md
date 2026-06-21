# True Classic — Paid Media Decision Engine (web UI)

The Vite + React single-page app for the True Classic Paid Media Decision
Engine. It is a thin, **read-and-govern** client over the FastAPI backend:
every number it shows comes from the engine, and every action (recompute,
approve/reject, SKU resolution) calls a real backend endpoint. The UI never
computes allocations itself.

Seven workspaces:

- **Decision Overview** — executive summary, budget allocation, execution preview, and the bounded LLM plan narration.
- **Data Unification** — live ingestion: source health, SKU reconciliation, DQ ledger.
- **Forecast & Response** — BAU forecast bands + local CM-response curves.
- **Budget Planner** — constraint editor (draft → Recompute) + feasibility report.
- **Buyer & Inventory** — inventory handoff: days of cover, stockout risk, reorder qty, inventory no-scale flags.
- **Model Evidence** — champion-selection evidence + interactive forecast-accuracy charts, with a fresh/stale verdict.
- **Audit & Business Controls** — append-only, hash-chained decision ledger.

## Run locally

**Prerequisites:** Node.js 18+, and the FastAPI backend running (see the repo
root `Makefile`: `make api`).

```bash
npm install        # one-time
npm run dev        # dev server → http://localhost:3000
```

The dev server is pinned to **:3000** so its origin matches the backend CORS
allowlist. Point it at a non-default backend with `VITE_API_BASE`:

```bash
VITE_API_BASE=http://localhost:8001 npm run dev
```

## Build

```bash
npm run build      # production bundle → dist/
npm run preview    # serve the build on :3000
npm run lint       # tsc --noEmit
```
