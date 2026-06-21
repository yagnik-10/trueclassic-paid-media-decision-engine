// Typed client for the decision API — ported verbatim from the Next.js frontend
// (frontend/lib/api.ts), the single source of truth for API shapes. The only
// framework difference is the base-URL env var: Vite uses import.meta.env.

export const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";

export interface CampaignLine {
  campaign_id: string;
  campaign_name: string;
  platform: string;
  segment: string;
  current_spend: number;
  recommended_spend: number;
  delta_pct: number;
  marginal_roas: number;
  marginal_roas_downside: number;
  marginal_hurdle: number; // this campaign's own break-even hurdle (1/CM × safety)
  current_revenue: number;
  response_slope: number;
  response_quad: number;
  forecast_p10: number;
  forecast_p50: number;
  forecast_p90: number;
  forecast_p10_raw: number;
  forecast_p90_raw: number;
  forecast_model: string;
  reason_codes: string[];
  risk_flags: string[];
  daily_cap: number;
  current_utilization: number;
  recommended_utilization: number;
  pacing_flag: string; // scale_opportunity | capped_constrained | strategic_floor | pullback_candidate | waste_risk | healthy
  incrementality: number;
  calibrated_roas_current: number;
  platform_roas_current: number;
  // CM (contribution-margin) marginal economics — primary decision lens (D-041).
  // marginal_cm_roas = contribution_margin_rate × marginal_roas; break-even 1.0×.
  contribution_margin_rate: number;
  marginal_cm_roas: number;
  marginal_cm_roas_downside: number;
}

export interface Kpis {
  // primary success metrics (D-041)
  cm_roas_current: number;
  cm_roas_projected: number;
  net_contribution_current: number;
  net_contribution_projected: number;
  // governance lens: calibrated gross ROAS is the enforced floor
  blended_roas_current: number;
  blended_roas_projected: number;
  reported_roas_current: number;
  reported_roas_projected: number;
  total_current_spend: number;
  total_recommended_spend: number;
  reserve: number;
  nc_cpa_projected: number;
}

export type ReserveMode = "growth" | "efficiency_first";

export interface ConstraintParams {
  roas_floor: number;
  nc_cpa_target: number;
  prospecting_min_share: number;
  movement_bound: number;
  reserve_mode: ReserveMode;
  calibration_overrides: Record<string, number>;
}

export interface CalibrationProvenanceRow {
  registry_id: string;
  segment: string;
  coefficient: number;
  approved_coefficient: number;
  source: string;
  effective_start: string;
  effective_end: string | null;
  confidence: string;
  scope: string;
  is_synthetic: boolean;
  overridden: boolean;
}

export interface BindingItem {
  name: string;
  status: string; // binding | slack | violated
  detail: string;
}

export interface CampaignBound {
  campaign_id: string;
  limits: string[];
  detail: string;
}

export interface SolverStatus {
  success: boolean;
  status: number;
  message: string;
  iterations: number;
  // decomposed signals (D-040): feasibility / convergence / stability / optimality
  business_feasible?: boolean;
  solver_converged?: boolean;
  candidate_stable?: boolean;
  local_optimality_converged?: boolean;
  solver_qualified?: boolean;
  improves_on_current?: boolean;
  n_starts?: number;
  n_feasible_starts?: number;
  n_near_best?: number;
  best_contribution?: number;
  worst_contribution?: number;
  near_best_alloc_spread?: number;
  current_allocation_contribution?: number;
  warning?: string;
}

export interface BindingReport {
  portfolio: BindingItem[];
  per_campaign: CampaignBound[];
  solver: SolverStatus;
}

export interface IntervalCalibration {
  method: string;
  offset: number;
  target_coverage: number;
  n_calibration: number;
  calibration_coverage_raw: number;
  calibration_coverage_calibrated: number;
}

export type RecommendationStatus = "pending" | "approved" | "rejected";

