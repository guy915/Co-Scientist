from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest

from app.citations import CitationState
from app.store import db as store_db
from app.store import events as store_events
from app.store import hypotheses as store
from app.store import records, runs
from app.store import runs_views as views
from app.store.hypotheses import HypothesisStateChanges, NewHypothesis
from app.store.records import (
    NewCitation,
    NewEvidence,
    NewMatch,
    NewReview,
    NewSafetyDecision,
)
from tests._store_helpers import seed_run


@pytest.fixture
def db(isolated_db: str) -> str:
    return os.environ["COSCIENTIST_DB_PATH"]


def test_event_log_is_append_only_and_strictly_increasing(db: str) -> None:
    run = seed_run("test", provider="mock")
    seqs = []
    for i in range(5):
        seqs.append(store_events.append_event(run.id, "log", {"i": i}))
    events = store_events.list_events(run.id)
    assert seqs == [e["seq"] for e in events]
    assert all(seqs[i] < seqs[i + 1] for i in range(4))


def test_list_events_filters_after_seq(db: str) -> None:
    run = seed_run("filter test", provider="mock")
    for i in range(4):
        store_events.append_event(run.id, "log", {"i": i})
    half = store_events.list_events(run.id)[1]["seq"]
    after = store_events.list_events(run.id, after_seq=half)
    assert len(after) == 2
    for ev in after:
        assert ev["seq"] > half


def test_list_runs_reports_top_elo_and_the_top_three_hypotheses(
    db: str,
) -> None:
    run = seed_run("top-hyps", provider="mock")
    for title, rating in (
        ("Low", 1180),
        ("High", 1320),
        ("Mid", 1250),
        ("Lowest", 1100),
    ):
        hid = store.add_hypothesis(
            NewHypothesis(
                run_id=run.id,
                title=title,
                statement="s",
                created_by_agent="generation",
            )
        )
        store.update_hypothesis_state(
            hid, HypothesisStateChanges(elo_rating=rating)
        )
    seed_run("no-hyps", provider="mock")

    by_goal = {r.research_goal: r for r in views.list_runs()}
    assert by_goal["top-hyps"].top_elo == 1320
    assert by_goal["no-hyps"].top_elo is None
    assert by_goal["top-hyps"].top_hypotheses == ["High", "Mid", "Low"]
    assert by_goal["no-hyps"].top_hypotheses == []
    single = runs.get_run(run.id)
    assert single is not None
    assert single.top_hypotheses is None
    assert single.top_elo is None


def test_list_runs_reports_latest_pipeline_stage(db: str) -> None:
    run = seed_run("staged", provider="mock")
    store_events.append_event(run.id, "supervisor.plan", {})
    store_events.append_event(run.id, "generate", {})
    store_events.append_event(run.id, "ranking", {})
    store_events.append_event(run.id, "status", {"status": "running"})
    seed_run("unstaged", provider="mock")

    by_goal = {r.research_goal: r for r in views.list_runs()}
    assert by_goal["staged"].latest_stage == "ranking"
    assert by_goal["unstaged"].latest_stage is None
    single = runs.get_run(run.id)
    assert single is not None
    assert single.latest_stage is None


def test_hypothesis_state_decoupled_from_hypothesis_row(db: str) -> None:
    run = seed_run("decoupling test", provider="mock")
    hid = store.add_hypothesis(
        NewHypothesis(
            run_id=run.id,
            title="t",
            statement="s",
            mechanism="m",
            expected_effect="e",
            experimental_context="x",
            created_by_agent="generation",
        )
    )
    store.update_hypothesis_state(
        hid, HypothesisStateChanges(elo_rating=1300, win_delta=1)
    )
    store.update_hypothesis_state(
        hid, HypothesisStateChanges(elo_rating=1350, win_delta=1)
    )
    h = store.get_hypothesis(hid)
    assert h is not None
    assert h["elo_rating"] == 1350
    assert h["win_count"] == 2
    assert h["title"] == "t"
    assert h["statement"] == "s"


