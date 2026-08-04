"""Model-driven, durable research-goal interview API.

This module owns the durable turn lifecycle and the HTTP surface. The
provider call and its deterministic fallback live in ``interviews_model``,
and the request-shaping half (schema, prompts, field normalization) in
``interviews_prompts``; both are re-exported here, so ``app.interviews``
remains the stable import and monkeypatch surface.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import store
from app.audience import AUDIENCE_PATTERN
from app.auth import client_id
from app.interviews_model import (
    _INTERVIEW_STALL_SECONDS as _INTERVIEW_STALL_SECONDS,
)
from app.interviews_model import (
    _INTERVIEW_TOTAL_SECONDS as _INTERVIEW_TOTAL_SECONDS,
)
from app.interviews_model import (
    ReasoningSink as ReasoningSink,
)
from app.interviews_model import (
    _call_interview_model as _call_interview_model,
)
from app.interviews_model import (
    _collect_stream_content as _collect_stream_content,
)
from app.interviews_model import (
    _fallback_interview_response as _fallback_interview_response,
)
from app.interviews_model import (
    _stream_interview_content as _stream_interview_content,
)
from app.interviews_prompts import (
    _RESPONSE_SCHEMA as _RESPONSE_SCHEMA,
)
from app.interviews_prompts import (
    _SYSTEM_PROMPT as _SYSTEM_PROMPT,
)
from app.interviews_prompts import (
    _clean_list as _clean_list,
)
from app.interviews_prompts import (
    _essentials_ready as _essentials_ready,
)
from app.interviews_prompts import (
    _interview_request as _interview_request,
)
from app.interviews_prompts import (
    _normalized_fields as _normalized_fields,
)
from app.interviews_prompts import (
    _prompt as _prompt,
)
from app.interviews_prompts import (
    _ready as _ready,
)
from app.interviews_prompts import (
    _system_prompt as _system_prompt,
)
from app.qa import sse_frame

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/interviews", tags=["interviews"])


class CreateInterviewRequest(BaseModel):
    """Initial scientist challenge for a new interview."""

    research_challenge: str = Field(..., min_length=1, max_length=20_000)
    audience: str | None = Field(None, pattern=AUDIENCE_PATTERN)


class InterviewTurnRequest(BaseModel):
    """One scientist answer or correction."""

    content: str = Field(..., min_length=1, max_length=20_000)


class InterviewFieldsRequest(BaseModel):
    """Scientist-authored edits to the four structured fields."""

    research_challenge: str = Field(..., min_length=1, max_length=20_000)
    focus_area: list[str]
    preferences: list[str]
    title: str | None = Field(None, max_length=200)


def _owned_interview(interview_id: str, request: Request) -> dict[str, Any]:
    """Return an owned interview or raise without leaking its existence."""
    interview = store.get_interview(interview_id)
    if interview is None or interview["client_id"] != client_id(request):
        raise HTTPException(status_code=404, detail="interview not found")
    return interview


def _reasoning_capture(
    on_reasoning: ReasoningSink | None,
) -> tuple[ReasoningSink, list[str]]:
    """Return a reasoning sink that records fragments while relaying them.

    Returns:
        A ``(sink, fragments)`` pair; ``fragments`` fills as the model
        reasons, so the caller can persist the turn's whole chain of
        thought once the turn resolves.
    """
    fragments: list[str] = []

    async def sink(fragment: str) -> None:
        fragments.append(fragment)
        if on_reasoning is not None:
            await on_reasoning(fragment)

    return sink, fragments


async def _advance(
    interview_id: str, on_reasoning: ReasoningSink | None = None
) -> dict[str, Any]:
    """Run one Agent turn and persist its derivation for later resume.

    The turn's chain of thought is persisted alongside its message: a chat
    is short, so its own thinking stays in the transcript the next turn is
    derived from, and a resumed chat shows the reasoning the scientist
    watched arrive rather than dropping it.

    Args:
        interview_id: The interview to advance.
        on_reasoning: Optional sink for live chain-of-thought fragments.

    Returns:
        The updated interview row.
    """
    interview = store.get_interview(interview_id)
    assert interview is not None
    sink, fragments = _reasoning_capture(on_reasoning)
    response, used_fallback = await _run_interview_turn(interview, sink)
    turn = _resolved_turn(response, used_fallback, "".join(fragments))
    _persist_interview_turn(interview_id, turn)
    updated = store.get_interview(interview_id)
    assert updated is not None
    return updated


@dataclasses.dataclass(frozen=True)
class _ResolvedTurn:
    """What one advanced turn resolved to, before it is persisted.

    Attributes:
        message: The Agent's message to the scientist.
        fields: The four structured fields as this turn derived them.
        reasoning: The turn's whole chain of thought, as relayed.
        completed: Whether this turn completes the interview.
    """

    message: str
    fields: dict[str, Any]
    reasoning: str
    completed: bool


def _resolved_turn(
    response: dict[str, Any], used_fallback: bool, reasoning: str
) -> _ResolvedTurn:
    """Read one model response into the turn record to persist.

    Returns:
        The resolved turn.

    Raises:
        HTTPException: 502 when the Agent returned no message to show.
    """
    fields = _normalized_fields(response)
    message = str(response.get("assistant_message") or "").strip()
    if not message:
        raise HTTPException(
            status_code=502, detail="Interview Agent returned no message."
        )
    return _ResolvedTurn(
        message=message,
        fields=fields,
        reasoning=reasoning,
        completed=_interview_turn_completed(response, fields, used_fallback),
    )


def _persist_interview_turn(interview_id: str, turn: _ResolvedTurn) -> None:
    """Append the Agent's turn and update the interview's derived fields."""
    store.append_interview_turn(
        interview_id,
        store.NewInterviewTurn("agent", turn.message, turn.reasoning),
    )
    store.update_interview(
        interview_id,
        turn.fields,
        None if turn.completed else turn.message,
        completed=turn.completed,
    )


async def _run_interview_turn(
    interview: dict[str, Any], on_reasoning: ReasoningSink | None
) -> tuple[dict[str, Any], bool]:
    """Call the interview model, falling back on a 503.

    Returns:
        A ``(response, used_fallback)`` pair.
    """
    try:
        return await _call_interview_model(interview, on_reasoning), False
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        return _fallback_interview_response(interview), True


def _interview_turn_completed(
    response: dict[str, Any], fields: dict[str, Any], used_fallback: bool
) -> bool:
    """Return whether this turn completes the interview."""
    if used_fallback:
        # The deterministic recovery path sequences its questions via _ready,
        # so let it collect a preferences answer before completing.
        return _ready(fields)
    # Trust the model's own completion signal once the essentials are
    # captured. Empty preferences is a valid "no constraints" terminal state
    # per the interview contract, so requiring it here would deadlock the
    # interview whenever the scientist has no additional constraints.
    return bool(response.get("completed")) and _essentials_ready(fields)


async def _advance_stream(interview_id: str) -> AsyncIterator[str]:
    """Advance one turn as SSE: live reasoning frames, then the interview.

    The Agent's turn runs as a task that pushes chain-of-thought fragments
    onto a queue while this generator drains it, so reasoning reaches the
    scientist as the model produces it rather than after the answer lands.
    The closing ``interview`` frame carries exactly what the turn resolved
    to, including the deterministic fallback when the provider fails.

    Yields:
        ``reasoning`` frames, then one terminal ``interview`` or ``error``
        frame.
    """
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _on_reasoning(fragment: str) -> None:
        await queue.put(fragment)

    task = asyncio.create_task(_advance(interview_id, _on_reasoning))
    # Sentinel closes the drain loop whether the turn succeeded or raised; it
    # queues behind any reasoning already emitted, so nothing is dropped.
    task.add_done_callback(lambda _: queue.put_nowait(None))

    while (fragment := await queue.get()) is not None:
        yield sse_frame({"type": "reasoning", "content": fragment})

    error_frame, updated = await _resolve_advance_task(task, interview_id)
    if error_frame is not None:
        yield error_frame
        return
    yield sse_frame({"type": "interview", "interview": updated})


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


def _interview_stream(interview_id: str) -> StreamingResponse:
    """Wrap ``_advance_stream`` in a no-buffer SSE response."""
    return StreamingResponse(
        _advance_stream(interview_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("")
async def create_interview(
    body: CreateInterviewRequest, request: Request
) -> StreamingResponse:
    """Start a durable Agent interview and stream its opening turn."""
    interview = store.create_interview(
        client_id(request),
        body.research_challenge,
        audience=body.audience,
    )
    return _interview_stream(str(interview["id"]))


@router.get("")
async def list_interviews(request: Request) -> list[dict[str, Any]]:
    """List the caller's chats, newest first, without their transcripts.

    Scoped to the calling client exactly as ``_owned_interview`` is: a chat
    carries a scientist's unfinished research goal, so it is never listed
    across clients.
    """
    return store.list_interviews(client_id(request))


@router.get("/{interview_id}")
async def get_interview(interview_id: str, request: Request) -> dict[str, Any]:
    """Resume an owned interview with its full transcript and progress."""
    return _owned_interview(interview_id, request)


@router.post("/{interview_id}/turns")
async def add_interview_turn(
    interview_id: str, body: InterviewTurnRequest, request: Request
) -> StreamingResponse:
    """Append a scientist answer and stream the Agent's next turn."""
    interview = _owned_interview(interview_id, request)
    if interview["status"] != "active":
        raise HTTPException(status_code=409, detail="interview is not active")
    store.append_interview_turn(
        interview_id, store.NewInterviewTurn("user", body.content)
    )
    return _interview_stream(interview_id)


