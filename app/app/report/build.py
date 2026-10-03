"""Report content gathering and assembly.

Holds the "build" half of report finalization -- loading a run's store
data and shaping it into the payload/markdown pair -- kept separate from
the "publish" half in ``report.finalize`` (the safety gate, persistence,
and event emission) so each stays independently sized and testable.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from app import store
from app.elo import live_leaderboard, rank_for_publication
from app.report.content import (
    _agent_insights,
    _idea_buckets,
    _knowledge_base_topics,
    _synthesized_knowledge_base_topics,
    derive_knowledge_facts,
    released_claim_evidence,
)
from app.report.gates import (
    _exclusion_tally,
    _verified_hypothesis_count,
    contradicted_hypothesis_ids,
    exclude_unsafe_hypotheses,
)
from app.report.markdown import ReportMarkdownInputs, render_report_markdown


class ReportRequest(NamedTuple):
    """Everything ``finalize_report`` needs besides the run id and emitter.

    Both providers build this from their drained final state -- the run's
    identity and tier, the synthesized sections, and where to persist -- and
    it is threaded unchanged through the whole finalize pipeline.

    Attributes:
        research_goal: The run's research goal.
        run_mode: The run's normalized tier.
        provider: The active workflow provider.
        citation_summary: Per-state citation counts, when audited.
        meta_review: The meta-review agent's synthesis, when produced.
        research_overview: The research-overview synthesis, when produced.
        degraded_sections: Engine nodes whose output degraded to a
            placeholder fallback after repeated parse failures; the report
            carries the list so a blank section can explain itself.
        retrieval_degradation: What the run could not search and what it
            had left instead, when no literature source was reachable.
            None on a run that retrieved normally. Unlike a degraded
            section this leaves no trace in the output, so a reader has
            no way to infer it from the report itself.
        skills_used: Science skill name -> invocations the run made.
            The skills reach third-party databases whose terms are
            separate from the bundle's licence and most of which require
            the user be notified of them, so the report names the ones
            this run actually used. Empty on a run that used none.
        execution_time: Wall-clock seconds the run took, when measured.
        summary: Optional summary paragraph for the markdown header.
        setup: The run's persisted requirements/attributes/criteria
            block (``run_modes.setup_config``), rendered as the report
            header's "Research Goal Details".
        attributes: The Supervisor's synthesized 1-5 stratification
            attributes (``config_synthesis.attributes``), rendered as the
            report's "Stratification Attributes" section -- a different,
            LLM-synthesized field from ``setup["attributes"]`` above (see
            ``report.markdown.process``'s vocabulary warning).
        critical_criteria: The Supervisor's synthesized per-goal evaluation
            criteria (``workflow_plan.review_phase.critical_criteria``),
            rendered as both the report's flat "Evaluation Criteria" list
            and its "Review Summary" rubric section -- a different,
            LLM-synthesized field from ``setup["criteria"]`` above (see
            ``report.markdown.process``'s vocabulary warning). Each entry is
            either a legacy bare name (a run persisted before R12-23) or a
            ``{name, questions}`` object; both renderers handle either
            shape.
        prepared_at: Epoch seconds this report was built, rendered as the
            header's provenance and research-purposes-only caution line.
            None omits that line rather than stating a date via the wall
            clock.
        goal_restatement: A freshly synthesized narrative restatement of the
            goal in different words (GOAL-RESTATEMENT-001), rendered at the
            head of the top-hypotheses section. None (offline/keyless runs,
            rows predating the column, or a generation failure) omits it.
        db_path: Optional override for the SQLite database path.
    """

    research_goal: str
    run_mode: str
    provider: str
    citation_summary: dict[str, int] | None = None
    meta_review: dict[str, Any] | None = None
    research_overview: dict[str, Any] | None = None
    degraded_sections: list[str] | None = None
    retrieval_degradation: dict[str, Any] | None = None
    skills_used: dict[str, int] | None = None
    execution_time: float | None = None
    summary: str | None = None
    setup: dict[str, Any] | None = None
    attributes: list[dict[str, Any]] | None = None
    critical_criteria: list[Any] | None = None
    prepared_at: float | None = None
    goal_restatement: str | None = None
    db_path: str | None = None


class _ReportData(NamedTuple):
    """Gathered hypotheses, evidence, reviews, and counts for a run."""

    hyps: list[dict[str, Any]]
    all_hyps: list[dict[str, Any]]
    claim_edges: list[dict[str, Any]]
    released_claim_edges: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    # This run's citation rows (store.list_citations), joined against
    # ``evidence`` by the markdown renderer to resolve the [C*] keys a
    # hypothesis's mechanism text cites.
    citations: list[dict[str, Any]]
    # This run's tournament match rows, carrying each match's persisted
    # debate transcript for the report's "Tournament debates" section.
    # ``match_count`` is their length rather than a second COUNT(*): the
    # payload's number and the section's rows must be the same fact.
    matches: list[dict[str, Any]]
    reviews: list[dict[str, Any]]
    # Searches the deep-research loop recorded for this run, keyed by
    # run_id alone -- extended/ultra tiers only, empty on every other
    # run. Nothing new is written for the report; this reads what
    # ``retrieval_calls`` already has.
    retrieval_calls: list[dict[str, Any]]
    # Why each hypothesis NOT in ``hyps`` left the ranked report (review
    # rejection, duplication, contradiction, or a safety hold), computed
    # once here from the same data ``exclude_unsafe_hypotheses`` used --
    # never by re-running that gate, whose legacy fallback path can write
    # an audit row as a side effect.
    exclusion_tally: dict[str, int]


class _BuiltReport(NamedTuple):
    """One run's report in every persisted form.

    Attributes:
        payload: The JSON report payload.
        markdown: The rendered Goal Report markdown document.
        facts: Durable knowledge-base rows derived from this run's claim-
            evidence graph (audit G14), persisted once the report actually
            publishes; see ``report.finalize._publish_report``.
        exclusion_tally: Why each non-published hypothesis left the ranked
            report (see ``_ReportData.exclusion_tally``), kept off the JSON
            payload since it exists only to compose the empty-leaderboard
            block reason -- see
            ``report.finalize._block_for_empty_leaderboard``.
    """

    payload: dict[str, Any]
    markdown: str
    facts: list[dict[str, Any]]
    exclusion_tally: dict[str, int]


async def build_report_content(run_id: str, req: ReportRequest) -> _BuiltReport:
    """Gather store data and build the report payload and markdown.

    Leaderboard, top hypotheses, and every row count are read from the store
    -- the drain has already persisted everything the payload counts, so the
    counts have one definition across providers.

    Args:
        run_id: Identifier of the run being reported on.
        req: The finalize request's descriptive inputs (goal, tier,
            provider, synthesized sections, and the store path).

    Returns:
        The report payload and its rendered markdown.
    """
    data = _gather_report_data(run_id, req.db_path)
    # Computed once and handed to the payload and the markdown document --
    # resolving it twice risks the two disagreeing on which topics a run's
    # Knowledge Base actually carries (see the root AGENTS.md Gotchas entry
    # on counts computed more than once).
    knowledge_base = _resolve_knowledge_base(data, req)
    inputs = _report_markdown_inputs(data, req, knowledge_base)
    return _BuiltReport(
        payload=_assemble_report_payload(data, req, knowledge_base),
        markdown=render_report_markdown(inputs),
        # Derived from the run's whole claim-evidence graph, not the
        # released subset the payload/markdown are scoped to -- the
        # knowledge base records everything the run found (see
        # app.report.content).
        facts=derive_knowledge_facts(data.claim_edges),
        exclusion_tally=data.exclusion_tally,
    )


def _hypothesis_title_by_id(hyps: list[dict[str, Any]]) -> dict[str, str]:
    """Map this run's published hypotheses to their titles, by id (R14-6).

    Built from the whole published pool (``data.hyps``), not the 5-item
    ``top_hypotheses`` report slice -- the engine's research-overview
    synthesis draws its example hypotheses from up to
    ``RESEARCH_OVERVIEW_TOP_K`` (10), which can name one outside that
    slice.
    """
    return {
        str(h["id"]): str(h["title"])
        for h in hyps
        if h.get("id") and h.get("title")
    }


def _report_markdown_inputs(
    data: _ReportData,
    req: ReportRequest,
    knowledge_base: list[dict[str, Any]],
) -> ReportMarkdownInputs:
    """Assemble the inputs the markdown document renders from."""
    return ReportMarkdownInputs(
        research_goal=req.research_goal,
        goal_restatement=req.goal_restatement,
        provider=req.provider,
        # Report body is capped to the top 5 by Elo; the full set remains
        # available via the leaderboard and the hypotheses API endpoint.
        top_hypotheses=data.hyps[:5],
        meta_review=req.meta_review,
        citation_summary=req.citation_summary,
        research_overview=req.research_overview,
        knowledge_base=knowledge_base,
        setup=req.setup,
        attributes=req.attributes,
        critical_criteria=req.critical_criteria,
        prepared_at=req.prepared_at,
        summary=req.summary,
        claim_evidence=data.released_claim_edges,
        skills_used=req.skills_used,
        retrieval_calls=data.retrieval_calls,
        hypothesis_title_by_id=_hypothesis_title_by_id(data.hyps),
        matches=data.matches,
        citations=data.citations,
        evidence=data.evidence,
        reviews=data.reviews,
    )


def _resolve_knowledge_base(
    data: _ReportData, req: ReportRequest
) -> list[dict[str, Any]]:
    """Resolve the run's Knowledge Base topics, once, for payload and markdown.

    Prefers the engine's synthesized topics (cross-source, from the
    research overview); falls back to per-hypothesis topics derived from
    the released claim graph when no overview was synthesized. The same
    resolved list backs both the JSON payload the UI reads and the
    markdown export, by design -- see the call site's comment.
    """
    synthesized = _synthesized_knowledge_base_topics(
        req.research_overview, data.evidence
    )
    return synthesized or _knowledge_base_topics(data.hyps, data.claim_edges)


def _gather_report_data(run_id: str, db_path: str | None) -> _ReportData:
    """Load and safety-filter a run's hypotheses, evidence, and claim edges."""
    all_hyps = store.list_hypotheses(run_id, db_path=db_path)
    claim_edges = store.list_claim_evidence(run_id, db_path=db_path)
    # Exclude any hypothesis a per-hypothesis safety review blocks (recorded as
    # an audit decision) before it can appear in the leaderboard or top ideas.
    # Ordered once, here, so the report body's top ideas and the standings
    # beside them open with the same idea. The store returns rows by raw
    # Elo, which puts an undermined idea first.
    hyps = rank_for_publication(
        exclude_unsafe_hypotheses(run_id, all_hyps, db_path, claim_edges)
    )
    evidence = store.list_evidence(run_id, db_path=db_path)
    released_claim_edges = released_claim_evidence(hyps, claim_edges, evidence)
    # Derived here from the same inputs the gate above just used, rather
    # than by re-running it: its legacy fallback path writes an audit row
    # as a side effect, so calling it twice would double that row.
    contradicted = contradicted_hypothesis_ids(run_id, db_path, claim_edges)
    # ``summary_counts`` exists to avoid materializing tables the caller
    # has; asking it here would re-count evidence beside tables the report
    # never reads it through.
    return _ReportData(
        hyps=hyps,
        all_hyps=all_hyps,
        claim_edges=claim_edges,
        released_claim_edges=released_claim_edges,
        evidence=evidence,
        citations=store.list_citations(run_id, db_path=db_path),
        matches=store.list_matches(run_id, db_path=db_path),
        reviews=store.list_reviews(run_id, db_path=db_path),
        retrieval_calls=store.list_retrieval_calls(run_id, db_path=db_path),
        exclusion_tally=_exclusion_tally(all_hyps, hyps, contradicted),
    )


