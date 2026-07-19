"""Endpoint tests for ``POST /api/runs/{id}/messages/ask``.

Covers the provider branch: the keyless mock posture must yield a grounded
offline answer (not an API-key error), while a configured provider still
streams a model answer through the unchanged litellm path.
"""

from __future__ import annotations

import sys

import pytest

from app import engine_adapter, store
from tests._client import fake_litellm as _fake_litellm
from tests._client import make_client as _client
from tests._client import wait_for_status as _wait_status


def _completed_run_id() -> str:
    """Create + run an offline engine workflow to done; return its run id."""
    c = _client()
    rid = c.post(
        "/api/runs",
        json={
            "research_goal": "Investigate ferroptosis in cancer",
            "tier": "express",
        },
    ).json()["id"]
    c.post(f"/api/runs/{rid}/start", json={})
    assert _wait_status(c, rid, "completed", timeout=30.0)
    return str(rid)


def test_ask_offline_returns_grounded_answer_not_error() -> None:
    """With no provider key (mock), the ask stream is a grounded answer."""
    rid = _completed_run_id()
    c = _client()

    res = c.post(f"/api/runs/{rid}/messages/ask", json={"question": "Summary?"})

    assert res.status_code == 200
    body = res.text
    assert '"type": "chunk"' in body
    assert '"type": "done"' in body
    assert '"type": "error"' not in body
    assert "requires a language model" not in body
    assert "requires an API key" not in body

    # The persisted answer is grounded in the run's own artifacts.
    msgs = store.list_messages(rid)
    answer = next(
        m for m in reversed(msgs) if m.kind == "qa" and m.sender == "system"
    )
    assert "Investigate ferroptosis in cancer" in answer.content
    assert "offline mode" in answer.content.lower()


def test_ask_uses_real_llm_when_provider_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured provider still streams through the litellm path."""
    rid = _completed_run_id()
    # The Q&A endpoint routes on the LLM backend now, not the retired mock
    # provider: a real (non-offline) backend takes the streaming litellm path.
    monkeypatch.setattr(engine_adapter, "offline_mode", lambda: False)
    monkeypatch.setitem(
        sys.modules, "litellm", _fake_litellm(["Model ", "text"])
    )

    c = _client()
    res = c.post(f"/api/runs/{rid}/messages/ask", json={"question": "Summary?"})

    assert res.status_code == 200
    body = res.text
    assert "Model " in body and "text" in body
    assert "offline mode" not in body.lower()

    msgs = store.list_messages(rid)
    answer = next(
        m for m in reversed(msgs) if m.kind == "qa" and m.sender == "system"
    )
    assert answer.content == "Model text"
