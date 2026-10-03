"""Final-state drain orchestrator: persist an engine run's results."""

from __future__ import annotations

import functools
import logging
import sqlite3
from collections.abc import Mapping
from typing import Any, NamedTuple

import app.store as store
from app.citations import empty_citation_summary
from app.claims import EvidencePassage
from app.claims.grounding import (
    AssessorSpec,
    assess_hypothesis_claims,
    build_assessor,
    build_batch_assessor,
    evidence_passages,
    persist_grounding,
)
from app.config import settings
from app.engine_adapter.drain.hypotheses import (
    ResolvedEvidenceBatch,
    _hypotheses_with_proximity_archive,
    _HypothesisSink,
    _persist_evidence_and_hypotheses,
    resolve_articles,
)
from app.engine_adapter.drain.matches import (
    _persist_engine_matches,
    _persist_engine_proximity,
    _persist_retrieval_calls,
)
from app.engine_adapter.drain.reviews import _CitationSink
from app.execution_policy import effective_execution_model
from app.hypothesis import (
    persist_escalated_verdicts,
    screen_hypotheses,
)
from app.hypothesis.safety import (
    POLICY_VERSION,
    HypothesisSafetyOutcome,
    escalate_held_hypotheses,
)

logger = logging.getLogger(__name__)


class FinalStateInputs(NamedTuple):
    """Precomputed persistence inputs derived from an engine final state.

    ``final_state`` itself rides along for the consumers that read keys not
    precomputed here (the held-for-review persistence).
    """

    hyps_parents_first: list[dict[str, Any]]
    articles: list[dict[str, Any]]
    matchups: list[dict[str, Any]]
    proximity_graph: dict[str, Any]
    persisted_engine_ids: set[str]
    final_state: dict[str, Any]


def degraded_sections(final_state: dict[str, Any]) -> list[str]:
    """Return the engine nodes whose output degraded to a fallback.

    The engine records every enhancement node served a placeholder
    fallback instead of parseable LLM output
    (``co_scientist.progress.record_schema_degradation``); the report
    carries the list so a section left blank by a degradation can say so
    instead of showing silence.
    """
    return [str(name) for name in final_state.get("degraded_nodes") or []]


def retrieval_degradation(
    final_state: dict[str, Any],
) -> dict[str, Any] | None:
    """Return what the run could not search, when it could not search.

    A different fact from ``degraded_sections``: that one explains a
    section left blank by output the model could not produce, while this
    one names retrieval the run never attempted. Nothing in the report's
    prose can reveal it, which is exactly why it has to be carried.
    """
    degradation = final_state.get("retrieval_degradation")
    return degradation if isinstance(degradation, dict) else None


def skills_used(final_state: dict[str, Any]) -> dict[str, int]:
    """Return the science skills the run invoked, by name and count.

    Carried because the skills query third-party databases whose terms
    are separate from the bundle's licence, and most of those sources
    require that the user be notified of them. The harness writes that
    notice into the workspace the skill runs in, which is deleted; the
    report is the only surface that reaches a person, and it can only
    name the sources the run actually used if the run counted them.
    Empty on every run that invoked no skill, which is every run without
    ``COSCIENTIST_SKILLS_DIR``.
    """
    metrics = final_state.get("metrics")
    used = getattr(metrics, "skills_used", None)
    if used is None and isinstance(metrics, dict):
        used = metrics.get("skills_used")
    if not isinstance(used, dict):
        return {}
    return {str(name): int(count) for name, count in used.items()}


