"""Stable *logical* content fingerprints for the generated dataset.

Fingerprints hash normalized logical content with canonical JSON serialization
(stable column order, stable row order, fixed float rounding, ISO dates, NaN→null).
They are invariant to incidental row order and to storage format (we never hash
Parquet bytes) but sensitive to any real change in generated values.

Used by tests as a determinism/drift regression guard within the pinned env.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pandas as pd

_FLOAT_DECIMALS = 6


def _normalize_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    norm = df[sorted(df.columns)].copy()
    for col in norm.columns:
        if pd.api.types.is_datetime64_any_dtype(norm[col]):
            norm[col] = norm[col].dt.strftime("%Y-%m-%d")
        elif pd.api.types.is_float_dtype(norm[col]):
            norm[col] = norm[col].round(_FLOAT_DECIMALS)
    recs = norm.where(pd.notna(norm), None).to_dict("records")
    # stable row order independent of incidental ordering
    recs.sort(key=lambda r: json.dumps(r, sort_keys=True, default=str))
    return recs


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def frame_fingerprint(df: pd.DataFrame) -> str:
    """Deterministic sha256 of a DataFrame's canonical-JSON logical content."""
    recs = _normalize_records(df)
    return _sha256(json.dumps(recs, sort_keys=True, default=str))


def dataset_fingerprint(tables: dict[str, pd.DataFrame]) -> dict[str, str]:
    return {name: frame_fingerprint(df) for name, df in sorted(tables.items())}


def envelope_fingerprint(envelope: dict) -> str:
    """Canonical-JSON fingerprint of a normalized API envelope."""
    return _sha256(json.dumps(envelope, sort_keys=True, default=str))


def canonical_tables_fingerprint(tables: dict[str, pd.DataFrame]) -> str:
    """Logical fingerprint over the canonical tables ONLY."""
    parts = [f"{name}:{fp}" for name, fp in dataset_fingerprint(tables).items()]
    return _sha256("\n".join(parts))


# Backwards-compatible alias (canonical-tables-only).
combined_fingerprint = canonical_tables_fingerprint


def full_artifact_fingerprint(
    tables: dict[str, pd.DataFrame],
    envelopes: dict[str, dict],
    *,
    seed: int,
    generator_version: str,
    schema_version: str,
    dependency_versions: dict[str, str],
) -> str:
    """The MAIN reproducibility fingerprint: the entire generated contract.

    Covers every canonical table, the Meta/Google/Shopify envelopes,
    generator/schema versions, the seed, and the relevant dependency versions.
    Hashes normalized logical content with canonical JSON (never Parquet bytes),
    so storage/serialization formatting cannot change it.
    """
    payload = {
        "seed": seed,
        "generator_version": generator_version,
        "schema_version": schema_version,
        "dependency_versions": dict(sorted(dependency_versions.items())),
        "canonical_tables_fingerprint": canonical_tables_fingerprint(tables),
        "table_fingerprints": dataset_fingerprint(tables),
        "envelope_fingerprints": {
            name: envelope_fingerprint(env) for name, env in sorted(envelopes.items())
        },
    }
    return _sha256(json.dumps(payload, sort_keys=True))
