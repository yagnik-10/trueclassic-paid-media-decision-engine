"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ErrorBar,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Recommendation } from "@/lib/api";

const PALETTE = ["#5b8def", "#38c172", "#e0a93b", "#e3554f", "#9b6cf0", "#3bc6c2", "#d96fae"];
const AXIS = "#9aa6bd";
const GRID = "#2a3344";

const short = (n: string) => n.replace(/^(Google|Meta)\s*[—-]\s*/, "");
const money = (n: number) => `$${Math.round(n).toLocaleString()}`;

function Panel({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="chart-panel">
      <div className="chart-title">{title}</div>
      {subtitle && <div className="chart-sub">{subtitle}</div>}
      <div style={{ width: "100%", height: 260 }}>
        <ResponsiveContainer>{children as any}</ResponsiveContainer>
      </div>
    </div>
  );
}

const tooltipStyle = { background: "#141925", border: "1px solid #2a3344", borderRadius: 8, color: "#e6eaf2", fontSize: 12 };

export default function Charts({ rec }: { rec: Recommendation }) {
  const realloc = rec.lines.map((l) => ({
    name: short(l.campaign_name), Current: l.current_spend, Recommended: l.recommended_spend,
  }));
  const marg = rec.lines.map((l) => ({
    name: short(l.campaign_name), marginal: l.marginal_roas, downside: l.marginal_roas_downside,
  }));
  const fc = rec.lines.map((l) => ({
    name: short(l.campaign_name), p50: l.forecast_p50,
    err: [Math.max(0, l.forecast_p50 - l.forecast_p10), Math.max(0, l.forecast_p90 - l.forecast_p50)],
  }));
  const xs: number[] = [];
  for (let p = -20; p <= 20; p += 5) xs.push(p);
  const curve = xs.map((p) => {
    const x = 1 + p / 100;
    const row: Record<string, number> = { pct: p };
    rec.lines.forEach((l) => {
      row[short(l.campaign_name)] = l.response_slope + 2 * l.response_quad * (x - 1) * l.current_spend;
    });
    return row;
  });

  return (
    <div className="charts">
      <Panel title="Budget reallocation" subtitle="current vs optimizer-recommended daily spend">
        <BarChart data={realloc} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="name" tick={{ fill: AXIS, fontSize: 11 }} angle={-20} textAnchor="end" height={60} interval={0} />
          <YAxis tick={{ fill: AXIS, fontSize: 11 }} tickFormatter={money} width={64} />
          <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => money(v)} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="Current" fill="#3b4660" radius={[3, 3, 0, 0]} />
          <Bar dataKey="Recommended" fill="#5b8def" radius={[3, 3, 0, 0]} />
        </BarChart>
      </Panel>

      <Panel title="Marginal ROAS by channel" subtitle={`recovered next-dollar return · scale floor ≈ ${rec.marginal_scale_floor.toFixed(2)}×`}>
        <BarChart data={marg} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="name" tick={{ fill: AXIS, fontSize: 11 }} angle={-20} textAnchor="end" height={60} interval={0} />
          <YAxis tick={{ fill: AXIS, fontSize: 11 }} width={44} />
          <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => `${v.toFixed(2)}×`} />
          <ReferenceLine y={rec.marginal_scale_floor} stroke="#e0a93b" strokeDasharray="4 4" label={{ value: "scale floor", fill: "#e0a93b", fontSize: 10, position: "insideTopRight" }} />
          <ReferenceLine y={0} stroke={GRID} />
          <Bar dataKey="marginal" radius={[3, 3, 0, 0]}>
            {marg.map((d, i) => (
              <Cell key={i} fill={d.marginal >= rec.marginal_scale_floor ? "#38c172" : "#e3554f"} />
            ))}
          </Bar>
        </BarChart>
      </Panel>

      <Panel title="Saturation / response curves" subtitle="marginal ROAS as spend moves ±20% around current (0% = today)">
        <LineChart data={curve} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <CartesianGrid stroke={GRID} />
          <XAxis dataKey="pct" tick={{ fill: AXIS, fontSize: 11 }} tickFormatter={(v) => `${v > 0 ? "+" : ""}${v}%`} />
          <YAxis tick={{ fill: AXIS, fontSize: 11 }} width={44} tickFormatter={(v) => `${v.toFixed(1)}×`} />
          <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => `${v.toFixed(2)}×`} labelFormatter={(l) => `spend ${l > 0 ? "+" : ""}${l}%`} />
          <ReferenceLine y={rec.marginal_scale_floor} stroke="#e0a93b" strokeDasharray="4 4" />
          <ReferenceLine x={0} stroke={GRID} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {rec.lines.map((l, i) => (
            <Line key={l.campaign_id} type="monotone" dataKey={short(l.campaign_name)} stroke={PALETTE[i % PALETTE.length]} dot={false} strokeWidth={2} />
          ))}
        </LineChart>
      </Panel>

      <Panel title="7-day revenue forecast" subtitle="P50 with P10–P90 interval (XGBoost quantile or baseline)">
        <BarChart data={fc} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="name" tick={{ fill: AXIS, fontSize: 11 }} angle={-20} textAnchor="end" height={60} interval={0} />
          <YAxis tick={{ fill: AXIS, fontSize: 11 }} width={64} tickFormatter={money} />
          <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => money(v)} />
          <Bar dataKey="p50" fill="#3bc6c2" radius={[3, 3, 0, 0]}>
            <ErrorBar dataKey="err" stroke="#e6eaf2" strokeWidth={1.5} width={4} direction="y" />
          </Bar>
        </BarChart>
      </Panel>
    </div>
  );
}
