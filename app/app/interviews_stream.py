"""SSE transport for one interview turn's advancement.

Split out of ``app.interviews`` (which re-exports every name here, so the
``interviews._interview_stream`` import and monkeypatch paths survive):
this module owns turning one Agent turn into an SSE stream -- the live
reasoning relay, the closing interview/error frame, and the BYOK scoping
the turn's model call runs under. The durable turn lifecycle and the HTTP
surface stay in ``app.interviews``; the provider call itself in
``app.interviews_model``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app import credentials, store
from app.execution_policy import (
    CAMPAIGN,
    CAMPAIGN_MODEL_NAME,
    scoped_execution_policy,
)
from app.interviews_model import ProseSink, ReasoningSink
from app.sse import sse_frame

logger = logging.getLogger(__name__)

# One live fragment on its way to the scientist: the channel it belongs to
# ("reasoning" or "chunk", the SSE frame types) and its text. Both channels
# share one queue so their relative order is preserved -- reasoning arrives
# wholly before prose on a thinking model, and the scientist should see it
# that way rather than by whichever coroutine happened to be scheduled.
_Fragment = tuple[str, str]


async def _advance(
    interview_id: str,
    on_reasoning: ReasoningSink | None = None,
    on_prose: ProseSink | None = None,
) -> dict[str, Any]:
    """Run one Agent turn; late import keeps the split cycle-free.

    Args:
        interview_id: The interview to advance.
        on_reasoning: Optional sink for live chain-of-thought fragments.
        on_prose: Optional sink for the answer's prose as it is written.

    Returns:
        The updated interview row.
    """
    from app.interviews import _advance as _advance_impl

    return await _advance_impl(interview_id, on_reasoning, on_prose)


def _resolved_execution_policy(
    interview_id: str, execution_policy: str | None
) -> str | None:
    """Use the trusted captured policy, or fail closed if the row vanished."""
    if execution_policy is not None:
        return execution_policy
    interview = store.get_interview(interview_id)
    if interview is None:
        return None
    return str(interview["execution_policy"])


async def _start_stream_advance(
    interview_id: str,
) -> tuple[asyncio.Queue[_Fragment | None], asyncio.Task[dict[str, Any]]]:
    queue: asyncio.Queue[_Fragment | None] = asyncio.Queue()

    async def _on_reasoning(fragment: str) -> None:
        await queue.put(("reasoning", fragment))

    async def _on_prose(fragment: str) -> None:
        await queue.put(("chunk", fragment))

    task = asyncio.create_task(_advance(interview_id, _on_reasoning, _on_prose))
    # Sentinel closes the drain loop whether the turn succeeded or raised;
    # it queues behind any fragment already emitted, so nothing is dropped.
    task.add_done_callback(lambda _: queue.put_nowait(None))
    return queue, task


async def _advance_stream(
    interview_id: str,
    byok: credentials.ByokCredential | None = None,
    *,
    execution_policy: str | None = None,
) -> AsyncGenerator[str, None]:
    """Advance one turn as SSE: live reasoning and prose, then the interview.

    The Agent's turn runs as a task that pushes fragments onto a queue while
    this generator drains it, so both the chain of thought and the answer
    itself reach the scientist as the model produces them rather than after
    the turn lands. The closing ``interview`` frame carries exactly what the
    turn resolved to, including the deterministic fallback when the provider
    fails.

    ``chunk`` is deliberately the frame name ``qa.py`` already streams
    prose under, so a client has one streaming contract for both chat
    surfaces rather than one per surface.

    A bring-your-own-key credential is scoped around the whole turn (the
    task created inside inherits it), so the turn's model call -- and only
    it -- runs on the scientist's own key.

    When the consumer stops iterating early -- Starlette cancels this on a
    client disconnect, racing ``StreamingResponse`` against a disconnect
    listener -- the ``finally`` below cancels the child task and awaits it
    so the turn's model call does not run to completion unwatched. Nothing
    is rolled back: the scientist's own turn was already persisted by the
    route before this generator opened, and ``_advance`` only persists the
    Agent's reply *after* the model call returns, so a cancel that lands
    during the call simply leaves that reply unwritten.

    Args:
        interview_id: The interview to advance.
        byok: The request's credential, when one was sent.
        execution_policy: Policy captured when the interview was authorized.

    Yields:
        ``reasoning`` and ``chunk`` frames, then one terminal ``interview``
        or ``error`` frame.
    """
    execution_policy = _resolved_execution_policy(
        interview_id, execution_policy
    )
    if execution_policy is None:
        yield sse_frame({"type": "error", "detail": "interview not found"})
        return
    with (
        scoped_execution_policy(
            execution_policy,
            campaign_model_name=(
                CAMPAIGN_MODEL_NAME if execution_policy == CAMPAIGN else None
            ),
        ),
        credentials.scoped_byok(byok),
    ):
        queue, task = await _start_stream_advance(interview_id)
        try:
            while (fragment := await queue.get()) is not None:
                kind, content = fragment
                yield sse_frame({"type": kind, "content": content})

            error_frame, updated = await _resolve_advance_task(
                task, interview_id
            )
            if error_frame is not None:
                yield error_frame
                return
            yield sse_frame({"type": "interview", "interview": updated})
        finally:
            await _cancel_pending(task)


async def _cancel_pending(task: asyncio.Task[dict[str, Any]]) -> None:
    """Cancel ``task`` and await it, unless it has already finished.

    A no-op on the normal-completion path -- the task is already done by
    then. Reached instead when the generator stops early (see
    ``_advance_stream``'s docstring): cancels the turn's model call rather
    than letting it run on unwatched, and awaits it so the cancellation
    finishes here instead of leaking a "Task was destroyed but it is
    pending" warning once nothing references it any more.
    """
    if task.done():
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _resolve_advance_task(
    task: asyncio.Task[dict[str, Any]], interview_id: str
) -> tuple[str | None, dict[str, Any] | None]:
    """Await the advance task, turning any failure into an error SSE frame.

    Returns:
        An ``(error_frame, updated_interview)`` pair, exactly one of which
        is not None.
    """
    try:
        return None, await task
    except HTTPException as exc:
        return sse_frame({"type": "error", "detail": str(exc.detail)}), None
    except Exception:
        logger.exception("Interview turn failed for %s", interview_id)
        return (
            sse_frame(
                {"type": "error", "detail": "The interview Agent failed."}
            ),
            None,
        )


def _interview_stream(
    interview_id: str,
    byok: credentials.ByokCredential | None = None,
    *,
    execution_policy: str | None = None,
) -> StreamingResponse:
    """Wrap ``_advance_stream`` in a no-buffer SSE response.

    Args:
        interview_id: The interview to advance.
        byok: The request's credential, when one was sent.
        execution_policy: Policy captured when the interview was authorized.

    Returns:
        The SSE response streaming the turn.
    """
    return StreamingResponse(
        _advance_stream(interview_id, byok, execution_policy=execution_policy),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
