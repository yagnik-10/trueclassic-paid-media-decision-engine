import { useCallback, useEffect, useState } from 'react';
import {
  CheckCircle,
  Database,
  Search,
  FileText,
  Loader2,
  ShieldCheck,
  AlertTriangle,
} from 'lucide-react';
import { useRecommendation } from '../state/RecommendationContext';
import { PlatformLogo } from './BrandLogo';
import {
  approveSku,
  getIngestion,
  ApiError,
  type IngestionSummary,
  type SkuResolutionItem,
} from '../lib/api';

const APPROVER = 'marketer@trueclassic';

const platformLabel = (p: string) =>
  p === 'meta' ? 'Meta Ads' : p === 'google' ? 'Google Ads' : p === 'shopify' ? 'Shopify' : p;

const sevTone = (s: string) =>
  s === 'high'
    ? { dot: 'border-red-500', badge: 'bg-red-50 text-red-800 border-red-200' }
    : s === 'medium'
    ? { dot: 'border-amber-500', badge: 'bg-amber-50 text-amber-800 border-amber-200' }
    : { dot: 'border-blue-500', badge: 'bg-blue-50 text-blue-800 border-blue-200' };

const humanize = (s: string) => s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

export default function DataUnification() {
  // The active recommendation drives the rest of the app; ingestion is its own
  // deterministic report. We refetch it when a new plan is solved (decision change).
  const { decision } = useRecommendation();
  const [data, setData] = useState<IngestionSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [approvingId, setApprovingId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setData(await getIngestion());
      setError(null);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh, decision?.row_hash]);

  const onApprove = async (item: SkuResolutionItem) => {
    // One-click approve only binds to a CONCRETE suggested match (resolved sku_id).
    // We never auto-bind an unmapped/quarantined row to the nearest-string candidate.
    const candidate =
      item.sku_id && item.allowed_candidates.includes(item.sku_id) ? item.sku_id : null;
    if (!candidate) return;
    setApprovingId(item.platform_product_id);
    try {
      await approveSku(item.platform_product_id, candidate, APPROVER);
      await refresh();
      setError(null);
    } catch (e: any) {
      const prefix = e instanceof ApiError ? `(${e.status}) ` : '';
      setError(prefix + (e?.message ?? String(e)));
    } finally {
      setApprovingId(null);
    }
  };

  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 text-[#45464d] text-sm animate-fade-in">
        <Loader2 size={16} className="animate-spin text-[#00714d]" /> Loading ingestion report…
      </div>
    );
  }
  if (error && !data) {
    return (
      <div className="bg-[#fee2e2] border border-[#fca5a5] text-[#7f1d1d] rounded-xl p-4 text-sm animate-fade-in">
        <b>Could not reach the ingestion API.</b> ({error})
      </div>
    );
  }
  if (!data) return null;

  const needsApproval = data.sku_resolution_summary['needs_approval'] ?? 0;
  const quarantinedSkus = data.sku_resolution_summary['quarantined'] ?? 0;
  const unresolved = needsApproval + quarantinedSkus;
  const clean = unresolved === 0 && data.total_quarantined === 0;

  const filtered = data.sku_resolutions.filter(
    (m) =>
      m.platform_product_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (m.sku_id ?? '').toLowerCase().includes(searchQuery.toLowerCase()),
  );

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Module Title */}
      <div className="flex justify-between items-end">
        <div>
          <h2 className="text-2xl font-bold font-headline-lg text-[#0d1c2d] tracking-tight">
            Data Unification Module
          </h2>
          <p className="text-sm text-[#45464d] mt-1">
            Deterministic ingestion of Meta + Google media and Shopify commerce truth: schema
            normalization, quarantine, and allowed-candidate SKU resolution.
          </p>
        </div>
        <span
          className={`inline-flex items-center gap-1 px-3 py-1 text-xs font-semibold rounded-full border ${
            clean
              ? 'bg-green-50 text-green-800 border-green-200'
              : 'bg-amber-50 text-amber-800 border-amber-200'
          }`}
        >
          {clean ? <CheckCircle size={13} className="text-green-600" /> : <AlertTriangle size={13} />}
          {clean ? 'System Healthy' : `${unresolved} item${unresolved === 1 ? '' : 's'} need review`}
        </span>
      </div>

      {/* Source Health Monitoring */}
      <div className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h3 className="text-sm font-semibold text-[#0d1c2d]">Source Health Monitoring</h3>
          <span className="text-[11px] text-[#76777d] font-data-mono">
            {data.canonical_fact_rows.toLocaleString()} fact rows ·{' '}
            {data.canonical_commerce_rows.toLocaleString()} commerce rows · {data.total_quarantined}{' '}
            quarantined
          </span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {data.feeds.map((f) => {
            const pct = f.raw > 0 ? (f.normalized / f.raw) * 100 : 100;
            const hasQ = f.quarantined > 0;
            return (
              <div
                key={f.platform}
                className="bg-white border border-[#e2e8f0] rounded-xl p-5 shadow-sm transition-all hover:border-[#00714d]/30"
              >
                <div className="flex justify-between items-center mb-4">
                  <div className="flex items-center gap-2">
                    <PlatformLogo platform={f.platform} />
                    <span className="text-xs font-bold text-[#0d1c2d]">{platformLabel(f.platform)}</span>
                  </div>
                  <span className="text-[11px] text-[#76777d]">deterministic feed</span>
                </div>

                <div className="space-y-3 text-xs leading-none">
                  <div className="flex justify-between items-center">
                    <span className="text-[#45464d]">Raw records received</span>
                    <span className="font-bold font-data-mono text-[#0d1c2d]">{f.raw.toLocaleString()}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-[#45464d] flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-[#006c49]" /> Normalized
                    </span>
                    <span className="font-bold font-data-mono text-[#0d1c2d]">{f.normalized.toLocaleString()}</span>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-[#45464d] flex items-center gap-1">
                      <span className={`w-1.5 h-1.5 rounded-full ${hasQ ? 'bg-red-500' : 'bg-gray-300'}`} /> Quarantined
                    </span>
                    <span className={`font-bold font-data-mono ${hasQ ? 'text-red-700' : 'text-[#76777d]'}`}>
                      {f.quarantined.toLocaleString()}
                    </span>
                  </div>
                </div>

                <div className="mt-4 pt-3 border-t border-[#e2e8f0]/40">
                  <div className="w-full bg-[#eef4ff] rounded-full h-1.5 overflow-hidden">
                    <div
                      className={`h-full rounded-full ${hasQ ? 'bg-amber-500' : 'bg-green-500'}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <div className="flex justify-between items-center mt-1.5 text-[10px] text-[#76777d]">
                    <span>Normalization Ratio</span>
                    <span className="font-semibold">{pct.toFixed(1)}%</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {error && data && (
        <div className="bg-[#fee2e2] border border-[#fca5a5] text-[#7f1d1d] rounded-lg p-3 text-sm">
          {error}
        </div>
      )}

      {/* Reconciliation table + resolution-status panel */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-8 bg-white border border-[#e2e8f0] rounded-xl shadow-sm flex flex-col overflow-hidden">
          <div className="p-4 border-b border-[#e2e8f0] flex justify-between items-center bg-[#f8f9ff]">
            <div className="flex items-center gap-2">
              <Database size={15} className="text-[#0d1c2d]" />
              <h3 className="text-xs font-bold text-[#0d1c2d] uppercase tracking-wider">
                SKU Reconciliation Workflow
              </h3>
            </div>
            <span className="text-[11px] text-[#76777d] font-data-mono">
              {data.sku_resolutions.length} resolutions
            </span>
          </div>

          <div className="p-3 bg-white border-b border-[#e2e8f0]/60 flex">
            <div className="relative w-full max-w-xs">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#76777d]" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Filter by product ID or SKU..."
                className="w-full pl-8 pr-3 py-1 text-xs rounded border border-[#c6c6cd] focus:outline-none focus:border-[#00714d]"
              />
            </div>
          </div>

          <div className="overflow-x-auto flex-1 h-full min-h-[220px]">
            <table className="w-full text-left border-collapse text-xs">
              <thead className="bg-[#f8f9ff] border-b border-[#e2e8f0]">
                <tr>
                  <th className="p-3 text-[#45464d] font-semibold">Platform Product ID</th>
                  <th className="p-3 text-[#45464d] font-semibold">Resolved SKU</th>
                  <th className="p-3 text-[#45464d] font-semibold">Confidence</th>
                  <th className="p-3 text-[#45464d] font-semibold">Status</th>
                  <th className="p-3 text-[#45464d] font-semibold text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#e2e8f0]/60 text-[#0d1c2d]">
                {filtered.map((m) => {
                  const pct = Math.round(m.confidence * 100);
                  const isApproved = m.status === 'approved';
                  const isAuto = m.status === 'auto_matched';
                  const isNeeds = m.status === 'needs_approval';
                  const isQuarantined = m.status === 'quarantined';
                  // Only a CONCRETE suggested match (resolved sku_id) is one-click
                  // approvable. A quarantined / 0%-confidence row has no sku_id — its
                  // nearest-string candidates are hints for manual review, not an
                  // auto-bind target — so it never shows a confident "Approve → X".
                  const candidate =
                    m.sku_id && m.allowed_candidates.includes(m.sku_id) ? m.sku_id : null;
                  const canApprove = (isNeeds || isQuarantined) && !!candidate;
                  return (
                    <tr key={m.platform_product_id} className={`hover:bg-[#eef4ff]/30 transition-all ${isQuarantined ? 'bg-red-50/20' : ''}`}>
                      <td className="p-3 font-semibold font-data-mono">{m.platform_product_id}</td>
                      <td className="p-3 text-[#45464d] font-data-mono">{m.sku_id ?? '—'}</td>
                      <td className="p-3">
                        <div className="flex items-center gap-2">
                          <div className="w-16 bg-[#eef4ff] rounded-full h-1.5 overflow-hidden">
                            <div
                              className={`h-full rounded-full ${pct >= 80 ? 'bg-green-500' : pct >= 60 ? 'bg-amber-500' : 'bg-red-500'}`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <span className="font-semibold font-data-mono text-[11px]">{pct}%</span>
                        </div>
                      </td>
                      <td className="p-3">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold border ${
                          isApproved
                            ? 'bg-green-50 text-green-800 border-green-200'
                            : isAuto
                            ? 'bg-gray-100 text-gray-700 border-gray-200'
                            : isNeeds
                            ? 'bg-[#fef3c7] text-[#92400E] border-[#fde68a]'
                            : 'bg-red-50 text-red-800 border-red-200'
                        }`}>
                          {humanize(m.status)}
                        </span>
                      </td>
                      <td className="p-3 text-right">
                        {canApprove ? (
                          <button
                            onClick={() => onApprove(m)}
                            disabled={approvingId === m.platform_product_id}
                            className="text-xs bg-[#40c057]/15 hover:bg-[#40c057]/30 text-[#006c49] px-2 py-1 rounded font-semibold transition-colors disabled:opacity-50 inline-flex items-center gap-1"
                            title={`Approve canonical match → ${candidate}`}
                          >
                            {approvingId === m.platform_product_id ? (
                              <Loader2 size={11} className="animate-spin" />
                            ) : (
                              <>Approve → <span className="font-data-mono">{candidate}</span></>
                            )}
                          </button>
                        ) : isApproved ? (
                          <span className="inline-flex items-center gap-1 text-[#006c49] text-[11px] font-semibold">
                            <ShieldCheck size={13} /> recorded
                          </span>
                        ) : isNeeds || isQuarantined ? (
                          <span
                            className="text-[11px] text-red-700 font-medium cursor-help"
                            title={
                              m.allowed_candidates.length > 0
                                ? `No confident match. Nearest canonical SKUs (for manual review): ${m.allowed_candidates.join(', ')}`
                                : 'No confident match — held for manual review.'
                            }
                          >
                            Manual review
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-[#76777d] text-[11px]">
                            <CheckCircle size={12} /> auto
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={5} className="p-6 text-center text-[#76777d]">
                      No SKU resolutions matched the filter.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Resolution status (real counts — no fabricated dollars) */}
        <div className="lg:col-span-4 flex flex-col">
          <div className="bg-white border border-[#e2e8f0] rounded-xl p-5 shadow-sm flex flex-col justify-between h-full relative overflow-hidden">
            <div>
              <h3 className="text-xs font-bold text-[#0d1c2d] uppercase tracking-wider mb-2">
                Attribution Readiness
              </h3>
              <p className="text-xs text-[#45464d] leading-normal">
                Records held out of the canonical tables until resolved. Their spend/revenue is
                excluded from attribution — the engine never optimizes on quarantined data.
              </p>
            </div>

            <div className="my-6 relative min-h-[140px] flex items-center justify-center bg-[#f8f9ff] rounded-lg border border-[#c6c6cd]/50 border-dashed overflow-hidden">
              {unresolved > 0 ? (
                <div className="text-center z-10">
                  <div className="text-3xl font-bold font-headline-xl text-amber-600">{unresolved}</div>
                  <div className="text-[10px] text-[#45464d] tracking-wide font-semibold uppercase mt-1">
                    SKU{unresolved === 1 ? '' : 's'} awaiting human review
                  </div>
                  <div className="text-[11px] text-[#76777d] mt-2 font-data-mono">
                    {needsApproval} needs-approval · {quarantinedSkus} quarantined
                  </div>
                </div>
              ) : (
                <div className="text-center z-10 max-w-[200px]">
                  <CheckCircle size={32} className="text-green-600 mx-auto mb-2" />
                  <div className="text-sm font-bold text-green-700">All SKUs resolved</div>
                  <p className="text-[10px] text-[#45464d] mt-1">Canonical tables ready for the engine.</p>
                </div>
              )}
            </div>

            <div className="flex gap-2.5 items-start mt-1">
              <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider border ${
                unresolved > 0 ? 'bg-amber-50 text-amber-800 border-amber-200' : 'bg-green-50 text-green-800 border-green-200'
              }`}>
                {unresolved > 0 ? 'Action needed' : 'Cleared'}
              </span>
              <p className="text-[11px] text-[#45464d] leading-normal">
                {unresolved > 0
                  ? 'Approve a row to bind it to an allowed canonical SKU — invented SKUs are rejected by the schema.'
                  : 'Every platform product maps to an approved canonical SKU.'}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Data-Quality Ledger — real DQ issues from the ingestion pipeline */}
      <div className="bg-white border border-[#e2e8f0] rounded-xl overflow-hidden shadow-sm">
        <div className="p-4 border-b border-[#e2e8f0] bg-[#f8f9ff]">
          <div className="flex items-center gap-2">
            <FileText size={15} className="text-[#0d1c2d]" />
            <h3 className="text-xs font-bold text-[#0d1c2d] uppercase tracking-wider">
              Data-Quality Ledger
            </h3>
            <span className="text-[11px] text-[#76777d] font-data-mono ml-auto">{data.dq_issues.length} issues</span>
          </div>
          <p className="text-xs text-[#45464d] mt-1">
            Detected data-quality issues and the deterministic resolution applied on ingest
            (flag, impute low-confidence, dedupe, unit-normalize) — never silently dropped.
          </p>
        </div>

        <div className="p-6">
          {data.dq_issues.length === 0 ? (
            <p className="text-xs text-[#45464d]">No data-quality issues detected.</p>
          ) : (
            <div className="relative border-l-2 border-[#e2e8f0] pl-6 ml-3 space-y-6">
              {data.dq_issues.map((i) => {
                const tone = sevTone(i.severity);
                return (
                  <div key={i.issue_id} className="relative group transition-all">
                    <span className={`absolute -left-[31px] top-1 w-3.5 h-3.5 rounded-full bg-white border-2 scale-100 group-hover:scale-110 transition-all ${tone.dot}`} />
                    <div className="flex justify-between items-start gap-4">
                      <div className="space-y-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={`inline-flex px-1.5 py-0.5 rounded text-[9px] font-bold uppercase border ${tone.badge}`}>
                            {i.severity}
                          </span>
                          <h4 className="text-xs font-semibold text-[#0d1c2d]">{humanize(i.issue_type)}</h4>
                          <span className="text-[10px] font-data-mono text-[#76777d]">{i.entity_ref}</span>
                        </div>
                        <p className="text-xs text-[#45464d] leading-normal max-w-4xl">{i.description}</p>
                      </div>
                      <span className="inline-flex items-center px-2 py-0.5 rounded bg-[#eef4ff] text-[#334155] text-[10px] font-semibold font-data-mono shrink-0">
                        {i.resolution}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
