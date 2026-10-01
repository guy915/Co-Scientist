"""The tournament's debate transcripts, rendered under the comparison.

Google publishes a whole tournament match as an artifact in its own right
(``outputs/ranking-tournament/als-tournament-debate.md``, Figure A.17): a
turn-by-turn exchange, roughly 412 words, closing on a single
``Better idea: <n>`` line. Our judge runs the same multi-turn debate and
returns every turn, but the drain used to keep only the closing rationale
(65-167 words), so the reader saw the tournament's conclusion and never
its argument. ``matches.debate_transcript`` now carries the turns and this
module renders them, immediately after the meta-review's own candidate
comparison -- the tournament's verdict, then the debate behind it.

**Why the section is capped.** The published exemplar is one match; a run
judges every pairing it can afford (11 on the express run this was
measured against, 10 of them multi-turn), so rendering every transcript in
full would add more words than the rest of the report holds. Three caps
bound it, and each is stated as a constant below rather than tuned in the
renderer: how many debates render, how many turns of one debate render,
and how long one turn's argument may be.

**Why the closing line is capitalised.** The two published sources
disagree: the ranking prompt asks the judge for ``better idea: 1``
(paper lines 794 and 853, and ``prompts/templates/ranking_debate.md``
repeats it verbatim), while Figure A.17's rendered artifact prints
``Better idea: 1`` (paper line 1122). This section mirrors the rendered
artifact, not the prompt, so it prints the capitalised form; the judge is
still asked for the lower-case phrasing, unchanged, and the engine's
``test_published_artifact_shapes`` pins the figure's casing separately,
against the exemplar rather than against this renderer.

**Why a withheld idea's debate never renders.** A transcript argues both
sides at length, quoting each idea's mechanism. An idea the content gates
withheld (duplicate, rejected, or safety-held) is absent from
``hypothesis_title_by_id``, which is built from the published pool -- so a
match with an unresolvable side is skipped entirely rather than rendered
with an anonymous participant, which would republish exactly the text the
gate removed.
"""

from __future__ import annotations

import json
from typing import Any, Final, NamedTuple

_MAX_DEBATES: Final = 5
"""Debates rendered, deepest first.

Five, because the report body itself publishes the top five ideas
(``report.build``): a debate below that depth is between ideas the reader
never meets in full.
"""

_MAX_TURNS: Final = 5
"""Turns rendered per debate.

The published exemplar runs five turns, and the paper's own envelope calls
3-5 typical (the engine's hard ceiling is 10). A debate that ran longer
renders its opening exchange -- where the clarifying questions are -- and
still closes on the whole match's verdict.
"""

_MAX_TURN_CHARS: Final = 1200
"""Characters of one turn's argument.

The exemplar's turns run about 520 characters and ours about 800, so this
bites only on a pathological turn; the cut is marked rather than silent.
"""

_MIN_DEBATE_TURNS: Final = 2
"""Turns below which a match is a single-turn comparison, not a debate.

``ranking_debate`` judges lower-ranked pairings in one turn, which has no
exchange to show -- and letting those fill the cap would crowd out the
multi-turn debates that do.
"""


class _Debate(NamedTuple):
    """One match's stored debate, resolved against the published pool."""

    idea_1: str
    idea_2: str
    verdict: str
    turns: list[dict[str, Any]]


