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

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from co_scientist.cache import (
    LLMCache,
    NullCache,
    cache_enabled_override,
    get_cache,
)
from co_scientist.constants import EXTENDED_MAX_TOKENS, HIGH_TEMPERATURE
from co_scientist.llm_request import (
    _acompletion_within_timeout,
    _clamp_temperature,
    _save_prompt_if_named,
    deepseek_thinking_extra_body,
    llm_timeout_seconds,
    reasoning_effort_args,
)

logger = logging.getLogger(__name__)


async def _prepare_llm_call(
    prompt: str,
    model_name: str,
    temperature: float,
    max_tokens: int,
    use_cache: bool,
    run_id: str | None,
    prompt_name: str | None,
    prompt_metadata: dict[str, Any] | None,
    **cache_key_kwargs: Any,
) -> tuple[float, "LLMCache | NullCache", dict[str, Any] | None]:
    """Runs the shared pre-call sequence for the public LLM entry points.

    Saves the prompt debug artifact (when named), clamps the temperature
    before the cache key is built so requested temperatures that execute
    identically share one cache entry, and performs the cache lookup. A
    cache miss is logged here; the hit log line is left to the call site.

    Args:
        prompt: The prompt about to be sent to the LLM.
        model_name: Model name in litellm format.
        temperature: Requested sampling temperature (clamped here).
        max_tokens: Maximum tokens in response.
        use_cache: When False, a NullCache is used so the call is fresh.
        run_id: Optional run identifier for the saved prompt's directory.
        prompt_name: Optional debug-artifact name for saving the prompt.
        prompt_metadata: Optional metadata appended to the saved prompt file.
        **cache_key_kwargs: Extra cache-key fields specific to the caller
            (e.g. ``json_schema=``, ``force_json=``, ``tools=``).

    Returns:
        A (clamped_temperature, cache, cached_response) tuple where
        cached_response is None on a cache miss.
    """
    await _save_prompt_if_named(prompt, run_id, prompt_name, prompt_metadata)

    temperature = _clamp_temperature(model_name, temperature)

    # NullCache when this call opted out, or the current task's generator
    # was constructed with enable_cache=False (see
    # cache.scoped_cache_override) -- scoped to this task rather than the
    # process-wide get_cache() singleton, so it never disables caching for
    # any other concurrently-running generator.
    cache_active = use_cache and cache_enabled_override() is not False
    cache: LLMCache | NullCache = get_cache() if cache_active else NullCache()
    cached_response = cache.get(
        prompt, model_name, temperature, max_tokens, **cache_key_kwargs
    )
    if cached_response is None:
        logger.debug(
            "cache miss for prompt: %s%s",
            prompt[:200],
            "..." if len(prompt) > 200 else "",
        )
    return temperature, cache, cached_response


def _message_to_history_dict(message: Any) -> dict[str, Any]:
    """Converts a litellm assistant message into a plain history dict.

    litellm's message object is a Pydantic model, not a plain dict; this
    converts it so it can be cached and replayed as message history.

    Args:
        message: The assistant message from a litellm completion response.

    Returns:
        A plain dict representation, including tool_calls when present.
    """
    message_dict: dict[str, Any] = {
        "role": message.role,
        "content": message.content,
    }

    # DeepSeek thinking returns the chain of thought as reasoning_content, and
    # the API requires it to be echoed back on any assistant message that
    # carries tool_calls -- omitting it 400s the next iteration. Preserve it so
    # the replayed history stays valid; harmless for non-thinking models, which
    # never populate the field.
    reasoning = getattr(message, "reasoning_content", None)
    if reasoning:
        message_dict["reasoning_content"] = reasoning

    # Add tool calls if present
    if hasattr(message, "tool_calls") and message.tool_calls:
        message_dict["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in message.tool_calls
        ]

    return message_dict


