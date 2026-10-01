"""The ``call_llm_with_tools`` agent loop and its helpers.

One loop iteration sends the running conversation to ``litellm.acompletion``,
executes any requested tool calls concurrently, and appends the assistant and
tool messages to the history; a successful loop result is cached only once
the final content is validated. The bounded loop driver itself -- per-turn
budget bookkeeping, the degraded-but-answered exit, and the cache-write
glue its success path calls -- is split out into ``llm.tools.loop_run`` to
keep this module within the size cap.

The shared pre-call sequence (``_prepare_llm_call``) is ``llm.precall``'s, so
caching is stubbed by patching ``get_cache`` there.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from co_scientist.cache import (
    LLMCache,
    LLMCacheRequest,
    NullCache,
)
from co_scientist.llm.admission.credentials import scoped_api_key
from co_scientist.llm.precall import _prepare_llm_call
from co_scientist.llm.tools.loop_run import _run_tool_call_loop
from co_scientist.llm.tools.policy import (
    DEFAULT_TOOL_LOOP_TOKEN_BUDGET,
    _guard_cache_for_local_tools,
)
from co_scientist.llm.values import CompletionSpec, LLMCallOptions

logger = logging.getLogger(__name__)


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
