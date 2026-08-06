"""The paper's judge protocol: literal verdict line + collected criteria.

Finding E17: the ranking verdict was a JSON enum rather than the paper's
literal ``better idea: <1 or 2>`` concluding line, and the seven
comparison criteria the prompt collects were never parsed onto the match
record. These tests pin the fix:

- the literal verdict line concluding ``decision_summary`` is the
  primary verdict (case variants accepted; the paper's own
  "better hypothesis" wording too); the JSON ``winner`` enum remains the
  fallback when the line is absent, which is how the deterministic
  offline backend answers;
- the seven criterion assessments ride on the matchup detail under
  ``criteria_comparisons``.
"""

from typing import Any

import pytest

from co_scientist.agents.ranking import ranking_debate
from co_scientist.agents.ranking.ranking_debate import (
    _DebateContext,
    judge_matchup,
)
from co_scientist.agents.ranking.ranking_debate_turns import (
    _parse_matchup_winner,
    _parse_verdict_line,
    _resolve_turn_winner,
)
from co_scientist.agents.ranking.ranking_results import (
    _build_matchup_detail,
    _extract_criteria_comparisons,
)
from co_scientist.schemas.ranking import (
    RANKING_COMPARISON_CRITERIA,
    RANKING_SCHEMA,
)
from tests._state import make_hypothesis


def _judgment(summary: str = "", winner: str = "a") -> dict[str, Any]:
    """Build a judge response with a decision_summary and a JSON winner."""
    return {"decision_summary": summary, "winner": winner}


# --- verdict-line parsing -------------------------------------------------


def test_verdict_line_maps_the_papers_numbers_onto_sides() -> None:
    """Hypothesis 1 as presented is side a; Hypothesis 2 is side b."""
    assert _parse_verdict_line("... better idea: 1") == "a"
    assert _parse_verdict_line("... better idea: 2") == "b"


def test_verdict_line_accepts_case_and_wording_variants() -> None:
    """Case variants and the paper's alternate wording all parse."""
    assert _parse_verdict_line("Better Idea: 1") == "a"
    assert _parse_verdict_line("BETTER IDEA:2") == "b"
    assert _parse_verdict_line("better hypothesis: 2") == "b"
    assert _parse_verdict_line("better idea: A") == "a"


def test_the_concluding_verdict_wins_over_an_earlier_quote() -> None:
    """A rationale may quote the format before concluding with a verdict."""
    text = (
        "End with better idea: 1 or 2. After weighing both sides,"
        " the stronger mechanism prevails.\n\nbetter idea: 2"
    )
    assert _parse_verdict_line(text) == "b"


def test_a_quoted_format_is_not_a_verdict() -> None:
    """A quote of the protocol format ("1 or 2") decides nothing."""
    assert _parse_verdict_line("conclude with better idea: 1 or 2") is None
    assert _parse_verdict_line("") is None
    assert _parse_verdict_line("no verdict here") is None


def test_an_invalid_verdict_token_yields_no_verdict() -> None:
    """Anything but 1/2/a/b is not a decision."""
    assert _parse_verdict_line("better idea: 3") is None
    assert _parse_verdict_line("better idea: both") is None


def test_verdict_line_takes_precedence_over_the_json_winner() -> None:
    """The paper's concluding line outranks the JSON enum when both exist."""
    winner, valid = _parse_matchup_winner(
        _judgment(summary="rationale.\nbetter idea: 2", winner="a"),
        fallback="a",
    )
    assert winner == "b"
    assert valid is True


def test_json_winner_fallback_when_no_verdict_line() -> None:
    """The offline backend answers in the JSON shape; nothing breaks.

    A response with no literal line resolves through the enum exactly as
    before -- this is the deterministic offline path's contract.
    """
    winner, valid = _parse_matchup_winner(
        _judgment(summary="plain rationale", winner="b"), fallback="a"
    )
    assert winner == "b"
    assert valid is True


def test_neither_verdict_nor_valid_winner_uses_the_fallback() -> None:
    winner, valid = _parse_matchup_winner(
        _judgment(summary="", winner=""), fallback="b"
    )
    assert winner == "b"
    assert valid is False


def test_verdict_unswaps_with_presentation_order() -> None:
    """On a swapped turn, side 1 as presented is the B hypothesis.

    The verdict names the hypotheses in presentation order, so a
    "better idea: 1" on a swapped turn votes for the unswapped side b.
    """
    winner, valid = _resolve_turn_winner(
        _judgment(summary="better idea: 1", winner="a"),
        swapped=True,
        fallback="a",
    )
    assert winner == "b"
    assert valid is True


async def test_judge_matchup_parses_the_literal_verdict_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end: the concluding line decides the matchup."""

    async def fake(**_: Any) -> dict[str, Any]:
        return {
            "winner": "a",  # contradicted by the literal line below
            "decision_summary": "B is stronger.\nbetter idea: 2",
            "confidence_level": "High",
        }

    monkeypatch.setattr(ranking_debate, "call_llm_json", fake)
    ctx = _DebateContext(
        make_hypothesis(text="alpha"),
        make_hypothesis(text="beta"),
        "goal",
        "fake/model",
    )

    winner, response = await judge_matchup(ctx, debate_turns=1)

    assert winner == "b"
    assert response["consensus_votes"] == ["b"]


# --- criteria collection --------------------------------------------------


def _full_explanation() -> dict[str, str]:
    """One assessment per canonical criterion, plus an invented key."""
    return {
        **{name: f"assesses {name}" for name in RANKING_COMPARISON_CRITERIA},
        "invented_extra_comparison": "not in the closed schema",
    }


def test_criteria_comparisons_collect_all_seven_canonical_axes() -> None:
    response = {"judgment_explanation": _full_explanation()}
    comparisons = _extract_criteria_comparisons(response)
    assert set(comparisons) == set(RANKING_COMPARISON_CRITERIA)
    assert comparisons["novelty_comparison"] == "assesses novelty_comparison"


def test_invented_and_empty_criteria_are_dropped() -> None:
    explanation = _full_explanation()
    explanation["feasibility_comparison"] = ""
    comparisons = _extract_criteria_comparisons(
        {"judgment_explanation": explanation}
    )
    assert "invented_extra_comparison" not in comparisons
    assert "feasibility_comparison" not in comparisons


def test_criteria_comparisons_empty_without_an_explanation() -> None:
    assert _extract_criteria_comparisons({}) == {}
    assert (
        _extract_criteria_comparisons({"judgment_explanation": "prose"}) == {}
    )


def test_matchup_detail_carries_the_criteria_comparisons() -> None:
    """The persisted match record is inspectable criterion by criterion."""
    from co_scientist.agents.ranking.ranking_results import (
        _apply_matchup_elo,
    )

    hyp_a = make_hypothesis(text="alpha")
    hyp_b = make_hypothesis(text="beta")
    outcome = _apply_matchup_elo(hyp_a, hyp_b, "a")

    detail = _build_matchup_detail(
        hyp_a,
        hyp_b,
        "a",
        {"judgment_explanation": _full_explanation()},
        outcome,
    )

    assert set(detail["criteria_comparisons"]) == set(
        RANKING_COMPARISON_CRITERIA
    )


def test_ranking_schema_criteria_are_single_sourced() -> None:
    """The schema's judgment keys are exactly the canonical seven."""
    explanation = RANKING_SCHEMA["schema"]["properties"]["judgment_explanation"]
    assert set(explanation["properties"]) == set(RANKING_COMPARISON_CRITERIA)
    assert set(explanation["required"]) == set(RANKING_COMPARISON_CRITERIA)
