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
from app.auth import require_principal
from app.config import deepseek_thinking_kwargs, settings
from app.qa import sse_frame

# Receives each chain-of-thought fragment as the model emits it.
ReasoningSink = Callable[[str], Awaitable[None]]

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/interviews", tags=["interviews"])

_INTERVIEW_TIMEOUT_SECONDS = 45.0
_RESPONSE_SCHEMA = {
    "name": "research_goal_interview",
    "schema": {
        "type": "object",
        "properties": {
            "assistant_message": {"type": "string", "minLength": 1},
            "research_challenge": {"type": "string", "minLength": 1},
            "focus_area": {"type": "array", "items": {"type": "string"}},
            "preferences": {"type": "array", "items": {"type": "string"}},
            "title": {"type": ["string", "null"]},
            "completed": {"type": "boolean"},
        },
        "required": [
            "assistant_message",
            "research_challenge",
            "focus_area",
            "preferences",
            "title",
            "completed",
        ],
        "additionalProperties": False,
    },
}

_SYSTEM_PROMPT = (
    "You are the Agent conducting Google Hypothesis Generation's "
    "research-goal interview. Collaboratively scope one scientific research "
    "goal. Ask exactly one concise, context-sensitive question at a time. "
    "Derive only information the scientist supplied; never invent laboratory "
    "capabilities, data, constraints, or preferences.\n\n"
    "Maintain exactly four structured fields:\n"
    "1. Research Challenge: the precise scientific question or hypothesis.\n"
    "2. Focus Area: scientific subareas or mechanisms to prioritize.\n"
    "3. Preferences: constraints, available data/models/tools, exclusions, "
    "novelty boundary, feasibility requirements, and desired output depth.\n"
    "4. Title: an optional concise title.\n\n"
    "Continue until the challenge is precise, at least one focus area is "
    "known, and meaningful preferences or an explicit statement that there "
    "are none is captured. Then summarize the finalized goal, set "
    "completed=true, and ask no further question. Return only schema-valid "
    "JSON."
)


class CreateInterviewRequest(BaseModel):
    """Initial scientist challenge for a new interview."""

    research_challenge: str = Field(..., min_length=1, max_length=20_000)


class InterviewTurnRequest(BaseModel):
    """One scientist answer or correction."""

    content: str = Field(..., min_length=1, max_length=20_000)


class InterviewFieldsRequest(BaseModel):
    """Scientist-authored edits to the four structured fields."""

    research_challenge: str = Field(..., min_length=1, max_length=20_000)
    focus_area: list[str]
    preferences: list[str]
    title: str | None = Field(None, max_length=200)


def _client_id(request: Request) -> str:
    """Return the verified researcher subject or compatibility scope."""
    return require_principal(request).subject


def _owned_interview(interview_id: str, request: Request) -> dict[str, Any]:
    """Return an owned interview or raise without leaking its existence."""
    interview = store.get_interview(interview_id)
    if interview is None or interview["client_id"] != _client_id(request):
        raise HTTPException(status_code=404, detail="interview not found")
    return interview


def _clean_list(raw: Any) -> list[str]:
    """Normalize a model- or user-produced list into non-empty strings."""
    if not isinstance(raw, list):
        return []
    return [str(value).strip() for value in raw if str(value).strip()]


def _normalized_fields(response: dict[str, Any]) -> dict[str, Any]:
    """Normalize the model response into the verified four-field contract."""
    title = response.get("title")
    return {
        "research_challenge": str(
            response.get("research_challenge") or ""
        ).strip(),
        "focus_area": _clean_list(response.get("focus_area")),
        "preferences": _clean_list(response.get("preferences")),
        "title": str(title).strip() if title else None,
    }


def _essentials_ready(fields: dict[str, Any]) -> bool:
    """Whether the essential scoping fields (challenge + focus) are present.

    Preferences are intentionally excluded: the interview contract treats an
    explicit "no constraints" as a valid terminal state (see the system
    prompt), so an empty preferences list must not block a model-confirmed
    completion. Used to validate the model's own ``completed`` signal.
    """
    return bool(fields["research_challenge"] and fields["focus_area"])


def _ready(fields: dict[str, Any]) -> bool:
    """Return whether required scoping fields contain substantive values.

    Requires preferences as well, so the deterministic recovery path (which
    fills fields from scientist answers in order) collects a preferences answer
    before it completes, rather than finalizing after the focus-area answer.
    """
    return bool(
        fields["research_challenge"]
        and fields["focus_area"]
        and fields["preferences"]
    )


def _prompt(interview: dict[str, Any]) -> str:
    """Render the persisted transcript and current derivation for the model."""
    transcript = [
        {"role": turn["role"], "content": turn["content"]}
        for turn in interview["turns"]
    ]
    context = {
        "current_fields": interview["fields"],
        "transcript": transcript,
    }
    return json.dumps(context, ensure_ascii=False)


