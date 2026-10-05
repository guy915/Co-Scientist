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

from app import retention
from app.report import build as report_build
from app.report import finalize as report_finalize
from app.report.content import derive_knowledge_facts
from app.store import checkpoints as store_checkpoints
from app.store import db as _store_db
from app.store import documents, logs, messages, records, reports
from app.store import events as store_events
from app.store import runs as store
from app.store import runs_views as views
from app.store import tasks as store_tasks
from app.store.events import (
    ACTIVITY_OTHER,
    ACTIVITY_VALUES,
    activity_for_event,
)
from app.store.logs import LogFilters, NewLogRecord
from app.store.messages import NewMessage
from app.store.models import RunStatus
from app.store.records import NewClaimEvidence, NewEvidence
from dev.backup_db import backup_database
from tests._client import create_run as _create_run
from tests._client import drain as _drain
from tests._client import make_client, wait_for_status
from tests._client import make_client as _client
from tests._drain_helpers import emit_event
from tests._engine_tasks_helpers import _seed_checkpoint, _task_state
from tests._store_helpers import _add, seed_checkpoint, seed_run


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
    facts = derive_knowledge_facts([_edge("supports")])
    assert len(facts) == 1
    assert facts[0]["kind"] == "fact"
    assert facts[0]["state"] == "supports"


def test_contradicts_edge_becomes_a_contradiction() -> None:
    facts = derive_knowledge_facts([_edge("contradicts")])
    assert len(facts) == 1
    assert facts[0]["kind"] == "contradiction"
    assert facts[0]["state"] == "contradicts"


def test_insufficient_edge_is_dropped() -> None:
    facts = derive_knowledge_facts([_edge("insufficient")])
    assert facts == []


def test_edge_with_no_claim_text_is_dropped() -> None:
    facts = derive_knowledge_facts([_edge("supports", claim="  ")])
    assert facts == []


def test_fact_carries_the_statement_and_hypothesis() -> None:
    facts = derive_knowledge_facts(
        [_edge("supports", claim="TREM2 promotes microglial phagocytosis.")]
    )
    assert facts[0]["statement"] == "TREM2 promotes microglial phagocytosis."
    assert facts[0]["hypothesis_id"] == "h1"


def test_fact_extracts_entities_from_the_claim() -> None:
    facts = derive_knowledge_facts(
        [_edge("supports", claim="TREM2 promotes microglial clearance.")]
    )
    assert "TREM2" in facts[0]["entities"]


def test_fact_evidence_id_comes_from_the_supporting_spans() -> None:
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
    # Supporting and contradicting edges store their evidence in different span
    # lists.
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
    facts = derive_knowledge_facts([_edge("supports")])
    assert facts[0]["evidence_id"] is None


def test_mixed_edges_only_keep_settled_ones() -> None:
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


def test_append_and_list_messages(isolated_db: str) -> None:
    seed_run("rg", provider="mock", client_id="c1", db_path=isolated_db)
    runs = views.list_runs(client_id="c1", db_path=isolated_db)
    run_id = runs[0].id

    messages.append_message(
        NewMessage(
            run_id=run_id,
            sender="user",
            content="focus on cytokines",
            kind="steering",
        ),
        db_path=isolated_db,
    )
    messages.append_message(
        NewMessage(
            run_id=run_id,
            sender="system",
            content="Research plan ready",
            kind="milestone",
        ),
        db_path=isolated_db,
    )

    msgs = messages.list_messages(run_id, db_path=isolated_db)
    assert len(msgs) == 2
    assert msgs[0].sender == "user"
    assert msgs[0].kind == "steering"
    assert msgs[0].applied is False
    assert msgs[1].kind == "milestone"


