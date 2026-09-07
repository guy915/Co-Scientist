"""The debate transcript in the published exemplar's own shape.

Figure A.17 (``outputs/ranking-tournament/als-tournament-debate.md``) is a
turn-by-turn exchange closing on a single ``Better idea: <n>`` line. The
judge already produces every turn; ``debate_transcript_document`` is the
projection a consumer persists and renders -- each turn's argument plus
which numbered idea it favoured, and one verdict for the whole match.

The per-turn numbering is the point of the projection. A turn's own
``reasoning`` ends with *that turn's* verdict line, stated in the
presentation order that turn used -- and the loop alternates that order
every turn -- so printing the turns verbatim shows a match arguing for
"idea 1" and "idea 2" by turns. The document strips each turn's trailing
verdict line and restates the whole match's verdict once, in the
canonical order.
"""

from typing import Any

from co_scientist.agents.ranking.ranking_debate_turns import (
    debate_transcript_document,
)
from co_scientist.agents.ranking.ranking_results import (
    _debate_provenance_fields,
)


def _entry(turn: int, winner: str, reasoning: str) -> dict[str, Any]:
    """One transcript entry in the shape ``_run_debate_turn`` records."""
    return {
        "turn": turn,
        "winner": winner,
        "winner_id": f"h-{winner}",
        "reasoning": reasoning,
        "presentation_order": "ab" if turn % 2 else "ba",
        "valid_output": True,
    }


def test_document_carries_every_turn_and_one_closing_verdict() -> None:
    """Each turn keeps its argument; the verdict is stated once."""
    transcript = [
        _entry(1, "a", "Idea 1 is better grounded. better idea: 1"),
        _entry(2, "a", "The mechanism holds up. Better idea: 2"),
    ]

    document = debate_transcript_document(transcript, "1")

    assert document["verdict"] == "1"
    assert [turn["turn"] for turn in document["turns"]] == [1, 2]
    assert [turn["favored"] for turn in document["turns"]] == ["1", "1"]
    assert document["turns"][0]["text"] == "Idea 1 is better grounded."
    assert document["turns"][1]["text"] == "The mechanism holds up."


def test_each_turn_records_which_idea_it_presented_first() -> None:
    """A consumer needs each turn's own numbering, not just the canonical one.

    A turn's prose numbers the two ideas in the order that turn presented
    them, and the loop alternates that order. Without this field a
    renderer can only guess, and prints turns that read as one judge
    contradicting itself (production run f8db4d04).
    """
    transcript = [
        _entry(1, "a", "Idea 1 is better grounded."),
        _entry(2, "a", "The mechanism holds up."),
    ]

    document = debate_transcript_document(transcript, "1")

    assert [turn["first"] for turn in document["turns"]] == ["1", "2"]


def test_a_turn_with_no_recorded_order_documents_the_canonical_one() -> None:
    """An entry predating the field reads as the un-swapped order."""
    entry = {"turn": 1, "winner": "a", "reasoning": "Idea 1 wins."}

    [turn] = debate_transcript_document([entry], "1")["turns"]

    assert turn["first"] == "1"


def test_a_mid_text_verdict_mention_survives() -> None:
    """Only a trailing verdict line is a verdict; prose about one is not."""
    transcript = [
        _entry(
            1,
            "b",
            "The panel is asked to end on better idea: 1 or 2. "
            "Idea 2 wins on feasibility.",
        )
    ]

    [turn] = debate_transcript_document(transcript, "2")["turns"]

    assert turn["text"].endswith("Idea 2 wins on feasibility.")
    assert "better idea: 1 or 2" in turn["text"]
    assert turn["favored"] == "2"


def test_an_empty_transcript_documents_no_turns() -> None:
    """A match with no recorded turns documents nothing to render."""
    assert debate_transcript_document([], "1") == {
        "verdict": "1",
        "turns": [],
    }


def test_provenance_names_the_verdict_number_the_exemplar_prints() -> None:
    """The matchup detail carries the published verdict number.

    Canonical side "a" is the exemplar's idea 1 and "b" its idea 2; a
    response predating the field falls back to the winner it was built
    with, so an older judge result still names a verdict.
    """
    assert (
        _debate_provenance_fields({"debate_verdict": "2"}, "a")[
            "debate_verdict"
        ]
        == "2"
    )
    assert _debate_provenance_fields({}, "b")["debate_verdict"] == "2"
    assert _debate_provenance_fields({}, "a")["debate_verdict"] == "1"
