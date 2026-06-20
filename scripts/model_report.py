#!/usr/bin/env python
"""Generate the reproducible model-performance report.

    make model-report        # writes reports/model_performance/{metrics.json,REPORT.md,plots/}

Regenerates everything from the deterministic synthetic data without editing any
source files. Run twice — the numeric outputs (metrics.json) are identical.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from backend.decision_engine.eval.report import OUT_DIR, run


def main() -> None:
    ap = argparse.ArgumentParser(description="Model-performance report")
    ap.add_argument("--out", type=Path, default=OUT_DIR, help="output directory")
    args = ap.parse_args()

    report = run(args.out)
    it = report["interpretation"]
    print(f"Model performance report → {args.out}")
    print(f"  data_fingerprint: {report['provenance']['data_fingerprint']}")
    print(f"  overall test WAPE: {it['overall_test_wape']} "
          f"(~{it['approx_point_accuracy_pct']}% intuitive accuracy)")
    print(f"  80% interval: XGBoost conformal {it['interval_conformal_assessment']}; "
          f"deployed mixed-policy empirical coverage {it['interval_coverage_deployed']} "
          f"(width {it['interval_width_deployed']})")
    print(f"  response hurdle accuracy: {it['response_hurdle_accuracy']} · "
          f"direction stable ±20%: {it['direction_stable_under_pm20pct']}")
    if it["champion_holdout_drift"]:
        print(f"  holdout drift (not flipped): {[d['campaign'] for d in it['champion_holdout_drift']]}")
    d = report["decision"]
    print(f"  CM ROAS (primary): {d['cm_roas_current']:.2f}× → {d['cm_roas_projected']:.2f}× · "
          f"net contribution ${d['net_contribution_current']:,.0f} → "
          f"${d['net_contribution_projected']:,.0f}/day (gross floor lens "
          f"{report['decision']['blended_roas_projected']:.2f}×)")
    ps = d["prospecting_share"]
    print(f"  prospecting share: {ps['actual_share'] * 100:.2f}% vs floor "
          f"{ps['floor'] * 100:.2f}% (slack {ps['slack_pp']:+.2f}pp)")
    print(f"  safe_for_model_demo: {it['safe_for_model_demo']} · "
          f"safe_for_decision_demo: {it['safe_for_decision_demo']}")
    print(f"  artifacts: metrics.json, per_campaign_point_metrics.csv, REPORT.md, "
          f"plots/ ({len(report['artifacts']['plots'])} png)")


if __name__ == "__main__":
    main()
