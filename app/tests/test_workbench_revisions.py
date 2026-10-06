from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import messages, runs
from app.store.messages import NewMessage
from tests._store_helpers import seed_run


@pytest.mark.parametrize("retry", [False, True])
def test_revising_qa_preserves_run_inputs_and_steering(
    isolated_db: str, retry: bool
) -> None:
    run = seed_run(
        "Keep scientific state",
        profile="express",
        provider="mock",
        client_id="qa-owner",
    )
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
    owner = {"X-Client-ID": "qa-owner"}

    def revise(
        message_id: int, body: dict[str, str], headers: dict[str, str]
    ) -> Any:
        return client.post(
            f"/api/runs/{run.id}/messages/{message_id}/revise",
            headers=headers,
            json=body,
        )

    with TestClient(app) as client:
        body = {} if retry else {"question": "Revised question"}
        target = answer.id if retry else question.id
        assert revise(target, body, {"X-Client-ID": "other"}).status_code == 404
        response = revise(target, body, owner)
        assert response.status_code == 200
        assert '"type": "done"' in response.text
        assert (
            revise(start.id, {"question": "Change setup"}, owner).status_code
            == 409
        )

    rows = messages.list_messages(run.id)
    assert [row.id for row in rows[:2]] == [start.id, steering.id]
    assert [row.sender for row in rows[2:]] == ["user", "system"]
    assert rows[2].content == (
        "Original question" if retry else "Revised question"
    )
    assert runs.get_run(run.id) == run


def test_replaced_question_discards_late_streamed_answer(
    isolated_db: str,
) -> None:
    run = seed_run("Cross-tab revision", profile="express", provider="mock")
    question = messages.append_message(
        NewMessage(run.id, "user", "Original", "qa")
    )
    replacement = messages.rewind_qa(run.id, question.id, "Revised")
    messages.append_qa_reply(
        NewMessage(run.id, "system", "Obsolete answer", "qa"), question.id
    )
    assert messages.list_messages(run.id) == [replacement]
    messages.append_qa_reply(
        NewMessage(run.id, "system", "Current answer", "qa"), replacement.id
    )
    assert messages.list_messages(run.id)[-1].content == "Current answer"
