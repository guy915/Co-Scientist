"""Pins the run spec against the plan config Google's product renders.

The reference corpus carries a transcription of the research plan shown in
Google's own Gemini Enterprise footage (``media/live-footage/``), which is
the only primary evidence of how the shipped product configures a run: the
sections its plan is built from, and the two vocabularies -- focus and tier
-- it offers with the selected option marked.

Those vocabularies were reconstructed here before the transcription was read
back, and they match it exactly, so this test reads them out of the artifact
rather than restating them. It exists because nothing else ties the two
together: a rename in ``run_modes`` would otherwise look like a free local
choice, and the fidelity audit had already recorded the four tiers as a
local extension over a two-tier product (``B1``) on the strength of the
earlier captures.

The corpus lives outside ``app/``, which is independently installable, so an
app checked out without it skips; a ``references/`` tree that has lost the
artifact is a move or a deletion, and fails.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app.run_modes import RUN_FOCUS_VALUES, RUN_TIER_DEFAULTS

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


def test_run_tiers_are_the_ones_the_product_offers() -> None:
    """The four tiers, and their order, come from the product's own plan."""
    assert _offered_options(_section("Tier")) == list(RUN_TIER_DEFAULTS)


def test_run_focus_values_are_the_ones_the_product_offers() -> None:
    """The four focus values, and their order, likewise."""
    assert _offered_options(_section("Focus")) == list(RUN_FOCUS_VALUES)


def test_the_plan_carries_every_section_the_product_shows() -> None:
    """The rendered run setup carries each section of the product's plan.

    The product's plan is the research goal plus five configured sections.
    ``Goal`` is the run's own research goal rather than a spec field, so
    only the other five are pinned here.
    """
    headings = re.findall(r"^## (.+)$", _plan_config(), re.M)
    configured = {"Requirements", "Attributes", "Criteria", "Focus", "Tier"}
    assert configured <= set(headings)
    assert "Goal" in headings
