// Typed client for the Stage 1 decision API.

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

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

export interface CalibrationRegistryEntry {
  registry_id: string;
  segment: string;
  coefficient: number;
  source: string;
  effective_start: string;
  effective_end: string | null;
  confidence: string;
  scope: string;
  is_synthetic: boolean;
}

export interface CalibrationRegistryResponse {
  entries: CalibrationRegistryEntry[];
  note: string;
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

export interface IntervalCalibration {
  method: string;
  offset: number;
  target_coverage: number;
  n_calibration: number;
  calibration_coverage_raw: number;
  calibration_coverage_calibrated: number;
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

export async function getCalibrationRegistry(): Promise<CalibrationRegistryResponse> {
  const res = await fetch(`${API_BASE}/api/calibration/registry`, { cache: "no-store" });
  if (!res.ok) throw new Error(`calibration registry failed: ${res.status}`);
  return res.json();
}

export async function getIngestion(): Promise<IngestionSummary> {
  const res = await fetch(`${API_BASE}/api/ingestion`, { cache: "no-store" });
  if (!res.ok) throw new Error(`ingestion failed: ${res.status}`);
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
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail ?? `approve failed: ${res.status}`);
  }
  return res.json();
}

function detailMessage(detail: unknown, fallback: string): string {
  // FastAPI 422 returns a list of {loc, msg, type}; surface the real reason.
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: (string | number)[]; msg?: string }) =>
        `${d.loc?.slice(-1)[0] ?? ""}: ${d.msg ?? ""}`.trim())
      .join("; ") || fallback;
  }
  return typeof detail === "string" ? detail : fallback;
}

export async function getRecommendation(
  policy: "expected" | "conservative" = "expected",
  c?: ConstraintParams,
): Promise<Recommendation> {
  const q = new URLSearchParams({ policy });
  if (c) {
    q.set("roas_floor", String(c.roas_floor));
    q.set("nc_cpa_target", String(c.nc_cpa_target));
    q.set("prospecting_min_share", String(c.prospecting_min_share));
    q.set("movement_bound", String(c.movement_bound));
    q.set("reserve_mode", c.reserve_mode);
    if (Object.keys(c.calibration_overrides).length > 0) {
      q.set("calibration_overrides", JSON.stringify(c.calibration_overrides));
    }
  }
  const res = await fetch(`${API_BASE}/api/recommendation?${q}`, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(detailMessage(body.detail, `recommendation failed: ${res.status}`));
  }
  return res.json();
}

export async function getAudit(scenarioId: string): Promise<DecisionResponse | null> {
  const res = await fetch(`${API_BASE}/api/recommendation/${scenarioId}/audit`, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`audit failed: ${res.status}`);
  return res.json();
}

// Stage 4.4 — durable, append-only, hash-chained decision ledger
export interface AuditChainStatus {
  ok: boolean;
  count: number;
  head_hash: string;
  broken_seq: number | null;
}

export async function getAuditLog(): Promise<DecisionResponse[]> {
  const res = await fetch(`${API_BASE}/api/audit/log`, { cache: "no-store" });
  if (!res.ok) throw new Error(`audit log failed: ${res.status}`);
  return res.json();
}

export async function verifyAuditChain(): Promise<AuditChainStatus> {
  const res = await fetch(`${API_BASE}/api/audit/verify`, { cache: "no-store" });
  if (!res.ok) throw new Error(`audit verify failed: ${res.status}`);
  return res.json();
}

export async function postDecision(
  scenarioId: string,
  action: "approve" | "reject",
  approver: string,
  notes?: string,
): Promise<DecisionResponse> {
  // approval binds to the stored snapshot by scenario_id — no re-solve, no constraints
  const res = await fetch(`${API_BASE}/api/recommendation/${scenarioId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, approver, notes }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail ?? `decision failed: ${res.status}`);
  }
  return res.json();
}