def _stored_document(match: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a match row's transcript column, or None when it has none.

    A row written before the column existed reads NULL, and a row whose
    JSON does not parse is treated the same way: the report omits the
    debate rather than printing a fragment of one.
    """
    raw = match.get("debate_transcript")
    if not raw:
        return None
    try:
        document = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def _resolve_debate(
    match: dict[str, Any], titles: dict[str, str]
) -> _Debate | None:
    """Resolve one match into a renderable debate, or None to skip it.

    Idea 1 and idea 2 are the judge's own canonical presentation order,
    recovered from the verdict: the winner is idea 1 exactly when the
    verdict says 1. Deriving it from the outcome instead would make every
    published verdict line read "better idea: 1".
    """
    document = _stored_document(match)
    if document is None:
        return None
    turns = [t for t in document.get("turns") or [] if isinstance(t, dict)]
    winner = titles.get(str(match.get("winner_id") or ""))
    loser = titles.get(str(match.get("loser_id") or ""))
    if not winner or not loser or len(turns) < _MIN_DEBATE_TURNS:
        return None
    verdict = str(document.get("verdict") or "1")
    first, second = (winner, loser) if verdict == "1" else (loser, winner)
    return _Debate(first, second, verdict, turns)


def _select_debates(
    matches: list[dict[str, Any]], titles: dict[str, str]
) -> list[_Debate]:
    """The debates this section renders, deepest first, capped.

    Depth is the tournament's own measure of which comparison mattered:
    ``ranking_debate`` budgets multiple turns to top-ranked pairings and
    settles the rest in one, so ordering by turn count puts the run's most
    contested comparisons first. Python's sort is stable, so matches of
    equal depth keep the order the tournament judged them in.
    """
    debates = [
        debate
        for match in matches
        if (debate := _resolve_debate(match, titles)) is not None
    ]
    debates.sort(key=lambda debate: len(debate.turns), reverse=True)
    return debates[:_MAX_DEBATES]


def _turn_text(turn: dict[str, Any]) -> str:
    """One turn's argument, truncated at the cap with the cut marked."""
    text = " ".join(str(turn.get("text") or "").split())
    if len(text) <= _MAX_TURN_CHARS:
        return text
    return text[:_MAX_TURN_CHARS].rstrip() + " …"


def _numbering_note(turn: dict[str, Any]) -> str:
    """State which idea this turn's own text calls "Hypothesis 1".

    The judge sees the pair in alternating order (the tournament's
    position-bias control), so a swapped turn's prose calls idea 2
    "Hypothesis 1". Rendered without that fact, production run f8db4d04
    showed one judge asserting "Hypothesis 1 is superior" and
    "Hypothesis 2 is superior" on two turns that favoured the same idea.
    A turn stored before the order was recorded says nothing rather than
    guessing.
    """
    first = str(turn.get("first") or "")
    if first not in ("1", "2"):
        return ""
    return f'; this turn\'s "Hypothesis 1" is idea {first}'


def _render_turn(index: int, turn: dict[str, Any]) -> str:
    """Render one turn as a labelled paragraph.

    The turn's own number is trusted only as a label; ``index`` is what
    the reader counts by, so a transcript missing a turn number still
    reads as a sequence. "Favors idea N" is always the section's own
    numbering; ``_numbering_note`` names the turn's.
    """
    favored = "2" if str(turn.get("favored") or "1") == "2" else "1"
    return (
        f"**Turn {index} (favors idea {favored}{_numbering_note(turn)}):**"
        f" {_turn_text(turn)}"
    )


def _render_debate(number: int, debate: _Debate) -> list[str]:
    """Render one debate: its pairing, its turns, and its verdict line."""
    lines = [
        f"### Debate {number}: 1. {debate.idea_1} vs 2. {debate.idea_2}",
        "",
    ]
    for index, turn in enumerate(debate.turns[:_MAX_TURNS], 1):
        lines += [_render_turn(index, turn), ""]
    lines += [f"Better idea: {debate.verdict}", ""]
    return lines


def _render_tournament_debates_markdown(
    matches: list[dict[str, Any]],
    hypothesis_title_by_id: dict[str, str] | None,
) -> list[str]:
    """Render the 'Tournament debates' section, or nothing when empty.

    Args:
        matches: The run's persisted match rows (``store.list_matches``).
        hypothesis_title_by_id: Titles of the published hypotheses, which
            is also the gate on which debates may render at all.

    Returns:
        The section's lines, or an empty list when no match carries a
        renderable debate -- a run judged before the transcript column
        existed, a run that never reached the tournament, or one whose
        debates all involve a withheld idea.
    """
    debates = _select_debates(matches, hypothesis_title_by_id or {})
    if not debates:
        return []
    lines = [
        "## Tournament debates",
        "",
        "_Each pairing is judged as a simulated expert debate: the judge"
        " re-examines the exchange each turn, with the two ideas presented"
        " in alternating order, before the closing verdict. Because that"
        " order alternates, each turn's header names which idea that"
        ' turn\'s own text calls "Hypothesis 1"; "favors idea N" always'
        " uses this section's numbering._",
        "",
    ]
    for number, debate in enumerate(debates, 1):
        lines += _render_debate(number, debate)
    return lines
