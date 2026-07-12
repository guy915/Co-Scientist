"""Shared report finalization for both workflow providers.

Homed here (rather than inside a single provider) so the real-engine drain
(``engine_adapter``) and the deterministic mock (``mock_workflow``) build the
report payload, render its markdown, run the final safety gate, and emit the
report/completed events through one implementation -- keeping the persisted
report, the final-gate policy, and the streamed event shapes identical across
providers.

The report content builders live in ``report_markdown`` and the event-payload
helpers in ``report_events``; the names both providers consume are re-exported
here so callers keep a single ``app.report_render`` import surface.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from app import store
from app.elo import live_leaderboard
from app.hypothesis_safety import (
    is_blocking_status,
    review_hypothesis_safety,
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
from app.safety import apply_safety_gate, screen_final
from app.store import RunStatus

logger = logging.getLogger(__name__)


def _contradicted_hypothesis_ids(run_id: str, db_path: str | None) -> set[str]:
    """Ids of hypotheses with a contradicted claim (publication-gate block).

    The pre-tournament claim grounding (``claim_grounding``) persisted the
    claim-evidence graph; a hypothesis with any ``contradicts`` edge failed the
    publication gate (SSR §7) and must not rank or publish.
    """
    return {
        str(edge["hypothesis_id"])
        for edge in store.list_claim_evidence(run_id, db_path=db_path)
        if edge.get("label") == "contradicts"
    }


def _exclude_unsafe_hypotheses(
    run_id: str,
    hyps: list[dict[str, Any]],
    db_path: str | None,
) -> list[dict[str, Any]]:
    """Drop hypotheses a safety review or the publication gate blocks.

    Milestone 5/6/M9 wiring: a hypothesis whose safety review is prohibited/
    ethical/uncertain (SSR §1, §10) or whose claims are contradicted by the
    evidence (the publication gate, SSR §7) must not appear in the final
    report's leaderboard or top ideas. The pre-tournament screen and claim
    grounding already persisted each hypothesis's ``safety_status`` and
    claim-evidence graph and recorded their audit rows, so the common path just
    honors those. A legacy row with no persisted safety status (older runs) is
    re-reviewed and audited here as a fallback. Benign hypotheses pass through
    unchanged.

    Args:
        run_id: The run whose report is being built.
        hyps: The run's hypotheses (store rows with a ``statement`` and,
            normally, a persisted ``safety_status``).
        db_path: Optional override for the SQLite database path.

    Returns:
        The hypotheses safe to synthesize, in the original order.
    """
    contradicted = _contradicted_hypothesis_ids(run_id, db_path)
    safe: list[dict[str, Any]] = []
    for hyp in hyps:
        # Publication gate: a contradicted claim blocks synthesis.
        if str(hyp.get("id")) in contradicted:
            logger.warning(
                "Excluding hypothesis %s from synthesis: contradicted claim",
                hyp.get("id"),
            )
            continue
        status = hyp.get("safety_status")
        # Common path: the screen already decided; honor the persisted status
        # without re-reviewing or double-recording the audit row.
        if status and status != "pending":
            if is_blocking_status(str(status)):
                logger.warning(
                    "Excluding hypothesis %s from synthesis: %s",
                    hyp.get("id"),
                    status,
                )
                continue
            safe.append(hyp)
            continue
        # Fallback for a row the screen never touched (legacy run).
        review = review_hypothesis_safety(str(hyp.get("statement") or ""))
        if review.blocks_tournament:
            store.add_safety_decision(
                run_id,
                stage="hypothesis",
                decision="block",
                reason=(
                    f"hypothesis {hyp.get('id')}: {review.outcome.value} "
                    f"({review.reason})"
                ),
                matches=list(review.matches),
                db_path=db_path,
            )
            logger.warning(
                "Excluding hypothesis %s from synthesis: %s",
                hyp.get("id"),
                review.outcome.value,
            )
            continue
        safe.append(hyp)
    return safe


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
    # Exclude any hypothesis a per-hypothesis safety review blocks (recorded as
    # an audit decision) before it can appear in the leaderboard or top ideas.
    hyps = _exclude_unsafe_hypotheses(run_id, all_hyps, db_path)
    counts = store.summary_counts(run_id, db_path=db_path)
    leaderboard = live_leaderboard(hyps)
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

    final = screen_final(markdown)
    async for event in apply_safety_gate(run_id, final, emit, db_path=db_path):
        yield event
    if final.decision == "block":
        logger.warning(
            "Report finalize blocked for run %s by the final safety gate.",
            run_id,
        )
        return

    saved = store.save_report(run_id, payload, markdown, db_path=db_path)
    yield await emit("report", {**payload, "report_id": saved["id"]})
    store.update_run_status(run_id, RunStatus.COMPLETED, db_path=db_path)
    logger.info(
        "Report finalized for run %s (report_id=%s).", run_id, saved["id"]
    )
    yield await emit("status", {"status": "completed"})
