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
from typing import Any

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
    apply_safety_gate,
    screen_final,
    screen_with_escalation,
)
from app.store import RunStatus

logger = logging.getLogger(__name__)


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
    counts have one definition across providers.

    Args:
        run_id: Identifier of the run being finalized.
        research_goal: The natural-language research goal.
        run_mode: Canonical run mode.
        provider: ``"engine"`` or ``"mock"``.
        citation_summary: Citation state -> count, or None.
        meta_review: Meta-review synthesis dict, or None.
        research_overview: Research-overview payload, or None.
        execution_time: Wall-clock seconds, when the provider tracks it.
        summary: Optional lead paragraph for the markdown ``## Summary``.
        db_path: Optional override for the SQLite database path.

    Returns:
        A tuple of (report payload, rendered markdown).
    """
    all_hyps = store.list_hypotheses(run_id, db_path=db_path)
    claim_edges = store.list_claim_evidence(run_id, db_path=db_path)
    # Exclude any hypothesis a per-hypothesis safety review blocks (recorded as
    # an audit decision) before it can appear in the leaderboard or top ideas.
    hyps = _exclude_unsafe_hypotheses(run_id, all_hyps, db_path, claim_edges)
    counts = store.summary_counts(run_id, db_path=db_path)
    leaderboard = live_leaderboard(hyps)
    evidence = store.list_evidence(run_id, db_path=db_path)
    released_claim_edges = _released_claim_evidence(hyps, claim_edges, evidence)
    synthesized_topics = _synthesized_knowledge_base_topics(
        research_overview, evidence
    )
    payload = build_report_payload(
        research_goal=research_goal,
        run_mode=run_mode,
        provider=provider,
        leaderboard=leaderboard,
        hypothesis_count=len(hyps),
        evidence_count=counts["evidence"],
        match_count=counts["matches"],
        citation_summary=citation_summary,
        meta_review=meta_review,
        research_overview=research_overview,
        knowledge_base=(
            synthesized_topics or _knowledge_base_topics(hyps, claim_edges)
        ),
        agent_insights=_agent_insights(hyps, claim_edges, meta_review),
        idea_buckets=_idea_buckets(hyps, all_hyps, claim_edges),
        claim_evidence=released_claim_edges,
        execution_time=execution_time,
    )
    markdown = render_report_markdown(
        research_goal=research_goal,
        provider=provider,
        # Report body is capped to the top 5 by Elo; the full set remains
        # available via the leaderboard and the hypotheses API endpoint.
        top_hypotheses=hyps[:5],
        meta_review=meta_review,
        citation_summary=citation_summary,
        research_overview=research_overview,
        summary=summary,
        claim_evidence=released_claim_edges,
    )
    return payload, markdown


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

    This is the single finalize path both providers invoke after their drain,
    so the final safety gate and the report/completed emission live in one
    place. Leaderboard, top hypotheses, and every row count are read from the
    store -- the drain has already persisted everything the payload counts, so
    the counts have one definition across providers.

    Order matches the shared contract: build payload -> render markdown ->
    screen_final + apply_safety_gate -> (unless blocked) save report -> emit
    report -> mark completed. A hard block records the blocked status via the
    safety gate and returns without persisting a report.

    Args:
        run_id: Identifier of the run being finalized.
        research_goal: The natural-language research goal.
        run_mode: Canonical run mode.
        provider: ``"engine"`` or ``"mock"``.
        citation_summary: Citation state -> count, or None.
        meta_review: Meta-review synthesis dict, or None.
        research_overview: Research-overview payload, or None.
        emit: The provider's event emitter, called as ``emit(type, payload)``.
        execution_time: Wall-clock seconds, when the provider tracks it.
        summary: Optional lead paragraph for the markdown ``## Summary``.
        resumed: When True, apply the single-publish idempotency guard so a
            resumed run reaching the end twice does not re-publish.
        db_path: Optional override for the SQLite database path.

    Yields:
        Event dicts to forward on the workflow's event stream.
    """
    logger.info("Finalizing report for run %s (provider=%s).", run_id, provider)
    # Single-publish guard (Milestone 4 idempotency): a *resumed* run that
    # reaches the end a second time must not publish a second report or emit a
    # second completion. Gated on ``resumed`` so a fresh run (and the
    # determinism replay tests) always finalize; only a resume checks whether
    # the report was already published before this restart.
    if resumed and store.get_latest_report(run_id, db_path=db_path) is not None:
        logger.info(
            "Report already published for run %s; skipping duplicate finalize.",
            run_id,
        )
        return
    payload, markdown = _build_report_content(
        run_id=run_id,
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

    final = await screen_with_escalation(
        run_id,
        "final",
        markdown,
        screen_final(markdown),
        provider=provider,
        db_path=db_path,
    )
    async for event in apply_safety_gate(run_id, final, emit, db_path=db_path):
        yield event
    if final.decision in {"block", "hold"}:
        logger.warning(
            "Report finalize withheld for run %s by the final safety gate.",
            run_id,
        )
        return

    # Under the rank-and-publish policy the leaderboard is empty only when every
    # idea was withheld -- contradicted by the evidence or blocked by the safety
    # review -- leaving nothing publishable. Unsupported (but non-contradicted)
    # ideas are published with an "Unverified" badge, so they never reach here.
    # Only real-backed runs are hard-blocked: an offline-backed run's
    # deterministic science is illustrative, never withheld for an empty board.
    # Keyed on the run's persisted backend (falling back to the provider when
    # the row is gone), not the process offline_mode().
    offline = store.run_offline_backed(
        run_id, missing_run_fallback=provider == "mock", db_path=db_path
    )
    if not offline and not payload.get("leaderboard"):
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
        return

    saved = store.save_report(run_id, payload, markdown, db_path=db_path)
    yield await emit("report", {**payload, "report_id": saved["id"]})
    store.update_run_status(run_id, RunStatus.COMPLETED, db_path=db_path)
    run = store.get_run(run_id, db_path=db_path)
    notification = (
        run.config.get("completion_notification") if run else {}
    ) or {}
    if notification.get("enabled") and notification.get("email"):
        store.enqueue_task(
            run_id,
            "notification.email",
            {
                "run_id": run_id,
                "email": notification["email"],
                "title": run.title or research_goal if run else research_goal,
            },
            idempotency_key=f"completion-email:{saved['id']}",
            priority=-100,
            dependencies=(),
            provenance={"trigger": "Goal Report completed"},
            budget={"delivery_attempts": 3},
            max_attempts=3,
            db_path=db_path,
        )
    logger.info(
        "Report finalized for run %s (report_id=%s).", run_id, saved["id"]
    )
    yield await emit("status", {"status": "completed"})
