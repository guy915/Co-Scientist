"""Durable node-level execution for the real scientific engine."""

from __future__ import annotations

import asyncio
import dataclasses
import functools
import hashlib
import json
import sqlite3
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app import store
from app.config import settings
from app.elo import INITIAL_ELO
from app.engine_adapter.drain import _persist_final_state
from app.engine_adapter.opts import _build_engine_opts, _build_generator
from app.engine_adapter.provider import _import_hypothesis_generator
from app.report_render import finalize_report, make_emitter
from app.run_modes import normalize_run_tier, resolved_run_config
from app.safety import (
    apply_safety_gate,
    screen_intake,
    screen_with_escalation,
)
from app.store import RunStatus, ScientificTask

_CHECKPOINT_PROVIDER = "engine"
BOOTSTRAP_TASK = "engine.bootstrap"
NODE_TASK_PREFIX = "engine.node."
FINALIZE_TASK = "engine.finalize"
REVIEW_ITEM_TASK = "engine.fanout.review.item"
REVIEW_AGGREGATE_TASK = "engine.fanout.review.aggregate"
VERIFICATION_ITEM_TASK = "engine.fanout.verification.item"
VERIFICATION_AGGREGATE_TASK = "engine.fanout.verification.aggregate"
RANKING_MATCH_TASK = "engine.ranking.match"
RANKING_FINALIZE_TASK = "engine.ranking.finalize"
# Emit tournament progress every Nth match rather than once per match. A match
# is its own durable task taking roughly a minute, so a full tournament runs
# for tens of minutes; without this it committed real work the whole time and
# emitted nothing, leaving the live-activity feed showing a healthy run as
# frozen. Per-match events would fix the silence but flood the feed, which
# renders only the newest handful of events and would lose every other phase.
RANKING_PROGRESS_EVERY = 5
GENERATION_STRATEGY_TASK = "engine.fanout.generation.strategy"
GENERATION_AGGREGATE_TASK = "engine.fanout.generation.aggregate"
MATURE_REFLECTION_ITEM_TASK = "engine.fanout.reflection.item"
MATURE_REFLECTION_AGGREGATE_TASK = "engine.fanout.reflection.aggregate"


class SupersededTaskError(RuntimeError):
    """Signals that a newer checkpoint made a leased task obsolete."""


def enqueue_bootstrap(
    run_id: str, *, db_path: str | None = None
) -> ScientificTask:
    """Enqueue the first idempotent task of a node-level engine run."""
    return store.enqueue_task(
        run_id,
        BOOTSTRAP_TASK,
        {},
        idempotency_key="engine:bootstrap:v1",
        priority=100,
        provenance={
            "behavior": "evidence-bounded-reconstruction",
            "scheduler": "durable-specialist-tasks-v1",
        },
        budget={"lease_seconds": 300},
        db_path=db_path,
    )


def enqueue_scientist_continuation(
    run_id: str,
    input_id: int,
    *,
    db_path: str | None = None,
) -> ScientificTask | None:
    """Reopen a completed engine run so new scientist input enters the loop."""
    run = store.get_run(run_id, db_path=db_path)
    if run is None or run.provider != "engine":
        return None
    if run.status != RunStatus.COMPLETED.value:
        return None
    checkpoint = store.get_latest_checkpoint(run_id, db_path=db_path)
    if checkpoint is None:
        return None
    store.update_run_status(run_id, RunStatus.QUEUED, db_path=db_path)
    return store.enqueue_task(
        run_id,
        f"{NODE_TASK_PREFIX}orchestrator",
        {"checkpoint_seq": int(checkpoint["seq"])},
        idempotency_key=f"engine:scientist-continuation:{input_id}",
        priority=100,
        provenance={
            "behavior": "scientist-directed-continuation",
            "input_id": input_id,
        },
        budget={"lease_seconds": 300},
        db_path=db_path,
    )


def _merge_scientist_inputs(
    state: dict[str, Any], run_id: str, db_path: str | None
) -> None:
    """Merge durable manual hypotheses and reviews at a safe task boundary."""
    from co_scientist.models import (
        Hypothesis,
        HypothesisOrigin,
        HypothesisReview,
    )

    hypotheses = list(state.get("hypotheses") or [])
    by_id = {hypothesis.id: hypothesis for hypothesis in hypotheses}
    for row in store.list_hypotheses(run_id, db_path=db_path):
        if row.get("created_by_agent") != "scientist_manual":
            continue
        hypothesis_id = str(row["id"])
        if hypothesis_id in by_id:
            continue
        hypothesis = Hypothesis(
            id=hypothesis_id,
            text=str(row.get("statement") or row.get("title") or ""),
            origin=HypothesisOrigin.SCIENTIST_MANUAL,
            explanation=str(row.get("title") or "") or None,
        )
        hypothesis.elo_rating = int(row.get("elo_rating") or INITIAL_ELO)
        hypotheses.append(hypothesis)
        by_id[hypothesis_id] = hypothesis

    verdict_scores = {"support": 90, "revise": 60, "oppose": 20}
    for row in store.list_reviews(run_id, db_path=db_path):
        if row.get("reviewer_agent") != "scientist":
            continue
        hypothesis = by_id.get(str(row.get("hypothesis_id")))
        if hypothesis is None:
            continue
        marker = f"[scientist-review:{row['id']}]"
        if any(
            marker in review.review_summary for review in hypothesis.reviews
        ):
            continue
        summary = str(row.get("summary") or "")
        verdict = next(
            (value for value in verdict_scores if value in summary.lower()),
            "revise",
        )
        score = verdict_scores[verdict]
        hypothesis.reviews.append(
            HypothesisReview(
                review_summary=f"{marker} {summary}",
                scores={"scientist_assessment": score},
                safety_ethical_concerns="",
                detailed_feedback={
                    "scientist_critique": str(row.get("critique") or "")
                },
                constructive_feedback=str(row.get("critique") or ""),
                overall_score=float(score),
            )
        )
    state["hypotheses"] = hypotheses


@dataclasses.dataclass(frozen=True)
class _GatePlan:
    """One hypothesis's extracted claims awaiting assessment.

    Built before any provider call so the whole run's claims can be assessed
    in a single wave, then paired back up with its hypothesis to apply the
    publication gate.
    """

    hypothesis: Any
    claims: tuple[str, ...]
    roles: Mapping[str, str]
    fingerprint: str


async def _assess_gate_claims(
    plans: Sequence[_GatePlan],
    passages: Sequence[Any],
    assessor: Any,
    assessor_id: str,
) -> list[list[Any]]:
    """Assess every pending hypothesis's claims in one bounded wave.

    Claims are independent -- of each other and across hypotheses -- so
    overlapping them changes no verdict, only how long the phase takes. In
    production a hypothesis carries 7-25 atomic claims and a run reaches this
    gate with dozens, and awaiting them one at a time made this node the
    longest serial stretch of an express run (21-23% of wall clock). The
    provider is not the constraint: twenty-four concurrent completions return
    in the same wall clock as four.

    Runs on a dedicated executor rather than ``asyncio.to_thread``: the
    default executor is shared process-wide and the durable worker cohort
    parks long-lived calls there for a whole run, so a wave of claims would
    contend with the workers themselves.

    Args:
        plans: The hypotheses whose claims need assessing, in state order.
        passages: Candidate evidence passages every claim is assessed against.
        assessor: The entailment assessor.
        assessor_id: Provenance id recorded on each assessment.

    Returns:
        Per plan, its claim assessments in the plan's own claim order.
    """
    from app.claim_grounding import ASSESSMENT_CONCURRENCY
    from app.claims import assess_claim

    flat = [
        (index, claim)
        for index, plan in enumerate(plans)
        for claim in plan.claims
    ]
    if not flat:
        return [[] for _ in plans]

    call = functools.partial(
        assess_claim,
        passages=passages,
        assessor=assessor,
        assessor_id=assessor_id,
    )
    if settings.claim_assessor == "llm":
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(
            max_workers=min(ASSESSMENT_CONCURRENCY, len(flat))
        ) as pool:
            # gather preserves input order, so each hypothesis's recorded
            # claim sequence is identical to the serial one.
            results = list(
                await asyncio.gather(
                    *(
                        loop.run_in_executor(pool, call, claim)
                        for _index, claim in flat
                    )
                )
            )
    else:
        # The deterministic assessor makes no call to overlap.
        results = [call(claim) for _index, claim in flat]

    grouped: list[list[Any]] = [[] for _ in plans]
    for (index, _claim), assessment in zip(flat, results, strict=True):
        grouped[index].append(assessment)
    return grouped


