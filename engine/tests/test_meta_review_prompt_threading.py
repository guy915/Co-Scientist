"""Regression tests: meta-review critique reaches every relevant prompt.

Paper invariant (SSR §4, §12): the Meta-review critique is appended to every
other agent's prompt in the next iteration — the mechanism by which the system
learns without back-propagation. These prompt-rendering regression tests
prove the critique text actually appears in each rendered prompt: they render
the Generation, Reflection, and Review prompts with a
distinctive critique and assert it is present.
"""

from co_scientist.prompts import (
    DebatePromptRequest,
    PromptRunContext,
    get_debate_generation_prompt,
    get_reflection_prompt,
    get_review_batch_prompt,
    get_review_prompt,
)

# Distinctive markers unlikely to appear in a template by accident.
_STRENGTH = "UNIQUEMARKER-strength-mitochondrial-coupling"
_WEAKNESS = "UNIQUEMARKER-weakness-blood-brain-barrier-permeability"
_RECOMMENDATION = "UNIQUEMARKER-recommendation-add-orthogonal-probe"

_META_REVIEW = {
    "common_strengths": [_STRENGTH],
    "common_weaknesses": [_WEAKNESS],
    "strategic_recommendations": [_RECOMMENDATION],
}


def _assert_critique_present(prompt: str) -> None:
    """Assert the meta-review context section and its critique text render."""
    assert "Meta-Review Context" in prompt
    assert _WEAKNESS in prompt
    assert _STRENGTH in prompt
    assert _RECOMMENDATION in prompt


def test_generation_debate_prompt_includes_meta_review() -> None:
    """The Generation (debate) prompt carries the meta-review critique."""
    prompt, _ = get_debate_generation_prompt(
        DebatePromptRequest(
            research_goal="Find a synthetic-lethal target",
            transcript="",
            context=PromptRunContext(meta_review=_META_REVIEW),
        )
    )
    _assert_critique_present(prompt)


def test_reflection_prompt_includes_meta_review() -> None:
    """The Reflection prompt carries the meta-review critique."""
    prompt, _ = get_reflection_prompt(
        articles_with_reasoning="Some prior work.",
        hypothesis_text="Inhibiting X reduces Y.",
        context=PromptRunContext(meta_review=_META_REVIEW),
    )
    _assert_critique_present(prompt)


def test_review_prompt_includes_meta_review() -> None:
    """The Review prompt carries the meta-review critique."""
    prompt, _ = get_review_prompt(
        research_goal="Find a synthetic-lethal target",
        hypothesis_text="Inhibiting X reduces Y.",
        context=PromptRunContext(meta_review=_META_REVIEW),
    )
    _assert_critique_present(prompt)


def test_review_batch_prompt_includes_meta_review() -> None:
    """The comparative batch-review prompt carries the meta-review critique."""
    prompt, _ = get_review_batch_prompt(
        research_goal="Find a synthetic-lethal target",
        hypotheses_list="1. Inhibiting X reduces Y.\n2. Blocking Z helps.",
        context=PromptRunContext(meta_review=_META_REVIEW),
    )
    _assert_critique_present(prompt)


def test_empty_meta_review_adds_no_context_section() -> None:
    """With no meta-review, no critique section is injected (no-op)."""
    prompt, _ = get_review_prompt(
        research_goal="Find a synthetic-lethal target",
        hypothesis_text="Inhibiting X reduces Y.",
        context=PromptRunContext(meta_review=None),
    )
    assert "Meta-Review Context" not in prompt