def test_hypothesis_row_carries_scene_setting_and_safety_notes(db: str) -> None:
    run = seed_run("scene-setting test", provider="mock")
    hid = store.add_hypothesis(
        NewHypothesis(
            run_id=run.id,
            title="t",
            statement="s",
            introduction=(
                "Metabolic disease remains a major cause of morbidity."
            ),
            recent_findings="Aldolase inhibitors have shown early promise.",
            safety_and_toxicity="Limited human safety data exists.",
            created_by_agent="generation",
        )
    )
    h = store.get_hypothesis(hid)
    assert h is not None
    assert h["introduction"] == (
        "Metabolic disease remains a major cause of morbidity."
    )
    assert h["recent_findings"] == (
        "Aldolase inhibitors have shown early promise."
    )
    assert h["safety_and_toxicity"] == "Limited human safety data exists."


def test_multi_parent_hypothesis_records_every_parent(db: str) -> None:
    run = seed_run("multi-parent", provider="mock")
    primary = store.add_hypothesis(
        NewHypothesis(
            run_id=run.id, title="P1", statement="p1", hypothesis_id="p1"
        )
    )
    partner = store.add_hypothesis(
        NewHypothesis(
            run_id=run.id, title="P2", statement="p2", hypothesis_id="p2"
        )
    )
    child = store.add_hypothesis(
        NewHypothesis(
            run_id=run.id,
            title="C",
            statement="cs",
            hypothesis_id="c1",
            parent_id=primary,
            parent_ids=[primary, partner],
            generation=1,
            created_by_agent="evolution",
        )
    )

    rows = {r["id"]: r for r in store.list_hypotheses(run.id)}
    assert rows[child]["parent_id"] == primary
    assert rows[child]["parent_ids"] == [primary, partner]
    assert rows[child]["generation"] == 1
    assert rows[primary]["generation"] == 0
    assert rows[primary]["parent_id"] is None
    assert rows[primary]["parent_ids"] is None
    assert rows[partner]["parent_ids"] is None
    single = store.get_hypothesis(child)
    assert single is not None and single["parent_ids"] == [primary, partner]


def test_redact_hypothesis_fields_overwrites_detail_columns(db: str) -> None:
    run = seed_run("redact", provider="mock")
    hid = store.add_hypothesis(
        NewHypothesis(
            run_id=run.id,
            title="H",
            statement="keep me",
            mechanism="secret mechanism",
            experimental_context="secret protocol",
        )
    )
    store.redact_hypothesis_fields(
        hid, {"mechanism": "[X]", "experimental_context": "[X]"}
    )
    row = store.get_hypothesis(hid)
    assert row is not None
    assert row["mechanism"] == "[X]"
    assert row["experimental_context"] == "[X]"
    assert row["statement"] == "keep me"


def test_redact_hypothesis_fields_rejects_non_redactable_column(
    db: str,
) -> None:
    run = seed_run("redact", provider="mock")
    hid = store.add_hypothesis(
        NewHypothesis(run_id=run.id, title="H", statement="s")
    )
    with pytest.raises(ValueError, match="non-redactable"):
        store.redact_hypothesis_fields(hid, {"statement": "wiped"})


def test_safety_decision_persists_matches_array(db: str) -> None:
    run = seed_run("safety", provider="mock")
    records.add_safety_decision(
        NewSafetyDecision(
            run_id=run.id,
            stage="intake",
            decision="block",
            reason="test reason",
            matches=["match-a", "match-b"],
        )
    )
    rows = records.list_safety_decisions(run.id)
    assert rows[0]["decision"] == "block"
    assert rows[0]["matches"] == ["match-a", "match-b"]


def test_match_log_preserves_elo_and_debate_turns(db: str) -> None:
    run = seed_run("matches", provider="mock")
    for before, after, turns in ((1200, 1212, 1), (1212, 1230, 3)):
        records.add_match(
            NewMatch(
                run_id=run.id,
                iteration=1,
                winner_id="w",
                loser_id="l",
                winner_before=before,
                winner_after=after,
                loser_before=2400 - before,
                loser_after=2400 - after,
                rationale="rationale",
                debate_turns=turns,
            )
        )
    first, second = records.list_matches(run.id)
    assert (first["winner_elo_before"], first["winner_elo_after"]) == (
        1200,
        1212,
    )
    assert (first["loser_elo_before"], first["loser_elo_after"]) == (1200, 1188)
    assert (first["debate_turns"], second["debate_turns"]) == (1, 3)