async def _apply_pre_ranking_evidence_gate(state: dict[str, Any]) -> None:
    """Quarantine ungrounded ideas before a decisive Elo tournament."""
    from app.claim_grounding import build_assessor
    from app.claims import (
        EvidencePassage,
        GateDecision,
        extract_atomic_claims,
        publication_gate,
    )

    passages = [
        EvidencePassage(
            evidence_id=str(article.source_id or article.title),
            text=" ".join(
                part
                for part in (article.title, article.abstract, article.content)
                if part
            ),
            source=article.source,
            url=str(article.url or ""),
        )
        for article in state.get("articles") or []
    ]
    # The scientist's private corpus is admissible evidence: a hypothesis's
    # claims may be grounded in the uploaded documents, not only in retrieved
    # literature. Including these passages lets scientist-provided evidence
    # release an otherwise-unsupported idea, matching the disclosed
    # private-repository behavior. Additive (empty when nothing was uploaded).
    for source in state.get("context_enrichment_sources") or []:
        data = source.get("data") or {}
        text = str(source.get("display") or data.get("excerpt") or "").strip()
        if not text:
            continue
        passages.append(
            EvidencePassage(
                evidence_id=str(
                    data.get("document_id") or data.get("title") or "private"
                ),
                text=text,
                source=str(source.get("source_type") or "private_document"),
                url="",
            )
        )
    assessor, assessor_id = build_assessor(
        settings.claim_assessor,
        settings.claim_verifier_model or settings.model_name,
    )
    # Pass one plans every hypothesis without making a single provider call,
    # so the claims that actually need assessing can go out together below.
    plans: list[_GatePlan] = []
    prior_by_id: dict[str, str] = {}
    for hypothesis in state.get("hypotheses") or []:
        gate_history = hypothesis.enrichments.get("claim_gate") or {}
        prior_disposition = str(
            gate_history.get("prior_review_disposition")
            or hypothesis.review_disposition
            or "viable"
        )
        prior_by_id[hypothesis.id] = prior_disposition
        claim_roles: dict[str, str] = {}
        ordered_claims: list[str] = []
        for source_text, role in (
            (hypothesis.text, "speculative"),
            (hypothesis.literature_grounding, "categorical"),
            (hypothesis.explanation, "speculative"),
            (hypothesis.experiment, "speculative"),
        ):
            for claim in extract_atomic_claims(source_text or ""):
                if claim not in claim_roles:
                    ordered_claims.append(claim)
                    claim_roles[claim] = role
                elif role == "categorical":
                    claim_roles[claim] = role
        input_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "assessor": assessor_id,
                    "claims": [
                        [claim, claim_roles[claim]] for claim in ordered_claims
                    ],
                    "passages": [
                        {
                            "evidence_id": passage.evidence_id,
                            "text": passage.text,
                            "source": passage.source,
                            "url": passage.url,
                        }
                        for passage in passages
                    ],
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        # An unchanged proposal/evidence snapshot reuses its audited verdict;
        # repeated ranking cycles should spend compute on new science.
        if gate_history.get("input_fingerprint") == input_fingerprint:
            if gate_history.get("decision") == GateDecision.BLOCK.value:
                hypothesis.review_disposition = "evidence_blocked"
            elif hypothesis.review_disposition == "evidence_blocked":
                hypothesis.review_disposition = prior_disposition
            continue
        plans.append(
            _GatePlan(
                hypothesis=hypothesis,
                claims=tuple(ordered_claims),
                roles=claim_roles,
                fingerprint=input_fingerprint,
            )
        )

    assessed = await _assess_gate_claims(plans, passages, assessor, assessor_id)

    for plan, assessments in zip(plans, assessed, strict=True):
        hypothesis = plan.hypothesis
        claim_roles = dict(plan.roles)
        input_fingerprint = plan.fingerprint
        prior_disposition = prior_by_id[hypothesis.id]
        # Rank-and-publish policy: only contradicted (or unsafe) ideas are
        # withheld from the tournament here. Ungrounded/speculative ideas stay
        # rankable — allow_speculative treats insufficient claims as speculative
        # and require_supported_claim=False drops the "needs a supported claim"
        # block — so every non-contradicted idea earns an Elo score and can be
        # published (badged unverified) instead of blocking the whole run.
        gate = publication_gate(
            assessments,
            allow_speculative=True,
            explicitly_speculative_claims={
                claim
                for claim, role in claim_roles.items()
                if role == "speculative"
            },
            require_supported_claim=False,
        )
        hypothesis.enrichments["claim_gate"] = {
            "decision": gate.decision.value,
            "reason": gate.reason,
            "assessor": assessor_id,
            "input_fingerprint": input_fingerprint,
            "prior_review_disposition": prior_disposition,
            "claims": [
                {
                    "claim": assessment.claim,
                    "role": claim_roles[assessment.claim],
                    "label": assessment.label.value,
                    "supporting_passages": [
                        span.to_dict()
                        for span in assessment.supporting_passages
                    ],
                    "contradicting_passages": [
                        span.to_dict()
                        for span in assessment.contradicting_passages
                    ],
                }
                for assessment in assessments
            ],
        }
        if gate.decision is GateDecision.BLOCK:
            hypothesis.review_disposition = "evidence_blocked"
            feedback = f"Evidence gate: {gate.reason}"
            if feedback not in (hypothesis.reflection_notes or ""):
                hypothesis.reflection_notes = "\n".join(
                    part
                    for part in (hypothesis.reflection_notes, feedback)
                    if part
                )
        elif hypothesis.review_disposition == "evidence_blocked":
            hypothesis.review_disposition = prior_disposition


def _require_run(task: ScientificTask, db_path: str | None) -> store.RunRow:
    """Return the task's run or raise if it has been deleted."""
    run = store.get_run(task.run_id, db_path=db_path)
    if run is None:
        raise RuntimeError(f"run {task.run_id} no longer exists")
    return run


def _require_item_task(
    item_id: Any, db_path: str | None, *, kind: str
) -> ScientificTask:
    """Return a fan-out item task or raise if it has vanished mid-flight."""
    item = store.get_task(str(item_id), db_path=db_path)
    if item is None:
        raise RuntimeError(f"{kind} {item_id} disappeared")
    return item


def _successor_task_type(successor: str | None) -> str:
    """Map a node successor to its durable task type (finalize when None)."""
    if successor is None:
        return FINALIZE_TASK
    return f"{NODE_TASK_PREFIX}{successor}"


def _generator_and_opts(
    task: ScientificTask, db_path: str | None
) -> tuple[Any, dict[str, Any]]:
    run = _require_run(task, db_path)
    cfg = resolved_run_config(run.config)
    generator = _build_generator(
        _import_hypothesis_generator(),
        cfg,
        offline=store.run_used_offline(run),
    )
    return generator, _build_engine_opts(cfg, run.id, db_path)


def _generator_for_restore(task: ScientificTask, db_path: str | None) -> Any:
    """Build a registry-compatible generator without consuming steering."""
    run = _require_run(task, db_path)
    return _build_generator(
        _import_hypothesis_generator(),
        resolved_run_config(run.config),
        offline=store.run_used_offline(run),
    )


