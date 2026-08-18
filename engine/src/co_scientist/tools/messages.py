"""The tool-role message shape both tool providers answer with.

One module rather than a helper per provider, because the shape is a
contract with the provider API -- a tool result must carry the
``tool_call_id`` it answers, and a turn that requested a tool call and
never got a matching result is rejected by the provider rather than
degraded. A local tool that raised where an MCP tool would have returned
an error message would therefore break the conversation, not just the
call, so both paths answer in the same shape.
"""

import json
from typing import Any


def tool_result_message(
    tool_name: str, tool_call_id: str, payload: Any
) -> dict[str, Any]:
    """Builds a successful tool-role message.

    Args:
        tool_name: The name the model called.
        tool_call_id: The id of the call being answered.
        payload: JSON-serializable result content.

    Returns:
        A tool-role message dict.
    """
    return {
        "role": "tool",
        "name": tool_name,
        "tool_call_id": tool_call_id,
        "content": json.dumps(payload, default=str),
    }


def tool_error_message(
    tool_name: str, tool_call_id: str, error: str
) -> dict[str, Any]:
    """Builds a tool-role message reporting a failure to the model.

    Args:
        tool_name: The name the model called.
        tool_call_id: The id of the call being answered.
        error: What went wrong, phrased for the model to act on.

    Returns:
        A tool-role message dict carrying an ``error`` key.
    """
    return {
        "role": "tool",
        "name": tool_name,
        "tool_call_id": tool_call_id,
        "content": json.dumps({"error": error}),
    }