def test_get_pending_steering(isolated_db: str) -> None:
    seed_run("rg", provider="mock", client_id="c1", db_path=isolated_db)
    run_id = views.list_runs(client_id="c1", db_path=isolated_db)[0].id

    messages.append_message(
        NewMessage(
            run_id=run_id, sender="user", content="steer A", kind="steering"
        ),
        db_path=isolated_db,
    )
    messages.append_message(
        NewMessage(
            run_id=run_id,
            sender="system",
            content="milestone msg",
            kind="milestone",
        ),
        db_path=isolated_db,
    )
    messages.append_message(
        NewMessage(
            run_id=run_id, sender="user", content="steer B", kind="steering"
        ),
        db_path=isolated_db,
    )

    pending = messages.get_pending_steering(run_id, db_path=isolated_db)
    assert len(pending) == 2
    assert all(m.kind == "steering" for m in pending)
    assert all(m.applied is False for m in pending)


def test_mark_steering_applied(isolated_db: str) -> None:
    seed_run("rg", provider="mock", client_id="c1", db_path=isolated_db)
    run_id = views.list_runs(client_id="c1", db_path=isolated_db)[0].id

    messages.append_message(
        NewMessage(
            run_id=run_id, sender="user", content="steer A", kind="steering"
        ),
        db_path=isolated_db,
    )
    messages.append_message(
        NewMessage(
            run_id=run_id, sender="user", content="steer B", kind="steering"
        ),
        db_path=isolated_db,
    )

    pending = messages.get_pending_steering(run_id, db_path=isolated_db)
    ids = [m.id for m in pending]
    messages.mark_steering_applied(ids, db_path=isolated_db)

    after = messages.get_pending_steering(run_id, db_path=isolated_db)
    assert len(after) == 0

    all_msgs = messages.list_messages(run_id, db_path=isolated_db)
    assert all(m.applied is True for m in all_msgs)


def test_queued_steering_flags_engine_pending_steering(
    isolated_db: str,
) -> None:
    # Steering needs the pending flag as well as preference text because the
    # orchestrator prioritizes that flag.
    from app.engine_adapter.opts import build_engine_opts

    run = seed_run("rg", db_path=isolated_db)
    messages.append_message(
        NewMessage(
            run_id=run.id,
            sender="user",
            content="focus on kinase X",
            kind="steering",
        ),
        db_path=isolated_db,
    )

    opts = build_engine_opts(run.config, run.id, isolated_db)
    assert opts.get("pending_steering") is True
    assert "kinase X" in str(opts.get("preferences") or "")


def test_no_steering_leaves_pending_flag_unset(isolated_db: str) -> None:
    from app.engine_adapter.opts import build_engine_opts

    run = seed_run("rg", db_path=isolated_db)
    opts = build_engine_opts(run.config, run.id, isolated_db)
    assert "pending_steering" not in opts