export interface Recommendation {
  rec_id: string;
  run_id: string;
  policy_mode: string;
  generated_at: string;
  scenario_id: string;
  data_fingerprint: string;
  engine_version: string;
  config_fingerprint: string;
  effective_movement_bound: number;
  status: RecommendationStatus;
  is_fixed_placeholder: boolean;
  engine: string;
  feasible: boolean;
  conflicts: string[];
  marginal_scale_floor: number;
  // CM-unit decision thresholds (constant across campaigns): hurdle = HARD_FLOOR_SAFETY,
  // break-even = 1.0×.
  marginal_cm_hurdle: number;
  cm_break_even: number;
  level_anchor: string;
  constraints: ConstraintParams;
  lines: CampaignLine[];
  kpis: Kpis;
  binding: BindingReport;
  calibration_registry: CalibrationProvenanceRow[];
  is_sensitivity_override: boolean;
  calibration_fingerprint: string;
  effective_calibration_fingerprint: string;
  interval_calibration: IntervalCalibration;
}

export interface ExecutionEvent {
  event_id: string;
  rec_id: string;
  platform: string;
  payload_hash: string;
  status: string;
  is_stub: boolean;
  created_at: string;
}

export interface ExecutionPayloadChange {
  campaign_id: string;
  campaign_name: string;
  platform: string;
  current_spend: number;
  new_daily_budget: number;
  delta_pct: number;
}

export interface ExecutionPlatformPayload {
  event_id: string;
  platform: string;
  payload_hash: string;
  is_stub: boolean;
  changes: ExecutionPayloadChange[];
}

export interface ExecutionPreview {
  scenario_id: string;
  is_stub: boolean;
  status: string;
  note: string;
  total_changes: number;
  held_flat: string[];
  inventory_blocked: string[];
  payloads: ExecutionPlatformPayload[];
}

export interface DecisionResponse {
  rec_id: string;
  scenario_id: string;
  policy: string;
  constraints: ConstraintParams;
  allocation: Record<string, number>;
  data_fingerprint: string;
  engine_version: string;
  config_fingerprint: string;
  calibration_fingerprint: string;
  effective_calibration_fingerprint: string;
  binding: BindingReport;
  action: "approve" | "reject";
  previous_status: "pending";
  new_status: "approved" | "rejected";
  status: "approved" | "rejected";
  approver: string;
  decided_at: string;
  notes?: string | null;
  execution_events: ExecutionEvent[];
  idempotent_replay: boolean;
  ledger_seq: number;
  prev_hash: string;
  row_hash: string;
}

export interface AuditChainStatus {
  ok: boolean;
  count: number;
  head_hash: string;
  broken_seq: number | null;
}

// --- Stage 2: ingestion & reconciliation -----------------------------------
export interface FeedStat {
  platform: string;
  raw: number;
  normalized: number;
  quarantined: number;
}

export interface DqIssue {
  issue_id: string;
  issue_type: string;
  severity: string;
  entity_type: string;
  entity_ref: string;
  description: string;
  resolution: string;
}

export interface SkuResolutionItem {
  platform: string;
  platform_product_id: string;
  sku_id: string | null;
  status: string;
  confidence: number;
  allowed_candidates: string[];
}

export interface IngestionSummary {
  feeds: FeedStat[];
  canonical_fact_rows: number;
  canonical_commerce_rows: number;
  total_quarantined: number;
  dq_issues: DqIssue[];
  sku_resolutions: SkuResolutionItem[];
  sku_resolution_summary: Record<string, number>;
}

// --- Buyer & Inventory (thin guardrail beat — FINAL_PLAN §9) ---------------
export interface BuyerCampaignLink {
  campaign_id: string;
  campaign_name: string;
  platform: string;
}

export type InventoryUrgency = "urgent" | "reorder_soon" | "monitor";

export interface BuyerInventoryItem {
  sku_id: string;
  product_name: string;
  units_on_hand: number;
  forecast_daily_demand: number;
  days_of_cover: number;
  lead_time_days: number;
  safety_days: number;
  stockout_risk: boolean;
  no_scale: boolean;
  estimated_stockout_date: string;
  reorder_qty: number;
  reorder_assumption: string;
  urgency: InventoryUrgency;
  linked_campaigns: BuyerCampaignLink[];
}

