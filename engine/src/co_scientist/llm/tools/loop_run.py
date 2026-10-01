"""Runs the bounded tool-call loop and caches its finished result.

Split out of ``llm.tools.loop`` to keep that module within the size cap.
Holds the per-turn budget bookkeeping (spend tracking, the wrap-up-turn
timing, dropping dead transcript weight), the degraded-but-answered exit
when a ceiling is reached, the loop driver that ties them together, and
the small cache-write glue the driver's success path calls. The
cache-*lookup* sequence (``_prepare_llm_call``/``_resolve_cache``) stays in
``llm.tools.loop``, since its ``get_cache()`` call is what tests patch by
that module's name. Every name is re-exported from ``llm.tools.loop``, so
callers and monkeypatching tests are unaffected.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, NoReturn

from co_scientist.cache import LLMCache, LLMCacheRequest, NullCache
from co_scientist.llm.tools.iteration import (
    _answer_without_tools,
    _run_iteration_logged,
)
from co_scientist.llm.tools.policy import (
    _handoff_iteration,
    _handoff_message,
    _handoff_spend,
    _turns_remaining,
    transcript_tokens,
)
from co_scientist.llm.tools.transcript import (
    elide_aged_evidence,
    elide_repeated_papers,
    elide_superseded_writes,
    normalize_tool_transcript,
)

if TYPE_CHECKING:
    from co_scientist.llm.tools.loop import ToolLoop

logger = logging.getLogger(__name__)


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


def _raise_budget_exhausted(loop: "ToolLoop") -> NoReturn:
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


def _spend_exhausted(spent: int, loop: "ToolLoop", iteration: int) -> bool:
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
    loop: "ToolLoop",
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
    loop: "ToolLoop",
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
    loop: "ToolLoop",
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
