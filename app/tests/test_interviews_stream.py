"""Tests for the interview turn's SSE transport (interviews/stream.py).

Covers the defect where a disconnected client -- or any cancellation of
the coroutine iterating ``_advance_stream`` -- left the turn's model call
running unwatched: no persisted turn should exist after a cancel that
lands during the provider call, and the child task must not leak.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import pytest

from app import store
from app.config import settings
from app.execution_policy import CAMPAIGN, CAMPAIGN_MODEL_NAME, STANDARD
from app.interviews import stream as interviews_stream
from app.interviews import turns as interview_turns


class _HangingStream:
    """A litellm-shaped stream whose first chunk never arrives.

    Stands in for a provider call cancelled mid-flight: ``started`` fires
    once the stream is actually being awaited, so the test can wait for
    the model call to be genuinely in progress before cancelling it.
    """

    def __init__(self, started: asyncio.Event) -> None:
        self._started = started

    def __aiter__(self) -> _HangingStream:
        return self

    async def __anext__(self) -> Any:
        self._started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")  # pragma: no cover


def _seed_interview(db_path: str) -> str:
    """Create an interview carrying two consecutive scientist turns.

    Mirrors what ``add_interview_turn`` leaves behind when a turn is
    stopped: the route appends the scientist's message *before* the
    stream opens, and a cancelled turn never appends the agent's reply.
    """
    interview = store.create_interview(
        "stop-scientist", "Restore antibiotic susceptibility", db_path=db_path
    )
    store.append_interview_turn(
        str(interview["id"]),
        store.NewInterviewTurn("user", "Prioritize efflux-pump regulation."),
        db_path=db_path,
    )
    return str(interview["id"])


async def test_campaign_interview_stream_selects_campaign_route(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.execution_policy import effective_execution_model

    campaign = store.create_interview(
        "campaign-owner",
        "Campaign goal",
        execution_policy=CAMPAIGN,
        db_path=isolated_db,
    )
    standard = store.create_interview(
        "standard-owner",
        "Standard goal",
        execution_policy=STANDARD,
        db_path=isolated_db,
    )
    selected: dict[str, str | None] = {}

    async def advance(interview_id: str, *_args: Any) -> dict[str, Any]:
        selected[interview_id] = effective_execution_model(
            "configured/chat-role"
        )
        return {"id": interview_id}

    monkeypatch.setattr(interview_turns, "advance_turn", advance)
    for interview_id in (str(campaign["id"]), str(standard["id"])):
        async for _ in interviews_stream._advance_stream(interview_id):
            pass

    assert selected == {
        str(campaign["id"]): CAMPAIGN_MODEL_NAME,
        str(standard["id"]): "configured/chat-role",
    }


async def test_cancel_mid_model_call_leaves_transcript_unchanged(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    reachable_provider: None,
) -> None:
    """Cancelling the stream's consumer mid-call persists nothing.

    Exercises the real call chain (``_call_interview_model`` ->
    ``_stream_interview_content`` -> the patched ``litellm.acompletion`` ->
    ``stream_chunks``), not a hand-rolled stand-in, so this is also the
    fallback-turn trap check: ``_run_interview_turn`` only catches
    ``HTTPException``, so if anything on this real path turned the
    cancellation into a broader failure, the deterministic fallback would
    author and persist a scripted turn instead of stopping cleanly.
    """
    import litellm

    interview_id = _seed_interview(isolated_db)
    before = store.get_interview(interview_id, db_path=isolated_db)

    started = asyncio.Event()

    async def _fake_acompletion(**_kwargs: Any) -> Any:
        return _HangingStream(started)

    monkeypatch.setattr(litellm, "acompletion", _fake_acompletion)
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-chat")

    gen = interviews_stream._advance_stream(interview_id)
    consumer = asyncio.ensure_future(gen.__anext__())
    await asyncio.wait_for(started.wait(), timeout=5)

    # Stand in for what Starlette does on a client disconnect: cancel the
    # coroutine driving the generator, not aclose() -- a pending anext()
    # cannot be closed concurrently, and task-cancellation is what a real
    # disconnect actually delivers.
    consumer.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await consumer

    after = store.get_interview(interview_id, db_path=isolated_db)
    assert after is not None
    assert after == before
    assert [t["role"] for t in after["turns"]] == ["user", "user"]

    pending = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]
    assert pending == []


async def test_closing_after_a_fragment_cancels_the_advance_task(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closing a partially consumed stream does not leave its task running."""
    interview_id = _seed_interview(isolated_db)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def _fake_advance(
        _interview_id: str,
        on_reasoning: Any = None,
        _on_prose: Any = None,
    ) -> dict[str, Any]:
        assert on_reasoning is not None
        await on_reasoning("first")
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        raise AssertionError("unreachable")  # pragma: no cover

    monkeypatch.setattr(interview_turns, "advance_turn", _fake_advance)

    gen = interviews_stream._advance_stream(interview_id)
    assert "reasoning" in await gen.__anext__()
    await asyncio.wait_for(started.wait(), timeout=5)
    await gen.aclose()

    assert cancelled.is_set()
    pending = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task() and not task.done()
    ]
    assert pending == []
