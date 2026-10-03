"""Tests for persistence 1."""

from __future__ import annotations

import io
import json
import logging
import sqlite3
import stat
import time
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app import retention, store
from app.knowledge_facts import derive_knowledge_facts
from app.report import build as report_build
from app.report import finalize as report_finalize
from app.store import db as store_db
from app.store.events import (
    ACTIVITY_OTHER,
    ACTIVITY_VALUES,
    activity_for_event,
)
from dev.backup_db import backup_database
from tests._client import drain as _drain
from tests._client import make_client, wait_for_status
from tests._client import make_client as _client
from tests._engine_tasks_helpers import _seed_checkpoint, _task_state
from tests._store_helpers import _add

# Consistent backups preserve committed WAL data and existing files.


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_deadline_never_publishes_a_backup(
    tmp_path: Path, timeout: float
) -> None:
    source = tmp_path / "source.db"
    source.touch()
    with pytest.raises(ValueError, match="positive and finite"):
        backup_database(source, tmp_path / "backup.db", timeout)
    assert not list(tmp_path.glob("*backup*"))


def test_expired_copy_leaves_no_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE records (value TEXT)")
    ticks = iter([0.0, 2.0])
    monkeypatch.setattr("dev.backup_db.time.monotonic", lambda: next(ticks))
    with pytest.raises(TimeoutError):
        backup_database(source, tmp_path / "backup.db", timeout=1.0)
    assert not list(tmp_path.glob("*backup*"))


def test_backup_includes_committed_wal_and_has_private_permissions(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.db"
    destination = tmp_path / "backup.db"
    with sqlite3.connect(source) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE records (value TEXT)")
        connection.execute("INSERT INTO records VALUES ('committed research')")
        connection.commit()
        assert Path(f"{source}-wal").stat().st_size > 0
        backup_database(source, destination)
        assert connection.execute("SELECT * FROM records").fetchall() == [
            ("committed research",)
        ]
    with sqlite3.connect(destination) as backup:
        assert backup.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert backup.execute("SELECT * FROM records").fetchall() == [
            ("committed research",)
        ]
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(".backup.db.*"))


def test_missing_source_never_creates_an_empty_database(tmp_path: Path) -> None:
    source = tmp_path / "missing.db"
    destination = tmp_path / "backup.db"
    with pytest.raises(FileNotFoundError):
        backup_database(source, destination)
    assert not source.exists()
    assert not destination.exists()


def test_existing_destination_is_preserved(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    source.touch()
    destination = tmp_path / "backup.db"
    destination.write_bytes(b"keep the previous backup")
    with pytest.raises(FileExistsError):
        backup_database(source, destination)
    assert destination.read_bytes() == b"keep the previous backup"


def test_failed_backup_leaves_no_published_or_temporary_file(
    tmp_path: Path,
) -> None:
    source = tmp_path / "corrupt.db"
    source.write_bytes(b"not a SQLite database")
    destination = tmp_path / "backup.db"
    with pytest.raises(sqlite3.DatabaseError):
        backup_database(source, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".backup.db.*"))


# Regression coverage for migrating a *populated* legacy-schema volume.
#
# ``app.store.db._init_schema`` runs the base ``_SCHEMA`` script (every
# ``CREATE TABLE``/``CREATE INDEX ... IF NOT EXISTS``) and then
# ``_run_migrations`` (idempotent ``ALTER TABLE ADD COLUMN`` plus backfills)
# against every database on every process start -- fresh or already
# populated. On a genuinely fresh database this is close to a no-op: the
# current ``_SCHEMA`` already bakes in most historical migrations' columns
# directly into the ``CREATE TABLE`` statements, so the column only needs
# adding via ``ALTER`` on a database whose on-disk tables predate that.
# The ordinary suite -- which always starts from ``isolated_db``, a brand
# new file -- never exercises that case.
#
# It is exactly the case that matters in production: a Railway volume is a
# single on-disk file that has been through some prefix of the migration
# history, never all of it retroactively. ``db.py``'s own comments document
# the invariant this depends on -- an index built in ``_SCHEMA`` over a
# column that only ``_run_migrations`` adds would abort ``executescript``
# against a database that lacks the column yet, while a fresh database
# (which gets the column straight from ``_SCHEMA``) sails through unaffected.
# That asymmetry is exactly how a schema change can look safe locally (every
# test starts fresh) and break the first migration against the deployed
# volume. This module builds an "ancient" database by hand -- tables with
# only the pre-migration columns, populated with rows a real old volume
# would hold -- and asserts the current store starts against it cleanly and
# the migrations do what they claim, using the two migrations ``db.py``
# itself calls out as ordering-sensitive: ``app_logs.client_id`` (added,
# then immediately indexed, in ``_run_migrations`` rather than ``_SCHEMA``
# specifically to avoid this failure mode) and the ``runs`` table's
# client-isolation purge plus ``llm_backend`` backfill.
#
# Not a full replay of every ``_migrate_*`` function -- that would duplicate
# the whole migration history as a second copy to keep in sync. Extend this
# module's ancient-table fixtures when a new migration lands that shares the
# same danger shape (a column added and then referenced by an index, a
# default, or a backfill in the same or a later migration).


def _create_ancient_tables(conn: sqlite3.Connection) -> None:
    """Create ``runs``/``app_logs`` as they looked before recent migrations.

    Mirrors ``schema.py``'s current column list minus every column
    ``_run_migrations`` still adds via ``ALTER TABLE`` for these two
    tables, so this is exactly the shape a volume never yet migrated
    forward would present.
    """
    conn.executescript(
        """
        CREATE TABLE runs (
            id TEXT PRIMARY KEY,
            research_goal TEXT NOT NULL,
            profile TEXT NOT NULL,
            status TEXT NOT NULL,
            provider TEXT NOT NULL,
            config_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            completed_at REAL,
            error TEXT
        );
        CREATE TABLE app_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at REAL NOT NULL,
            level TEXT NOT NULL,
            levelno INTEGER NOT NULL,
            logger TEXT NOT NULL,
            message TEXT NOT NULL,
            run_id TEXT,
            exc_text TEXT
        );
        """
    )


def _insert_ancient_run(
    conn: sqlite3.Connection, run_id: str, provider: str
) -> None:
    conn.execute(
        "INSERT INTO runs (id, research_goal, profile, status, provider, "
        "config_json, created_at, updated_at) "
        "VALUES (?, 'legacy goal', 'standard', 'completed', ?, '{}', 1, 1)",
        (run_id, provider),
    )


