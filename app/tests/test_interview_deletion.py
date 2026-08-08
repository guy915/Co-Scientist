"""Tests for permanent chat deletion: DELETE /api/interviews/{id}."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import store

from ._client import make_client

_OWNER = {"X-Client-ID": "chat-owner"}
_OTHER = {"X-Client-ID": "someone-else"}


def _make_chat(owner: str = "chat-owner", turns: int = 2) -> str:
    """Create an interview with a short transcript and return its id."""
    interview = store.create_interview(owner, "Why do biofilms resist drugs?")
    interview_id: str = str(interview["id"])
    for index in range(turns):
        store.append_interview_turn(
            interview_id, store.NewInterviewTurn("user", f"answer {index}")
        )
    return interview_id


def test_deletes_the_chat_and_its_transcript() -> None:
    client: TestClient = make_client()
    chat_id = _make_chat()

    response = client.delete(f"/api/interviews/{chat_id}", headers=_OWNER)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deleted"] is True
    assert body["counts"]["interviews"] == 1
    # The opening turn is seeded at creation, so the transcript is longer
    # than the answers appended above.
    assert body["counts"]["interview_turns"] >= 2
    assert store.get_interview(chat_id) is None


def test_the_chat_is_gone_from_the_owner_list() -> None:
    client: TestClient = make_client()
    kept, removed = _make_chat(), _make_chat()

    deleted = client.delete(f"/api/interviews/{removed}", headers=_OWNER)
    assert deleted.status_code == 200, deleted.text

    listed = client.get("/api/interviews", headers=_OWNER).json()
    ids = {chat["id"] for chat in listed}
    assert kept in ids
    assert removed not in ids


def test_another_client_cannot_delete_it() -> None:
    client: TestClient = make_client()
    chat_id = _make_chat()

    response = client.delete(f"/api/interviews/{chat_id}", headers=_OTHER)

    # 404, not 403: a non-owner must not learn the chat exists at all.
    assert response.status_code == 404
    assert store.get_interview(chat_id) is not None


def test_an_identity_less_caller_cannot_delete_it() -> None:
    client: TestClient = make_client()
    chat_id = _make_chat(owner="")

    response = client.delete(
        f"/api/interviews/{chat_id}", headers={"X-Client-ID": ""}
    )

    # An empty subject owns nothing, even a row whose own client_id is
    # empty too -- the rule _owned_interview enforces on every read.
    assert response.status_code == 404
    assert store.get_interview(chat_id) is not None


def test_deleting_an_unknown_chat_is_a_404() -> None:
    client: TestClient = make_client()

    response = client.delete("/api/interviews/no-such-chat", headers=_OWNER)

    assert response.status_code == 404


def test_a_deleted_chat_leaves_its_staged_document_behind() -> None:
    client: TestClient = make_client()
    chat_id = _make_chat()
    document_id = store.add_staged_document(
        store.NewStagedDocument(
            client_id="chat-owner",
            title="notes.txt",
            text="cryoprotectant toxicity notes",
            mime_type="text/plain",
            sha256="0" * 64,
            byte_size=29,
            extraction_tool="test",
        )
    )
    store.attach_documents_to_interview(chat_id, [document_id], "chat-owner")

    body = client.delete(f"/api/interviews/{chat_id}", headers=_OWNER).json()

    assert body["counts"]["staged_documents_detached"] == 1
    # The document survives: it may be the caller's only copy.
    assert store.get_staged_documents([document_id], "chat-owner")
