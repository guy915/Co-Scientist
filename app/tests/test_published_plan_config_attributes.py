"""Pins the R12-5 attribute *structure* against the published Attributes block.

Unlike ``test_published_plan_config_criteria.py`` (R12-4), this does not
assert our default equals the published content -- the MASH plan config's
``## Attributes`` section (docs/CORPUS-EXTRACTION.md line 1930) is specific
to that one run's goal, so copying its text would hardcode one study's
rubric as every run's default (see ``run_modes.planning``'s module
docstring). What this pins instead is the published *structure* -- four
axes on an explicit 1-5 scale with anchor text, one categorical with an
enumerated value set -- and that ``run_modes.planning``'s shape can
represent every published item exactly, anchor omissions included.

Reads ``docs/CORPUS-EXTRACTION.md`` at test time rather than retranscribing
the section as Python literals, so a future edit to that appendix cannot
drift from this test unnoticed. Safe to do unconditionally -- that file is
committed repo content, not the optional ``references/`` corpus this module
must never touch.
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass

from app.run_modes import attribute_display_strings
from app.run_modes.planning import clean_attributes_list

_CORPUS_EXTRACTION = (
    pathlib.Path(__file__).resolve().parents[2]
    / "docs"
    / "CORPUS-EXTRACTION.md"
)
_SCALE_POINTS = ("1", "3", "5")


@dataclass(frozen=True)
class _PublishedAttribute:
    """One parsed bullet from the published ``## Attributes`` section."""

    name: str
    kind: str  # "scale" or "categorical"
    anchors: dict[str, str]
    values: list[str]


def _attribute_section_text() -> str:
    """Return the raw text of the published ``## Attributes`` section."""
    text = _CORPUS_EXTRACTION.read_text(encoding="utf-8")
    match = re.search(r"^## Attributes\n(.*?)(?=\n## )", text, re.S | re.M)
    assert match is not None, (
        "docs/CORPUS-EXTRACTION.md lost its Attributes section"
    )
    return match.group(1)


def _parse_scale_anchors(parenthetical: str) -> dict[str, str]:
    """Extract each point's anchor text from a "1-5 scale (...)" parenthetical.

    Anchor text may itself contain commas (e.g. Validation Plan Strength's
    "5: Clear, detailed, with well-defined quantitative go/no-go criteria"),
    so this only splits on a comma immediately followed by the next point
    marker, never on any comma.
    """
    anchors = {}
    for match in re.finditer(
        r"([135]):\s*(.*?)(?=,\s*[135]:|$)", parenthetical
    ):
        anchors[match.group(1)] = match.group(2).strip()
    return anchors


def _parse_categorical_values(parenthetical: str) -> list[str]:
    """Extract each option from a "(A, B, or C)" categorical parenthetical."""
    parts = re.split(r",\s*", parenthetical)
    return [re.sub(r"^or\s+", "", part).strip() for part in parts]


def _parse_one_attribute(name: str, body: str) -> _PublishedAttribute:
    """Parse one bullet's body into its structural shape."""
    body = re.sub(r"\s+", " ", body).strip()
    paren_match = re.search(r"\(([^()]*)\)", body)
    assert paren_match is not None, f"{name!r} bullet carries no parenthetical"
    parenthetical = paren_match.group(1)
    if "1-5 scale" in body:
        return _PublishedAttribute(
            name=name,
            kind="scale",
            anchors=_parse_scale_anchors(parenthetical),
            values=[],
        )
    return _PublishedAttribute(
        name=name,
        kind="categorical",
        anchors={},
        values=_parse_categorical_values(parenthetical),
    )


def _published_attributes() -> list[_PublishedAttribute]:
    """Parse every bullet in the published ``## Attributes`` section."""
    section = _attribute_section_text()
    bullets = re.findall(
        r"^- \*\*(.+?):\*\*\s*(.*?)(?=\n- \*\*|\Z)", section, re.S | re.M
    )
    assert bullets, "the Attributes section printed no '**Name:** ...' bullets"
    return [_parse_one_attribute(name, body) for name, body in bullets]


def test_published_attributes_are_four_scaled_and_one_categorical() -> None:
    """The published block's own shape: 4 scaled axes + 1 categorical axis."""
    attributes = _published_attributes()
    names_and_kinds = [(a.name, a.kind) for a in attributes]
    assert names_and_kinds == [
        ("Mechanism Novelty", "scale"),
        ("Human Relevance", "scale"),
        ("Clinical Translatability", "scale"),
        ("Target Area", "categorical"),
        ("Validation Plan Strength", "scale"),
    ]


def test_human_relevance_anchor_omits_the_midpoint() -> None:
    """One published scale carries no point-3 anchor -- not every axis does."""
    human_relevance = next(
        a for a in _published_attributes() if a.name == "Human Relevance"
    )
    assert set(human_relevance.anchors) == {"1", "5"}


def test_target_area_is_a_three_option_categorical() -> None:
    """The one published categorical axis names three allowed values."""
    target_area = next(
        a for a in _published_attributes() if a.name == "Target Area"
    )
    assert target_area.values == [
        "Epigenetics",
        "Stellate Cell Biology",
        "Stromal-Immune Crosstalk",
    ]


def test_our_attribute_shape_represents_every_published_item() -> None:
    """R12-5: our structured shape can encode every published axis intact.

    This proves the *structure* mirrors the published block -- scaled axes
    with partial or full anchors, and a categorical axis with an
    enumerated value set -- without copying the published (goal-specific)
    content into our own goal-agnostic default.
    """
    for attribute in _published_attributes():
        if attribute.kind == "scale":
            item = {
                "name": attribute.name,
                "scale": dict(attribute.anchors),
            }
        else:
            item = {"name": attribute.name, "values": list(attribute.values)}
        cleaned = clean_attributes_list([item])
        assert cleaned == [item]
        lines = attribute_display_strings([item])
        assert len(lines) == 1
        assert lines[0].startswith(attribute.name)
