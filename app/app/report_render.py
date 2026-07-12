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
from app.safety import (
    POLICY_VERSION,
    apply_safety_gate,
    screen_contextual,
    screen_final,
)
from app.store import RunStatus

logger = logging.getLogger(__name__)


def _knowledge_base_topics(
    hypotheses: list[dict[str, Any]],
    claim_edges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build named technical topics from released hypotheses and claim links."""
    references_by_hypothesis: dict[str, list[str]] = {}
    for edge in claim_edges:
        if edge.get("label") != "supports":
            continue
        hypothesis_id = str(edge.get("hypothesis_id") or "")
        evidence_id = str(edge.get("evidence_id") or "")
        if evidence_id:
            references_by_hypothesis.setdefault(hypothesis_id, []).append(
                evidence_id
            )
    topics: list[dict[str, Any]] = []
    for hypothesis in hypotheses[:8]:
        hypothesis_id = str(hypothesis.get("id") or "")
        topics.append(
            {
                "id": f"topic-{hypothesis_id}",
                "title": str(hypothesis.get("title") or "Mechanistic finding"),
                "summary": str(
                    hypothesis.get("mechanism")
                    or hypothesis.get("statement")
                    or ""
                ),
                "detail": str(
                    hypothesis.get("experimental_context")
                    or hypothesis.get("expected_effect")
                    or ""
                ),
                "reference_ids": sorted(
                    set(references_by_hypothesis.get(hypothesis_id, []))
                ),
            }
        )
    return topics


def _synthesized_knowledge_base_topics(
    research_overview: dict[str, Any] | None,
    evidence: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Map engine-synthesized source titles to durable evidence identifiers."""
    if not isinstance(research_overview, dict):
        return []
    raw_topics = research_overview.get("knowledge_base")
    if not isinstance(raw_topics, list):
        return []
    evidence_id_by_title = {
        str(item.get("title") or ""): str(item.get("id") or "")
        for item in evidence
    }
    topics: list[dict[str, Any]] = []
    for raw in raw_topics:
        if not isinstance(raw, dict):
            continue
        references = raw.get("references") or []
        reference_ids = sorted(
            {
                evidence_id_by_title.get(str(ref.get("title") or ""), "")
                for ref in references
                if isinstance(ref, dict)
            }
            - {""}
        )
        if not reference_ids:
            continue
        topics.append(
            {
                "id": str(raw.get("id") or f"topic-{len(topics) + 1}"),
                "title": str(raw.get("title") or "Technical topic"),
                "summary": str(raw.get("summary") or ""),
                "detail": str(raw.get("detail") or ""),
                "uncertainty": str(raw.get("uncertainty") or ""),
                "reference_ids": reference_ids,
            }
        )
    return topics


def _agent_insights(
    hypotheses: list[dict[str, Any]],
    claim_edges: list[dict[str, Any]],
    meta_review: dict[str, Any] | None,
) -> dict[str, Any]:
    """Derive visible findings, uncertainty, contradictions, and experiments."""
    meta = meta_review or {}
    return {
        "key_findings": [
            str(hypothesis.get("statement") or hypothesis.get("title") or "")
            for hypothesis in hypotheses[:5]
        ],
        "uncertainties": [
            str(item) for item in meta.get("common_weaknesses", [])
        ],
        "contradictions": [
            str(edge.get("claim_text") or edge.get("claim_id") or "")
            for edge in claim_edges
            if edge.get("label") == "contradicts"
        ],
        "recommended_directions": [
            str(item) for item in meta.get("strategic_recommendations", [])
        ],
        "next_experiments": [
            str(hypothesis.get("experimental_context") or "")
            for hypothesis in hypotheses[:5]
            if hypothesis.get("experimental_context")
        ],
    }


def _idea_buckets(
    safe_hypotheses: list[dict[str, Any]],
    all_hypotheses: list[dict[str, Any]],
    claim_edges: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Classify released leaders and excluded ideas with explicit reasons."""
    safe_ids = {str(hypothesis.get("id")) for hypothesis in safe_hypotheses}
    edge_reasons: dict[str, set[str]] = {}
    for edge in claim_edges:
        if edge.get("label") == "supports":
            continue
        edge_reasons.setdefault(str(edge.get("hypothesis_id")), set()).add(
            "Evidence verification did not support every material claim."
        )
    high_potential = [
        {
            "id": str(hypothesis.get("id")),
            "title": str(hypothesis.get("title") or "Untitled idea"),
            "reason": (
                "Released by safety and evidence gates and ranked by Elo."
            ),
        }
        for hypothesis in safe_hypotheses[:5]
    ]
    non_viable = []
    for hypothesis in all_hypotheses:
        hypothesis_id = str(hypothesis.get("id"))
        if hypothesis_id in safe_ids:
            continue
        reasons = sorted(edge_reasons.get(hypothesis_id, set()))
        if is_blocking_status(str(hypothesis.get("safety_status") or "")):
            reasons.append("The scientific safety review blocked this idea.")
        non_viable.append(
            {
                "id": hypothesis_id,
                "title": str(hypothesis.get("title") or "Untitled idea"),
                "reason": " ".join(reasons)
                or "The release gate excluded this idea.",
            }
        )
    return {"high_potential": high_potential, "non_viable": non_viable}


def _unverified_hypothesis_ids(run_id: str, db_path: str | None) -> set[str]:
    """Ids of hypotheses with a claim that failed publication readiness.

    The pre-tournament claim grounding (``claim_grounding``) persisted the
    claim-evidence graph; a hypothesis with a contradicted or insufficient edge
    failed the evidence policy and must not rank or publish categorically.
    """
    return {
        str(edge["hypothesis_id"])
        for edge in store.list_claim_evidence(run_id, db_path=db_path)
        if edge.get("label") != "supports"
    }


def _exclude_unsafe_hypotheses(
    run_id: str,
    hyps: list[dict[str, Any]],
    db_path: str | None,
    *,
    require_verified_claims: bool = True,
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
        require_verified_claims: Whether insufficient claim evidence excludes
            the hypothesis. False is reserved for explicit mock fixtures.

    Returns:
        The hypotheses safe to synthesize, in the original order.
    """
    unverified = _unverified_hypothesis_ids(run_id, db_path)
    safe: list[dict[str, Any]] = []
    for hyp in hyps:
        if hyp.get("status") == "rejected":
            continue
        # Faithful publication gate: every material claim must be supported
        # before the hypothesis can enter synthesis. Explicit mock workflows
        # remain compatibility fixtures and are never credited as science.
        if require_verified_claims and str(hyp.get("id")) in unverified:
            logger.warning(
                "Excluding hypothesis %s from synthesis: unverified claim",
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
    hyps = _exclude_unsafe_hypotheses(
        run_id,
        all_hyps,
        db_path,
        require_verified_claims=provider != "mock",
    )
    counts = store.summary_counts(run_id, db_path=db_path)
    leaderboard = live_leaderboard(hyps)
    claim_edges = store.list_claim_evidence(run_id, db_path=db_path)
    evidence = store.list_evidence(run_id, db_path=db_path)
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
    approved = store.safety_stage_is_approved(
        run_id, "final", POLICY_VERSION, db_path=db_path
    )
    if provider != "mock" and not approved:
        final = await screen_contextual(markdown, "final", deterministic=final)
    async for event in apply_safety_gate(run_id, final, emit, db_path=db_path):
        yield event
    if final.decision in {"block", "hold"}:
        logger.warning(
            "Report finalize withheld for run %s by the final safety gate.",
            run_id,
        )
        return

    # Scientific readiness is independent of lexical misuse screening. A run
    # with hypotheses but no evidence-ready proposal must remain blocked rather
    # than publishing an empty or categorically unsupported Goal Report.
    if provider != "mock" and not payload.get("leaderboard"):
        reason = "No hypothesis passed the claim-level evidence release gate."
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
