"""Decoding of raw MCP tool results.

Split from ``response_parser.py``, whose bulk is the field-mapping
``ResponseParser``; this is the unrelated transport-level decode step.
``response_parser`` re-exports ``parse_mcp_result`` so the import path every
caller already uses keeps resolving.
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
