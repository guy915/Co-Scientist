"""Shared report finalization for the workflow provider.

Homed separately from ``engine_adapter`` so building the report payload,
rendering its markdown, running the final safety gate, and emitting the
report/completed events stay independently nameable/testable, through one
implementation.

The report content builders live in ``report_markdown``, the event-payload
helpers in ``report_events``, the content-derivation helpers (topics,
insights, buckets, claim filters) in ``report_content``, and the
completion-email scheduling in ``report_notify``; their names are
re-exported here so callers keep a single ``app.report_render`` import
surface.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any, NamedTuple

from app import store
from app.elo import live_leaderboard
from app.report_content import _agent_insights as _agent_insights
from app.report_content import (
    _contradicted_hypothesis_ids as _contradicted_hypothesis_ids,
)
from app.report_content import (
    _exclude_unsafe_hypotheses as _exclude_unsafe_hypotheses,
)
from app.report_content import _idea_buckets as _idea_buckets
from app.report_content import (
    _knowledge_base_topics as _knowledge_base_topics,
)
from app.report_content import (
    _released_claim_evidence as _released_claim_evidence,
)
from app.report_content import (
    _synthesized_knowledge_base_topics as _synthesized_knowledge_base_topics,
)
from app.report_content import (
    _unverified_hypothesis_ids as _unverified_hypothesis_ids,
)
from app.report_content import (
    _verified_hypothesis_count as _verified_hypothesis_count,
)
from app.report_events import EmitFn as EmitFn
from app.report_events import article_stub as article_stub
from app.report_events import emit_cancel_or_pause as emit_cancel_or_pause
from app.report_events import hypothesis_stub as hypothesis_stub
from app.report_events import make_emitter as make_emitter
from app.report_events import match_stub as match_stub
from app.report_markdown import (
    ReportMarkdownInputs,
    ReportPayloadInputs,
    build_report_payload,
    render_report_markdown,
)
from app.report_markdown import (
    format_deep_verification_critique as format_deep_verification_critique,
)
from app.report_notify import (
    _completion_email_deliverable as _completion_email_deliverable,
)
from app.report_notify import (
    _completion_email_task as _completion_email_task,
)
from app.report_notify import (
    _enqueue_completion_notification as _enqueue_completion_notification,
)
from app.safety import (
    SafetyDecision,
    ScreenSubject,
    apply_safety_gate,
    screen_final,
    screen_with_escalation,
)
from app.store import RunStatus

logger = logging.getLogger(__name__)


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
        execution_time: Wall-clock seconds the run took, when measured.
        summary: Optional summary paragraph for the markdown header.
        db_path: Optional override for the SQLite database path.
    """

    research_goal: str
    run_mode: str
    provider: str
    citation_summary: dict[str, int] | None = None
    meta_review: dict[str, Any] | None = None
    research_overview: dict[str, Any] | None = None
    degraded_sections: list[str] | None = None
    execution_time: float | None = None
    summary: str | None = None
    db_path: str | None = None


# The pre-bundle name, kept so existing imports and monkeypatch seams keep
# resolving.
_ReportBuildArgs = ReportRequest


class _ReportData(NamedTuple):
    """Gathered hypotheses, evidence, claim edges, and counts for a run."""

    hyps: list[dict[str, Any]]
    all_hyps: list[dict[str, Any]]
    claim_edges: list[dict[str, Any]]
    released_claim_edges: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    match_count: int


class _BuiltReport(NamedTuple):
    """One run's report in both persisted forms."""

    payload: dict[str, Any]
    markdown: str


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
    return _BuiltReport(
        payload=_assemble_report_payload(data, req),
        markdown=_render_report_content_markdown(data, req),
    )


def _render_report_content_markdown(
    data: _ReportData, req: _ReportBuildArgs
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
            summary=req.summary,
            claim_evidence=data.released_claim_edges,
        )
    )