export interface BuyerInventoryResponse {
  snapshot_date: string;
  reorder_policy: string;
  items: BuyerInventoryItem[];
}

// --- Model Evidence (curated view over the model report) -------------------
export interface EvidenceProvenance {
  dataset_profile: string;
  engine_version: string;
  report_version: string;
  data_fingerprint: string;
  panel_data_fingerprint: string;
  config_fingerprint: string;
  calibration_fingerprint: string;
  evidence_input_fingerprint: string;
  master_seed: number;
  note: string;
}

export interface ChampionPreTest {
  xgb_wape: number;
  best_baseline_wape: number;
  improvement_pct: number;
  fold_wins: number;
  n_folds: number;
  threshold: number;
  reason: string;
}

export interface ModelTestPoint {
  model: string;
  wape: number | null;
  mae: number | null;
  bias_me: number | null;
}

export interface ForecastSeriesPoint {
  date: string;
  actual: number;
  pred: number;
  p10: number;
  p50: number;
  p90: number;
  residual: number;
  covered: boolean;
}

export interface ChampionCampaign {
  campaign_id: string;
  selected_model: string;
  is_xgb_champion: boolean;
  pretest: ChampionPreTest | null;
  test_points: ModelTestPoint[];
  champion_test_wape: number | null;
  best_baseline_test_wape: number | null;
  holdout_drift: boolean;
  drift_pct_worse: number | null;
  test_series: ForecastSeriesPoint[];
  test_coverage: number | null;
}

export interface EvidenceSummary {
  overall_test_wape: number | null;
  approx_point_accuracy_pct: number | null;
  xgb_materially_beats_baseline_in: string[];
  fallback_campaigns: string[];
  champion_holdout_drift_campaigns: string[];
  safe_for_model_demo: boolean;
  safe_for_decision_demo: boolean;
}

export interface ModelEvidenceResponse {
  schema_version: string;
  report_version: string;
  generated_at: string;
  stale: boolean;
  stale_reason: string | null;
  active_evidence_input_fingerprint: string;
  series_available: boolean;
  provenance: EvidenceProvenance;
  summary: EvidenceSummary;
  campaigns: ChampionCampaign[];
}

// Distinguish HTTP failures so callers can react to 409 (stale/superseded) and
// 422 (infeasible/sensitivity) on the decision endpoint — never swallow them.
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function detailMessage(detail: unknown, fallback: string): string {
  // FastAPI 422 returns a list of {loc, msg, type}; surface the real reason.
  if (Array.isArray(detail)) {
    return (
      detail
        .map((d: { loc?: (string | number)[]; msg?: string }) =>
          `${d.loc?.slice(-1)[0] ?? ""}: ${d.msg ?? ""}`.trim(),
        )
        .join("; ") || fallback
    );
  }
  return typeof detail === "string" ? detail : fallback;
}

async function asError(res: Response, fallback: string): Promise<ApiError> {
  const body = await res.json().catch(() => ({}));
  return new ApiError(res.status, detailMessage((body as any).detail, fallback));
}

function constraintQuery(c?: ConstraintParams): URLSearchParams {
  const q = new URLSearchParams();
  if (!c) return q;
  q.set("roas_floor", String(c.roas_floor));
  q.set("nc_cpa_target", String(c.nc_cpa_target));
  q.set("prospecting_min_share", String(c.prospecting_min_share));
  q.set("movement_bound", String(c.movement_bound));
  q.set("reserve_mode", c.reserve_mode);
  if (Object.keys(c.calibration_overrides).length > 0) {
    q.set("calibration_overrides", JSON.stringify(c.calibration_overrides));
  }
  return q;
}

export async function getRecommendation(
  policy: "expected" | "conservative" = "expected",
  c?: ConstraintParams,
): Promise<Recommendation> {
  const q = constraintQuery(c);
  q.set("policy", policy);
  const res = await fetch(`${API_BASE}/api/recommendation?${q}`, { cache: "no-store" });
  if (!res.ok) throw await asError(res, `recommendation failed: ${res.status}`);
  return res.json();
}