def test_engine_opts_bind_private_attachment_context(isolated_db: str) -> None:
    from app.engine_adapter.opts import build_engine_opts

    run = seed_run("kinase AML", db_path=isolated_db)
    records.add_evidence(
        NewEvidence(
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
    seed_run("rg", provider="mock", client_id="c1", db_path=isolated_db)
    run_id = views.list_runs(client_id="c1", db_path=isolated_db)[0].id

    msg = messages.append_message(
        NewMessage(
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


def _make_run(client: TestClient, goal: str = "test goal") -> str:
    client.headers.update({"X-Client-ID": "test-client"})
    res = _create_run(client, goal, tier="express")
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
    client = _client()
    client.headers.update({"X-Client-ID": "test-client"})
    run = seed_run(
        "Completed research", client_id="test-client", db_path=isolated_db
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
    store.update_run_status(run.id, RunStatus.COMPLETED, db_path=isolated_db)

    response = client.post(
        f"/api/runs/{run.id}/messages",
        json={"content": "Test the mechanism in organoids next."},
    )

    assert response.status_code == 200
    assert response.json()["continuation_task_id"] is not None
    reopened = store.get_run(run.id, db_path=isolated_db)
    assert reopened is not None and reopened.status == "queued"
    tasks = store_tasks.list_tasks(run.id, db_path=isolated_db)
    assert tasks[-1].task_type == "engine.node.orchestrator"
    assert tasks[-1].priority == 100


def test_send_message_always_stores_as_steering(isolated_db: str) -> None:
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
    import asyncio

    from app import task_worker

    run = seed_run(
        "test milestone generation",
        profile="express",
        config={"tier": "express"},
        client_id="test-client",
        llm_backend="offline",
        db_path=isolated_db,
    )
    task_worker.enqueue_run_workflow(run.id, db_path=isolated_db)
    asyncio.run(
        task_worker.run_run_worker_pool(
            run.id,
            "milestone-test",
            policy=task_worker.WorkerPolicy(db_path=isolated_db),
        )
    )

    msgs = messages.list_messages(run.id, db_path=isolated_db)
    milestones = [m for m in msgs if m.kind == "milestone"]
    assert len(milestones) >= 1
    assert all(m.sender == "system" for m in milestones)


def _backdate_completion(db_path: str, run_id: str, seconds_ago: float) -> None:
    # Write timestamps directly so age-based sweeps are deterministic without
    # real-time waits.
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
    created = _create_run(
        client,
        "Old completed goal",
        headers={"X-Client-ID": "retention-tester"},
    )
    run_id = created.json()["id"]
    store.update_run_status(run_id, RunStatus.COMPLETED)

    deleted = retention.sweep_expired_runs(now=time.time() + 10_000 * 86_400)

    assert deleted == []
    assert store.run_exists(run_id)


def test_sweep_deletes_only_terminal_runs_past_the_window(
    isolated_db: str,
) -> None:
    client = make_client()
    old_completed = _create_run(
        client,
        "Old completed goal",
        headers={"X-Client-ID": "retention-tester"},
    ).json()["id"]
    store.update_run_status(old_completed, RunStatus.COMPLETED)
    _backdate_completion(isolated_db, old_completed, 120 * 86_400)

    old_running = _create_run(
        client,
        "Old but still running",
        headers={"X-Client-ID": "retention-tester"},
    ).json()["id"]
    store.update_run_status(old_running, RunStatus.RUNNING)
    _backdate_completion(isolated_db, old_running, 120 * 86_400)

    recent_completed = _create_run(
        client, "Just completed", headers={"X-Client-ID": "retention-tester"}
    ).json()["id"]
    store.update_run_status(recent_completed, RunStatus.COMPLETED)

    deleted = retention.sweep_expired_runs()

    assert deleted == [old_completed]
    assert not store.run_exists(old_completed)
    assert store.run_exists(old_running)
    assert store.run_exists(recent_completed)


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
    assert (
        documents.get_staged_documents([document_id], "retention-tester") == []
    )


def _run(db: str) -> str:
    return seed_run("goal", provider="mock", db_path=db).id


def test_save_and_get_latest_checkpoint(isolated_db: str) -> None:
    run_id = _run(isolated_db)
    assert (
        store_checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
        is None
    )
    assert not store_checkpoints.has_checkpoint(run_id, db_path=isolated_db)

    seq1 = seed_checkpoint(
        run_id,
        {"hyp_ids": ["a", "b"]},
        stage="post_generation",
        last_event_seq=5,
        db_path=isolated_db,
    )
    seq2 = seed_checkpoint(
        run_id,
        {"hyp_ids": ["a", "b"], "round": 1},
        stage="post_ranking",
        last_event_seq=12,
        db_path=isolated_db,
    )
    assert (seq1, seq2) == (1, 2)
    assert store_checkpoints.has_checkpoint(run_id, db_path=isolated_db)

    latest = store_checkpoints.get_latest_checkpoint(
        run_id, db_path=isolated_db
    )
    assert latest is not None
    assert latest["seq"] == 2
    assert latest["stage"] == "post_ranking"
    assert latest["last_event_seq"] == 12
    assert latest["state"] == {"hyp_ids": ["a", "b"], "round": 1}


def test_checkpoints_are_run_scoped(isolated_db: str) -> None:
    run_a = _run(isolated_db)
    run_b = _run(isolated_db)
    seed_checkpoint(
        run_a, {"x": 1}, stage="s", last_event_seq=1, db_path=isolated_db
    )
    assert store_checkpoints.has_checkpoint(run_a, db_path=isolated_db)
    assert not store_checkpoints.has_checkpoint(run_b, db_path=isolated_db)


def _count(db: str) -> int:
    with _store_db.connect(db) as conn:
        return int(
            conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
        )


def _seed_raw_checkpoints(db: str, run_id: str, count: int) -> None:
    with _store_db.connect(db) as conn:
        for i in range(1, count + 1):
            conn.execute(
                "INSERT INTO checkpoints (run_id, seq, stage, schema_version, "
                "last_event_seq, state_json, created_at) "
                "VALUES (?, ?, ?, 1, ?, ?, 0.0)",
                (run_id, i, f"stage_{i}", i, f'{{"round": {i}}}'),
            )


def test_saving_prunes_the_checkpoints_it_supersedes(isolated_db: str) -> None:
    # Only the newest checkpoint is readable; retaining every full state can
    # fill the volume.
    run_id = _run(isolated_db)
    for i in range(5):
        seed_checkpoint(
            run_id,
            {"round": i},
            stage=f"stage_{i}",
            last_event_seq=i,
            db_path=isolated_db,
        )

    assert _count(isolated_db) == 1
    latest = store_checkpoints.get_latest_checkpoint(
        run_id, db_path=isolated_db
    )
    assert latest is not None
    assert latest["seq"] == 5
    assert latest["stage"] == "stage_4"
    assert latest["state"] == {"round": 4}
    assert store_checkpoints.has_checkpoint(run_id, db_path=isolated_db)


def test_pruning_is_per_run(isolated_db: str) -> None:
    first, second = _run(isolated_db), _run(isolated_db)
    for run_id in (first, second):
        for i in range(3):
            seed_checkpoint(
                run_id,
                {"run": run_id, "round": i},
                stage=f"s{i}",
                last_event_seq=i,
                db_path=isolated_db,
            )

    assert _count(isolated_db) == 2
    for run_id in (first, second):
        latest = store_checkpoints.get_latest_checkpoint(
            run_id, db_path=isolated_db
        )
        assert latest is not None
        assert latest["state"]["run"] == run_id
        assert latest["seq"] == 3


def test_prune_superseded_reclaims_pre_existing_history(
    isolated_db: str,
) -> None:
    # Direct inserts reproduce old databases that bypassed checkpoint pruning.
    run_id = _run(isolated_db)
    _seed_raw_checkpoints(isolated_db, run_id, 20)
    assert _count(isolated_db) == 20

    deleted = store_checkpoints.prune_superseded_checkpoints(
        db_path=isolated_db
    )

    assert deleted == 19
    assert _count(isolated_db) == 1
    latest = store_checkpoints.get_latest_checkpoint(
        run_id, db_path=isolated_db
    )
    assert latest is not None
    assert latest["seq"] == 20
    assert latest["state"] == {"round": 20}


def test_prune_superseded_is_idempotent(isolated_db: str) -> None:
    run_id = _run(isolated_db)
    seed_checkpoint(
        run_id, {}, stage="only", last_event_seq=1, db_path=isolated_db
    )

    assert (
        store_checkpoints.prune_superseded_checkpoints(db_path=isolated_db) == 0
    )
    assert (
        store_checkpoints.prune_superseded_checkpoints(db_path=isolated_db) == 0
    )
    assert store_checkpoints.has_checkpoint(run_id, db_path=isolated_db)


def test_prune_batches_and_folds_the_wal_between_batches(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Reclamation must survive SQLITE_FULL; commit small batches so headroom
    # shortages cannot roll back all progress.
    from app.store import checkpoints as checkpoints_module

    run_id = _run(isolated_db)
    _seed_raw_checkpoints(isolated_db, run_id, 11)

    checkpoints: list[int] = []
    real_checkpoint_wal = _store_db.checkpoint_wal

    def _record(db_path: str | None = None) -> None:
        checkpoints.append(_count(isolated_db))
        real_checkpoint_wal(db_path)

    monkeypatch.setattr(checkpoints_module, "checkpoint_wal", _record)

    deleted = store_checkpoints.prune_superseded_checkpoints(
        db_path=isolated_db
    )

    assert deleted == 10
    assert _count(isolated_db) == 1
    assert len(checkpoints) >= 2
    assert checkpoints == sorted(checkpoints, reverse=True)
    latest = store_checkpoints.get_latest_checkpoint(
        run_id, db_path=isolated_db
    )
    assert latest is not None
    assert latest["seq"] == 11


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
    run = seed_run("activity test", provider="mock")
    store_events.append_event(run.id, "ranking", {"iteration": 1})
    events = store_events.list_events(run.id)
    assert events[-1]["payload"]["activity"] == "tournament"


def test_list_events_reads_row_persisted_without_activity_key(
    isolated_db: str,
) -> None:
    run = seed_run("legacy row test", provider="mock")
    old_payload = {"status": "completed"}
    with sqlite3.connect(isolated_db) as conn:
        conn.execute(
            "INSERT INTO run_events (run_id, seq, type, payload_json, "
            "created_at) VALUES (?, 1, 'status', ?, 0)",
            (run.id, json.dumps(old_payload)),
        )
        conn.commit()
    events = store_events.list_events(run.id)
    assert events[0]["payload"] == old_payload
    assert "activity" not in events[0]["payload"]


_SUPPORTED = "IL-6 increases inflammation via STAT3 signaling."


def _finalize(run: Any, db_path: str) -> None:
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
            emit_event,
        )
    )


def test_replace_and_list_round_trip(isolated_db: str) -> None:
    run = seed_run("kf goal", provider="mock")
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

    reports.replace_knowledge_facts(run.id, facts, db_path=isolated_db)
    rows = reports.list_knowledge_facts(run.id, db_path=isolated_db)

    assert len(rows) == 1
    assert rows[0]["kind"] == "fact"
    assert rows[0]["statement"] == "IL-6 increases inflammation."
    assert rows[0]["entities"] == ["IL6"]
    assert rows[0]["evidence_id"] == "ev-1"


def test_replace_clears_prior_rows(isolated_db: str) -> None:
    run = seed_run("kf goal", provider="mock")
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

    reports.replace_knowledge_facts(run.id, first, db_path=isolated_db)
    reports.replace_knowledge_facts(run.id, second, db_path=isolated_db)
    rows = reports.list_knowledge_facts(run.id, db_path=isolated_db)

    assert len(rows) == 1
    assert rows[0]["statement"] == "Second."


def test_list_filters_by_kind(isolated_db: str) -> None:
    run = seed_run("kf goal", provider="mock")
    hyp_id = _add(run.id, "H", _SUPPORTED, isolated_db)
    reports.replace_knowledge_facts(
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

    facts_only = reports.list_knowledge_facts(
        run.id, kind="fact", db_path=isolated_db
    )
    assert [r["statement"] for r in facts_only] == ["A fact."]


def test_list_filters_by_entity_case_insensitively(isolated_db: str) -> None:
    run = seed_run("kf goal", provider="mock")
    hyp_id = _add(run.id, "H", _SUPPORTED, isolated_db)
    reports.replace_knowledge_facts(
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

    matched = reports.list_knowledge_facts(
        run.id, entity="trem2", db_path=isolated_db
    )
    assert [r["statement"] for r in matched] == ["About TREM2."]


def test_facts_are_scoped_per_run(isolated_db: str) -> None:
    run_a = seed_run("goal a", provider="mock")
    run_b = seed_run("goal b", provider="mock")
    hyp_a = _add(run_a.id, "H", _SUPPORTED, isolated_db)
    reports.replace_knowledge_facts(
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

    assert reports.list_knowledge_facts(run_b.id, db_path=isolated_db) == []
    assert len(reports.list_knowledge_facts(run_a.id, db_path=isolated_db)) == 1


def test_run_deletion_cascades_to_knowledge_facts(isolated_db: str) -> None:
    run = seed_run("kf goal", provider="mock")
    hyp_id = _add(run.id, "H", _SUPPORTED, isolated_db)
    reports.replace_knowledge_facts(
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
    assert len(reports.list_knowledge_facts(run.id, db_path=isolated_db)) == 1

    with _store_db.connect(isolated_db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM runs WHERE id = ?", (run.id,))

    assert reports.list_knowledge_facts(run.id, db_path=isolated_db) == []


def test_finalize_report_persists_knowledge_facts(isolated_db: str) -> None:
    # Use separate hypotheses: the contradicted one is excluded, while the
    # supported one keeps publication viable.
    run = seed_run("kf e2e goal", provider="mock")
    hyp_id = _add(run.id, "Supported", _SUPPORTED, isolated_db)
    contradicted_id = _add(run.id, "Contradicted", _SUPPORTED, isolated_db)
    records.add_claim_evidence(
        NewClaimEvidence(
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
    records.add_claim_evidence(
        NewClaimEvidence(
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

    assert reports.list_knowledge_facts(run.id, db_path=isolated_db) == []

    _finalize(run, isolated_db)

    facts = reports.list_knowledge_facts(run.id, db_path=isolated_db)
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
    run = seed_run("kf goal", provider="mock")
    hyp_id = _add(run.id, "Supported", _SUPPORTED, isolated_db)
    records.add_claim_evidence(
        NewClaimEvidence(
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
    first = reports.list_knowledge_facts(run.id, db_path=isolated_db)
    assert len(first) == 1

    reports.replace_knowledge_facts(
        run.id,
        [dict(row, evidence_id=None) for row in first],
        db_path=isolated_db,
    )
    second = reports.list_knowledge_facts(run.id, db_path=isolated_db)
    assert len(second) == 1


async def test_knowledge_facts_endpoint_returns_persisted_rows(
    isolated_db: str,
) -> None:
    from app.runs.collections import get_knowledge_facts

    run = seed_run("kf goal", provider="mock")
    hyp_id = _add(run.id, "H", _SUPPORTED, isolated_db)
    reports.replace_knowledge_facts(
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


def _append(
    isolated_db: str,
    message: str,
    *,
    level: str = "INFO",
    logger_name: str = "app.test",
    run_id: str | None = None,
) -> int:
    return logs.append_log(
        NewLogRecord(
            level=level,
            levelno=int(logging.getLevelName(level)),
            logger_name=logger_name,
            message=message,
            run_id=run_id,
        ),
        db_path=isolated_db,
    )


def test_append_and_list_roundtrip(isolated_db: str) -> None:
    row_id = logs.append_log(
        NewLogRecord(
            level="INFO",
            levelno=logging.INFO,
            logger_name="app.test",
            message="hello world",
            run_id="run-1",
            exc_text="Traceback: boom",
        ),
        db_path=isolated_db,
    )
    rows = logs.list_logs(db_path=isolated_db)
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
    rows = logs.list_logs(
        filters=LogFilters(after_id=ids[1]), db_path=isolated_db
    )
    assert [row["message"] for row in rows] == ["m2", "m3", "m4"]
    rows = logs.list_logs(limit=2, db_path=isolated_db)
    assert [row["message"] for row in rows] == ["m3", "m4"]


def test_list_filters_by_min_level(isolated_db: str) -> None:
    _append(isolated_db, "debugging", level="DEBUG")
    _append(isolated_db, "informational")
    _append(isolated_db, "bad", level="ERROR")
    rows = logs.list_logs(
        filters=LogFilters(min_levelno=logging.WARNING),
        db_path=isolated_db,
    )
    assert [row["message"] for row in rows] == ["bad"]


def test_list_filters_by_run_and_substring(isolated_db: str) -> None:
    _append(isolated_db, "global line")
    _append(isolated_db, "run line one", run_id="run-1")
    _append(isolated_db, "run line two", run_id="run-1")
    _append(isolated_db, "other run", run_id="run-2")
    rows = logs.list_logs(
        filters=LogFilters(run_id="run-1"), db_path=isolated_db
    )
    assert [row["message"] for row in rows] == ["run line one", "run line two"]
    rows = logs.list_logs(
        filters=LogFilters(contains="line one"), db_path=isolated_db
    )
    assert [row["message"] for row in rows] == ["run line one"]


def test_count_logs_ignores_limit_and_respects_filters(
    isolated_db: str,
) -> None:
    for i in range(5):
        _append(isolated_db, f"info {i}")
    _append(isolated_db, "bad", level="ERROR")
    _append(isolated_db, "scoped", run_id="run-1")
    assert logs.count_logs(db_path=isolated_db) == 7
    assert (
        logs.count_logs(
            filters=LogFilters(min_levelno=logging.WARNING),
            db_path=isolated_db,
        )
        == 1
    )
    assert (
        logs.count_logs(filters=LogFilters(run_id="run-1"), db_path=isolated_db)
        == 1
    )
    assert (
        logs.count_logs(
            filters=LogFilters(contains="info"), db_path=isolated_db
        )
        == 5
    )


def test_count_logs_honours_the_cursor(isolated_db: str) -> None:
    _append(isolated_db, "old one")
    cursor = _append(isolated_db, "old two")
    _append(isolated_db, "new one")
    # Retention and scoped clears remove pre-cursor rows, so after-cursor counts
    # cannot be derived by subtraction.
    assert logs.count_logs(db_path=isolated_db) == 3
    assert (
        logs.count_logs(
            filters=LogFilters(after_id=cursor), db_path=isolated_db
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
    rows = logs.list_logs(
        filters=LogFilters(noise_loggers=noise), db_path=isolated_db
    )
    assert [row["message"] for row in rows] == [
        "run started",
        "request failed",
    ]
    assert (
        logs.count_logs(
            filters=LogFilters(noise_loggers=noise), db_path=isolated_db
        )
        == 2
    )
    assert logs.count_logs(db_path=isolated_db) == 4


def test_noise_loggers_match_by_prefix(isolated_db: str) -> None:
    _append(isolated_db, "pool note", logger_name="httpx.client")
    rows = logs.list_logs(
        filters=LogFilters(noise_loggers=("httpx",)), db_path=isolated_db
    )
    assert rows == []


def test_prune_logs_keeps_newest(isolated_db: str) -> None:
    for i in range(10):
        _append(isolated_db, f"m{i}")
    deleted = logs.prune_logs(max_rows=4, db_path=isolated_db)
    assert deleted == 6
    rows = logs.list_logs(db_path=isolated_db)
    assert [row["message"] for row in rows] == ["m6", "m7", "m8", "m9"]
    assert logs.prune_logs(max_rows=4, db_path=isolated_db) == 0


def test_clear_logs_empties_and_restarts_ids(isolated_db: str) -> None:
    for i in range(3):
        _append(isolated_db, f"m{i}")
    assert logs.clear_logs(db_path=isolated_db) == 3
    assert logs.list_logs(db_path=isolated_db) == []
    assert _append(isolated_db, "after clear") == 1


def test_clear_logs_on_empty_table_returns_zero(isolated_db: str) -> None:
    assert logs.clear_logs(db_path=isolated_db) == 0


def test_latest_log_id(isolated_db: str) -> None:
    assert logs.latest_log_id(db_path=isolated_db) == 0
    last = 0
    for i in range(3):
        last = _append(isolated_db, f"m{i}")
    assert logs.latest_log_id(db_path=isolated_db) == last