def test_migrating_a_pre_isolation_volume_purges_orphaned_runs(
    isolated_db: str,
) -> None:
    """A volume from before client isolation loses its unowned run rows.

    This is destructive by design (``_migrate_client_isolation``'s purge,
    documented in ``db.py``) -- unowned rows are invisible to every client
    once ownership exists, so keeping them serves no one. The point under
    test is that migrating this exact legacy shape does not raise, and
    ``app_logs`` -- which has no purge, only an added, indexed column --
    keeps its pre-existing row intact.
    """
    raw = sqlite3.connect(isolated_db)
    try:
        _create_ancient_tables(raw)
        _insert_ancient_run(raw, "legacy-run-1", "engine")
        raw.execute(
            "INSERT INTO app_logs (created_at, level, levelno, logger, "
            "message) VALUES (1, 'INFO', 20, 'app.test', 'legacy line')"
        )
        raw.commit()
    finally:
        raw.close()

    # Any store call establishes the connection and runs _init_schema.
    assert store.get_run("legacy-run-1", db_path=isolated_db) is None

    with store_db.connect(isolated_db) as conn:
        app_log_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(app_logs)")
        }
        assert "client_id" in app_log_cols
        indexes = {
            row[1] for row in conn.execute("PRAGMA index_list(app_logs)")
        }
        assert "idx_app_logs_client" in indexes
        rows = conn.execute(
            "SELECT message, client_id FROM app_logs"
        ).fetchall()
        assert [tuple(r) for r in rows] == [("legacy line", None)]


def test_migrating_a_client_isolated_volume_backfills_llm_backend(
    isolated_db: str,
) -> None:
    """A volume already carrying client_id still needs llm_backend backfilled.

    Simulates a volume that already went through client isolation (an
    earlier deploy) but predates the offline/real backend column -- so the
    purge above must not fire again (both rows survive) while the backfill
    still runs, keyed on each row's own provider.
    """
    raw = sqlite3.connect(isolated_db)
    try:
        _create_ancient_tables(raw)
        raw.execute(
            "ALTER TABLE runs ADD COLUMN client_id TEXT NOT NULL DEFAULT ''"
        )
        _insert_ancient_run(raw, "legacy-mock-run", "mock")
        _insert_ancient_run(raw, "legacy-engine-run", "engine")
        raw.execute(
            "UPDATE runs SET client_id = 'legacy-client' WHERE id IN "
            "('legacy-mock-run', 'legacy-engine-run')"
        )
        raw.commit()
    finally:
        raw.close()

    mock_run = store.get_run("legacy-mock-run", db_path=isolated_db)
    engine_run = store.get_run("legacy-engine-run", db_path=isolated_db)

    assert mock_run is not None and mock_run.llm_backend == "offline"
    assert engine_run is not None and engine_run.llm_backend == "real"


def test_migrating_a_volume_with_the_retired_feedback_table_drops_it(
    isolated_db: str,
) -> None:
    """A volume carrying the retired pilot-feedback table loses it cleanly.

    The current schema no longer creates ``feedback`` at all, so this is
    the one migration only a populated legacy volume exercises: build the
    table by hand, as an old deploy would still have it, and confirm the
    ``DROP TABLE IF EXISTS`` migration removes it without raising.
    """
    raw = sqlite3.connect(isolated_db)
    try:
        _create_ancient_tables(raw)
        raw.execute(
            "CREATE TABLE feedback (id INTEGER PRIMARY KEY, "
            "client_id TEXT NOT NULL, audience TEXT NOT NULL, "
            "category TEXT NOT NULL, message TEXT NOT NULL, "
            "created_at REAL NOT NULL)"
        )
        raw.execute(
            "INSERT INTO feedback (client_id, audience, category, message, "
            "created_at) VALUES ('c1', 'general', 'bug', 'old note', 1)"
        )
        raw.commit()
    finally:
        raw.close()

    # Any store call establishes the connection and runs _init_schema plus
    # _run_migrations, which is where the drop happens.
    assert store.get_run("does-not-exist", db_path=isolated_db) is None

    with store_db.connect(isolated_db) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "feedback" not in tables


# Tests for durable structured fact/contradiction derivation (audit G14).
#
# ``derive_knowledge_facts`` is a pure function (no DB), tested directly here.
# Store round-trip and the report-finalize wiring are covered in
# ``test_store_knowledge_facts.py``.


def _edge(
    label: str,
    claim: str = "IL-6 increases inflammation via STAT3 signaling.",
    **over: Any,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "hypothesis_id": "h1",
        "claim": claim,
        "label": label,
        "supporting": [],
        "contradicting": [],
    }
    base.update(over)
    return base


def test_supports_edge_becomes_a_fact() -> None:
    """A ``supports`` edge becomes a durable "fact" row."""
    facts = derive_knowledge_facts([_edge("supports")])
    assert len(facts) == 1
    assert facts[0]["kind"] == "fact"
    assert facts[0]["state"] == "supports"


def test_contradicts_edge_becomes_a_contradiction() -> None:
    """A ``contradicts`` edge becomes a durable "contradiction" row."""
    facts = derive_knowledge_facts([_edge("contradicts")])
    assert len(facts) == 1
    assert facts[0]["kind"] == "contradiction"
    assert facts[0]["state"] == "contradicts"


def test_insufficient_edge_is_dropped() -> None:
    """An insufficient edge asserts nothing and is not carried over."""
    facts = derive_knowledge_facts([_edge("insufficient")])
    assert facts == []


def test_edge_with_no_claim_text_is_dropped() -> None:
    """A settled edge with blank claim text produces no row either way."""
    facts = derive_knowledge_facts([_edge("supports", claim="  ")])
    assert facts == []


def test_fact_carries_the_statement_and_hypothesis() -> None:
    facts = derive_knowledge_facts(
        [_edge("supports", claim="TREM2 promotes microglial phagocytosis.")]
    )
    assert facts[0]["statement"] == "TREM2 promotes microglial phagocytosis."
    assert facts[0]["hypothesis_id"] == "h1"


def test_fact_extracts_entities_from_the_claim() -> None:
    """Entities mentioned in the claim text are tagged onto the row."""
    facts = derive_knowledge_facts(
        [_edge("supports", claim="TREM2 promotes microglial clearance.")]
    )
    assert "TREM2" in facts[0]["entities"]


def test_fact_evidence_id_comes_from_the_supporting_spans() -> None:
    """A fact's evidence id is read from supporting, not contradicting."""
    facts = derive_knowledge_facts(
        [
            _edge(
                "supports",
                supporting=[{"evidence_id": "ev-1"}],
                contradicting=[{"evidence_id": "ev-wrong"}],
            )
        ]
    )
    assert facts[0]["evidence_id"] == "ev-1"


def test_contradiction_evidence_id_comes_from_the_contradicting_spans() -> None:
    """A contradiction's evidence id is read from contradicting.

    Not from supporting -- the two labels' evidence lives in different span
    lists on the same edge.
    """
    facts = derive_knowledge_facts(
        [
            _edge(
                "contradicts",
                supporting=[{"evidence_id": "ev-wrong"}],
                contradicting=[{"evidence_id": "ev-2"}],
            )
        ]
    )
    assert facts[0]["evidence_id"] == "ev-2"


def test_fact_evidence_id_is_none_without_a_span() -> None:
    """A settled edge with no evidence-id span leaves evidence_id None."""
    facts = derive_knowledge_facts([_edge("supports")])
    assert facts[0]["evidence_id"] is None


