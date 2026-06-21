import { useMemo, useRef, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from 'react';
import { Loader2, Info, TrendingDown, AlertTriangle } from 'lucide-react';
import { useRecommendation } from '../state/RecommendationContext';
import type { CampaignLine } from '../lib/api';
import { PlatformLogo } from './BrandLogo';

// ---- formatting helpers ---------------------------------------------------
const money = (n: number) =>
  Math.abs(n) >= 1_000_000
    ? `$${(n / 1_000_000).toFixed(2)}M`
    : Math.abs(n) >= 1_000
    ? `$${Math.round(n / 1_000)}k`
    : `$${Math.round(n)}`;

const pct = (n: number) => `${Math.round(n * 100)}%`;
const shortName = (n: string) => n.replace(/^(Google|Meta)\s*[—-]\s*/, '');

function platformLogo(platform: string) {
  const p = platform.toLowerCase();
  const key = p.includes('google') ? 'google' : p.includes('meta') ? 'meta' : p.includes('shopify') ? 'shopify' : '';
  if (!key) return <span className="text-[10px] font-bold text-[#76777d]">·</span>;
  return <PlatformLogo platform={key} className="w-3.5 h-3.5" />;
}

// forecast_model is "xgboost_quantile" | "baseline_same_weekday" | "baseline_trailing_14d"
function modelInfo(model: string): { label: string; sub: string; conformal: boolean } {
  if (model.startsWith('xgboost')) return { label: 'XGBoost', sub: 'quantile', conformal: true };
  if (model.startsWith('baseline'))
    return { label: 'Baseline', sub: model.replace('baseline_', '').replace(/_/g, '-'), conformal: false };
  return { label: model || '—', sub: '', conformal: false };
}

// even tick values from hi down to lo (inclusive), n ticks
function ticks(lo: number, hi: number, n = 5): number[] {
  if (!isFinite(lo) || !isFinite(hi) || hi <= lo) return [hi, lo];
  return Array.from({ length: n }, (_, i) => hi - ((hi - lo) * i) / (n - 1));
}

const PCTS: number[] = [];
for (let p = -20; p <= 20; p += 2) PCTS.push(p);

// local marginal-(gross)ROAS estimate as spend moves by p%, from the engine's local
// quadratic response params: m(Δ) = slope + 2·quad·Δspend  (Δspend = p% · current).
const marginalAt = (l: CampaignLine, p: number) =>
  l.response_slope + 2 * l.response_quad * (p / 100) * l.current_spend;

// CM (contribution-margin) units — the primary decision lens. Pure unit conversion of
// the engine's already-derived marginal by the backend-supplied per-line margin; the
// economics live in the engine, not here. Break-even = 1.0×, hurdle = safety multiple.
const marginalCmAt = (l: CampaignLine, p: number) => l.contribution_margin_rate * marginalAt(l, p);

// local revenue response: the quadratic whose derivative is `marginalAt`. This is the
// actual spend-response *curve* (bowed) — diminishing returns show as the curve rolling
// over. R(Δ) = current_revenue + slope·Δ + quad·Δ²  (Δspend = p% · current).
const revenueAt = (l: CampaignLine, p: number) => {
  const dx = (p / 100) * l.current_spend;
  return l.current_revenue + l.response_slope * dx + l.response_quad * dx * dx;
};

// interior revenue peak (marginal = 0) as a % move, if the local fit is concave (quad<0)
// and the turning point sits in-range. Null otherwise (convex or monotone within ±20%).
const revenuePeakPct = (l: CampaignLine): number | null => {
  if (l.response_quad >= 0 || l.current_spend <= 0) return null;
  return (-l.response_slope / (2 * l.response_quad) / l.current_spend) * 100;
};

// visual x-padding: axis runs to ±25% but the supported decision range stays ±20%.
const XAX = 25;

// pixel paddings of the SVG plot area inside each chart wrapper (match the pl-/pr- classes)
const PLOT = { left: 48, right: 8 };

// map a mouse event to a [0,1] fraction across the plot's horizontal data area
function hoverFraction(e: ReactMouseEvent, el: HTMLElement): number {
  const r = el.getBoundingClientRect();
  return Math.max(0, Math.min(1, (e.clientX - r.left - PLOT.left) / (r.width - PLOT.left - PLOT.right)));
}

// small dark tooltip pinned to the top of a chart, horizontally clamped inside it
function ChartTooltip({ xPct, children }: { xPct: number; children: ReactNode }) {
  return (
    <div
      className="pointer-events-none absolute top-1 z-10 -translate-x-1/2 rounded-md bg-[#0d1c2d] text-white text-[10px] font-semibold px-2 py-1 shadow-lg whitespace-nowrap leading-tight"
      style={{ left: `clamp(64px, ${xPct}%, calc(100% - 64px))` }}
    >
      {children}
    </div>
  );
}

// ===========================================================================
// Chart 1 — BAU revenue forecast band (P10 / P50 / P90) across campaigns
// ===========================================================================
function ForecastBandChart({
  lines,
  selectedId,
  onSelect,
}: {
  lines: CampaignLine[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const domainMax = Math.max(1, ...lines.map((l) => l.forecast_p90));
  const yTicks = ticks(0, domainMax);
  const W = 500;
  const H = 250;
  const slot = W / lines.length;
  const sy = (v: number) => H - (v / domainMax) * H;

  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ idx: number; xPct: number } | null>(null);
  const onMove = (e: ReactMouseEvent) => {
    const el = wrapRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const idx = Math.max(0, Math.min(lines.length - 1, Math.floor(hoverFraction(e, el) * lines.length)));
    setHover({ idx, xPct: ((e.clientX - r.left) / r.width) * 100 });
  };
  const hl = hover ? lines[hover.idx] : null;
  const hlInfo = hl ? modelInfo(hl.forecast_model) : null;

  return (
    <div
      ref={wrapRef}
      className="flex-1 relative w-full h-full mt-4 bg-transparent"
      onMouseMove={onMove}
      onMouseLeave={() => setHover(null)}
    >
      {hl && hlInfo && (
        <ChartTooltip xPct={hover!.xPct}>
          <div className="font-bold mb-0.5">{shortName(hl.campaign_name)}</div>
          <div>P50 {money(hl.forecast_p50)} · {hlInfo.label}</div>
          <div className="text-[#9aa6bd]">P10–P90 {money(hl.forecast_p10)} – {money(hl.forecast_p90)}</div>
        </ChartTooltip>
      )}
      {/* y gridlines + labels */}
      <div className="absolute inset-0 flex flex-col justify-between pt-2 pb-12 pl-12 pr-2">
        {yTicks.map((t, i) => (
          <div key={i} className="border-t border-[#e2e8f0]/50 w-full relative">
            <span className="absolute -left-11 -top-2 text-[10px] font-semibold font-data-mono text-[#76777d]">
              {money(t)}
            </span>
          </div>
        ))}
      </div>

      <svg
        className="absolute inset-0 w-full h-full pb-12 pl-12 pr-2 pt-2"
        preserveAspectRatio="none"
        viewBox={`0 0 ${W} ${H}`}
      >
        {hover && (
          <rect x={hover.idx * slot} y={0} width={slot} height={H} fill="#0d1c2d" opacity={0.05} />
        )}
        {lines.map((l, i) => {
          const cx = i * slot + slot / 2;
          const barW = slot * 0.34;
          const isSel = l.campaign_id === selectedId;
          const isHov = hover?.idx === i;
          const info = modelInfo(l.forecast_model);
          const p50y = sy(l.forecast_p50);
          const p10y = sy(l.forecast_p10);
          const p90y = sy(l.forecast_p90);
          return (
            <g key={l.campaign_id} onClick={() => onSelect(l.campaign_id)} style={{ cursor: 'pointer' }}>
              {/* P50 bar */}
              <rect
                x={cx - barW / 2}
                y={p50y}
                width={barW}
                height={Math.max(0, H - p50y)}
                fill={isSel ? '#006c49' : info.conformal ? '#3bc6c2' : '#9aa6bd'}
                opacity={isSel ? 0.95 : isHov ? 0.8 : 0.55}
              />
              {/* P10–P90 whisker */}
              <line x1={cx} y1={p10y} x2={cx} y2={p90y} stroke="#131b2e" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
              <line x1={cx - 5} y1={p10y} x2={cx + 5} y2={p10y} stroke="#131b2e" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
              <line x1={cx - 5} y1={p90y} x2={cx + 5} y2={p90y} stroke="#131b2e" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
            </g>
          );
        })}
      </svg>

      {/* x labels — wrap (don't truncate) so every channel is readable, clickable */}
      <div className="absolute bottom-0 left-12 right-2 h-11 flex items-start text-[9px] font-semibold text-[#76777d]">
        {lines.map((l) => (
          <button
            type="button"
            key={l.campaign_id}
            onClick={() => onSelect(l.campaign_id)}
            className={`flex-1 text-center px-0.5 leading-[1.15] break-words hover:text-[#006c49] transition-colors ${l.campaign_id === selectedId ? 'text-[#006c49] font-bold' : ''}`}
            title={l.campaign_name}
          >
            {shortName(l.campaign_name)}
          </button>
        ))}
      </div>
    </div>
  );
}

// ===========================================================================
// Chart 2 — Local spend-response estimate in CM units (marginal CM ROAS vs spend)
// ===========================================================================
function SpendResponseChart({ line, hurdle, breakEven }: { line: CampaignLine; hurdle: number; breakEven: number }) {
  const W = 500;
  const H = 250;
  const vals = PCTS.map((p) => marginalCmAt(line, p));
  const lo = Math.min(0, breakEven, ...vals);
  const hi = Math.max(hurdle, ...vals) * 1.08;
  const yTicks = ticks(lo, hi);
  // axis padded to ±25% so the recommended marker at the ±20% bound isn't clipped;
  // the response line + decisions stay within the supported ±20% range.
  const sx = (p: number) => ((p + XAX) / (2 * XAX)) * W;
  const sy = (v: number) => H - ((v - lo) / (hi - lo)) * H;

  const poly = PCTS.map((p) => `${sx(p)},${sy(marginalCmAt(line, p))}`).join(' ');
  const recPct = Math.max(-20, Math.min(20, line.delta_pct));

  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ pct: number; xPct: number } | null>(null);
  const onMove = (e: ReactMouseEvent) => {
    const el = wrapRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const pct = Math.max(-20, Math.min(20, -XAX + hoverFraction(e, el) * 2 * XAX));
    setHover({ pct, xPct: ((e.clientX - r.left) / r.width) * 100 });
  };
  const hCm = hover ? marginalCmAt(line, hover.pct) : 0;

  return (
    <div
      ref={wrapRef}
      className="flex-1 relative w-full h-full mt-4 bg-transparent"
      onMouseMove={onMove}
      onMouseLeave={() => setHover(null)}
    >
      {hover && (
        <ChartTooltip xPct={hover.xPct}>
          <div className="font-bold mb-0.5">{hover.pct >= 0 ? '+' : ''}{hover.pct.toFixed(0)}% spend</div>
          <div>marginal CM {hCm.toFixed(2)}×</div>
          <div className="text-[#9aa6bd]">gross {marginalAt(line, hover.pct).toFixed(2)}×</div>
        </ChartTooltip>
      )}
      <div className="absolute inset-0 flex flex-col justify-between pt-2 pb-7 pl-12 pr-2">
        {yTicks.map((t, i) => (
          <div key={i} className="border-t border-[#e2e8f0]/50 w-full relative">
            <span className="absolute -left-11 -top-2 text-[10px] font-semibold font-data-mono text-[#76777d]">
              {t.toFixed(2)}×
            </span>
          </div>
        ))}
      </div>

      <svg
        className="absolute inset-0 w-full h-full pb-7 pl-12 pr-2 pt-2"
        preserveAspectRatio="none"
        viewBox={`0 0 ${W} ${H}`}
      >
        {/* break-even (1.00×) → safety-hurdle (≈1.05×) band — they're only ~5% apart, so
            one shaded band reads far better than two near-overlapping lines */}
        <rect x={0} y={sy(hurdle)} width={W} height={Math.max(1, sy(breakEven) - sy(hurdle))}
              fill="#ba1a1a" opacity={0.08} />
        <line x1={0} y1={sy(breakEven)} x2={W} y2={sy(breakEven)} stroke="#76777d" strokeWidth={1} vectorEffect="non-scaling-stroke" />
        <line x1={0} y1={sy(hurdle)} x2={W} y2={sy(hurdle)} stroke="#ba1a1a" strokeWidth={1.5} strokeDasharray="4,4" vectorEffect="non-scaling-stroke" opacity={0.8} />

        {/* supported-range guides at ±20% (axis extends to ±25%) */}
        <line x1={sx(-20)} y1={0} x2={sx(-20)} y2={H} stroke="#e2e8f0" strokeWidth={1} vectorEffect="non-scaling-stroke" />
        <line x1={sx(20)} y1={0} x2={sx(20)} y2={H} stroke="#e2e8f0" strokeWidth={1} vectorEffect="non-scaling-stroke" />

        {/* hover crosshair */}
        {hover && (
          <>
            <line x1={sx(hover.pct)} y1={0} x2={sx(hover.pct)} y2={H} stroke="#0d1c2d" strokeWidth={1} strokeDasharray="2,2" opacity={0.4} vectorEffect="non-scaling-stroke" />
            <circle cx={sx(hover.pct)} cy={sy(hCm)} r={4} fill="#0d1c2d" stroke="#fff" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
          </>
        )}

        {/* current spend marker (0%) and recommended marker */}
        <line x1={sx(0)} y1={0} x2={sx(0)} y2={H} stroke="#76777d" strokeWidth={1.2} strokeDasharray="3,3" vectorEffect="non-scaling-stroke" />
        <line x1={sx(recPct)} y1={0} x2={sx(recPct)} y2={H} stroke="#006c49" strokeWidth={1.6} vectorEffect="non-scaling-stroke" />

        {/* marginal CM ROAS response curve */}
        <polyline points={poly} fill="none" stroke="#131b2e" strokeWidth={2.5} vectorEffect="non-scaling-stroke" />
        <circle cx={sx(0)} cy={sy(marginalCmAt(line, 0))} r={4} fill="#fff" stroke="#76777d" strokeWidth={2} vectorEffect="non-scaling-stroke" />
        <circle cx={sx(recPct)} cy={sy(marginalCmAt(line, recPct))} r={4.5} fill="#fff" stroke="#006c49" strokeWidth={2.5} vectorEffect="non-scaling-stroke" />
      </svg>

      <div className="absolute bottom-0 left-12 right-2 flex justify-between text-[10px] font-semibold font-data-mono text-[#76777d]">
        {[-25, -20, 0, 20, 25].map((p) => (
          <span key={p} className={p === 0 ? 'text-[#0d1c2d] font-bold' : Math.abs(p) === 20 ? 'text-[#45464d]' : 'text-[#aeb0b6]'}>
            {p > 0 ? '+' : ''}
            {p}%
          </span>
        ))}
      </div>
    </div>
  );
}

// ===========================================================================
// Chart 2b — Revenue spend-response *curve* (the bowed quadratic itself)
// ===========================================================================
function RevenueResponseChart({ line, peakPct }: { line: CampaignLine; peakPct: number | null }) {
  const W = 500;
  const H = 250;
  const vals = PCTS.map((p) => revenueAt(line, p));
  let lo = Math.min(...vals);
  let hi = Math.max(...vals);
  const pad = Math.max(1, (hi - lo) * 0.1);
  lo -= pad;
  hi += pad;
  const yTicks = ticks(lo, hi);
  const sx = (p: number) => ((p + XAX) / (2 * XAX)) * W;
  const sy = (v: number) => H - ((v - lo) / (hi - lo)) * H;

  const poly = PCTS.map((p) => `${sx(p)},${sy(revenueAt(line, p))}`).join(' ');
  const recPct = Math.max(-20, Math.min(20, line.delta_pct));
  const peakInRange = peakPct !== null && peakPct >= -20 && peakPct <= 20;

  const wrapRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ pct: number; xPct: number } | null>(null);
  const onMove = (e: ReactMouseEvent) => {
    const el = wrapRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const pct = Math.max(-20, Math.min(20, -XAX + hoverFraction(e, el) * 2 * XAX));
    setHover({ pct, xPct: ((e.clientX - r.left) / r.width) * 100 });
  };
  const hRev = hover ? revenueAt(line, hover.pct) : 0;
  const hDelta = hRev - line.current_revenue;

  return (
    <div
      ref={wrapRef}
      className="flex-1 relative w-full h-full mt-4 bg-transparent"
      onMouseMove={onMove}
      onMouseLeave={() => setHover(null)}
    >
      {hover && (
        <ChartTooltip xPct={hover.xPct}>
          <div className="font-bold mb-0.5">{hover.pct >= 0 ? '+' : ''}{hover.pct.toFixed(0)}% spend</div>
          <div>revenue {money(hRev)}</div>
          <div className={hDelta >= 0 ? 'text-[#7ee0b8]' : 'text-[#ffb4ab]'}>
            {hDelta >= 0 ? '+' : ''}{money(hDelta)} vs today
          </div>
        </ChartTooltip>
      )}
      <div className="absolute inset-0 flex flex-col justify-between pt-2 pb-7 pl-12 pr-2">
        {yTicks.map((t, i) => (
          <div key={i} className="border-t border-[#e2e8f0]/50 w-full relative">
            <span className="absolute -left-11 -top-2 text-[10px] font-semibold font-data-mono text-[#76777d]">
              {money(t)}
            </span>
          </div>
        ))}
      </div>

      <svg
        className="absolute inset-0 w-full h-full pb-7 pl-12 pr-2 pt-2"
        preserveAspectRatio="none"
        viewBox={`0 0 ${W} ${H}`}
      >
        {/* supported-range guides at ±20% (axis extends to ±25%) */}
        <line x1={sx(-20)} y1={0} x2={sx(-20)} y2={H} stroke="#e2e8f0" strokeWidth={1} vectorEffect="non-scaling-stroke" />
        <line x1={sx(20)} y1={0} x2={sx(20)} y2={H} stroke="#e2e8f0" strokeWidth={1} vectorEffect="non-scaling-stroke" />

        {/* hover crosshair */}
        {hover && (
          <>
            <line x1={sx(hover.pct)} y1={0} x2={sx(hover.pct)} y2={H} stroke="#0d1c2d" strokeWidth={1} strokeDasharray="2,2" opacity={0.4} vectorEffect="non-scaling-stroke" />
            <circle cx={sx(hover.pct)} cy={sy(hRev)} r={4} fill="#0d1c2d" stroke="#fff" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
          </>
        )}

        {/* saturation peak (where marginal = 0), if it falls in range */}
        {peakInRange && (
          <line x1={sx(peakPct as number)} y1={0} x2={sx(peakPct as number)} y2={H} stroke="#e0a93b" strokeWidth={1.2} strokeDasharray="4,3" vectorEffect="non-scaling-stroke" />
        )}

        {/* current spend marker (0%) and recommended marker */}
        <line x1={sx(0)} y1={0} x2={sx(0)} y2={H} stroke="#76777d" strokeWidth={1.2} strokeDasharray="3,3" vectorEffect="non-scaling-stroke" />
        <line x1={sx(recPct)} y1={0} x2={sx(recPct)} y2={H} stroke="#006c49" strokeWidth={1.6} vectorEffect="non-scaling-stroke" />

        {/* revenue response curve */}
        <polyline points={poly} fill="none" stroke="#131b2e" strokeWidth={2.5} vectorEffect="non-scaling-stroke" />
        {peakInRange && (
          <circle cx={sx(peakPct as number)} cy={sy(revenueAt(line, peakPct as number))} r={3.5} fill="#e0a93b" stroke="#fff" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
        )}
        <circle cx={sx(0)} cy={sy(revenueAt(line, 0))} r={4} fill="#fff" stroke="#76777d" strokeWidth={2} vectorEffect="non-scaling-stroke" />
        <circle cx={sx(recPct)} cy={sy(revenueAt(line, recPct))} r={4.5} fill="#fff" stroke="#006c49" strokeWidth={2.5} vectorEffect="non-scaling-stroke" />
      </svg>

      <div className="absolute bottom-0 left-12 right-2 flex justify-between text-[10px] font-semibold font-data-mono text-[#76777d]">
        {[-25, -20, 0, 20, 25].map((p) => (
          <span key={p} className={p === 0 ? 'text-[#0d1c2d] font-bold' : Math.abs(p) === 20 ? 'text-[#45464d]' : 'text-[#aeb0b6]'}>
            {p > 0 ? '+' : ''}
            {p}%
          </span>
        ))}
      </div>
    </div>
  );
}

