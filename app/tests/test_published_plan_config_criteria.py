"""Pins ``run_modes.DEFAULT_CRITERIA`` against the published Criteria block.

R12-4: the MASH plan config's ``## Criteria`` section (docs/CORPUS-
EXTRACTION.md line 1949 -- the same Gemini Enterprise capture
``test_published_plan_config.py`` pins tier/focus and section headings
against) prints three named settings, each with an explicit value, not a
free-prose list: "Idea correctness: Required", "Idea novelty: Required",
"Maximize impact: Yes".

Unlike that sibling module, this reads the three pairs directly out of
``docs/CORPUS-EXTRACTION.md`` at test time rather than retranscribing them
as Python literals, so a future edit to that appendix (or to
``DEFAULT_CRITERIA``) cannot drift from the other unnoticed. That is safe
to do unconditionally here -- ``docs/CORPUS-EXTRACTION.md`` is committed
repo content, not the optional ``references/`` corpus this module must
never touch, so there is nothing to skip: the file is always present in
any checkout that has this test.
"""

from __future__ import annotations

import pathlib
import re

from app.run_modes import DEFAULT_CRITERIA

_CORPUS_EXTRACTION = (
    pathlib.Path(__file__).resolve().parents[2]
    / "docs"
    / "CORPUS-EXTRACTION.md"
)


def _published_criteria_pairs() -> list[dict[str, str]]:
    """Parse the MASH plan config's ``## Criteria`` block off disk.

    Returns:
        The section's ``- Name: Value`` bullets, in the order printed.
    """
    text = _CORPUS_EXTRACTION.read_text(encoding="utf-8")
    match = re.search(r"^## Criteria\n(.*?)(?=\n## )", text, re.S | re.M)
    assert match is not None, (
        "docs/CORPUS-EXTRACTION.md lost its Criteria section"
    )
    pairs = re.findall(r"^- (.+?):\s*(.+)$", match.group(1), re.M)
    assert pairs, "the Criteria section printed no 'Name: Value' bullets"
    return [
        {"name": name.strip(), "value": value.strip()} for name, value in pairs
    ]


def test_default_criteria_mirrors_the_published_plan_config() -> None:
    """The default Criteria are exactly the three published name/value pairs."""
    assert list(DEFAULT_CRITERIA) == _published_criteria_pairs()
