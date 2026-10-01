"""Shared report finalization for the workflow provider.

Homed separately from ``engine_adapter`` so building the report payload,
rendering its markdown, running the final safety gate, and emitting the
report/completed events stay independently nameable/testable, through one
implementation.

The report content builders live in ``report_markdown``, the
content-derivation helpers (topics, insights, buckets, claim filters) in
``report_content``, the gathering and assembly of the payload/markdown pair
(``ReportRequest``, ``_BuiltReport``, ``_build_report_content``) in
``report_build``, and the completion-email scheduling in ``report_notify``;
the names callers use are re-exported here so ``app.report_render`` stays
their import surface. Run-event emission (``make_emitter`` and the event
stubs) lives in ``run_events``, outside the report cluster.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from app import store
from app.report_build import ReportRequest as ReportRequest
from app.report_build import _build_report_content as _build_report_content
from app.report_build import _BuiltReport as _BuiltReport
from app.report_build import _ReportBuildArgs as _ReportBuildArgs
from app.report_content import _agent_insights as _agent_insights
from app.report_content import (
    _contradicted_hypothesis_ids as _contradicted_hypothesis_ids,
)
from app.report_content import (
    _empty_leaderboard_reason as _empty_leaderboard_reason,
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
from app.report_markdown import (
    format_deep_verification_critique as format_deep_verification_critique,
)
from app.report_notify import (
    _enqueue_completion_notification as _enqueue_completion_notification,
)
from app.run_events import EmitFn
from app.safety import (
    SafetyDecision,
    ScreenSubject,
    apply_safety_gate,
    redact_matched_spans,
    redact_payload_text,
    screen_final,
    screen_with_escalation,
)
from app.store import RunStatus
from app.store.tasks_model import ScientificTask

logger = logging.getLogger(__name__)


async def finalize_report(
    run_id: str,
    req: ReportRequest,
    emit: EmitFn,
    *,
    resumed: bool = False,
    task: ScientificTask | None = None,
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
        task: The durable finalize task, when publication must verify its
            current lease in the same transaction as the report writes.

    Yields:
        Event dicts to forward on the workflow's event stream.
    """
    logger.info(
        "Finalizing report for run %s (provider=%s).", run_id, req.provider
    )
    if resumed and _report_already_published(run_id, db_path=req.db_path):
        return
    async for event in _finalize_report_pipeline(run_id, req, emit, task):
        yield event


async def _finalize_report_pipeline(
    run_id: str,
    req: _ReportBuildArgs,
    emit: EmitFn,
    task: ScientificTask | None,
) -> AsyncIterator[dict[str, Any]]:
    """Build, safety-gate, and publish a run's final report.

    Order matches the shared contract documented on ``finalize_report``.
    """
    built, blocked, gate_events = await _build_and_gate_report(
        run_id, req, emit, task
    )
    for event in gate_events:
        yield event
    if blocked:
        return
    async for event in _gate_readiness_and_publish(
        run_id, req, emit, built, task
    ):
        yield event


async def _gate_readiness_and_publish(
    run_id: str,
    req: _ReportBuildArgs,
    emit: EmitFn,
    built: _BuiltReport,
    task: ScientificTask | None,
) -> AsyncIterator[dict[str, Any]]:
    """Block an empty leaderboard, or publish the report otherwise.

    Split out of ``_finalize_report_pipeline`` to keep each step's branching
    independently readable; order matches the shared contract documented on
    ``finalize_report``.
    """
    if _readiness_blocked(built.payload):
        async for event in _block_for_empty_leaderboard(
            run_id, built, emit, db_path=req.db_path, task=task
        ):
            yield event
        return
    async for event in _publish_report(
        run_id,
        req.research_goal,
        built,
        emit,
        db_path=req.db_path,
        task=task,
    ):
        yield event


