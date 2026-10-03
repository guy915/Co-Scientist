"""Render the synthesized evaluation rubric and published tournament debates.

The rubric displays model-generated attributes and criteria, distinct from
the researcher-authored setup; it never gates or ranks hypotheses. Debates
render only when both participants belong to the released hypothesis pool.
"""

from __future__ import annotations

import json
from typing import Any, Final, NamedTuple


def _render_stratification_attributes_markdown(
    attributes: list[dict[str, Any]] | None,
) -> list[str]:
    """Render the Supervisor's synthesized 1-5 stratification attributes."""
    items = [
        attr
        for attr in attributes or []
        if isinstance(attr, dict) and str(attr.get("name") or "").strip()
    ]
    if not items:
        return []
    lines = ["## Stratification Attributes\n"]
    for attr in items:
        name = str(attr["name"]).strip()
        rubric = str(attr.get("rubric") or "").strip()
        lines.append(f"- **{name}:** {rubric}" if rubric else f"- **{name}**")
    lines.append("")
    return lines


def _critical_criterion_name(criterion: Any) -> str:
    """Extract a critical criterion's display name, or "" when unusable."""
    if isinstance(criterion, str):
        return criterion.strip()
    if isinstance(criterion, dict):
        return str(criterion.get("name") or "").strip()
    return ""


def _critical_criterion_description(criterion: Any) -> str:
    """Extract a critical criterion's prose description, or ""."""
    if not isinstance(criterion, dict):
        return ""
    return str(criterion.get("description") or "").strip()


def _critical_criteria_entries(
    critical_criteria: list[Any] | None,
) -> list[tuple[str, str]]:
    """Extract (name, description) pairs, skipping unusable entries.

    Kept separate from ``_render_evaluation_criteria_markdown`` (its only
    caller today) so a non-list ``critical_criteria`` field and an
    unusable entry both filter out here, once, rather than in the
    renderer's own layout logic.
    """
    if not isinstance(critical_criteria, list):
        return []
    return [
        (name, _critical_criterion_description(item))
        for item in critical_criteria
        for name in [_critical_criterion_name(item)]
        if name
    ]


def _render_evaluation_criterion(name: str, description: str) -> list[str]:
    """Render one Evaluation Criteria entry."""
    if description:
        return [f"**{name}:** {description}", ""]
    return [f"- {name}"]


def _render_evaluation_criteria_markdown(
    critical_criteria: list[Any] | None,
) -> list[str]:
    """Render the Supervisor's synthesized per-goal evaluation criteria."""
    entries = _critical_criteria_entries(critical_criteria)
    if not entries:
        return []
    lines = ["## Evaluation Criteria\n"]
    for name, description in entries:
        lines.extend(_render_evaluation_criterion(name, description))
    if lines[-1] != "":
        lines.append("")
    return lines


def _render_review_summary_question(question: Any) -> str:
    """Render one reviewer question bullet, or "" when unusable.

    Mirrors the published Review Summary's bolded-name-plus-question
    format (docs/CORPUS-EXTRACTION.md, line 2929): ``{name, question}``,
    the name bolded when present. A malformed question entry (missing
    text, or not an object -- ``questions`` has no legacy bare-string
    shape to fall back to, unlike the criteria themselves) renders "".
    """
    if not isinstance(question, dict):
        return ""
    name = str(question.get("name") or "").strip()
    text = str(question.get("question") or "").strip()
    if not text:
        return ""
    return f"- **{name}:** {text}" if name else f"- {text}"


def _render_review_summary_criterion(
    index: int, criterion: Any, name: str
) -> list[str]:
    """Render one numbered criterion heading plus its question bullets.

    A legacy bare-name entry (``criterion`` is a str, not a dict) carries
    no ``questions`` to look up, so it numbers in with no bullets beneath
    it -- degraded, not dropped.
    """
    lines = [f"### {index}. {name}\n"]
    raw_questions = (
        criterion.get("questions") if isinstance(criterion, dict) else None
    )
    questions = raw_questions if isinstance(raw_questions, list) else []
    for question in questions:
        line = _render_review_summary_question(question)
        if line:
            lines.append(line)
    lines.append("")
    return lines


def _render_review_summary_markdown(
    critical_criteria: list[Any] | None,
) -> list[str]:
    """Render the Supervisor's synthesized review rubric as its own section."""
    if not isinstance(critical_criteria, list):
        return []
    named = [
        (criterion, name)
        for criterion in critical_criteria
        for name in [_critical_criterion_name(criterion)]
        if name
    ]
    if not named:
        return []
    lines = ["## Review Summary\n"]
    for index, (criterion, name) in enumerate(named, start=1):
        lines.extend(_render_review_summary_criterion(index, criterion, name))
    return lines


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
    """State which idea this turn's own text calls "Hypothesis 1"."""
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
    """Render the 'Tournament debates' section, or nothing when empty."""
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