def test_connections_pair_wal_with_normal_synchronous(db: str) -> None:
    # WAL with NORMAL reduces fsync lock time while checkpoints preserve
    # durability; writes remain single-writer.
    with store_db.connect() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1


class _StaleColumnView:
    """A connection whose column listing predates another process's ALTER."""

    def __init__(self, conn: sqlite3.Connection, alter_error: str) -> None:
        self._conn = conn
        self._alter_error = alter_error

    def execute(self, sql: str, *args: Any) -> Any:
        if sql.startswith("PRAGMA table_info"):
            return []
        if sql.startswith("ALTER TABLE"):
            raise sqlite3.OperationalError(self._alter_error)
        return self._conn.execute(sql, *args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def _reopen_with_stale_columns(
    monkeypatch: pytest.MonkeyPatch, db: str, alter_error: str
) -> None:
    with store_db.connect():
        pass
    store_db._initialized.discard(db)
    real_open = store_db._open_raw_connection
    monkeypatch.setattr(
        store_db,
        "_open_raw_connection",
        lambda path: cast(
            sqlite3.Connection, _StaleColumnView(real_open(path), alter_error)
        ),
    )


def test_startup_tolerates_a_racing_process_adding_the_column(
    db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reopen_with_stale_columns(monkeypatch, db, "duplicate column name: x")
    with store_db.connect():
        pass
    assert db in store_db._initialized


def test_startup_surfaces_other_migration_failures(
    db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _reopen_with_stale_columns(monkeypatch, db, "disk I/O error")
    with (
        pytest.raises(sqlite3.OperationalError, match="disk I/O error"),
        store_db.connect(),
    ):
        pass
    assert db not in store_db._initialized


def test_wal_checkpoint_failure_is_logged_not_raised(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.store.db"):
        store_db.checkpoint_wal(str(tmp_path))
    assert "WAL checkpoint failed" in caplog.text


def _seed_cascade_children(run_id: str) -> None:
    hid = store.add_hypothesis(
        NewHypothesis(
            run_id=run_id,
            title="t",
            statement="s",
            created_by_agent="generation",
        )
    )
    eid = records.add_evidence(
        NewEvidence(run_id=run_id, title="paper", source="pubmed")
    )
    records.add_review(
        NewReview(
            run_id=run_id,
            hypothesis_id=hid,
            reviewer_agent="reflection",
            summary="sum",
            critique="crit",
        )
    )
    records.add_citation(
        NewCitation(
            run_id=run_id,
            hypothesis_id=hid,
            evidence_id=eid,
            claim="c",
            state=CitationState.VERIFIED,
        )
    )
    store_events.append_event(run_id, "log", {"i": 0})


def test_deleting_a_run_cascades_to_child_rows(db: str) -> None:
    run = seed_run("cascade", provider="mock")
    _seed_cascade_children(run.id)

    with store_db.connect() as conn:
        conn.execute("DELETE FROM runs WHERE id=?", (run.id,))

    assert store.list_hypotheses(run.id) == []
    assert records.list_evidence(run.id) == []
    assert records.list_reviews(run.id) == []
    assert records.list_citations(run.id) == []
    assert store_events.list_events(run.id) == []


_PER_RUN_LISTED_TABLES = (
    "evidence",
    "citations",
    "claim_evidence",
    "safety_decisions",
    "reviews",
    "matches",
    "proximity_edges",
)


@pytest.mark.parametrize("table", _PER_RUN_LISTED_TABLES)
def test_per_run_listing_never_scans_the_whole_table(
    db: str, table: str
) -> None:
    # Run-scoped indexes avoid scanning other runs.
    with store_db.connect() as conn:
        plan = conn.execute(
            f"EXPLAIN QUERY PLAN SELECT * FROM {table} WHERE run_id=? "
            "ORDER BY created_at ASC",
            ("any-run",),
        ).fetchall()
    detail = " ".join(row["detail"] for row in plan)
    assert f"SCAN {table}" not in detail, detail
