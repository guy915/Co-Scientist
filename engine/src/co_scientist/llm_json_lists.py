"""Coercion of a parsed LLM JSON value into the list a caller expects.

DeepSeek's json_object response mode does not enforce the schema it is
given, so a field a schema declares as an array can still come back off
shape: a bare string, a dict carrying the list under one of a few
plausible keys, a dict that is itself the single element wanted, or a
list whose elements are individually the wrong type.
``coerce_json_list`` is the one seam every such read should route
through, so the fix lives once rather than once per caller.

Not a substitute for ``co_scientist.llm_json.validate_json_schema``: a
call site that already passes a JSON schema to ``call_llm_json`` is
validated there, on every retry attempt, with corrective feedback sent
back to the model. This module is for the sites that read a list without
a schema in the loop at all -- a tool-calling loop's final response
(``parse_tool_loop_json``), or a freeform/json_object-mode call made
directly against a provider.
"""

import logging
from typing import Any, Literal, overload

logger = logging.getLogger(__name__)

ElementKind = Literal["any", "dict", "str"]


def _element_ok(item: Any, element: ElementKind) -> bool:
    """Whether one list element already matches the wanted element kind."""
    if element == "dict":
        return isinstance(item, dict)
    if element == "str":
        return isinstance(item, str)
    return True


def _clean_str_element(item: str) -> str:
    """Strip one string element; blank strings are dropped by the caller."""
    return item.strip()


def _filter_elements(
    items: list[Any], element: ElementKind
) -> tuple[list[Any], bool]:
    """Keep only well-typed, non-blank elements; report whether any dropped.

    Args:
        items: The raw list to filter.
        element: The element kind every entry must satisfy.

    Returns:
        The kept elements (strings stripped), and whether anything was
        dropped -- a wrong-typed entry, or (for ``"str"``) a blank one.
    """
    kept: list[Any] = []
    dropped = False
    for item in items:
        if not _element_ok(item, element):
            dropped = True
            continue
        if element == "str":
            cleaned = _clean_str_element(item)
            if not cleaned:
                dropped = True
                continue
            kept.append(cleaned)
        else:
            kept.append(item)
    return kept, dropped


def _list_from_dict(
    value: dict[str, Any], keys: tuple[str, ...], element: ElementKind
) -> list[Any] | None:
    """Recover a list from a dict: a known key, or the dict as one element.

    Args:
        value: The dict found where a list was expected.
        keys: Property names that might carry the list, tried in order.
        element: The element kind the caller wants.

    Returns:
        The list found under a key, ``[value]`` when ``value`` itself is
        the single element wanted (``element="dict"``), or ``None`` when
        nothing usable could be recovered.
    """
    for key in keys:
        found = value.get(key)
        if isinstance(found, list):
            return found
    if element == "dict":
        return [value]
    return None


def _coerce_from_list(
    value: list[Any], element: ElementKind, site: str
) -> list[Any]:
    """Filter an already-list value, warning only if something was dropped."""
    items, dropped = _filter_elements(value, element)
    if dropped:
        logger.warning("%s: dropped list element(s) of the wrong type", site)
    return items


def _coerce_from_dict(
    value: dict[str, Any],
    keys: tuple[str, ...],
    element: ElementKind,
    site: str,
) -> list[Any]:
    """Recover a list from a dict, warning either way -- a real coercion."""
    found = _list_from_dict(value, keys, element)
    if found is None:
        logger.warning(
            "%s: expected a list, got a dict with no usable list", site
        )
        return []
    items, _dropped = _filter_elements(found, element)
    logger.warning("%s: coerced a dict into a list", site)
    return items


def _coerce_from_scalar(
    value: Any, element: ElementKind, site: str
) -> list[Any]:
    """Wrap a bare non-list, non-dict scalar into a one-element list."""
    if element != "str" or not isinstance(value, str) or not value.strip():
        logger.warning(
            "%s: expected a list, got %s", site, type(value).__name__
        )
        return []
    logger.warning("%s: coerced a bare value into a one-item list", site)
    return [value.strip()]


@overload
def coerce_json_list(
    value: Any,
    *,
    keys: tuple[str, ...] = (),
    element: Literal["str"],
    site: str,
) -> list[str]: ...


@overload
def coerce_json_list(
    value: Any,
    *,
    keys: tuple[str, ...] = (),
    element: Literal["dict"],
    site: str,
) -> list[dict[str, Any]]: ...


@overload
def coerce_json_list(
    value: Any,
    *,
    keys: tuple[str, ...] = (),
    element: Literal["any"] = "any",
    site: str,
) -> list[Any]: ...


def coerce_json_list(
    value: Any,
    *,
    keys: tuple[str, ...] = (),
    element: ElementKind = "any",
    site: str,
) -> list[Any]:
    """Coerce a parsed LLM JSON value into the list a caller expects.

    Overloaded on ``element``: ``"str"`` and ``"dict"`` narrow the return
    type to what ``_filter_elements`` actually guarantees at runtime for
    those cases, so a caller declaring ``list[str]`` or ``list[dict[str,
    Any]]`` gets a checked return rather than an ``Any`` it has to trust.

    Args:
        value: The parsed value found where a list was expected.
        keys: Property names to look under when ``value`` is a dict
            carrying the list rather than being the list itself --
            typically the schema's own field name plus a generic
            fallback such as ``"items"``.
        element: The element type each list entry must satisfy --
            ``"dict"`` drops non-dict entries (and lets a bare dict
            stand for a one-element list), ``"str"`` coerces scalars to
            stripped, non-blank strings, ``"any"`` performs no
            per-element filtering.
        site: The call site, logged with any coercion warning so a run
            that degraded silently can be traced back to where.

    Returns:
        A list of well-typed elements; empty when nothing usable could
        be recovered from ``value``.
    """
    if isinstance(value, list):
        return _coerce_from_list(value, element, site)
    if value is None:
        return []
    if isinstance(value, dict):
        return _coerce_from_dict(value, keys, element, site)
    return _coerce_from_scalar(value, element, site)
