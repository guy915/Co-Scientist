"""The ``call_llm_with_tools`` agent loop and its helpers.

One loop iteration sends the running conversation to ``litellm.acompletion``,
executes any requested tool calls concurrently, and appends the assistant and
tool messages to the history; a successful loop result is cached only once
the final content is validated.

Also home to ``_prepare_llm_call``, the shared pre-call sequence consumed by
every public entry point (``call_llm``/``call_llm_json`` in ``llm``, and
``call_llm_with_tools`` here). It lives in this module rather than ``llm``
because ``llm`` imports this module, and the loop needing it from ``llm``
would be a cycle. Note for tests: caching is therefore stubbed by patching
``get_cache`` on *this* module, not on ``llm``.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

from co_scientist.cache import (
    LLMCache,
    LLMCacheRequest,
    NullCache,
    cache_enabled_override,
    get_cache,
)
from co_scientist.llm_credentials import (
    scoped_api_key,
)
from co_scientist.llm_request import (
    _clamp_temperature,
    _save_prompt_if_named,
)
from co_scientist.llm_telemetry import record_cache_result
from co_scientist.llm_tool_iteration import (
    _execute_tool_calls as _execute_tool_calls,
)
from co_scientist.llm_tool_iteration import (
    _run_iteration_logged,
)
from co_scientist.llm_tool_iteration import (
    _run_tool_call_iteration as _run_tool_call_iteration,
)
from co_scientist.llm_tool_policy import (
    DEFAULT_TOOL_LOOP_TOKEN_BUDGET,
    transcript_tokens,
)
from co_scientist.llm_tool_policy import (
    _contains_local_tool as _contains_local_tool,
)
from co_scientist.llm_tool_policy import (
    _guard_cache_for_local_tools as _guard_cache_for_local_tools,
)
from co_scientist.llm_tool_policy import (
    _handoff_iteration as _handoff_iteration,
)
from co_scientist.llm_tool_policy import (
    _handoff_message as _handoff_message,
)
from co_scientist.llm_tool_policy import (
    _handoff_spend as _handoff_spend,
)
from co_scientist.llm_tool_transcript import (
    _message_to_history_dict as _message_to_history_dict,
)
from co_scientist.llm_tool_transcript import (
    normalize_tool_transcript,
)
from co_scientist.llm_types import CompletionSpec, LLMCallOptions

# `_message_to_history_dict` is re-exported above under its original
# private name: the transcript-shaping helpers moved to
# `llm_tool_transcript` to keep this module under the size ceiling, and
# tests and `llm.py` patch the name here.
logger = logging.getLogger(__name__)


def _resolve_cache(use_cache: bool) -> "LLMCache | NullCache":
    """Resolves the cache to use for a call, honoring the disable overrides.

    NullCache when this call opted out, or the current task's generator was
    constructed with enable_cache=False (see cache.scoped_cache_override) --
    scoped to this task rather than the process-wide get_cache() singleton,
    so it never disables caching for any other concurrently-running
    generator.
    """
    cache_active = use_cache and cache_enabled_override() is not False
    return get_cache() if cache_active else NullCache()


def _log_cache_lookup(
    prompt: str, cached_response: dict[str, Any] | None
) -> None:
    """Logs a cache miss for a lookup; a hit is logged by the call site."""
    if cached_response is None:
        logger.debug(
            "cache miss for prompt: %s%s",
            prompt[:200],
            "..." if len(prompt) > 200 else "",
        )


async def _prepare_llm_call(
    request: LLMCacheRequest, opts: LLMCallOptions
) -> tuple[LLMCacheRequest, "LLMCache | NullCache", dict[str, Any] | None]:
    """Runs the shared pre-call sequence for the public LLM entry points.

    Saves the prompt debug artifact (when named), clamps the temperature
    before the cache key is built so requested temperatures that execute
    identically share one cache entry, and performs the cache lookup.

    Args:
        request: The request as the caller asked for it; its response-shape
            fields (``json_schema``/``force_json``/``tools``) are what make
            the cache key caller-specific.
        opts: Cache and debug-artifact options for this call.

    Returns:
        A (clamped_request, cache, cached_response) tuple where the request
        carries the clamped temperature the call must actually use, and
        cached_response is None on a cache miss.
    """
    await _save_prompt_if_named(
        request.prompt, opts.run_id, opts.prompt_name, opts.prompt_metadata
    )

    request = replace(
        request,
        temperature=_clamp_temperature(request.model_name, request.temperature),
    )

    cache = _resolve_cache(opts.use_cache)
    cached_response = cache.get(request)
    _log_cache_lookup(request.prompt, cached_response)
    # Only a genuinely active cache is worth a hit/miss telemetry record.
    # ``call_llm_json``'s retry loop deliberately calls back into
    # ``call_llm`` with ``use_cache=False`` for every attempt (see that
    # module's docstring): a NullCache lookup there always "misses" by
    # construction, and counting it would double-count one logical request
    # as two cache attempts for no informative reason.
    if isinstance(cache, LLMCache):
        record_cache_result(request.model_name, hit=cached_response is not None)
    return request, cache, cached_response


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
    (see ``llm_tool_policy``), because a turn count does not bound cost:
    each turn resends the whole transcript, so the last turns of a long
    loop cost several times the first. Whichever ceiling is reached first
    ends the loop.

    Near either bound a one-shot wrap-up turn is injected (see
    ``_handoff_iteration``) so the model can land a partial answer instead
    of being cut off mid-investigation. The hard caps remain as the
    backstop -- the handoff makes reaching them rarer, not impossible.

    Raises:
        RuntimeError: If either ceiling is exhausted without a response.
    """
    max_iterations = loop.max_iterations
    handoff_at = _handoff_iteration(max_iterations)
    handed_off = False
    spent = 0
    for iteration in range(max_iterations):
        logger.debug(
            "llm tool call iteration %s/%s", iteration + 1, max_iterations
        )
        spent += transcript_tokens(messages)
        if spent >= loop.max_prompt_tokens:
            logger.warning(
                "Token budget (%s) reached in tool call loop after %s"
                " iterations; %s tokens re-sent",
                loop.max_prompt_tokens,
                iteration,
                spent,
            )
            break
        if iteration == handoff_at or (
            not handed_off and spent >= _handoff_spend(loop.max_prompt_tokens)
        ):
            handed_off = True
            messages.append(_handoff_message(max_iterations - iteration))
        done, final_content = await _run_iteration_logged(
            messages, request, tool_executor, iteration
        )
        if done:  # only True alongside a non-None final_content
            assert final_content is not None
            logger.debug("llm finished after %s iterations", iteration + 1)
            return _finalize_tool_loop_success(
                cache, request, final_content, messages
            )

    logger.warning(
        "Tool call loop gave no final answer within %s iterations /"
        " %s prompt tokens",
        max_iterations,
        loop.max_prompt_tokens,
    )
    raise RuntimeError(
        "LLM tool call loop exhausted its budget"
        f" (max_iterations={max_iterations},"
        f" max_prompt_tokens={loop.max_prompt_tokens})"
    )


async def _prepare_tool_call(
    request: LLMCacheRequest, opts: LLMCallOptions
) -> tuple[
    LLMCacheRequest,
    "LLMCache | NullCache",
    tuple[str, list[dict[str, Any]]] | None,
]:
    """Runs the shared pre-call sequence for ``call_llm_with_tools``.

    Args:
        request: The tool-call request as the caller asked for it.
        opts: Cache and debug-artifact options for this call.

    Returns:
        A (clamped_request, cache, cached_result) tuple where cached_result
        is the already-cached (final_response, message_history) pair on a
        cache hit, else None.
    """
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
            reached first ends the loop.
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
