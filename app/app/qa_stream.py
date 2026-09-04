"""The model-backed half of grounded Q&A: streaming, with one tool round.

Split from ``app.qa`` (which owns framing, persistence and the offline
answer) to keep both files inside the size cap; ``app.qa`` re-exports
``stream_llm_deltas`` under its former private name, so the module remains
the monkeypatch surface tests already use.

The shape worth knowing: the prompt carries an *index* of the run's ideas,
never their bodies, so the first round is offered the ``search_ideas`` tool
(``app.qa_ideas``) and a model that needs idea text asks for it. That costs
a second round only when it is used.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from app import credentials, offline_guard, qa_ideas
from app.config import (
    THINKING_FLOOR_TIMEOUT_SECONDS,
    deepseek_thinking_kwargs,
    thinking_safe_max_tokens,
)
from app.llm_stream import stream_chunks

logger = logging.getLogger(__name__)

# A grounded answer cites passages and stays short; the ceiling is here so
# the reasoning is funded from its own headroom rather than the answer's.
_ANSWER_MAX_TOKENS = 4_000
# The answer streams into the chat as it is written, so silence is the only
# thing that distinguishes a dead provider from a thorough one.
_QA_STALL_SECONDS = 45.0
_QA_TOTAL_SECONDS = THINKING_FLOOR_TIMEOUT_SECONDS + 60.0


def _completion_request(
    model: str,
    api_key: str | None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Build the streaming completion request both rounds are made with.

    One shape for both: a tool round that forgot the token floor or the
    deadline fails exactly the way the first round would have, only later
    and with the tool result already paid for.
    """
    request: dict[str, Any] = {
        "model": model,
        "messages": messages,
        # Sending no budget takes the provider's default, which thinking can
        # exhaust before the first answer delta -- the stream then ends
        # clean and empty and the scientist gets a blank reply, not an error.
        "max_tokens": thinking_safe_max_tokens(model, _ANSWER_MAX_TOKENS),
        "timeout": _QA_TOTAL_SECONDS,
        "stream": True,
        "api_key": api_key,
        **deepseek_thinking_kwargs(model),
    }
    if tools:
        request["tools"] = tools
    return request


async def _stream_completion(
    request: dict[str, Any],
    tool_calls: dict[int, dict[str, Any]],
) -> AsyncGenerator[tuple[str, str], None]:
    """Stream one completion, yielding ``(kind, fragment)`` pairs.

    ``kind`` is ``"reasoning"`` for a chain-of-thought delta and ``"chunk"``
    for prose, mirroring ``run_start_announcement._stream_model_fragments``
    -- the request already asks for thinking (see ``_completion_request``),
    so this is the read side of that request rather than a new spend.

    Args:
        request: The completion request (see ``_completion_request``).
        tool_calls: Sink the response's tool-call fragments accumulate into,
            keyed by their index in the response.

    Yields:
        Non-empty ``(kind, fragment)`` pairs, in the order they arrive.
    """
    import litellm

    response = await litellm.acompletion(**request)
    async for chunk in stream_chunks(
        response,
        stall_seconds=_QA_STALL_SECONDS,
        total_seconds=_QA_TOTAL_SECONDS,
    ):
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta is None:
            continue
        qa_ideas.accumulate_tool_calls(tool_calls, delta)
        reasoning = getattr(delta, "reasoning_content", None) or ""
        if reasoning:
            yield "reasoning", str(reasoning)
        text = getattr(delta, "content", None) or ""
        if text:
            yield "chunk", str(text)


def _resolved_calls(
    tool_calls: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the accumulated tool calls that are actually callable.

    A call is only usable once its name has arrived; a provider that opened
    a tool call and then changed its mind leaves a nameless fragment behind.
    Missing ids are filled in by index, because the tool result must name
    the call it answers and not every provider sends one.
    """
    resolved = []
    for index, call in sorted(tool_calls.items()):
        if not call.get("name"):
            continue
        resolved.append({**call, "id": call.get("id") or f"call_{index}"})
    return resolved


def _tool_result_messages(
    calls: list[dict[str, Any]], ideas: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Execute each tool call and render its result as a ``tool`` message."""
    return [
        {
            "role": "tool",
            "tool_call_id": call["id"],
            "name": call["name"],
            "content": qa_ideas.run_tool_call(call, ideas),
        }
        for call in calls
    ]


async def stream_llm_deltas(
    model: str,
    system_prompt: str,
    question: str,
    ideas: list[dict[str, Any]],
) -> AsyncGenerator[tuple[str, str], None]:
    """Stream the answer, letting the model look up idea bodies once first.

    The prompt carries an index of the run's ideas but not their text (see
    ``qa_run_state.render_idea_index``), so the first round is offered the
    ``search_ideas`` tool. A model that answers straight away costs exactly
    what it did before; only a model that asks for ideas pays for a second
    round, which is offered no tools and therefore has to answer.

    Deltas already yielded are what closes the loop: a model that wrote part
    of an answer *and then* asked for a tool has its request ignored, since
    the scientist is reading that answer and a second one would be appended
    to the middle of it. Only prose counts as "wrote part of an answer" --
    reasoning alone (a model still thinking, not yet writing) does not skip
    the tool round.

    Args:
        model: The chat model to complete with.
        system_prompt: The assembled grounding prompt.
        question: The scientist's question.
        ideas: The run's ideas, which the tool searches.

    Yields:
        Non-empty ``(kind, fragment)`` pairs of the final answer -- see
        ``_stream_completion``.
    """
    # The endpoint already routes an offline process to the deterministic
    # grounded answer, so this never fires from there. It is here so the
    # invariant belongs to the call that makes the request rather than to
    # one caller that remembers to check -- any later caller of
    # stream_answer inherits it.
    offline_guard.require_remote_chat("Q&A")
    # A scoped bring-your-own-key credential overrides both the model and
    # the deployment credential for this call.
    model, api_key = credentials.byok_model_and_key(model)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]
    tools = [qa_ideas.tool_declaration()] if ideas else None
    tool_calls: dict[int, dict[str, Any]] = {}
    answered = False
    async for kind, fragment in _stream_completion(
        _completion_request(model, api_key, messages, tools), tool_calls
    ):
        if kind == "chunk":
            answered = True
        yield kind, fragment
    calls = _resolved_calls(tool_calls)
    if answered or not calls:
        return
    messages += [
        qa_ideas.assistant_tool_message(calls),
        *_tool_result_messages(calls, ideas),
    ]
    async for kind, fragment in _stream_completion(
        _completion_request(model, api_key, messages, None), {}
    ):
        yield kind, fragment
