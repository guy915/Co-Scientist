"""Offline contracts for ranking operations."""

from __future__ import annotations

import pathlib
from dataclasses import FrozenInstanceError
from typing import Any

import pytest

import co_scientist.agents.ranking.ranking_debate as ranking_elo
from co_scientist.agents.ranking import (
    RankingJudgement,
    RankingMatchResult,
    TournamentGuidance,
    apply_ranking_matchup,
    build_tournament_pairings,
    finalize_ranking,
    judge_ranking_matchup,
    prepare_ranking_judging_context,
    prepare_ranking_prompt_context,
    prepare_ranking_round,
    ranking_debate,
    remaining_ranking_rounds,
)
from co_scientist.agents.ranking.ranking_debate import (
    _RANKING_DEBATE_MAX_TURNS,
    _RANKING_DEBATE_TYPICAL_MAX_TURNS,
    _RANKING_DEBATE_TYPICAL_MIN_TURNS,
    _build_matchup_detail,
    _build_matchup_prompt,
    _DebateContext,
    _extract_criteria_comparisons,
    _MatchupPromptContext,
    _parse_matchup_winner,
    _parse_verdict_line,
    _resolve_turn_winner,
    _review_summary,
    judge_matchup,
)
from co_scientist.constants import INITIAL_ELO_RATING
from co_scientist.models import ExecutionMetrics, HypothesisReview
from co_scientist.schemas.review import (
    RANKING_COMPARISON_CRITERIA,
    RANKING_SCHEMA,
)
from tests._state import make_hypothesis, make_review, make_state


def test_pairings_are_deterministic_and_exclude_judged_pairs() -> None:
    pool = [make_hypothesis(id=str(i), text=f"idea {i}") for i in range(5)]
    excluded = {frozenset({"0", "1"}), frozenset({"2", "3"})}
    first = build_tournament_pairings(pool, 10, "goal", 17, excluded)
    assert first == build_tournament_pairings(pool, 10, "goal", 17, excluded)
    identities = [frozenset({a.id, b.id}) for a, b in first]
    assert len(identities) == len(set(identities)) == 8
    assert not excluded.intersection(identities)


@pytest.mark.asyncio
async def test_prepare_admits_sorts_and_emits_progress() -> None:
    low = make_hypothesis(text="low", score=2, elo_rating=0)
    high = make_hypothesis(text="high", score=9, elo_rating=0)
    pool = [low, high]
    events: list[Any] = []

    async def progress(event: str, payload: dict[str, Any]) -> None:
        events.append((event, payload))

    state = make_state(
        hypotheses=pool,
        progress_callback=progress,
        supervisor_guidance={"strategy": "test"},
        run_focus_guidance="focus",
    )
    rounds, guidance = await prepare_ranking_round(state, pool)
    assert pool == [high, low]
    assert low.elo_rating == high.elo_rating == INITIAL_ELO_RATING
    assert rounds == remaining_ranking_rounds(state, pool)
    assert guidance.supervisor_guidance == {"strategy": "test"}
    assert tuple(guidance) == ({"strategy": "test"}, None, {}, None, "focus")
    assert isinstance(guidance, TournamentGuidance)
    assert events[0][0] == "tournament_start"


def test_remaining_budget_funds_only_peer_reviewed_coverage() -> None:
    pool = [make_hypothesis(reviews=[make_review()]) for _ in range(3)]
    state = make_state(
        hypotheses=pool, metrics=ExecutionMetrics(tournaments_count=100)
    )
    assert remaining_ranking_rounds(state, pool) == 3
    for hypothesis in pool:
        hypothesis.reviews = []
    assert remaining_ranking_rounds(state, pool) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("preferences", [None, "scientist preferences"])
async def test_judging_keeps_criteria_and_explicit_preferences(
    monkeypatch: pytest.MonkeyPatch,
    preferences: str | None,
) -> None:
    from co_scientist.agents.ranking import operations

    pair = (make_hypothesis(), make_hypothesis())
    state = make_state(
        preferences="scientist preferences",
        criteria=["feasibility"],
        run_setup_guidance="setup",
        run_focus_guidance="focus",
    )
    captured: list[Any] = []

    async def judge(ctx: Any, debate_turns: int) -> tuple[str, dict[str, Any]]:
        captured.append(ctx)
        return "b", {"debate_turns": 2, "judge_model": "test"}

    monkeypatch.setattr(operations, "judge_matchup", judge)
    prompt = prepare_ranking_prompt_context(state, preferences=preferences)
    context = prepare_ranking_judging_context(prompt, list(pair))
    judgement = await judge_ranking_matchup(pair, context, 7)
    assert captured[0].criteria == ["feasibility"]
    assert captured[0].preferences == preferences
    assert captured[0].run_setup_guidance == "setup"
    assert captured[0].run_focus_guidance == "focus"
    assert captured[0].matchup_index == 7
    assert judgement.budgeted_turns == 10
    result = apply_ranking_matchup(
        pair, judgement, k_factor=24, current_iteration=3
    )
    assert result.llm_calls == 2
    assert result.detail["iteration"] == 3
    assert result.detail["judge_model"] == "test"
    for value, field, replacement in [
        (prompt, "preferences", "changed"),
        (context, "median_elo", 0),
        (judgement, "winner", "a"),
        (result, "llm_calls", 99),
    ]:
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, replacement)
    assert isinstance(result, RankingMatchResult)


