"""Bounded tool-calling execution, request iterations and cached answers.

Transcript shaping and tool execution policies are supplied by their separate
modules. Shared request preparation remains in llm.precall.
"""

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
    (``llm.admission.credentials.current_api_key``) rather than carried on
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

    Each turn gets three physical attempts under the standard backoff and
    platform-quota parking policy. The retry boundary stops before tool
    execution, so tools from a completed turn are never replayed here.
    The mandatory-reasoning rung still raises the budget without changing
    the tool request's reasoning effort.

    Returns:
        The (response, final_content) pair, where final_content is None
        when the model asked for tools instead of answering.
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
    """Caches a successful tool-call loop result.

    Only called once the final content is validated, so a failed loop is
    retried fresh next time rather than replayed from a broken cache entry.

    Args:
        cache: The cache tier resolved for this call.
        request: The request identifying the cache entry.
        final_content: The validated final response text.
        messages: The full message history the loop accumulated.
    """
    cache.set(
        request,
        # Stored repaired, so a replay is valid however this turn ended.
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
    """Caches a finished tool-call loop and returns its result."""
    _cache_tool_call_result(cache, request, final_content, messages)
    return final_content, messages


def _raise_budget_exhausted(loop: ToolLoop) -> NoReturn:
    """Ends a loop that produced no answer, not even a closing one.

    Rare by construction: reaching a ceiling now buys a turn with the
    tools withheld first, and a model that has been working for a dozen
    turns has something to say when asked. This is what remains -- a
    loop whose closing turn failed or came back empty.

    Args:
        loop: The loop, for the ceilings to name in the message.

    Raises:
        RuntimeError: Always. Callers that can degrade catch it -- the
            simulation review falls back to mental simulation.
    """
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
    """Whether this loop has re-sent all the prompt tokens it may.

    Args:
        spent: Prompt tokens re-sent so far, this turn included.
        loop: The loop carrying the ceiling.
        iteration: The 0-based turn about to run, for the log line.

    Returns:
        True when the loop must stop before sending another turn.
    """
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
    """Whether this turn is the one to inject the wrap-up message on.

    Either ceiling can trigger it, since either can end the loop. The
    turn-count trigger fires on its exact iteration (matching the
    behaviour before spend was bounded); the spend trigger fires once, on
    the first turn at or past its threshold.

    Args:
        iteration: The 0-based turn about to run.
        handoff_at: The turn the turn-count policy warns on, or -1.
        spent: Prompt tokens re-sent so far.
        loop: The loop carrying the spend ceiling.
        handed_off: Whether a wrap-up turn was already injected.

    Returns:
        True to inject the wrap-up turn before this iteration.
    """
    if iteration == handoff_at:
        return True
    return not handed_off and spent >= _handoff_spend(loop.max_prompt_tokens)


def _drop_dead_context(messages: list[dict[str, Any]]) -> None:
    """Removes what the transcript is re-sending for nothing.

    Three passes, in this order because the third reads what the second
    leaves behind: superseded file writes, then evidence old enough that
    the model has finished with it, then a paper two searches both
    returned. Ageing must run before deduplication -- an aged record is
    a stub, and a deduplication pass that counted stubs as copies would
    elide the live copy against one, leaving no text at all (see
    ``llm.tools.transcript._is_note``).

    Together they are what keeps a loop's cost roughly linear in its
    turns instead of quadratic, which is the difference between a loop
    that finishes and one that stops on its token ceiling.

    Run at the top of every turn rather than at send time, so that the
    transcript the budget is counted against, the one sent to the
    provider, and the one handed back to the caller are the same object.
    Counting tokens the request will not carry is how a loop dies owing
    a budget it never spent.
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
    """Ends an out-of-room loop with an answer rather than with nothing.

    Reaching a ceiling used to raise, which threw away every token the
    loop had spent: a simulation that had written a model, run it and
    seen its numbers returned no observation at all, and the review fell
    back to imagining the mechanism it had just measured. The work is
    already paid for, so the loop buys one more turn with the tools
    withheld and reports what the model made of it.

    Deliberately not cached. This is the degraded outcome, and a cache
    that replayed it would hand a later run a partial answer as though
    the loop had finished.

    Args:
        request: The request whose model and sampling the closing turn
            reuses.
        messages: The conversation the loop accumulated.
        loop: The loop, for the ceilings to name if this fails too.

    Returns:
        The closing answer and the transcript that produced it.

    Raises:
        RuntimeError: If even the closing turn gave no answer.
    """
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
    """Runs tool-call iterations until a final response, then caches it.

    ``messages`` (seeded with the initial user turn) is mutated in place.

    Bounded twice, by turns and by the prompt tokens those turns re-send
    (see ``llm.tools.policy``), because a turn count does not bound cost:
    each turn resends the whole transcript, so the last turns of a long
    loop cost several times the first. Whichever ceiling is reached first
    ends the loop.

    Near either bound a one-shot wrap-up turn is injected (see
    ``_handoff_iteration``) so the model can land a partial answer instead
    of being cut off mid-investigation. Reaching a bound anyway is not a
    total loss: the loop buys one closing turn with the tools withheld
    (``_harvest_partial_answer``) rather than discarding everything it
    already paid for.

    Each turn first drops the file writes a later write superseded, which
    is dead weight the transcript would otherwise re-send forever.

    Raises:
        RuntimeError: If a ceiling is reached *and* the closing turn
            answers nothing either.
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
        if done:  # only True alongside a non-None final_content
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
    """The tool set and loop bound for a tool-calling completion.

    Attributes:
        tools: OpenAI-format tool definitions offered to the model.
        executor: Async callable that runs one tool call and returns its
            result payload.
        max_iterations: Maximum model<->tool round-trips before giving up.
        max_prompt_tokens: Prompt tokens this loop may re-send in total,
            summed over every turn. The second ceiling, and the one that
            actually bounds cost: a turn re-sends the whole transcript, so
            spend grows with the square of the turn count and a turn count
            alone cannot say what a loop will cost. Whichever ceiling is
            reached first ends the loop -- and ending it buys one closing
            turn beyond this figure, which is one transcript's worth of
            overshoot in exchange for the loop returning what it spent
            the rest of the budget learning.
        tool_contract: Optional resolved configuration behind ``tools`` --
            e.g. a tool registry's enabled sources and endpoints -- that can
            change how a tool call behaves without changing the schema
            offered to the model. Folded into the cache key alongside
            ``tools`` (see ``LLMCacheRequest.tool_contract``) so a
            cached transcript from an old configuration cannot replay under
            a new one. None for callers with no such external contract.
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
    """Call an LLM with tool access and handle tool execution loop.

    Implements an agent loop: the LLM can call tools, see the results, and
    keep iterating until it produces a final response (or raises, on a call
    failure or an exhausted ``loop.max_iterations``). ``options`` follows
    ``call_llm``'s cache/telemetry policy.

    Args:
        prompt: The rendered prompt seeding the conversation.
        spec: Which model to call and how to sample; ``json_schema`` and
            ``force_json`` are unused on this path.
        loop: The tool set, executor, and round-trip bound.
        options: Cache and telemetry behavior; defaults to
            ``LLMCallOptions()``.
    """
    opt = options if options is not None else LLMCallOptions()
    opt = _guard_cache_for_local_tools(loop, opt)
    # An explicit spec key temporarily overrides any run-scoped key for
    # this loop; every iteration reads the effective key back from the
    # context (see _build_tool_loop_completion_args).
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
        # Seed history with the initial user turn; resent in full each
        # iteration.
        messages = [{"role": "user", "content": prompt}]
        return await _run_tool_call_loop(
            request, messages, loop.executor, loop, cache
        )
