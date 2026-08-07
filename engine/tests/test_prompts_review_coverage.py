"""Which prompts see the meta-review's coverage sections, and which do not.

The "areas already covered" and "open directions" blocks reach most
prompts by default but are deliberately withheld from the two review
scoring prompts. Split out of ``test_prompts_review.py`` to keep that
module within the file-length ceiling.
"""

from __future__ import annotations

from co_scientist.prompts import (
    PromptRunContext,
    RankingSide,
    get_ranking_prompt,
    get_review_batch_prompt,
    get_review_prompt,
)

_COVERAGE_META_REVIEW = {
    "common_strengths": ["clear mechanism"],
    "common_weaknesses": ["weak controls"],
    "emerging_themes": ["UNIQUEMARKER-already-covered-kinase-inhibition"],
    "strategic_recommendations": ["broaden the cohort"],
    "potential_connections": [
        {
            "connection_type": "complementary_mechanism",
            "synthesis_opportunity": (
                "UNIQUEMARKER-open-direction-combine-autophagy-proteasome"
            ),
        }
    ],
}


def test_review_prompt_omits_coverage_sections() -> None:
    """The scored review prompt excludes the two novelty-adjacent sections.

    Deliberate scoping (see ``_format_meta_review_context``'s docstring):
    this prompt's score feeds the sticky, never-revisited initial review
    gate on its ``novelty`` axis, and "this area is already covered" /
    "this direction is open" read as direct novelty cues. The pre-
    existing strengths/weaknesses/recommendations sections are unaffected.
    """
    prompt, _ = get_review_prompt(
        research_goal="g",
        hypothesis_text="h",
        context=PromptRunContext(meta_review=_COVERAGE_META_REVIEW),
    )
    assert "Meta-Review Context" in prompt
    assert "clear mechanism" in prompt
    assert "weak controls" in prompt
    assert "broaden the cohort" in prompt
    assert "Research Areas Already Covered" not in prompt
    assert "Open Directions Flagged for Further Exploration" not in prompt
    assert "UNIQUEMARKER-already-covered-kinase-inhibition" not in prompt
    assert "UNIQUEMARKER-open-direction-combine-autophagy-proteasome" not in (
        prompt
    )


def test_review_batch_prompt_omits_coverage_sections() -> None:
    """The comparative batch review prompt excludes the same two sections."""
    prompt, _ = get_review_batch_prompt(
        research_goal="reduce tumor metastasis",
        hypotheses_list="1. block CXCR4\n2. inhibit MMP-9",
        context=PromptRunContext(meta_review=_COVERAGE_META_REVIEW),
    )
    assert "Meta-Review Context" in prompt
    assert "broaden the cohort" in prompt
    assert "Research Areas Already Covered" not in prompt
    assert "Open Directions Flagged for Further Exploration" not in prompt
    assert "UNIQUEMARKER-already-covered-kinase-inhibition" not in prompt
    assert "UNIQUEMARKER-open-direction-combine-autophagy-proteasome" not in (
        prompt
    )


def test_ranking_prompt_keeps_coverage_sections() -> None:
    """Contrast: the tournament judge keeps both sections by default.

    It is a reversible Elo signal, not a gate.
    """
    prompt, _ = get_ranking_prompt(
        research_goal="g",
        side_a=RankingSide(text="A"),
        side_b=RankingSide(text="B"),
        context=PromptRunContext(meta_review=_COVERAGE_META_REVIEW),
    )
    assert "UNIQUEMARKER-already-covered-kinase-inhibition" in prompt
    assert "UNIQUEMARKER-open-direction-combine-autophagy-proteasome" in prompt
