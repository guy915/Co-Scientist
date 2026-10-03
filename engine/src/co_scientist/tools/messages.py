"""Tool-role responses and decoding of raw MCP result payloads.

Successful and failed tool messages always carry the tool_call_id they
answer so the provider can match each requested call to its result.
"""

import json
from typing import Any

# Enough of an undecodable payload to recognize what returned it (an HTML
# error page, a throttling notice, a stack trace) without pasting a whole
# response body into the log.
_PAYLOAD_EXCERPT_CHARS = 200


def parse_mcp_result(result: Any) -> Any:
    """Decodes a raw MCP tool result that may arrive as a JSON string.

    MCP tools return either already-decoded Python data or a JSON-encoded
    string depending on transport. This is the canonical decode step; callers
    keep their own handling of malformed JSON.

    A decode failure quotes the start of the offending payload. The bare
    message ("Expecting value: line 1 column 1 (char 0)") says only that the
    body was not JSON, which is the one thing already known -- it cannot
    distinguish an upstream HTML status page from a throttling notice from
    an empty body, and those call for different fixes.

    Args:
        result: Raw MCP tool result.

    Returns:
        The decoded object for JSON strings, otherwise the value unchanged.

    Raises:
        json.JSONDecodeError: If result is a string that is not valid JSON.
    """
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError as exc:
            raise json.JSONDecodeError(
                f"{exc.msg} (payload: {_payload_excerpt(result)})",
                exc.doc,
                exc.pos,
            ) from exc
    return result


def _payload_excerpt(payload: str) -> str:
    """Quote the head of an undecodable payload for a diagnostic message."""
    head = " ".join(payload.split())[:_PAYLOAD_EXCERPT_CHARS]
    if not head:
        return "empty"
    suffix = "..." if len(head) < len(payload.strip()) else ""
    return f"{head!r}{suffix}"


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
    return tool_result_message(tool_name, tool_call_id, {"error": error})
