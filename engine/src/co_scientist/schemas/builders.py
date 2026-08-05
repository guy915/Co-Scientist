"""Shared node constructors for the JSON schemas in this package.

Every object node across these schemas is closed
(``additionalProperties: False``), and all but six of them require exactly
their full declared property list -- which each node used to restate by
hand underneath its ``properties`` block. ``obj`` derives ``required``
from ``properties`` instead, so a property added to a node cannot leave a
stale ``required`` behind, and the handful of genuinely optional keys are
named at the one place that knows they are optional.
"""

from typing import Any


def obj(
    properties: dict[str, Any],
    *,
    optional: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build a closed object node requiring every property but ``optional``.

    Args:
        properties: The node's declared properties, in the order the model
            should see them.
        optional: Property names the model may omit. Everything else is
            required.

    Returns:
        A JSON Schema object node.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": [name for name in properties if name not in optional],
    }


def str_array(description: str | None = None) -> dict[str, Any]:
    """Build an array-of-strings node, with an optional description.

    Args:
        description: Prose shown to the model, omitted when None.

    Returns:
        A JSON Schema array node whose items are strings.
    """
    node: dict[str, Any] = {"type": "array", "items": {"type": "string"}}
    if description is not None:
        node["description"] = description
    return node
