"""One turn of a tool-calling loop, and what a failed turn is answered with.

Split from ``llm_tool_loop`` for the file-size ceiling. The seam is the
turn: this module sends one completion, dispatches whatever tools it
asked for, and decides what a turn that answered nothing needs *changed*
before being sent again. The loop above it decides how many turns there
are and what to do when they run out.

``llm_tool_loop`` re-exports every name here under its original private
spelling, so that module stays the single import path and the seam tests
patch.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from co_scientist.cache import LLMCacheRequest
from co_scientist.llm_credentials import current_api_key
from co_scientist.llm_json_escalation import (
    BudgetEscalation,
    escalated_max_tokens,
    escalation_for_error,
    log_escalation,
)
from co_scientist.llm_request import (
    _acompletion_within_timeout,
    _apply_api_key,
    _apply_thinking_args,
    _apply_timeout,
)
from co_scientist.llm_response import _extract_completion_content
from co_scientist.llm_tool_transcript import (
    _message_to_history_dict,
    normalize_tool_transcript,
)
from co_scientist.tool_effects import batch_by_effects

logger = logging.getLogger(__name__)


async def _execute_tool_calls(
    tool_calls: list[Any],
    tool_executor: Callable[[Any], Awaitable[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Executes a turn's tool calls, concurrently where effects allow it.

    Calls are grouped into contiguous runs that may share a batch (see
    ``tool_effects.batch_by_effects``); each batch is gathered, and a
    barrier tool -- one that writes, appends, or spawns a process -- is a
    batch of one, so it runs alone. Batches execute in order, so a model
    that asked for read-then-write-then-read gets exactly that.

    Every tool on this host is a read-only MCP call today, which resolves
    to a single batch and the same unconditional concurrency this function
    had before effects existed. The grouping earns its keep the moment a
    tool executes code.

    Args:
        tool_calls: The tool_calls list from the assistant message.
        tool_executor: Async callable that executes a single tool call and
            returns its tool response message.

    Returns:
        The tool response messages, in the same order as ``tool_calls``.
    """
    results: list[dict[str, Any]] = []
    for batch in batch_by_effects(tool_calls):
        results.extend(
            await asyncio.gather(*[tool_executor(tc) for tc in batch])
        )
    return results


def _build_tool_loop_completion_args(
    messages: list[dict[str, Any]],
    request: LLMCacheRequest,
    escalation: BudgetEscalation = BudgetEscalation.NONE,
) -> dict[str, Any]:
    """Builds the keyword arguments for one tool-loop completion call.

    Same two-layer timeout ceiling as ``call_llm``: ask the provider client
    to give up on its own, leaving the hard cancellation to the caller's
    ``_acompletion_within_timeout`` await. Both layers are the run-wide
    ``COSCIENTIST_LLM_TIMEOUT_SECONDS`` ceiling, which no call site narrows,
    so the deadline that has to admit a funded chain of thought is already
    the same one every other completion gets.

    Thinking mode goes through the same ``_apply_thinking_args`` as
    ``call_llm`` rather than being restated here, because that helper also
    carries the ``max_tokens`` floor a thinking call needs -- restating only
    the provider knobs sent every draft and validation-synthesis turn out
    thinking on an answer-sized budget. The tool loop always thinks: nothing
    on this path exposes the opt-out.

    The bring-your-own-key credential is read from the task context
    (``llm_credentials.current_api_key``) rather than carried on
    ``request``: the request doubles as the cache key and must stay
    credential-free.

    Args:
        messages: The running conversation resent on every iteration.
        request: The tool-call request (model, tools, token, temperature).
        escalation: The rung this attempt is being made at, which raises
            the budget and, at the top, turns thinking off. ``NONE`` sends
            the call exactly as its caller sized it.

    Returns:
        Keyword arguments ready to pass to ``litellm.acompletion``.
    """
    completion_args: dict[str, Any] = {
        "model": request.model_name,
        # Repaired here rather than at each place a transcript can be
        # cut: the send is the one point that must never see a broken
        # pairing, since the provider rejects the whole request.
        "messages": normalize_tool_transcript(messages),
        "tools": request.tools,
        "max_tokens": escalated_max_tokens(request.max_tokens, escalation),
        "temperature": request.temperature,
        "drop_params": True,
    }
    _apply_thinking_args(
        completion_args,
        request.model_name,
        enable_thinking=escalation is not BudgetEscalation.NO_THINKING,
    )
    _apply_timeout(completion_args)
    _apply_api_key(completion_args, current_api_key())
    return completion_args


async def _run_tool_call_iteration(
    messages: list[dict[str, Any]],
    request: LLMCacheRequest,
    tool_executor: Callable[[Any], Awaitable[dict[str, Any]]],
    escalation: BudgetEscalation = BudgetEscalation.NONE,
) -> tuple[bool, str | None]:
    """Runs one LLM-with-tools iteration; mutates `messages` in place.

    Returns:
        Tuple of (done, final_content). When done is True, final_content
        holds the finalized response text (already validated via
        _finalize_tool_call_response); when False, tool calls were
        dispatched and appended to `messages` and the caller should iterate
        again.
    """
    completion_args = _build_tool_loop_completion_args(
        messages, request, escalation
    )
    response = await _acompletion_within_timeout(
        completion_args, request.model_name
    )

    message = response.choices[0].message

    if hasattr(message, "tool_calls") and message.tool_calls:
        # LLM wants to call tools: execute them in parallel, add the
        # results to message history, and continue the loop.
        logger.debug("llm requested %s tool calls", len(message.tool_calls))
        messages.append(_message_to_history_dict(message))
        messages.extend(
            await _execute_tool_calls(message.tool_calls, tool_executor)
        )
        return False, None

    # No tool calls - this is the final response. Classified by
    # `_extract_completion_content` rather than by a check of its own,
    # because an empty answer here has the same three causes it has on
    # the plain path and only one of them is answered by a different
    # budget -- and writing a program is the most reasoning-heavy thing
    # anything asks a model for, so this path meets that wall often.
    #
    # Recorded only once it validates: an answerless turn contributed
    # nothing, and leaving it in the transcript would resend it as an
    # empty assistant message on the very retry that answers it.
    final = _extract_completion_content(response, request.model_name)
    messages.append(_message_to_history_dict(message))
    return True, final


async def _run_iteration_logged(
    messages: list[dict[str, Any]],
    request: LLMCacheRequest,
    tool_executor: Callable[[Any], Awaitable[dict[str, Any]]],
    iteration: int,
) -> tuple[bool, str | None]:
    """Runs one tool-call iteration, escalating an answerless completion.

    A turn that spent its whole budget reasoning is not answered by
    sending it again: the same request reasons its way into the same wall
    and is billed for it each time. So the rungs are climbed here, inside
    the iteration, rather than by spending the loop's turn budget on it --
    a turn is for the model's next *step*, and burning steps on a request
    that cannot answer would end the investigation with the work half
    done. The rung resets for the next iteration, since the budget was
    only ever wrong for that one turn's chain of thought.
    """
    escalation = BudgetEscalation.NONE
    while True:
        try:
            return await _run_tool_call_iteration(
                messages, request, tool_executor, escalation
            )
        except Exception as e:
            escalated = escalation_for_error(e, escalation)
            if escalated is None:
                logger.error(
                    "Error in LLM tool call loop (iteration %s): %s",
                    iteration + 1,
                    e,
                )
                raise
            log_escalation(e, escalated)
            escalation = escalated
