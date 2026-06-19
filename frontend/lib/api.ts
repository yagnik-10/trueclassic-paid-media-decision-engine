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
  current_revenue: number;
  response_slope: number;
  response_quad: number;
  forecast_p10: number;
  forecast_p50: number;
  forecast_p90: number;
  forecast_model: string;
  reason_codes: string[];
  risk_flags: string[];
}

export interface Kpis {
  blended_roas_current: number;
  blended_roas_projected: number;
  reported_roas_current: number;
  reported_roas_projected: number;
  total_current_spend: number;
  total_recommended_spend: number;
  reserve: number;
  nc_cpa_projected: number;
}

export type RecommendationStatus = "pending" | "approved" | "rejected";

export interface Recommendation {
  rec_id: string;
  run_id: string;
  policy_mode: string;
  generated_at: string;
  status: RecommendationStatus;
  is_fixed_placeholder: boolean;
  engine: string;
  feasible: boolean;
  conflicts: string[];
  marginal_scale_floor: number;
  lines: CampaignLine[];
  kpis: Kpis;
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

export async function getRecommendation(): Promise<Recommendation> {
  const res = await fetch(`${API_BASE}/api/recommendation`, { cache: "no-store" });
  if (!res.ok) throw new Error(`recommendation failed: ${res.status}`);
  return res.json();
}

export async function getAudit(recId: string): Promise<DecisionResponse | null> {
  const res = await fetch(`${API_BASE}/api/recommendation/${recId}/audit`, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`audit failed: ${res.status}`);
  return res.json();
}

export async function postDecision(
  recId: string,
  action: "approve" | "reject",
  approver: string,
  notes?: string,
): Promise<DecisionResponse> {
  const res = await fetch(`${API_BASE}/api/recommendation/${recId}/decision`, {
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
