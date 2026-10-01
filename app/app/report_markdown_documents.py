"""Assembles the Goal Report document from its rendered sections.

R14-11 split a run's report into two separately-purposed documents
(``research-overview.md`` and ``top-ranking-hypotheses.md``). That split
was reversed 2026-09-04: the owner's product-UI evidence (the published
screen recordings show four run-detail tabs, not five, and one combined
document) showed the split inverted a section that belonged inside the
single document rather than attesting a genuine second document -- see
docs/PARITY.md's REPORT-DOCUMENT-SPLIT-001 row and
docs/CORPUS-STATUS.md's R14-11 entry. This module now renders that one
document again, in the skeleton the pre-split renderer used
(``git show 078f96b1~1:app/app/report_markdown.py``), with every section
the split era added folded back in at the position that era itself
established for it: the R14-27 narrative directions synthesis immediately
before the full hypothesis write-up (its own published "before Candidate
Ideas" placement), the meta-review's tournament-facing half after that
write-up, and the run-wide References list last.

Split out of ``report_markdown`` to keep that module within the size cap;
the names callers use are re-exported so its namespace keeps resolving.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from app.report_markdown_bibliography import _render_references_section
from app.report_markdown_header import (
    _render_about_disclosure,
    _render_provenance_line,
    _render_research_goal_details,
    _render_summary_section,
    _render_title_and_provider,
)
from app.report_markdown_hypothesis import (
    _render_hypothesis_entry,
    _reviews_by_hypothesis,
)
from app.report_markdown_knowledge_base import _render_knowledge_base_markdown
from app.report_markdown_meta_review import (
    _render_main_research_directions_markdown,
    _render_meta_review_overview_markdown,
    _render_meta_review_ranking_markdown,
)
from app.report_markdown_overview import research_overview_sections
from app.report_markdown_references import references_by_hypothesis
from app.report_markdown_sources import _render_data_sources_section
from app.report_markdown_supervisor import (
    _render_evaluation_criteria_markdown,
    _render_review_summary_markdown,
    _render_stratification_attributes_markdown,
)
from app.report_markdown_toc import _render_table_of_contents
from app.report_markdown_tournament import (
    _render_tournament_debates_markdown,
)


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
# co_scientist.agents.generation.literature_tools.validate_novelty) only
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


def _any_novelty_verified(top_hypotheses: list[dict[str, Any]]) -> bool:
    """Return whether any hypothesis carries a corpus-checked novelty result.

    Real today only via the tool-calling generation path the app never
    enables (see the module-level note above), so this stays a genuine
    check -- not a hardcoded True -- so a future run that does enable that
    path stops rendering an inaccurate blanket disclosure without a code
    change here.
    """
    return any(hyp.get("novelty_validation") for hyp in top_hypotheses)


def _render_novelty_disclosure(
    top_hypotheses: list[dict[str, Any]],
) -> list[str]:
    """Render the novelty-unverified disclosure, unless corpus-checked."""
    if not top_hypotheses or _any_novelty_verified(top_hypotheses):
        return []
    return [_NOVELTY_DISCLOSURE, ""]


def _lead_with_goal_restatement(
    section: list[str], restatement: str | None
) -> list[str]:
    """Open the top-hypotheses section with the goal restatement.

    GOAL-RESTATEMENT-001: the restatement opens the section (mirroring where
    Google's own top-ranking-hypotheses document opens with it), inserted
    right after the ``## Top hypotheses`` heading line and its blank that
    ``_render_top_hypotheses_markdown`` always emits first. None leaves the
    section unchanged.
    """
    if not restatement or len(section) < 2:
        return section
    return [*section[:2], restatement, "", *section[2:]]


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

    The prose counterpart of ``report_markdown.ReportPayloadInputs``: the
    same run identity plus the already-ranked hypotheses and the sections
    that have a rendered form.
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
    # renderers in report_markdown_supervisor.py handle every shape.
    critical_criteria: list[Any] | None = None
    # Epoch seconds this report was built, rendered as the provenance and
    # research-purposes-only caution line. None omits that line entirely
    # rather than stating a date via the wall clock -- see
    # report_markdown_header._render_provenance_line.
    prepared_at: float | None = None
    summary: str | None = None
    claim_evidence: list[dict[str, Any]] | None = None
    skills_used: dict[str, int] | None = None
    retrieval_calls: list[dict[str, Any]] | None = None
    # Raw citations/evidence rows (store.list_citations / list_evidence),
    # joined per hypothesis by report_markdown_references to resolve the
    # [C*] keys the mechanism text cites. None (an old run rendered before
    # this field existed, or a run with no citation data at all) resolves
    # no keys -- the report never fabricates a reference.
    citations: list[dict[str, Any]] | None = None
    evidence: list[dict[str, Any]] | None = None
    # Every review row the drain persisted (store.list_reviews), joined per
    # hypothesis for the Go/No-Go framing and simulation-review subsections
    # (R14-15/R14-22, report_markdown_hypothesis.py). None omits both.
    reviews: list[dict[str, Any]] | None = None
    # This run's hypothesis titles by id, for a contact group's example
    # hypotheses (R14-6) -- see report_build._hypothesis_title_by_id. Also
    # the published-pool gate the tournament section renders behind (see
    # report_markdown_tournament).
    hypothesis_title_by_id: dict[str, str] | None = None
    # Every tournament match row the drain persisted
    # (store.list_matches), rendered as "Tournament debates" from the
    # turn-by-turn transcript each carries. None, or a run whose matches
    # predate that column, renders no such section.
    matches: list[dict[str, Any]] | None = None


def _report_sections_goal_and_criteria(
    inputs: ReportMarkdownInputs,
) -> list[list[str]]:
    """Goal details through the earlier meta-review insights section."""
    return [
        _render_research_goal_details(inputs.research_goal, inputs.setup),
        _render_provenance_line(inputs.prepared_at),
        _render_summary_section(inputs.summary),
        _render_evaluation_criteria_markdown(inputs.critical_criteria),
        _render_stratification_attributes_markdown(inputs.attributes),
        _render_meta_review_overview_markdown(inputs.meta_review or {}),
    ]


def _report_sections_overview_and_directions(
    inputs: ReportMarkdownInputs,
) -> list[list[str]]:
    """Sections 10-12: research-overview sub-sections through directions.

    The Review Summary, then R14-27's narrative directions synthesis --
    immediately before Top hypotheses, R14-27's own published "before
    Candidate Ideas" placement.
    """
    return [
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
    ]


def _report_sections_ideas_and_sources(
    inputs: ReportMarkdownInputs,
) -> list[list[str]]:
    """The full per-idea write-up through the run-wide References list."""
    return [
        _lead_with_goal_restatement(
            _render_top_hypotheses_markdown(
                inputs.top_hypotheses,
                inputs.claim_evidence or [],
                inputs.citations or [],
                inputs.evidence or [],
                inputs.reviews or [],
            ),
            inputs.goal_restatement,
        ),
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
        # report_markdown_bibliography.py for placement and dedup
        # rationale. Sits last, matching the published MASH report's own
        # References span running to the end of the document.
        _render_references_section(inputs.evidence or []),
    ]


def _report_sections(inputs: ReportMarkdownInputs) -> list[list[str]]:
    """Every section below the title/About/table-of-contents, in order.

    One section per possible ``## `` heading -- split apart (rather than
    one concatenated ``lines`` list) so :func:`render_report_markdown` can
    hand the same sections to the R14-1 table of contents that it renders
    with, instead of re-deriving which ones are populated. Grouped into
    three helpers (goal/criteria, overview/directions, ideas/sources) to
    stay under this module's own function-length cap; the grouping is
    presentational only -- callers see one flat, ordered list.
    """
    return [
        *_report_sections_goal_and_criteria(inputs),
        *_report_sections_overview_and_directions(inputs),
        *_report_sections_ideas_and_sources(inputs),
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
