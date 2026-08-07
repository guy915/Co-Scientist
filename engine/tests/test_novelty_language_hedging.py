"""K3: novelty language must stay hedged on the real generation path.

Covers the non-tool-calling generation, review, and ranking prompts.
Novelty verification against a broad literature corpus
(``literature_tools/validate_novelty.py``) only runs on the tool-calling
generation path, which the app never enables for a real run (see
``app/app/engine_adapter/opts.py``). The prompts on the path every real run
actually executes must therefore never invite the model to assert a
hypothesis is unprecedented, the first of its kind, or that no prior work
exists -- these tests pin the hedging instruction added to each of those
prompts.
"""

from co_scientist.prompts import (
    DebatePromptRequest,
    RankingSide,
    get_debate_generation_prompt,
    get_ranking_prompt,
    get_review_batch_prompt,
    get_review_prompt,
)

_HEDGE_MARKERS = ("unprecedented", "first of its kind")


def _assert_hedged(prompt: str) -> None:
    for marker in _HEDGE_MARKERS:
        assert marker in prompt, f"missing hedge marker: {marker!r}"


def test_generation_after_debate_hedges_novelty_with_no_literature() -> None:
    """The no-literature debate-generation template hedges unconditionally."""
    prompt, _ = get_debate_generation_prompt(
        DebatePromptRequest(
            research_goal="design a self-healing polymer",
            hypotheses_count=3,
            transcript="",
            is_final_turn=False,
            articles_with_reasoning=None,
        )
    )
    _assert_hedged(prompt)
    # No literature is available on this branch, so the hedge must not
    # invite citing retrieval keys that do not exist here.
    assert "[C*]" not in prompt


def test_generation_debate_and_literature_hedges_novelty() -> None:
    """The literature-aware debate-generation template hedges novelty."""
    prompt, _ = get_debate_generation_prompt(
        DebatePromptRequest(
            research_goal="design a self-healing polymer",
            hypotheses_count=3,
            transcript="",
            is_final_turn=False,
            articles_with_reasoning="Paper A found X [C1].",
        )
    )
    _assert_hedged(prompt)


def test_review_prompt_hedges_novelty_free_text() -> None:
    """The single-hypothesis review prompt hedges its novelty free text."""
    prompt, _ = get_review_prompt(
        research_goal="design a self-healing polymer",
        hypothesis_text="Polymer X self-heals via reversible bonds.",
    )
    _assert_hedged(prompt)
    # The numeric gate calibration must be untouched by the hedge.
    assert "1-3" in prompt
    assert "already established/non-novel" in prompt


def test_review_batch_prompt_hedges_novelty_free_text() -> None:
    """The comparative batch review prompt hedges its novelty free text."""
    prompt, _ = get_review_batch_prompt(
        research_goal="design a self-healing polymer",
        hypotheses_list="1. Polymer X self-heals via reversible bonds.",
    )
    _assert_hedged(prompt)
    assert "1-3" in prompt
    assert "already established/non-novel" in prompt


def test_ranking_prompt_hedges_novelty_comparison() -> None:
    """The tournament comparison prompt hedges its novelty_comparison field."""
    prompt, _ = get_ranking_prompt(
        research_goal="design a self-healing polymer",
        side_a=RankingSide(text="Hypothesis A text."),
        side_b=RankingSide(text="Hypothesis B text."),
    )
    _assert_hedged(prompt)
