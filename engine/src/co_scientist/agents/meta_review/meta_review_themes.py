"""Normalization of the meta-review's recurring-critique taxonomy (MO-2).

Split out of ``meta_review.py`` when the flat ``{theme, description,
frequency}`` entry gained its nested ``sub_themes``: that module was
already at 440 of the repo's 500-line ceiling, and this is the one part of
it with no dependency on the node, its prompt, or the workflow state.

Every coercion here exists because ``json_object`` mode enforces nothing
(see ``llm.request.completion._supports_json_schema_response_format``): the
model can return a bare string where an object is declared, a string where an
array is, or an integer where a string is. Nothing is dropped for being the
wrong shape -- an entry that does not parse as a taxonomy node keeps its own
text and loses only the structure it never had. The uniform shape this returns
is a cross-module contract: ``report_markdown_meta_review`` on the app side
renders it, and a checkpoint written before ``sub_themes`` existed still reaches
that renderer unnormalized, so both sides read every nested field with a default
rather than by indexing.
"""

from typing import Any


def normalize_recurring_themes(
    recurring_themes: list[Any],
) -> list[dict[str, Any]]:
    """Coerce every entry into a uniform nested taxonomy node.

    Args:
        recurring_themes: The model's ``recurring_themes`` array, of any
            shape.

    Returns:
        One ``{theme, description, frequency, sub_themes}`` dict per
        entry, with ``sub_themes`` itself normalized.
    """
    return [_normalize_theme(entry) for entry in recurring_themes]


def _normalize_theme(entry: Any) -> dict[str, Any]:
    """Normalize one top-level theme.

    A non-dict entry keeps its text as ``theme`` with everything else
    empty, rather than being dropped: the flattening this replaced already
    tolerated a bare string, and a model that ignores the schema at the
    top level has still said something worth reporting.
    """
    if not isinstance(entry, dict):
        return _theme_node(str(entry), "", "", [])
    return _theme_node(
        str(entry.get("theme", "")),
        str(entry.get("description", "")),
        # A lax provider returns frequency as a bare integer even though
        # the schema declares it a string.
        str(entry.get("frequency", "")),
        _normalize_sub_themes(entry.get("sub_themes")),
    )


def _theme_node(
    theme: str,
    description: str,
    frequency: str,
    sub_themes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build one theme node, so its key set is written down once."""
    return {
        "theme": theme,
        "description": description,
        "frequency": frequency,
        "sub_themes": sub_themes,
    }


def _normalize_sub_themes(sub_themes: Any) -> list[dict[str, Any]]:
    """Normalize a theme's sub-theme list, tolerating a non-list value."""
    if not isinstance(sub_themes, list):
        return []
    return [_normalize_sub_theme(entry) for entry in sub_themes]


def _normalize_sub_theme(entry: Any) -> dict[str, Any]:
    """Normalize one critique point under a theme.

    ``points`` is the taxonomy's third level and the published artifact's
    last: a list of plain guidance sentences, with nothing nested below
    them.
    """
    if not isinstance(entry, dict):
        return {"theme": str(entry), "description": "", "points": []}
    return {
        "theme": str(entry.get("theme", "")),
        "description": str(entry.get("description", "")),
        "points": _normalize_points(entry.get("points")),
    }


def _normalize_points(points: Any) -> list[str]:
    """Coerce a sub-theme's guidance points to strings."""
    if not isinstance(points, list):
        return []
    return [str(point) for point in points]
