"""Helpers for the ``call_llm_with_tools`` agent loop.

One loop iteration sends the running conversation to ``litellm.acompletion``,
executes any requested tool calls concurrently, and appends the assistant and
tool messages to the history; a successful loop result is cached only once
the final content is validated.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import litellm

from co_scientist.cache import LLMCache, NullCache
from co_scientist.llm_request import deepseek_thinking_extra_body

logger = logging.getLogger(__name__)


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
    response = await litellm.acompletion(
        model=model_name,
        messages=messages,
        tools=tools,
        max_tokens=max_tokens,
        temperature=temperature,
        drop_params=True,
        extra_body=deepseek_thinking_extra_body(model_name),
    )

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