def test_mixed_edges_only_keep_settled_ones() -> None:
    """A mixed batch keeps supports/contradicts, dropping insufficient."""
    edges = [
        _edge("supports", claim="A supports claim."),
        _edge("insufficient", claim="An insufficient claim."),
        _edge("contradicts", claim="A contradicts claim."),
    ]
    facts = derive_knowledge_facts(edges)
    assert [f["statement"] for f in facts] == [
        "A supports claim.",
        "A contradicts claim.",
    ]


# Tests for the messages store layer.


def test_append_and_list_messages(isolated_db: str) -> None:
    store.create_run(
        "rg",
        "standard",
        "mock",
        {},
        store.RunCreateOptions(client_id="c1", db_path=isolated_db),
    )
    runs = store.list_runs(client_id="c1", db_path=isolated_db)
    run_id = runs[0].id

    store.append_message(
        store.NewMessage(
            run_id=run_id,
            sender="user",
            content="focus on cytokines",
            kind="steering",
        ),
        db_path=isolated_db,
    )
    store.append_message(
        store.NewMessage(
            run_id=run_id,
            sender="system",
            content="Research plan ready",
            kind="milestone",
        ),
        db_path=isolated_db,
    )

    msgs = store.list_messages(run_id, db_path=isolated_db)
    assert len(msgs) == 2
    assert msgs[0].sender == "user"
    assert msgs[0].kind == "steering"
    assert msgs[0].applied is False
    assert msgs[1].kind == "milestone"


def test_get_pending_steering(isolated_db: str) -> None:
    store.create_run(
        "rg",
        "standard",
        "mock",
        {},
        store.RunCreateOptions(client_id="c1", db_path=isolated_db),
    )
    run_id = store.list_runs(client_id="c1", db_path=isolated_db)[0].id

    store.append_message(
        store.NewMessage(
            run_id=run_id, sender="user", content="steer A", kind="steering"
        ),
        db_path=isolated_db,
    )
    store.append_message(
        store.NewMessage(
            run_id=run_id,
            sender="system",
            content="milestone msg",
            kind="milestone",
        ),
        db_path=isolated_db,
    )
    store.append_message(
        store.NewMessage(
            run_id=run_id, sender="user", content="steer B", kind="steering"
        ),
        db_path=isolated_db,
    )

    pending = store.get_pending_steering(run_id, db_path=isolated_db)
    assert len(pending) == 2
    assert all(m.kind == "steering" for m in pending)
    assert all(m.applied is False for m in pending)


def test_mark_steering_applied(isolated_db: str) -> None:
    store.create_run(
        "rg",
        "standard",
        "mock",
        {},
        store.RunCreateOptions(client_id="c1", db_path=isolated_db),
    )
    run_id = store.list_runs(client_id="c1", db_path=isolated_db)[0].id

    store.append_message(
        store.NewMessage(
            run_id=run_id, sender="user", content="steer A", kind="steering"
        ),
        db_path=isolated_db,
    )
    store.append_message(
        store.NewMessage(
            run_id=run_id, sender="user", content="steer B", kind="steering"
        ),
        db_path=isolated_db,
    )

    pending = store.get_pending_steering(run_id, db_path=isolated_db)
    ids = [m.id for m in pending]
    store.mark_steering_applied(ids, db_path=isolated_db)

    after = store.get_pending_steering(run_id, db_path=isolated_db)
    assert len(after) == 0

    all_msgs = store.list_messages(run_id, db_path=isolated_db)
    assert all(m.applied is True for m in all_msgs)


def test_queued_steering_flags_engine_pending_steering(
    isolated_db: str,
) -> None:
    """Queued steering makes the engine opts carry a high-priority flag (M7).

    The real engine's orchestrator treats ``pending_steering`` as a
    high-priority request to generate anew; the adapter must set it when
    steering is queued (in addition to folding the text into preferences).
    """
    from app.engine_adapter.opts import build_engine_opts

    run = store.create_run(
        "rg",
        "standard",
        "engine",
        {},
        store.RunCreateOptions(db_path=isolated_db),
    )
    store.append_message(
        store.NewMessage(
            run_id=run.id,
            sender="user",
            content="focus on kinase X",
            kind="steering",
        ),
        db_path=isolated_db,
    )

    opts = build_engine_opts(run.config, run.id, isolated_db)
    assert opts.get("pending_steering") is True
    # The steering text is also folded into the preferences context.
    assert "kinase X" in str(opts.get("preferences") or "")


def test_no_steering_leaves_pending_flag_unset(isolated_db: str) -> None:
    from app.engine_adapter.opts import build_engine_opts

    run = store.create_run(
        "rg",
        "standard",
        "engine",
        {},
        store.RunCreateOptions(db_path=isolated_db),
    )
    opts = build_engine_opts(run.config, run.id, isolated_db)
    assert "pending_steering" not in opts


def test_engine_opts_bind_private_attachment_context(isolated_db: str) -> None:
    """A consented attachment becomes engine literature and citation context."""
    from app.engine_adapter.opts import build_engine_opts

    run = store.create_run(
        "kinase AML",
        "standard",
        "engine",
        {},
        store.RunCreateOptions(db_path=isolated_db),
    )
    store.add_evidence(
        store.NewEvidence(
            run_id=run.id,
            title="Private kinase result",
            source="attachment",
            abstract="Kinase X inhibition reduced AML growth in donor samples.",
        ),
        db_path=isolated_db,
    )

    opts = build_engine_opts(run.config, run.id, isolated_db)

    sources = opts["context_enrichment_sources"]
    assert sources[0]["source_type"] == "private_document"
    assert sources[0]["tool_id"] == "private_corpus"
    assert "Kinase X" in opts["user_inputs"]["literature"][0]


def test_message_to_dict(isolated_db: str) -> None:
    store.create_run(
        "rg",
        "standard",
        "mock",
        {},
        store.RunCreateOptions(client_id="c1", db_path=isolated_db),
    )
    run_id = store.list_runs(client_id="c1", db_path=isolated_db)[0].id

    msg = store.append_message(
        store.NewMessage(
            run_id=run_id, sender="user", content="hello", kind="steering"
        ),
        db_path=isolated_db,
    )
    d = msg.to_dict()
    assert d["sender"] == "user"
    assert d["content"] == "hello"
    assert d["kind"] == "steering"
    assert d["applied"] is False
    assert "id" in d
    assert "created_at" in d


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


def _make_run(client: TestClient, goal: str = "test goal") -> str:
    client.headers.update({"X-Client-ID": "test-client"})
    res = client.post(
        "/api/runs",
        json={"research_goal": goal, "tier": "express"},
    )
    assert res.status_code == 200
    return cast(str, res.json()["id"])


