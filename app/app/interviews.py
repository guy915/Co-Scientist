"""Model-driven, durable research-goal interview API."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import store
from app.audience import AUDIENCE_PATTERN
from app.auth import client_id
from app.config import (
    THINKING_FLOOR_TIMEOUT_SECONDS,
    deepseek_thinking_kwargs,
    thinking_safe_max_tokens,
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
from app.llm_stream import stream_chunks
from app.qa import sse_frame

# Receives each chain-of-thought fragment as the model emits it.
ReasoningSink = Callable[[str], Awaitable[None]]

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/interviews", tags=["interviews"])

# Silence, not duration, is what marks an interview turn as lost. The turn
# streams and its chain of thought is relayed to the scientist as it arrives,
# so a long reasoning pass is visible progress, not a blank wait -- while a
# provider that has stopped answering goes quiet immediately. Bounding the
# total instead is what made a funded chain of thought fail the turn on the
# clock right after it stopped failing on the token budget.
_INTERVIEW_STALL_SECONDS = 45.0
# Derived so the clock cannot drift below the token budget it has to admit,
# plus room for the prompt round-trip either side of the reasoning.
_INTERVIEW_TOTAL_SECONDS = THINKING_FLOOR_TIMEOUT_SECONDS + 60.0


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


async def _stream_interview_content(
    interview: dict[str, Any], on_reasoning: ReasoningSink | None
) -> str:
    """Stream one Agent turn, relaying reasoning, and return its answer text.

    The call always streams so there is a single transport to reason about.
    DeepSeek emits the whole chain of thought as ``reasoning_content`` deltas
    before the first ``content`` delta, so reasoning can be surfaced live
    while the answer is still being written. Content deltas are accumulated
    silently: they are fragments of the response JSON, never prose to show a
    scientist.

    Returns:
        The concatenated answer content (still unparsed JSON).
    """
    import litellm

    model, messages, response_format = _interview_request(interview)
    response = await litellm.acompletion(
        model=model,
        messages=messages,
        response_format=response_format,
        temperature=0.3,
        # Thinking spends reasoning tokens against this budget before the
        # four-field answer, so the floor covers the reasoning and 3k is
        # what remains for the answer -- ample for four short fields.
        # Sizing this for the answer alone is what leaves a run untitled
        # and an interview turn blank; see thinking_safe_max_tokens.
        max_tokens=thinking_safe_max_tokens(model, 3_000),
        # Bounds establishing the stream; once chunks flow, stream_chunks
        # below owns the clock.
        timeout=_INTERVIEW_TOTAL_SECONDS,
        stream=True,
        **deepseek_thinking_kwargs(model),
    )
    return await _collect_stream_content(response, on_reasoning)


async def _collect_stream_content(
    response: Any, on_reasoning: ReasoningSink | None
) -> str:
    """Drain a streaming completion, relaying reasoning, into answer text."""
    content: list[str] = []
    async for chunk in stream_chunks(
        response,
        stall_seconds=_INTERVIEW_STALL_SECONDS,
        total_seconds=_INTERVIEW_TOTAL_SECONDS,
    ):
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        # Absent on non-thinking models and on providers that never reason.
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning and on_reasoning is not None:
            await on_reasoning(reasoning)
        if delta.content:
            content.append(delta.content)
    return "".join(content)


async def _call_interview_model(
    interview: dict[str, Any],
    on_reasoning: ReasoningSink | None = None,
) -> dict[str, Any]:
    """Call the configured semantic interview model with structured output.

    Args:
        interview: The durable interview row being advanced.
        on_reasoning: Optional sink for live chain-of-thought fragments.

    Returns:
        The parsed response object.

    Raises:
        HTTPException: 503 on any provider, timeout, or parse failure, which
            ``_advance`` converts into the deterministic fallback turn.
    """
    try:
        content = await _stream_interview_content(interview, on_reasoning)
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("interview response must be a JSON object")
        return {str(key): value for key, value in parsed.items()}
    except Exception as exc:
        logger.warning("Interview model failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="The interview Agent is temporarily unavailable.",
        ) from exc


def _fallback_interview_response(
    interview: dict[str, Any],
) -> dict[str, Any]:
    """Advance the four-field interview from explicit scientist answers.

    The recovery path never infers scientific content. It assigns each new
    answer to the field the Agent most recently requested, preserving a usable
    and resumable interview when the configured model is temporarily absent.
    """
    fields = dict(interview["fields"])
    user_turns = [
        str(turn["content"]).strip()
        for turn in interview["turns"]
        if turn["role"] == "user" and str(turn["content"]).strip()
    ]
    answers = user_turns[1:]
    if not fields.get("focus_area") and answers:
        fields["focus_area"] = [answers[0]]
    if not fields.get("preferences") and len(answers) > 1:
        fields["preferences"] = [answers[1]]
    completed = _ready(fields)
    if completed:
        message = "The research goal is ready for run configuration."
    elif not fields.get("focus_area"):
        message = (
            "Which scientific mechanisms or focus areas should this research "
            "prioritize?"
        )
    else:
        message = (
            "What constraints, available models or data, exclusions, and "
            "feasibility preferences should guide the work?"
        )
    return {
        "assistant_message": message,
        **fields,
        "completed": completed,
    }


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
    fields = _normalized_fields(response)
    message = str(response.get("assistant_message") or "").strip()
    if not message:
        raise HTTPException(
            status_code=502, detail="Interview Agent returned no message."
        )
    completed = _interview_turn_completed(response, fields, used_fallback)
    store.append_interview_turn(
        interview_id,
        store.NewInterviewTurn("agent", message, "".join(fragments)),
    )
    store.update_interview(
        interview_id,
        fields,
        None if completed else message,
        completed=completed,
    )
    updated = store.get_interview(interview_id)
    assert updated is not None
    return updated


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
