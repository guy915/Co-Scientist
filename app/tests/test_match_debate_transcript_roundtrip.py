"""F3 end to end: judge output -> drain -> store -> report.

Each hop was individually pinned; this walks the whole path with the
engine's own judge, so a shape change anywhere between the debate loop and
the rendered document fails here rather than silently dropping the
transcript at whichever boundary moved.
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

from app import report_markdown, store
from app.engine_adapter.drain_matches import _persist_engine_matches


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