def _interview_request(interview: dict[str, Any]) -> tuple[str, Any, Any]:
    """Build the model, messages, and response_format for one Agent turn.

    Args:
        interview: The durable interview row being advanced.

    Returns:
        A ``(model, messages, response_format)`` triple ready for litellm.
    """
    from co_scientist.llm_request import (
        _inject_schema_into_prompt,
        _supports_json_schema_response_format,
    )

    model = settings.effective_chat_model
    user_prompt = _prompt(interview)
    if _supports_json_schema_response_format(model):
        return (
            model,
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            {"type": "json_schema", "json_schema": _RESPONSE_SCHEMA},
        )
    # DeepSeek and other json_object-only providers reject the json_schema
    # response format; downgrade to json_object and restate the schema in the
    # prompt, mirroring the engine's provider-capability shim so the interview
    # survives providers the science path already handles.
    return (
        model,
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _inject_schema_into_prompt(
                    user_prompt, _RESPONSE_SCHEMA
                ),
            },
        ],
        {"type": "json_object"},
    )


async def _stream_interview_content(
    interview: dict[str, Any], on_reasoning: ReasoningSink | None
) -> str:
    """Stream one Agent turn, relaying reasoning, and return its answer text.

    The call always streams so there is a single transport to reason about.
    DeepSeek emits the whole chain of thought as ``reasoning_content`` deltas
    before the first ``content`` delta, so reasoning can be surfaced live while
    the answer is still being written. Content deltas are accumulated silently:
    they are fragments of the response JSON, never prose to show a scientist.

    Args:
        interview: The durable interview row being advanced.
        on_reasoning: Optional sink for chain-of-thought fragments. When None
            the reasoning is simply discarded.

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
        # four-field answer; 1.5k sufficed for short transcripts, 3k leaves
        # headroom for longer interviews.
        max_tokens=3_000,
        stream=True,
        **deepseek_thinking_kwargs(model),
    )
    content: list[str] = []
    async for chunk in response:
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
        content = await asyncio.wait_for(
            _stream_interview_content(interview, on_reasoning),
            timeout=_INTERVIEW_TIMEOUT_SECONDS,
        )
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


async def _advance(
    interview_id: str, on_reasoning: ReasoningSink | None = None
) -> dict[str, Any]:
    """Run one Agent turn and persist its derivation for later resume.

    Args:
        interview_id: The interview to advance.
        on_reasoning: Optional sink for live chain-of-thought fragments. The
            reasoning is relayed for display only and never persisted, so a
            resumed interview replays its turns without stale thinking.

    Returns:
        The updated interview row.
    """
    interview = store.get_interview(interview_id)
    assert interview is not None
    used_fallback = False
    try:
        response = await _call_interview_model(interview, on_reasoning)
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        response = _fallback_interview_response(interview)
        used_fallback = True
    fields = _normalized_fields(response)
    message = str(response.get("assistant_message") or "").strip()
    if not message:
        raise HTTPException(
            status_code=502, detail="Interview Agent returned no message."
        )
    if used_fallback:
        # The deterministic recovery path sequences its questions via _ready,
        # so let it collect a preferences answer before completing.
        completed = _ready(fields)
    else:
        # Trust the model's own completion signal once the essentials are
        # captured. Empty preferences is a valid "no constraints" terminal
        # state per the interview contract, so requiring it here would deadlock
        # the interview whenever the scientist has no additional constraints.
        completed = bool(response.get("completed")) and _essentials_ready(
            fields
        )
    store.append_interview_turn(interview_id, "agent", message)
    store.update_interview(
        interview_id,
        fields,
        None if completed else message,
        completed=completed,
    )
    updated = store.get_interview(interview_id)
    assert updated is not None
    return updated


async def _advance_stream(interview_id: str) -> AsyncIterator[str]:
    """Advance one turn as SSE: live reasoning frames, then the interview.

    The Agent's turn runs as a task that pushes chain-of-thought fragments onto
    a queue while this generator drains it, so reasoning reaches the scientist
    as the model produces it rather than after the answer lands. The closing
    ``interview`` frame carries exactly what the turn resolved to, including
    the deterministic fallback when the provider fails.

    Args:
        interview_id: The interview to advance.

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

    try:
        updated = await task
    except HTTPException as exc:
        yield sse_frame({"type": "error", "detail": str(exc.detail)})
        return
    except Exception:
        logger.exception("Interview turn failed for %s", interview_id)
        yield sse_frame(
            {"type": "error", "detail": "The interview Agent failed."}
        )
        return
    yield sse_frame({"type": "interview", "interview": updated})


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
        _client_id(request), body.research_challenge
    )
    return _interview_stream(str(interview["id"]))


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
    store.append_interview_turn(interview_id, "user", body.content)
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