async def _build_and_gate_report(
    run_id: str,
    req: _ReportBuildArgs,
    emit: EmitFn,
    task: ScientificTask | None,
) -> tuple[_BuiltReport, bool, list[dict[str, Any]]]:
    """Build the report content and run it through the final safety gate.

    Returns:
        A tuple of (built report, blocked, safety-gate events to yield in
        order before checking ``blocked``).
    """
    built = await _build_report_content(run_id, req)
    final = await _screen_final_report(
        run_id, built.markdown, req.provider, db_path=req.db_path
    )
    if final.decision == "redact":
        built = _redacted_report(built, final)
    gate_events = [
        event
        async for event in apply_safety_gate(
            run_id, final, emit, db_path=req.db_path, task=task
        )
    ]
    blocked = final.decision in {"block", "hold"}
    if blocked:
        logger.warning(
            "Report finalize withheld for run %s by the final safety gate.",
            run_id,
        )
    return built, blocked, gate_events


def _redacted_report(
    built: _BuiltReport, decision: SafetyDecision
) -> _BuiltReport:
    """Apply a redact decision to every persisted form of the report.

    The payload and the markdown document are renderings of the same
    content, and both are saved and emitted, so scrubbing one would leave
    the original readable through the other -- through ``/report``, the
    ``report`` event, the run's event log, and the public share built from
    the same row.

    Args:
        built: The report as built, before publication.
        decision: The final-stage decision naming the spans to remove.

    Returns:
        The report with every matched span replaced in the payload and
        the markdown document.
    """
    matches = list(decision.matches)
    logger.warning(
        "Redacting %d matched span(s) from the report under the final "
        "safety gate.",
        len(matches),
    )
    return _BuiltReport(
        payload=redact_payload_text(built.payload, matches),
        markdown=redact_matched_spans(built.markdown, matches),
        # Facts are derived from claim text already persisted (unredacted)
        # in claim_evidence and reachable via /claim-evidence regardless, so
        # redacting the report's prose does not need to also redact these.
        facts=built.facts,
        exclusion_tally=built.exclusion_tally,
    )


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
    """Run the final safety screen (with escalation) over the report."""
    return await screen_with_escalation(
        run_id,
        ScreenSubject("final", markdown, screen_final(markdown)),
        provider=provider,
        db_path=db_path,
    )


def _commit_leased_report_publication(
    run_id: str,
    research_goal: str,
    built: _BuiltReport,
    task: ScientificTask,
    db_path: str | None,
) -> tuple[dict[str, str], int, dict[str, Any], int, dict[str, Any]]:
    """Atomically publish report state after validating the finalize lease."""
    # Function-local: engine_tasks_support imports engine_adapter, whose drain
    # imports this module (format_deep_verification_critique), so a top-level
    # import is a cycle whichever module loads first.
    from app.engine_tasks_support import _assert_task_commit_allowed

    with store.transaction(db_path) as conn:
        _assert_task_commit_allowed(task, conn)
        saved = store.save_report(
            run_id,
            built.payload,
            built.markdown,
            db_path=db_path,
            conn=conn,
            write_markdown=False,
        )
        store.replace_knowledge_facts(
            run_id, built.facts, db_path=db_path, conn=conn
        )
        report_payload = {**built.payload, "report_id": saved["id"]}
        report_seq = store.append_event(
            run_id, "report", report_payload, conn=conn
        )
        status_payload = {"status": "completed"}
        status_seq = store.append_event(
            run_id, "status", status_payload, conn=conn
        )
        store.update_run_status(
            run_id, RunStatus.COMPLETED, db_path=db_path, conn=conn
        )
        _enqueue_completion_notification(
            run_id, research_goal, saved["id"], db_path=db_path, conn=conn
        )
    return saved, report_seq, report_payload, status_seq, status_payload


