"""Tests for the messages store layer."""

from __future__ import annotations

from typing import cast

from fastapi.testclient import TestClient

from app import store
from tests._client import make_client as _client
from tests._client import wait_for_status
from tests._engine_tasks_helpers import _seed_checkpoint, _task_state


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
