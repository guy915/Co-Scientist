"""The interview's provider call and its deterministic recovery path.

Split out of ``app.interviews``: this module owns one Agent turn's contact
with the model -- the streaming request, its bounds, draining the stream, and
the fallback that keeps the interview usable when the provider is absent.
``app.interviews`` owns the durable turn lifecycle and the HTTP surface, and
re-exports every name here, so ``interviews._call_interview_model`` remains
the monkeypatch seam it has always been.
"""

from __future__ import annotations

import dataclasses
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
from app.interviews_wire import TurnSplitter
from app.llm_stream import stream_chunks

# Receives each chain-of-thought fragment as the model emits it.
ReasoningSink = Callable[[str], Awaitable[None]]
# Receives each fragment of the answer's prose as the model writes it.
ProseSink = Callable[[str], Awaitable[None]]


@dataclasses.dataclass(frozen=True)
class TurnSinks:
    """Where one streamed turn's two live channels are relayed.

    Both are optional: a caller that only wants the resolved turn (the
    non-streaming ``POST`` path, and every test that drives a turn directly)
    passes neither and receives the same result.
    """

    on_reasoning: ReasoningSink | None = None
    on_prose: ProseSink | None = None


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
    interview: dict[str, Any], sinks: TurnSinks
) -> tuple[str, dict[str, Any] | None]:
    """Stream one Agent turn, relaying it live, and return what it resolved to.

    The call always streams so there is a single transport to reason about.
    DeepSeek emits the whole chain of thought as ``reasoning_content`` deltas
    before the first ``content`` delta, so reasoning surfaces live while the
    answer is still being written. Content deltas are the answer's prose and
    are relayed as they arrive, up to the trailing spec block, which is
    withheld and parsed at the end (see ``app.interviews_wire``).

    Returns:
        The turn's whole prose and its parsed fields, the latter None when
        the turn carried no usable spec block.
    """
    import litellm

    # Refuse before the request is shaped, not after: the prompt carries the
    # scientist's research goal verbatim, and forced offline means it does
    # not leave the process. The raise lands in _call_interview_model's
    # except branch, which is the same 503 -> scripted-turn path an absent
    # provider already takes.
    offline_guard.require_remote_chat("the interview")
    model, messages = _interview_request(interview)
    # A scoped bring-your-own-key credential overrides both the model and
    # the deployment credential for this turn.
    model, api_key = credentials.byok_model_and_key(model)
    response = await litellm.acompletion(
        model=model,
        messages=messages,
        temperature=0.3,
        # Thinking spends reasoning tokens against this budget before the
        # answer, so the floor covers the reasoning and this is what remains
        # for the prose and its spec block. Sizing this for the answer alone
        # is what leaves a run untitled and an interview turn blank; see
        # thinking_safe_max_tokens. Raised from 3k when the block learned to
        # carry clickable answers: a turn offering three options writes a
        # label and a description for each on top of the five fields it
        # already restates every turn, and a budget that funds the prose but
        # truncates the block loses the whole turn's state, not just the
        # options.
        max_tokens=thinking_safe_max_tokens(model, 4_000),
        # Bounds establishing the stream; once chunks flow, stream_chunks
        # below owns the clock.
        timeout=_INTERVIEW_TOTAL_SECONDS,
        stream=True,
        **deepseek_thinking_kwargs(model),
        api_key=api_key,
    )
    return await _collect_stream_content(response, sinks)


async def _emit(sink: ProseSink | None, text: str) -> None:
    """Relay ``text`` when there is both a sink and something to say."""
    if text and sink is not None:
        await sink(text)


async def _relay_chunk(
    chunk: Any, splitter: TurnSplitter, sinks: TurnSinks
) -> None:
    """Relay one stream chunk's reasoning and prose to their sinks.

    ``reasoning_content`` is absent on non-thinking models and on providers
    that never reason. Content goes through the splitter rather than to the
    sink directly, so the trailing spec block is withheld from the scientist
    instead of appearing and then being retracted.
    """
    if not chunk.choices:
        return
    delta = chunk.choices[0].delta
    await _emit(
        sinks.on_reasoning, getattr(delta, "reasoning_content", "") or ""
    )
    await _emit(sinks.on_prose, splitter.feed(delta.content or ""))


async def _collect_stream_content(
    response: Any, sinks: TurnSinks
) -> tuple[str, dict[str, Any] | None]:
    """Drain a streaming completion into relayed prose and parsed fields."""
    splitter = TurnSplitter()
    async for chunk in stream_chunks(
        response,
        stall_seconds=_INTERVIEW_STALL_SECONDS,
        total_seconds=_INTERVIEW_TOTAL_SECONDS,
    ):
        await _relay_chunk(chunk, splitter, sinks)
    trailing, whole, fields = splitter.finish()
    await _emit(sinks.on_prose, trailing)
    return whole, fields


def _turn_response(
    interview: dict[str, Any], prose: str, fields: dict[str, Any] | None
) -> dict[str, Any]:
    """Assemble one turn's response from its prose and its parsed fields.

    A turn that carried no usable spec block keeps the interview's previous
    fields, which is why this is not an error: the fields are cumulative
    interview state, not a per-turn derivation, so "no block" and "this turn
    learned nothing new" are the same claim. Callers downstream cannot tell
    the difference, and must not -- the scientist still gets the prose.

    Args:
        interview: The durable interview row being advanced.
        prose: The turn's whole message to the scientist.
        fields: The parsed spec block, or None when there was none.

    Returns:
        The response object in the shape ``_resolved_turn`` reads.
    """
    if fields is None:
        logger.warning(
            "Interview turn carried no usable spec block; keeping fields"
        )
        return {
            "assistant_message": prose,
            **dict(interview["fields"]),
            "completed": False,
        }
    return {**fields, "assistant_message": prose}


async def _call_interview_model(
    interview: dict[str, Any],
    on_reasoning: ReasoningSink | None = None,
    on_prose: ProseSink | None = None,
) -> dict[str, Any]:
    """Call the configured interview model for one turn.

    Args:
        interview: The durable interview row being advanced.
        on_reasoning: Optional sink for live chain-of-thought fragments.
        on_prose: Optional sink for the answer's prose as it is written.

    Returns:
        The turn's response object.

    Raises:
        HTTPException: 503 on any provider or timeout failure, which
            ``_advance`` converts into the deterministic fallback turn. A
            missing or malformed spec block is *not* such a failure; see
            ``_turn_response``.
    """
    try:
        prose, fields = await _stream_interview_content(
            interview, TurnSinks(on_reasoning=on_reasoning, on_prose=on_prose)
        )
    except Exception as exc:
        logger.warning("Interview model failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="The interview Agent is temporarily unavailable.",
        ) from exc
    return _turn_response(interview, prose, fields)


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