async def _publish_report(  # noqa: PLR0913
    run_id: str,
    research_goal: str,
    built: _BuiltReport,
    emit: EmitFn,
    *,
    db_path: str | None,
    task: ScientificTask | None,
) -> AsyncIterator[dict[str, Any]]:
    """Save the report, emit it, mark the run completed, and notify."""
    payload = built.payload
    if task is None:
        saved = store.save_report(
            run_id, payload, built.markdown, db_path=db_path
        )
        # Only reached once the report is actually publishing (not blocked or
        # held), so a run whose report never publishes leaves no knowledge-base
        # rows behind either.
        store.replace_knowledge_facts(run_id, built.facts, db_path=db_path)
        yield await emit("report", {**payload, "report_id": saved["id"]})
        store.update_run_status(run_id, RunStatus.COMPLETED, db_path=db_path)
        _enqueue_completion_notification(
            run_id, research_goal, saved["id"], db_path=db_path
        )
        yield await emit("status", {"status": "completed"})
    else:
        from app.store.reports import write_report_markdown

        saved, report_seq, report_payload, status_seq, status_payload = (
            _commit_leased_report_publication(
                run_id, research_goal, built, task, db_path
            )
        )
        write_report_markdown(saved["markdown_path"], built.markdown)
        # The transaction already wrote these events; yield their regular SSE
        # stubs without calling the persisting emitter a second time.
        yield {"seq": report_seq, "type": "report", "payload": report_payload}
        yield {"seq": status_seq, "type": "status", "payload": status_payload}
    logger.info(
        "Report finalized for run %s (report_id=%s).", run_id, saved["id"]
    )


def _readiness_blocked(payload: dict[str, Any]) -> bool:
    """Return whether the run's empty leaderboard should hard-block release.

    Under the rank-and-publish policy the leaderboard is empty only when
    every idea was withheld -- by review rejection, deduplication, a
    contradicting claim, or a safety hold (see
    ``_empty_leaderboard_reason`` for which one actually applied) --
    leaving nothing publishable. Unsupported (but non-contradicted) ideas
    are published with an "Unverified" badge, so they never reach here.

    Applies identically whether the run is backed by a real model or the
    offline deterministic router: the offline backend still drives the same
    graph end to end, so an empty leaderboard there is the same "nothing
    survived review" outcome as a real run's, and it would be dishonest to
    publish a completed-looking report over it. (An offline run this
    happens to is rare in practice -- the offline router's canned content
    reliably survives review -- but rare is not never, and when it does
    happen the run should say so rather than paper over it.) The three
    curated default demos never reach this function at all: they write
    their report row directly (`seed.py`'s `_seed_curated_scenario`),
    bypassing `finalize_report` entirely, so this gate cannot affect them
    either way.
    """
    return not payload.get("leaderboard")


async def _block_for_empty_leaderboard(
    run_id: str,
    built: _BuiltReport,
    emit: EmitFn,
    *,
    db_path: str | None,
    task: ScientificTask | None,
) -> AsyncIterator[dict[str, Any]]:
    """Record the empty-leaderboard block, mark the run blocked, and emit it."""
    reason = _empty_leaderboard_reason(
        built.payload["idea_count"], built.exclusion_tally
    )
    decision = store.NewSafetyDecision(
        run_id=run_id,
        stage="scientific_readiness",
        decision="block",
        reason=reason,
        matches=[],
    )
    if task is None:
        store.add_safety_decision(decision, db_path=db_path)
        store.update_run_status(
            run_id, RunStatus.BLOCKED, error=reason, db_path=db_path
        )
        event = await emit("status", {"status": "blocked", "reason": reason})
    else:
        seq = _commit_empty_leaderboard_block(run_id, decision, task, db_path)
        event = {
            "seq": seq,
            "type": "status",
            "payload": {"status": "blocked", "reason": reason},
        }
    logger.warning("Report finalize blocked for run %s: %s", run_id, reason)
    yield event


def _commit_empty_leaderboard_block(
    run_id: str,
    decision: store.NewSafetyDecision,
    task: ScientificTask,
    db_path: str | None,
) -> int:
    """Atomically persist a readiness block while the finalize lease is live."""
    # Function-local, for the cycle explained in the publish function above.
    from app.engine_tasks_support import _assert_task_commit_allowed

    payload = {"status": "blocked", "reason": decision.reason}
    with store.transaction(db_path) as conn:
        _assert_task_commit_allowed(task, conn)
        store.add_safety_decision(decision, conn=conn)
        store.update_run_status(
            run_id, RunStatus.BLOCKED, error=decision.reason, conn=conn
        )
        return store.append_event(run_id, "status", payload, conn=conn)
