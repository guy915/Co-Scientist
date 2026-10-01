"""Endpoint tests for ``POST /api/runs/{id}/messages/ask``.

Covers the provider branch: the keyless mock posture must yield a grounded
offline answer (not an API-key error), while a configured provider still
streams a model answer through the unchanged litellm path.
"""

from __future__ import annotations

import sys

import pytest

from app import store
from tests._client import fake_litellm as _fake_litellm
from tests._client import make_client as _client
from tests._client import wait_for_status as _wait_status
from tests._process_mode_helpers import FakeProcessMode


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
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    """A configured provider still streams through the litellm path."""
    rid = _completed_run_id()
    # The Q&A endpoint routes on the LLM backend now, not the retired mock
    # provider: a real (non-offline) backend takes the streaming litellm path.
    fake_process_mode.online()
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


def _prompt_for(rid: str) -> str:
    """Return the system prompt the Q&A endpoint would send for ``rid``."""
    from app import qa, runs_chat

    run = store.get_run(rid)
    assert run is not None
    return qa.build_system_prompt(runs_chat._gather_qa_context(run))


def test_the_prompt_carries_the_runs_progress_and_its_report() -> None:
    """The chat can answer "how is it going" and "what did it conclude".

    The scientist keeps talking to the chat after the run starts, so the
    context is not only the run's artifacts: what the prompt must carry is
    how far the run got, what it produced, and -- once it finishes -- what
    its report concluded.
    """
    prompt = _prompt_for(_completed_run_id())

    assert "Run status:" in prompt
    assert "Ideas generated so far:" in prompt
    assert "Final report:" in prompt
    assert "Ideas explored:" in prompt
    # Idea *titles* are in the prompt; their bodies are the tool's job.
    assert "call the search_ideas tool" in prompt


def test_a_running_run_carries_no_final_report_section() -> None:
    """A run still going must not be given an empty report to answer out of."""
    c = _client()
    rid = c.post(
        "/api/runs",
        json={"research_goal": "Investigate X", "tier": "express"},
    ).json()["id"]
    store.update_run_status(rid, store.RunStatus.RUNNING)

    prompt = _prompt_for(rid)

    assert "Run status:" in prompt
    assert "Final report:" not in prompt
