"""Report content gathering and assembly, split out of ``report_render``.

Holds the "build" half of report finalization -- loading a run's store
data and shaping it into the payload/markdown pair -- kept separate from
the "publish" half (the safety gate, persistence, and event emission) so
each stays independently sized and testable. Every name is re-exported
from ``app.report_render``, which remains the stable import and
monkeypatch surface.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from app import store
from app.elo import live_leaderboard, rank_for_publication
from app.knowledge_facts import derive_knowledge_facts
from app.report_content import (
    _agent_insights,
    _exclude_unsafe_hypotheses,
    _idea_buckets,
    _knowledge_base_topics,
    _released_claim_evidence,
    _synthesized_knowledge_base_topics,
    _verified_hypothesis_count,
)
from app.report_markdown import (
    ReportMarkdownInputs,
    ReportPayloadInputs,
    build_report_payload,
    render_report_markdown,
)


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
        prepared_at: Epoch seconds this report was built, rendered as the
            header's provenance and research-purposes-only caution line.
            None omits that line rather than stating a date via the wall
            clock.
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
    prepared_at: float | None = None
    db_path: str | None = None


# The pre-bundle name, kept so existing imports and monkeypatch seams keep
# resolving.
_ReportBuildArgs = ReportRequest


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
    match_count: int
    reviews: list[dict[str, Any]]
    # Searches the deep-research loop recorded for this run, keyed by
    # run_id alone -- extended/ultra tiers only, empty on every other
    # run. Nothing new is written for the report; this reads what
    # ``retrieval_calls`` already has.
    retrieval_calls: list[dict[str, Any]]


class _BuiltReport(NamedTuple):
    """One run's report in both persisted forms.

    Attributes:
        payload: The JSON report payload.
        markdown: The rendered Markdown report.
        facts: Durable knowledge-base rows derived from this run's claim-
            evidence graph (audit G14), persisted once the report actually
            publishes; see ``report_render._publish_report``.
    """

    payload: dict[str, Any]
    markdown: str
    facts: list[dict[str, Any]]


def _build_report_content(run_id: str, req: _ReportBuildArgs) -> _BuiltReport:
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
    # Computed once and handed to both the payload and the markdown export
    # -- resolving it twice risks the two surfaces disagreeing on which
    # topics a run's Knowledge Base actually carries (see the root
    # AGENTS.md Gotchas entry on counts computed more than once).
    knowledge_base = _resolve_knowledge_base(data, req)
    return _BuiltReport(
        payload=_assemble_report_payload(data, req, knowledge_base),
        markdown=_render_report_content_markdown(data, req, knowledge_base),
        # Derived from the run's whole claim-evidence graph, not the
        # released subset the payload/markdown are scoped to -- the
        # knowledge base records everything the run found (see
        # app.knowledge_facts).
        facts=derive_knowledge_facts(data.claim_edges),
    )


def _render_report_content_markdown(
    data: _ReportData,
    req: _ReportBuildArgs,
    knowledge_base: list[dict[str, Any]],
) -> str:
    """Render the report markdown from already-gathered store data."""
    return render_report_markdown(
        ReportMarkdownInputs(
            research_goal=req.research_goal,
            provider=req.provider,
            # Report body is capped to the top 5 by Elo; the full set remains
            # available via the leaderboard and the hypotheses API endpoint.
            top_hypotheses=data.hyps[:5],
            meta_review=req.meta_review,
            citation_summary=req.citation_summary,
            research_overview=req.research_overview,
            knowledge_base=knowledge_base,
            setup=req.setup,
            prepared_at=req.prepared_at,
            summary=req.summary,
            claim_evidence=data.released_claim_edges,
            skills_used=req.skills_used,
            retrieval_calls=data.retrieval_calls,
            citations=data.citations,
            evidence=data.evidence,
        )
    )


def _resolve_knowledge_base(
    data: _ReportData, req: _ReportBuildArgs
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
        _exclude_unsafe_hypotheses(run_id, all_hyps, db_path, claim_edges)
    )
    evidence = store.list_evidence(run_id, db_path=db_path)
    released_claim_edges = _released_claim_evidence(hyps, claim_edges, evidence)
    # The payload wants two numbers, and one of them is already in hand:
    # ``summary_counts`` exists to avoid materializing tables the caller has,
    # and asking it here re-counted evidence beside three tables the report
    # never reads.
    return _ReportData(
        hyps=hyps,
        all_hyps=all_hyps,
        claim_edges=claim_edges,
        released_claim_edges=released_claim_edges,
        evidence=evidence,
        citations=store.list_citations(run_id, db_path=db_path),
        match_count=store.count_matches(run_id, db_path=db_path),
        # The reader's copy of every review row -- initial, deep
        # verification, and the mature cascade's distinctly labeled
        # full/simulation/recurrent results (audit E1).
        reviews=store.list_reviews(run_id, db_path=db_path),
        retrieval_calls=store.list_retrieval_calls(run_id, db_path=db_path),
    )


def _assemble_report_payload(
    data: _ReportData,
    req: _ReportBuildArgs,
    knowledge_base: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the report payload dict from already-gathered store data."""
    hyps, all_hyps, claim_edges = data.hyps, data.all_hyps, data.claim_edges
    payload = build_report_payload(
        ReportPayloadInputs(
            research_goal=req.research_goal,
            run_mode=req.run_mode,
            provider=req.provider,
            leaderboard=live_leaderboard(hyps),
            hypothesis_count=len(hyps),
            idea_count=len(all_hyps),
            verified_count=_verified_hypothesis_count(hyps, claim_edges),
            evidence_count=len(data.evidence),
            match_count=data.match_count,
            citation_summary=req.citation_summary,
            meta_review=req.meta_review,
            research_overview=req.research_overview,
            knowledge_base=knowledge_base,
            agent_insights=_agent_insights(hyps, claim_edges, req.meta_review),
            idea_buckets=_idea_buckets(hyps, all_hyps, claim_edges),
            claim_evidence=data.released_claim_edges,
            execution_time=req.execution_time,
        )
    )
    _attach_run_conditions(payload, data, req)
    return payload


def _attach_run_conditions(
    payload: dict[str, Any], data: _ReportData, req: _ReportBuildArgs
) -> None:
    """Attach what the reader needs to read the payload correctly.

    Not results: the conditions the run met. A section left blank by a
    fallback reads as missing data unless the report says generation
    failed, and retrieval the run never attempted is invisible in every
    other field -- an unreachable literature server routes the graph
    around every source and the run completes looking ordinary. The
    reviews ride along here because they are the same kind of fact: what
    was actually done to each idea, rather than the idea itself.
    """
    payload["degraded_sections"] = list(req.degraded_sections or [])
    payload["retrieval_degradation"] = req.retrieval_degradation
    payload["skills_used"] = dict(req.skills_used or {})
    # Every review row the drain persisted, so the report carries the
    # initial, deep-verification, and mature-cascade reviews to the reader
    # (audit E1); the ideas view reads the same rows from /reviews.
    payload["reviews"] = list(data.reviews)
