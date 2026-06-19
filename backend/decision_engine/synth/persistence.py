"""Write the generated dataset to disk: canonical CSV/Parquet, raw JSON, DuckDB.

CSV is the deterministic, diff-able artifact the tests fingerprint. Parquet and
a DuckDB file are written for the analytics/query path the later stages use.
"""

from __future__ import annotations

import json
from pathlib import Path


from backend.decision_engine import config as C
from backend.decision_engine.synth.envelope_writers import build_all_envelopes
from backend.decision_engine.synth.generator import Dataset


def write_canonical(ds: Dataset, canonical_dir: Path = C.CANONICAL_DIR) -> None:
    """Write ONLY the 13 canonical, model-ready tables.

    Latent generator truth (``ds.scenario_truth``) is deliberately NOT written
    here — it would leak targets (marginal ROAS, incrementality, noise) into the
    model-input path. Use ``write_latent_truth`` behind an explicit flag instead.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    from backend.decision_engine.schemas.canonical import OPERATIONAL_TABLES, arrow_schema

    canonical_dir.mkdir(parents=True, exist_ok=True)
    for name, df in ds.tables.items():
        df.to_csv(canonical_dir / f"{name}.csv", index=False, date_format="%Y-%m-%d")
        if name in OPERATIONAL_TABLES:
            # explicit Arrow schema so empty tables keep their declared types
            table = pa.Table.from_pylist([], schema=arrow_schema(name))
            pq.write_table(table, canonical_dir / f"{name}.parquet")
        else:
            df.to_parquet(canonical_dir / f"{name}.parquet", index=False)


def write_latent_truth(ds: Dataset, latent_dir: Path = C.LATENT_DIR) -> Path:
    """Persist latent generator truth under an explicitly INTERNAL path.

    Only ever called with an explicit opt-in (``--write-latent-truth``). The
    output lives outside ``data/canonical`` and ``data/raw`` so no adapter,
    DuckDB load, or feature-discovery path can pick it up by accident.
    """
    latent_dir.mkdir(parents=True, exist_ok=True)
    out = latent_dir / "scenario_truth.json"
    ds.scenario_truth.to_json(out, orient="records", indent=2)
    return out


def write_raw(ds: Dataset, raw_dir: Path = C.RAW_DIR) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    envelopes = build_all_envelopes(
        ds.tables["fact_ad_performance"], ds.tables["fact_commerce_truth"]
    )
    for name, env in envelopes.items():
        (raw_dir / f"{name}.json").write_text(
            json.dumps(env, indent=2, sort_keys=False, default=str)
        )


def write_duckdb(ds: Dataset, db_path: Path = C.CANONICAL_DIR / "decision_engine.duckdb") -> None:
    import duckdb

    from backend.decision_engine.schemas.canonical import (
        OPERATIONAL_TABLES,
        duckdb_columns,
    )

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    try:
        for name, df in ds.tables.items():
            if name in OPERATIONAL_TABLES:
                # explicit DDL so empty tables get their declared column types
                cols = ", ".join(f'"{c}" {t}' for c, t in duckdb_columns(name).items())
                con.execute(f"CREATE TABLE {name} ({cols})")
            else:
                con.register("_tmp", df)
                con.execute(f"CREATE TABLE {name} AS SELECT * FROM _tmp")
                con.unregister("_tmp")
    finally:
        con.close()


def write_manifest_file(ds: Dataset, write_latent: bool = False) -> Path:
    from backend.decision_engine.synth.manifest import write_manifest

    return write_manifest(ds, include_latent=write_latent)


def write_all(ds: Dataset, write_latent: bool = False) -> None:
    """Normal demo-generation path. Does NOT persist latent truth by default."""
    write_canonical(ds)
    write_raw(ds)
    write_duckdb(ds)
    write_manifest_file(ds, write_latent=write_latent)
    if write_latent:
        write_latent_truth(ds)
