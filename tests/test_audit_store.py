"""Stage 4.4 — durable, append-only, hash-chained decision/audit ledger.

Asserts the governance properties the in-memory store could not give us: decisions
survive a process restart, the ledger is tamper-evident (hash chain + DB triggers),
and the D-030 decision contract (idempotent replay, terminal immutability, conflict)
is preserved on the durable backend.
"""

from __future__ import annotations

import sqlite3

import pytest

from backend.api.recommendation import build_recommendation
from backend.api.schemas import ConstraintParams
from backend.api.store import DecisionConflict, DurableDecisionStore


@pytest.fixture(scope="module")
def rec_a():
    return build_recommendation()


@pytest.fixture(scope="module")
def rec_b():
    # a distinct scenario (different movement bound -> different scenario_id)
    return build_recommendation(constraints=ConstraintParams(movement_bound=0.30))


def test_decision_persists_across_restart(tmp_path, rec_a):
    db = str(tmp_path / "decisions.db")
    s1 = DurableDecisionStore(db)
    s1.decide(rec_a, "approve", "marketer", "ship it")

    s2 = DurableDecisionStore(db)              # a fresh process opening the same file
    got = s2.get(rec_a.scenario_id)
    assert got is not None and got.status == "approved" and got.approver == "marketer"
    assert got.notes == "ship it"
    # full D-030 provenance is preserved on disk
    assert got.config_fingerprint == rec_a.config_fingerprint
    assert got.calibration_fingerprint == rec_a.calibration_fingerprint
    assert got.effective_calibration_fingerprint == rec_a.effective_calibration_fingerprint
    # solver status round-trips faithfully (value preserved, not pinned to a literal)
    assert got.binding.solver.success == rec_a.binding.solver.success
    assert got.binding.solver.status == rec_a.binding.solver.status


def test_idempotent_replay_and_conflict_on_durable_store(rec_a):
    s = DurableDecisionStore(":memory:")
    first = s.decide(rec_a, "approve", "m", None)
    replay = s.decide(rec_a, "approve", "m", None)
    assert first.idempotent_replay is False and replay.idempotent_replay is True
    with pytest.raises(DecisionConflict):
        s.decide(rec_a, "reject", "m", None)        # terminal record cannot flip


def test_append_only_triggers_block_mutation(tmp_path, rec_a):
    db = str(tmp_path / "decisions.db")
    s = DurableDecisionStore(db)
    s.decide(rec_a, "approve", "m", None)
    raw = sqlite3.connect(db)
    with pytest.raises(sqlite3.Error):            # UPDATE is forbidden by trigger
        raw.execute("UPDATE decisions SET approver = 'attacker' WHERE seq = 1")
    with pytest.raises(sqlite3.Error):            # DELETE is forbidden by trigger
        raw.execute("DELETE FROM decisions WHERE seq = 1")
    raw.close()


def test_hash_chain_links_and_verifies(tmp_path, rec_a, rec_b):
    db = str(tmp_path / "decisions.db")
    s = DurableDecisionStore(db)
    s.decide(rec_a, "approve", "m", None)
    s.decide(rec_b, "reject", "m", None)
    v = s.verify_chain()
    assert v["ok"] is True and v["count"] == 2 and v["head_hash"]
    # the ledger reads back in commit order
    log = s.all_decisions()
    assert [d.scenario_id for d in log] == [rec_a.scenario_id, rec_b.scenario_id]


def test_chain_detects_out_of_band_tampering(tmp_path, rec_a, rec_b):
    db = str(tmp_path / "decisions.db")
    s = DurableDecisionStore(db)
    s.decide(rec_a, "approve", "m", None)
    s.decide(rec_b, "reject", "m", None)
    assert s.verify_chain()["ok"] is True
    # an attacker drops the guard triggers and rewrites an approved record's approver;
    # the row's stored hash no longer matches its recomputed content -> chain breaks.
    raw = sqlite3.connect(db)
    raw.executescript("DROP TRIGGER decisions_no_update; DROP TRIGGER decisions_no_delete;")
    raw.execute("UPDATE decisions SET approver = 'attacker' WHERE seq = 1")
    raw.commit()
    raw.close()
    broken = s.verify_chain()
    assert broken["ok"] is False and broken["broken_seq"] == 1
