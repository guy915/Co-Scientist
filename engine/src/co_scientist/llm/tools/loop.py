from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any, NoReturn

from co_scientist.cache import LLMCache, LLMCacheRequest, NullCache
from co_scientist.exceptions import (
    FreeModelEligibilityError,
    LLMCallBudgetExceededError,
)
from co_scientist.llm.admission.free_policy import (
    current_api_key,
    scoped_api_key,
)
from co_scientist.llm.attempts.escalation import (
    BudgetEscalation,
    escalated_max_tokens,
)
from co_scientist.llm.attempts.retry import Attempt, AttemptPlan, run_attempts
from co_scientist.llm.precall import _prepare_llm_call
from co_scientist.llm.request.completion import (
    _acompletion_within_timeout,
    _apply_api_key,
    _apply_timeout,
)
from co_scientist.llm.request.response import _extract_completion_content
from co_scientist.llm.request.thinking import _apply_thinking_args
from co_scientist.llm.tools.policy import (
    DEFAULT_TOOL_LOOP_TOKEN_BUDGET,
    _guard_cache_for_local_tools,
    _handoff_iteration,
    _handoff_message,
    _handoff_spend,
    _turns_remaining,
    closing_message,
    transcript_tokens,
)
from co_scientist.llm.tools.transcript import (
    _message_to_history_dict,
    elide_aged_evidence,
    elide_repeated_papers,
    elide_superseded_writes,
    normalize_tool_transcript,
)
from co_scientist.llm.values import CompletionSpec, LLMCallOptions
from co_scientist.tool_effects import batch_by_effects

logger = logging.getLogger(__name__)


