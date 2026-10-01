"""Flattens possibly-malformed report fields into readable plain text.

Research-overview fields come from the model in json_object mode with no
server-side schema enforcement, so a field the schema declares a string
can arrive as a dict, a list, or a string that is itself serialized JSON.
Emitting any of those verbatim leaks raw JSON into the report.

A leaf module (no imports of its own beyond the standard library) so
every report-markdown module that needs this coercion -- currently
``report.markdown.overview`` and ``report.markdown.contact_groups`` --
can import it directly without creating a cross-import cycle between
those two.
"""

from __future__ import annotations

import json
from typing import Any


def _readable_text(value: Any) -> str:
    """Flatten a possibly-malformed field into readable plain text.

    Flattens a JSON-looking string, a dict, or a list into human-readable
    text, and passes a well-formed string through unchanged.
    """
    if isinstance(value, str):
        return _readable_from_string(value)
    if isinstance(value, list):
        return _join_readable(value, " ")
    if isinstance(value, dict):
        return _join_readable(list(value.values()), " - ")
    return "" if value is None else str(value)


def _readable_from_string(value: str) -> str:
    """Parse and flatten a JSON-looking string; else return it unchanged."""
    trimmed = value.strip()
    if not _is_json_like(trimmed):
        return value
    try:
        return _readable_text(json.loads(trimmed))
    except (ValueError, TypeError):
        return value


def _is_json_like(text: str) -> bool:
    """Whether the string looks like a serialized JSON object or array."""
    return (text.startswith("{") and text.endswith("}")) or (
        text.startswith("[") and text.endswith("]")
    )


def _join_readable(values: list[Any], separator: str) -> str:
    """Flatten each value to text, drop the empties, and join them."""
    return separator.join(
        text for text in (_readable_text(item) for item in values) if text
    )


def _readable_text_list(value: Any) -> list[str]:
    """Flatten a possibly-malformed list field into readable strings.

    Tolerates a JSON-encoded string, a lone dict, or a list whose items are
    dicts or serialized JSON, mirroring ``_readable_text``.
    """
    if isinstance(value, str):
        return _list_from_string(value)
    if isinstance(value, list):
        return [text for text in map(_readable_text, value) if text]
    if isinstance(value, dict):
        text = _readable_text(value)
        return [text] if text else []
    return []


def _list_from_string(value: str) -> list[str]:
    """Parse a JSON-array string into readable items; else a single line."""
    trimmed = value.strip()
    if not trimmed:
        return []
    if not _is_json_like(trimmed):
        return [trimmed]
    try:
        return _readable_text_list(json.loads(trimmed))
    except (ValueError, TypeError):
        return [trimmed]
