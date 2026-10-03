"""Tournament-match persistence in the final-state drain.

Covers ``engine_adapter.drain.matches``: the columns a judged matchup
carries into its ``matches`` row. Id resolution and the unresolved-side
skip live in ``test_engine_drain.py``; this module holds the cycle the
match was judged in, which the drain used to discard.
"""

from __future__ import annotations

import json
from typing import Any

from co_scientist.agents.ranking.ranking_debate_turns import (
    _DebateRun,
    _finalize_debate_response,
    _MatchupPrompt,
)
from co_scientist.agents.ranking.ranking_results import (
    _debate_provenance_fields,
)

from app import store
from app.engine_adapter.drain.matches import _persist_engine_matches
from app.report import markdown as report_markdown
from tests._drain_helpers import _final_state_with_features, _persist


def test_persist_match_records_the_iteration_it_was_judged_in(
    isolated_db: str,
) -> None:
    """The matchup's own iteration reaches the row, not a hardcoded zero.

    The drain wrote ``iteration=0`` for every match on every run. Production
    extended run bc77950f judged its 23 matches across three iterations and
    stored all of them as iteration 0, so the persisted Elo history could
    not be read back by cycle.
    """
    state = _final_state_with_features()
    state["tournament_matchups"][0]["iteration"] = 2
    run = store.create_run("CSC goal", "standard", "engine", {})

    _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    matches = store.list_matches(run.id, db_path=isolated_db)
    assert [match["iteration"] for match in matches] == [2]


def test_persist_match_without_an_iteration_falls_back_to_zero(
    isolated_db: str,
) -> None:
    """A matchup judged before the field existed still persists.

    Checkpoints written by an earlier build carry no ``iteration`` on their
    matchups, and a resumed run drains them alongside newly judged ones.
    """
    state = _final_state_with_features()
    state["tournament_matchups"][0].pop("iteration", None)
    run = store.create_run("CSC goal", "standard", "engine", {})

    _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    matches = store.list_matches(run.id, db_path=isolated_db)
    assert [match["iteration"] for match in matches] == [0]


def _judged_matchup() -> dict[str, Any]:
    """A matchup detail as the ranking node emits it after a real debate."""
    transcript = [
        {
            "turn": 1,
            "winner": "b",
            "winner_id": "e-b",
            "reasoning": ("Idea 2 names a measurable target. better idea: 2"),
            "presentation_order": "ab",
            "valid_output": True,
        },
        {
            "turn": 2,
            "winner": "b",
            "winner_id": "e-b",
            "reasoning": (
                "Presented the other way round it still holds. Better idea: 1"
            ),
            "presentation_order": "ba",
            "valid_output": True,
        },
    ]
    response: dict[str, Any] = {"decision_summary": "Idea 2 wins."}
    run = _DebateRun(
        base=_MatchupPrompt("", None, None, None),
        transcript=transcript,
        fallback="a",
        start_parity=0,
    )
    winner = _finalize_debate_response(response, ["b", "b"], run, "model")
    return {
        "hypothesis_a_id": "e-a",
        "hypothesis_b_id": "e-b",
        "winner_id": "e-b",
        "reasoning": "Idea 2 wins.",
        **_debate_provenance_fields(response, winner),
    }


def test_a_judged_debate_reaches_the_report(isolated_db: str) -> None:
    """The turns survive persistence and render in the published shape.

    Turn 2 was judged with the ideas presented in reverse, so its own
    trailing "Better idea: 1" names the same idea turn 1 called 2. The
    stored document keeps one verdict for the match and neither turn's
    contradictory line.
    """
    run = store.create_run("cardiac fibrosis goal", "express", "engine", {})
    with store.transaction(isolated_db) as conn:
        _persist_engine_matches(
            run.id,
            [_judged_matchup()],
            {"e-a": "h1", "e-b": "h2"},
            conn,
        )

    [row] = store.list_matches(run.id, db_path=isolated_db)
    document = json.loads(row["debate_transcript"])
    assert document["verdict"] == "2"
    assert [turn["favored"] for turn in document["turns"]] == ["2", "2"]
    assert document["turns"][0]["text"] == "Idea 2 names a measurable target."
    assert document["turns"][1]["text"].endswith("it still holds.")

    markdown = report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="cardiac fibrosis goal",
            provider="engine",
            top_hypotheses=[{"id": "h2", "title": "Empagliflozin"}],
            matches=store.list_matches(run.id, db_path=isolated_db),
            hypothesis_title_by_id={"h1": "NHE1 screen", "h2": "Empagliflozin"},
        )
    )

    assert "## Tournament debates" in markdown
    assert "### Debate 1: 1. NHE1 screen vs 2. Empagliflozin" in markdown
    assert (
        '**Turn 1 (favors idea 2; this turn\'s "Hypothesis 1" is idea 1):**'
        " Idea 2 names a measurable target." in markdown
    )
    # Turn 2 was judged the other way round: its own text calls idea 2
    # "Hypothesis 1", and the header says so rather than leaving the
    # reader to read two turns as contradicting each other.
    assert (
        '**Turn 2 (favors idea 2; this turn\'s "Hypothesis 1" is idea 2):**'
        in markdown
    )
    # Published artifact (Figure A.17, paper line 1122) prints it capitalized.
    assert markdown.rstrip().count("Better idea:") == 1
    assert "Better idea: 2" in markdown
