from __future__ import annotations

from app.store import messages
from app.store.messages import NewMessage
from tests._store_helpers import seed_run


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
