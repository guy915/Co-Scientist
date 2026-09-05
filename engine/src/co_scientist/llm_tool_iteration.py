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
from dataclasses import replace
from typing import Any

from co_scientist.cache import LLMCacheRequest
from co_scientist.exceptions import LLMCallBudgetExceededError
from co_scientist.llm_call_budget import record_provider_request
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
from co_scientist.llm_tool_policy import closing_message
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


def _final_content(response: Any, model_name: str) -> str | None:
    """The turn's answer, or None when it asked for tools instead.

    Raises:
        ValueError: If the turn asked for no tools and answered nothing;
            the subclass says which remedy applies.
    """
    message = response.choices[0].message
    if getattr(message, "tool_calls", None):
        return None
    return _extract_completion_content(response, model_name)


async def _answered_completion(
    messages: list[dict[str, Any]],
    request: LLMCacheRequest,
    iteration: int,
) -> tuple[Any, str | None]:
    """One turn's completion, escalating if it comes back answerless.

    A turn that spent its whole budget reasoning is not answered by
    sending it again: the same request reasons its way into the same wall
    and is billed for it each time. So the rungs are climbed here rather
    than by spending the loop's turn budget -- a turn is for the model's
    next *step*, and burning steps on a request that cannot answer would
    end the investigation with the work half done. The rung resets for
    the next turn, since the budget was only ever wrong for this one
    chain of thought.

    Scope matters as much as the ladder: this covers the completion and
    the answer's validation, and deliberately stops before the tools run.
    A retry that spanned tool execution would run a turn's tools twice
    for one request -- which for a local tool means writing the same
    files or starting the same command again, and leaves the earlier
    assistant turn in the transcript with nothing answering its calls.

    Returns:
        The (response, final_content) pair, where final_content is None
        when the model asked for tools instead of answering.
    """
    escalation = BudgetEscalation.NONE
    while True:
        try:
            # Every pass through this loop is a real outbound request --
            # count it before sending, same as the plain call_llm seam
            # (llm_call._call_llm_and_cache), so a run's ceiling sees a
            # tool-loop turn's own escalation attempts too.
            record_provider_request()
            response = await _acompletion_within_timeout(
                _build_tool_loop_completion_args(messages, request, escalation),
                request.model_name,
            )
            return response, _final_content(response, request.model_name)
        except Exception as exc:
            escalated = escalation_for_error(exc, escalation)
            if escalated is None:
                logger.error(
                    "Error in LLM tool call loop (iteration %s): %s",
                    iteration + 1,
                    exc,
                )
                raise
            log_escalation(exc, escalated)
            escalation = escalated


async def _run_tool_call_iteration(
    messages: list[dict[str, Any]],
    request: LLMCacheRequest,
    tool_executor: Callable[[Any], Awaitable[dict[str, Any]]],
    iteration: int = 0,
) -> tuple[bool, str | None]:
    """Runs one LLM-with-tools iteration; mutates `messages` in place.

    Returns:
        Tuple of (done, final_content). When done is True, final_content
        holds the finalized response text; when False, tool calls were
        dispatched and appended to `messages` and the caller should
        iterate again.
    """
    response, final = await _answered_completion(messages, request, iteration)
    message = response.choices[0].message

    if final is None:
        # LLM wants to call tools: execute them in parallel, add the
        # results to message history, and continue the loop.
        logger.debug("llm requested %s tool calls", len(message.tool_calls))
        messages.append(_message_to_history_dict(message))
        messages.extend(
            await _execute_tool_calls(message.tool_calls, tool_executor)
        )
        return False, None

    # Recorded only once it validates: an answerless turn contributed
    # nothing, and leaving it in the transcript would resend it as an
    # empty assistant message on the very retry that answers it.
    messages.append(_message_to_history_dict(message))
    return True, final


async def _run_iteration_logged(
    messages: list[dict[str, Any]],
    request: LLMCacheRequest,
    tool_executor: Callable[[Any], Awaitable[dict[str, Any]]],
    iteration: int,
) -> tuple[bool, str | None]:
    """Runs one tool-call iteration.

    Failures are logged where they are classified, in
    ``_answered_completion``, which is the layer that knows whether a
    retry follows.
    """
    return await _run_tool_call_iteration(
        messages, request, tool_executor, iteration
    )


async def _answer_without_tools(
    messages: list[dict[str, Any]],
    request: LLMCacheRequest,
) -> str | None:
    """Asks for a final answer with the tools taken away.

    The closing turn of a loop that ran out of room. Withholding the
    tools is what makes it closing: a model still holding them spends
    the turn calling one, which is precisely the state the loop is
    ending because it can no longer afford. With none offered the only
    move left is prose, so the work the loop already paid for comes back
    as an answer instead of being discarded.

    Args:
        messages: The conversation as it stands, left unmodified -- the
            caller owns what the transcript records.
        request: The request whose model and sampling this reuses.

    Returns:
        The model's closing answer, or None if it could not give one,
        which leaves the caller to fail the loop as it did before.

    Raises:
        LLMCallBudgetExceededError: If the run is already over its
            LLM-call ceiling -- propagated rather than degraded to None,
            since a run that has overspent must abort, not fall back to
            the loop's ordinary "gave no final answer" failure.
    """
    closing = replace(request, tools=[])
    args = _build_tool_loop_completion_args(
        [*messages, closing_message()], closing
    )
    args.pop("tools", None)
    try:
        record_provider_request()
        response = await _acompletion_within_timeout(args, request.model_name)
        return _extract_completion_content(response, request.model_name)
    except LLMCallBudgetExceededError:
        raise
    except Exception as exc:
        logger.warning("Could not harvest a final answer: %s", exc)
        return None