// ===========================================================================
export default function ForecastResponse() {
  const { rec, loading, solving, error } = useRecommendation();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [respMode, setRespMode] = useState<'revenue' | 'marginal'>('revenue');

  const selected = useMemo<CampaignLine | null>(() => {
    if (!rec) return null;
    return rec.lines.find((l) => l.campaign_id === selectedId) ?? rec.lines[0] ?? null;
  }, [rec, selectedId]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-[#45464d] text-sm animate-fade-in">
        <Loader2 size={16} className="animate-spin text-[#00714d]" /> Loading forecasts…
      </div>
    );
  }
  if (error && !rec) {
    return (
      <div className="bg-[#fee2e2] border border-[#fca5a5] text-[#7f1d1d] rounded-xl p-4 text-sm animate-fade-in">
        <b>Could not reach the decision API.</b> Is the backend running on <code>:8000</code>? ({error})
      </div>
    );
  }
  if (!rec || !selected) return null;

  const ic = rec.interval_calibration;
  const nHeuristic = rec.lines.filter((l) => !modelInfo(l.forecast_model).conformal).length;
  const selInfo = modelInfo(selected.forecast_model);
  const selSpread = selected.forecast_p50 > 0
    ? (selected.forecast_p90 - selected.forecast_p10) / selected.forecast_p50
    : 0;

  // CM-unit decision context for the selected campaign (thresholds are constant).
  const cmHurdle = rec.marginal_cm_hurdle || 1.05;
  const cmBreakEven = rec.cm_break_even || 1.0;
  const selMaxCm = Math.max(...PCTS.map((p) => marginalCmAt(selected, p)));
  const atMoveBound = Math.abs(selected.delta_pct) >= 19.9;
  const decisionNote =
    selMaxCm < cmBreakEven
      ? 'Below contribution break-even across observed support — reduce to the permitted movement floor.'
      : selMaxCm < cmHurdle
      ? 'Below the marginal safety hurdle across observed support — hold or reduce.'
      : null;

  // revenue-curve shape narrative (only meaningful in the curve view)
  const selPeak = revenuePeakPct(selected);
  const curveNote =
    selPeak !== null && selPeak >= -20 && selPeak <= 20
      ? `Diminishing returns: local revenue peaks near ${selPeak >= 0 ? '+' : ''}${Math.round(selPeak)}% spend (marginal hits zero), so scaling past it adds spend faster than contribution.`
      : selected.response_quad < 0 && selPeak !== null && selPeak < -20
      ? 'Past its local peak — calibrated revenue / day falls as spend rises across the range, so the optimizer reduces spend.'
      : selected.response_quad < 0
      ? 'Concave within range — still rising, with the marginal flattening toward saturation beyond +20%.'
      : 'Accelerating within range — marginal return rises with spend across the observed ±20% band.';

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2.5 mb-1.5">
          <span className="px-2 py-0.5 rounded bg-[#eef4ff] text-[#0f172a] font-semibold text-[10px] uppercase tracking-wider border border-[#dae2fd]">
            Module M2
          </span>
          <h2 className="text-2xl font-bold font-headline-lg text-[#0d1c2d] tracking-tight">Forecast &amp; Response</h2>
        </div>
        <p className="text-xs text-[#45464d] flex items-center gap-1.5 font-medium">
          <span className="w-1.5 h-1.5 rounded-full bg-[#006c49]" />
          Selected-model 7-day BAU forecasts with deployed uncertainty bands and local marginal CM-return
          estimates. The optimizer uses P50 &amp; marginal CM ROAS; uncertainty is shown for human review, not risk sizing.
          {solving && (
            <span className="inline-flex items-center gap-1 text-[#00714d]">
              <Loader2 size={11} className="animate-spin" /> resolving…
            </span>
          )}
        </p>
      </div>

      {/* Top charts */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* Forecast band */}
        <div className="bg-white border border-[#e2e8f0] rounded-xl p-5 flex flex-col h-[440px] shadow-sm">
          <div>
            <h3 className="text-sm font-bold text-[#0d1c2d]">Revenue forecast — next 7 days</h3>
            <p className="text-xs text-[#76777d] mt-1 leading-relaxed">
              P50 bar with P10–P90 whisker per campaign. Band is{' '}
              <span className="font-semibold text-[#0d1c2d]">mixed</span>: conformal-calibrated for XGBoost champions,
              {nHeuristic > 0 ? ` operational ±20% heuristic for ${nHeuristic} baseline champion${nHeuristic > 1 ? 's' : ''}.` : ' all champions are XGBoost.'}
            </p>
          </div>
          <ForecastBandChart lines={rec.lines} selectedId={selected.campaign_id} onSelect={setSelectedId} />
          <div className="flex items-center justify-between gap-3 mt-3 pt-3 border-t border-[#e2e8f0]/40">
            <div className="flex items-center gap-4">
              <span className="flex items-center gap-1.5 text-[10px] text-[#45464d] font-semibold">
                <span className="w-3 h-3 rounded-sm bg-[#3bc6c2] inline-block" /> XGBoost P50
              </span>
              <span className="flex items-center gap-1.5 text-[10px] text-[#45464d] font-semibold">
                <span className="w-3 h-3 rounded-sm bg-[#9aa6bd] inline-block" /> Baseline P50
              </span>
              <span className="flex items-center gap-1.5 text-[10px] text-[#45464d] font-semibold">
                <span className="w-2.5 h-[2px] bg-[#131b2e] inline-block" /> P10–P90
              </span>
            </div>
            {ic?.n_calibration > 0 && (
              <span className="text-[10px] text-[#76777d]" title="Coverage is measured on the XGBoost conformal subset only; baseline ±20% bands are an uncalibrated operational heuristic.">
                XGBoost conformal coverage {pct(ic.calibration_coverage_calibrated)} vs {pct(ic.target_coverage)} target
              </span>
            )}
          </div>
        </div>

        {/* Local spend-response — curve (revenue) ↔ marginal (CM ROAS) */}
        <div className="bg-white border border-[#e2e8f0] rounded-xl p-5 flex flex-col h-[440px] shadow-sm">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 className="text-sm font-bold text-[#0d1c2d]">
                {respMode === 'revenue' ? 'Revenue / day' : 'Marginal CM ROAS'} — {shortName(selected.campaign_name)}
              </h3>
              <p className="text-xs text-[#76777d] mt-1 leading-relaxed">
                {respMode === 'revenue' ? (
                  <>
                    Daily calibrated <span className="font-semibold text-[#0d1c2d]">revenue / day</span> as spend moves ±20% around the
                    current daily budget (0% = today). The bow is diminishing returns — a local estimate within observed support, not a
                    fitted saturation model.
                  </>
                ) : (
                  <>
                    Next-dollar <span className="font-semibold text-[#0d1c2d]">contribution</span> return (the curve's slope). Break-even
                    = 1.00×, safety hurdle = {cmHurdle.toFixed(2)}×. Local estimate within observed support.
                  </>
                )}
              </p>
            </div>
            <div className="flex shrink-0 rounded-lg border border-[#e2e8f0] overflow-hidden text-[11px] font-semibold">
              <button
                type="button"
                onClick={() => setRespMode('revenue')}
                className={`px-2.5 py-1 transition-colors ${respMode === 'revenue' ? 'bg-[#0d1c2d] text-white' : 'bg-white text-[#45464d] hover:bg-[#f1f5f9]'}`}
              >
                Curve
              </button>
              <button
                type="button"
                onClick={() => setRespMode('marginal')}
                className={`px-2.5 py-1 border-l border-[#e2e8f0] transition-colors ${respMode === 'marginal' ? 'bg-[#0d1c2d] text-white' : 'bg-white text-[#45464d] hover:bg-[#f1f5f9]'}`}
              >
                Marginal
              </button>
            </div>
          </div>
          {respMode === 'marginal' && decisionNote && (
            <div className="mt-2 flex items-start gap-2 bg-red-50 border border-red-200 text-red-800 rounded-lg px-3 py-2 text-[11px] font-medium">
              <TrendingDown size={13} className="mt-0.5 shrink-0" />
              <span>{decisionNote}</span>
            </div>
          )}
          {respMode === 'revenue' && (
            <div className="mt-2 flex items-start gap-2 bg-[#fff8ec] border border-[#f0d8a8] text-[#8a5a00] rounded-lg px-3 py-2 text-[11px] font-medium">
              <Info size={13} className="mt-0.5 shrink-0" />
              <span>{curveNote}</span>
            </div>
          )}
          {respMode === 'revenue' ? (
            <RevenueResponseChart line={selected} peakPct={selPeak} />
          ) : (
            <SpendResponseChart line={selected} hurdle={cmHurdle} breakEven={cmBreakEven} />
          )}
          <div className="flex items-center justify-between gap-3 mt-3 pt-3 border-t border-[#e2e8f0]/40">
            <div className="flex items-center gap-4">
              <span className="flex items-center gap-1.5 text-[10px] text-[#45464d] font-semibold">
                <span className="w-1.5 h-3 border-l border-dashed border-[#76777d] inline-block" /> Current
              </span>
              <span className="flex items-center gap-1.5 text-[10px] text-[#45464d] font-semibold">
                <span className="w-1.5 h-3 border-l-2 border-[#006c49] inline-block" /> Recommended
                {atMoveBound && (
                  <span className="text-[#006c49] font-bold"> · {selected.delta_pct > 0 ? '+' : ''}{Math.round(selected.delta_pct)}% movement limit
                    {Math.abs(selected.delta_pct) > 20.5 ? ' (marker clamped to ±20% curve support)' : ''}
                  </span>
                )}
              </span>
            </div>
            {respMode === 'marginal' ? (
              <span className="flex items-center gap-1.5 text-[10px] text-red-700 font-semibold" title="Contribution break-even (1.00×) up to the safety hurdle; the optimizer scales only campaigns whose marginal CM ROAS clears the hurdle.">
                <span className="w-2.5 h-2.5 rounded-sm bg-[#ba1a1a]/15 border border-[#ba1a1a]/40 inline-block" />
                break-even 1.00× → hurdle {cmHurdle.toFixed(2)}×
              </span>
            ) : selPeak !== null && selPeak >= -20 && selPeak <= 20 ? (
              <span className="flex items-center gap-1.5 text-[10px] text-[#b45309] font-semibold" title="Spend level where the next dollar stops adding revenue (marginal = 0).">
                <span className="w-2.5 h-[2px] border-t border-dashed border-[#e0a93b] inline-block" /> revenue peak ≈ {selPeak >= 0 ? '+' : ''}{Math.round(selPeak)}%
              </span>
            ) : (
              <span className="text-[10px] text-[#76777d] font-medium">x: spend Δ vs current daily budget · ±20% support</span>
            )}
          </div>
        </div>
      </div>

      {/* Selected-campaign summary strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <SummaryCard label="Champion model" value={`${selInfo.label}${selInfo.sub ? ` · ${selInfo.sub}` : ''}`}
          sub={selInfo.conformal ? 'conformal-calibrated band' : '±20% heuristic band'} />
        <SummaryCard label="Forecast P50 (7d)" value={money(selected.forecast_p50)}
          sub={`P10–P90 ${money(selected.forecast_p10)} – ${money(selected.forecast_p90)} (±${Math.round(selSpread * 50)}%)`} />
        <SummaryCard label="Marginal CM ROAS" value={`${selected.marginal_cm_roas.toFixed(2)}×`}
          sub={`hurdle ${cmHurdle.toFixed(2)}× · downside ${selected.marginal_cm_roas_downside.toFixed(2)}× · gross ${selected.marginal_roas.toFixed(2)}×`}
          danger={selected.marginal_cm_roas < cmHurdle} />
        <SummaryCard label="Calibrated vs reported" value={`${selected.calibrated_roas_current.toFixed(2)}×`}
          sub={`platform-reported ${selected.platform_roas_current.toFixed(2)}× · incr ${selected.incrementality.toFixed(2)}`} />
      </div>

      {/* Model breakdown table */}
      <div className="bg-white border border-[#e2e8f0] rounded-xl overflow-hidden shadow-sm">
        <div className="p-4 border-b border-[#e2e8f0] flex flex-col sm:flex-row sm:items-center justify-between gap-2 bg-[#f8f9ff]">
          <div>
            <h3 className="text-xs font-bold text-[#0d1c2d] uppercase tracking-wider">Champion model breakdown</h3>
            <p className="text-xs text-[#76777d] mt-1 leading-normal">
              Per-campaign champion (XGBoost quantile vs visible baseline), forecast band, and marginal economics. Select a row to inspect its response curve.
            </p>
          </div>
          <div className="inline-flex items-center gap-2 bg-[#eef4ff] text-[#45464d] px-3 py-1.5 rounded-lg border border-[#c6c6cd]/50 text-xs font-medium">
            <Info size={14} className="text-[#0d1c2d]" />
            <span className="italic text-[11px]">Meta + Google only · forecasts are display-only inputs.</span>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="bg-gray-50 border-b border-[#e2e8f0]">
                <th className="py-3 px-4 text-[#45464d] font-semibold">Campaign / Platform</th>
                <th className="py-3 px-4 text-[#45464d] font-semibold">Champion model</th>
                <th className="py-3 px-4 text-[#45464d] font-semibold text-right">Forecast P50 (7d)</th>
                <th className="py-3 px-4 text-[#45464d] font-semibold text-right">P10–P90 band</th>
                <th className="py-3 px-4 text-[#45464d] font-semibold text-right">Marginal CM ROAS</th>
                <th className="py-3 px-4 text-[#45464d] font-semibold text-right">Calib / Reported</th>
                <th className="py-3 px-4 text-[#45464d] font-semibold text-center">Band</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#e2e8f0]/40 text-[#0d1c2d]">
              {rec.lines.map((l) => {
                const info = modelInfo(l.forecast_model);
                const belowHurdle = l.marginal_cm_roas < cmHurdle;
                const isSel = l.campaign_id === selected.campaign_id;
                return (
                  <tr
                    key={l.campaign_id}
                    onClick={() => setSelectedId(l.campaign_id)}
                    className={`cursor-pointer transition-colors ${isSel ? 'bg-[#e5efff]/50' : 'hover:bg-[#eef4ff]/30'}`}
                  >
                    <td className="py-3.5 px-4 font-semibold whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <span className="w-5 h-5 rounded bg-[#f1f5f9] border border-[#e2e8f0] flex items-center justify-center">
                          {platformLogo(l.platform)}
                        </span>
                        {shortName(l.campaign_name)}
                      </div>
                    </td>
                    <td className="py-3.5 px-4">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold font-data-mono border ${
                          info.conformal
                            ? 'bg-[#dae2fd] text-[#131b2e] border-[#bec6e0]'
                            : 'bg-gray-100 text-gray-700 border-gray-200'
                        }`}
                      >
                        {info.label}
                        {info.sub ? ` · ${info.sub}` : ''}
                      </span>
                    </td>
                    <td className="py-3.5 px-4 text-right font-semibold font-data-mono">{money(l.forecast_p50)}</td>
                    <td className="py-3.5 px-4 text-right font-data-mono text-[#76777d]">
                      {money(l.forecast_p10)} – {money(l.forecast_p90)}
                    </td>
                    <td className={`py-3.5 px-4 text-right font-data-mono font-semibold ${belowHurdle ? 'text-red-700' : 'text-[#006c49]'}`}
                        title={`gross marginal ROAS ${l.marginal_roas.toFixed(2)}× · CM hurdle ${cmHurdle.toFixed(2)}×`}>
                      <span className="inline-flex items-center gap-1 justify-end">
                        {belowHurdle && <TrendingDown size={12} />}
                        {l.marginal_cm_roas.toFixed(2)}×
                      </span>
                    </td>
                    <td className="py-3.5 px-4 text-right font-data-mono text-[#45464d]">
                      {l.calibrated_roas_current.toFixed(2)}× / {l.platform_roas_current.toFixed(2)}×
                    </td>
                    <td className="py-3.5 px-4 text-center">
                      <span
                        className={`inline-flex items-center justify-center px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border ${
                          info.conformal
                            ? 'bg-green-50 text-[#006c49] border-green-200'
                            : 'bg-amber-50 text-amber-800 border-amber-200'
                        }`}
                      >
                        {info.conformal ? 'Conformal' : '±20% heur.'}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="px-4 py-3 border-t border-[#e2e8f0]/60 bg-[#f8f9ff] flex items-center gap-2 text-[#76777d]">
          <AlertTriangle size={13} className="text-[#b45309]" />
          <span className="text-[11px] italic">
            Bands are display-only and not used for risk sizing; the optimizer allocates on P50 + marginal ROAS against each campaign’s break-even hurdle.
          </span>
        </div>
      </div>
    </div>
  );
}

function SummaryCard({ label, value, sub, danger }: { label: string; value: string; sub?: string; danger?: boolean }) {
  return (
    <div className="bg-white border border-[#e2e8f0] rounded-xl p-3.5 shadow-sm">
      <div className="text-[10px] uppercase tracking-wider text-[#76777d] font-bold">{label}</div>
      <div className={`text-base font-bold font-data-mono mt-0.5 ${danger ? 'text-red-700' : 'text-[#0d1c2d]'}`}>{value}</div>
      {sub && <div className="text-[10px] text-[#76777d] mt-0.5 leading-tight">{sub}</div>}
    </div>
  );
}