def stratification_attributes(
    final_state: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return the Supervisor's synthesized 1-5 stratification attributes.

    A read of guidance the Supervisor already synthesizes and
    ``drain/final_state.py`` already persists into the
    ``supervisor_plan`` table (``supervisor_guidance.config_synthesis.
    attributes``, up to three ``{name, rubric}`` axes) and
    ``prompts/review.py`` already injects into every reviewer prompt --
    not a new computation, just handing an existing one to the report
    (R12-17). Display only: the report never uses this to gate, filter,
    rank, or disqualify a hypothesis. Degrades to an empty list, never an
    error, on an old checkpoint predating this field or a malformed one.
    """
    guidance = final_state.get("supervisor_guidance")
    config = (
        guidance.get("config_synthesis") if isinstance(guidance, dict) else None
    )
    attributes = config.get("attributes") if isinstance(config, dict) else None
    if not isinstance(attributes, list):
        return []
    return [attr for attr in attributes if isinstance(attr, dict)]


def critical_criteria(final_state: dict[str, Any]) -> list[Any]:
    """Display-only guidance must never gate, rank, or disqualify hypotheses.

    Older checkpoints may carry bare criterion names instead of objects.
    """
    guidance = final_state.get("supervisor_guidance")
    plan = guidance.get("workflow_plan") if isinstance(guidance, dict) else None
    review_phase = plan.get("review_phase") if isinstance(plan, dict) else None
    criteria = (
        review_phase.get("critical_criteria")
        if isinstance(review_phase, dict)
        else None
    )
    if not isinstance(criteria, list):
        return []
    return [item for item in criteria if isinstance(item, (str, dict))]


def grounding_counts(
    grounding_result: Any, grounding_candidates: list[dict[str, Any]]
) -> dict[str, int]:
    """Tally the pre-ranking evidence gate's outcome for the report.

    "assessed", not "grounded": ``reason_by_id`` carries a gate reason for
    every hypothesis put through the gate, blocked ones included, so
    publishing it as "grounded" made a run where both candidates were
    blocked read "grounded=2 blocked=2" -- four hypotheses' worth of
    outcome for two hypotheses, with the blocked ones counted twice.
    """
    assessed = len(grounding_result.reason_by_id)
    return {
        "assessed": assessed,
        "grounded": assessed - grounding_result.blocked_count,
        "blocked": grounding_result.blocked_count,
        "eligible": (
            len(grounding_candidates) - grounding_result.blocked_count
        ),
    }


def safety_counts(screening_result: Any) -> dict[str, int]:
    """Tally the per-hypothesis safety screen's outcome for the report."""
    return {
        "screened": screening_result.screened_count,
        "blocked": screening_result.blocked_count,
        "eligible": (
            screening_result.screened_count - screening_result.blocked_count
        ),
    }


async def _assess_claims(
    grounding_candidates: list[dict[str, Any]],
    passages: list[EvidencePassage],
    gate_records: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[Any, dict[str, dict[str, Any]]]:
    """Assess each hypothesis claim against retrieved evidence passages.

    Claims the pre-ranking gate already assessed against the same evidence
    are reused rather than re-derived. The gate assesses a strict superset
    of these claims (it reads the hypothesis's experiment field too) with
    the same roles on the overlap, and a claim's verdict depends only on
    itself and the passages it retrieves -- so a per-claim match is enough
    to carry the verdict across.

    The wave itself runs off this coroutine's event loop
    (``async_bridge.run_off_loop``), the same way the pre-ranking gate
    (``engine_tasks.gate._assess_gate_claims``) runs its own wave -- see
    the module docstring. ``scoped_telemetry("claim_grounding")``
    attributes this pass's LLM calls in the run's metrics separately from
    the pre-ranking gate's own ``"claim_gate"`` phase.

    Args:
        grounding_candidates: Persisted hypotheses not already rejected.
        passages: The run's evidence passages.
        gate_records: Per store-id, the hypothesis's stored ``claim_gate``
            enrichment; omitted means assess everything.

    Returns:
        A tuple of (per hypothesis id its ``(assessment, role)`` pairs in
        claim order, this pass's LLM telemetry snapshot).
    """
    from co_scientist.llm import scoped_telemetry

    from app.async_bridge import run_off_loop

    model = effective_execution_model(
        settings.claim_verifier_model or settings.model_name
    )
    assert model is not None
    assessor, assessor_id = build_assessor(settings.claim_assessor, model)
    batch_assessor = build_batch_assessor(settings.claim_assessor, model)
    spec = AssessorSpec(assessor, assessor_id, batch_assessor)
    call = functools.partial(
        assess_hypothesis_claims,
        grounding_candidates,
        passages,
        spec,
        reuse=_reusable_by_hypothesis(gate_records or {}),
    )
    with scoped_telemetry("claim_grounding") as telemetry:
        assessed = await run_off_loop(call)
    return assessed, telemetry.snapshot()


def _gate_records_by_store_id(
    inputs: FinalStateInputs,
    store_id_by_engine_id: Mapping[str, str],
) -> dict[str, Mapping[str, Any]]:
    """Map each persisted hypothesis to the gate verdict recorded for it.

    The gate's verdicts live on the engine hypothesis's enrichments, but
    the drain assesses the persisted rows, so the two have to be joined by
    the engine-to-store id map the persistence pass just built.
    """
    records: dict[str, Mapping[str, Any]] = {}
    for hypothesis in inputs.hyps_parents_first:
        engine_id = str(hypothesis.get("id") or "")
        store_id = store_id_by_engine_id.get(engine_id)
        gate = (hypothesis.get("enrichments") or {}).get("claim_gate")
        if store_id and isinstance(gate, Mapping):
            records[store_id] = gate
    return records


def _reusable_by_hypothesis(
    gate_records: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Index every hypothesis's reusable gate verdicts by fingerprint."""
    from app.claims.grounding import reusable_assessments

    indexed = {
        store_id: reusable_assessments(record)
        for store_id, record in gate_records.items()
    }
    return {key: value for key, value in indexed.items() if value}


def fold_grounding_telemetry(
    final_state: dict[str, Any], usage: dict[str, dict[str, Any]]
) -> None:
    """Fold the finalize grounding pass's LLM telemetry into final metrics."""
    if not usage:
        return
    from co_scientist.models import MetricDeltas
    from co_scientist.models.metrics import (
        ExecutionMetrics,
        create_metrics_update,
        merge_metrics,
    )

    calls = sum(entry.get("calls", 0) for entry in usage.values())
    existing = ExecutionMetrics.from_dict(final_state.get("metrics") or {})
    delta = create_metrics_update(
        deltas=MetricDeltas(llm_calls=calls), model_usage=usage
    )
    merged = merge_metrics(existing, delta)
    final_state["metrics"] = merged.to_dict()


# How much of a held hypothesis's statement its decision row carries: enough
# for a reviewer to recognize the idea, not so much the audit trail reprints
# it. Matches the text-prefix width of the engine's own audit entries.
_HELD_TEXT_PREFIX_CHARS = 120


def _final_state_list(
    final_state: dict[str, Any], key: str
) -> list[dict[str, Any]]:
    """Return a list-valued key from the engine's final state, or empty."""
    return final_state.get(key) or []


def _engine_audit_by_hypothesis_id(
    final_state: dict[str, Any],
) -> dict[str, Mapping[str, Any]]:
    """Index the engine's per-hypothesis safety audit entries by id.

    The safety screen records one ``safety_decisions`` entry per blocked or
    held hypothesis; the drain joins a held hypothesis to its entry for the
    screen's rationale, matches, and policy version.
    """
    return {
        str(item.get("hypothesis_id")): item
        for item in _final_state_list(final_state, "safety_decisions")
        if isinstance(item, Mapping) and item.get("hypothesis_id")
    }


def _held_decision_reason(
    hyp_id: str,
    outcome: str,
    text: str,
    audit: Mapping[str, Any],
) -> str:
    """Build the audit reason for one held hypothesis.

    Follows the shape of the other hypothesis-stage rows (``hypothesis
    <id>: <outcome> (<rationale>)``), appending a prefix of the held idea's
    text: the engine keeps held hypotheses out of the pool, so no hypothesis
    row is persisted for one and its decision row is the only copy of it.
    """
    engine_reason = str(audit.get("reason") or "") or (
        "the safety screen held this hypothesis for manual review"
    )
    reason = f"hypothesis {hyp_id}: {outcome} ({engine_reason})"
    prefix = text[:_HELD_TEXT_PREFIX_CHARS]
    if prefix:
        reason = f"{reason}; idea: {prefix}"
    return reason


def _held_decision(
    run_id: str,
    entry: Mapping[str, Any],
    audit_by_id: Mapping[str, Mapping[str, Any]],
) -> store.NewSafetyDecision | None:
    """Build one held-for-review decision row from a held entry.

    Args:
        run_id: Run the drained final state belongs to.
        entry: One ``held_for_review`` entry (a hypothesis dict).
        audit_by_id: Engine audit entries keyed by hypothesis id.

    Returns:
        The decision to record, or None when the entry carries neither an
        id nor text and so cannot be identified for review.
    """
    hyp_id = str(entry.get("id") or "")
    text = str(entry.get("text") or "")
    if not hyp_id and not text:
        return None
    audit = audit_by_id.get(hyp_id, {})
    outcome = str(
        entry.get("safety_status") or HypothesisSafetyOutcome.UNCERTAIN.value
    )
    return store.NewSafetyDecision(
        run_id=run_id,
        stage="hypothesis",
        decision="hold",
        reason=_held_decision_reason(hyp_id, outcome, text, audit),
        matches=[str(m) for m in (audit.get("matches") or [])],
        category=outcome,
        policy_version=(
            str(audit.get("policy_version") or "") or POLICY_VERSION
        ),
        requires_review=True,
        assessor="engine:safety_screen",
    )


def _persist_held_for_review(
    run_id: str,
    final_state: dict[str, Any],
    conn: sqlite3.Connection,
) -> None:
    """Persist a reviewable decision row for each held hypothesis.

    Args:
        run_id: Run the drained final state belongs to.
        final_state: The engine's final state (held entries are plain dicts).
        conn: Open connection of the caller's transaction.
    """
    held = _final_state_list(final_state, "held_for_review")
    if not held:
        return
    audit_by_id = _engine_audit_by_hypothesis_id(final_state)
    recorded = 0
    for entry in held:
        if not isinstance(entry, Mapping):
            continue
        decision = _held_decision(run_id, entry, audit_by_id)
        if decision is None:
            continue
        store.add_safety_decision(decision, conn=conn)
        recorded += 1
    logger.info(
        "Recorded %d held-for-review decision(s) for run %s.",
        recorded,
        run_id,
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