// Stage 5 bounded narrator: prose-only explanation of a stored snapshot. `source`
// is "llm" (live Claude call) or "fallback" (deterministic template). Numbers in
// the UI always render from app state, never parsed from this text.
export interface Narration {
  text: string;
  source: "llm" | "fallback";
  model: string;
}

export async function getNarration(scenarioId: string): Promise<Narration> {
  const res = await fetch(`${API_BASE}/api/recommendation/${scenarioId}/narration`, {
    cache: "no-store",
  });
  if (!res.ok) throw await asError(res, `narration failed: ${res.status}`);
  return res.json();
}

export async function getExecutionPreview(scenarioId: string): Promise<ExecutionPreview> {
  // read-only: the stubbed set-budget payloads approval WOULD commit (no live write).
  const res = await fetch(`${API_BASE}/api/recommendation/${scenarioId}/execution-preview`, {
    cache: "no-store",
  });
  if (!res.ok) throw await asError(res, `execution preview failed: ${res.status}`);
  return res.json();
}

export async function getAudit(scenarioId: string): Promise<DecisionResponse | null> {
  const res = await fetch(`${API_BASE}/api/recommendation/${scenarioId}/audit`, {
    cache: "no-store",
  });
  if (res.status === 404) return null;
  if (!res.ok) throw await asError(res, `audit failed: ${res.status}`);
  return res.json();
}

export async function getAuditLog(): Promise<DecisionResponse[]> {
  const res = await fetch(`${API_BASE}/api/audit/log`, { cache: "no-store" });
  if (!res.ok) throw await asError(res, `audit log failed: ${res.status}`);
  return res.json();
}

export async function verifyAuditChain(): Promise<AuditChainStatus> {
  const res = await fetch(`${API_BASE}/api/audit/verify`, { cache: "no-store" });
  if (!res.ok) throw await asError(res, `audit verify failed: ${res.status}`);
  return res.json();
}

export async function getIngestion(): Promise<IngestionSummary> {
  const res = await fetch(`${API_BASE}/api/ingestion`, { cache: "no-store" });
  if (!res.ok) throw await asError(res, `ingestion failed: ${res.status}`);
  return res.json();
}

export async function getInventory(): Promise<BuyerInventoryResponse> {
  // read-only buyer/inventory snapshot + reorder suggestion (no live write).
  const res = await fetch(`${API_BASE}/api/inventory`, { cache: "no-store" });
  if (!res.ok) throw await asError(res, `inventory failed: ${res.status}`);
  return res.json();
}

export async function getModelEvidence(): Promise<ModelEvidenceResponse> {
  // curated, versioned view over the deterministic model report (read-only).
  const res = await fetch(`${API_BASE}/api/model-evidence`, { cache: "no-store" });
  if (!res.ok) throw await asError(res, `model evidence failed: ${res.status}`);
  return res.json();
}

export async function approveSku(
  platformProductId: string,
  skuId: string,
  approver: string,
): Promise<SkuResolutionItem> {
  const res = await fetch(
    `${API_BASE}/api/sku-resolution/${encodeURIComponent(platformProductId)}/approve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sku_id: skuId, approver }),
    },
  );
  if (!res.ok) throw await asError(res, `approve failed: ${res.status}`);
  return res.json();
}

export async function resetDemoState(): Promise<{ ok: boolean; decisions_cleared: number }> {
  // DEMO/admin reset: clears the durable decision ledger + SKU approvals on the
  // backend, returning the whole app to a fresh, pending state.
  const res = await fetch(`${API_BASE}/api/admin/reset`, { method: "POST" });
  if (!res.ok) throw await asError(res, `reset failed: ${res.status}`);
  return res.json();
}

export async function postDecision(
  scenarioId: string,
  action: "approve" | "reject",
  approver: string,
  notes?: string,
): Promise<DecisionResponse> {
  // approval binds to the stored snapshot by scenario_id — no re-solve, no constraints.
  // 409 = stale/superseded; 422 = infeasible/sensitivity; surfaced via ApiError.status.
  const res = await fetch(`${API_BASE}/api/recommendation/${scenarioId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, approver, notes }),
  });
  if (!res.ok) throw await asError(res, `decision failed: ${res.status}`);
  return res.json();
}