async def _execute_tool_calls(
    tool_calls: list[Any],
    tool_executor: Callable[[Any], Awaitable[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Effect barriers run alone in model-requested order; batching must not
    reorder read/write effects.
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
    """Use the shared thinking floor and both timeout layers; credentials
    stay out of cache keys.
    """
    completion_args: dict[str, Any] = {
        "model": request.model_name,
        # Repair at send time so every cut transcript reaches the provider with
        # valid pairing.
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
    message = response.choices[0].message
    if getattr(message, "tool_calls", None):
        return None
    return _extract_completion_content(response, model_name)


async def _answered_completion(
    messages: list[dict[str, Any]],
    request: LLMCacheRequest,
    iteration: int,
) -> tuple[Any, str | None]:
    """Retries must stop before tool execution or repeat side effects.
    Reset rungs per turn to preserve the investigation step budget.
    """

    async def make_attempt(attempt: Attempt) -> tuple[Any, str | None]:
        response = await _acompletion_within_timeout(
            _build_tool_loop_completion_args(messages, request, attempt.rung),
            request.model_name,
        )
        return response, _final_content(response, request.model_name)

    return await run_attempts(
        make_attempt, AttemptPlan(request.model_name, max_attempts=3)
    )


async def _run_tool_call_iteration(
    messages: list[dict[str, Any]],
    request: LLMCacheRequest,
    tool_executor: Callable[[Any], Awaitable[dict[str, Any]]],
    iteration: int = 0,
) -> tuple[bool, str | None]:
    response, final = await _answered_completion(messages, request, iteration)
    message = response.choices[0].message

    if final is None:
        logger.debug("llm requested %s tool calls", len(message.tool_calls))
        messages.append(_message_to_history_dict(message))
        messages.extend(
            await _execute_tool_calls(message.tool_calls, tool_executor)
        )
        return False, None

    # Do not retain answerless assistant turns: the answering retry would resend
    # an empty message.
    messages.append(_message_to_history_dict(message))
    return True, final


async def _run_iteration_logged(
    messages: list[dict[str, Any]],
    request: LLMCacheRequest,
    tool_executor: Callable[[Any], Awaitable[dict[str, Any]]],
    iteration: int,
) -> tuple[bool, str | None]:
    """The attempt boundary logs because it knows whether a retry follows."""
    return await _run_tool_call_iteration(
        messages, request, tool_executor, iteration
    )


async def _answer_without_tools(
    messages: list[dict[str, Any]],
    request: LLMCacheRequest,
) -> str | None:
    """Withholding tools turns paid investigation into prose, not more actions.
    Provider-call budget errors must propagate, never become empty fallbacks.
    """
    closing = replace(request, tools=[])
    args = _build_tool_loop_completion_args(
        [*messages, closing_message()], closing
    )
    args.pop("tools", None)
    try:
        response = await _acompletion_within_timeout(args, request.model_name)
        return _extract_completion_content(response, request.model_name)
    except (LLMCallBudgetExceededError, FreeModelEligibilityError):
        raise
    except Exception as exc:
        logger.warning("Could not harvest a final answer: %s", exc)
        return None


def _cache_tool_call_result(
    cache: LLMCache | NullCache,
    request: LLMCacheRequest,
    final_content: str,
    messages: list[dict[str, Any]],
) -> None:
    """Only validated final content is cached; failed loops must retry fresh."""
    cache.set(
        request,
        # Cache repaired transcripts so replay remains valid regardless of how
        # the turn ended.
        {
            "final_response": final_content,
            "message_history": normalize_tool_transcript(messages),
        },
    )


def _finalize_tool_loop_success(
    cache: LLMCache | NullCache,
    request: LLMCacheRequest,
    final_content: str,
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    _cache_tool_call_result(cache, request, final_content, messages)
    return final_content, messages


def _raise_budget_exhausted(loop: ToolLoop) -> NoReturn:
    logger.warning(
        "Tool call loop gave no final answer within %s iterations /"
        " %s prompt tokens",
        loop.max_iterations,
        loop.max_prompt_tokens,
    )
    raise RuntimeError(
        "LLM tool call loop exhausted its budget"
        f" (max_iterations={loop.max_iterations},"
        f" max_prompt_tokens={loop.max_prompt_tokens})"
    )


def _spend_exhausted(spent: int, loop: ToolLoop, iteration: int) -> bool:
    if spent < loop.max_prompt_tokens:
        return False
    logger.warning(
        "Token budget (%s) reached in tool call loop after %s iterations;"
        " %s tokens re-sent",
        loop.max_prompt_tokens,
        iteration,
        spent,
    )
    return True


def _handoff_due(
    iteration: int,
    handoff_at: int,
    spent: int,
    loop: ToolLoop,
    handed_off: bool,
) -> bool:
    if iteration == handoff_at:
        return True
    return not handed_off and spent >= _handoff_spend(loop.max_prompt_tokens)


def _drop_dead_context(messages: list[dict[str, Any]]) -> None:
    """Age before deduplication so old stubs cannot erase fresh evidence.
    Count, send and return the same transcript to avoid billing unsent text.
    """
    elided = elide_superseded_writes(messages)
    if elided:
        logger.debug("elided %s superseded file write(s)", elided)
    aged = elide_aged_evidence(messages)
    if aged:
        logger.debug("elided %s aged evidence result(s)", aged)
    repeats = elide_repeated_papers(messages)
    if repeats:
        logger.debug("elided %s repeated paper record(s)", repeats)


async def _harvest_partial_answer(
    request: LLMCacheRequest,
    messages: list[dict[str, Any]],
    loop: ToolLoop,
) -> tuple[str, list[dict[str, Any]]]:
    """Do not cache a degraded partial answer as a completed investigation."""
    answer = await _answer_without_tools(messages, request)
    if not answer:
        _raise_budget_exhausted(loop)
    logger.info(
        "Tool call loop ran out of room; harvested a %s-character partial"
        " answer",
        len(answer),
    )
    return answer, messages


async def _run_tool_call_loop(
    request: LLMCacheRequest,
    messages: list[dict[str, Any]],
    tool_executor: Callable[[Any], Awaitable[dict[str, Any]]],
    loop: ToolLoop,
    cache: LLMCache | NullCache,
) -> tuple[str, list[dict[str, Any]]]:
    """Turns resend the whole transcript, so a turn count alone cannot bound
    spend.
    """
    max_iterations = loop.max_iterations
    handoff_at = _handoff_iteration(max_iterations)
    handed_off = False
    spent = 0
    for iteration in range(max_iterations):
        logger.debug(
            "llm tool call iteration %s/%s", iteration + 1, max_iterations
        )
        _drop_dead_context(messages)
        spent += transcript_tokens(messages)
        if _spend_exhausted(spent, loop, iteration):
            return await _harvest_partial_answer(request, messages, loop)
        if _handoff_due(iteration, handoff_at, spent, loop, handed_off):
            handed_off = True
            messages.append(
                _handoff_message(
                    _turns_remaining(iteration, spent, loop, messages)
                )
            )
        done, final_content = await _run_iteration_logged(
            messages, request, tool_executor, iteration
        )
        if done:
            assert final_content is not None
            logger.debug("llm finished after %s iterations", iteration + 1)
            return _finalize_tool_loop_success(
                cache, request, final_content, messages
            )

    return await _harvest_partial_answer(request, messages, loop)


async def _prepare_tool_call(
    request: LLMCacheRequest, opts: LLMCallOptions
) -> tuple[
    LLMCacheRequest,
    LLMCache | NullCache,
    tuple[str, list[dict[str, Any]]] | None,
]:
    request, cache, cached_response = await _prepare_llm_call(request, opts)
    if cached_response is None:
        return request, cache, None
    logger.debug("using cached llm tool call response")
    return (
        request,
        cache,
        (
            cached_response["final_response"],
            cached_response["message_history"],
        ),
    )


@dataclass(frozen=True)
class ToolLoop:
    """Tool configuration belongs in cache keys despite unchanged schemas.
    A closing turn can exceed local bounds but never the provider cap.
    """

    tools: list[dict[str, Any]]
    executor: Callable[[Any], Awaitable[dict[str, Any]]]
    max_iterations: int = 10
    max_prompt_tokens: int = DEFAULT_TOOL_LOOP_TOKEN_BUDGET
    tool_contract: dict[str, Any] | None = None


async def call_llm_with_tools(
    prompt: str,
    spec: CompletionSpec,
    loop: ToolLoop,
    options: LLMCallOptions | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    opt = options if options is not None else LLMCallOptions()
    opt = _guard_cache_for_local_tools(loop, opt)
    # An explicit key overrides this task context for the loop, not shared
    # backend state.
    with scoped_api_key(spec.api_key):
        request = LLMCacheRequest(
            prompt=prompt,
            model_name=spec.model_name,
            temperature=spec.temperature,
            max_tokens=spec.max_tokens,
            tools=loop.tools,
            tool_contract=loop.tool_contract,
        )
        request, cache, cached_result = await _prepare_tool_call(request, opt)
        if cached_result is not None:
            return cached_result
        messages = [{"role": "user", "content": prompt}]
        return await _run_tool_call_loop(
            request, messages, loop.executor, loop, cache
        )
