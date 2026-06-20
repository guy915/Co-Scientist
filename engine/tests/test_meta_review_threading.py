"""Tests for threading meta-review feedback and deep-verification into prompts.

These cover three canonical-fidelity behaviors:
- Meta-review feedback reaches the reflection and ranking prompts.
- The meta-review slot is a byte-clean no-op when empty (iteration-1 prompts
  and their cache keys stay unchanged).
- Deep-verification probes are consumed by the ranking prompt.
"""

from co_scientist.prompts import get_ranking_prompt
from co_scientist.prompts import get_reflection_prompt

_META = {
    "common_weaknesses": ["ignores blood-brain-barrier permeability"],
    "strategic_recommendations": ["address BBB"],
}

_PROBES = [{
    "question": "Is CXCR1/2 inhibition sufficient alone?",
    "answer": "Likely needs combination therapy.",
    "reasoning": "AML bypasses single-target inhibition.",
    "assumption_is_fundamental": True,
}]


def test_reflection_prompt_includes_meta_review_when_present() -> None:
    """The reflection prompt surfaces meta-review feedback when present."""
    prompt, _ = get_reflection_prompt(articles_with_reasoning="lit",
                                      hypothesis_text="H",
                                      meta_review=_META)
    assert "blood-brain-barrier" in prompt


def test_reflection_prompt_omits_meta_review_when_empty() -> None:
    """The reflection prompt omits meta-review feedback when absent."""
    prompt, _ = get_reflection_prompt(articles_with_reasoning="lit",
                                      hypothesis_text="H",
                                      meta_review=None)
    assert "blood-brain-barrier" not in prompt


def test_ranking_prompt_includes_meta_review_when_present() -> None:
    """The ranking prompt surfaces meta-review feedback when present."""
    prompt, _ = get_ranking_prompt(research_goal="g",
                                   hypothesis_a="A",
                                   hypothesis_b="B",
                                   meta_review=_META)
    assert "blood-brain-barrier" in prompt


def test_ranking_prompt_omits_meta_review_when_empty() -> None:
    """The ranking prompt has no meta-review section when feedback is absent."""
    prompt, _ = get_ranking_prompt(research_goal="g",
                                   hypothesis_a="A",
                                   hypothesis_b="B",
                                   meta_review=None)
    assert "Meta-Review Context" not in prompt


def test_ranking_prompt_empty_optional_slots_are_byte_clean() -> None:
    """Empty meta-review and deep-verification slots add no extra blank lines.

    With both optional slots empty the tail of the ranking prompt must keep
    its original single-blank-line spacing, so iteration-1 prompts (and their
    sha256 cache keys) are unchanged.
    """
    prompt, _ = get_ranking_prompt(research_goal="g",
                                   hypothesis_a="A",
                                   hypothesis_b="B",
                                   meta_review=None)
    assert "No reflection notes available.\n\n## Output Format" in prompt
    assert "\n\n\n## Output Format" not in prompt


def test_ranking_prompt_includes_deep_verification_when_present() -> None:
    """Deep-verification probes and verdict appear in the ranking prompt."""
    prompt, _ = get_ranking_prompt(research_goal="g",
                                   hypothesis_a="A",
                                   hypothesis_b="B",
                                   deep_verification_a={
                                       "probes": _PROBES,
                                       "verdict": "weakened",
                                   })
    assert "Deep Verification" in prompt
    assert "weakened" in prompt
    assert "Is CXCR1/2 inhibition sufficient alone?" in prompt
    assert "fundamental assumption" in prompt


def test_ranking_prompt_omits_deep_verification_when_empty() -> None:
    """The ranking prompt has no deep-verification section when none exists."""
    prompt, _ = get_ranking_prompt(research_goal="g",
                                   hypothesis_a="A",
                                   hypothesis_b="B")
    assert "Deep Verification" not in prompt
