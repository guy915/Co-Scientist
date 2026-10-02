"""Final-state drain orchestrator: persist an engine run's results.

Writes an engine run's accumulated final state — evidence, hypotheses
(with reviews, deep-verification reviews, and citations), and tournament
matches — into the SQLite store in two transactions, and returns the
provider-specific report inputs the shared finalize path needs.
"""

from __future__ import annotations

import functools
import sqlite3
from typing import Any, NamedTuple

from app import store
from app.citations import empty_citation_summary
from app.claims import EvidencePassage
from app.claims.grounding import evidence_passages, persist_grounding
from app.engine_adapter.drain.claim_grounding import (
    _assess_claims,
    _gate_records_by_store_id,
    fold_grounding_telemetry,
)
from app.engine_adapter.drain.evidence_resolution import resolve_articles
from app.engine_adapter.drain.hypotheses import (
    ResolvedEvidenceBatch,
    _hypotheses_with_proximity_archive,
    _HypothesisSink,
    _persist_evidence_and_hypotheses,
)
from app.engine_adapter.drain.inputs import FinalStateInputs
from app.engine_adapter.drain.matches import (
    _persist_engine_matches,
    _persist_engine_proximity,
)
from app.engine_adapter.drain.report_inputs import (
    critical_criteria,
    degraded_sections,
    grounding_counts,
    retrieval_degradation,
    safety_counts,
    skills_used,
    stratification_attributes,
)
from app.engine_adapter.drain.research import _persist_retrieval_calls
from app.engine_adapter.drain.reviews import _CitationSink
from app.engine_adapter.drain.safety import _persist_held_for_review
from app.hypothesis.safety import escalate_held_hypotheses
from app.hypothesis.screening import (
    persist_escalated_verdicts,
    screen_hypotheses,
)


class DrainResult(NamedTuple):
    """What one drained final state hands the report path and stage events.

    ``report_inputs`` is spread verbatim into ``finalize_report``; the two
    count dicts are emitted by the caller as the post-drain
    ``safety.hypothesis`` and ``citation.grounding`` stage events.
    """

    report_inputs: dict[str, Any]
    safety_counts: dict[str, int]
    grounding_counts: dict[str, int]


def _screen_and_collect_grounding_inputs(
    run_id: str, conn: sqlite3.Connection
) -> tuple[Any, list[EvidencePassage], list[dict[str, Any]]]:
    """Run the per-hypothesis safety screen and gather claim-grounding inputs.

    The engine ran its tournament internally, so the safety screen enforces
    the guarantee at the app boundary. Deterministic only -- see
    ``persist_final_state`` for the model-escalation phase a held UNCERTAIN
    still gets, later and lock-free.

    Returns:
        A tuple of (screening result, evidence passages, grounding
        candidates -- persisted hypotheses not already rejected).
    """
    from app.report.gates import EXCLUDED_HYPOTHESIS_STATUSES

    persisted = store.list_hypotheses(run_id, conn=conn)
    screening_result = screen_hypotheses(run_id, persisted, conn=conn)
    passages = evidence_passages(run_id, conn=conn)
    grounding_candidates = [
        hypothesis
        for hypothesis in persisted
        if hypothesis.get("status") not in EXCLUDED_HYPOTHESIS_STATUSES
    ]
    return screening_result, passages, grounding_candidates


def _build_drain_result(
    final_state: dict[str, Any],
    citation_summary: dict[str, int],
    screening_result: Any,
    grounding_result: Any,
    grounding_candidates: list[dict[str, Any]],
) -> DrainResult:
    """Assemble the `DrainResult` from a completed drain's tallies."""
    return DrainResult(
        report_inputs={
            "citation_summary": citation_summary,
            "meta_review": final_state.get("meta_review") or {},
            "research_overview": final_state.get("research_overview") or {},
            "degraded_sections": degraded_sections(final_state),
            "retrieval_degradation": retrieval_degradation(final_state),
            "skills_used": skills_used(final_state),
            "attributes": stratification_attributes(final_state),
            "critical_criteria": critical_criteria(final_state),
        },
        safety_counts=safety_counts(screening_result),
        grounding_counts=grounding_counts(
            grounding_result, grounding_candidates
        ),
    )


def _prepare_final_state_inputs(
    final_state: dict[str, Any],
) -> FinalStateInputs:
    """Derive the drain's persistence inputs from an engine final state.

    Hypotheses are ordered parents-first so the ``parent_id`` foreign key
    resolves during insertion. ``persisted_engine_ids`` is every engine id
    being persisted, so a child's parent_id is only kept when the parent is
    also stored (see ``_resolve_persisted_parent_id``); the walrus narrows
    the element type to str (dropping the None from an id-less row).
    """
    hyps = _hypotheses_with_proximity_archive(
        final_state.get("hypotheses") or [],
        final_state.get("removed_duplicates") or [],
    )
    persisted_engine_ids = {hid for h in hyps if (hid := h.get("id"))}
    hyps_parents_first = sorted(hyps, key=lambda h: int(h.get("generation", 0)))
    return FinalStateInputs(
        hyps_parents_first=hyps_parents_first,
        articles=final_state.get("articles") or [],
        matchups=final_state.get("tournament_matchups") or [],
        proximity_graph=final_state.get("proximity_graph") or {},
        persisted_engine_ids=persisted_engine_ids,
        final_state=final_state,
    )


