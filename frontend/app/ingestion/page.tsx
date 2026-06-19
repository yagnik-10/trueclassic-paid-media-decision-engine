"use client";

import { useEffect, useState } from "react";
import {
  type IngestionSummary,
  type SkuResolutionItem,
  approveSku,
  getIngestion,
} from "@/lib/api";

export default function IngestionPage() {
  const [data, setData] = useState<IngestionSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    getIngestion().then(setData).catch((e) => setError(String(e.message ?? e)));
  }, []);

  async function approve(item: SkuResolutionItem) {
    const candidate = item.sku_id ?? item.allowed_candidates[0];
    if (!candidate) return;
    setBusy(item.platform_product_id);
    setError(null);
    try {
      await approveSku(item.platform_product_id, candidate, "marketer@trueclassic");
      setData(await getIngestion());
    } catch (e: any) {
      setError(String(e.message ?? e));
    } finally {
      setBusy(null);
    }
  }

  if (error && !data) {
    return <div className="wrap"><h1>Ingestion</h1><p className="err">{error}</p></div>;
  }
  if (!data) return <div className="wrap"><p className="sub">Running ingestion…</p></div>;

  return (
    <div className="wrap">
      <h1>Ingestion &amp; Reconciliation</h1>
      <p className="sub">
        Raw Meta / Google / Shopify API exports → validated → canonical, with quarantine,
        SKU reconciliation, and detected data-quality flags.
      </p>

      <div className="kpis">
        <div className="kpi"><div className="label">Canonical ad-performance rows</div><div className="value">{data.canonical_fact_rows.toLocaleString()}</div></div>
        <div className="kpi"><div className="label">Canonical commerce rows</div><div className="value">{data.canonical_commerce_rows.toLocaleString()}</div></div>
        <div className="kpi"><div className="label">Quarantined records</div><div className="value">{data.total_quarantined}</div></div>
        <div className="kpi"><div className="label">Data-quality flags</div><div className="value">{data.dq_issues.length}</div></div>
      </div>

      <h3 style={{ margin: "8px 0" }}>Feeds</h3>
      <table>
        <thead><tr><th>Platform</th><th className="num">Raw records</th><th className="num">Normalized</th><th className="num">Quarantined</th></tr></thead>
        <tbody>
          {data.feeds.map((f) => (
            <tr key={f.platform}>
              <td>{f.platform}</td>
              <td className="num">{f.raw.toLocaleString()}</td>
              <td className="num">{f.normalized.toLocaleString()}</td>
              <td className={`num ${f.quarantined ? "down" : "flat"}`}>{f.quarantined}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3 style={{ margin: "28px 0 8px" }}>SKU reconciliation</h3>
      <table>
        <thead><tr><th>Platform ID</th><th>Platform</th><th>Canonical SKU</th><th>Status</th><th className="num">Confidence</th><th>Action</th></tr></thead>
        <tbody>
          {data.sku_resolutions.map((s) => (
            <tr key={`${s.platform}-${s.platform_product_id}`}>
              <td className="mono">{s.platform_product_id}</td>
              <td>{s.platform}</td>
              <td>{s.sku_id ?? <span className="muted">— unmapped —</span>}</td>
              <td><span className={`status-pill ${s.status}`}>{s.status.replace("_", " ")}</span></td>
              <td className="num">{(s.confidence * 100).toFixed(0)}%</td>
              <td>
                {s.status === "needs_approval" && (
                  <button className="approve small" disabled={busy === s.platform_product_id}
                          onClick={() => approve(s)}>
                    Approve → {s.allowed_candidates[0]}
                  </button>
                )}
                {s.status === "quarantined" && (
                  <span className="sub">candidates: {s.allowed_candidates.join(", ")}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3 style={{ margin: "28px 0 8px" }}>Detected data-quality issues</h3>
      <table>
        <thead><tr><th>Type</th><th>Severity</th><th>Entity</th><th>Detail</th><th>Resolution</th></tr></thead>
        <tbody>
          {data.dq_issues.map((i) => (
            <tr key={i.issue_id}>
              <td>{i.issue_type.replace(/_/g, " ")}</td>
              <td><span className={`sev ${i.severity}`}>{i.severity}</span></td>
              <td className="mono">{i.entity_ref}</td>
              <td>{i.description}</td>
              <td className="sub">{i.resolution.replace(/_/g, " ")}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {error && <p className="err">{error}</p>}
    </div>
  );
}
