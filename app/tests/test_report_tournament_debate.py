"""F3: the tournament's debate transcripts render in the report.

Google publishes a whole match as a turn-by-turn exchange closing on one
``Better idea: <n>`` line (``outputs/ranking-tournament/
als-tournament-debate.md``, 412 words). Ours judged the same multi-turn
debate and kept only the closing rationale, so the tournament reached the
reader asserted rather than argued. The turns are now persisted on the
match row (``matches.debate_transcript``) and rendered here.

The section is deliberately bounded -- see the caps in
``report.markdown.tournament`` -- because a run judges every pairing while
Google publishes one exemplar, and an uncapped transcript dump would be a
larger document than the report it sits in.
"""

from __future__ import annotations

import json
from typing import Any

from app.report import markdown as report_markdown

_TITLES = {"h1": "SGLT2 inhibition in fibroblasts", "h2": "NHE1 screening"}


def _transcript(verdict: str, turns: list[tuple[int, str, str]]) -> str:
    """A stored transcript document, as ``drain_matches`` writes it."""
    return json.dumps(
        {
            "verdict": verdict,
            "turns": [
                {"turn": turn, "favored": favored, "text": text}
                for turn, favored, text in turns
            ],
        }
    )


def _match(**overrides: Any) -> dict[str, Any]:
    """One match row, defaulting to a two-turn debate the winner won."""
    row: dict[str, Any] = {
        "winner_id": "h1",
        "loser_id": "h2",
        "debate_turns": 2,
        "rationale": "Idea 1 prevails.",
        "debate_transcript": _transcript(
            "1",
            [
                (1, "1", "Idea 1 names a measurable target."),
                (2, "1", "The counter-argument does not survive."),
            ],
        ),
    }
    row.update(overrides)
    return row


def _markdown(matches: list[dict[str, Any]] | None) -> str:
    """Render a minimal report carrying only the given matches."""
    return report_markdown.render_report_markdown(
        report_markdown.ReportMarkdownInputs(
            research_goal="Explain the cardiac benefit.",
            provider="engine",
            top_hypotheses=[{"id": "h1", "title": _TITLES["h1"]}],
            matches=matches,
            hypothesis_title_by_id=dict(_TITLES),
        )
    )


def test_a_stored_debate_renders_turns_and_one_closing_verdict() -> None:
    """The published shape: numbered ideas, each turn, one verdict line."""
    markdown = _markdown([_match()])

    assert "## Tournament debates" in markdown
    assert (
        "### Debate 1: 1. SGLT2 inhibition in fibroblasts "
        "vs 2. NHE1 screening" in markdown
    )
    assert "**Turn 1 (favors idea 1):** Idea 1 names a measurable target." in (
        markdown
    )
    assert "**Turn 2 (favors idea 1):** The counter-argument does not" in (
        markdown
    )
    # Published artifact (Figure A.17, paper line 1122) prints it capitalized.
    assert "Better idea: 1" in markdown
    assert markdown.count("Better idea:") == 1


def test_idea_numbering_follows_the_verdict_not_the_winner() -> None:
    """Verdict "2" means the winner is idea 2, so the loser leads.

    The number is the judge's own canonical presentation order, not the
    outcome -- printing the winner first regardless would make every
    published verdict line read "Better idea: 1".
    """
    markdown = _markdown(
        [
            _match(
                debate_transcript=_transcript(
                    "2",
                    [
                        (1, "2", "Idea 2 is better grounded."),
                        (2, "2", "It stays better grounded."),
                    ],
                )
            )
        ]
    )

    assert (
        "### Debate 1: 1. NHE1 screening "
        "vs 2. SGLT2 inhibition in fibroblasts" in markdown
    )
    assert "Better idea: 2" in markdown


def test_a_match_with_no_stored_transcript_renders_as_it_did() -> None:
    """A legacy row (NULL transcript) produces no section at all."""
    markdown = _markdown([_match(debate_transcript=None)])

    assert "## Tournament debates" not in markdown
    assert "Tournament debates" not in markdown


def test_no_matches_at_all_render_nothing() -> None:
    """A run that never reached the tournament omits the heading (R14-23)."""
    assert "## Tournament debates" not in _markdown(None)
    assert "## Tournament debates" not in _markdown([])


