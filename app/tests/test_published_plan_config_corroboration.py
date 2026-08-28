"""Corroborates the transcription pinned in the sibling plan-config module.

``test_published_plan_config.py`` checks ``app.run_modes`` against literals
transcribed from the reference corpus's Gemini Enterprise plan-config
capture, cited there to the extracted file they came from. This module
re-reads that same file and asserts the transcription still matches what
is on disk.

The corpus lives outside ``app/``, which is independently installable, so
this module skips when checked out without it; a ``references/`` tree
that has lost the artifact is a move or a deletion, and fails. Losing this
module on ``references/`` deletion is expected and safe: the values it
exists to corroborate are already guarded, without disk access, by the
sibling pin module.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from tests.test_published_plan_config import (
    _PLAN_CONFIGURED_SECTIONS,
    _PLAN_FOCUS_OPTIONS,
    _PLAN_GOAL_SECTION,
    _PLAN_TIER_OPTIONS,
)

_REFERENCES = pathlib.Path(__file__).resolve().parents[2] / "references"
_PLAN_CONFIG = (
    _REFERENCES
    / "core/google-co-scientist/research/extracted-artifacts/outputs"
    / "plan-configs/mash-liver-fibrosis-reversal-research-plan.md"
)


def _plan_config() -> str:
    """Return the transcribed plan config, skipping only outside the repo."""
    if not _REFERENCES.is_dir():
        pytest.skip("app checked out without the reference corpus")
    assert _PLAN_CONFIG.is_file(), f"artifact moved or deleted: {_PLAN_CONFIG}"
    return _PLAN_CONFIG.read_text(encoding="utf-8")


def _section(name: str) -> str:
    """Return one ``## `` section's body from the plan config.

    Args:
        name: The section heading, e.g. ``Tier``.

    Returns:
        Everything under that heading up to the next one.
    """
    match = re.search(
        rf"^## {name}\n(.*?)(?=\n## |\Z)", _plan_config(), re.S | re.M
    )
    assert match is not None, f"plan config has no {name!r} section"
    return match.group(1)


def _offered_options(section: str) -> list[str]:
    """Return the options a plan section offers, in the order shown.

    Each is a bullet whose label precedes a colon; the selected one carries
    a bold marker this deliberately ignores, since the vocabulary is what
    is being pinned, not which option that run chose.

    Args:
        section: The section body to read.

    Returns:
        The option labels, lowercased with spaces as underscores.
    """
    labels = re.findall(r"^- \*?\*?([A-Z][^:*]*?)\*?\*?:", section, re.M)
    return [label.strip().lower().replace(" ", "_") for label in labels]


def test_plan_config_still_offers_the_pinned_tiers() -> None:
    """The transcribed plan still offers the pinned tiers, in order."""
    assert _offered_options(_section("Tier")) == list(_PLAN_TIER_OPTIONS)


def test_plan_config_still_offers_the_pinned_focus_values() -> None:
    """The transcribed plan still offers the pinned focus values, in order."""
    assert _offered_options(_section("Focus")) == list(_PLAN_FOCUS_OPTIONS)


def test_plan_config_still_prints_every_pinned_section() -> None:
    """The transcribed plan still prints every pinned section heading."""
    headings = re.findall(r"^## (.+)$", _plan_config(), re.M)
    assert set(headings) >= _PLAN_CONFIGURED_SECTIONS
    assert _PLAN_GOAL_SECTION in headings