@pytest.mark.asyncio
async def test_public_judge_meters_real_early_consensus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    async def completion(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(1)
        winner = "a" if len(calls) % 2 else "b"
        return {"winner": winner, "decision_summary": "same winner"}

    monkeypatch.setattr(ranking_debate, "call_llm_json", completion)
    pair = (make_hypothesis(text="a"), make_hypothesis(text="b"))
    prompt = prepare_ranking_prompt_context(make_state())
    context = prepare_ranking_judging_context(prompt, list(pair))
    judgement = await judge_ranking_matchup(pair, context, 0)
    result = apply_ranking_matchup(
        pair, judgement, k_factor=24, current_iteration=0
    )
    assert judgement.budgeted_turns == 10
    assert judgement.winner == "a"
    assert result.llm_calls == len(calls) < judgement.budgeted_turns


def test_apply_preserves_confidence_knobs_and_budget_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ranking_elo, "ELO_MARGIN_VICTORY_SCALE", 1.0)
    pair = (make_hypothesis(), make_hypothesis())
    judgement = RankingJudgement("a", {"confidence_level": "High"}, 10)
    result = apply_ranking_matchup(
        pair, judgement, k_factor=24, current_iteration=4
    )
    assert result.llm_calls == 10
    assert pair[0].elo_rating == 1224
    assert pair[1].elo_rating == 1176
    assert result.detail["confidence"] == "High"
    assert result.detail["winner_elo_before"] == 1200


@pytest.mark.asyncio
async def test_finalize_orders_bands_and_charges_judged_matches() -> None:
    low = make_hypothesis(text="low", elo_rating=1100)
    top = make_hypothesis(text="top", elo_rating=1400)
    blocked = make_hypothesis(
        text="blocked", elo_rating=1800, review_disposition="inaccurate"
    )
    update = await finalize_ranking(
        make_state(), [low, blocked, top], [{"winner": "a"}], 12, 3
    )
    assert update["hypotheses"] == [top, low, blocked]
    assert update["metrics"].tournaments_count == 1
    assert update["metrics"].llm_calls == 3


@pytest.mark.asyncio
async def test_graph_captures_prompt_once_and_refreshes_sorted_pool_each_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist.agents.ranking import operations, ranking

    pool = [make_hypothesis(id=str(i), text=str(i), score=i) for i in range(3)]
    a, b, c = pool
    pairs = [(a, b), (b, c), (a, c)]
    snapshots: list[Any] = []
    captured: list[Any] = []
    prompts: list[Any] = []
    median = ranking_debate._median_elo
    prepare = prepare_ranking_prompt_context

    def record_median(hypotheses: list[Any]) -> float:
        snapshots.append([(h.id, h.elo_rating) for h in hypotheses])
        return median(hypotheses)

    def record_prompt(*args: Any, **kwargs: Any) -> Any:
        prompts.append(1)
        return prepare(*args, **kwargs)

    async def judge(ctx: Any, debate_turns: int) -> tuple[str, dict[str, Any]]:
        captured.append(ctx)
        return "a", {"debate_turns": 1}

    monkeypatch.setattr(operations, "_median_elo", record_median)
    monkeypatch.setattr(operations, "judge_matchup", judge)
    monkeypatch.setattr(
        ranking, "prepare_ranking_prompt_context", record_prompt
    )
    monkeypatch.setattr(
        ranking,
        "build_tournament_pairings",
        lambda *args, **kwargs: [pairs.pop(0)] if pairs else [],
    )
    state = make_state(
        hypotheses=pool, criteria=["feasible"], preferences="preferences"
    )
    await ranking.ranking_node(state)
    assert len(prompts) == 1
    assert len(snapshots) == 3
    assert all(
        [item[0] for item in snapshot] == ["2", "1", "0"]
        for snapshot in snapshots
    )
    assert snapshots[0] != snapshots[1] != snapshots[2]
    assert [ctx.preferences for ctx in captured] == ["preferences"] * 3
    assert [ctx.criteria for ctx in captured] == [["feasible"]] * 3


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
    from co_scientist.agents.ranking.ranking_debate import _apply_matchup_elo

    hyp_a = make_hypothesis(text="alpha")
    hyp_b = make_hypothesis(text="beta")
    outcome = _apply_matchup_elo(hyp_a, hyp_b, "a")

    detail = _build_matchup_detail(
        (hyp_a, hyp_b),
        "a",
        {"judgment_explanation": _full_explanation()},
        outcome,
        0,
    )

    assert set(detail["criteria_comparisons"]) == set(
        RANKING_COMPARISON_CRITERIA
    )


def test_ranking_schema_criteria_are_single_sourced() -> None:
    """The schema's judgment keys are exactly the canonical seven."""
    explanation = RANKING_SCHEMA["schema"]["properties"]["judgment_explanation"]
    assert set(explanation["properties"]) == set(RANKING_COMPARISON_CRITERIA)
    assert set(explanation["required"]) == set(RANKING_COMPARISON_CRITERIA)
