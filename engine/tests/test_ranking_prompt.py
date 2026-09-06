"""Coverage-focused tests for ``co_scientist.agents.ranking.ranking_prompt``.

``test_ranking.py`` drives ``ranking_node`` end to end with plain
hypotheses (no reviews, no deep-verification probes, no reflection notes),
so several of this module's branches -- the "has data" paths of
``_review_summary``/``_deep_verification_summary``, the partial/full
coverage branches of ``_log_reflection_coverage``, the "has classification"
branch of ``_log_reflection_debug``, and both branches of
``_warn_if_reflection_notes_dropped`` -- never run. This file calls the
private helpers directly (matching the existing convention of testing
``reflection_helpers``'s private functions directly).

Both projections now delegate to ``Hypothesis.review_summary()``/
``Hypothesis.deep_verification_summary()`` (also covered directly in
``test_models.py``, since evolution reads the same methods without going
through this module); the local names here stay in place because
``ranking.py`` re-exports every ``ranking_prompt`` name for compatibility.
"""

import logging
import pathlib

import pytest

from co_scientist.agents.ranking.ranking_debate_turns import (
    _RANKING_DEBATE_MAX_TURNS,
    _RANKING_DEBATE_TYPICAL_MAX_TURNS,
    _RANKING_DEBATE_TYPICAL_MIN_TURNS,
)
from co_scientist.agents.ranking.ranking_prompt import (
    _build_matchup_prompt,
    _deep_verification_summary,
    _log_reflection_coverage,
    _log_reflection_debug,
    _MatchupPromptContext,
    _review_summary,
    _warn_if_reflection_notes_dropped,
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


# --- _deep_verification_summary ----------------------------------------------


def test_deep_verification_summary_none_when_no_probes() -> None:
    """A hypothesis with no deep-verification probes yields None."""
    hypothesis = make_hypothesis(
        text="a hypothesis", deep_verification_probes=[]
    )
    assert _deep_verification_summary(hypothesis) is None


def test_deep_verification_summary_returns_probes_and_verdict() -> None:
    """Populated probes/verdict are returned as a summary dict."""
    probes = [
        {
            "question": "does it hold under X?",
            "answer": "yes",
            "reasoning": "because Y",
            "assumption_is_fundamental": True,
        }
    ]
    hypothesis = make_hypothesis(
        text="a hypothesis",
        deep_verification_probes=probes,
        deep_verification_verdict="holds",
    )
    assert _deep_verification_summary(hypothesis) == {
        "probes": probes,
        "verdict": "holds",
    }


# --- _log_reflection_coverage -------------------------------------------


def test_log_reflection_coverage_none_have_reflection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When no hypothesis has reflection notes, the "none" warning fires."""
    hypotheses = [
        make_hypothesis(text="a", reflection_notes=None),
        make_hypothesis(text="b", reflection_notes=None),
    ]
    with caplog.at_level(
        logging.DEBUG, logger="co_scientist.agents.ranking.ranking_prompt"
    ):
        _log_reflection_coverage(hypotheses)
    assert "No hypotheses have reflection notes" in caplog.text


def test_log_reflection_coverage_some_have_reflection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A partial-coverage pool logs the "some missing" warning."""
    hypotheses = [
        make_hypothesis(text="a", reflection_notes="notes for a"),
        make_hypothesis(text="b", reflection_notes=None),
    ]
    with caplog.at_level(
        logging.DEBUG, logger="co_scientist.agents.ranking.ranking_prompt"
    ):
        _log_reflection_coverage(hypotheses)
    assert "Some hypotheses missing reflection notes" in caplog.text


def test_log_reflection_coverage_all_have_reflection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Full coverage logs the "all hypotheses" confirmation."""
    hypotheses = [
        make_hypothesis(text="a", reflection_notes="notes for a"),
        make_hypothesis(text="b", reflection_notes="notes for b"),
    ]
    with caplog.at_level(
        logging.DEBUG, logger="co_scientist.agents.ranking.ranking_prompt"
    ):
        _log_reflection_coverage(hypotheses)
    assert "all hypotheses have reflection notes" in caplog.text


# --- _log_reflection_debug ---------------------------------------------


def test_log_reflection_debug_missing_notes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Absent reflection notes log a "missing" message and return early."""
    with caplog.at_level(
        logging.DEBUG, logger="co_scientist.agents.ranking.ranking_prompt"
    ):
        _log_reflection_debug("A", None)
    assert "hypothesis A: missing reflection notes" in caplog.text


def test_log_reflection_debug_extracts_classification(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A "Classification:" marker is parsed out of the reflection notes."""
    notes = "Some analysis text.\nClassification: Novel\nMore text."
    with caplog.at_level(
        logging.DEBUG, logger="co_scientist.agents.ranking.ranking_prompt"
    ):
        _log_reflection_debug("B", notes)
    assert "classification: Novel" in caplog.text


def test_log_reflection_debug_no_classification_marker(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Notes without a "Classification:" marker default to "unknown"."""
    with caplog.at_level(
        logging.DEBUG, logger="co_scientist.agents.ranking.ranking_prompt"
    ):
        _log_reflection_debug("A", "plain reflection text, no marker")
    assert "classification: unknown" in caplog.text


# --- _warn_if_reflection_notes_dropped ---------------------------------


def test_warn_if_reflection_notes_dropped_neither_present_is_a_noop(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """With neither side's notes present, the function returns immediately."""
    with caplog.at_level(
        logging.DEBUG, logger="co_scientist.agents.ranking.ranking_prompt"
    ):
        _warn_if_reflection_notes_dropped("some prompt text", None, None)
    assert caplog.text == ""


def test_warn_if_reflection_notes_dropped_found_in_prompt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the section header made it into the prompt, logs confirmation."""
    prompt = "...\n## Reflection Notes\n...notes here..."
    with caplog.at_level(
        logging.DEBUG, logger="co_scientist.agents.ranking.ranking_prompt"
    ):
        _warn_if_reflection_notes_dropped(prompt, "notes for a", None)
    assert "prompt includes 'Reflection Notes' section" in caplog.text


def test_warn_if_reflection_notes_dropped_missing_from_prompt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the section header is absent, logs the regression warning.

    In the real template the "## Reflection Notes" header is static text
    that always renders, so this branch is unreachable via the normal
    _build_matchup_prompt call path; it is only reachable by calling this
    pure helper directly with a hand-built prompt string, as done here.
    """
    prompt = "a prompt with no reflection section at all"
    with caplog.at_level(
        logging.DEBUG, logger="co_scientist.agents.ranking.ranking_prompt"
    ):
        _warn_if_reflection_notes_dropped(prompt, None, "notes for b")
    assert (
        "warning: Reflection notes provided but not found in prompt"
        in caplog.text
    )


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
