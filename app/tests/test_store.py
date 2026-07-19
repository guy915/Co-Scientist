"""Storage-layer invariants.

Covers the append-only event log, evidence/citation linkage, and report
survival.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app import store


@pytest.fixture
def db(isolated_db: str) -> str:
    return os.environ["COSCIENTIST_DB_PATH"]


def test_event_log_is_append_only_and_strictly_increasing(db: str) -> None:
    run = store.create_run("test", "standard", "mock", {})
    seqs = []
    for i in range(5):
        seqs.append(store.append_event(run.id, "log", {"i": i}))
    events = store.list_events(run.id)
    assert seqs == [e["seq"] for e in events]
    # Strictly monotonic.
    assert all(seqs[i] < seqs[i + 1] for i in range(4))


def test_list_events_filters_after_seq(db: str) -> None:
    run = store.create_run("filter test", "standard", "mock", {})
    for i in range(4):
        store.append_event(run.id, "log", {"i": i})
    half = store.list_events(run.id)[1]["seq"]
    after = store.list_events(run.id, after_seq=half)
    assert len(after) == 2
    for ev in after:
        assert ev["seq"] > half


def test_list_runs_reports_top_elo(db: str) -> None:
    run = store.create_run("top-elo", "standard", "mock", {})
    for rating in (1240, 1310, 1180):
        hid = store.add_hypothesis(
            run.id, title="t", statement="s", created_by_agent="generation"
        )
        store.update_hypothesis_state(hid, elo_rating=rating)
    # A second run with no hypotheses reports None rather than a stray value.
    store.create_run("no-hyps", "standard", "mock", {})

    by_goal = {r.research_goal: r for r in store.list_runs()}
    assert by_goal["top-elo"].top_elo == 1310
    assert by_goal["no-hyps"].top_elo is None
    # A single-run read does not carry the aggregate.
    assert store.get_run(run.id) is not None
    assert store.get_run(run.id).top_elo is None  # type: ignore[union-attr]


def test_list_runs_reports_top_hypotheses_by_elo(db: str) -> None:
    run = store.create_run("top-hyps", "standard", "mock", {})
    for title, rating in (("Low", 1180), ("High", 1320), ("Mid", 1250)):
        hid = store.add_hypothesis(
            run.id, title=title, statement="s", created_by_agent="generation"
        )
        store.update_hypothesis_state(hid, elo_rating=rating)
    # A run with no hypotheses reports an empty list, not None or a stray value.
    store.create_run("no-hyps", "standard", "mock", {})

    by_goal = {r.research_goal: r for r in store.list_runs()}
    # Ordered by Elo descending, so the highest-rated hypotheses lead.
    assert by_goal["top-hyps"].top_hypotheses == ["High", "Mid", "Low"]
    assert by_goal["no-hyps"].top_hypotheses == []
    # A single-run read does not carry the list enrichment.
    assert store.get_run(run.id).top_hypotheses is None  # type: ignore[union-attr]


def test_list_runs_caps_top_hypotheses_at_three(db: str) -> None:
    run = store.create_run("many-hyps", "standard", "mock", {})
    for rating in (1300, 1290, 1280, 1270, 1260):
        hid = store.add_hypothesis(
            run.id,
            title=f"h{rating}",
            statement="s",
            created_by_agent="generation",
        )
        store.update_hypothesis_state(hid, elo_rating=rating)

    listed = {r.research_goal: r for r in store.list_runs()}["many-hyps"]
    assert listed.top_hypotheses == ["h1300", "h1290", "h1280"]


def test_list_runs_reports_latest_pipeline_stage(db: str) -> None:
    run = store.create_run("staged", "standard", "mock", {})
    store.append_event(run.id, "supervisor.plan", {})
    store.append_event(run.id, "generate", {})
    store.append_event(run.id, "ranking", {})
    # A later non-stage event (status) does not shift the reported stage.
    store.append_event(run.id, "status", {"status": "running"})
    # A run with no pipeline events yet reports None.
    store.create_run("unstaged", "standard", "mock", {})

    by_goal = {r.research_goal: r for r in store.list_runs()}
    assert by_goal["staged"].latest_stage == "ranking"
    assert by_goal["unstaged"].latest_stage is None
    # A single-run read does not carry the list enrichment.
    assert store.get_run(run.id).latest_stage is None  # type: ignore[union-attr]


def test_hypothesis_state_decoupled_from_hypothesis_row(db: str) -> None:
    run = store.create_run("decoupling test", "standard", "mock", {})
    hid = store.add_hypothesis(
        run.id,
        title="t",
        statement="s",
        mechanism="m",
        expected_effect="e",
        experimental_context="x",
        created_by_agent="generation",
    )
    # Mutate state.
    store.update_hypothesis_state(hid, elo_rating=1300, win_delta=1)
    store.update_hypothesis_state(hid, elo_rating=1350, win_delta=1)
    h = store.get_hypothesis(hid)
    assert h is not None
    assert h["elo_rating"] == 1350
    assert h["win_count"] == 2
    # Original immutable fields on `hypotheses` row stay untouched.
    assert h["title"] == "t"
    assert h["statement"] == "s"


def test_evolved_hypothesis_has_parent_and_higher_generation(db: str) -> None:
    run = store.create_run("lineage", "standard", "mock", {})
    parent = store.add_hypothesis(
        run.id,
        title="P",
        statement="ps",
        created_by_agent="generation",
    )
    child = store.add_hypothesis(
        run.id,
        title="C",
        statement="cs",
        created_by_agent="evolution",
        parent_id=parent,
        generation=1,
    )
    rows = store.list_hypotheses(run.id)
    by_id = {r["id"]: r for r in rows}
    assert by_id[child]["parent_id"] == parent
    assert by_id[child]["generation"] == 1
    assert by_id[parent]["parent_id"] is None
    assert by_id[parent]["generation"] == 0


def test_redact_hypothesis_fields_overwrites_detail_columns(db: str) -> None:
    run = store.create_run("redact", "standard", "mock", {})
    hid = store.add_hypothesis(
        run.id,
        title="H",
        statement="keep me",
        mechanism="secret mechanism",
        experimental_context="secret protocol",
    )
    store.redact_hypothesis_fields(
        hid, {"mechanism": "[X]", "experimental_context": "[X]"}
    )
    row = store.get_hypothesis(hid)
    assert row is not None
    assert row["mechanism"] == "[X]"
    assert row["experimental_context"] == "[X]"
    # The statement (not a redactable detail column) is untouched.
    assert row["statement"] == "keep me"


def test_redact_hypothesis_fields_rejects_non_redactable_column(
    db: str,
) -> None:
    run = store.create_run("redact", "standard", "mock", {})
    hid = store.add_hypothesis(run.id, title="H", statement="s")
    with pytest.raises(ValueError, match="non-redactable"):
        store.redact_hypothesis_fields(hid, {"statement": "wiped"})


def test_reports_round_trip_markdown_to_disk(db: str) -> None:
    run = store.create_run("report rt", "standard", "mock", {})
    saved = store.save_report(run.id, {"k": "v"}, "# Hello\nbody", db_path=db)
    assert saved["markdown_path"].endswith(".md")
    md = store.read_report_markdown(run.id, db_path=db)
    assert md and "Hello" in md
    rep = store.get_latest_report(run.id, db_path=db)
    assert rep and rep["payload"] == {"k": "v"}


def test_safety_decision_persists_matches_array(db: str) -> None:
    run = store.create_run("safety", "standard", "mock", {})
    store.add_safety_decision(
        run.id, "intake", "block", "test reason", ["match-a", "match-b"]
    )
    rows = store.list_safety_decisions(run.id)
    assert rows[0]["decision"] == "block"
    assert rows[0]["matches"] == ["match-a", "match-b"]


def test_match_log_preserves_pre_post_elo(db: str) -> None:
    run = store.create_run("matches", "standard", "mock", {})
    store.add_match(run.id, 1, "w", "l", 1200, 1212, 1200, 1188, "rationale")
    rows = store.list_matches(run.id)
    assert rows[0]["winner_elo_before"] == 1200
    assert rows[0]["winner_elo_after"] == 1212
    assert rows[0]["loser_elo_before"] == 1200
    assert rows[0]["loser_elo_after"] == 1188


def test_match_log_records_debate_turns(db: str) -> None:
    run = store.create_run("matches", "standard", "mock", {})
    # A single-turn comparison (default) and a multi-turn scientific debate.
    store.add_match(run.id, 1, "w", "l", 1200, 1212, 1200, 1188, "single")
    store.add_match(
        run.id, 1, "w", "l", 1212, 1230, 1188, 1170, "multi", debate_turns=3
    )
    rows = store.list_matches(run.id)
    assert rows[0]["debate_turns"] == 1
    assert rows[1]["debate_turns"] == 3


# --- compact_database ------------------------------------------------------


def _free_ratio(db: str) -> float:
    """Return the share of the database file that is free pages."""
    with store.connect(db) as conn:
        pages = int(conn.execute("PRAGMA page_count").fetchone()[0])
        free = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
    return free / pages if pages else 0.0


def _bloat(db: str, rows: int = 400) -> None:
    """Insert then delete rows, leaving the file full of free pages."""
    blob = "x" * 20_000
    with store.connect(db) as conn:
        for i in range(rows):
            conn.execute(
                "INSERT INTO app_logs (created_at, level, levelno, logger, "
                "message) VALUES (0.0, 'INFO', 20, 'bloat', ?)",
                (f"{i}{blob}",),
            )
        conn.execute("DELETE FROM app_logs WHERE logger = 'bloat'")


def test_compact_reclaims_a_mostly_free_database(isolated_db: str) -> None:
    """VACUUM gives back the size that deleted rows left behind.

    Deleting rows returns pages to SQLite's freelist but never shrinks the
    file. In production the pruned checkpoints left a 390 MB file holding
    ~25 MB of live data; this is the step that hands that back.
    """
    _bloat(isolated_db)
    assert _free_ratio(isolated_db) > 0.5
    before_size = os.path.getsize(isolated_db)

    result = store.compact_database(db_path=isolated_db)

    assert result is not None
    before_mb, after_mb = result
    assert after_mb < before_mb
    assert os.path.getsize(isolated_db) < before_size
    assert _free_ratio(isolated_db) < 0.5


def test_compact_declines_a_healthy_database(isolated_db: str) -> None:
    """A database that is mostly live data is left alone.

    VACUUM rewrites the whole file, so it must not run on every startup of a
    healthy deployment.
    """
    with store.connect(isolated_db) as conn:
        conn.execute(
            "INSERT INTO app_logs (created_at, level, levelno, logger, "
            "message) VALUES (0.0, 'INFO', 20, 'live', 'kept')"
        )

    assert store.compact_database(db_path=isolated_db) is None


def test_compact_declines_without_disk_headroom(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It refuses when VACUUM's temporary copy would not fit.

    Regression in spirit: the first version of the checkpoint sweep assumed it
    could always write, and crashed the server against the full disk it was
    meant to relieve. Compaction needs room for a second copy of the file, so
    it checks before it starts rather than failing part-way.
    """
    _bloat(isolated_db)
    assert _free_ratio(isolated_db) > 0.5
    before_size = os.path.getsize(isolated_db)

    class _FullDisk:
        f_bavail = 1
        f_frsize = 4096

    monkeypatch.setattr(os, "statvfs", lambda _p: _FullDisk())

    assert store.compact_database(db_path=isolated_db) is None
    # Untouched: it declined before doing any work.
    assert os.path.getsize(isolated_db) == before_size


def test_compact_missing_database_is_a_noop(tmp_path: Path) -> None:
    """A path that does not exist yet is not an error."""
    assert store.compact_database(db_path=str(tmp_path / "absent.db")) is None
