from __future__ import annotations

import pytest

from app.store import db, messages, runs, tasks
from app.store.messages import NewMessage
from app.store.schema import SCHEMA
from app.store.tasks import NewTask


def test_retirement_drops_tables_and_settles_pending_tasks(
    isolated_db: str,
) -> None:
    run = runs.create_run("Retirement test", "express", "engine", {})
    retired = tasks.enqueue_task(
        NewTask(run.id, "engine.outcome.refinement", {}, "retired")
    )
    with db.connect() as conn:
        conn.execute("CREATE TABLE hypothesis_outcomes (id TEXT PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE outcome_refinement_actions (id TEXT PRIMARY KEY)"
        )
        conn.executescript(SCHEMA)
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert "hypothesis_outcomes" not in names
    assert "outcome_refinement_actions" not in names
    settled = tasks.get_task(retired.id)
    assert settled is not None
    assert settled.status == "completed"
    assert settled.result == {"retired": True}


@pytest.mark.parametrize("retry", [False, True])
def test_qa_revisions_preserve_consumed_input_and_steering(
    isolated_db: str, retry: bool
) -> None:
    run = runs.create_run("Keep scientific state", "express", "engine", {})
    start = messages.append_message(
        NewMessage(run.id, "user", "Start", "start")
    )
    question = messages.append_message(
        NewMessage(run.id, "user", "Original question", "qa")
    )
    answer = messages.append_message(
        NewMessage(run.id, "system", "Original answer", "qa")
    )
    steering = messages.append_message(
        NewMessage(run.id, "user", "Keep guidance", "steering")
    )
    messages.append_message(
        NewMessage(run.id, "user", "Downstream question", "qa")
    )
    replacement = messages.rewind_qa(
        run.id,
        answer.id if retry else question.id,
        None if retry else "Revised question",
    )
    assert replacement.content == (
        "Original question" if retry else "Revised question"
    )
    assert [row.id for row in messages.list_messages(run.id)] == [
        start.id,
        steering.id,
        replacement.id,
    ]
    assert runs.get_run(run.id) == run
    with pytest.raises(ValueError, match="Only Q&A"):
        messages.rewind_qa(run.id, start.id, "Change setup")
    assert len(messages.list_messages(run.id)) == 3


def test_revision_endpoint_checks_owner_and_streams_replacement(
    isolated_db: str,
) -> None:
    from fastapi.testclient import TestClient

    from app.main import app
    from app.store.runs import RunCreateOptions

    run = runs.create_run(
        "Q&A API", "express", "mock", {}, RunCreateOptions(client_id="qa-owner")
    )
    question = messages.append_message(
        NewMessage(run.id, "user", "Original", "qa")
    )
    with TestClient(app) as client:
        url = f"/api/runs/{run.id}/messages/{question.id}/revise"
        refused = client.post(
            url,
            headers={"X-Client-ID": "different-owner"},
            json={"question": "Revised"},
        )
        assert refused.status_code == 404
        response = client.post(
            url,
            headers={"X-Client-ID": "qa-owner"},
            json={"question": "Revised"},
        )
        assert response.status_code == 200
        assert '"type": "done"' in response.text
    rows = messages.list_messages(run.id)
    assert [row.sender for row in rows] == ["user", "system"]
    assert rows[0].content == "Revised"
