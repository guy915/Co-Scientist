"""Shared report finalization for both workflow providers.

Homed here (rather than inside a single provider) so the real-engine drain
(``engine_adapter``) and the deterministic mock (``mock_workflow``) build the
report payload, render its markdown, run the final safety gate, and emit the
report/completed events through one implementation -- keeping the persisted
report, the final-gate policy, and the streamed event shapes identical across
providers.

The report content builders live in ``report_markdown`` and the event-payload
helpers in ``report_events``; both are re-exported here so callers keep a single
``app.report_render`` import surface.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from app import store
from app.elo import live_leaderboard
from app.report_events import EmitFn as EmitFn
from app.report_events import article_stub as article_stub
from app.report_events import hypothesis_stub as hypothesis_stub
from app.report_events import make_emitter as make_emitter
from app.report_events import match_stub as match_stub
from app.report_markdown import (
    _META_REVIEW_BULLET_SECTIONS as _META_REVIEW_BULLET_SECTIONS,
)

# Private render helpers moved to report_markdown are re-exported so their
# original ``app.report_render.<name>`` import paths stay stable.
from app.report_markdown import _append_if as _append_if
from app.report_markdown import _first as _first
from app.report_markdown import _has_aims_content as _has_aims_content
from app.report_markdown import _has_overview_content as _has_overview_content
from app.report_markdown import _render_aims_list as _render_aims_list
from app.report_markdown import _render_bullet_list as _render_bullet_list
from app.report_markdown import _render_citation_audit as _render_citation_audit
from app.report_markdown import (
    _render_directions_list as _render_directions_list,
)
from app.report_markdown import (
    _render_experiments_list as _render_experiments_list,
)
from app.report_markdown import (
    _render_hypothesis_entry as _render_hypothesis_entry,
)
from app.report_markdown import _render_impact as _render_impact
from app.report_markdown import (
    _render_meta_review_markdown as _render_meta_review_markdown,
)
from app.report_markdown import _render_nih_aim as _render_nih_aim
from app.report_markdown import (
    _render_nih_aims_section as _render_nih_aims_section,
)
from app.report_markdown import (
    _render_optional_paragraph as _render_optional_paragraph,
)
from app.report_markdown import (
    _render_overview_section as _render_overview_section,
)
from app.report_markdown import _render_probe as _render_probe
from app.report_markdown import _render_recommendation as _render_recommendation
from app.report_markdown import (
    _render_research_direction as _render_research_direction,
)
from app.report_markdown import (
    _render_strategic_recommendations as _render_strategic_recommendations,
)
from app.report_markdown import (
    _render_top_hypotheses_markdown as _render_top_hypotheses_markdown,
)
from app.report_markdown import build_report_payload as build_report_payload
from app.report_markdown import (
    format_deep_verification_critique as format_deep_verification_critique,
)
from app.report_markdown import render_report_markdown as render_report_markdown
from app.report_markdown import (
    render_research_overview_markdown as render_research_overview_markdown,
)
from app.safety import apply_safety_gate, screen_final
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
    hyps = store.list_hypotheses(run_id, db_path=db_path)
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
        db_path: Optional override for the SQLite database path.

    Yields:
        Event dicts to forward on the workflow's event stream.
    """
    logger.info("Finalizing report for run %s (provider=%s).", run_id, provider)
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
