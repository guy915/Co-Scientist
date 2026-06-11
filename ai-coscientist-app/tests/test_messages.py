"""Tests for the messages store layer."""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app import store


def test_append_and_list_messages(isolated_db):
    store.create_run("rg", "standard", "mock", {}, client_id="c1", db_path=isolated_db)
    runs = store.list_runs(client_id="c1", db_path=isolated_db)
    run_id = runs[0].id

    store.append_message(run_id, "user", "focus on cytokines", "steering", db_path=isolated_db)
    store.append_message(run_id, "system", "Research plan ready", "milestone", db_path=isolated_db)

    msgs = store.list_messages(run_id, db_path=isolated_db)
    assert len(msgs) == 2
    assert msgs[0].sender == "user"
    assert msgs[0].kind == "steering"
    assert msgs[0].applied is False
    assert msgs[1].kind == "milestone"


def test_get_pending_steering(isolated_db):
    store.create_run("rg", "standard", "mock", {}, client_id="c1", db_path=isolated_db)
    run_id = store.list_runs(client_id="c1", db_path=isolated_db)[0].id

    store.append_message(run_id, "user", "steer A", "steering", db_path=isolated_db)
    store.append_message(run_id, "system", "milestone msg", "milestone", db_path=isolated_db)
    store.append_message(run_id, "user", "steer B", "steering", db_path=isolated_db)

    pending = store.get_pending_steering(run_id, db_path=isolated_db)
    assert len(pending) == 2
    assert all(m.kind == "steering" for m in pending)
    assert all(m.applied is False for m in pending)


def test_mark_steering_applied(isolated_db):
    store.create_run("rg", "standard", "mock", {}, client_id="c1", db_path=isolated_db)
    run_id = store.list_runs(client_id="c1", db_path=isolated_db)[0].id

    store.append_message(run_id, "user", "steer A", "steering", db_path=isolated_db)
    store.append_message(run_id, "user", "steer B", "steering", db_path=isolated_db)

    pending = store.get_pending_steering(run_id, db_path=isolated_db)
    ids = [m.id for m in pending]
    store.mark_steering_applied(ids, db_path=isolated_db)

    after = store.get_pending_steering(run_id, db_path=isolated_db)
    assert len(after) == 0

    all_msgs = store.list_messages(run_id, db_path=isolated_db)
    assert all(m.applied is True for m in all_msgs)


def test_message_to_dict(isolated_db):
    store.create_run("rg", "standard", "mock", {}, client_id="c1", db_path=isolated_db)
    run_id = store.list_runs(client_id="c1", db_path=isolated_db)[0].id

    msg = store.append_message(run_id, "user", "hello", "steering", db_path=isolated_db)
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


def _client():
    from app.main import app
    return TestClient(app)


def _make_run(client, goal="test goal"):
    res = client.post("/api/runs", json={"research_goal": goal, "profile": "standard"},
                      headers={"X-Client-ID": "test-client"})
    assert res.status_code == 200
    return res.json()["id"]


def test_send_message_endpoint(isolated_db):
    client = _client()
    run_id = _make_run(client)

    res = client.post(f"/api/runs/{run_id}/messages",
                      json={"content": "focus on cytokines"})
    assert res.status_code == 200
    data = res.json()
    assert data["kind"] == "steering"
    assert data["status"] == "queued"
    assert data["content"] == "focus on cytokines"


def test_send_message_always_stores_as_steering(isolated_db):
    """POST /messages always stores as steering; Q&A routing is the frontend's job."""
    client = _client()
    run_id = _make_run(client)

    res = client.post(f"/api/runs/{run_id}/messages",
                      json={"content": "Why did hypothesis 3 drop?"})
    assert res.status_code == 200
    assert res.json()["kind"] == "steering"


def test_list_messages_endpoint(isolated_db):
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


def test_list_messages_404_on_unknown_run(isolated_db):
    client = _client()
    res = client.get("/api/runs/nonexistent-id/messages")
    assert res.status_code == 404


def test_steering_messages_applied_after_run(isolated_db):
    """Steering messages sent before a run starts should be marked applied when the run completes."""
    client = _client()
    run_id = _make_run(client, goal="test steering injection")

    client.post(f"/api/runs/{run_id}/messages",
                json={"content": "focus on apoptosis pathways", "kind": "steering"})

    msgs_before = client.get(f"/api/runs/{run_id}/messages").json()["messages"]
    assert msgs_before[0]["applied"] is False

    client.post(f"/api/runs/{run_id}/start", json={})
    deadline = time.time() + 20.0
    while time.time() < deadline:
        r = client.get(f"/api/runs/{run_id}")
        if r.json()["status"] == "completed":
            break
        time.sleep(0.1)

    msgs_after = client.get(f"/api/runs/{run_id}/messages").json()["messages"]
    steering = [m for m in msgs_after if m["kind"] == "steering"]
    assert len(steering) == 1
    assert steering[0]["applied"] is True


def test_milestone_messages_generated_after_run(isolated_db):
    """Milestone messages should be generated as the run progresses."""
    client = _client()
    run_id = _make_run(client, goal="test milestone generation")

    client.post(f"/api/runs/{run_id}/start", json={})
    deadline = time.time() + 20.0
    while time.time() < deadline:
        r = client.get(f"/api/runs/{run_id}")
        if r.json()["status"] == "completed":
            break
        time.sleep(0.1)

    msgs = client.get(f"/api/runs/{run_id}/messages").json()["messages"]
    milestones = [m for m in msgs if m["kind"] == "milestone"]
    assert len(milestones) >= 1
    kinds = [m["sender"] for m in milestones]
    assert all(k == "system" for k in kinds)
