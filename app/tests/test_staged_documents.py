"""Documents staged before a run exists: grounding, and one commit point.

Two defects, one cause. An attachment used to be uploadable only *after*
the run had been created, so it could not reach the interview that scoped
the goal (it arrived after the plan was fixed), and it made run start a
three-call sequence -- create, upload, start -- whose middle step could
fail and leave a created, unstarted, ungrounded run behind with nothing
naming it.

Staging the upload first fixes both: the interview quotes it, and creating
the run carries it in as part of the same call.
"""

from __future__ import annotations

import io
import json
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app import interviews, offline_guard, store
from app.config import settings
from tests._client import make_client
from tests._interviews_helpers import (
    _fake_stream,
    _interview_payload,
    _response,
)
from tests._llm_fake_backend import install_completion_backend

_DOC_TEXT = "Tetraploid zebrafish hearts regenerate via klf2a signalling."
_HEADERS = {"X-Client-ID": "doc-scientist"}


def _stage(
    client: TestClient,
    *,
    text: str = _DOC_TEXT,
    name: str = "lab-notes.txt",
    headers: dict[str, str] | None = None,
) -> Any:
    """Upload one document to the staging endpoint and return the response."""
    return client.post(
        "/api/documents",
        headers=headers if headers is not None else _HEADERS,
        files={"file": (name, io.BytesIO(text.encode()), "text/plain")},
        data={"consent": "true"},
    )


def _stage_id(client: TestClient, **kwargs: Any) -> str:
    """Stage one document and return its id, asserting the upload worked."""
    response = _stage(client, **kwargs)
    assert response.status_code == 200, response.text
    return cast(str, response.json()["id"])


def test_staging_rejects_an_unextractable_document() -> None:
    """A document that cannot be read is refused before anything is stored."""
    client = make_client()
    response = client.post(
        "/api/documents",
        headers=_HEADERS,
        files={"file": ("scan.bin", io.BytesIO(b"\x00\x01"), "application/x")},
        data={"consent": "true"},
    )
    assert response.status_code == 422


def test_staged_document_is_not_visible_to_another_client() -> None:
    """Documents are owner-scoped, so another caller cannot attach one."""
    client = make_client()
    document_id = _stage_id(client)
    response = client.post(
        "/api/interviews",
        headers={"X-Client-ID": "someone-else"},
        json={"research_challenge": "x", "document_ids": [document_id]},
    )
    assert response.status_code == 404


def test_attached_document_reaches_the_interview_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Agent's prompt carries the text of the document the user attached.

    Asserted against the request actually sent to the provider, not against
    the wording of the reply.
    """
    client = make_client()
    document_id = _stage_id(client)
    created = client.post(
        "/api/interviews",
        headers=_HEADERS,
        json={
            "research_challenge": "How do hearts regenerate?",
            "document_ids": [document_id],
        },
    )
    assert created.status_code == 200, created.text

    interview_id = store.list_interviews("doc-scientist")[0]["id"]
    captured: dict[str, Any] = {}

    async def _fake_acompletion(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_stream(json.dumps(_response("Which mechanism?")))

    install_completion_backend(monkeypatch, _fake_acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "openai/gpt-4o")
    # The suite forces offline, which refuses the request before the prompt
    # is shaped; this case is about the prompt, and the provider is fake.
    monkeypatch.setattr(offline_guard, "remote_chat_allowed", lambda: True)
    interview = store.get_interview(str(interview_id))
    assert interview is not None

    import asyncio

    asyncio.run(interviews._call_interview_model(interview))

    prompt = " ".join(m["content"] for m in captured["messages"])
    assert _DOC_TEXT in prompt
    assert "lab-notes.txt" in prompt


def test_interview_payload_lists_its_attached_documents() -> None:
    """The chat reports what is attached, so the UI is not claiming it alone."""
    client = make_client()
    document_id = _stage_id(client)
    streamed = client.post(
        "/api/interviews",
        headers=_HEADERS,
        json={"research_challenge": "goal", "document_ids": [document_id]},
    )
    interview_id = store.list_interviews("doc-scientist")[0]["id"]
    payload = client.get(
        f"/api/interviews/{interview_id}", headers=_HEADERS
    ).json()
    assert [d["title"] for d in payload["documents"]] == ["lab-notes.txt"]
    # The streamed turn carries the same list: a client that only ever sees
    # frames must not have to re-fetch to learn what it attached.
    frame = _interview_payload(streamed)
    assert [d["title"] for d in frame["documents"]] == ["lab-notes.txt"]


def test_create_run_carries_staged_documents_into_its_corpus() -> None:
    """A run created with attachments is grounded before it is ever started."""
    client = make_client()
    document_id = _stage_id(client)
    created = client.post(
        "/api/runs",
        headers=_HEADERS,
        json={
            "research_goal": "Cardiac regeneration",
            "tier": "express",
            "document_ids": [document_id],
        },
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["id"]
    evidence = client.get(
        f"/api/runs/{run_id}/evidence", headers=_HEADERS
    ).json()
    titles = [row["title"] for row in evidence["evidence"]]
    assert "lab-notes.txt" in titles


def test_create_run_with_an_unknown_document_creates_no_run() -> None:
    """The failing half of the setup leaves no unstarted run behind.

    This is the whole point of moving the upload ahead of creation: a
    partial failure has to happen before anything is committed, not
    between two writes that nothing reconciles.
    """
    client = make_client()
    before = client.get("/api/runs", headers=_HEADERS).json()["runs"]
    response = client.post(
        "/api/runs",
        headers=_HEADERS,
        json={
            "research_goal": "Cardiac regeneration",
            "document_ids": ["not-a-real-document"],
        },
    )
    assert response.status_code == 404
    after = client.get("/api/runs", headers=_HEADERS).json()["runs"]
    assert len(after) == len(before)


def test_run_created_from_a_chat_inherits_the_chat_documents() -> None:
    """Documents attached to the chat ground the run the chat starts."""
    client = make_client()
    document_id = _stage_id(client)
    client.post(
        "/api/interviews",
        headers=_HEADERS,
        json={"research_challenge": "goal", "document_ids": [document_id]},
    )
    interview_id = str(store.list_interviews("doc-scientist")[0]["id"])
    store.update_interview(
        interview_id,
        {
            "research_challenge": "goal",
            "focus_area": ["signalling"],
            "preferences": [],
            "lab_constraints": [],
            "title": None,
        },
        None,
        completed=True,
    )
    created = client.post(
        "/api/runs",
        headers=_HEADERS,
        json={"research_goal": "goal", "interview_id": interview_id},
    )
    assert created.status_code == 200, created.text
    evidence = client.get(
        f"/api/runs/{created.json()['id']}/evidence", headers=_HEADERS
    ).json()
    assert "lab-notes.txt" in [row["title"] for row in evidence["evidence"]]