async def _persist_evidence_hypotheses_and_screen(
    run_id: str,
    inputs: FinalStateInputs,
    citation_summary: dict[str, int],
    store_id_by_engine_id: dict[str, str],
    db_path: str | None,
) -> tuple[Any, list[EvidencePassage], list[dict[str, Any]]]:
    """Run the drain's first transaction: evidence, hypotheses, screening.

    Batches this half of the drain into one transaction: a real run writes
    dozens of rows here, and per-call connections would fsync each one
    individually. Mutates `citation_summary` and `store_id_by_engine_id` in
    place.

    Evidence availability is resolved before the transaction opens:
    dereferencing a DOI/PMID is network I/O, and this function must never
    hold the write lock across it (see AGENTS.md). It also must not block
    the caller's event loop while it runs -- a run retrieving dozens of
    articles can spend tens of seconds across ``citations.resolver``'s
    bounded concurrency and per-request timeout, and the durable finalize
    task's lease heartbeat renews on this same loop (see
    ``_assess_claims`` for the incident this pattern already fixed for the
    claim-grounding wave) -- so the resolve runs off it via
    ``async_bridge.run_off_loop``.

    Returns:
        The (screening result, evidence passages, grounding candidates)
        tuple `_screen_and_collect_grounding_inputs` produces.
    """
    from app.async_bridge import run_off_loop

    resolved = await run_off_loop(
        functools.partial(resolve_articles, inputs.articles)
    )
    evidence = ResolvedEvidenceBatch(
        articles=inputs.articles, resolved=resolved
    )
    sink = _HypothesisSink(
        citations=_CitationSink(
            ev_id_by_title={},
            abstract_by_title={},
            citation_summary=citation_summary,
        ),
        store_id_by_engine_id=store_id_by_engine_id,
        persisted_engine_ids=inputs.persisted_engine_ids,
    )
    with store.transaction(db_path) as conn:
        # Before the evidence, so a row that names the search which found
        # it never points at a call that is not there yet.
        _persist_retrieval_calls(run_id, inputs.final_state, conn)
        _persist_evidence_and_hypotheses(
            run_id,
            evidence,
            inputs.hyps_parents_first,
            sink,
            conn,
        )
        result = _screen_and_collect_grounding_inputs(run_id, conn)
        _persist_held_for_review(run_id, inputs.final_state, conn)
        _persist_supervisor_plan(run_id, inputs.final_state, conn)
        return result


def _persist_grounding_matches_proximity_txn(
    run_id: str,
    provider_outputs: tuple[Any, list[Any]],
    inputs: FinalStateInputs,
    store_id_by_engine_id: dict[str, str],
    db_path: str | None,
) -> Any:
    """Run the drain's 2nd transaction: grounding, matches, and escalation."""
    assessed, escalated = provider_outputs
    with store.transaction(db_path) as conn:
        grounding_result = persist_grounding(run_id, assessed, conn=conn)
        _persist_engine_matches(
            run_id, inputs.matchups, store_id_by_engine_id, conn
        )
        _persist_engine_proximity(
            run_id, inputs.proximity_graph, store_id_by_engine_id, conn
        )
        persist_escalated_verdicts(run_id, escalated, conn=conn)
        return grounding_result


async def persist_final_state(
    *,
    run_id: str,
    final_state: dict[str, Any],
    db_path: str | None = None,
) -> DrainResult:
    """Drain an engine final state into the store.

    Writes evidence, hypotheses (with reviews, deep-verification reviews,
    and citations), and tournament matches; the report is built separately
    by ``finalize_report``, which consumes the returned inputs. Claim
    assessment and safety escalation both run between transactions,
    holding no connection, and both run off
    the caller's event loop (``async_bridge.run_off_loop``) rather than
    directly on it, so a durable finalize task's lease heartbeat keeps
    renewing while either provider wave runs (see ``_assess_claims``).

    Returns:
        A :class:`DrainResult`: the ``finalize_report`` kwargs plus the
        screen/grounding tallies emitted as post-drain stage events.
    """
    inputs = _prepare_final_state_inputs(final_state)
    citation_summary = empty_citation_summary()
    store_id_by_engine_id: dict[str, str] = {}
    (
        screening_result,
        passages,
        grounding_candidates,
    ) = await _persist_evidence_hypotheses_and_screen(
        run_id, inputs, citation_summary, store_id_by_engine_id, db_path
    )
    assessed, grounding_usage = await _assess_claims(
        grounding_candidates,
        passages,
        _gate_records_by_store_id(inputs, store_id_by_engine_id),
    )
    fold_grounding_telemetry(final_state, grounding_usage)
    # Safety escalation is synchronous provider work. Run it between the
    # transactions and off this loop so the finalize lease keeps renewing.
    from app.async_bridge import run_off_loop

    escalated = await run_off_loop(
        functools.partial(
            escalate_held_hypotheses,
            run_id,
            screening_result.escalatable,
            db_path=db_path,
        )
    )
    grounding_result = _persist_grounding_matches_proximity_txn(
        run_id, (assessed, escalated), inputs, store_id_by_engine_id, db_path
    )
    return _build_drain_result(
        final_state,
        citation_summary,
        screening_result,
        grounding_result,
        grounding_candidates,
    )


def _persist_supervisor_plan(
    run_id: str, final_state: dict[str, Any], conn: sqlite3.Connection
) -> None:
    """Persist the Supervisor's plan and per-cycle allocation ledger."""
    store.save_supervisor_plan(
        store.NewSupervisorPlan(
            run_id=run_id,
            guidance=final_state.get("supervisor_guidance") or {},
            termination_reason=final_state.get("termination_reason"),
            decision_provenance=final_state.get(
                "supervisor_decision_provenance"
            ),
            orchestrator_state=final_state.get("orchestrator_state") or {},
        ),
        conn=conn,
    )
    store.replace_supervisor_allocations(
        run_id, final_state.get("task_history") or [], conn=conn
    )
