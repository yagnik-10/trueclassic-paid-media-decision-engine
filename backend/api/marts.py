"""Stage 4.5 — lightweight, Looker-ready SQL marts over the durable audit ledger.

These are plain SQL **views** on the append-only `decisions` table (D-031), so they
are always fresh, add no storage, and need no extra dependency. A BI tool (Looker,
Metabase, …) points at the same SQLite file and reads four flat, single-grain marts:

    mart_decision            one row per decision  (the governance fact)
    mart_decision_line       one row per (decision, campaign) — the allocation fact
    mart_binding_constraint  one row per (decision, portfolio constraint)
    mart_audit_chain         one row per decision — provenance + hash-chain linkage

The DDL lives here (committed + tested) and is the source of truth; `build_marts.py`
materializes it into the live ledger and exports the DDL + CSV extracts. The marts
flatten the JSON columns the ledger stores (`allocation_json`, `binding_json`,
`constraints_json`) via SQLite's JSON1 functions.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

# Ordered so dependent inspection / export is deterministic.
MART_VIEWS: dict[str, str] = {
    # one row per decision: scalar provenance + flattened constraint/solver params
    # and JSON-derived rollups (campaign count, deployed spend, constraint posture).
    "mart_decision": """
CREATE VIEW IF NOT EXISTS mart_decision AS
SELECT
    d.seq,
    d.scenario_id,
    d.rec_id,
    d.policy,
    d.action,
    d.status,
    d.approver,
    d.decided_at,
    d.notes,
    d.data_fingerprint,
    d.engine_version,
    d.config_fingerprint,
    d.calibration_fingerprint,
    d.effective_calibration_fingerprint,
    json_extract(d.constraints_json, '$.roas_floor')            AS roas_floor,
    json_extract(d.constraints_json, '$.nc_cpa_target')         AS nc_cpa_target,
    json_extract(d.constraints_json, '$.prospecting_min_share') AS prospecting_min_share,
    json_extract(d.constraints_json, '$.movement_bound')        AS movement_bound,
    json_extract(d.constraints_json, '$.reserve_mode')          AS reserve_mode,
    (SELECT COUNT(*) FROM json_each(d.constraints_json, '$.calibration_overrides'))
        AS n_calibration_overrides,
    CASE WHEN (SELECT COUNT(*) FROM json_each(d.constraints_json, '$.calibration_overrides')) > 0
         THEN 1 ELSE 0 END                                      AS is_sensitivity_override,
    json_extract(d.binding_json, '$.solver.success')            AS solver_success,
    json_extract(d.binding_json, '$.solver.status')             AS solver_status,
    json_extract(d.binding_json, '$.solver.iterations')         AS solver_iterations,
    json_extract(d.binding_json, '$.solver.message')            AS solver_message,
    (SELECT COUNT(*) FROM json_each(d.allocation_json))         AS n_campaigns,
    (SELECT COALESCE(SUM(value), 0) FROM json_each(d.allocation_json))
        AS total_recommended_spend,
    (SELECT COUNT(*) FROM json_each(d.binding_json, '$.portfolio')
        WHERE json_extract(value, '$.status') = 'binding')      AS n_binding_constraints,
    (SELECT COUNT(*) FROM json_each(d.binding_json, '$.portfolio')
        WHERE json_extract(value, '$.status') = 'violated')     AS n_violated_constraints,
    (SELECT COUNT(*) FROM json_each(d.binding_json, '$.portfolio')
        WHERE json_extract(value, '$.status') = 'slack')        AS n_slack_constraints,
    (SELECT COUNT(*) FROM json_each(d.binding_json, '$.per_campaign'))
        AS n_campaign_bounds
FROM decisions d;
""",
    # one row per allocated campaign, with within-decision spend share.
    "mart_decision_line": """
CREATE VIEW IF NOT EXISTS mart_decision_line AS
SELECT
    d.seq,
    d.scenario_id,
    d.decided_at,
    d.status,
    d.policy,
    a.key                                                       AS campaign_id,
    a.value                                                     AS recommended_spend,
    a.value / NULLIF((SELECT SUM(value) FROM json_each(d.allocation_json)), 0)
        AS spend_share
FROM decisions d, json_each(d.allocation_json) a;
""",
    # one row per portfolio constraint, with its binding/slack/violated posture.
    "mart_binding_constraint": """
CREATE VIEW IF NOT EXISTS mart_binding_constraint AS
SELECT
    d.seq,
    d.scenario_id,
    d.decided_at,
    d.status                                                    AS decision_status,
    json_extract(p.value, '$.name')                            AS constraint_name,
    json_extract(p.value, '$.status')                          AS constraint_status,
    json_extract(p.value, '$.detail')                          AS detail
FROM decisions d, json_each(d.binding_json, '$.portfolio') p;
""",
    # provenance + hash-chain linkage for governance reporting.
    "mart_audit_chain": """
CREATE VIEW IF NOT EXISTS mart_audit_chain AS
SELECT
    d.seq,
    d.scenario_id,
    d.decided_at,
    d.action,
    d.status,
    d.prev_hash,
    d.row_hash,
    d.data_fingerprint,
    d.engine_version,
    d.config_fingerprint,
    d.calibration_fingerprint,
    d.effective_calibration_fingerprint
FROM decisions d
ORDER BY d.seq;
""",
}

MART_NAMES: tuple[str, ...] = tuple(MART_VIEWS)


def marts_ddl() -> str:
    """The full CREATE VIEW DDL (the artifact a Looker/warehouse deploy consumes)."""
    return "\n".join(MART_VIEWS[name].strip() for name in MART_NAMES) + "\n"


def create_marts(conn: sqlite3.Connection) -> None:
    """(Re)create the mart views on a ledger connection. Idempotent + non-destructive
    (views only; the append-only `decisions` table and its triggers are untouched)."""
    conn.executescript(marts_ddl())
    conn.commit()


def query_mart(conn: sqlite3.Connection, name: str) -> list[dict]:
    if name not in MART_VIEWS:
        raise KeyError(f"unknown mart {name!r}; expected one of {MART_NAMES}")
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(f"SELECT * FROM {name}").fetchall()]


def export_marts(conn: sqlite3.Connection, out_dir: Path) -> list[Path]:
    """Write the DDL plus one CSV extract per mart to ``out_dir`` (for offline BI /
    spreadsheet review). Returns the files written."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    ddl_path = out_dir / "marts.sql"
    ddl_path.write_text(marts_ddl(), encoding="utf-8")
    written.append(ddl_path)

    for name in MART_NAMES:
        rows = query_mart(conn, name)
        csv_path = out_dir / f"{name}.csv"
        # stable header even when the mart is empty (cols from the view's metadata)
        cols = [c[0] for c in conn.execute(f"SELECT * FROM {name} LIMIT 0").description]
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=cols)
            writer.writeheader()
            writer.writerows(rows)
        written.append(csv_path)
    return written
