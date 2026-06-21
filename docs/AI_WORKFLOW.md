# AI workflow

The brief evaluates *how* the prototype was built with AI as a primary tool —
"which tools, which prompts, where you intervened, what you rejected." This file
captures that signal. The AI-workflow story lives in **how the system was built**,
not in fragile live agentic behavior (there is no runtime orchestration agent —
see FINAL_PLAN §8).

## Tooling

- **Build-time AI: Claude Code / Cursor** (Claude Opus/Sonnet during development) —
  primary builders: schema contracts, deterministic generator, defect catalog,
  the engine/API, tests, and docs.
- Deterministic Python (numpy/pandas/Pandera/Pydantic/SciPy/XGBoost) does **all**
  numerical work. The **runtime narrator** (Stage 5) is a bounded LLM sidecar with
  a deterministic template fallback: it never computes budgets, ranks, approves, or
  executes — it only narrates an already-computed snapshot. The provider is chosen
  from environment keys (OpenAI `OPENAI_API_KEY` tried first, then Anthropic
  `ANTHROPIC_API_KEY`); **in this demo it is served by `gpt-4o-mini`**. If no key
  is set or the call/grounding-check fails, the deterministic template is used.

## How Stage 0 was prompted & verified

1. **Read both source docs in full** before any code; treated `docs/FINAL_PLAN.md`
   as canonical and surfaced contradictions (Prophet/Amazon/Streamlit in the
   brief vs. the locked plan) before building.
2. **Designed the scenario truth first**, then *pressure-tested the numbers* with
   throwaway scripts: swept the marginal-ROAS floor to size the efficiency-first
   reserve, and searched a beta scale so a bounded ±20% reallocation lifts
   calibrated blended ROAS across the 4.0 line. Constants were chosen from these
   checks, not guessed.
3. **Encoded invariants as tolerances/directions**, not a single allocation, so
   the Stage-3 optimizer has room to solve while the tensions stay guaranteed.
4. **Froze a content fingerprint** as a determinism regression guard.

## Interventions / corrections (what was changed or rejected)

- **Rejected: business reasoning inside the LLM.** The decision boundary is
  explicit — numbers come from deterministic code; the LLM only ranks allowed
  candidates or narrates validated output. (This is the planned Q&A line:
  "the coding model put business reasoning inside the LLM; I moved all numeric
  decisions into deterministic services.")
- **Corrected: inventory guardrail tripped three SKUs.** First pass hard-coded
  units-on-hand and accidentally made three SKUs stockout-risky, diluting the
  "one constrained SKU" story. Changed to a target-days-of-cover formulation so
  exactly the joggers breach the threshold — deterministically, regardless of
  simulated demand.
- **Corrected: blended ROAS unreachable.** First scenario left calibrated blended
  ROAS at ~3.6 with no bounded reallocation able to reach 4.0 — i.e. the primary
  metric was unattainable. Re-tuned so the current state is just below target and
  the optimizer can cross it (see DECISIONS D-008).
- **Corrected: empty operational tables failed schema** (object-dtype empties).
  Added `coerce=True` to those schemas rather than faking rows.

## Post-review remediation (a second AI reviewer found real issues)

A separate AI reviewer (Codex) audited Stage 0. Each finding was **verified
against the code before acting** — not taken on faith — and all were legitimate:

- **Latent-truth leakage (blocking).** `scenario_truth.csv` (marginal ROAS,
  incrementality, noise) was written into `data/canonical`, a target-leakage
  risk. Fixed: kept in memory; persisted only under `data/internal/latent`
  behind `--write-latent-truth`; added isolation tests (D-009).
- **Validation overclaim (blocking).** Tests only proved wholesale envelope
  rejection. Added a two-level record-validation/quarantine utility and
  mixed valid/invalid tests (D-010).
- **Knife-edge ROAS (important).** The fixture crossed 4.0 by 0.09 (3.946→4.034),
  which looks manufactured. *Searched the parameter space* and found the
  structural tension: bigger saturated channels free more budget but drag the
  average down. Retuned to a broad band (≈3.88 → ≈4.12, +0.23) where the result
  emerges from the data, not a hardcoded number (D-008).
- **Magic hurdle (important).** Replaced the `2.8` efficiency constant with an
  economic derivation (break-even = 1/margin, × safety multipliers). The
  derivation *validated* the old number (2.754 ≈ 2.8) — reassuring, but now it is
  principled and tested against margin/risk changes (D-007).
- Also: reproducible dependency lock (D-011), independent defect contract
  fixture (D-012), manifest + logical fingerprints (D-013), field rename (D-014).

**Process note:** the retune was driven by throwaway search scripts, and one of
the new isolation tests *caught my own first cut* (it flagged `marginal_roas` on
the `recommendation` output table — a false positive I then scoped to input
tables only). The tests earned their keep immediately.

## Second review round (the most important catch)

A follow-up review found that my D-008 "proof" was **constraint-invalid**. The
greedy marginal-rank helper that produced 4.1146 *ignored the constraints it was
supposed to honor* — it scaled the inventory-constrained PMax campaign and
starved prospecting below its share floor. Verified directly: prospecting share
0.321 < 0.35 and PMax +11%. This is the exact failure mode the whole system is
meant to prevent, hiding inside a test helper. Fixes:

- Replaced the greedy helper with a transparent **constraint-valid enumeration**
  (`tests/_feasibility.py`) honoring movement bounds, caps, inventory no-scale,
  prospecting floor, budget/reserve, ROAS floor, and contribution lift. The real
  feasible witness is ≈4.099 (not 4.1146), with prospecting 0.351 and PMax held.
- **Validation through normalization** (`ingestion.py`): valid records now
  demonstrably become canonical rows; invalid ones are quarantined.
- **Full-artifact fingerprint** as the main reproducibility hash (tables +
  envelopes + versions + seed + deps), with drift tests.
- **Typed empty operational tables** (explicit Arrow/DuckDB schemas).
- **Campaign/SKU-specific economic hurdles**; **enforcing `make lint`**; removed a
  duplicate constant; corrected the deps comment.

Lesson captured for later stages: a feasibility/optimizer helper must enforce the
*same* constraint set the product advertises, or it proves nothing. Tests that
assert an outcome number without re-checking feasibility can launder an invalid
allocation into a green suite.

## Scope reset (the most important meta-lesson)

The two review rounds above, while each finding was technically valid, walked the
work **past the Stage 0 boundary** one "good fix" at a time: raw→canonical
normalization and a validation/quarantine utility (both **Stage 2**), and a
constrained allocation search + reserve-feasibility (both **Stage 3/4**). The
original mandate was "implement Stage 0 only." So those were **removed** and
deferred to their proper stages, with the design rationale preserved in
`docs/DECISIONS.md` (D-020) as the spec for those stages.

What stayed is everything that is genuinely Stage 0 infrastructure: deterministic
generator, 13 schemas, planted defects, golden scenario, latent-truth isolation,
dependency lock, typed persistence, full-artifact manifest/fingerprint, and the
independent defect contract. The allocation-feasibility proof was replaced by a
broad property assertion that the scenario *supports* a future optimization —
Stage 0 never computes one.

Meta-lesson: a green review comment is not the same as in-scope work. "Valid bug,
wrong stage" is a real category, and staging discipline outranks an individual
reviewer's local correctness point.

## What stays human-in-the-loop

SKU mapping approval, recommendation approve/edit/reject, and constraint
relaxation are all human decisions. The schema **rejects any SKU not in the
allowed-candidates list**, so the LLM cannot invent a mapping.
