"""Ranking prompt contracts for reviews, evidence, and judge framing."""

import pathlib

from co_scientist.agents.ranking.ranking_debate_turns import (
    _RANKING_DEBATE_MAX_TURNS,
    _RANKING_DEBATE_TYPICAL_MAX_TURNS,
    _RANKING_DEBATE_TYPICAL_MIN_TURNS,
    _build_matchup_prompt,
    _MatchupPromptContext,
    _review_summary,
)
from co_scientist.models import HypothesisReview
from tests._state import make_hypothesis

# --- _review_summary ---------------------------------------------------------


def test_review_summary_none_when_no_reviews() -> None:
    """A hypothesis with no reviews yields None."""
    hypothesis = make_hypothesis(text="a hypothesis", reviews=[])
    assert _review_summary(hypothesis) is None


def test_review_summary_returns_latest_scores_and_overall_score() -> None:
    """The most recent review's scores/overall_score are extracted."""
    review = HypothesisReview(
        review_summary="summary",
        scores={"novelty": 8, "rigor": 6},
        safety_ethical_concerns="none",
        detailed_feedback={},
        constructive_feedback="tighten the mechanism",
        overall_score=7.0,
    )
    hypothesis = make_hypothesis(text="a hypothesis", reviews=[review])
    assert _review_summary(hypothesis) == {
        "scores": {"novelty": 8, "rigor": 6},
        "overall_score": 7.0,
    }


# --- mature review findings (audit E1) ----------------------------------


def _matchup_context() -> _MatchupPromptContext:
    """Build the minimal run-level context a matchup prompt needs."""
    return _MatchupPromptContext(research_goal="test goal")


def _debate_matchup_context() -> _MatchupPromptContext:
    """The same context for a top-ranked, multi-turn (ranking-05) matchup."""
    return _MatchupPromptContext(research_goal="test goal", debate=True)


def test_matchup_prompt_surfaces_fatal_mature_review_findings() -> None:
    """A fatal full/simulation result reaches the judge's prompt (E1).

    The reviews were computed at LLM + retrieval cost but read by nothing
    before this; the verdict and its decisive findings must appear on the
    affected side so they can influence the outcome.
    """
    hypothesis_a = make_hypothesis(text="idea A")
    hypothesis_a.enrichments["full"] = {
        "verdict": "rejected",
        "justification": "the proposed pathway is circular",
        "retrieved_articles": [{"title": "never shown to a judge"}],
    }
    hypothesis_a.enrichments["simulation"] = {
        "verdict": "breaks_down",
        "decisive_step": "ligand binding never occurs",
        "failure_points": ["step two"],
    }
    hypothesis_b = make_hypothesis(text="idea B")

    prompt, _, _, _ = _build_matchup_prompt(
        hypothesis_a, hypothesis_b, _matchup_context()
    )

    assert "Hypothesis 1 Mature Review Findings" in prompt
    assert "Full review verdict: rejected" in prompt
    assert "the proposed pathway is circular" in prompt
    assert "Simulation review verdict: breaks_down" in prompt
    assert "ligand binding never occurs" in prompt
    # Side B has no mature reviews: no block, and no retrieval internals.
    assert "Hypothesis 2 Mature Review Findings" not in prompt
    assert "never shown to a judge" not in prompt


def test_matchup_prompt_is_unchanged_before_the_cascade_runs() -> None:
    """No mature reviews means no findings block on either side."""
    prompt, _, _, _ = _build_matchup_prompt(
        make_hypothesis(text="idea A"),
        make_hypothesis(text="idea B"),
        _matchup_context(),
    )

    assert "Mature Review Findings" not in prompt


# --- panel framing (corpus R8-6) ----------------------------------------


