"""Pins the run spec against the plan config Google's product renders.

The reference corpus carries a transcription of the research plan shown in
Google's own Gemini Enterprise footage (``media/live-footage/``), which is
the only primary evidence of how the shipped product configures a run: the
sections its plan is built from, and the two vocabularies -- focus and tier
-- it offers with the selected option marked.

It exists because nothing else ties the two together: a rename in
``run_modes`` would otherwise look like a free local choice, and the
fidelity audit had already recorded the four tiers as a local extension
over a two-tier product (``B1``) on the strength of earlier captures.

The plan's own vocabulary is transcribed once, below, as cited module-level
constants, and every test in this module checks ``app.run_modes`` against
those constants directly -- so none of it touches disk and none of it can
skip. That is the half of the pin that must keep guarding once
``references/`` is gone.
``test_published_plan_config_corroboration.py`` re-reads the transcription
and asserts it still matches what is on disk; that module is the one
allowed to skip when the corpus is absent.
"""

from __future__ import annotations

from app.run_modes import RUN_FOCUS_VALUES, RUN_TIER_DEFAULTS, setup_config

# references/core/google-co-scientist/research/extracted-artifacts/outputs/
# plan-configs/mash-liver-fibrosis-reversal-research-plan.md -- 85 lines,
# sha256 d6b17ff762ea. Transcribed from the Gemini Enterprise live-footage
# capture of the product's own "Research plan" panel; each tuple is the
# section's offered options, in the order shown, with the selected one
# ignored -- the vocabulary is what is pinned, not which option that run
# chose.
_PLAN_TIER_OPTIONS = ("express", "standard", "extended", "ultra")
_PLAN_FOCUS_OPTIONS = (
    "prefer_evidence",
    "balance",
    "prefer_novelty",
    "breakthrough",
)
# The product's plan is the research goal plus five configured sections.
# "Goal" is the run's own research goal rather than a spec field, so only
# the other five are pinned.
_PLAN_CONFIGURED_SECTIONS = {
    "Requirements",
    "Attributes",
    "Criteria",
    "Focus",
    "Tier",
}
_PLAN_GOAL_SECTION = "Goal"


def test_run_tiers_are_the_ones_the_product_offers() -> None:
    """The four tiers, and their order, come from the product's own plan."""
    assert list(_PLAN_TIER_OPTIONS) == list(RUN_TIER_DEFAULTS)


def test_run_focus_values_are_the_ones_the_product_offers() -> None:
    """The four focus values, and their order, likewise."""
    assert list(_PLAN_FOCUS_OPTIONS) == list(RUN_FOCUS_VALUES)


def test_the_plan_carries_every_section_the_product_shows() -> None:
    """The run spec carries each configured section of the product's plan."""
    spec = setup_config(research_goal="pin check")
    spec_keys = {key.lower() for key in spec}
    configured = {section.lower() for section in _PLAN_CONFIGURED_SECTIONS}
    assert configured <= spec_keys
    assert _PLAN_GOAL_SECTION.lower() in spec_keys