def test_a_single_turn_comparison_is_not_a_debate() -> None:
    """One turn is the single-turn comparison, not the published exchange.

    Rendering it would fill a capped section with matches that have no
    exchange to show, crowding out the multi-turn debates that do.
    """
    markdown = _markdown(
        [
            _match(
                debate_turns=1,
                debate_transcript=_transcript(
                    "1", [(1, "1", "Idea 1 is stronger.")]
                ),
            )
        ]
    )

    assert "## Tournament debates" not in markdown


def test_a_match_whose_idea_left_the_report_is_not_rendered() -> None:
    """A withheld idea's debate quotes it at length -- so it is skipped.

    ``hypothesis_title_by_id`` names the published pool; a duplicate,
    rejected, or safety-blocked idea is absent from it, and its transcript
    argues both sides in full. Rendering it would republish text the
    content gates withheld.
    """
    markdown = _markdown([_match(loser_id="h-withheld")])

    assert "## Tournament debates" not in markdown


def test_the_section_caps_how_many_debates_it_renders() -> None:
    """Only the deepest debates render, up to the cap."""
    matches = [
        _match(
            debate_turns=2 + index,
            debate_transcript=_transcript(
                "1",
                [
                    (turn, "1", f"Debate {index} turn {turn}.")
                    for turn in range(1, 3 + index)
                ],
            ),
        )
        for index in range(8)
    ]

    markdown = _markdown(matches)

    assert markdown.count("### Debate ") == 5
    # Deepest first: the 8th match budgeted the most turns.
    assert "Debate 7 turn 1." in markdown
    assert "Debate 0 turn 1." not in markdown


def test_a_pathologically_long_turn_is_truncated() -> None:
    """One turn's argument is capped, with the cut marked."""
    markdown = _markdown(
        [
            _match(
                debate_transcript=_transcript(
                    "1",
                    [
                        (1, "1", "word " * 900),
                        (2, "1", "Short close."),
                    ],
                )
            )
        ]
    )

    assert "…" in markdown
    assert len(markdown) < 6000


def test_only_the_first_turns_of_a_very_long_debate_render() -> None:
    """A debate at the engine's ten-turn ceiling renders its opening turns."""
    markdown = _markdown(
        [
            _match(
                debate_turns=10,
                debate_transcript=_transcript(
                    "1",
                    [
                        (turn, "1", f"Turn {turn} argument.")
                        for turn in range(1, 11)
                    ],
                ),
            )
        ]
    )

    assert "Turn 5 argument." in markdown
    assert "Turn 6 argument." not in markdown


def _ordered_transcript(
    verdict: str, turns: list[tuple[int, str, str, str]]
) -> str:
    """A stored transcript whose turns also record their own numbering."""
    return json.dumps(
        {
            "verdict": verdict,
            "turns": [
                {"turn": t, "favored": f, "text": x, "first": first}
                for t, f, x, first in turns
            ],
        }
    )


def test_a_swapped_turn_names_the_numbering_its_own_text_uses() -> None:
    """The production symptom: two turns that read as contradicting.

    Turns alternate which idea is presented first, so a swapped turn's
    prose calls idea 2 "Hypothesis 1". Rendered without that fact the
    section shows one judge asserting "Hypothesis 1 is superior" and
    "Hypothesis 2 is superior" while both turns favour the same idea
    (production run f8db4d04, debate 2). Each turn header now names the
    numbering that turn's own text uses.
    """
    markdown = _markdown(
        [
            _match(
                debate_transcript=_ordered_transcript(
                    "2",
                    [
                        (1, "2", "Hypothesis 2 is superior on impact.", "1"),
                        (2, "2", "Hypothesis 1 is superior on impact.", "2"),
                    ],
                )
            )
        ]
    )

    assert (
        '**Turn 1 (favors idea 2; this turn\'s "Hypothesis 1" is idea 1):**'
        " Hypothesis 2 is superior on impact." in markdown
    )
    assert (
        '**Turn 2 (favors idea 2; this turn\'s "Hypothesis 1" is idea 2):**'
        " Hypothesis 1 is superior on impact." in markdown
    )


def test_a_turn_without_a_recorded_order_renders_as_it_did() -> None:
    """A row written before the order was recorded keeps its old header."""
    markdown = _markdown([_match()])

    assert "**Turn 1 (favors idea 1):** Idea 1 names" in markdown