def _assemble_report_payload(
    data: _ReportData,
    req: ReportRequest,
    knowledge_base: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the report payload dict from already-gathered store data."""
    hyps, all_hyps, claim_edges = data.hyps, data.all_hyps, data.claim_edges
    payload: dict[str, Any] = {
        "research_goal": req.research_goal,
        "run_mode": req.run_mode,
        "provider": req.provider,
        "leaderboard": live_leaderboard(hyps),
        "hypothesis_count": len(hyps),
        # Explored and published ideas differ when the release gate withholds
        # an unsafe or contradicted candidate.
        "idea_count": len(all_hyps),
        "verified_count": _verified_hypothesis_count(hyps, claim_edges),
        "evidence_count": len(data.evidence),
        "match_count": len(data.matches),
        "citation_summary": req.citation_summary or {},
        "meta_review": req.meta_review or {},
        "research_overview": req.research_overview or {},
        "knowledge_base": knowledge_base,
        "agent_insights": _agent_insights(hyps, claim_edges, req.meta_review),
        "idea_buckets": _idea_buckets(hyps, all_hyps, claim_edges),
        "claim_evidence": data.released_claim_edges,
        "degraded_sections": list(req.degraded_sections or []),
        "retrieval_degradation": req.retrieval_degradation,
        "skills_used": dict(req.skills_used or {}),
        "reviews": list(data.reviews),
    }
    if req.execution_time is not None:
        payload["execution_time"] = req.execution_time
    return payload
