"""R12-4: the run-level Criteria field's named-setting shape and back-compat.

Split out of ``run_modes`` to keep that module within the size cap. Google's
published run plan renders Criteria as three named settings, each carrying
an explicit value ("Idea correctness: Required", etc. --
docs/CORPUS-EXTRACTION.md line 1949), not free prose; this module owns the
default that mirrors them, the caller-input cleaning that still accepts a
producer's own free-prose criteria, and the back-compat rendering shared by
every consumer of a run's stored ``criteria`` -- whichever shape it holds.

Every name here is re-exported from ``run_modes`` so ``run_modes.<name>``
keeps resolving for existing importers.
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
    """Extract a name/value pair from one dict-shaped criteria item.

    Shared by ``clean_criteria_list`` and ``criteria_display_strings`` so
    both agree on what counts as a usable R12-4 pair.

    Returns:
        The stripped ``(name, value)`` pair, or ``None`` when the item
        carries no usable name.
    """
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    return name, str(item.get("value") or "").strip()


def clean_criteria_list(values: list[Any] | None = None) -> list[Any]:
    """Trim and validate a caller-supplied criteria list.

    Each item is either the legacy free-prose string (a run persisted
    before R12-4, or a caller -- CLI, demo seeding -- that still supplies
    its own prose criteria) or the ``{"name", "value"}`` pair shape
    mirroring Google's published run plan (``DEFAULT_CRITERIA``). Both
    are accepted here so an existing producer of free-text criteria keeps
    working unchanged; only the *default*, used when a caller supplies
    none, moved to the published pair shape.
    """
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
    """Render one criteria item (either stored shape) as a display line.

    Returns:
        The bare string, ``"{name}: {value}"`` for a dict item, or ``""``
        when the item is unusable (an unnamed dict, or blank text).
    """
    if isinstance(item, dict):
        pair = _named_criterion(item)
        if pair is None:
            return ""
        name, value = pair
        return f"{name}: {value}" if value else name
    return str(item).strip()


def criteria_display_strings(raw_values: Any) -> list[str]:
    """Render stored criteria as flat display/prompt lines.

    Back-compat (R12-4): a run persisted before this change stored
    ``criteria`` as a list of free-prose strings; one created after
    stores the ``{"name", "value"}`` pair shape mirroring Google's
    published run plan (``DEFAULT_CRITERIA``). Both shapes render here --
    the bare string, or ``"{name}: {value}"`` -- so a legacy run's
    report, Goal Details, and engine-facing prompt guidance keep reading
    exactly as they always did, and every consumer of the setup block's
    criteria (``setup_guidance``, the report header, the engine opts
    translation) shares this one coercion instead of each guessing at
    the shape on its own.
    """
    if not isinstance(raw_values, list):
        return []
    return [
        line for item in raw_values if (line := _criterion_display_line(item))
    ]


def _default_criteria() -> list[dict[str, str]]:
    """Fresh copies of ``DEFAULT_CRITERIA`` so callers never share dicts."""
    return [dict(pair) for pair in DEFAULT_CRITERIA]
