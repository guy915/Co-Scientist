"""Render the Goal Report from its ordered document sections."""

from __future__ import annotations

import dataclasses
import json
from typing import Any, Final, NamedTuple

from app.report.markdown.document import (
    _render_about_disclosure,
    _render_data_sources_section,
    _render_knowledge_base_markdown,
    _render_provenance_line,
    _render_research_goal_details,
    _render_summary_section,
    _render_table_of_contents,
    _render_title_and_provider,
)
from app.report.markdown.hypothesis import (
    _render_hypothesis_entry,
    _render_references_section,
    _reviews_by_hypothesis,
    references_by_hypothesis,
)
from app.report.markdown.overview import (
    _render_main_research_directions_markdown,
    _render_meta_review_overview_markdown,
    _render_meta_review_ranking_markdown,
    research_overview_sections,
)


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


_MAX_TURNS: Final = 5


_MAX_TURN_CHARS: Final = 1200


_MIN_DEBATE_TURNS: Final = 2


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


def _claim_evidence_by_hypothesis(
    claim_evidence: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group claim edges by hypothesis id in one pass.

    The section renders up to five hypotheses and every edge belongs to
    exactly one of them, so grouping once beats re-filtering the whole edge
    list per entry.

    Args:
        claim_evidence: The run's released claim-evidence edges.

    Returns:
        Mapping of hypothesis id to its edges, in their original order.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for edge in claim_evidence:
        key = str(edge.get("hypothesis_id") or "")
        grouped.setdefault(key, []).append(edge)
    return grouped


# K3: novelty scores/language throughout the review, ranking, and
# generation prompts are the reviewing model's own unaided judgment --
# grounding that judgment in an actual literature search
# (novelty_validation, populated by
# co_scientist.agents.generation.literature_tools.validate) only
# runs on the tool-calling generation path, which the app never enables for
# a real run (see engine_adapter/opts.py). A reader must never be left with
# definitive novelty language on the strength of an unverified judgment, so
# this note renders whenever nothing in the report was actually corpus-
# checked -- which today is every run.
_NOVELTY_DISCLOSURE = (
    "_Novelty above reflects the reviewing model's own judgment, not a"
    " search of the published literature. Treat any claim that an idea is"
    " original, unprecedented, or unexplored as directional, not verified._"
)


def _render_novelty_disclosure(
    top_hypotheses: list[dict[str, Any]],
) -> list[str]:
    """Render the novelty-unverified disclosure, unless corpus-checked."""
    if not top_hypotheses or any(
        hyp.get("novelty_validation") for hyp in top_hypotheses
    ):
        return []
    return [_NOVELTY_DISCLOSURE, ""]


def _render_top_hypotheses_markdown(
    top_hypotheses: list[dict[str, Any]],
    claim_evidence: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
) -> list[str]:
    """Render the numbered 'Top hypotheses' section."""
    edges_by_hypothesis = _claim_evidence_by_hypothesis(claim_evidence)
    refs_by_hypothesis = references_by_hypothesis(citations, evidence)
    reviews_by_hypothesis = _reviews_by_hypothesis(reviews)
    lines: list[str] = ["## Top hypotheses", ""]
    lines += _render_novelty_disclosure(top_hypotheses)
    for i, hyp in enumerate(top_hypotheses, 1):
        hyp_id = str(hyp.get("id") or "")
        lines += _render_hypothesis_entry(
            i,
            hyp,
            edges_by_hypothesis.get(hyp_id, []),
            refs_by_hypothesis.get(hyp_id, []),
            reviews_by_hypothesis.get(hyp_id, []),
        )
    return lines


def _render_citation_audit(
    citation_summary: dict[str, int] | None,
) -> list[str]:
    """Render the 'Citation audit' section, or nothing when absent."""
    if not citation_summary:
        return []
    lines = ["## Citation audit"]
    lines.extend(
        f"- {state}: {count}" for state, count in citation_summary.items()
    )
    lines.append("")
    return lines


@dataclasses.dataclass(frozen=True)
class ReportMarkdownInputs:
    """Everything the report markdown document renders from.

    Run identity, ranked hypotheses, and synthesized document sections.
    """

    research_goal: str
    provider: str
    top_hypotheses: list[dict[str, Any]]
    # A freshly synthesized narrative restatement of the goal in different
    # words (GOAL-RESTATEMENT-001), rendered at the head of the top-hypotheses
    # section. None (offline/keyless runs, rows predating the column, or a
    # generation failure) omits the paragraph -- the raw "Research Goal
    # Details" block above is unaffected either way.
    goal_restatement: str | None = None
    meta_review: dict[str, Any] | None = None
    citation_summary: dict[str, int] | None = None
    research_overview: dict[str, Any] | None = None
    knowledge_base: list[dict[str, Any]] | None = None
    # The run's persisted requirements/attributes/criteria (and goal),
    # rendered as "Research Goal Details" -- see run_modes.setup_config.
    setup: dict[str, Any] | None = None
    # The Supervisor's synthesized 1-5 stratification attributes
    # (config_synthesis.attributes), rendered as "Stratification
    # Attributes". A different, LLM-synthesized field from
    # setup["attributes"] above -- same English word, two differently-
    # shaped published sections (docs/CORPUS-EXTRACTION.md R12-17); do not
    # conflate them under one heading.
    attributes: list[dict[str, Any]] | None = None
    # The Supervisor's synthesized per-goal evaluation criteria
    # (workflow_plan.review_phase.critical_criteria), rendered as both
    # "Evaluation Criteria" (bolded-name-plus-prose, R12-18/R12-23b) and
    # "Review Summary" (numbered, with each criterion's named reviewer
    # questions -- R12-23). A different, LLM-synthesized field from
    # setup["criteria"] above -- same English word, differently-shaped
    # published sections (docs/CORPUS-EXTRACTION.md R12-18, R12-23); do
    # not conflate them under one heading. Each entry is the legacy bare
    # criterion-name string, the R12-23 {name, questions} object, or the
    # richer R12-23b {name, description, questions} object; both
    # renderers in report/markdown/process.py handle every shape.
    critical_criteria: list[Any] | None = None
    # Epoch seconds this report was built, rendered as the provenance and
    # research-purposes-only caution line. None omits that line entirely
    # rather than stating a date via the wall clock -- see
    # report.markdown.document._render_provenance_line.
    prepared_at: float | None = None
    summary: str | None = None
    claim_evidence: list[dict[str, Any]] | None = None
    skills_used: dict[str, int] | None = None
    retrieval_calls: list[dict[str, Any]] | None = None
    # Raw citations/evidence rows (store.list_citations / list_evidence),
    # joined per hypothesis by report.markdown.references to resolve the
    # [C*] keys the mechanism text cites. None (an old run rendered before
    # this field existed, or a run with no citation data at all) resolves
    # no keys -- the report never fabricates a reference.
    citations: list[dict[str, Any]] | None = None
    evidence: list[dict[str, Any]] | None = None
    # Every review row the drain persisted (store.list_reviews), joined per
    # hypothesis for the Go/No-Go framing and simulation-review subsections
    # (R14-15/R14-22, report/markdown/hypothesis.py). None omits both.
    reviews: list[dict[str, Any]] | None = None
    # This run's hypothesis titles by id, for a contact group's example
    # hypotheses (R14-6) -- see report.build._hypothesis_title_by_id. Also
    # the published-pool gate the tournament section renders behind (see
    # report.markdown.process).
    hypothesis_title_by_id: dict[str, str] | None = None
    # Every tournament match row the drain persisted
    # (store.list_matches), rendered as "Tournament debates" from the
    # turn-by-turn transcript each carries. None, or a run whose matches
    # predate that column, renders no such section.
    matches: list[dict[str, Any]] | None = None


def _report_sections(inputs: ReportMarkdownInputs) -> list[list[str]]:
    """Render sections once, in the order shared by the body and contents."""
    top_hypotheses = _render_top_hypotheses_markdown(
        inputs.top_hypotheses,
        inputs.claim_evidence or [],
        inputs.citations or [],
        inputs.evidence or [],
        inputs.reviews or [],
    )
    if inputs.goal_restatement:
        top_hypotheses[2:2] = [inputs.goal_restatement, ""]
    return [
        _render_research_goal_details(inputs.research_goal, inputs.setup),
        _render_provenance_line(inputs.prepared_at),
        _render_summary_section(inputs.summary),
        _render_evaluation_criteria_markdown(inputs.critical_criteria),
        _render_stratification_attributes_markdown(inputs.attributes),
        _render_meta_review_overview_markdown(inputs.meta_review or {}),
        # R14-1: each of the research-overview's own four sub-sections
        # travels as its own entry rather than the one flattened list
        # ``render_research_overview_markdown`` returns, so a report that
        # only carries e.g. Research Contacts still gets the other three
        # correctly omitted from the table of contents.
        *research_overview_sections(
            inputs.research_overview or {}, inputs.hypothesis_title_by_id
        ),
        # R12-23: the published "Review summary" sits right after the
        # research directions and before the full hypothesis write-up.
        _render_review_summary_markdown(inputs.critical_criteria),
        _render_main_research_directions_markdown(inputs.meta_review or {}),
        top_hypotheses,
        # "Idea Comparison Table" / "Comparison with Existing Solutions" /
        # "Recommendation" (R14-7/R14-8) -- the tournament-facing half of
        # the meta-review's synthesis, evaluating the candidates just
        # rendered above.
        _render_meta_review_ranking_markdown(inputs.meta_review or {}),
        # F3: the debates behind that comparison's verdicts -- the
        # tournament's own published artifact, immediately after the
        # ranking material it explains.
        _render_tournament_debates_markdown(
            inputs.matches or [], inputs.hypothesis_title_by_id
        ),
        _render_knowledge_base_markdown(inputs.knowledge_base or []),
        _render_data_sources_section(
            inputs.skills_used or {}, inputs.retrieval_calls or []
        ),
        _render_citation_audit(inputs.citation_summary),
        # R12-12: the run-wide bibliography, deduplicated -- see
        # report/markdown/references.py for placement and dedup
        # rationale. Sits last, matching the published MASH report's own
        # References span running to the end of the document.
        _render_references_section(inputs.evidence or []),
    ]


def render_report_markdown(inputs: ReportMarkdownInputs) -> str:
    """Render a run's Goal Report markdown from one skeleton for every provider.

    Sections populate only when their data is present, so a provider that
    omits meta-review, citations, or a research overview simply skips those
    headings rather than emitting empty ones. Right after the always-present
    title/provider line and the R14-4 About disclosure comes a table of
    contents (R14-1) naming whichever sections this particular render
    actually produced.

    Args:
        inputs: The run identity, top hypotheses, and rendered sections.

    Returns:
        The rendered markdown document.
    """
    title_lines = _render_title_and_provider(
        inputs.research_goal, inputs.provider
    )
    about_lines = _render_about_disclosure()
    sections = _report_sections(inputs)
    lines = title_lines + about_lines + _render_table_of_contents(sections)
    for section in sections:
        lines += section
    return "\n".join(lines)