def _save_state_and_enqueue(
    task: ScientificTask,
    state: dict[str, Any],
    successor: str | None,
    *,
    expected_checkpoint_seq: int,
    db_path: str | None,
) -> tuple[int, str | None]:
    """Atomically checkpoint one node effect and enqueue its successor."""
    from co_scientist.checkpoint import (
        CHECKPOINT_VERSION,
        serialize_workflow_state,
    )

    envelope = serialize_workflow_state(
        state,
        last_event_seq=store.latest_event_seq(task.run_id, db_path=db_path),
    )
    successor_type = _successor_task_type(successor)
    with store.transaction(db_path) as conn:
        latest = store.get_latest_checkpoint(task.run_id, conn=conn)
        latest_seq = int(latest["seq"]) if latest else 0
        if latest_seq != expected_checkpoint_seq:
            raise RuntimeError(
                "checkpoint changed while scientific task was executing"
            )
        checkpoint_seq = store.save_checkpoint(
            task.run_id,
            stage=f"engine_task:{task.id}",
            schema_version=CHECKPOINT_VERSION,
            last_event_seq=envelope["last_event_seq"],
            # resume_successor names the task that this checkpoint's committed
            # state feeds into next, so a crash-resume re-enqueues the right
            # node rather than the orchestrator default in
            # task_worker.enqueue_run_workflow. It matches the successor
            # enqueued just below (same type, same checkpoint_seq), so its
            # idempotency key is identical and resume resolves to that exact
            # already-queued task instead of creating a second one. Without
            # it, a run interrupted right after bootstrap resumed at the
            # orchestrator with no supervisor_guidance in state and failed in
            # generation. The cooperative-pause path (_save_paused_state)
            # already records this; this closes the crash path to match.
            state={
                "provider": _CHECKPOINT_PROVIDER,
                "resume_successor": successor_type,
                **envelope,
            },
            conn=conn,
        )
        is_orchestrator = task.task_type == f"{NODE_TASK_PREFIX}orchestrator"
        if is_orchestrator:
            _apply_supervisor_queue_actions(
                task.run_id,
                state.get("supervisor_queue_actions") or [],
                conn,
            )
        priority = (
            int(state.get("next_task_priority", 90)) if is_orchestrator else 90
        )
        successor_task = store.enqueue_task(
            task.run_id,
            successor_type,
            {"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"{successor_type}:{checkpoint_seq}",
            priority=max(0, min(100, priority)),
            dependencies=(task.id,),
            provenance={"scheduled_by": task.task_type},
            conn=conn,
        )
    return checkpoint_seq, successor_task.id


def _apply_supervisor_queue_actions(
    run_id: str,
    actions: list[dict[str, Any]],
    conn: sqlite3.Connection,
) -> None:
    """Apply bounded same-run queue mutations inside the checkpoint commit."""
    tasks = {task.id: task for task in store.list_tasks(run_id, conn=conn)}
    for action in actions[:8]:
        task_id = str(action.get("task_id") or "")
        target = tasks.get(task_id)
        if target is None:
            continue
        reason = str(action.get("reason") or "Supervisor queue update")
        kind = action.get("action")
        if kind == "reprioritize" and action.get("priority") is not None:
            store.reprioritize_task(
                task_id,
                int(action["priority"]),
                reason=reason,
                conn=conn,
            )
        elif kind == "cancel":
            store.cancel_task(task_id, reason=reason, conn=conn)
        elif kind == "retry":
            store.retry_task(task_id, reason=reason, conn=conn)


def _durable_queue_snapshot(
    run_id: str, db_path: str | None
) -> list[dict[str, Any]]:
    """Return the bounded queue state the Supervisor may safely mutate."""
    return [
        {
            "task_id": task.id,
            "task_type": task.task_type,
            "status": task.status,
            "priority": task.priority,
            "attempt": task.attempt,
            "max_attempts": task.max_attempts,
            "dependencies": list(task.dependencies),
            "error": task.error,
        }
        for task in store.list_tasks(run_id, db_path=db_path)[-100:]
        if task.status in {"queued", "leased", "paused", "failed"}
    ]


def _save_state_and_enqueue_exact(
    task: ScientificTask,
    state: dict[str, Any],
    successor_type: str,
    successor_inputs: dict[str, Any],
    *,
    idempotency_key: str,
    expected_checkpoint_seq: int,
    db_path: str | None,
) -> tuple[int, str]:
    """Checkpoint one effect and enqueue a non-node scientific task."""
    from co_scientist.checkpoint import (
        CHECKPOINT_VERSION,
        serialize_workflow_state,
    )

    envelope = serialize_workflow_state(
        state,
        last_event_seq=store.latest_event_seq(task.run_id, db_path=db_path),
    )
    with store.transaction(db_path) as conn:
        latest = store.get_latest_checkpoint(task.run_id, conn=conn)
        latest_seq = int(latest["seq"]) if latest else 0
        if latest_seq != expected_checkpoint_seq:
            raise RuntimeError("checkpoint changed during scientific task")
        checkpoint_seq = store.save_checkpoint(
            task.run_id,
            stage=f"engine_task:{task.id}",
            schema_version=CHECKPOINT_VERSION,
            last_event_seq=envelope["last_event_seq"],
            state={"provider": _CHECKPOINT_PROVIDER, **envelope},
            conn=conn,
        )
        inputs = {**successor_inputs, "checkpoint_seq": checkpoint_seq}
        successor = store.enqueue_task(
            task.run_id,
            successor_type,
            inputs,
            idempotency_key=idempotency_key.format(
                checkpoint_seq=checkpoint_seq
            ),
            priority=86,
            dependencies=(task.id,),
            provenance={"scheduled_by": task.task_type},
            conn=conn,
        )
    return checkpoint_seq, successor.id


def _save_paused_state(
    task: ScientificTask,
    state: dict[str, Any],
    resume_successor: str,
    *,
    expected_checkpoint_seq: int,
    db_path: str | None,
) -> int:
    """Checkpoint an in-flight task without making successor work claimable."""
    from co_scientist.checkpoint import (
        CHECKPOINT_VERSION,
        serialize_workflow_state,
    )

    envelope = serialize_workflow_state(
        state,
        last_event_seq=store.latest_event_seq(task.run_id, db_path=db_path),
    )
    with store.transaction(db_path) as conn:
        latest = store.get_latest_checkpoint(task.run_id, conn=conn)
        latest_seq = int(latest["seq"]) if latest else 0
        if latest_seq != expected_checkpoint_seq:
            raise RuntimeError("checkpoint changed while pausing task")
        return store.save_checkpoint(
            task.run_id,
            stage=f"engine_task_paused:{task.id}",
            schema_version=CHECKPOINT_VERSION,
            last_event_seq=envelope["last_event_seq"],
            state={
                "provider": _CHECKPOINT_PROVIDER,
                "resume_successor": resume_successor,
                **envelope,
            },
            conn=conn,
        )


async def execute_bootstrap(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Safety-gate a run, prepare state, and enqueue the Supervisor task."""
    run = _require_run(task, db_path)
    emit = make_emitter(run.id, db_path=db_path)
    # Via screen_with_escalation, not screen_contextual directly: the
    # escalation wrapper carries the two guards this durable path must honor
    # as much as the streaming one does -- an offline-backed run never pays
    # for a real contextual model call, and a stage a human already approved
    # is not re-screened (which would otherwise let a fresh contextual verdict
    # re-hold an approved run on every resume).
    decision = await screen_with_escalation(
        run.id,
        "intake",
        run.research_goal,
        screen_intake(run.research_goal),
        provider=run.provider,
        db_path=db_path,
    )
    async for _ in apply_safety_gate(run.id, decision, emit, db_path=db_path):
        pass
    if decision.decision in {"block", "hold"}:
        return {"run_id": run.id, "status": "withheld", "terminal": True}

    store.update_run_status(run.id, RunStatus.RUNNING, db_path=db_path)
    generator, opts = _generator_and_opts(task, db_path)
    state = await generator.prepare_task_state(
        run.research_goal,
        opts=opts,
        run_id=run.id,
    )
    refreshed = store.get_run(run.id, db_path=db_path)
    if refreshed is None or refreshed.status == RunStatus.CANCELLED.value:
        raise RuntimeError("run cancelled during bootstrap")
    if refreshed.status == RunStatus.PAUSED.value:
        checkpoint_seq = _save_paused_state(
            task,
            state,
            f"{NODE_TASK_PREFIX}supervisor",
            expected_checkpoint_seq=0,
            db_path=db_path,
        )
        return {"checkpoint_seq": checkpoint_seq, "status": "paused"}
    checkpoint_seq, successor_id = _save_state_and_enqueue(
        task,
        state,
        "supervisor",
        expected_checkpoint_seq=0,
        db_path=db_path,
    )
    await emit(
        "scientific_task",
        {
            "task": "bootstrap",
            "status": "completed",
            "checkpoint_seq": checkpoint_seq,
        },
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
    }


def _latest_task_checkpoint(
    task: ScientificTask, db_path: str | None
) -> tuple[dict[str, Any], int]:
    checkpoint = store.get_latest_checkpoint(task.run_id, db_path=db_path)
    if checkpoint is None:
        raise RuntimeError("specialist task has no workflow checkpoint")
    return checkpoint, int(checkpoint["seq"])


def _restore_item_checkpoint(
    task: ScientificTask, db_path: str | None, *, superseded: str
) -> tuple[dict[str, Any], int]:
    """Restore the read-only workflow state a fan-out item task runs against.

    Rejects a task whose leased checkpoint a newer one has already replaced,
    then rebuilds the immutable state from the current checkpoint.

    Args:
        task: The leased fan-out item task.
        db_path: Optional override for the SQLite database path.
        superseded: Item label for the ``SupersededTaskError`` message.

    Returns:
        The restored workflow state dict and the leased checkpoint sequence.

    Raises:
        SupersededTaskError: When the leased checkpoint was superseded.
    """
    from co_scientist.checkpoint import restore_workflow_state

    checkpoint, current_seq = _latest_task_checkpoint(task, db_path)
    expected_seq = int(task.inputs["checkpoint_seq"])
    if current_seq != expected_seq:
        raise SupersededTaskError(f"{superseded} checkpoint was superseded")
    generator = _generator_for_restore(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    return state, expected_seq


def _enqueue_review_fanout(
    task: ScientificTask,
    state: dict[str, Any],
    checkpoint_seq: int,
    *,
    db_path: str | None,
) -> dict[str, Any]:
    """Materialize one independently leasable task per unreviewed hypothesis."""
    unreviewed = [
        hypothesis
        for hypothesis in state["hypotheses"]
        if not hypothesis.reviews
    ]
    with store.transaction(db_path) as conn:
        items = [
            store.enqueue_task(
                task.run_id,
                REVIEW_ITEM_TASK,
                {
                    "checkpoint_seq": checkpoint_seq,
                    "hypothesis_id": hypothesis.id,
                    "hypothesis_index": index,
                },
                idempotency_key=(
                    f"review:item:{checkpoint_seq}:{hypothesis.id}"
                ),
                priority=85,
                dependencies=(task.id,),
                provenance={
                    "scheduled_by": task.task_type,
                    "specialist": "reflection.initial",
                },
                conn=conn,
            )
            for index, hypothesis in enumerate(unreviewed)
        ]
        aggregate = store.enqueue_task(
            task.run_id,
            REVIEW_AGGREGATE_TASK,
            {
                "checkpoint_seq": checkpoint_seq,
                "item_task_ids": [item.id for item in items],
            },
            idempotency_key=f"review:aggregate:{checkpoint_seq}",
            priority=80,
            dependencies=tuple(item.id for item in items),
            provenance={
                "scheduled_by": task.task_type,
                "allow_failed_dependencies": True,
            },
            conn=conn,
        )
    return {
        "checkpoint_seq": checkpoint_seq,
        "fanout_task_ids": [item.id for item in items],
        "aggregate_task_id": aggregate.id,
        "node": "review",
    }


def _enqueue_verification_fanout(
    task: ScientificTask,
    state: dict[str, Any],
    checkpoint_seq: int,
    *,
    db_path: str | None,
) -> dict[str, Any]:
    """Materialize one leasable deep-verification task per idea."""
    from co_scientist.agents.reflection.deep_verification import (
        _select_hypotheses_to_verify,
    )

    selected = _select_hypotheses_to_verify(state["hypotheses"])
    with store.transaction(db_path) as conn:
        items = [
            store.enqueue_task(
                task.run_id,
                VERIFICATION_ITEM_TASK,
                {
                    "checkpoint_seq": checkpoint_seq,
                    "hypothesis_id": hypothesis.id,
                },
                idempotency_key=(
                    f"verification:item:{checkpoint_seq}:{hypothesis.id}"
                ),
                priority=88,
                dependencies=(task.id,),
                provenance={
                    "scheduled_by": task.task_type,
                    "specialist": "reflection.deep_verification",
                },
                conn=conn,
            )
            for hypothesis in selected
        ]
        aggregate = store.enqueue_task(
            task.run_id,
            VERIFICATION_AGGREGATE_TASK,
            {
                "checkpoint_seq": checkpoint_seq,
                "item_task_ids": [item.id for item in items],
            },
            idempotency_key=f"verification:aggregate:{checkpoint_seq}",
            priority=82,
            dependencies=tuple(item.id for item in items),
            provenance={
                "scheduled_by": task.task_type,
                "allow_failed_dependencies": True,
            },
            conn=conn,
        )
    return {
        "checkpoint_seq": checkpoint_seq,
        "fanout_task_ids": [item.id for item in items],
        "aggregate_task_id": aggregate.id,
        "node": "deep_verification",
    }


async def _enqueue_generation_fanout(
    task: ScientificTask,
    state: dict[str, Any],
    checkpoint_seq: int,
    *,
    db_path: str | None,
) -> dict[str, Any]:
    """Commit generation planning and enqueue each enabled strategy."""
    from co_scientist.agents.generation.coordinator import _prepare_generation
    from co_scientist.checkpoint import (
        CHECKPOINT_VERSION,
        serialize_workflow_state,
    )

    counts, reference_index, literature = await _prepare_generation(state)
    strategy_counts = {
        "tools": counts.tools_count,
        "debate_lit": counts.debate_with_lit_count,
        "debate_only": counts.debate_only_count,
        "assumptions": counts.assumptions_count,
    }
    task_specs = [
        (strategy, 1, index)
        for strategy, count in strategy_counts.items()
        if strategy in {"debate_lit", "debate_only"}
        for index in range(count)
    ] + [
        (strategy, count, 0)
        for strategy, count in strategy_counts.items()
        if strategy not in {"debate_lit", "debate_only"} and count > 0
    ]
    envelope = serialize_workflow_state(
        state,
        last_event_seq=store.latest_event_seq(task.run_id, db_path=db_path),
    )
    with store.transaction(db_path) as conn:
        latest = store.get_latest_checkpoint(task.run_id, conn=conn)
        latest_seq = int(latest["seq"]) if latest else 0
        if latest_seq != checkpoint_seq:
            raise RuntimeError("checkpoint changed during generation planning")
        planned_seq = store.save_checkpoint(
            task.run_id,
            stage=f"engine_task:{task.id}",
            schema_version=CHECKPOINT_VERSION,
            last_event_seq=envelope["last_event_seq"],
            state={"provider": _CHECKPOINT_PROVIDER, **envelope},
            conn=conn,
        )
        items = [
            store.enqueue_task(
                task.run_id,
                GENERATION_STRATEGY_TASK,
                {
                    "checkpoint_seq": planned_seq,
                    "strategy": strategy,
                    "count": count,
                    "strategy_index": index,
                    "literature": literature,
                    "reference_text": reference_index.text,
                    "reference_sources": reference_index.sources,
                },
                idempotency_key=(
                    f"generation:{strategy}:{planned_seq}:{index}:{count}"
                ),
                priority=87,
                dependencies=(task.id,),
                provenance={
                    "scheduled_by": task.task_type,
                    "generation_strategy": strategy,
                    "strategy_index": index,
                },
                conn=conn,
            )
            for strategy, count, index in task_specs
        ]
        aggregate = store.enqueue_task(
            task.run_id,
            GENERATION_AGGREGATE_TASK,
            {
                "checkpoint_seq": planned_seq,
                "item_task_ids": [item.id for item in items],
                "counts": dataclasses.asdict(counts),
            },
            idempotency_key=f"generation:aggregate:{planned_seq}",
            priority=81,
            dependencies=tuple(item.id for item in items),
            provenance={
                "scheduled_by": task.task_type,
                "allow_failed_dependencies": True,
            },
            conn=conn,
        )
    return {
        "checkpoint_seq": planned_seq,
        "fanout_task_ids": [item.id for item in items],
        "aggregate_task_id": aggregate.id,
        "node": "generate",
    }


def _enqueue_mature_reflection_fanout(
    task: ScientificTask,
    state: dict[str, Any],
    checkpoint_seq: int,
    *,
    db_path: str | None,
) -> dict[str, Any]:
    """Schedule maturity-appropriate Reflection modes as durable tasks."""
    iteration = int(state.get("current_iteration", 0))
    literature = state.get("articles_with_reasoning")
    specs: list[tuple[str, str]] = []
    for hypothesis in state["hypotheses"]:
        if hypothesis.review_disposition != "viable":
            continue
        if literature and not hypothesis.reflection_notes:
            specs.append((hypothesis.id, "observation"))
        if "full" not in hypothesis.enrichments:
            specs.extend(
                ((hypothesis.id, "full"), (hypothesis.id, "simulation"))
            )
        elif iteration > int(
            hypothesis.enrichments.get("recurrent_review_iteration", -1)
        ):
            specs.append((hypothesis.id, "recurrent"))
    with store.transaction(db_path) as conn:
        items = [
            store.enqueue_task(
                task.run_id,
                MATURE_REFLECTION_ITEM_TASK,
                {
                    "checkpoint_seq": checkpoint_seq,
                    "hypothesis_id": hypothesis_id,
                    "review_mode": review_mode,
                },
                idempotency_key=(
                    f"reflection:{review_mode}:{checkpoint_seq}:{hypothesis_id}"
                ),
                priority=86,
                dependencies=(task.id,),
                provenance={
                    "scheduled_by": task.task_type,
                    "reflection_mode": review_mode,
                },
                conn=conn,
            )
            for hypothesis_id, review_mode in specs
        ]
        aggregate = store.enqueue_task(
            task.run_id,
            MATURE_REFLECTION_AGGREGATE_TASK,
            {
                "checkpoint_seq": checkpoint_seq,
                "item_task_ids": [item.id for item in items],
            },
            idempotency_key=f"reflection:aggregate:{checkpoint_seq}",
            priority=80,
            dependencies=tuple(item.id for item in items),
            provenance={
                "scheduled_by": task.task_type,
                "allow_failed_dependencies": True,
            },
            conn=conn,
        )
    return {
        "checkpoint_seq": checkpoint_seq,
        "fanout_task_ids": [item.id for item in items],
        "aggregate_task_id": aggregate.id,
        "node": "comprehensive_reflection",
    }


async def execute_review_item(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Review one hypothesis without mutating the shared workflow checkpoint."""
    from co_scientist.agents.reflection.review import review_single_hypothesis

    state, expected_seq = _restore_item_checkpoint(
        task, db_path, superseded="review item"
    )
    hypothesis_id = str(task.inputs["hypothesis_id"])
    hypothesis = next(
        (item for item in state["hypotheses"] if item.id == hypothesis_id),
        None,
    )
    if hypothesis is None:
        raise ValueError(
            f"hypothesis {hypothesis_id} is absent from checkpoint"
        )
    review = await review_single_hypothesis(
        hypothesis_text=hypothesis.text,
        research_goal=state["research_goal"],
        model_name=state["model_name"],
        supervisor_guidance=state.get("supervisor_guidance"),
        meta_review=state.get("meta_review"),
        run_id=state.get("run_id"),
        hypothesis_index=int(task.inputs["hypothesis_index"]),
        tool_registry=state.get("tool_registry"),
        run_setup_guidance=state.get("run_setup_guidance"),
        run_focus_guidance=state.get("run_focus_guidance"),
    )
    return {
        "hypothesis_id": hypothesis_id,
        "review": dataclasses.asdict(review),
        "checkpoint_seq": expected_seq,
    }


async def execute_review_aggregate(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Commit successful review results and preserve isolated failures."""
    from co_scientist.agents.reflection.review import _apply_initial_review_gate
    from co_scientist.checkpoint import restore_workflow_state
    from co_scientist.models import (
        HypothesisReview,
        create_metrics_update,
        phase_message,
    )
    from co_scientist.task_runtime import apply_task_update

    checkpoint, current_seq = _latest_task_checkpoint(task, db_path)
    expected_seq = int(task.inputs["checkpoint_seq"])
    if (
        current_seq > expected_seq
        and checkpoint["stage"] == f"engine_task:{task.id}"
    ):
        return {"checkpoint_seq": current_seq, "replayed": True}
    if current_seq != expected_seq:
        raise SupersededTaskError("review aggregate checkpoint was superseded")
    generator = _generator_for_restore(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    by_id = {hypothesis.id: hypothesis for hypothesis in state["hypotheses"]}
    successful = 0
    failed = 0
    for item_id in task.inputs.get("item_task_ids", []):
        item = _require_item_task(item_id, db_path, kind="review item")
        if item.status != "completed" or not item.result:
            failed += 1
            hypothesis_id = str(item.inputs.get("hypothesis_id", ""))
            if hypothesis_id in by_id:
                by_id[hypothesis_id].review_disposition = "review_failed"
            continue
        hypothesis = by_id[str(item.result["hypothesis_id"])]
        review = HypothesisReview(**item.result["review"])
        hypothesis.reviews.append(review)
        # The durable aggregate mirrors the normal Review node's score update
        # so tournament seeding observes peer-review quality.
        hypothesis.score = review.overall_score
        _apply_initial_review_gate([hypothesis], [review])
        successful += 1
    committed = apply_task_update(
        state,
        {
            "hypotheses": state["hypotheses"],
            "metrics": create_metrics_update(
                reviews_count_delta=successful,
                llm_calls_delta=successful + failed,
            ),
            "messages": phase_message(
                "review",
                f"Reviewed {successful} hypotheses; {failed} isolated failures",
                strategy="durable_parallel_individual",
            ),
        },
    )
    checkpoint_seq, successor_id = _save_state_and_enqueue(
        task,
        committed,
        "comprehensive_reflection",
        expected_checkpoint_seq=current_seq,
        db_path=db_path,
    )
    await _emit_node_completion(
        task.run_id,
        "review",
        "comprehensive_reflection",
        committed,
        checkpoint_seq,
        db_path,
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "successful_reviews": successful,
        "failed_reviews": failed,
    }


async def execute_verification_item(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Deep-verify one hypothesis without mutating the workflow checkpoint."""
    from co_scientist.agents.reflection.deep_verification import (
        _verification_evidence_context,
        _verify_one,
    )

    state, expected_seq = _restore_item_checkpoint(
        task, db_path, superseded="verification item"
    )
    hypothesis_id = str(task.inputs["hypothesis_id"])
    hypothesis = next(
        (item for item in state["hypotheses"] if item.id == hypothesis_id),
        None,
    )
    if hypothesis is None:
        raise ValueError(
            f"hypothesis {hypothesis_id} is absent from checkpoint"
        )
    result = await _verify_one(
        hypothesis,
        state["research_goal"],
        state["model_name"],
        asyncio.Semaphore(1),
        state.get("tool_registry"),
        _verification_evidence_context(state),
        state,
    )
    if result is None:
        raise RuntimeError(f"deep verification failed for {hypothesis_id}")
    return {
        "hypothesis_id": hypothesis_id,
        "verification": result,
        "checkpoint_seq": expected_seq,
    }


async def execute_generation_strategy(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Execute one generation strategy against a read-only plan checkpoint."""
    from co_scientist.agents.generation.assumptions import (
        generate_with_assumptions,
    )
    from co_scientist.agents.generation.citations import ReferenceIndex
    from co_scientist.agents.generation.debate import generate_with_debate
    from co_scientist.agents.generation.literature_tools import (
        generate_with_tools,
    )

    state, expected_seq = _restore_item_checkpoint(
        task, db_path, superseded="generation strategy"
    )
    strategy = str(task.inputs["strategy"])
    count = int(task.inputs["count"])
    reference_index = ReferenceIndex(
        text=str(task.inputs.get("reference_text") or ""),
        sources=dict(task.inputs.get("reference_sources") or {}),
    )
    transcripts: list[dict[str, Any]] = []
    if strategy == "tools":
        hypotheses = await generate_with_tools(state, count, reference_index)
    elif strategy in {"debate_lit", "debate_only"}:
        literature = (
            task.inputs.get("literature") if strategy == "debate_lit" else None
        )
        debate_reference = (
            reference_index
            if strategy == "debate_lit"
            else ReferenceIndex(text="", sources={})
        )
        hypotheses, transcripts = await generate_with_debate(
            state=state,
            count=count,
            articles_with_reasoning=literature,
            reference_index=debate_reference,
        )
    elif strategy == "assumptions":
        hypotheses = await generate_with_assumptions(state, count)
    else:
        raise ValueError(f"unsupported generation strategy: {strategy}")
    return {
        "strategy": strategy,
        "hypotheses": [hypothesis.to_dict() for hypothesis in hypotheses],
        "transcripts": transcripts,
        "checkpoint_seq": expected_seq,
    }


async def execute_generation_aggregate(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Combine independent generation strategies into one hypothesis append."""
    from co_scientist.agents.generation.coordinator import _finalize_generation
    from co_scientist.agents.generation.coordinator_results import (
        GenerationResults,
    )
    from co_scientist.agents.generation.coordinator_strategy import (
        GenerationCounts,
    )
    from co_scientist.checkpoint import restore_workflow_state
    from co_scientist.models import Hypothesis, create_metrics_update
    from co_scientist.task_runtime import apply_task_update

    checkpoint, current_seq = _latest_task_checkpoint(task, db_path)
    expected_seq = int(task.inputs["checkpoint_seq"])
    if (
        current_seq > expected_seq
        and checkpoint["stage"] == f"engine_task:{task.id}"
    ):
        return {"checkpoint_seq": current_seq, "replayed": True}
    if current_seq != expected_seq:
        raise SupersededTaskError(
            "generation aggregate checkpoint was superseded"
        )
    generator = _generator_for_restore(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    buckets: dict[str, list[Hypothesis]] = {
        "tools": [],
        "debate_lit": [],
        "debate_only": [],
        "assumptions": [],
    }
    transcripts: list[dict[str, Any]] = []
    failed = 0
    for item_id in task.inputs.get("item_task_ids", []):
        item = _require_item_task(item_id, db_path, kind="generation strategy")
        if item.status != "completed" or not item.result:
            failed += 1
            continue
        strategy = str(item.result["strategy"])
        buckets[strategy].extend(
            Hypothesis.from_dict(payload)
            for payload in item.result.get("hypotheses", [])
        )
        transcripts.extend(item.result.get("transcripts", []))
    counts = GenerationCounts(**task.inputs["counts"])
    results = GenerationResults(
        tools_hypotheses=buckets["tools"],
        debate_with_lit_hypotheses=buckets["debate_lit"],
        debate_only_hypotheses=buckets["debate_only"],
        assumptions_hypotheses=buckets["assumptions"],
        debate_transcripts=transcripts,
    )
    update = await _finalize_generation(state, counts, results)
    update["metrics"] = create_metrics_update(
        hypothesis_count=update["hypothesis_count"]
    )
    if failed:
        update["message"] += f"; {failed} strategy failure(s) isolated"
    committed = apply_task_update(state, update)
    successor = "reflection" if state.get("mcp_available") else "review"
    checkpoint_seq, successor_id = _save_state_and_enqueue(
        task,
        committed,
        successor,
        expected_checkpoint_seq=current_seq,
        db_path=db_path,
    )
    await _emit_node_completion(
        task.run_id, "generate", successor, committed, checkpoint_seq, db_path
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "hypotheses_generated": update["hypothesis_count"],
        "failed_strategies": failed,
    }


async def execute_mature_reflection_item(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Execute one disclosed mature Reflection mode for one hypothesis."""
    from co_scientist.agents.reflection.comprehensive_reflection import (
        _run_review,
    )
    from co_scientist.agents.reflection.reflection import (
        analyze_single_hypothesis,
    )
    from co_scientist.agents.reflection.review_types import ReviewType

    state, expected_seq = _restore_item_checkpoint(
        task, db_path, superseded="mature reflection"
    )
    hypothesis_id = str(task.inputs["hypothesis_id"])
    hypothesis = next(
        (item for item in state["hypotheses"] if item.id == hypothesis_id),
        None,
    )
    if hypothesis is None:
        raise ValueError(
            f"hypothesis {hypothesis_id} is absent from checkpoint"
        )
    mode = ReviewType(str(task.inputs["review_mode"]))
    if mode is ReviewType.OBSERVATION:
        literature = state.get("articles_with_reasoning")
        if not literature:
            raise RuntimeError("observation review has no literature context")
        result = await analyze_single_hypothesis(
            hypothesis=hypothesis,
            articles_with_reasoning=literature,
            model_name=state["model_name"],
            hypothesis_index=1,
            total_count=1,
            run_id=state.get("run_id"),
            tool_registry=state.get("tool_registry"),
            meta_review=state.get("meta_review"),
        )
    else:
        _, result = await _run_review(state, hypothesis, mode)
    if result is None:
        raise RuntimeError(f"{mode.value} review failed for {hypothesis_id}")
    return {
        "hypothesis_id": hypothesis_id,
        "review_mode": mode.value,
        "review": result,
        "checkpoint_seq": expected_seq,
    }


async def execute_mature_reflection_aggregate(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Commit mature Reflection results while isolating individual failures."""
    from co_scientist.agents.reflection.deep_verification import (
        merge_retrieved_articles,
    )
    from co_scientist.agents.reflection.review_types import ReviewType
    from co_scientist.checkpoint import restore_workflow_state
    from co_scientist.models import create_metrics_update, phase_message
    from co_scientist.task_runtime import apply_task_update

    checkpoint, current_seq = _latest_task_checkpoint(task, db_path)
    expected_seq = int(task.inputs["checkpoint_seq"])
    if (
        current_seq > expected_seq
        and checkpoint["stage"] == f"engine_task:{task.id}"
    ):
        return {"checkpoint_seq": current_seq, "replayed": True}
    if current_seq != expected_seq:
        raise SupersededTaskError(
            "reflection aggregate checkpoint was superseded"
        )
    generator = _generator_for_restore(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    by_id = {hypothesis.id: hypothesis for hypothesis in state["hypotheses"]}
    successful = 0
    failed = 0
    reflection_results: list[dict[str, Any]] = []
    for item_id in task.inputs.get("item_task_ids", []):
        item = _require_item_task(item_id, db_path, kind="reflection task")
        if item.status != "completed" or not item.result:
            failed += 1
            continue
        hypothesis = by_id[str(item.result["hypothesis_id"])]
        mode = ReviewType(str(item.result["review_mode"]))
        review = item.result["review"]
        reflection_results.append(review)
        if mode is ReviewType.OBSERVATION:
            classification = review.get("classification", "neutral")
            reasoning = review.get("reasoning", "")
            hypothesis.reflection_notes = (
                f"{reasoning}\n\nClassification: {classification}"
            )
        hypothesis.enrichments[mode.value] = review
        if mode is ReviewType.RECURRENT:
            hypothesis.enrichments["recurrent_review_iteration"] = int(
                state.get("current_iteration", 0)
            )
        successful += 1
    state["articles"] = merge_retrieved_articles(
        state.get("articles"), reflection_results
    )
    committed = apply_task_update(
        state,
        {
            "hypotheses": state["hypotheses"],
            "articles": state["articles"],
            "metrics": create_metrics_update(
                llm_calls_delta=successful + failed
            ),
            "messages": phase_message(
                "reflection",
                f"Completed {successful} mature reviews; "
                f"{failed} isolated failures",
            ),
        },
    )
    checkpoint_seq, successor_id = _save_state_and_enqueue(
        task,
        committed,
        "safety_screen",
        expected_checkpoint_seq=current_seq,
        db_path=db_path,
    )
    await _emit_node_completion(
        task.run_id,
        "comprehensive_reflection",
        "safety_screen",
        committed,
        checkpoint_seq,
        db_path,
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "successful_reviews": successful,
        "failed_reviews": failed,
    }


async def execute_verification_aggregate(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Commit independent verification results and continue the tournament."""
    from co_scientist.agents.reflection.deep_verification import (
        merge_retrieved_articles,
    )
    from co_scientist.checkpoint import restore_workflow_state
    from co_scientist.models import create_metrics_update, phase_message
    from co_scientist.task_runtime import apply_task_update

    checkpoint, current_seq = _latest_task_checkpoint(task, db_path)
    expected_seq = int(task.inputs["checkpoint_seq"])
    if (
        current_seq > expected_seq
        and checkpoint["stage"] == f"engine_task:{task.id}"
    ):
        return {"checkpoint_seq": current_seq, "replayed": True}
    if current_seq != expected_seq:
        raise SupersededTaskError(
            "verification aggregate checkpoint was superseded"
        )
    generator = _generator_for_restore(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    by_id = {hypothesis.id: hypothesis for hypothesis in state["hypotheses"]}
    successful = 0
    failed = 0
    llm_calls = 0
    verification_results: list[dict[str, Any]] = []
    for item_id in task.inputs.get("item_task_ids", []):
        item = _require_item_task(item_id, db_path, kind="verification item")
        if item.status != "completed" or not item.result:
            failed += 1
            continue
        hypothesis = by_id[str(item.result["hypothesis_id"])]
        verification = item.result["verification"]
        verification_results.append(verification)
        hypothesis.deep_verification_probes = verification.get("probes", [])
        hypothesis.deep_verification_verdict = verification.get("verdict")
        hypothesis.enrichments["deep_verification"] = verification
        llm_calls += int(verification.get("verification_llm_calls", 1))
        successful += 1
    state["articles"] = merge_retrieved_articles(
        state.get("articles"), verification_results
    )
    committed = apply_task_update(
        state,
        {
            "hypotheses": state["hypotheses"],
            "articles": state["articles"],
            "metrics": create_metrics_update(llm_calls_delta=llm_calls),
            "messages": phase_message(
                "deep_verification",
                f"Deep-verified {successful} hypotheses; "
                f"{failed} isolated failures",
            ),
        },
    )
    checkpoint_seq, successor_id = _save_state_and_enqueue(
        task,
        committed,
        "ranking",
        expected_checkpoint_seq=current_seq,
        db_path=db_path,
    )
    await _emit_node_completion(
        task.run_id,
        "deep_verification",
        "ranking",
        committed,
        checkpoint_seq,
        db_path,
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "successful_verifications": successful,
        "failed_verifications": failed,
    }


def _ranking_eligible(state: dict[str, Any]) -> list[Any]:
    """Return hypotheses eligible for a tournament under engine policy.

    Ideas the pre-ranking evidence gate quarantined (``evidence_blocked``) are
    excluded alongside deep-verification-undermined and review-rejected ideas,
    so an unsupported or contradicted claim never influences the decisive Elo
    tournament even though the report gate would later drop it. The predicate
    lives on ``Hypothesis.is_rankable`` so the durable path and the engine
    scheduler's coverage accounting stay in sync (a mismatch loops the
    orchestrator on ranking).
    """
    return [
        hypothesis
        for hypothesis in state["hypotheses"]
        if hypothesis.is_rankable()
    ]


async def _schedule_ranking_chain(
    task: ScientificTask,
    state: dict[str, Any],
    checkpoint_seq: int,
    *,
    db_path: str | None,
) -> dict[str, Any] | None:
    """Prepare a tournament and schedule its first sequential match task."""
    from co_scientist.agents.ranking.ranking import _prepare_ranking_round

    eligible = _ranking_eligible(state)
    if len(eligible) < 2:
        return None
    rounds, *_ = await _prepare_ranking_round(state, eligible)
    state["pending_ranking_matchups"] = []
    committed_seq, successor_id = _save_state_and_enqueue_exact(
        task,
        state,
        RANKING_MATCH_TASK,
        {
            "round_index": 0,
            "tournament_rounds": rounds,
            "total_llm_calls": 0,
            "previous_pair": [],
        },
        idempotency_key="ranking:match:{checkpoint_seq}:0",
        expected_checkpoint_seq=checkpoint_seq,
        db_path=db_path,
    )
    return {
        "checkpoint_seq": committed_seq,
        "successor_task_id": successor_id,
        "tournament_rounds": rounds,
        "node": "ranking",
    }


# How many matchups one durable task judges concurrently. Bounded so a wave
# still commits a checkpoint often enough to be a useful resume point, and so
# the pool's Elo ratings re-adapt between waves rather than drifting across a
# whole round judged from one stale snapshot.
RANKING_WAVE_SIZE = 5


def _ranking_wave(
    candidates: list[Any],
    previous_pair: frozenset[str],
    index: int,
    rounds: int,
) -> list[Any]:
    """Return the distinct matchups this task should judge concurrently.

    Skips the pair the previous wave ended on (the existing rematch guard) and
    never repeats a pair inside one wave, since every pairing in a wave is
    drawn from the same Elo snapshot and would otherwise be judged twice.
    Never runs past the round budget.
    """
    remaining = max(0, rounds - index)
    wave: list[Any] = []
    seen: set[frozenset[str]] = {previous_pair} if previous_pair else set()
    for pair in candidates:
        if len(wave) >= min(RANKING_WAVE_SIZE, remaining):
            break
        key = frozenset({pair[0].id, pair[1].id})
        if key in seen:
            continue
        seen.add(key)
        wave.append(pair)
    if not wave and candidates and remaining:
        # Every candidate was a repeat; judging the best one again still makes
        # progress and matches the previous one-per-task fallback.
        wave.append(candidates[0])
    return wave


async def execute_ranking_match(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Judge and commit exactly one Elo matchup before scheduling another."""
    from co_scientist.agents.ranking.ranking import (
        _apply_matchup_elo,
        _build_matchup_detail,
        _build_tournament_pairings,
        _gather_tournament_context,
        _matchup_debate_turns,
        _median_elo,
        judge_matchup,
    )
    from co_scientist.checkpoint import restore_workflow_state
    from co_scientist.constants import ELO_K_FACTOR

    checkpoint, current_seq = _latest_task_checkpoint(task, db_path)
    expected_seq = int(task.inputs["checkpoint_seq"])
    if (
        current_seq > expected_seq
        and checkpoint["stage"] == f"engine_task:{task.id}"
    ):
        return {"checkpoint_seq": current_seq, "replayed": True}
    if current_seq != expected_seq:
        raise SupersededTaskError("ranking match checkpoint was superseded")
    generator = _generator_for_restore(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    eligible = _ranking_eligible(state)
    index = int(task.inputs["round_index"])
    rounds = int(task.inputs["tournament_rounds"])
    candidates = _build_tournament_pairings(
        eligible,
        min(3, rounds),
        state["research_goal"],
        int(state.get("current_iteration", 0)) * 10_000 + index,
    )
    previous_pair = frozenset(
        str(item) for item in task.inputs["previous_pair"]
    )
    # Judge a wave of distinct matchups instead of one. A matchup is three
    # debate turns of real model work (~45s), so one-per-task ran a 128-match
    # round at a concurrency of one -- about 94 minutes of wall clock for
    # ~20 minutes of work. Pairings within a wave are drawn from the same Elo
    # snapshot, which is the cost of the parallelism: adaptation happens at
    # wave boundaries rather than after every single match.
    wave = _ranking_wave(candidates, previous_pair, index, rounds)
    details = list(state.get("pending_ranking_matchups") or [])
    total_calls = int(task.inputs["total_llm_calls"])
    next_index = rounds
    last_pair: list[str] = []
    if wave:
        guidance, registry, meta_review, setup, focus = (
            _gather_tournament_context(state)
        )
        median = _median_elo(eligible)
        depths = [
            _matchup_debate_turns(pair[0], pair[1], median) for pair in wave
        ]

        async def _judge(
            offset: int, pair: tuple[Any, Any]
        ) -> tuple[str, dict[str, Any]]:
            """Judge one matchup of the wave."""
            judgement: tuple[str, dict[str, Any]] = await judge_matchup(
                pair[0],
                pair[1],
                state["research_goal"],
                state["model_name"],
                guidance,
                run_id=state.get("run_id"),
                matchup_index=index + offset,
                tool_registry=registry,
                meta_review=meta_review,
                run_setup_guidance=setup,
                run_focus_guidance=focus,
                debate_turns=depths[offset],
            )
            return judgement

        # The engine's ranking semaphore bounds the real fan-out; gather only
        # offers it more than one call to bound.
        judged = await asyncio.gather(
            *(_judge(offset, pair) for offset, pair in enumerate(wave))
        )
        # Elo is applied in wave order so the committed result is independent
        # of the order the concurrent judgements happened to return in.
        k_factor = int(state.get("elo_k_factor") or ELO_K_FACTOR)
        for offset, (pair, (winner, response)) in enumerate(
            zip(wave, judged, strict=True)
        ):
            hypothesis_a, hypothesis_b = pair
            outcome = _apply_matchup_elo(
                hypothesis_a, hypothesis_b, winner, k_factor=k_factor
            )
            details.append(
                _build_matchup_detail(
                    hypothesis_a, hypothesis_b, winner, response, outcome
                )
            )
            total_calls += depths[offset]
            last_pair = [hypothesis_a.id, hypothesis_b.id]
        next_index = index + len(wave)
    state["pending_ranking_matchups"] = details
    successor_type = (
        RANKING_MATCH_TASK if next_index < rounds else RANKING_FINALIZE_TASK
    )
    successor_inputs = (
        {
            "round_index": next_index,
            "tournament_rounds": rounds,
            "total_llm_calls": total_calls,
            "previous_pair": last_pair,
        }
        if successor_type == RANKING_MATCH_TASK
        else {
            "tournament_rounds": rounds,
            "total_llm_calls": total_calls,
        }
    )
    committed_seq, successor_id = _save_state_and_enqueue_exact(
        task,
        state,
        successor_type,
        successor_inputs,
        idempotency_key=(
            f"ranking:match:{{checkpoint_seq}}:{next_index}"
            if successor_type == RANKING_MATCH_TASK
            else "ranking:finalize:{checkpoint_seq}"
        ),
        expected_checkpoint_seq=current_seq,
        db_path=db_path,
    )
    # Placed after the commit, downstream of this function's replay/supersession
    # guard, so a redelivered match never re-announces progress. The final match
    # is left to the finalizer's own "completed" event rather than reported
    # twice.
    if (
        wave
        and next_index < rounds
        and next_index % RANKING_PROGRESS_EVERY == 0
    ):
        emit = make_emitter(task.run_id, db_path=db_path)
        await emit(
            "scientific_task",
            {
                "task": "ranking",
                "status": "running",
                "checkpoint_seq": committed_seq,
                "successor": None,
                "message": f"Tournament match {next_index} of {rounds}",
            },
        )
    return {
        "checkpoint_seq": committed_seq,
        "successor_task_id": successor_id,
        "round_index": index,
        "matches_committed": len(details),
    }


async def execute_ranking_finalize(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Finalize a sequential durable tournament and return to orchestration."""
    from co_scientist.agents.ranking.ranking import _finalize_ranking_result
    from co_scientist.checkpoint import restore_workflow_state
    from co_scientist.task_runtime import apply_task_update

    checkpoint, current_seq = _latest_task_checkpoint(task, db_path)
    expected_seq = int(task.inputs["checkpoint_seq"])
    if (
        current_seq > expected_seq
        and checkpoint["stage"] == f"engine_task:{task.id}"
    ):
        return {"checkpoint_seq": current_seq, "replayed": True}
    if current_seq != expected_seq:
        raise SupersededTaskError("ranking finalizer checkpoint was superseded")
    generator = _generator_for_restore(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    update = await _finalize_ranking_result(
        state,
        state["hypotheses"],
        list(state.get("pending_ranking_matchups") or []),
        int(task.inputs["tournament_rounds"]),
        int(task.inputs["total_llm_calls"]),
    )
    committed = apply_task_update(state, update)
    committed.pop("pending_ranking_matchups", None)
    checkpoint_seq, successor_id = _save_state_and_enqueue(
        task,
        committed,
        "orchestrator",
        expected_checkpoint_seq=current_seq,
        db_path=db_path,
    )
    await _emit_node_completion(
        task.run_id,
        "ranking",
        "orchestrator",
        committed,
        checkpoint_seq,
        db_path,
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "matches_committed": len(update.get("tournament_matchups", [])),
    }


async def execute_node_task(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Execute and commit exactly one engine specialist node."""
    from co_scientist.checkpoint import restore_workflow_state
    from co_scientist.task_runtime import execute_task_node

    checkpoint, current_seq = _latest_task_checkpoint(task, db_path)
    run = store.get_run(task.run_id, db_path=db_path)
    if run is None or run.status == RunStatus.CANCELLED.value:
        raise RuntimeError("run cancelled before specialist execution")
    expected_seq = int(task.inputs.get("checkpoint_seq", -1))
    # Redelivery after the checkpoint commit but before task completion is an
    # acknowledgement replay, never a second scientific effect.
    if current_seq > expected_seq:
        if checkpoint["stage"] == f"engine_task:{task.id}":
            return {"checkpoint_seq": current_seq, "replayed": True}
        raise SupersededTaskError("specialist task checkpoint was superseded")
    if current_seq != expected_seq:
        raise RuntimeError("specialist task checkpoint does not match input")

    generator, opts = _generator_and_opts(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    # Re-deliver durable scientist steering/private sources at every safe task
    # boundary. _build_engine_opts marks the message queue consumed only after
    # materializing these values, so a worker restart cannot silently lose it.
    if opts.get("pending_steering"):
        state["pending_steering"] = True
    if opts.get("preferences"):
        state["preferences"] = opts["preferences"]
    if opts.get("context_enrichment_sources"):
        state["context_enrichment_sources"] = opts["context_enrichment_sources"]
    _merge_scientist_inputs(state, task.run_id, db_path)
    node_name = task.task_type.removeprefix(NODE_TASK_PREFIX)
    if node_name == "orchestrator":
        state["durable_task_queue"] = _durable_queue_snapshot(
            task.run_id, db_path
        )
    if run.status == RunStatus.PAUSED.value:
        checkpoint_seq = _save_paused_state(
            task,
            state,
            task.task_type,
            expected_checkpoint_seq=current_seq,
            db_path=db_path,
        )
        return {
            "checkpoint_seq": checkpoint_seq,
            "node": node_name,
            "status": "paused",
        }
    if node_name == "review":
        return _enqueue_review_fanout(task, state, current_seq, db_path=db_path)
    if node_name == "generate":
        return await _enqueue_generation_fanout(
            task, state, current_seq, db_path=db_path
        )
    if node_name == "comprehensive_reflection":
        return _enqueue_mature_reflection_fanout(
            task, state, current_seq, db_path=db_path
        )
    if node_name == "deep_verification":
        return _enqueue_verification_fanout(
            task, state, current_seq, db_path=db_path
        )
    if node_name == "ranking":
        await _apply_pre_ranking_evidence_gate(state)
        scheduled = await _schedule_ranking_chain(
            task, state, current_seq, db_path=db_path
        )
        if scheduled is not None:
            return scheduled
    committed, successor = await execute_task_node(node_name, state)
    run = store.get_run(task.run_id, db_path=db_path)
    if run is None or run.status == RunStatus.CANCELLED.value:
        raise RuntimeError("run cancelled during specialist execution")
    successor_type = _successor_task_type(successor)
    if run.status == RunStatus.PAUSED.value:
        checkpoint_seq = _save_paused_state(
            task,
            committed,
            successor_type,
            expected_checkpoint_seq=current_seq,
            db_path=db_path,
        )
        return {
            "checkpoint_seq": checkpoint_seq,
            "node": node_name,
            "status": "paused",
        }
    checkpoint_seq, successor_id = _save_state_and_enqueue(
        task,
        committed,
        successor,
        expected_checkpoint_seq=current_seq,
        db_path=db_path,
    )
    await _emit_node_completion(
        task.run_id, node_name, successor, committed, checkpoint_seq, db_path
    )
    return {
        "checkpoint_seq": checkpoint_seq,
        "successor_task_id": successor_id,
        "node": node_name,
    }


def _plain_final_state(state: dict[str, Any]) -> dict[str, Any]:
    """Convert restored typed state into the app drain's persisted shape."""
    metrics = state.get("metrics")
    return {
        **state,
        "hypotheses": [item.to_dict() for item in state.get("hypotheses", [])],
        "articles": [item.to_dict() for item in state.get("articles") or []],
        "metrics": metrics.to_dict() if metrics else {},
    }


def _emit_node_milestone(
    run_id: str,
    node_name: str,
    state: dict[str, Any],
    db_path: str | None,
) -> None:
    """Append the milestone chat message the streaming path emits for a node.

    Reuses ``events.py``'s canonical vocabulary (``_canonical_event_type``,
    ``_canonical_engine_payload``, ``_format_milestone``) so the durable and
    streaming engine paths never carry two copies of the milestone strings.
    A no-op for node types with no milestone builder (e.g. ``review``,
    ``orchestrator``, ``safety_screen``, ``comprehensive_reflection``) --
    checked before the state conversion below so those completions pay no
    extra cost.

    Callers place this immediately after the node's checkpoint commit (the
    same call site as the durable path's ``scientific_task`` event, where one
    exists), which is only reached once per real checkpoint advance -- a
    redelivered/replayed task returns earlier, at the function's existing
    idempotency guard, so a retried task never emits a duplicate milestone.
    A crash between the checkpoint commit and this call loses that node's
    milestone rather than duplicating it, the same failure mode the existing
    ``scientific_task`` emit already has.
    """
    from app.engine_adapter.events import (
        _MILESTONE_BUILDERS,
        _canonical_engine_payload,
        _canonical_event_type,
        _format_milestone,
    )

    node_type = _canonical_event_type(node_name)
    if node_type not in _MILESTONE_BUILDERS:
        return
    payload = _canonical_engine_payload(
        node_name, node_type, _plain_final_state(state)
    )
    milestone = _format_milestone(node_type, payload)
    if milestone:
        store.append_message(
            run_id, "system", milestone, "milestone", db_path=db_path
        )


async def _emit_node_completion(
    run_id: str,
    node_name: str,
    successor: str | None,
    committed: dict[str, Any],
    checkpoint_seq: int,
    db_path: str | None,
) -> None:
    """Emit the milestone and ``scientific_task`` event for one node.

    Pairs the two side-effects the streaming path's ``_emit_engine_node_event``
    couples for every node: a milestone chat message (a no-op for node types
    without one) and the ``scientific_task`` completion event the frontend's
    live-activity feed (``ACTIVITY_META``) and mid-run refetch logic key on.

    Before this, the five fan-out aggregate completions (``generate``,
    ``review``, ``comprehensive_reflection``, ``deep_verification``,
    ``ranking`` -- the node types where the durable path's actual scientific
    work happens) emitted no event of any kind, leaving the live-activity feed
    blind to exactly the nodes doing the substantive work. Only the generic
    ``execute_node_task`` completion path emitted ``scientific_task``.

    Callers place this immediately after the node's checkpoint commit,
    downstream of that function's existing checkpoint-replay/supersession
    guard, so a redelivered or replayed task never double-emits either side
    effect (same reasoning as ``_emit_node_milestone``).
    """
    _emit_node_milestone(run_id, node_name, committed, db_path)
    emit = make_emitter(run_id, db_path=db_path)
    await emit(
        "scientific_task",
        {
            "task": node_name,
            "status": "completed",
            "checkpoint_seq": checkpoint_seq,
            "successor": successor,
        },
    )


async def execute_finalize(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Drain the final checkpoint and publish through the shared report gate."""
    from co_scientist.checkpoint import restore_workflow_state

    run = _require_run(task, db_path)
    if run.status == RunStatus.CANCELLED.value:
        raise RuntimeError("run cancelled before finalization")
    if (
        run.status == RunStatus.COMPLETED.value
        and store.get_latest_report(run.id, db_path=db_path) is not None
    ):
        return {"run_id": run.id, "status": "completed", "replayed": True}
    checkpoint, _ = _latest_task_checkpoint(task, db_path)
    generator = _generator_for_restore(task, db_path)
    state = restore_workflow_state(
        checkpoint["state"], tool_registry=generator.tool_registry
    )
    refreshed = store.get_run(run.id, db_path=db_path)
    if refreshed is not None and refreshed.status == RunStatus.PAUSED.value:
        checkpoint_seq = _save_paused_state(
            task,
            state,
            FINALIZE_TASK,
            expected_checkpoint_seq=int(checkpoint["seq"]),
            db_path=db_path,
        )
        return {"checkpoint_seq": checkpoint_seq, "status": "paused"}
    final_state = _plain_final_state(state)
    # Final drain is deterministic and replayable. Clear only its prior rows
    # so a crash after persistence but before task acknowledgement cannot
    # duplicate hypotheses, evidence, matches, or verification edges.
    store.clear_publication_artifacts(run.id, db_path=db_path)
    report_inputs = _persist_final_state(
        run_id=run.id, final_state=final_state, db_path=db_path
    )
    # Popped before the rest of report_inputs is spread into finalize_report
    # below (which does not accept them as kwargs); emitted as the same
    # post-drain stage events the streaming engine path emits, so both engine
    # execution modes carry identical per-stage fidelity.
    safety_counts = report_inputs.pop("safety_counts")
    grounding_counts = report_inputs.pop("grounding_counts")
    metrics = final_state.get("metrics") or {}
    execution_time = max(0.0, time.time() - float(state.get("start_time", 0)))
    store.save_run_metrics(run.id, metrics, db_path=db_path)
    store.update_run_status(run.id, RunStatus.SYNTHESIZING, db_path=db_path)
    emit = make_emitter(run.id, db_path=db_path)
    await emit("safety.hypothesis", safety_counts)
    await emit("citation.grounding", grounding_counts)
    await emit("citation_audit", dict(report_inputs["citation_summary"]))
    async for _ in finalize_report(
        run_id=run.id,
        research_goal=run.research_goal,
        run_mode=normalize_run_tier(run.profile),
        provider="engine",
        emit=emit,
        execution_time=execution_time,
        db_path=db_path,
        **report_inputs,
    ):
        pass
    final = store.get_run(run.id, db_path=db_path)
    return {"run_id": run.id, "status": final.status if final else "missing"}


async def execute_engine_task(
    task: ScientificTask, *, db_path: str | None = None
) -> dict[str, Any]:
    """Dispatch one leased engine task without executing unrelated nodes."""
    if task.task_type == BOOTSTRAP_TASK:
        return await execute_bootstrap(task, db_path=db_path)
    if task.task_type == REVIEW_ITEM_TASK:
        return await execute_review_item(task, db_path=db_path)
    if task.task_type == REVIEW_AGGREGATE_TASK:
        return await execute_review_aggregate(task, db_path=db_path)
    if task.task_type == VERIFICATION_ITEM_TASK:
        return await execute_verification_item(task, db_path=db_path)
    if task.task_type == VERIFICATION_AGGREGATE_TASK:
        return await execute_verification_aggregate(task, db_path=db_path)
    if task.task_type == RANKING_MATCH_TASK:
        return await execute_ranking_match(task, db_path=db_path)
    if task.task_type == RANKING_FINALIZE_TASK:
        return await execute_ranking_finalize(task, db_path=db_path)
    if task.task_type == GENERATION_STRATEGY_TASK:
        return await execute_generation_strategy(task, db_path=db_path)
    if task.task_type == GENERATION_AGGREGATE_TASK:
        return await execute_generation_aggregate(task, db_path=db_path)
    if task.task_type == MATURE_REFLECTION_ITEM_TASK:
        return await execute_mature_reflection_item(task, db_path=db_path)
    if task.task_type == MATURE_REFLECTION_AGGREGATE_TASK:
        return await execute_mature_reflection_aggregate(task, db_path=db_path)
    if task.task_type.startswith(NODE_TASK_PREFIX):
        return await execute_node_task(task, db_path=db_path)
    if task.task_type == FINALIZE_TASK:
        return await execute_finalize(task, db_path=db_path)
    raise ValueError(f"unsupported engine task: {task.task_type}")
