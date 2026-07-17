"""Placeholder substitution for tool content parameters.

``resolve_content_params()`` replaces ``{placeholder}`` references in a
tool's content_params values (strings, or lists of strings) with runtime
context values such as the research goal. The private helpers below
implement the per-value and per-match substitution rules, including the
type-preservation semantics for values that consist of exactly one
placeholder.
"""

import re
from typing import Any

# Matches a bare "{placeholder}" reference; compiled once here rather than
# on every resolve_content_params() call (invoked per paper during content
# fetching).
_PLACEHOLDER_PATTERN = re.compile(r"\{(\w+)\}")


def _apply_placeholder_match(
    resolved_value: Any,
    match: str,
    value: str,
    context: dict[str, Any],
    *,
    preserve_type: bool,
) -> Any:
    """Fold one matched placeholder's substitution into resolved_value.

    Args:
        resolved_value: Substitution result accumulated from earlier
            matches (or the original value, for the first match).
        match: Placeholder name found in value.
        value: The original (pre-substitution) string; used to test
            whether it consists of exactly this one placeholder.
        context: Runtime values keyed by placeholder name.
        preserve_type: See _substitute_placeholders.

    Returns:
        resolved_value unchanged if match is absent from context;
        otherwise resolved_value with this placeholder substituted.
    """
    if match not in context:
        return resolved_value
    context_val = context[match]
    # A value that is *only* "{placeholder}" preserves the context value's
    # original type (e.g. a list stays a list); a placeholder embedded in a
    # larger string is necessarily stringified via str.replace.
    if preserve_type and value == f"{{{match}}}":
        return context_val
    return resolved_value.replace(
        f"{{{match}}}",
        str(context_val) if not isinstance(context_val, str) else context_val,
    )


def _substitute_placeholders(
    value: str,
    context: dict[str, Any],
    placeholder_pattern: "re.Pattern[str]",
    *,
    preserve_type: bool,
) -> Any:
    """Replace every known {placeholder} in value with its context value.

    Args:
        value: String value, possibly containing one or more {name}
            placeholders.
        context: Runtime values keyed by placeholder name.
        placeholder_pattern: Compiled pattern matching a bare placeholder.
        preserve_type: When True and value is *exactly* one placeholder
            (e.g. "{research_goal}"), returns the context value verbatim,
            preserving its original type (e.g. a list stays a list).
            Otherwise substitution always goes through str.replace, so the
            result is a string.

    Returns:
        value with its known placeholders substituted; unknown
        placeholders (absent from context) are left untouched.
    """
    matches = placeholder_pattern.findall(value)
    if not matches:
        return value

    resolved_value: Any = value
    for match in matches:
        resolved_value = _apply_placeholder_match(
            resolved_value, match, value, context, preserve_type=preserve_type
        )

    return resolved_value


def _resolve_content_param_value(
    value: Any, context: dict[str, Any], placeholder_pattern: "re.Pattern[str]"
) -> Any:
    """Resolve one content_params value: a string, a list, or passthrough.

    Args:
        value: A single content_params value (string, list, or other).
        context: Runtime context containing values to substitute.
        placeholder_pattern: Compiled pattern matching a bare placeholder.

    Returns:
        The value with placeholders substituted; unchanged for non-string,
        non-list values (numbers, bools, dicts -- dicts are not recursed
        into).
    """
    if isinstance(value, str):
        return _substitute_placeholders(
            value, context, placeholder_pattern, preserve_type=True
        )
    if not isinstance(value, list):
        return value
    # Resolve each item in the list. Note: unlike the string case above,
    # list items never preserve_type, since a list of placeholders is
    # inherently a list of strings.
    return [
        _substitute_placeholders(
            item, context, placeholder_pattern, preserve_type=False
        )
        if isinstance(item, str)
        else item
        for item in value
    ]


def resolve_content_params(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Resolve content params by substituting {placeholders} with context.

    Supports:
        - {research_goal} - the current research goal
        - {focus_areas} - list of focus areas (from hypothesis categories,
          etc.)
        - Any other context key

    Args:
        params: Content params dict with potential {placeholder} values
        context: Runtime context containing values to substitute

    Returns:
        Resolved params dict with placeholders replaced
    """
    if not params:
        return {}

    resolved: dict[str, Any] = {}
    for key, value in params.items():
        resolved[key] = _resolve_content_param_value(
            value, context, _PLACEHOLDER_PATTERN
        )

    return resolved
