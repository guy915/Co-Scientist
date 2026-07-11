"""Output formatting for the ``cosci`` CLI.

Two rendering modes back every read command: ``--json`` emits the raw API
payload pretty-printed, and the default is line-oriented text meant to be read
by a person or grepped by an agent. Formatting lives here so the command
handlers stay thin.
"""

from __future__ import annotations

import json
from typing import Any


def emit_json(obj: Any) -> None:
    """Print ``obj`` as indented JSON on stdout."""
    print(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True))


def oneline(text: Any, limit: int = 100) -> str:
    """Collapse whitespace in ``text`` and truncate to ``limit`` characters."""
    collapsed = " ".join(str(text).split())
    if len(collapsed) > limit:
        return collapsed[: limit - 1] + "…"
    return collapsed


def _get(record: dict[str, Any], *keys: str) -> str:
    """Return the first present, non-empty value among ``keys`` as text."""
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def format_run_line(run: dict[str, Any]) -> str:
    """Render one run as a tab-separated ``id  status  provider  goal`` line."""
    return "\t".join(
        (
            _get(run, "id"),
            _get(run, "status"),
            _get(run, "provider"),
            oneline(_get(run, "research_goal")),
        )
    )


def format_kv(pairs: list[tuple[str, Any]]) -> str:
    """Render ``(key, value)`` pairs as aligned ``key: value`` lines."""
    if not pairs:
        return ""
    width = max(len(key) for key, _ in pairs)
    lines = [f"{key.ljust(width)} : {value}" for key, value in pairs]
    return "\n".join(lines)


def format_action_line(result: dict[str, Any]) -> str:
    """Render a lifecycle action result as ``id  status``."""
    return "\t".join((_get(result, "id"), _get(result, "status")))


def format_record_line(
    record: dict[str, Any], field_groups: tuple[tuple[str, ...], ...]
) -> str:
    """Render one list record as a tab-separated line of chosen fields.

    Each group is a list of candidate keys; the first present, non-empty value
    in the group is used for that column. Trailing empty columns are dropped so
    a record missing later fields still renders cleanly. The last column is
    treated as free text and collapsed onto one line.

    Args:
        record: The list item to render.
        field_groups: Ordered candidate-key groups, one per output column.

    Returns:
        A tab-separated line of the record's selected fields.
    """
    columns = [_get(record, *group) for group in field_groups]
    while len(columns) > 1 and not columns[-1]:
        columns.pop()
    if columns:
        columns[-1] = oneline(columns[-1])
    return "\t".join(columns)


def sse_data(line: str) -> dict[str, Any] | None:
    """Parse one SSE ``data:`` line into its JSON object, else ``None``.

    Non-data lines (blank separators, comments, ``event:``/``id:`` fields) and
    malformed JSON return ``None`` so the caller can simply skip them.
    """
    if not line.startswith("data:"):
        return None
    body = line[len("data:") :].strip()
    if not body:
        return None
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def format_event_line(event: dict[str, Any]) -> str:
    """Render a run event frame as ``seq  type  compact-payload``."""
    seq = event.get("seq", "")
    etype = event.get("type", "")
    payload = event.get("payload")
    rendered = (
        json.dumps(payload, ensure_ascii=False)
        if payload not in (None, {})
        else ""
    )
    return f"{seq}\t{etype}\t{oneline(rendered, limit=200)}".rstrip()
