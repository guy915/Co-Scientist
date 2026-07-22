"""Shared report finalization for the workflow provider.

Homed separately from ``engine_adapter`` so building the report payload,
rendering its markdown, running the final safety gate, and emitting the
report/completed events stay independently nameable/testable, through one
implementation.

The report content builders live in ``report_markdown``, the event-payload
helpers in ``report_events``, and the content-derivation helpers (topics,
insights, buckets, claim filters) in ``report_content``; their names are
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
from app.report_events import EmitFn as EmitFn
from app.report_events import article_stub as article_stub
from app.report_events import emit_cancel_or_pause as emit_cancel_or_pause
from app.report_events import hypothesis_stub as hypothesis_stub
from app.report_events import make_emitter as make_emitter
from app.report_events import match_stub as match_stub
from app.report_markdown import build_report_payload, render_report_markdown
from app.report_markdown import (
    format_deep_verification_critique as format_deep_verification_critique,
)
from app.safety import (
    SafetyDecision,
    apply_safety_gate,
    screen_final,
    screen_with_escalation,
)
from app.store import RunStatus

logger = logging.getLogger(__name__)


class _ReportBuildArgs(NamedTuple):
    """Bundled ``finalize_report`` arguments threaded through its pipeline."""

    research_goal: str
    run_mode: str
    provider: str
    citation_summary: dict[str, int] | None
    meta_review: dict[str, Any] | None
    research_overview: dict[str, Any] | None
    execution_time: float | None
    summary: str | None
    db_path: str | None


class _ReportData(NamedTuple):
    """Gathered hypotheses, evidence, claim edges, and counts for a run."""

    hyps: list[dict[str, Any]]
    all_hyps: list[dict[str, Any]]
    claim_edges: list[dict[str, Any]]
    released_claim_edges: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    counts: dict[str, int]


def _build_report_content(
    *,
    run_id: str,
    research_goal: str,
    run_mode: str,
    provider: str,
    citation_summary: dict[str, int] | None,
    meta_review: dict[str, Any] | None,
    research_overview: dict[str, Any] | None,
    execution_time: float | None,
    summary: str | None,
    db_path: str | None,
) -> tuple[dict[str, Any], str]:
    """Gather store data and build the report payload and markdown.

    Leaderboard, top hypotheses, and every row count are read from the store
    -- the drain has already persisted everything the payload counts, so the
    counts have one definition across providers. Delegates to
    ``_gather_report_data`` for the store reads, ``_assemble_report_payload``
    for the payload dict, and ``_render_report_content_markdown`` for the
    markdown; see those for the per-argument contract.

    Returns:
        A tuple of (report payload, rendered markdown).
    """
    data = _gather_report_data(run_id, db_path)
    shared: dict[str, Any] = {
        "research_goal": research_goal,
        "provider": provider,
        "meta_review": meta_review,
        "citation_summary": citation_summary,
        "research_overview": research_overview,
    }
    payload = _assemble_report_payload(
        data=data, run_mode=run_mode, execution_time=execution_time, **shared
    )
    markdown = _render_report_content_markdown(
        data=data, summary=summary, **shared
    )
    return payload, markdown


def _render_report_content_markdown(
    *,
    data: _ReportData,
    research_goal: str,
    provider: str,
    meta_review: dict[str, Any] | None,
    citation_summary: dict[str, int] | None,
    research_overview: dict[str, Any] | None,
    summary: str | None,
) -> str:
    """Render the report markdown from already-gathered store data."""
    return render_report_markdown(
        research_goal=research_goal,
        provider=provider,
        # Report body is capped to the top 5 by Elo; the full set remains
        # available via the leaderboard and the hypotheses API endpoint.
        top_hypotheses=data.hyps[:5],
        meta_review=meta_review,
        citation_summary=citation_summary,
        research_overview=research_overview,
        summary=summary,
        claim_evidence=data.released_claim_edges,
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
    counts = store.summary_counts(run_id, db_path=db_path)
    return _ReportData(
        hyps=hyps,
        all_hyps=all_hyps,
        claim_edges=claim_edges,
        released_claim_edges=released_claim_edges,
        evidence=evidence,
        counts=counts,
    )


def _assemble_report_payload(
    *,
    data: _ReportData,
    research_goal: str,
    run_mode: str,
    provider: str,
    citation_summary: dict[str, int] | None,
    meta_review: dict[str, Any] | None,
    research_overview: dict[str, Any] | None,
    execution_time: float | None,
) -> dict[str, Any]:
    """Build the report payload dict from already-gathered store data."""
    hyps, all_hyps, claim_edges = data.hyps, data.all_hyps, data.claim_edges
    synthesized_topics = _synthesized_knowledge_base_topics(
        research_overview, data.evidence
    )
    return build_report_payload(
        research_goal=research_goal,
        run_mode=run_mode,
        provider=provider,
        leaderboard=live_leaderboard(hyps),
        hypothesis_count=len(hyps),
        evidence_count=data.counts["evidence"],
        match_count=data.counts["matches"],
        citation_summary=citation_summary,
        meta_review=meta_review,
        research_overview=research_overview,
        knowledge_base=(
            synthesized_topics or _knowledge_base_topics(hyps, claim_edges)
        ),
        agent_insights=_agent_insights(hyps, claim_edges, meta_review),
        idea_buckets=_idea_buckets(hyps, all_hyps, claim_edges),
        claim_evidence=data.released_claim_edges,
        execution_time=execution_time,
    )


async def finalize_report(
    *,
    run_id: str,
    research_goal: str,
    run_mode: str,
    provider: str,
    citation_summary: dict[str, int] | None,
    meta_review: dict[str, Any] | None,
    research_overview: dict[str, Any] | None,
    emit: EmitFn,
    execution_time: float | None = None,
    summary: str | None = None,
    resumed: bool = False,
    db_path: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Build, screen, persist, and emit a run's final report.

    Single finalize path both providers invoke after their drain; order
    enforced by ``_finalize_report_pipeline``.

    Yields:
        Event dicts to forward on the workflow's event stream.
    """
    logger.info("Finalizing report for run %s (provider=%s).", run_id, provider)
    if resumed and _report_already_published(run_id, db_path=db_path):
        return
    req = _ReportBuildArgs(
        research_goal=research_goal,
        run_mode=run_mode,
        provider=provider,
        citation_summary=citation_summary,
        meta_review=meta_review,
        research_overview=research_overview,
        execution_time=execution_time,
        summary=summary,
        db_path=db_path,
    )
    async for event in _finalize_report_pipeline(run_id, req, emit):
        yield event


