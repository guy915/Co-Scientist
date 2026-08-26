"""Endpoint tests for ``POST /api/runs/{id}/messages/started``.

The Agent's spoken confirmation that a run has begun. Covers the two rows
one call persists (the scientist's own prompt and the reply), the frame
order a client reads, and the deterministic announcement that stands in
whenever no model is reachable -- offline, or a provider that fails.
"""

from __future__ import annotations

import sys
import types
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app import engine_adapter, store
from tests._client import fake_litellm as _fake_litellm
from tests._client import make_client as _client


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


def _announce(run_id: str, prompt: str = "Start research") -> httpx.Response:
    """POST the announcement endpoint for ``run_id``."""
    res: httpx.Response = _client().post(
        f"/api/runs/{run_id}/messages/started", json={"prompt": prompt}
    )
    return res


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reachable provider's own two sentences are what get persisted."""
    rid = _started_run_id()
    monkeypatch.setattr(engine_adapter, "offline_mode", lambda: False)
    monkeypatch.setitem(
        sys.modules,
        "litellm",
        _fake_litellm(["Your session is ", "under way."]),
    )

    body = _announce(rid).text

    assert "under way." in body
    assert '"fallback": true' not in body
    reply = _start_rows(rid)[1]
    assert reply.content == "Your session is under way."
    assert reply.meta is None


def test_provider_failure_falls_back_without_an_error_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run did start, so a failed announcement never reads as one."""
    rid = _started_run_id()
    monkeypatch.setattr(engine_adapter, "offline_mode", lambda: False)
    monkeypatch.setitem(
        sys.modules,
        "litellm",
        _fake_litellm([], raise_exc=RuntimeError("provider down")),
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The announcement is a turn, so it shows and keeps its thinking."""
    rid = _started_run_id()
    monkeypatch.setattr(engine_adapter, "offline_mode", lambda: False)
    monkeypatch.setitem(
        sys.modules,
        "litellm",
        _thinking_litellm("The run exists, so this confirms it.", "Under way."),
    )

    body = _announce(rid).text

    assert '"type": "reasoning"' in body
    assert body.index('"type": "reasoning"') < body.index('"type": "chunk"')
    reply = _start_rows(rid)[1]
    assert reply.meta == {"reasoning": "The run exists, so this confirms it."}