async def _execute_tool_calls(
    tool_calls: list[Any],
    tool_executor: Callable[[Any], Awaitable[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Executes all requested tool calls concurrently.

    Args:
        tool_calls: The tool_calls list from the assistant message.
        tool_executor: Async callable that executes a single tool call and
            returns its tool response message.

    Returns:
        The tool response messages, in the same order as ``tool_calls``.
    """
    return await asyncio.gather(*[tool_executor(tc) for tc in tool_calls])


def _finalize_tool_call_response(message: Any, model_name: str) -> str:
    """Validates and returns the final (non-tool-call) assistant response.

    Args:
        message: The assistant message from the iteration where the LLM
            stopped requesting tool calls.
        model_name: Model name in litellm format, included in the error
            message when the response is empty.

    Returns:
        The final response text.

    Raises:
        ValueError: If the message has no non-whitespace content.
    """
    final_content = message.content if message.content else ""
    if not final_content.strip():
        logger.error("LLM returned empty final response in tool call loop")
        raise ValueError(
            f"LLM returned empty final response. Model: {model_name}"
        )
    return final_content


async def _run_tool_call_iteration(
    messages: list[dict[str, Any]],
    model_name: str,
    tools: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
    tool_executor: Callable[[Any], Awaitable[dict[str, Any]]],
) -> tuple[bool, str | None]:
    """Runs one LLM-with-tools iteration; mutates `messages` in place.

    Args:
        messages: The running conversation history; appended to (and
            possibly extended with tool response messages) in place.
        model_name: Model name in litellm format.
        tools: List of tools in OpenAI format.
        max_tokens: Maximum tokens for this call.
        temperature: Sampling temperature.
        tool_executor: Async callable that executes tool calls and returns
            tool response messages.

    Returns:
        Tuple of (done, final_content). When done is True, final_content
        holds the finalized response text (already validated via
        _finalize_tool_call_response); when False, tool calls were
        dispatched and appended to `messages` and the caller should iterate
        again.
    """
    completion_args: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "tools": tools,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "drop_params": True,
        "extra_body": deepseek_thinking_extra_body(model_name),
        **reasoning_effort_args(model_name),
    }
    # Same two-layer ceiling as call_llm: ask the provider client to give
    # up on its own, and hard-cancel the await when a hang never reaches
    # the transport at all.
    timeout = llm_timeout_seconds()
    if timeout is not None:
        completion_args["timeout"] = timeout
    response = await _acompletion_within_timeout(completion_args, model_name)

    message = response.choices[0].message
    message_dict = _message_to_history_dict(message)
    messages.append(message_dict)

    # Check if LLM wants to call tools
    if hasattr(message, "tool_calls") and message.tool_calls:
        logger.debug("llm requested %s tool calls", len(message.tool_calls))

        # Execute all tool calls in parallel and add the results to
        # message history
        messages.extend(
            await _execute_tool_calls(message.tool_calls, tool_executor)
        )

        # Continue loop - LLM will see tool results and respond
        return False, None

    # No tool calls - this is the final response
    final_content = _finalize_tool_call_response(message, model_name)
    return True, final_content


def _cache_tool_call_result(
    cache: LLMCache | NullCache,
    prompt: str,
    model_name: str,
    temperature: float,
    max_tokens: int,
    final_content: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> None:
    """Caches a successful tool-call loop result.

    Only called once the final content is validated, so a failed loop is
    retried fresh next time rather than replayed from a broken cache entry.

    Args:
        cache: The cache to store the result in.
        prompt: The initial user prompt (part of the cache key).
        model_name: Model name in litellm format.
        temperature: Sampling temperature used for the loop.
        max_tokens: Maximum tokens per LLM call.
        final_content: The validated final response text.
        messages: The complete message history for the loop.
        tools: List of tools in OpenAI format (part of the cache key).
    """
    cache.set(
        prompt,
        model_name,
        temperature,
        max_tokens,
        {"final_response": final_content, "message_history": messages},
        tools=tools,
    )


async def call_llm_with_tools(
    prompt: str,
    model_name: str,
    tools: list[dict[str, Any]],
    tool_executor: Callable[[Any], Awaitable[dict[str, Any]]],
    max_tokens: int = EXTENDED_MAX_TOKENS,
    temperature: float = HIGH_TEMPERATURE,
    max_iterations: int = 10,
    use_cache: bool = True,
    run_id: str | None = None,
    prompt_name: str | None = None,
    prompt_metadata: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Call an LLM with tool access and handle tool execution loop.

    This function implements an agent loop where the LLM can call tools,
    see the results, and continue iterating until it produces a final response.

    Args:
        prompt: The initial user prompt
        model_name: Model name in litellm format
        tools: List of tools in OpenAI format
        tool_executor: Async callable that executes tool calls and returns
            tool response messages
        max_tokens: Maximum tokens per LLM call
        temperature: Sampling temperature
        max_iterations: Maximum number of LLM calls (prevents infinite loops)
        use_cache: When False, bypass the LLM cache so the call is always fresh
            (used for stochastic, diversity-critical generation).
        run_id: Optional run identifier for the saved prompt's directory;
            ``None`` falls back to "unknown".
        prompt_name: Optional debug-artifact name. When provided, the prompt
            is saved to disk before the call — always, regardless of
            ``run_id`` (globally gated by ``COSCIENTIST_SAVE_PROMPTS``).
        prompt_metadata: Optional metadata appended to the saved prompt file.

    Returns:
        Tuple of (final_response_text, complete_message_history)

    Raises:
        Exception: If the LLM call fails or max iterations reached
    """
    temperature, cache, cached_response = await _prepare_llm_call(
        prompt,
        model_name,
        temperature,
        max_tokens,
        use_cache,
        run_id,
        prompt_name,
        prompt_metadata,
        tools=tools,
    )
    if cached_response is not None:
        logger.debug("using cached llm tool call response")
        return cached_response["final_response"], cached_response[
            "message_history"
        ]

    # Running conversation history: grows with each assistant/tool turn and
    # is resent in full to acompletion on every iteration below.
    messages = [{"role": "user", "content": prompt}]

    for iteration in range(max_iterations):
        logger.debug(
            "llm tool call iteration %s/%s", iteration + 1, max_iterations
        )

        try:
            done, final_content = await _run_tool_call_iteration(
                messages,
                model_name,
                tools,
                max_tokens,
                temperature,
                tool_executor,
            )
        except Exception as e:
            logger.error(
                "Error in LLM tool call loop (iteration %s): %s",
                iteration + 1,
                e,
            )
            raise

        if done:
            # _run_tool_call_iteration only returns done=True alongside a
            # non-None final_content (see _finalize_tool_call_response).
            assert final_content is not None
            logger.debug("llm finished after %s iterations", iteration + 1)
            _cache_tool_call_result(
                cache,
                prompt,
                model_name,
                temperature,
                max_tokens,
                final_content,
                messages,
                tools,
            )
            return final_content, messages

    # Max iterations reached
    logger.warning(
        "Max iterations (%s) reached in tool call loop", max_iterations
    )
    raise RuntimeError(
        f"LLM tool call loop exceeded max iterations ({max_iterations})"
    )
