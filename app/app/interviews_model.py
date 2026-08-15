"""The interview's provider call and its deterministic recovery path.

Split out of ``app.interviews``: this module owns one Agent turn's contact
with the model -- the streaming request, its bounds, draining the stream, and
the fallback that keeps the interview usable when the provider is absent.
``app.interviews`` owns the durable turn lifecycle and the HTTP surface, and
re-exports every name here, so ``interviews._call_interview_model`` remains
the monkeypatch seam it has always been.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException

from app import credentials, offline_guard
from app.config import (
    THINKING_FLOOR_TIMEOUT_SECONDS,
    deepseek_thinking_kwargs,
    thinking_safe_max_tokens,
)
from app.interviews_prompts import _interview_request, _ready
from app.llm_stream import stream_chunks

# Receives each chain-of-thought fragment as the model emits it.
ReasoningSink = Callable[[str], Awaitable[None]]

logger = logging.getLogger(__name__)

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

    # Refuse before the request is shaped, not after: the prompt carries the
    # scientist's research goal verbatim, and forced offline means it does
    # not leave the process. The raise lands in _call_interview_model's
    # except branch, which is the same 503 -> scripted-turn path an absent
    # provider already takes.
    offline_guard.require_remote_chat("the interview")
    model, messages, response_format = _interview_request(interview)
    # A scoped bring-your-own-key credential overrides both the model and
    # the deployment credential for this turn.
    model, api_key = credentials.byok_model_and_key(model)
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
        api_key=api_key,
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
    """Advance the five-field interview from explicit scientist answers.

    The recovery path never infers scientific content. It assigns each new
    answer to the field the Agent most recently requested, preserving a usable
    and resumable interview when the configured model is temporarily absent.
    The scripted sequence completes without eliciting lab constraints (K5):
    the field stays at its empty "none declared" state, which the engine
    treats as "no constraints". The turns it authors are marked as fallback
    when persisted (see ``interviews._resolved_turn``), so the UI can signal
    them as guided questions rather than silently passing them off as model
    output.
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
