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

import pytest

from co_scientist.agents.ranking.ranking_prompt import (
    _deep_verification_summary,
    _log_reflection_coverage,
    _log_reflection_debug,
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
