"""Empty operational tables keep their declared types in DuckDB and Parquet."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.decision_engine.schemas.canonical import (
    OPERATIONAL_TABLES,
    arrow_schema,
    duckdb_columns,
)
from backend.decision_engine.synth.generator import generate
from backend.decision_engine.synth.persistence import write_canonical, write_duckdb


@pytest.fixture(scope="module")
def written(dataset):
    with tempfile.TemporaryDirectory() as d:
        canon = Path(d) / "canonical"
        ds = generate()
        write_canonical(ds, canonical_dir=canon)
        write_duckdb(ds, db_path=canon / "decision_engine.duckdb")
        yield canon


@pytest.mark.parametrize("table", OPERATIONAL_TABLES)
def test_parquet_arrow_schema_matches_contract(written, table):
    import pyarrow.parquet as pq

    schema = pq.read_schema(written / f"{table}.parquet")
    expected = arrow_schema(table)
    assert schema.names == expected.names
    assert [str(t) for t in schema.types] == [str(t) for t in expected.types]
    # the columns are NOT all object/null
    assert not all(str(t) == "null" for t in schema.types)


@pytest.mark.parametrize("table", OPERATIONAL_TABLES)
def test_duckdb_column_types_match_contract(written, table):
    import duckdb

    con = duckdb.connect(str(written / "decision_engine.duckdb"))
    try:
        info = con.execute(f"PRAGMA table_info('{table}')").fetchall()
    finally:
        con.close()
    got = {row[1]: row[2].upper() for row in info}  # name -> type
    expected = {c: t.upper() for c, t in duckdb_columns(table).items()}
    assert got == expected


def test_operational_tables_are_empty_on_disk(written):
    import duckdb

    con = duckdb.connect(str(written / "decision_engine.duckdb"))
    try:
        for table in OPERATIONAL_TABLES:
            assert con.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    finally:
        con.close()