def test_matchup_prompt_frames_the_judge_as_a_panel() -> None:
    """The published ranking-05 "panel of domain experts" framing renders.

    Google's ranking-05 opens "simulating a panel of domain experts
    engaged in a structured discussion" (docs/CORPUS-EXTRACTION.md:1210)
    -- and that is ranking-05's opening, not ranking-04's. It belongs to
    the multi-turn debate prompt only; a single-shot comparison renders
    ranking-04, which names one expert evaluator.
    """
    prompt, _, _, _ = _build_matchup_prompt(
        make_hypothesis(text="idea A"),
        make_hypothesis(text="idea B"),
        _debate_matchup_context(),
    )

    assert "panel of domain experts" in prompt
    assert "structured discussion" in prompt


def test_single_shot_matchup_renders_the_published_single_evaluator() -> None:
    """A lower-ranked comparison gets ranking-04's own role, not A.5's."""
    prompt, _, _, _ = _build_matchup_prompt(
        make_hypothesis(text="idea A"),
        make_hypothesis(text="idea B"),
        _matchup_context(),
    )

    assert "You are an expert evaluator tasked with comparing two" in prompt
    assert "panel of domain experts" not in prompt


def test_panel_framing_does_not_dislodge_the_decisive_verdict_instruction() -> (
    None
):
    """Adding the panel framing must not soften the required verdict line.

    Ranking is the run's most expensive call site and already carries a
    measured ~23% answerless-retry rate on this prompt family (corpus
    R8-4); the panel framing must not read as an invitation to keep
    deliberating instead of committing to a verdict.
    """
    prompt, _, _, _ = _build_matchup_prompt(
        make_hypothesis(text="idea A"),
        make_hypothesis(text="idea B"),
        _debate_matchup_context(),
    )

    assert "Make a clear decision" in prompt
    assert '"better idea: 1"' in prompt and '"better idea: 2"' in prompt
    # Every turn answers, turn 1 included: the published prompt defers
    # its judgment to termination, but each of our turns is its own call.
    assert "answer every turn - turn 1 included" in prompt


# --- the debate template's own turn envelope ----------------------------

_TEMPLATES = (
    pathlib.Path(__file__).resolve().parents[1]
    / "src"
    / "co_scientist"
    / "prompts"
    / "templates"
)


def test_debate_template_states_the_envelope_the_loop_enforces() -> None:
    """ranking_debate.md prints the turn envelope the judge loop applies.

    Published ranking-05 carries the numbers as literals, so they are
    literals in the template; this is what keeps them from drifting from
    the constants ``_ranking_debate_consensus`` and
    ``_matchup_debate_turns`` actually enforce. The panel paces itself
    against whatever number it is told, so a stale figure reads as a real
    instruction.
    """
    template = (_TEMPLATES / "ranking_debate.md").read_text(encoding="utf-8")

    assert (
        "typically ranging from"
        f" {_RANKING_DEBATE_TYPICAL_MIN_TURNS} to"
        f" {_RANKING_DEBATE_TYPICAL_MAX_TURNS}, with a maximum of"
        f" {_RANKING_DEBATE_MAX_TURNS}." in template
    )
    assert (
        f"(typically {_RANKING_DEBATE_TYPICAL_MIN_TURNS}"
        f"-{_RANKING_DEBATE_TYPICAL_MAX_TURNS} turns, up to"
        f" {_RANKING_DEBATE_MAX_TURNS} turns)" in template
    )


def test_matchup_prompt_keeps_reflection_and_verification() -> None:
    hypothesis_a = make_hypothesis(
        text="idea A",
        reflection_notes="Measured flux from pathway A.",
        deep_verification_probes=[
            {
                "question": "Does the flux persist?",
                "answer": "Yes, under the measured condition.",
                "reasoning": "The control confirms it.",
                "assumption_is_fundamental": True,
            }
        ],
        deep_verification_verdict="holds",
    )
    hypothesis_b = make_hypothesis(text="idea B")
    prompt, _, notes_a, notes_b = _build_matchup_prompt(
        hypothesis_a, hypothesis_b, _matchup_context()
    )
    assert "Measured flux from pathway A." in prompt
    assert "Does the flux persist?" in prompt
    assert "Yes, under the measured condition." in prompt
    assert notes_a == hypothesis_a.reflection_notes
    assert notes_b is None
