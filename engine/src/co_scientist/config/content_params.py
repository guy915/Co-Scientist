"""Substitute runtime context into tool content parameters.

A whole-value placeholder preserves its context value's type. Embedded
placeholders and list items stringify; nested containers stay untouched.
"""

import re
from typing import Any

_PLACEHOLDER_PATTERN = re.compile(r"\{(\w+)\}")


def _substitute_placeholders(
    value: str, context: dict[str, Any], *, preserve_type: bool = True
) -> Any:
    """Resolve known placeholders, preserving whole values when requested."""
    exact = _PLACEHOLDER_PATTERN.fullmatch(value)
    if preserve_type and exact and exact[1] in context:
        return context[exact[1]]
    # Keep the original occurrence order: later replacements may also apply
    # to placeholder text introduced by an earlier context value.
    for name in _PLACEHOLDER_PATTERN.findall(value):
        if name in context:
            value = value.replace(f"{{{name}}}", str(context[name]))
    return value


def resolve_content_params(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Resolve ``{name}`` references in string parameters and list items.

    Args:
        params: Tool content parameters containing optional placeholders.
        context: Runtime values keyed by placeholder name.

    Returns:
        Resolved parameters. Unknown placeholders stay literal; a parameter
        consisting of exactly one known placeholder retains its value type.
    """
    if not params:
        return {}
    resolved: dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, str):
            resolved[key] = _substitute_placeholders(value, context)
        elif isinstance(value, list):
            resolved[key] = [
                _substitute_placeholders(item, context, preserve_type=False)
                if isinstance(item, str)
                else item
                for item in value
            ]
        else:
            resolved[key] = value
    return resolved
