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
  reason_codes: string[];
  risk_flags: string[];
}

export interface Kpis {
  blended_roas_current: number;
  blended_roas_projected: number;
  total_current_spend: number;
  total_recommended_spend: number;
  reserve: number;
}

export type RecommendationStatus = "pending" | "approved" | "rejected";

export interface Recommendation {
  rec_id: string;
  run_id: string;
  policy_mode: string;
  generated_at: string;
  status: RecommendationStatus;
  is_fixed_placeholder: boolean;
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