def _gather_report_data(run_id: str, db_path: str | None) -> _ReportData:
    """Load and safety-filter a run's hypotheses, evidence, and claim edges."""
    all_hyps = store.list_hypotheses(run_id, db_path=db_path)
    claim_edges = store.list_claim_evidence(run_id, db_path=db_path)
    # Exclude any hypothesis a per-hypothesis safety review blocks (recorded as
    # an audit decision) before it can appear in the leaderboard or top ideas.
    hyps = _exclude_unsafe_hypotheses(run_id, all_hyps, db_path, claim_edges)
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
        match_count=store.count_matches(run_id, db_path=db_path),
    )


def _assemble_report_payload(
    data: _ReportData, req: _ReportBuildArgs
) -> dict[str, Any]:
    """Build the report payload dict from already-gathered store data."""
    hyps, all_hyps, claim_edges = data.hyps, data.all_hyps, data.claim_edges
    synthesized_topics = _synthesized_knowledge_base_topics(
        req.research_overview, data.evidence
    )
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
            knowledge_base=(
                synthesized_topics or _knowledge_base_topics(hyps, claim_edges)
            ),
            agent_insights=_agent_insights(hyps, claim_edges, req.meta_review),
            idea_buckets=_idea_buckets(hyps, all_hyps, claim_edges),
            claim_evidence=data.released_claim_edges,
            execution_time=req.execution_time,
        )
    )
    # A section left blank by a fallback reads as missing data unless the
    # report says generation failed; the engine records the degraded nodes.
    payload["degraded_sections"] = list(req.degraded_sections or [])
    return payload


