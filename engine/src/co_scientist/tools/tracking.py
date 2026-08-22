"""Counting a tool loop's calls by tool name.

Shared by the two providers a loop can be handed -- the MCP one and the
workspace one -- because the count is a property of the loop, not of who
services the call. A drafting pass that reaches both surfaces at once
would otherwise report only half its tool use.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)


def tracked_executor(
    provider: Any, label: str
) -> tuple[Callable[[Any], Awaitable[dict[str, Any]]], dict[str, int]]:
    """Wraps a provider's ``execute_tool_call`` with per-name counting.

    Args:
        provider: Anything with an ``execute_tool_call`` coroutine.
        label: Log prefix identifying the calling phase, e.g. "Draft".

    Returns:
        An (executor, counts) pair. The executor delegates to the
        provider; counts maps tool name to call count and is updated in
        place as the executor runs.
    """
    counts: dict[str, int] = {}

    async def executor(tool_call: Any) -> dict[str, Any]:
        name = tool_call.function.name
        counts[name] = counts.get(name, 0) + 1
        logger.info("%s: %s call #%s", label, name, counts[name])
        result: dict[str, Any] = await provider.execute_tool_call(tool_call)
        return result

    return executor, counts
