"""Truncation of over-long strings for the json_object downgrade.

Split out of ``llm.structured.validate`` at the file-size cap, alongside its
``llm.structured.lists``/``llm.structured.repair`` siblings.

Provider-capability shim for json_object-only models (see
``co_scientist.llm.request.completion._supports_json_schema_response_format``),
alongside ``llm.structured.validate._prune_unknown_properties``,
``llm.structured.validate._backfill_required_fields`` and
``llm.structured.validate._truncate_oversized_arrays``: without server-side
enforcement ``maxLength`` is advisory only, so an otherwise good answer a few
characters over the limit fails the whole response. Production run b82f9162
failed generation and validation calls this way on a hypothesis ``title`` field,
and on a free gateway model with a 100-requests/day cap each such retry is 1% of
the day's budget.

Only ``maxLength`` is enforced here. ``minLength``, ``pattern`` and enum
membership are left untouched -- those describe the *content* of the
answer, not an over-generous provider, and no amount of truncation fixes a
wrong answer.

Reshapes the OUTPUT only, exactly like ``_truncate_oversized_arrays`` -- see
the "Trim the schema, never the input" gotcha (root ``AGENTS.md``).
"""

import logging
from typing import Any, Final

from co_scientist.llm.structured.validate import _is_backfillable

logger = logging.getLogger(__name__)

# A cut within this fraction of maxLength (measured back from the limit) is
# treated as "near enough" to trim at the preceding word boundary instead of
# slicing mid-word; a boundary found earlier than that is too much of the
# string to give up and a hard cut is used instead.
_STRING_TRUNCATION_BOUNDARY_FRACTION: Final = 0.2


def _truncate_oversized_strings(obj: Any, schema: Any, _path: str = "") -> None:
    """Recursively truncates strings that exceed their schema's ``maxLength``.

    Args:
        obj: Parsed JSON value to truncate in place (non-dicts are ignored).
        schema: JSON schema node describing ``obj``.
        _path: Dotted/bracketed field path built up during recursion, for
            the truncation warning; callers should not pass this.
    """
    if not _is_backfillable(obj, schema):
        return
    props = schema.get("properties", {})
    for key, value in obj.items():
        if key in props:
            field_path = f"{_path}.{key}" if _path else key
            obj[key] = _truncate_string_child(value, props[key], field_path)


def _truncate_string_child(
    value: Any, property_schema: Any, field_path: str
) -> Any:
    """Truncates one property's value if it is an over-long string.

    Mirrors ``llm.structured.validate._truncate_child``, but unlike an array or
    a dict a string cannot be trimmed in place -- it is immutable -- so this
    returns the (possibly new) value for the caller to write back, rather than
    mutating ``value`` itself.

    Args:
        value: The property's value, of any shape.
        property_schema: The schema node describing that property.
        field_path: This value's path, for the truncation warning.

    Returns:
        The value, truncated if it was an over-long string; unchanged
        otherwise (recursing into an array's items or a nested object in
        place first).
    """
    if not isinstance(property_schema, dict):
        return value
    if isinstance(value, str):
        return _truncate_string_value(
            value, property_schema.get("maxLength"), field_path
        )
    if isinstance(value, list):
        return _truncate_string_list(value, property_schema, field_path)
    if isinstance(value, dict):
        _truncate_oversized_strings(value, property_schema, field_path)
        return value
    return value


def _truncate_string_list(
    value: list[Any], property_schema: dict[str, Any], field_path: str
) -> list[Any]:
    """Truncates each over-long string in an array, in place.

    Split out of ``_truncate_string_child`` to keep its own branching
    within the complexity limit; walks each item with the array's own
    item schema, covering a plain string array and an array of objects
    alike.

    Args:
        value: The array to walk (mutated in place).
        property_schema: The schema node describing the array.
        field_path: This array's path, for nested truncation warnings.

    Returns:
        ``value``, mutated in place.
    """
    item_schema = property_schema.get("items")
    for index, item in enumerate(value):
        value[index] = _truncate_string_child(
            item, item_schema, f"{field_path}[{index}]"
        )
    return value


def _truncate_string_value(value: str, max_length: Any, field_path: str) -> str:
    """Truncates one string to ``max_length``, preferring a word boundary.

    Args:
        value: The candidate string.
        max_length: The schema's ``maxLength`` for this field, or ``None``/
            non-int when the field carries no such cap.
        field_path: This value's path, named in the truncation warning.

    Returns:
        ``value`` unchanged when it fits or carries no cap; otherwise cut
        to ``max_length``, at the last whitespace within the trailing
        ``_STRING_TRUNCATION_BOUNDARY_FRACTION`` of the limit when one
        exists there, else a hard cut at ``max_length``.
    """
    if not isinstance(max_length, int) or len(value) <= max_length:
        return value
    candidate = value[:max_length]
    boundary_window = max_length - max(
        1, round(max_length * _STRING_TRUNCATION_BOUNDARY_FRACTION)
    )
    boundary = candidate.rfind(" ", max(0, boundary_window))
    truncated = candidate[:boundary].rstrip() if boundary != -1 else candidate
    logger.warning(
        "Truncated over-long string at '%s': %d chars -> %d chars"
        " (schema maxLength=%d)",
        field_path,
        len(value),
        len(truncated),
        max_length,
    )
    return truncated