def test_send_message_endpoint(isolated_db: str) -> None:
    client = _client()
    run_id = _make_run(client)

    res = client.post(
        f"/api/runs/{run_id}/messages", json={"content": "focus on cytokines"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["kind"] == "steering"
    assert data["status"] == "queued"
    assert data["content"] == "focus on cytokines"
    assert data["continuation_task_id"] is None


def test_steering_reopens_completed_engine_run(isolated_db: str) -> None:
    """Post-report steering continues from the durable engine checkpoint."""
    client = _client()
    client.headers.update({"X-Client-ID": "test-client"})
    run = store.create_run(
        "Completed research",
        "standard",
        "engine",
        {},
        store.RunCreateOptions(client_id="test-client", db_path=isolated_db),
    )
    state = {
        **_task_state(run.id),
        "research_goal": run.research_goal,
        "current_iteration": 1,
        "start_time": 1.0,
    }
    _seed_checkpoint(
        run.id, state, stage="engine_task:final", db_path=isolated_db
    )
    store.update_run_status(
        run.id, store.RunStatus.COMPLETED, db_path=isolated_db
    )

    response = client.post(
        f"/api/runs/{run.id}/messages",
        json={"content": "Test the mechanism in organoids next."},
    )

    assert response.status_code == 200
    assert response.json()["continuation_task_id"] is not None
    reopened = store.get_run(run.id, db_path=isolated_db)
    assert reopened is not None and reopened.status == "queued"
    tasks = store.list_tasks(run.id, db_path=isolated_db)
    assert tasks[-1].task_type == "engine.node.orchestrator"
    assert tasks[-1].priority == 100


def test_send_message_always_stores_as_steering(isolated_db: str) -> None:
    """POST /messages always stores as steering.

    Q&A routing is the frontend's job.
    """
    client = _client()
    run_id = _make_run(client)

    res = client.post(
        f"/api/runs/{run_id}/messages",
        json={"content": "Why did hypothesis 3 drop?"},
    )
    assert res.status_code == 200
    assert res.json()["kind"] == "steering"


def test_list_messages_endpoint(isolated_db: str) -> None:
    client = _client()
    run_id = _make_run(client)

    client.post(f"/api/runs/{run_id}/messages", json={"content": "steer A"})
    client.post(f"/api/runs/{run_id}/messages", json={"content": "steer B"})

    res = client.get(f"/api/runs/{run_id}/messages")
    assert res.status_code == 200
    msgs = res.json()["messages"]
    assert len(msgs) == 2
    assert msgs[0]["content"] == "steer A"
    assert msgs[1]["content"] == "steer B"


def test_list_messages_404_on_unknown_run(isolated_db: str) -> None:
    client = _client()
    res = client.get("/api/runs/nonexistent-id/messages")
    assert res.status_code == 404


def test_steering_messages_applied_after_run(isolated_db: str) -> None:
    """Steering messages sent before a run starts are applied later.

    They should be marked applied when the run completes.
    """
    client = _client()
    run_id = _make_run(client, goal="test steering injection")

    client.post(
        f"/api/runs/{run_id}/messages",
        json={"content": "focus on apoptosis pathways", "kind": "steering"},
    )

    msgs_before = client.get(f"/api/runs/{run_id}/messages").json()["messages"]
    assert msgs_before[0]["applied"] is False

    client.post(f"/api/runs/{run_id}/start", json={})
    wait_for_status(client, run_id, "completed", timeout=20.0, interval=0.1)

    msgs_after = client.get(f"/api/runs/{run_id}/messages").json()["messages"]
    steering = [m for m in msgs_after if m["kind"] == "steering"]
    assert len(steering) == 1
    assert steering[0]["applied"] is True


def test_milestone_messages_generated_by_durable_run(
    isolated_db: str,
) -> None:
    """The durable run surfaces node milestones as system chat messages.

    Every durable node commit emits the same milestone side-messages the
    frontend shows (via ``append_node_milestone``). Drive a run through the
    durable node executor (the surface ``/start`` uses) and assert the
    milestone messages land, each authored by ``system``.
    """
    import asyncio

    from app import task_worker

    run = store.create_run(
        "test milestone generation",
        "express",
        "engine",
        {"tier": "express"},
        store.RunCreateOptions(
            client_id="test-client",
            llm_backend="offline",
            db_path=isolated_db,
        ),
    )
    task_worker.enqueue_run_workflow(run.id, db_path=isolated_db)
    asyncio.run(
        task_worker.run_run_worker_pool(
            run.id,
            "milestone-test",
            policy=task_worker.WorkerPolicy(db_path=isolated_db),
        )
    )

    msgs = store.list_messages(run.id, db_path=isolated_db)
    milestones = [m for m in msgs if m.kind == "milestone"]
    assert len(milestones) >= 1
    assert all(m.sender == "system" for m in milestones)


# Tests for the time-based retention sweep (N4): app.retention.


def _backdate_completion(db_path: str, run_id: str, seconds_ago: float) -> None:
    """Force a run's completed_at/updated_at into the past for a test.

    ``store`` has no setter for this (a real run's timestamps are always
    "now" when it settles), so the sweep's age judgment is exercised here
    by writing the column directly rather than by waiting out real time.
    """
    backdated = time.time() - seconds_ago
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE runs SET completed_at=?, updated_at=? WHERE id=?",
            (backdated, backdated, run_id),
        )


def test_run_retention_days_defaults_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COSCIENTIST_RUN_RETENTION_DAYS", raising=False)
    assert retention.run_retention_days() == 90


def test_run_retention_days_reads_the_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COSCIENTIST_RUN_RETENTION_DAYS", "5")
    assert retention.run_retention_days() == 5


def test_zero_disables_the_run_sweep(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COSCIENTIST_RUN_RETENTION_DAYS", "0")
    client = make_client()
    created = client.post(
        "/api/runs",
        headers={"X-Client-ID": "retention-tester"},
        json={"research_goal": "Old completed goal"},
    )
    run_id = created.json()["id"]
    store.update_run_status(run_id, store.RunStatus.COMPLETED)

    deleted = retention.sweep_expired_runs(now=time.time() + 10_000 * 86_400)

    assert deleted == []
    assert store.run_exists(run_id)


def test_sweep_deletes_only_terminal_runs_past_the_window(
    isolated_db: str,
) -> None:
    client = make_client()
    old_completed = client.post(
        "/api/runs",
        headers={"X-Client-ID": "retention-tester"},
        json={"research_goal": "Old completed goal"},
    ).json()["id"]
    store.update_run_status(old_completed, store.RunStatus.COMPLETED)
    _backdate_completion(isolated_db, old_completed, 120 * 86_400)

    old_running = client.post(
        "/api/runs",
        headers={"X-Client-ID": "retention-tester"},
        json={"research_goal": "Old but still running"},
    ).json()["id"]
    store.update_run_status(old_running, store.RunStatus.RUNNING)
    _backdate_completion(isolated_db, old_running, 120 * 86_400)

    recent_completed = client.post(
        "/api/runs",
        headers={"X-Client-ID": "retention-tester"},
        json={"research_goal": "Just completed"},
    ).json()["id"]
    store.update_run_status(recent_completed, store.RunStatus.COMPLETED)

    # Only the completed row backdated past the default 90-day window
    # should be swept.
    deleted = retention.sweep_expired_runs()

    assert deleted == [old_completed]
    assert not store.run_exists(old_completed)
    assert store.run_exists(old_running)  # never terminal -> never swept
    assert store.run_exists(recent_completed)  # not yet expired


def test_sweep_expired_documents_deletes_only_past_the_window(
    isolated_db: str,
) -> None:
    client = make_client()
    staged = client.post(
        "/api/documents",
        headers={"X-Client-ID": "retention-tester"},
        files={"file": ("notes.txt", io.BytesIO(b"old notes"), "text/plain")},
        data={"consent": "true"},
    )
    document_id = staged.json()["id"]

    far_future = time.time() + 200 * 86_400
    deleted = retention.sweep_expired_documents(now=far_future)

    assert deleted == 1
    assert store.get_staged_documents([document_id], "retention-tester") == []


# Tests for durable workflow-checkpoint persistence (Milestone 4).


def _run(db: str) -> str:
    return store.create_run(
        "goal", "standard", "mock", {}, store.RunCreateOptions(db_path=db)
    ).id


def test_save_and_get_latest_checkpoint(isolated_db: str) -> None:
    """Saving checkpoints assigns monotonic seqs; latest is returned."""
    run_id = _run(isolated_db)
    assert store.get_latest_checkpoint(run_id, db_path=isolated_db) is None
    assert not store.has_checkpoint(run_id, db_path=isolated_db)

    seq1 = store.save_checkpoint(
        run_id,
        store.NewCheckpoint(
            stage="post_generation",
            schema_version=1,
            last_event_seq=5,
            state={"hyp_ids": ["a", "b"]},
        ),
        db_path=isolated_db,
    )
    seq2 = store.save_checkpoint(
        run_id,
        store.NewCheckpoint(
            stage="post_ranking",
            schema_version=1,
            last_event_seq=12,
            state={"hyp_ids": ["a", "b"], "round": 1},
        ),
        db_path=isolated_db,
    )
    assert (seq1, seq2) == (1, 2)
    assert store.has_checkpoint(run_id, db_path=isolated_db)

    latest = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None
    assert latest["seq"] == 2
    assert latest["stage"] == "post_ranking"
    assert latest["last_event_seq"] == 12
    assert latest["state"] == {"hyp_ids": ["a", "b"], "round": 1}


def test_checkpoints_are_run_scoped(isolated_db: str) -> None:
    """A checkpoint belongs only to its run."""
    run_a = _run(isolated_db)
    run_b = _run(isolated_db)
    store.save_checkpoint(
        run_a,
        store.NewCheckpoint(
            stage="s", schema_version=1, last_event_seq=1, state={"x": 1}
        ),
        db_path=isolated_db,
    )
    assert store.has_checkpoint(run_a, db_path=isolated_db)
    assert not store.has_checkpoint(run_b, db_path=isolated_db)


def _count(db: str) -> int:
    """Return the total number of checkpoint rows across all runs."""
    with store.connect(db) as conn:
        return int(
            conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
        )


def _seed_raw_checkpoints(db: str, run_id: str, count: int) -> None:
    """Insert ``count`` checkpoint rows directly, bypassing the prune path."""
    with store.connect(db) as conn:
        for i in range(1, count + 1):
            conn.execute(
                "INSERT INTO checkpoints (run_id, seq, stage, schema_version, "
                "last_event_seq, state_json, created_at) "
                "VALUES (?, ?, ?, 1, ?, ?, 0.0)",
                (run_id, i, f"stage_{i}", i, f'{{"round": {i}}}'),
            )


def test_saving_prunes_the_checkpoints_it_supersedes(isolated_db: str) -> None:
    """Only the newest checkpoint survives, because only it is readable.

    Regression: every boundary crossed used to leave a full WorkflowState
    snapshot behind forever. In production that grew the checkpoints table to
    380 MB -- 97% of the database -- and filled the volume until every write
    failed with "database or disk is full".
    """
    run_id = _run(isolated_db)
    for i in range(5):
        store.save_checkpoint(
            run_id,
            store.NewCheckpoint(
                stage=f"stage_{i}",
                schema_version=1,
                last_event_seq=i,
                state={"round": i},
            ),
            db_path=isolated_db,
        )

    assert _count(isolated_db) == 1
    latest = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None
    # Pruning must not disturb the seq counter: it is assigned as MAX(seq) + 1
    # and the bootstrap path asserts on it.
    assert latest["seq"] == 5
    assert latest["stage"] == "stage_4"
    assert latest["state"] == {"round": 4}
    assert store.has_checkpoint(run_id, db_path=isolated_db)


def test_pruning_is_per_run(isolated_db: str) -> None:
    """One run's checkpoints are never pruned by another run's progress."""
    first, second = _run(isolated_db), _run(isolated_db)
    for run_id in (first, second):
        for i in range(3):
            store.save_checkpoint(
                run_id,
                store.NewCheckpoint(
                    stage=f"s{i}",
                    schema_version=1,
                    last_event_seq=i,
                    state={"run": run_id, "round": i},
                ),
                db_path=isolated_db,
            )

    assert _count(isolated_db) == 2
    for run_id in (first, second):
        latest = store.get_latest_checkpoint(run_id, db_path=isolated_db)
        assert latest is not None
        assert latest["state"]["run"] == run_id
        assert latest["seq"] == 3


def test_prune_superseded_reclaims_pre_existing_history(
    isolated_db: str,
) -> None:
    """The startup sweep applies the rule to a database written without it.

    Simulates the production database: rows inserted directly, bypassing the
    pruning write path, exactly as the old code left them.
    """
    run_id = _run(isolated_db)
    _seed_raw_checkpoints(isolated_db, run_id, 20)
    assert _count(isolated_db) == 20

    deleted = store.prune_superseded_checkpoints(db_path=isolated_db)

    assert deleted == 19
    assert _count(isolated_db) == 1
    # The run is still resumable, from precisely the boundary it reached.
    latest = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None
    assert latest["seq"] == 20
    assert latest["state"] == {"round": 20}


def test_prune_superseded_is_idempotent(isolated_db: str) -> None:
    """Safe to run on every startup: a second sweep finds nothing to do."""
    run_id = _run(isolated_db)
    store.save_checkpoint(
        run_id,
        store.NewCheckpoint(
            stage="only", schema_version=1, last_event_seq=1, state={}
        ),
        db_path=isolated_db,
    )

    assert store.prune_superseded_checkpoints(db_path=isolated_db) == 0
    assert store.prune_superseded_checkpoints(db_path=isolated_db) == 0
    assert store.has_checkpoint(run_id, db_path=isolated_db)


def test_prune_batches_and_folds_the_wal_between_batches(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sweep must survive the full disk it exists to relieve.

    Regression: the first version issued one DELETE for the whole history and
    ran at startup. On the full production volume the write failed with
    SQLITE_FULL, the statement rolled back whole -- reclaiming nothing -- and
    the exception took the server down with it. Now the WAL is folded back
    first, for headroom, and each small batch commits before the next is
    attempted, so partial progress survives a volume that is still full.
    """
    from app.store import checkpoints as checkpoints_module

    run_id = _run(isolated_db)
    _seed_raw_checkpoints(isolated_db, run_id, 11)

    checkpoints: list[int] = []
    real_checkpoint_wal = store.checkpoint_wal

    def _record(db_path: str | None = None) -> None:
        checkpoints.append(_count(isolated_db))
        real_checkpoint_wal(db_path)

    monkeypatch.setattr(checkpoints_module, "checkpoint_wal", _record)

    deleted = store.prune_superseded_checkpoints(db_path=isolated_db)

    assert deleted == 10
    assert _count(isolated_db) == 1
    # Several bounded batches rather than one all-or-nothing statement, each
    # one committed before the next is journalled.
    assert len(checkpoints) >= 2
    assert checkpoints == sorted(checkpoints, reverse=True)
    latest = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert latest is not None
    assert latest["seq"] == 11


# Tests for the ``activity`` discriminator on run_events payloads.
#
# Covers the pure mapping (``activity_for_event``), its coverage of every
# engine node, and the round trip through ``store.append_event``/
# ``list_events`` including backward compatibility with events persisted
# before this field existed.


def test_known_node_types_map_to_their_activity() -> None:
    assert activity_for_event("supervisor.plan", {}) == "planning"
    assert activity_for_event("literature_review", {}) == "literature_search"
    assert activity_for_event("generate", {}) == "drafting"
    assert activity_for_event("reflection", {}) == "review"
    assert activity_for_event("ranking", {}) == "tournament"
    assert activity_for_event("evolve", {}) == "evolution"
    assert activity_for_event("proximity", {}) == "deduplication"
    assert activity_for_event("meta_review", {}) == "synthesis"
    assert activity_for_event("safety_screen", {}) == "safety"


def test_scientific_task_reads_node_name_from_payload_task() -> None:
    payload = {"task": "ranking", "status": "completed"}
    assert activity_for_event("scientific_task", payload) == "tournament"


def test_unknown_stage_maps_to_catch_all_never_raises() -> None:
    assert activity_for_event("some_future_node", {}) == ACTIVITY_OTHER
    assert (
        activity_for_event("scientific_task", {"task": "nonexistent"})
        == ACTIVITY_OTHER
    )
    assert activity_for_event("lifecycle", {"event": "queued"}) == (
        ACTIVITY_OTHER
    )


def test_every_node_in_node_to_agent_has_an_activity() -> None:
    """A node added to the engine without an activity must not go unnoticed."""
    from co_scientist.agents import NODE_TO_AGENT

    for node_name in NODE_TO_AGENT:
        activity = activity_for_event(node_name, {})
        assert activity in ACTIVITY_VALUES
        assert activity != ACTIVITY_OTHER, (
            f"node {node_name!r} has no activity mapping"
        )


def test_append_event_persists_activity_inside_payload(
    isolated_db: str,
) -> None:
    run = store.create_run("activity test", "standard", "mock", {})
    store.append_event(run.id, "ranking", {"iteration": 1})
    events = store.list_events(run.id)
    assert events[-1]["payload"]["activity"] == "tournament"


def test_list_events_reads_row_persisted_without_activity_key(
    isolated_db: str,
) -> None:
    """A run resumed across this deploy replays events with no ``activity``.

    Simulates that by inserting a row directly, bypassing ``append_event``'s
    activity computation entirely.
    """
    run = store.create_run("legacy row test", "standard", "mock", {})
    old_payload = {"status": "completed"}
    with sqlite3.connect(isolated_db) as conn:
        conn.execute(
            "INSERT INTO run_events (run_id, seq, type, payload_json, "
            "created_at) VALUES (?, 1, 'status', ?, 0)",
            (run.id, json.dumps(old_payload)),
        )
        conn.commit()
    events = store.list_events(run.id)
    assert events[0]["payload"] == old_payload
    assert "activity" not in events[0]["payload"]


# Store round-trip and report-finalize wiring for knowledge facts (G14).
#
# ``derive_knowledge_facts`` itself (pure, no DB) is tested in
# ``test_knowledge_facts.py``; this file covers the durable store I/O
# (``replace_knowledge_facts``/``list_knowledge_facts``) and the real
# end-to-end path: a run's report finalizing actually persists rows a caller
# can read back, including through the collections endpoint.


_SUPPORTED = "IL-6 increases inflammation via STAT3 signaling."


async def _emit(type_: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": type_, "payload": payload}


def _finalize(run: Any, db_path: str) -> None:
    """Run the real finalize_report pipeline (safety gate + persistence)."""
    _drain(
        report_finalize.finalize_report(
            run.id,
            report_build.ReportRequest(
                research_goal=run.research_goal,
                run_mode="standard",
                provider="engine",
                execution_time=1.0,
                db_path=db_path,
            ),
            _emit,
        )
    )


# --- store round-trip --------------------------------------------------


def test_replace_and_list_round_trip(isolated_db: str) -> None:
    run = store.create_run("kf goal", "standard", "mock", {})
    hyp_id = _add(run.id, "H", _SUPPORTED, isolated_db)
    facts = [
        {
            "hypothesis_id": hyp_id,
            "evidence_id": "ev-1",
            "kind": "fact",
            "statement": "IL-6 increases inflammation.",
            "entities": ["IL6"],
            "state": "supports",
        }
    ]

    store.replace_knowledge_facts(run.id, facts, db_path=isolated_db)
    rows = store.list_knowledge_facts(run.id, db_path=isolated_db)

    assert len(rows) == 1
    assert rows[0]["kind"] == "fact"
    assert rows[0]["statement"] == "IL-6 increases inflammation."
    assert rows[0]["entities"] == ["IL6"]
    assert rows[0]["evidence_id"] == "ev-1"


def test_replace_clears_prior_rows(isolated_db: str) -> None:
    """A second replace fully supersedes the first -- no accumulation."""
    run = store.create_run("kf goal", "standard", "mock", {})
    hyp_id = _add(run.id, "H", _SUPPORTED, isolated_db)
    first = [
        {
            "hypothesis_id": hyp_id,
            "kind": "fact",
            "statement": "First.",
            "entities": [],
            "state": "supports",
        }
    ]
    second = [
        {
            "hypothesis_id": hyp_id,
            "kind": "contradiction",
            "statement": "Second.",
            "entities": [],
            "state": "contradicts",
        }
    ]

    store.replace_knowledge_facts(run.id, first, db_path=isolated_db)
    store.replace_knowledge_facts(run.id, second, db_path=isolated_db)
    rows = store.list_knowledge_facts(run.id, db_path=isolated_db)

    assert len(rows) == 1
    assert rows[0]["statement"] == "Second."


def test_list_filters_by_kind(isolated_db: str) -> None:
    run = store.create_run("kf goal", "standard", "mock", {})
    hyp_id = _add(run.id, "H", _SUPPORTED, isolated_db)
    store.replace_knowledge_facts(
        run.id,
        [
            {
                "hypothesis_id": hyp_id,
                "kind": "fact",
                "statement": "A fact.",
                "entities": [],
                "state": "supports",
            },
            {
                "hypothesis_id": hyp_id,
                "kind": "contradiction",
                "statement": "A contradiction.",
                "entities": [],
                "state": "contradicts",
            },
        ],
        db_path=isolated_db,
    )

    facts_only = store.list_knowledge_facts(
        run.id, kind="fact", db_path=isolated_db
    )
    assert [r["statement"] for r in facts_only] == ["A fact."]


def test_list_filters_by_entity_case_insensitively(isolated_db: str) -> None:
    run = store.create_run("kf goal", "standard", "mock", {})
    hyp_id = _add(run.id, "H", _SUPPORTED, isolated_db)
    store.replace_knowledge_facts(
        run.id,
        [
            {
                "hypothesis_id": hyp_id,
                "kind": "fact",
                "statement": "About TREM2.",
                "entities": ["TREM2"],
                "state": "supports",
            },
            {
                "hypothesis_id": hyp_id,
                "kind": "fact",
                "statement": "About KRAS.",
                "entities": ["KRAS"],
                "state": "supports",
            },
        ],
        db_path=isolated_db,
    )

    matched = store.list_knowledge_facts(
        run.id, entity="trem2", db_path=isolated_db
    )
    assert [r["statement"] for r in matched] == ["About TREM2."]


def test_facts_are_scoped_per_run(isolated_db: str) -> None:
    """A fact belongs to exactly one run -- G14's per-run-only requirement."""
    run_a = store.create_run("goal a", "standard", "mock", {})
    run_b = store.create_run("goal b", "standard", "mock", {})
    hyp_a = _add(run_a.id, "H", _SUPPORTED, isolated_db)
    store.replace_knowledge_facts(
        run_a.id,
        [
            {
                "hypothesis_id": hyp_a,
                "kind": "fact",
                "statement": "Only in run A.",
                "entities": [],
                "state": "supports",
            }
        ],
        db_path=isolated_db,
    )

    assert store.list_knowledge_facts(run_b.id, db_path=isolated_db) == []
    assert len(store.list_knowledge_facts(run_a.id, db_path=isolated_db)) == 1


def test_run_deletion_cascades_to_knowledge_facts(isolated_db: str) -> None:
    """Deleting a run's row cascades to its knowledge_facts (FK CASCADE)."""
    run = store.create_run("kf goal", "standard", "mock", {})
    hyp_id = _add(run.id, "H", _SUPPORTED, isolated_db)
    store.replace_knowledge_facts(
        run.id,
        [
            {
                "hypothesis_id": hyp_id,
                "kind": "fact",
                "statement": "Doomed.",
                "entities": [],
                "state": "supports",
            }
        ],
        db_path=isolated_db,
    )
    assert len(store.list_knowledge_facts(run.id, db_path=isolated_db)) == 1

    with store.connect(isolated_db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM runs WHERE id = ?", (run.id,))

    assert store.list_knowledge_facts(run.id, db_path=isolated_db) == []


# --- end-to-end: report finalize persists facts -------------------------


def test_finalize_report_persists_knowledge_facts(isolated_db: str) -> None:
    """A published report derives and durably persists its knowledge facts.

    Drives the real ``finalize_report`` pipeline (safety gate included) --
    not a fixture -- against a run carrying one supports and one contradicts
    claim-evidence edge, then reads the rows back from the store.

    The two edges sit on separate hypotheses on purpose. A contradicted
    claim excludes its own hypothesis from synthesis, so putting both on one
    idea leaves the leaderboard empty and the run is blocked from publishing
    (finding N25 removed the offline exemption that used to let this
    through), which would mean no report and so no facts to assert on.
    """
    run = store.create_run("kf e2e goal", "standard", "mock", {})
    hyp_id = _add(run.id, "Supported", _SUPPORTED, isolated_db)
    contradicted_id = _add(run.id, "Contradicted", _SUPPORTED, isolated_db)
    store.add_claim_evidence(
        store.NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=hyp_id,
            claim="IL-6 increases inflammation via STAT3 signaling.",
            label="supports",
            supporting=[{"evidence_id": "ev-1", "quote": "IL-6 raises it."}],
            contradicting=[],
            assessor="deterministic-v1",
        ),
        db_path=isolated_db,
    )
    store.add_claim_evidence(
        store.NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=contradicted_id,
            claim="TREM2 has no role in this pathway.",
            label="contradicts",
            supporting=[],
            contradicting=[
                {"evidence_id": "ev-2", "quote": "TREM2 is central."}
            ],
            assessor="deterministic-v1",
        ),
        db_path=isolated_db,
    )

    assert store.list_knowledge_facts(run.id, db_path=isolated_db) == []

    _finalize(run, isolated_db)

    facts = store.list_knowledge_facts(run.id, db_path=isolated_db)
    by_kind = {row["kind"]: row for row in facts}
    assert set(by_kind) == {"fact", "contradiction"}
    assert by_kind["fact"]["evidence_id"] == "ev-1"
    assert by_kind["fact"]["hypothesis_id"] == hyp_id
    assert "IL6" in by_kind["fact"]["entities"]
    assert by_kind["contradiction"]["evidence_id"] == "ev-2"
    assert "TREM2" in by_kind["contradiction"]["entities"]


def test_finalize_report_replaces_facts_on_re_finalize(
    isolated_db: str,
) -> None:
    """Re-finalizing does not accumulate duplicate knowledge-facts rows."""
    run = store.create_run("kf goal", "standard", "mock", {})
    hyp_id = _add(run.id, "Supported", _SUPPORTED, isolated_db)
    store.add_claim_evidence(
        store.NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=hyp_id,
            claim="A supported claim.",
            label="supports",
            supporting=[],
            contradicting=[],
            assessor="deterministic-v1",
        ),
        db_path=isolated_db,
    )

    _finalize(run, isolated_db)
    first = store.list_knowledge_facts(run.id, db_path=isolated_db)
    assert len(first) == 1

    # A second finalize call is a documented no-op (report already
    # published) at the finalize_report layer, so exercise the persistence
    # helper directly the way a resumed run's re-finalize would.
    store.replace_knowledge_facts(
        run.id,
        [dict(row, evidence_id=None) for row in first],
        db_path=isolated_db,
    )
    second = store.list_knowledge_facts(run.id, db_path=isolated_db)
    assert len(second) == 1


async def test_knowledge_facts_endpoint_returns_persisted_rows(
    isolated_db: str,
) -> None:
    """``GET /runs/{id}/knowledge-facts`` reads back the persisted rows."""
    from app.runs.collections import get_knowledge_facts

    run = store.create_run("kf goal", "standard", "mock", {})
    hyp_id = _add(run.id, "H", _SUPPORTED, isolated_db)
    store.replace_knowledge_facts(
        run.id,
        [
            {
                "hypothesis_id": hyp_id,
                "kind": "fact",
                "statement": "Endpoint-visible fact.",
                "entities": ["IL6"],
                "state": "supports",
            }
        ],
        db_path=isolated_db,
    )

    result = await get_knowledge_facts(run.id, kind=None, entity=None)

    assert len(result["knowledge_facts"]) == 1
    assert result["knowledge_facts"][0]["statement"] == (
        "Endpoint-visible fact."
    )


# Tests for the persisted application log store (app_logs table).


def _append(
    isolated_db: str,
    message: str,
    *,
    level: str = "INFO",
    logger_name: str = "app.test",
    run_id: str | None = None,
) -> int:
    # The numeric level always tracks the name, so it is derived here
    # rather than passed alongside it.
    return store.append_log(
        store.NewLogRecord(
            level=level,
            levelno=int(logging.getLevelName(level)),
            logger_name=logger_name,
            message=message,
            run_id=run_id,
        ),
        db_path=isolated_db,
    )


def test_append_and_list_roundtrip(isolated_db: str) -> None:
    row_id = store.append_log(
        store.NewLogRecord(
            level="INFO",
            levelno=logging.INFO,
            logger_name="app.test",
            message="hello world",
            run_id="run-1",
            exc_text="Traceback: boom",
        ),
        db_path=isolated_db,
    )
    rows = store.list_logs(db_path=isolated_db)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == row_id
    assert row["level"] == "INFO"
    assert row["levelno"] == logging.INFO
    assert row["logger"] == "app.test"
    assert row["message"] == "hello world"
    assert row["run_id"] == "run-1"
    assert row["exc_text"] == "Traceback: boom"
    assert row["created_at"] > 0


def test_list_after_id_and_limit(isolated_db: str) -> None:
    ids = [_append(isolated_db, f"m{i}") for i in range(5)]
    rows = store.list_logs(
        filters=store.LogFilters(after_id=ids[1]), db_path=isolated_db
    )
    assert [row["message"] for row in rows] == ["m2", "m3", "m4"]
    rows = store.list_logs(limit=2, db_path=isolated_db)
    # A limit keeps the NEWEST rows, still returned in ascending order.
    assert [row["message"] for row in rows] == ["m3", "m4"]


def test_list_filters_by_min_level(isolated_db: str) -> None:
    _append(isolated_db, "debugging", level="DEBUG")
    _append(isolated_db, "informational")
    _append(isolated_db, "bad", level="ERROR")
    rows = store.list_logs(
        filters=store.LogFilters(min_levelno=logging.WARNING),
        db_path=isolated_db,
    )
    assert [row["message"] for row in rows] == ["bad"]


def test_list_filters_by_run_and_substring(isolated_db: str) -> None:
    _append(isolated_db, "global line")
    _append(isolated_db, "run line one", run_id="run-1")
    _append(isolated_db, "run line two", run_id="run-1")
    _append(isolated_db, "other run", run_id="run-2")
    rows = store.list_logs(
        filters=store.LogFilters(run_id="run-1"), db_path=isolated_db
    )
    assert [row["message"] for row in rows] == ["run line one", "run line two"]
    rows = store.list_logs(
        filters=store.LogFilters(contains="line one"), db_path=isolated_db
    )
    assert [row["message"] for row in rows] == ["run line one"]


def test_count_logs_ignores_limit_and_respects_filters(
    isolated_db: str,
) -> None:
    for i in range(5):
        _append(isolated_db, f"info {i}")
    _append(isolated_db, "bad", level="ERROR")
    _append(isolated_db, "scoped", run_id="run-1")
    assert store.count_logs(db_path=isolated_db) == 7
    assert (
        store.count_logs(
            filters=store.LogFilters(min_levelno=logging.WARNING),
            db_path=isolated_db,
        )
        == 1
    )
    assert (
        store.count_logs(
            filters=store.LogFilters(run_id="run-1"), db_path=isolated_db
        )
        == 1
    )
    assert (
        store.count_logs(
            filters=store.LogFilters(contains="info"), db_path=isolated_db
        )
        == 5
    )


def test_count_logs_honours_the_cursor(isolated_db: str) -> None:
    _append(isolated_db, "old one")
    cursor = _append(isolated_db, "old two")
    _append(isolated_db, "new one")
    # Two counts of the same set, differing only in the cursor. The
    # after-cursor count is its own query rather than a subtraction: rows
    # below the cursor are deleted by retention pruning and by a scoped
    # clear, which drives such a difference negative.
    assert store.count_logs(db_path=isolated_db) == 3
    assert (
        store.count_logs(
            filters=store.LogFilters(after_id=cursor), db_path=isolated_db
        )
        == 1
    )


def test_noise_loggers_hidden_below_warning(isolated_db: str) -> None:
    _append(isolated_db, "run started", logger_name="app.runs")
    _append(isolated_db, "GET /status", logger_name="uvicorn.access")
    _append(isolated_db, "clicked", logger_name="ui.interaction")
    _append(
        isolated_db,
        "request failed",
        logger_name="uvicorn.access",
        level="WARNING",
    )
    noise = ("uvicorn.access", "ui.interaction")
    rows = store.list_logs(
        filters=store.LogFilters(noise_loggers=noise), db_path=isolated_db
    )
    # INFO chatter from noise loggers is hidden; WARNING+ always shows,
    # and INFO from other loggers is untouched.
    assert [row["message"] for row in rows] == [
        "run started",
        "request failed",
    ]
    assert (
        store.count_logs(
            filters=store.LogFilters(noise_loggers=noise), db_path=isolated_db
        )
        == 2
    )
    # Without the filter everything is still there.
    assert store.count_logs(db_path=isolated_db) == 4


def test_noise_loggers_match_by_prefix(isolated_db: str) -> None:
    _append(isolated_db, "pool note", logger_name="httpx.client")
    rows = store.list_logs(
        filters=store.LogFilters(noise_loggers=("httpx",)), db_path=isolated_db
    )
    assert rows == []


def test_prune_logs_keeps_newest(isolated_db: str) -> None:
    for i in range(10):
        _append(isolated_db, f"m{i}")
    deleted = store.prune_logs(max_rows=4, db_path=isolated_db)
    assert deleted == 6
    rows = store.list_logs(db_path=isolated_db)
    assert [row["message"] for row in rows] == ["m6", "m7", "m8", "m9"]
    # Under the cap: nothing to delete.
    assert store.prune_logs(max_rows=4, db_path=isolated_db) == 0


def test_clear_logs_empties_and_restarts_ids(isolated_db: str) -> None:
    for i in range(3):
        _append(isolated_db, f"m{i}")
    assert store.clear_logs(db_path=isolated_db) == 3
    assert store.list_logs(db_path=isolated_db) == []
    # A clear is a fresh start: ids restart at 1 so the id-numbered UI
    # badge reads as a count again. Followers detect the reset via
    # last_id dropping below their cursor.
    assert _append(isolated_db, "after clear") == 1


def test_clear_logs_on_empty_table_returns_zero(isolated_db: str) -> None:
    assert store.clear_logs(db_path=isolated_db) == 0


def test_latest_log_id(isolated_db: str) -> None:
    assert store.latest_log_id(db_path=isolated_db) == 0
    last = 0
    for i in range(3):
        last = _append(isolated_db, f"m{i}")
    assert store.latest_log_id(db_path=isolated_db) == last
