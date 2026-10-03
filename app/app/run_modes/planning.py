"""Normalize and render structured planning criteria and attributes.

Legacy free-prose values remain supported alongside named criteria,
scaled attributes and categorical attributes. Defaults are goal-agnostic.
"""

from __future__ import annotations

from typing import Any

# Unlike Attributes -- a separate, goal-specific row -- these three are
# goal-agnostic, so the default mirrors them exactly rather than adapting
# them. Pinned against the source doc by
# tests/test_published_plan_config_criteria.py.
DEFAULT_CRITERIA: tuple[dict[str, str], ...] = (
    {"name": "Idea correctness", "value": "Required"},
    {"name": "Idea novelty", "value": "Required"},
    {"name": "Maximize impact", "value": "Yes"},
)


def _named_criterion(item: dict[str, Any]) -> tuple[str, str] | None:
    """Extract a name/value pair from one dict-shaped criteria item."""
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    return name, str(item.get("value") or "").strip()


def clean_criteria_list(values: list[Any] | None = None) -> list[Any]:
    """Trim and validate a caller-supplied criteria list."""
    cleaned: list[Any] = []
    for item in values or []:
        if isinstance(item, dict):
            pair = _named_criterion(item)
            if pair is not None:
                cleaned.append({"name": pair[0], "value": pair[1]})
        else:
            text = str(item).strip()
            if text:
                cleaned.append(text)
    return cleaned


def _criterion_display_line(item: Any) -> str:
    """Render one criteria item (either stored shape) as a display line."""
    if isinstance(item, dict):
        pair = _named_criterion(item)
        if pair is None:
            return ""
        name, value = pair
        return f"{name}: {value}" if value else name
    return str(item).strip()


def criteria_display_strings(raw_values: Any) -> list[str]:
    """Render stored criteria as flat display/prompt lines."""
    if not isinstance(raw_values, list):
        return []
    return [
        line for item in raw_values if (line := _criterion_display_line(item))
    ]


def _default_criteria() -> list[dict[str, str]]:
    """Fresh copies of ``DEFAULT_CRITERIA`` so callers never share dicts."""
    return [dict(pair) for pair in DEFAULT_CRITERIA]


_SCALE_POINTS: tuple[str, ...] = ("1", "3", "5")

# The old DEFAULT_ATTRIBUTES held three free strings ("Mechanistically
# specific", "Evidence-grounded", "Experiment-ready"); the same three
# concepts carry over here as scaled 1-5 axes with anchor text at every
# point, goal-agnostic by construction. The published block's one
# categorical axis (Target Area) is itself goal-*derived* -- its three
# values are literally that run's own core-focus-area list from the
# Requirements section -- so no goal-agnostic categorical default exists
# to mirror. The categorical shape is still fully supported below
# (``clean_attributes_list``, ``attribute_display_strings``) for any
# producer that wants one; pinned against the published Target Area
# bullet by tests/test_published_plan_config_attributes.py.
DEFAULT_ATTRIBUTES: tuple[dict[str, Any], ...] = (
    {
        "name": "Mechanistic specificity",
        "scale": {
            "1": "Vague or hand-wavy mechanism",
            "3": "Plausible mechanism with some unexplained steps",
            "5": "Precise, causally complete mechanism",
        },
    },
    {
        "name": "Evidence grounding",
        "scale": {
            "1": "Speculative, no literature support",
            "3": "Partially supported by existing evidence",
            "5": "Strongly grounded in established literature",
        },
    },
    {
        "name": "Experimental readiness",
        "scale": {
            "1": "No clear path to testing",
            "3": "Testable with significant additional groundwork",
            "5": "Directly testable with a well-defined validation plan",
        },
    },
)


def _clean_scale(raw: Any) -> dict[str, str]:
    """Trim a stored scale dict to its present, non-empty anchors."""
    if not isinstance(raw, dict):
        return {}
    cleaned: dict[str, str] = {}
    for point in _SCALE_POINTS:
        text = str(raw.get(point) or "").strip()
        if text:
            cleaned[point] = text
    return cleaned


def _clean_values(raw: Any) -> list[str]:
    """Trim a stored categorical value list to its non-empty entries."""
    if not isinstance(raw, list):
        return []
    return [text for item in raw if (text := str(item).strip())]


def _clean_attribute_dict(item: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one dict-shaped attribute item, or None if unnamed."""
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    scale = _clean_scale(item.get("scale"))
    if scale:
        return {"name": name, "scale": scale}
    values = _clean_values(item.get("values"))
    if values:
        return {"name": name, "values": values}
    return {"name": name}


def clean_attributes_list(values: list[Any] | None = None) -> list[Any]:
    """Trim and validate a caller-supplied attributes list."""
    cleaned: list[Any] = []
    for item in values or []:
        if isinstance(item, dict):
            normalized = _clean_attribute_dict(item)
            if normalized is not None:
                cleaned.append(normalized)
        else:
            text = str(item).strip()
            if text:
                cleaned.append(text)
    return cleaned


def _join_with_or(values: list[str]) -> str:
    """Join values with a trailing "or", matching the published phrasing."""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} or {values[1]}"
    return ", ".join(values[:-1]) + f", or {values[-1]}"


def _scaled_display_line(name: str, scale: dict[str, str]) -> str:
    """Render one scaled axis, mirroring the published "1-5 scale (...)"."""
    anchors = ", ".join(
        f"{point}: {scale[point]}" for point in _SCALE_POINTS if point in scale
    )
    return f"{name}: 1-5 scale ({anchors})" if anchors else name


def _categorical_display_line(name: str, values: list[str]) -> str:
    """Render one categorical axis, mirroring the published "(A, B, or C)"."""
    return f"{name} ({_join_with_or(values)})" if values else name


def _dict_attribute_display_line(item: dict[str, Any]) -> str:
    """Render one dict-shaped attribute item as a display line."""
    name = str(item.get("name") or "").strip()
    if not name:
        return ""
    scale = item.get("scale")
    if isinstance(scale, dict) and scale:
        return _scaled_display_line(name, scale)
    values = item.get("values")
    if isinstance(values, list) and values:
        return _categorical_display_line(name, [str(v) for v in values])
    return name


def _attribute_display_line(item: Any) -> str:
    """Render one attribute item (either stored shape) as a display line."""
    if isinstance(item, dict):
        return _dict_attribute_display_line(item)
    return str(item).strip()


def attribute_display_strings(raw_values: Any) -> list[str]:
    """Render stored attributes as flat display/report lines."""
    if not isinstance(raw_values, list):
        return []
    return [
        line for item in raw_values if (line := _attribute_display_line(item))
    ]


def attribute_names(raw_values: Any) -> list[str]:
    """Return just the bare name of each stored attribute item."""
    if not isinstance(raw_values, list):
        return []
    names: list[str] = []
    for item in raw_values:
        name = (
            str(item.get("name") or "").strip()
            if isinstance(item, dict)
            else str(item).strip()
        )
        if name:
            names.append(name)
    return names


def _default_attributes() -> list[dict[str, Any]]:
    """Fresh copies of ``DEFAULT_ATTRIBUTES`` so callers never share dicts."""
    fresh: list[dict[str, Any]] = []
    for item in DEFAULT_ATTRIBUTES:
        copy: dict[str, Any] = {"name": item["name"]}
        if "scale" in item:
            copy["scale"] = dict(item["scale"])
        if "values" in item:
            copy["values"] = list(item["values"])
        fresh.append(copy)
    return fresh
