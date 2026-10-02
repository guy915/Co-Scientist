"""Endpoint tests for ``POST /api/runs/{id}/messages/started``.

The Agent's spoken confirmation that a run has begun. Covers the two rows
one call persists (the scientist's own prompt and the reply), the frame
order a client reads, and the deterministic announcement that stands in
whenever no model is reachable -- offline, or a provider that fails.
"""

from __future__ import annotations

import types
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from app import store
from app.config import settings
from tests._client import fake_litellm as _fake_litellm
from tests._client import make_client as _client
from tests._llm_fake_backend import install_completion_backend
from tests._process_mode_helpers import FakeProcessMode


def _started_run_id() -> str:
    """Create a run (no engine work needed) and return its id."""
    c = _client()
    return str(
        c.post(
            "/api/runs",
            json={
                "research_goal": "Investigate ferroptosis in cancer",
                "tier": "express",
            },
        ).json()["id"]
    )


def _announce(run_id: str, prompt: str = "Start research") -> Any:
    """POST the announcement endpoint for ``run_id``.

    Returns ``Any``: TestClient's own httpx is vendored, so naming its
    Response type here binds the test to a second, incompatible httpx.
    """
    return _client().post(
        f"/api/runs/{run_id}/messages/started", json={"prompt": prompt}
    )


def _start_rows(run_id: str) -> list[store.MessageRow]:
    """Every persisted ``start`` row for the run, in order."""
    return [m for m in store.list_messages(run_id) if m.kind == "start"]


def test_announcement_persists_the_prompt_and_the_reply() -> None:
    """One call leaves both halves of the exchange on the run."""
    rid = _started_run_id()

    res = _announce(rid)

    assert res.status_code == 200
    rows = _start_rows(rid)
    assert [row.sender for row in rows] == ["user", "system"]
    assert rows[0].content == "Start research"
    assert rows[1].content.strip()


def test_announcement_streams_chunks_then_done() -> None:
    """The client reads prose chunks and a terminal ``done`` frame."""
    rid = _started_run_id()

    body = _announce(rid).text

    assert '"type": "chunk"' in body
    assert '"type": "done"' in body
    assert body.index('"type": "chunk"') < body.index('"type": "done"')
    assert '"type": "error"' not in body


def test_offline_announcement_is_marked_as_the_fallback() -> None:
    """With no model reachable the reply is the deterministic one."""
    rid = _started_run_id()

    body = _announce(rid).text

    assert '"fallback": true' in body
    assert _start_rows(rid)[1].meta == {"fallback": True}


def test_live_model_writes_the_announcement(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    """A reachable provider's own two sentences are what get persisted."""
    rid = _started_run_id()
    fake_process_mode.online()
    install_completion_backend(
        monkeypatch,
        (_fake_litellm(["Your session is ", "under way."])).acompletion,
    )

    body = _announce(rid).text

    assert "under way." in body
    assert '"fallback": true' not in body
    reply = _start_rows(rid)[1]
    assert reply.content == "Your session is under way."
    assert reply.meta is None


def test_provider_failure_falls_back_without_an_error_frame(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    """The run did start, so a failed announcement never reads as one."""
    rid = _started_run_id()
    fake_process_mode.online()
    install_completion_backend(
        monkeypatch,
        (
            _fake_litellm([], raise_exc=RuntimeError("provider down"))
        ).acompletion,
    )

    body = _announce(rid).text

    assert '"type": "error"' not in body
    assert '"fallback": true' in body
    assert _start_rows(rid)[1].content.strip()


def test_announcement_404s_for_an_unknown_run() -> None:
    """An id nothing owns is a 404, not an empty announcement."""
    assert _announce("no-such-run").status_code == 404


def _thinking_litellm(reasoning: str, prose: str) -> types.SimpleNamespace:
    """A fake litellm whose stream reasons before it writes, as DeepSeek does.

    ``tests._client.fake_litellm`` streams content deltas only, so the
    reasoning channel needs its own stand-in.
    """

    async def _chunk_stream() -> AsyncIterator[Any]:
        for field, text in (
            ("reasoning_content", reasoning),
            ("content", prose),
        ):
            delta = SimpleNamespace(content=None, reasoning_content=None)
            setattr(delta, field, text)
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])

    async def _acompletion(**_kwargs: Any) -> AsyncIterator[Any]:
        return _chunk_stream()

    return types.SimpleNamespace(acompletion=_acompletion)


def test_reasoning_is_relayed_and_kept_with_the_reply(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    """The announcement is a turn, so it shows and keeps its thinking."""
    rid = _started_run_id()
    fake_process_mode.online()
    install_completion_backend(
        monkeypatch,
        (
            _thinking_litellm(
                "The run exists, so this confirms it.", "Under way."
            )
        ).acompletion,
    )

    body = _announce(rid).text

    assert '"type": "reasoning"' in body
    assert body.index('"type": "reasoning"') < body.index('"type": "chunk"')
    reply = _start_rows(rid)[1]
    assert reply.meta == {"reasoning": "The run exists, so this confirms it."}


def _thinking_only_then_answered_litellm(
    reasoning: str, prose: str, calls: list[dict[str, Any]]
) -> types.SimpleNamespace:
    """A fake litellm whose first stream reasons and writes nothing.

    The second call (thinking off, per ``calls``) answers normally --
    mirrors production 2026-09-06, where a stream relayed ~68k characters
    of chain of thought and ended with no answer at all.
    """

    async def _reasoning_only_stream() -> AsyncIterator[Any]:
        delta = SimpleNamespace(content=None, reasoning_content=reasoning)
        yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])

    async def _answered_stream() -> AsyncIterator[Any]:
        delta = SimpleNamespace(content=prose, reasoning_content=None)
        yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])

    async def _acompletion(**kwargs: Any) -> AsyncIterator[Any]:
        calls.append(kwargs)
        if len(calls) == 1:
            return _reasoning_only_stream()
        return _answered_stream()

    return types.SimpleNamespace(acompletion=_acompletion)


def test_thinking_only_announcement_retries_before_the_fallback(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    """A stream that reasoned and wrote nothing gets a real answer, not copy.

    Confirms the retry the interview stream also gets (see
    ``test_interviews_model.test_thinking_only_turn_retries_once_with_
    thinking_off``): the announcement's own fixed fallback text is
    reserved for when the retry also comes back empty, not for every
    thinking-only stream.
    """
    rid = _started_run_id()
    fake_process_mode.online()
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-v4-pro")
    calls: list[dict[str, Any]] = []
    install_completion_backend(
        monkeypatch,
        (
            _thinking_only_then_answered_litellm(
                "brainstorming candidates at length...",
                "Research is under way.",
                calls,
            )
        ).acompletion,
    )

    body = _announce(rid).text

    assert len(calls) == 2
    assert calls[1]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert '"fallback": true' not in body
    reply = _start_rows(rid)[1]
    assert reply.content == "Research is under way."