async def finalize_report(
    run_id: str,
    req: ReportRequest,
    emit: EmitFn,
    *,
    resumed: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """Build, screen, persist, and emit a run's final report.

    The run's single finalize path, invoked after its drain; order enforced
    by ``_finalize_report_pipeline``.

    Args:
        run_id: Identifier of the run being finalized.
        req: The drained report inputs; see :class:`ReportRequest`.
        emit: The run's event emitter.
        resumed: When true, a report already published for this run makes
            this a no-op rather than a duplicate finalize.

    Yields:
        Event dicts to forward on the workflow's event stream.
    """
    logger.info(
        "Finalizing report for run %s (provider=%s).", run_id, req.provider
    )
    if resumed and _report_already_published(run_id, db_path=req.db_path):
        return
    async for event in _finalize_report_pipeline(run_id, req, emit):
        yield event


async def _finalize_report_pipeline(
    run_id: str, req: _ReportBuildArgs, emit: EmitFn
) -> AsyncIterator[dict[str, Any]]:
    """Build, safety-gate, and publish a run's final report.

    Order matches the shared contract documented on ``finalize_report``.
    """
    built, blocked, gate_events = await _build_and_gate_report(
        run_id, req, emit
    )
    for event in gate_events:
        yield event
    if blocked:
        return
    async for event in _gate_readiness_and_publish(run_id, req, emit, built):
        yield event


async def _gate_readiness_and_publish(
    run_id: str,
    req: _ReportBuildArgs,
    emit: EmitFn,
    built: _BuiltReport,
) -> AsyncIterator[dict[str, Any]]:
    """Block an empty leaderboard, or publish the report otherwise.

    Split out of ``_finalize_report_pipeline`` to keep each step's branching
    independently readable; order matches the shared contract documented on
    ``finalize_report``.
    """
    if _readiness_blocked(
        built.payload, req.provider, run_id, db_path=req.db_path
    ):
        async for event in _block_for_empty_leaderboard(
            run_id, req.provider, emit, db_path=req.db_path
        ):
            yield event
        return
    async for event in _publish_report(
        run_id, req.research_goal, built, emit, db_path=req.db_path
    ):
        yield event


async def _build_and_gate_report(
    run_id: str, req: _ReportBuildArgs, emit: EmitFn
) -> tuple[_BuiltReport, bool, list[dict[str, Any]]]:
    """Build the report content and run it through the final safety gate.

    Returns:
        A tuple of (built report, blocked, safety-gate events to yield in
        order before checking ``blocked``).
    """
    built = _build_report_content(run_id, req)
    final = await _screen_final_report(
        run_id, built.markdown, req.provider, db_path=req.db_path
    )
    gate_events = [
        event
        async for event in apply_safety_gate(
            run_id, final, emit, db_path=req.db_path
        )
    ]
    blocked = final.decision in {"block", "hold"}
    if blocked:
        logger.warning(
            "Report finalize withheld for run %s by the final safety gate.",
            run_id,
        )
    return built, blocked, gate_events


def _report_already_published(run_id: str, *, db_path: str | None) -> bool:
    """Return whether a report is already saved for this run."""
    if store.get_latest_report(run_id, db_path=db_path) is None:
        return False
    logger.info(
        "Report already published for run %s; skipping duplicate finalize.",
        run_id,
    )
    return True


async def _screen_final_report(
    run_id: str,
    markdown: str,
    provider: str,
    *,
    db_path: str | None,
) -> SafetyDecision:
    """Run the final safety screen (with escalation) over the report text."""
    return await screen_with_escalation(
        run_id,
        ScreenSubject("final", markdown, screen_final(markdown)),
        provider=provider,
        db_path=db_path,
    )


async def _publish_report(
    run_id: str,
    research_goal: str,
    built: _BuiltReport,
    emit: EmitFn,
    *,
    db_path: str | None,
) -> AsyncIterator[dict[str, Any]]:
    """Save the report, emit it, mark the run completed, and notify."""
    payload = built.payload
    saved = store.save_report(run_id, payload, built.markdown, db_path=db_path)
    yield await emit("report", {**payload, "report_id": saved["id"]})
    store.update_run_status(run_id, RunStatus.COMPLETED, db_path=db_path)
    _enqueue_completion_notification(
        run_id, research_goal, saved["id"], db_path=db_path
    )
    logger.info(
        "Report finalized for run %s (report_id=%s).", run_id, saved["id"]
    )
    yield await emit("status", {"status": "completed"})


def _readiness_blocked(
    payload: dict[str, Any],
    provider: str,
    run_id: str,
    *,
    db_path: str | None,
) -> bool:
    """Return whether the run's empty leaderboard should hard-block release.

    Under the rank-and-publish policy the leaderboard is empty only when
    every idea was withheld -- contradicted by the evidence or blocked by the
    safety review -- leaving nothing publishable. Unsupported (but
    non-contradicted) ideas are published with an "Unverified" badge, so they
    never reach here. Only real-backed runs are hard-blocked: an
    offline-backed run's deterministic science is illustrative, never
    withheld for an empty board. Keyed on the run's persisted backend
    (falling back to the provider when the row is gone), not the process
    offline_mode().
    """
    offline = store.run_offline_backed(
        run_id, missing_run_fallback=provider == "mock", db_path=db_path
    )
    return not offline and not payload.get("leaderboard")


async def _block_for_empty_leaderboard(
    run_id: str,
    provider: str,
    emit: EmitFn,
    *,
    db_path: str | None,
) -> AsyncIterator[dict[str, Any]]:
    """Record the empty-leaderboard block, mark the run blocked, and emit it."""
    reason = (
        "No hypothesis could be published: every idea was either "
        "contradicted by the evidence or withheld by the safety review."
    )
    store.add_safety_decision(
        store.NewSafetyDecision(
            run_id=run_id,
            stage="scientific_readiness",
            decision="block",
            reason=reason,
            matches=[],
        ),
        db_path=db_path,
    )
    store.update_run_status(
        run_id, RunStatus.BLOCKED, error=reason, db_path=db_path
    )
    logger.warning("Report finalize blocked for run %s: %s", run_id, reason)
    yield await emit("status", {"status": "blocked", "reason": reason})
