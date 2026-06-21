import { useCallback, useEffect, useState } from 'react';
import {
  Package,
  AlertTriangle,
  CheckCircle,
  Clock,
  Loader2,
  Truck,
  Ban,
} from 'lucide-react';
import { useRecommendation } from '../state/RecommendationContext';
import { PlatformLogo } from './BrandLogo';
import { getInventory, type BuyerInventoryResponse, type BuyerInventoryItem } from '../lib/api';

const urgencyTone = (u: BuyerInventoryItem['urgency']) =>
  u === 'urgent'
    ? { badge: 'bg-red-50 text-red-800 border-red-200', dot: 'bg-red-500', label: 'Reorder urgent', icon: AlertTriangle }
    : u === 'reorder_soon'
    ? { badge: 'bg-amber-50 text-amber-800 border-amber-200', dot: 'bg-amber-500', label: 'Reorder soon', icon: Clock }
    : { badge: 'bg-green-50 text-green-800 border-green-200', dot: 'bg-green-500', label: 'Monitor', icon: CheckCircle };

const fmtDate = (iso: string) => {
  // Parse YYYY-MM-DD as a LOCAL calendar date (new Date('2025-08-03') is UTC midnight,
  // which renders a day early in negative-offset timezones).
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  const d = m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
};

export default function BuyerInventory() {
  const { decision } = useRecommendation();
  const [data, setData] = useState<BuyerInventoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setData(await getInventory());
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

  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 text-[#45464d] text-sm animate-fade-in">
        <Loader2 size={16} className="animate-spin text-[#00714d]" /> Loading inventory snapshot…
      </div>
    );
  }
  if (error && !data) {
    return (
      <div className="bg-[#fee2e2] border border-[#fca5a5] text-[#7f1d1d] rounded-xl p-4 text-sm animate-fade-in">
        <b>Could not reach the inventory API.</b> ({error})
      </div>
    );
  }
  if (!data) return null;

  const atRisk = data.items.filter((i) => i.stockout_risk).length;
  const clean = atRisk === 0;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Module Title */}
      <div className="flex justify-between items-end">
        <div>
          <h2 className="text-2xl font-bold font-headline-lg text-[#0d1c2d] tracking-tight">
            Buyer & Inventory
          </h2>
          <p className="text-sm text-[#45464d] mt-1">
            Replenishment guardrail: a SKU below its lead-time + safety-day cover blocks scale on the
            campaigns that sell it. Inventory snapshot as of {fmtDate(data.snapshot_date)}.
          </p>
        </div>
        <span
          className={`inline-flex items-center gap-1 px-3 py-1 text-xs font-semibold rounded-full border ${
            clean
              ? 'bg-green-50 text-green-800 border-green-200'
              : 'bg-red-50 text-red-800 border-red-200'
          }`}
        >
          {clean ? <CheckCircle size={13} className="text-green-600" /> : <AlertTriangle size={13} />}
          {clean ? 'All SKUs in cover' : `${atRisk} SKU${atRisk === 1 ? '' : 's'} at stockout risk`}
        </span>
      </div>

      {/* SKU cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {data.items.map((it) => {
          const tone = urgencyTone(it.urgency);
          const ToneIcon = tone.icon;
          return (
            <div
              key={it.sku_id}
              className={`bg-white border rounded-xl p-5 shadow-sm transition-all ${
                it.stockout_risk ? 'border-red-200' : 'border-[#e2e8f0] hover:border-[#00714d]/30'
              }`}
            >
              <div className="flex justify-between items-start mb-4">
                <div className="flex items-center gap-2.5 min-w-0">
                  <Package size={18} className={it.stockout_risk ? 'text-red-600' : 'text-[#76777d]'} />
                  <div className="min-w-0">
                    <h3 className="text-sm font-bold text-[#0d1c2d] truncate">{it.product_name}</h3>
                    <span className="text-[11px] text-[#76777d] font-data-mono">{it.sku_id}</span>
                  </div>
                </div>
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border shrink-0 ${tone.badge}`}>
                  <ToneIcon size={11} /> {tone.label}
                </span>
              </div>

              {/* Days of cover headline */}
              <div className="flex items-end justify-between mb-4">
                <div>
                  <div className="text-[10px] text-[#76777d] uppercase tracking-wider font-semibold">Days of cover</div>
                  <div className={`text-3xl font-bold font-headline-xl ${it.stockout_risk ? 'text-red-600' : 'text-[#0d1c2d]'}`}>
                    {it.days_of_cover.toFixed(0)}
                    <span className="text-sm font-semibold text-[#76777d] ml-1">days</span>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-[10px] text-[#76777d] uppercase tracking-wider font-semibold">Est. stockout</div>
                  <div className={`text-sm font-bold font-data-mono ${it.stockout_risk ? 'text-red-700' : 'text-[#0d1c2d]'}`}>
                    {fmtDate(it.estimated_stockout_date)}
                  </div>
                </div>
              </div>

              {/* Metrics grid */}
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs border-t border-[#e2e8f0]/60 pt-3">
                <div className="flex justify-between">
                  <span className="text-[#45464d]">Units on hand</span>
                  <span className="font-bold font-data-mono text-[#0d1c2d]">{it.units_on_hand.toLocaleString()}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#45464d]">Daily demand</span>
                  <span className="font-bold font-data-mono text-[#0d1c2d]">{it.forecast_daily_demand.toLocaleString(undefined, { maximumFractionDigits: 0 })}/d</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#45464d]">Lead + safety</span>
                  <span className="font-bold font-data-mono text-[#0d1c2d]">{it.lead_time_days} + {it.safety_days}d</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#45464d]">Suggested reorder</span>
                  <span className={`font-bold font-data-mono ${it.reorder_qty > 0 ? 'text-[#00714d]' : 'text-[#76777d]'}`}>
                    {it.reorder_qty > 0 ? `${it.reorder_qty.toLocaleString()} units` : '—'}
                  </span>
                </div>
              </div>

              {/* No-scale + linked campaigns */}
              <div className="mt-4 pt-3 border-t border-[#e2e8f0]/60 space-y-2.5">
                {it.no_scale ? (
                  <div className="flex items-center gap-1.5 text-[11px] font-semibold text-red-700">
                    <Ban size={13} /> Inventory no-scale — linked campaigns pinned at current spend
                  </div>
                ) : (
                  <div className="flex items-center gap-1.5 text-[11px] font-semibold text-[#006c49]">
                    <Truck size={13} /> Cleared to scale — sufficient cover
                  </div>
                )}
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[10px] text-[#76777d] uppercase tracking-wider font-semibold mr-1">Sells via</span>
                  {it.linked_campaigns.map((c) => (
                    <span
                      key={c.campaign_id}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-[#eef4ff] border border-[#c6c6cd]/40 text-[10px] font-semibold text-[#334155]"
                      title={c.campaign_id}
                    >
                      <PlatformLogo platform={c.platform} />
                      {c.campaign_name}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Reorder policy footnote */}
      <div className="bg-white border border-[#e2e8f0] rounded-xl p-4 shadow-sm text-[11px] text-[#45464d] leading-relaxed">
        <span className="font-semibold text-[#0d1c2d]">Reorder policy:</span> {data.reorder_policy} Suggested
        quantities are a planning aid, not a committed purchase order — this is a thin buyer handoff, not a
        replenishment system. The inventory no-scale flag is the same one the optimizer enforces, so the buyer
        view and the recommendation never disagree.
      </div>
    </div>
  );
}
