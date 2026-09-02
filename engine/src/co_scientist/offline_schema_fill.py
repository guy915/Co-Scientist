"""Generic JSON-schema-to-fake-value traversal, shared by two fillers.

Split out of ``offline_llm``, which had grown past the module-size budget:
this half of it knows nothing about any particular schema or prompt, only
how to walk an arbitrary JSON Schema fragment and produce a minimal value
that satisfies it. ``offline_llm.py`` (the production router) and
``tests/_llm_fake.py`` (the test fake) both import ``_fill_schema`` and
``_FillHints`` from here rather than duplicating the traversal -- see
``offline_llm``'s own module docstring for why that sharing matters
(determinism, uniqueness) and ``_llm_fake.py``'s for why the fake keeps its
own leaf-value strategy instead of this module's.

Every "required" property (or, absent a "required" list, every declared
property) is filled recursively, with enums resolved to their first
allowed value and an array filled to one item unless a caller's ``hints``
says otherwise for that property name. An optional property is left
absent unless a caller's ``hints.optional_fields`` names it -- the same
scoped-opt-in shape as the array-length and scalar-value hints.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Placeholder values for scalar schema types this filler special-cases.
_SCALAR_DEFAULTS: dict[str, Any] = {
    "integer": 4,
    "number": 4.0,
    "boolean": True,
}


@dataclass(frozen=True)
class _FillHints:
    """Per-call hints threaded through the schema-filling traversal.

    Bundled into one object, rather than two parameters, because
    ``_fill_array`` already sits at the five-parameter ceiling (schema,
    count, leaf_fn, hints, field) -- see the repo's PLR0913 convention.

    Attributes:
        array_lengths: Property-name -> item-count map; an array property
            whose name is a key here is filled to that length instead of
            the default one item. See ``offline_llm._ARRAY_LENGTH_HINTS``.
        scalar_values: Property-name -> override value for a scalar leaf,
            read ahead of ``_SCALAR_DEFAULTS``. See
            ``offline_llm._SCALAR_VALUE_HINTS``.
        optional_fields: Property names to fill even though their object
            node's schema marks them optional. Empty by default -- an
            optional property is normally left absent, the same way a real
            provider genuinely omits one. See
            ``offline_llm._OPTIONAL_FIELD_HINTS``, which is the only
            producer of a non-empty set here: it is scoped per schema name,
            not a blanket "fill every optional" switch.
    """

    array_lengths: dict[str, int] = field(default_factory=dict)
    scalar_values: dict[str, Any] = field(default_factory=dict)
    optional_fields: frozenset[str] = frozenset()


def _scalar_leaf_value(schema_type: str, field: str, hints: _FillHints) -> Any:
    """Resolves one scalar leaf, honoring a per-field value override.

    Args:
        schema_type: The scalar's JSON Schema "type" (a key in
            ``_SCALAR_DEFAULTS``).
        field: The property name this scalar fills.
        hints: The call's array-length and scalar-value hints.

    Returns:
        ``hints.scalar_values[field]`` when set, else the generic
        ``_SCALAR_DEFAULTS[schema_type]`` placeholder.
    """
    if field in hints.scalar_values:
        return hints.scalar_values[field]
    return _SCALAR_DEFAULTS[schema_type]


def _fill_schema(
    schema: dict[str, Any],
    leaf_fn: Callable[[str], Any],
    hints: _FillHints | None = None,
    field: str = "",
) -> Any:
    """Builds a minimal value satisfying one JSON-schema node.

    Args:
        schema: A JSON Schema fragment (object, array, or scalar).
        leaf_fn: Callable taking the property name being filled and
            returning the next string-leaf value; called once per string
            leaf encountered. Callers choose the uniqueness strategy (a
            seeded RNG for the runtime router, a process-global counter for
            the test fake).
        hints: Optional array-length and scalar-value hints (see
            ``_FillHints``); defaults to no hints.
        field: Name of the property this node is filling, passed to
            ``leaf_fn`` so a leaf can read as the field it lands in.
            Empty at the schema root.

    Returns:
        A value satisfying ``schema``: object properties filled
        recursively, array items filled per ``hints.array_lengths``
        (default one), an enum's first allowed value, or a scalar
        placeholder (per ``hints.scalar_values``, else the generic
        default).
    """
    hints = hints or _FillHints()

    if "enum" in schema:
        return schema["enum"][0]

    schema_type = schema.get("type", "object")

    if schema_type == "object":
        return _fill_object(schema, leaf_fn, hints)

    if schema_type == "array":
        return _fill_array(schema, 1, leaf_fn, hints, field)

    if schema_type in _SCALAR_DEFAULTS:
        return _scalar_leaf_value(schema_type, field, hints)

    # string, or any type this filler does not special-case.
    return leaf_fn(field)


def _fill_object(
    schema: dict[str, Any],
    leaf_fn: Callable[[str], Any],
    hints: _FillHints,
) -> dict[str, Any]:
    """Fills every required property, plus any hinted optional ones.

    Args:
        schema: The object's JSON Schema fragment.
        leaf_fn: Zero-argument callable returning the next string-leaf
            value (see ``_fill_schema``).
        hints: Array-length, scalar-value, and optional-field hints,
            threaded into each property's fill. ``hints.optional_fields``
            is empty by default, so a property this node's own schema
            marks optional stays absent unless a caller named it.

    Returns:
        A dict mapping each filled property name to its value.
    """
    properties = schema.get("properties", {})
    required = schema.get("required") or list(properties.keys())
    return {
        name: _fill_property(name, prop_schema, leaf_fn, hints)
        for name, prop_schema in properties.items()
        if name in required or name in hints.optional_fields
    }


def _fill_property(
    name: str,
    schema: dict[str, Any],
    leaf_fn: Callable[[str], Any],
    hints: _FillHints,
) -> Any:
    """Fills one object property, honoring an array-length hint by name.

    Args:
        name: The property name, checked against ``hints.array_lengths``.
        schema: The property's own JSON Schema fragment.
        leaf_fn: Zero-argument callable returning the next string-leaf
            value (see ``_fill_schema``).
        hints: Array-length and scalar-value hints.

    Returns:
        The filled property value.
    """
    if schema.get("type") == "array" and name in hints.array_lengths:
        return _fill_array(
            schema, hints.array_lengths[name], leaf_fn, hints, name
        )
    return _fill_schema(schema, leaf_fn, hints, name)


def _fill_array(
    schema: dict[str, Any],
    count: int,
    leaf_fn: Callable[[str], Any],
    hints: _FillHints,
    field: str = "",
) -> list[Any]:
    """Fills an array schema with ``count`` (at least one) filled items.

    Args:
        schema: The array's JSON Schema fragment (reads "items").
        count: Desired item count; clamped up to one.
        leaf_fn: Zero-argument callable returning the next string-leaf
            value (see ``_fill_schema``).
        hints: Array-length and scalar-value hints, threaded into each
            item's fill so length hints apply at any nesting depth.
        field: Name of the array property, passed down so an item reads as
            the field it belongs to.

    Returns:
        A list of ``max(count, 1)`` filled items.
    """
    item_schema = schema.get("items", {"type": "string"})
    return [
        _fill_schema(item_schema, leaf_fn, hints, field)
        for _ in range(max(count, 1))
    ]