async def _finalize_report_pipeline(
    run_id: str, req: _ReportBuildArgs, emit: EmitFn
) -> AsyncIterator[dict[str, Any]]:
    """Build, safety-gate, and publish a run's final report.

    Order matches the shared contract documented on ``finalize_report``.
    """
    payload, markdown, blocked, gate_events = await _build_and_gate_report(
        run_id, req, emit
    )
    for event in gate_events:
        yield event
    if blocked:
        return

    if _readiness_blocked(payload, req.provider, run_id, db_path=req.db_path):
        async for event in _block_for_empty_leaderboard(
            run_id, req.provider, emit, db_path=req.db_path
        ):
            yield event
        return

    async for event in _publish_report(
        run_id, req.research_goal, payload, markdown, emit, db_path=req.db_path
    ):
        yield event


async def _build_and_gate_report(
    run_id: str, req: _ReportBuildArgs, emit: EmitFn
) -> tuple[dict[str, Any], str, bool, list[dict[str, Any]]]:
    """Build the report content and run it through the final safety gate.

    Returns:
        A tuple of (payload, markdown, blocked, safety-gate events to yield
        in order before checking ``blocked``).
    """
    payload, markdown = _build_report_content(
        run_id=run_id,
        research_goal=req.research_goal,
        run_mode=req.run_mode,
        provider=req.provider,
        citation_summary=req.citation_summary,
        meta_review=req.meta_review,
        research_overview=req.research_overview,
        execution_time=req.execution_time,
        summary=req.summary,
        db_path=req.db_path,
    )
    final = await _screen_final_report(
        run_id, markdown, req.provider, db_path=req.db_path
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
    return payload, markdown, blocked, gate_events


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
        "final",
        markdown,
        screen_final(markdown),
        provider=provider,
        db_path=db_path,
    )


async def _publish_report(
    run_id: str,
    research_goal: str,
    payload: dict[str, Any],
    markdown: str,
    emit: EmitFn,
    *,
    db_path: str | None,
) -> AsyncIterator[dict[str, Any]]:
    """Save the report, emit it, mark the run completed, and notify."""
    saved = store.save_report(run_id, payload, markdown, db_path=db_path)
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
        run_id,
        stage="scientific_readiness",
        decision="block",
        reason=reason,
        matches=[],
        db_path=db_path,
    )
    store.update_run_status(
        run_id, RunStatus.BLOCKED, error=reason, db_path=db_path
    )
    logger.warning("Report finalize blocked for run %s: %s", run_id, reason)
    yield await emit("status", {"status": "blocked", "reason": reason})


def _enqueue_completion_notification(
    run_id: str,
    research_goal: str,
    report_id: str,
    *,
    db_path: str | None,
) -> None:
    """Enqueue the completion email task when the run opted in."""
    run = store.get_run(run_id, db_path=db_path)
    notification = (
        run.config.get("completion_notification") if run else {}
    ) or {}
    if not (notification.get("enabled") and notification.get("email")):
        return
    store.enqueue_task(
        run_id,
        "notification.email",
        {
            "run_id": run_id,
            "email": notification["email"],
            "title": run.title or research_goal if run else research_goal,
        },
        idempotency_key=f"completion-email:{report_id}",
        priority=-100,
        dependencies=(),
        provenance={"trigger": "Goal Report completed"},
        budget={"delivery_attempts": 3},
        max_attempts=3,
        db_path=db_path,
    )
