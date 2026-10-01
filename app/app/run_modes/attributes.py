"""R12-5: the run-level Attributes field's structured shape and back-compat.

Split out of ``run_modes`` to keep that module within the size cap, mirroring
the sibling ``run_modes.criteria`` module R12-4 added. Google's published run
plan renders Attributes as five named scoring axes
(docs/CORPUS-EXTRACTION.md line 1930): four on an explicit 1-5 scale with
anchor text at points 1, 3, and 5 (Mechanism Novelty, Human Relevance,
Clinical Translatability, Validation Plan Strength), and one categorical
with an enumerated value set (Target Area: Epigenetics / Stellate Cell
Biology / Stromal-Immune Crosstalk).

Unlike Criteria -- goal-agnostic, mirrored verbatim -- these five are
specific to that one run's goal (liver fibrosis), so copying their text
would hardcode one study's rubric as every run's default. What generalizes
is the *structure*: an attribute is a named axis that is either scaled
(anchors at 1, 3, and 5 -- Human Relevance in the published block carries
only 1 and 5, so a scale need not fill every point) or categorical (a name
plus an enumerated set of allowed values). This module owns that structure
-- the default that mirrors it with goal-agnostic content, the
caller-input cleaning that still accepts a producer's own free-prose
attributes, and the back-compat rendering shared by every consumer of a
run's stored ``attributes`` -- whichever shape it holds.

A goal-*specific* attribute rubric is a separate, already-built field:
``config_synthesis.attributes`` (R12-17), which the Supervisor synthesizes
per run and ``report/markdown/supervisor.py`` renders as "Stratification
Attributes" -- deliberately not this field, and not touched here.

Every name here is re-exported from ``run_modes`` so ``run_modes.<name>``
keeps resolving for existing importers.
"""

from __future__ import annotations

from typing import Any

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
    """Trim a stored scale dict to its present, non-empty anchors.

    Anchors need not fill every point -- the published block's own Human
    Relevance axis carries only 1 and 5, no midpoint.
    """
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
    """Normalize one dict-shaped attribute item, or None if unnamed.

    A scale wins over a values list when a producer sends both (malformed
    input); an item with neither still keeps its bare name, matching
    ``clean_criteria_list``'s own forgiving rule for an unnamed value.
    """
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
    """Trim and validate a caller-supplied attributes list.

    Each item is either the legacy free-prose string (a run persisted
    before R12-5, or a caller -- CLI, demo seeding, an Agent interview's
    ``focus_area`` -- that still supplies its own prose attributes) or the
    structured axis shape mirroring Google's published run plan
    (``DEFAULT_ATTRIBUTES``): ``{"name", "scale"}`` for a 1-5 rating with
    anchor text, or ``{"name", "values"}`` for a categorical axis. Both
    are accepted here so an existing producer of free-text attributes
    keeps working unchanged; only the *default*, used when a caller
    supplies none, moved to the structured shape.
    """
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
    """Join values with a trailing "or", matching the published phrasing.

    ``["A", "B", "C"]`` -> ``"A, B, or C"``, mirroring the published
    Target Area bullet's own "(Epigenetics, Stellate Cell Biology, or
    Stromal-Immune Crosstalk)" punctuation.
    """
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
    """Render stored attributes as flat display/report lines.

    Back-compat (R12-5): a run persisted before this change stored
    ``attributes`` as a list of free-prose strings; one created after
    stores the structured axis shape mirroring Google's published run
    plan (``DEFAULT_ATTRIBUTES``). Both shapes render here -- the bare
    string, ``"{name}: 1-5 scale (...)"``, or ``"{name} (A, B, or C)"`` --
    so a legacy run's report, Goal Details, and specifications tab keep
    reading exactly as they always did, and every consumer of the setup
    block's attributes (``setup_guidance``, the report header, the specs
    tab) shares this one coercion instead of each guessing at the shape
    on its own.
    """
    if not isinstance(raw_values, list):
        return []
    return [
        line for item in raw_values if (line := _attribute_display_line(item))
    ]


def attribute_names(raw_values: Any) -> list[str]:
    """Return just the bare name of each stored attribute item.

    Feeds the engine's comma-joined and bullet-joined attribute prompt
    slots (``format_attributes``, ``_format_debate_attributes``, and the
    csv-joined ``attributes`` slot in ``prompts/planning.py`` and
    ``prompts/literature.py``) with short quality descriptors, exactly as
    a legacy free-prose run always sent -- an anchor's own internal
    punctuation would otherwise land inside a comma-joined prompt slot
    and read as extra list items. The full anchored rubric
    (``attribute_display_strings``) still reaches the engine, bulleted,
    through ``setup_guidance``'s "Attributes:" block, folded into the
    "preferences" opt -- nothing here is lost, only kept out of the
    slots that were never meant to carry it.
    """
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
