#!/usr/bin/env python
"""CLI entrypoint: deterministically generate the golden-scenario dataset.

    python scripts/generate_synthetic_data.py [--seed N]

Writes canonical CSV/Parquet + DuckDB to data/canonical and raw API-envelope
JSON to data/raw, then prints row counts, planted-defect counts, and the
combined fingerprint.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as a plain script (no install required).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.decision_engine import config as C  # noqa: E402
from backend.decision_engine.synth.generator import generate  # noqa: E402
from backend.decision_engine.synth.manifest import build_manifest  # noqa: E402
from backend.decision_engine.synth.persistence import write_all  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate True Classic Paid Media Decision Engine synthetic dataset")
    ap.add_argument("--seed", type=int, default=C.MASTER_SEED)
    ap.add_argument(
        "--profile", choices=C.PROFILES, default="golden",
        help="dataset profile: 'golden' (smooth known-truth benchmark) or "
        "'realistic' (structured volatility + exogenous spend variation).",
    )
    ap.add_argument(
        "--write-latent-truth",
        action="store_true",
        help="ALSO persist latent generator truth under <profile>/internal/latent "
        "(debug/test only; never part of the normal model-input path).",
    )
    args = ap.parse_args()

    ds = generate(seed=args.seed, profile=args.profile)
    write_all(ds, write_latent=args.write_latent_truth, profile=args.profile)

    paths = C.profile_paths(args.profile)
    print(f"Generated profile={args.profile} with seed={args.seed}")
    print(f"  output: {paths['canonical']}  and  {paths['raw']}")
    print("\nRow counts:")
    for name, df in ds.tables.items():
        print(f"  {name:28} {len(df):6} rows")
    print("\nPlanted defect counts:")
    for issue_type, count in ds.defect_counts.items():
        print(f"  {issue_type:34} {count}")
    manifest = build_manifest(ds, include_latent=args.write_latent_truth)
    print(f"\nCanonical-tables fingerprint: {manifest['canonical_tables_fingerprint']}")
    print(f"Full-artifact fingerprint:    {manifest['full_artifact_fingerprint']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