def _require_revisable_turn(
    interview: dict[str, Any], turn_id: int, role: str
) -> None:
    """Check the turn a revision targets, or raise a 4xx explaining why not.

    Raises:
        HTTPException: 409 when the interview is closed to revision, 404 when
            the turn is not one of its own, 409 when it is not the kind of
            turn this revision applies to.
    """
    if interview["status"] == "cancelled":
        raise HTTPException(status_code=409, detail="interview is cancelled")
    turn = next(
        (t for t in interview["turns"] if int(t["id"]) == turn_id), None
    )
    if turn is None:
        raise HTTPException(status_code=404, detail="turn not found")
    if turn["role"] != role:
        raise HTTPException(
            status_code=409, detail=f"turn is not a {role} turn"
        )


def _reset_derivation(interview_id: str) -> None:
    """Re-baseline the four fields after a rewind, and reopen the interview.

    The stored fields are the model's derivation from a transcript that no
    longer exists, so keeping them would feed the next turn exactly the
    conclusions the scientist just withdrew. They are cleared back to the
    opening challenge -- whatever the first surviving user turn says -- and
    the model re-derives the rest from what remains.
    """
    interview = store.get_interview(interview_id)
    assert interview is not None
    opening = next((t for t in interview["turns"] if t["role"] == "user"), None)
    store.update_interview(
        interview_id,
        {
            "research_challenge": str(opening["content"]) if opening else "",
            "focus_area": [],
            "preferences": [],
            "title": None,
        },
        "Continue the interview.",
        completed=False,
    )


@router.put("/{interview_id}/turns/{turn_id}")
async def edit_interview_turn(
    interview_id: str,
    turn_id: int,
    body: InterviewTurnRequest,
    request: Request,
) -> StreamingResponse:
    """Replace one scientist turn in place and re-answer from there.

    An edited prompt is a correction, not a new question: the turn is
    rewritten where it stands and the Agent answers it again, rather than the
    old wording staying in the transcript with the correction appended after
    it -- which is what makes the two readings of "what did I ask?" disagree.
    Everything the Agent said after it was derived from the old wording, so
    it goes with it.
    """
    interview = _owned_interview(interview_id, request)
    _require_revisable_turn(interview, turn_id, "user")
    store.rewind_interview(interview_id, turn_id)
    store.append_interview_turn(
        interview_id, store.NewInterviewTurn("user", body.content)
    )
    _reset_derivation(interview_id)
    return _interview_stream(interview_id)


@router.post("/{interview_id}/turns/{turn_id}/retry")
async def retry_interview_turn(
    interview_id: str, turn_id: int, request: Request
) -> StreamingResponse:
    """Discard one Agent turn and answer the same prompt again.

    Retry has to remove the answer it is replacing. Re-running the model
    with the rejected turn still in the transcript asks it to continue from
    the answer rather than to reconsider it.
    """
    interview = _owned_interview(interview_id, request)
    _require_revisable_turn(interview, turn_id, "agent")
    store.rewind_interview(interview_id, turn_id)
    _reset_derivation(interview_id)
    return _interview_stream(interview_id)


@router.put("/{interview_id}/fields")
async def edit_interview_fields(
    interview_id: str, body: InterviewFieldsRequest, request: Request
) -> dict[str, Any]:
    """Persist scientist edits and finalize when required fields are ready."""
    _owned_interview(interview_id, request)
    fields = body.model_dump()
    fields["focus_area"] = _clean_list(fields["focus_area"])
    fields["preferences"] = _clean_list(fields["preferences"])
    completed = _ready(fields)
    store.update_interview(
        interview_id,
        fields,
        None if completed else "Continue the interview.",
        completed=completed,
    )
    updated = store.get_interview(interview_id)
    assert updated is not None
    return updated
