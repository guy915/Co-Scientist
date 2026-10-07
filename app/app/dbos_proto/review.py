"""Review fan-out as DBOS workflows.

One parent workflow per review node commit, one child workflow per
hypothesis. Children start in a fixed order, so step numbering replays
deterministically; each child runs its attempts sequentially.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import sqlite3
import time
import weakref
from collections.abc import Iterator
from typing import Any

from dbos import DBOS, SetWorkflowID

from app.config import settings
from app.dbos_proto import review_workflow_id
from app.engine_tasks.support import (
    NodeCompletion,
    SupersededTaskError,
    _emit_node_completion,
    _metrics_snapshot,
    _successor_task_type,
)
from app.store import db, events, runs, tasks
from app.store import checkpoints as store
from app.store import retrieval_calls as retrieval
from app.store.checkpoints import NewCheckpoint
from app.store.models import (
    TERMINAL_STATUSES,
    UNKNOWN_PROVIDER_OUTCOME_ERROR,
    ScientificTask,
)

MAX_ATTEMPTS = 3
_RATE_LIMIT_PARK_JITTER_SECONDS = 15.0

_ISSUANCE_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS dbos_review_issuance ("
    " workflow_id TEXT NOT NULL, attempt INTEGER NOT NULL,"
    " issued_at REAL NOT NULL, settled_at REAL,"
    " PRIMARY KEY (workflow_id, attempt))"
)


def ensure_tables(db_path: str) -> None:
    with db.connect(db_path) as conn:
        conn.execute(_ISSUANCE_SCHEMA)


# --- scopes ---------------------------------------------------------------


@contextlib.contextmanager
def _run_scopes(run_id: str) -> Iterator[bool]:
    """Recovered workflows start outside any task scope, so each workflow
    re-enters credential, call-budget and zero-cost scopes itself.
    """
    from co_scientist.llm import (
        scoped_api_key,
        scoped_llm_call_budget,
        scoped_zero_cost_admission,
    )

    from app.credentials import get_run_credential, scoped_byok
    from app.engine_tasks import runtime as engine_tasks_runtime
    from app.execution_policy import zero_cost_admission_for_config
    from app.logging_setup import run_log_context
    from app.run_modes import resolved_run_config

    run = runs.get_run(run_id)
    if run is None:
        raise LookupError(f"run not found for review workflow: {run_id}")
    credential = get_run_credential(run_id)
    ceiling = resolved_run_config(run.config).get("max_llm_calls")
    ceiling = int(ceiling) if isinstance(ceiling, int) else None
    zero_cost = zero_cost_admission_for_config(run.config)
    with (
        run_log_context(run_id),
        engine_tasks_runtime.bound(engine_tasks_runtime.active()),
        scoped_byok(credential),
        scoped_api_key(
            credential.api_key if credential else None,
            by_model=credential.keys_by_model() if credential else None,
        ),
        scoped_llm_call_budget(run_id, ceiling),
        scoped_zero_cost_admission(zero_cost),
    ):
        yield zero_cost and credential is None


_slots: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Semaphore]] = (
    weakref.WeakKeyDictionary()
)


def _item_slots(run_id: str) -> asyncio.Semaphore:
    """Bound one run's in-flight provider calls per running loop; a shared
    primitive would bind to the first loop that waits on it.
    """
    per_loop = _slots.setdefault(asyncio.get_running_loop(), {})
    if run_id not in per_loop:
        per_loop[run_id] = asyncio.Semaphore(settings.worker_pool_size)
    return per_loop[run_id]


# --- issuance markers -----------------------------------------------------


def _issue(workflow_id: str, attempt: int) -> bool:
    """False when this attempt was already issued and never settled: the
    process died mid-call, so the provider outcome is unknown.
    """
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT settled_at FROM dbos_review_issuance WHERE workflow_id=? AND attempt=?",
            (workflow_id, attempt),
        ).fetchone()
        if row is not None:
            return False
        conn.execute(
            "INSERT INTO dbos_review_issuance (workflow_id, attempt, issued_at) VALUES (?,?,?)",
            (workflow_id, attempt, time.time()),
        )
    return True


def _settle(workflow_id: str, attempt: int) -> None:
    with db.transaction() as conn:
        conn.execute(
            "UPDATE dbos_review_issuance SET settled_at=? WHERE workflow_id=? AND attempt=?",
            (time.time(), workflow_id, attempt),
        )


# --- item -----------------------------------------------------------------


def _item_view(run_id: str, checkpoint_seq: int, hypothesis_id: str, index: int) -> ScientificTask:
    now = time.time()
    return ScientificTask(
        id=f"dbos:{run_id}:{checkpoint_seq}:{hypothesis_id}",
        run_id=run_id,
        task_type="engine.fanout.review.item",
        status="leased",
        priority=85,
        inputs={
            "checkpoint_seq": checkpoint_seq,
            "hypothesis_id": hypothesis_id,
            "hypothesis_index": index,
        },
        dependencies=(),
        provenance={},
        idempotency_key="",
        budget={},
        attempt=1,
        max_attempts=MAX_ATTEMPTS,
        lease_owner=None,
        lease_expires_at=None,
        result=None,
        error=None,
        created_at=now,
        updated_at=now,
        started_at=now,
        completed_at=None,
    )


def _classify(exc: Exception) -> dict[str, Any]:
    from co_scientist.exceptions import (
        LLMCallBudgetExceededError,
        LLMRateLimitParkError,
        LLMTimeoutError,
    )

    if isinstance(exc, SupersededTaskError):
        return {"kind": "superseded", "error": str(exc)}
    if isinstance(exc, LLMRateLimitParkError):
        resume_at = exc.resume_at + random.uniform(0, _RATE_LIMIT_PARK_JITTER_SECONDS)
        return {"kind": "park", "resume_at": resume_at, "error": str(exc)}
    if isinstance(exc, LLMCallBudgetExceededError):
        return {"kind": "budget", "error": str(exc)}
    if isinstance(exc, LLMTimeoutError) and not exc.zero_cost_admitted:
        return {"kind": "unknown", "error": UNKNOWN_PROVIDER_OUTCOME_ERROR}
    return {"kind": "retryable", "error": str(exc)}


@DBOS.step(name="coscientist.review.attempt")
async def review_attempt(
    run_id: str,
    checkpoint_seq: int,
    hypothesis_id: str,
    index: int,
    attempt: int,
    provably_free: bool,
) -> dict[str, Any]:
    from app.engine_tasks.fanout import execute_review_item

    workflow_id = str(DBOS.workflow_id)
    fresh = await asyncio.to_thread(_issue, workflow_id, attempt)
    if not fresh and not provably_free:
        return {"kind": "unknown", "error": UNKNOWN_PROVIDER_OUTCOME_ERROR}
    async with _item_slots(run_id):
        try:
            result = await execute_review_item(
                _item_view(run_id, checkpoint_seq, hypothesis_id, index)
            )
        except Exception as exc:  # The child workflow decides retry or settlement.
            outcome = _classify(exc)
        else:
            outcome = {"kind": "ok", "result": result}
    await asyncio.to_thread(_settle, workflow_id, attempt)
    return outcome


@DBOS.workflow(name="coscientist.review.item")
async def review_item(run_id: str, checkpoint_seq: int, hypothesis_id: str, index: int) -> dict[str, Any]:
    with _run_scopes(run_id) as provably_free:
        attempt = 0
        while True:
            attempt += 1
            outcome = await review_attempt(
                run_id, checkpoint_seq, hypothesis_id, index, attempt, provably_free
            )
            if outcome["kind"] == "park":
                # A platform cap spends no retry; the durable sleep survives
                # restarts and wakes at the provider's reset.
                await DBOS.sleep_async(max(0.0, outcome["resume_at"] - time.time()))
                attempt -= 1
                continue
            if outcome["kind"] == "retryable" and attempt < MAX_ATTEMPTS:
                continue
            return {"hypothesis_id": hypothesis_id, "attempts": attempt, **outcome}


# --- aggregate ------------------------------------------------------------


def _apply_review_outcomes(
    by_id: dict[str, Any],
    outcomes: list[dict[str, Any]],
    criteria: list[str] | None,
) -> tuple[int, int, dict[str, dict[str, Any]]]:
    from co_scientist.agents.reflection import apply_initial_review_gate
    from co_scientist.agents.reflection.review_gate import refresh_review_dispositions
    from co_scientist.models import HypothesisReview

    from app.engine_tasks.support import merge_usage_snapshots

    successful = failed = 0
    usage: list[dict[str, Any]] = []
    for outcome in outcomes:
        hypothesis = by_id.get(outcome["hypothesis_id"])
        if outcome["kind"] != "ok":
            failed += 1
            if hypothesis is not None:
                hypothesis.review_disposition = "review_failed"
            continue
        result = outcome["result"]
        review = HypothesisReview(**result["review"])
        hypothesis = by_id[str(result["hypothesis_id"])]
        hypothesis.reviews.append(review)
        hypothesis.score = review.overall_score
        apply_initial_review_gate([hypothesis], [review], criteria)
        usage.append(result.get("model_usage") or {})
        successful += 1
    refresh_review_dispositions(by_id.values(), criteria)
    return successful, failed, merge_usage_snapshots(usage)


class _Replayed(Exception):
    def __init__(self, checkpoint_seq: int) -> None:
        self.checkpoint_seq = checkpoint_seq


def _commit_fence(node_task: ScientificTask, expected_seq: int, conn: sqlite3.Connection) -> None:
    """DBOS owns durability here, so the fence is run liveness and an
    unchanged checkpoint rather than a lease.
    """
    latest = conn.execute(
        "SELECT seq, stage FROM checkpoints WHERE run_id=? ORDER BY seq DESC LIMIT 1",
        (node_task.run_id,),
    ).fetchone()
    if latest is not None and latest["stage"] == f"engine_task:{node_task.id}":
        raise _Replayed(int(latest["seq"]))
    if latest is None or int(latest["seq"]) != expected_seq:
        raise SupersededTaskError("review checkpoint was superseded")
    row = conn.execute("SELECT status FROM runs WHERE id=?", (node_task.run_id,)).fetchone()
    if row is None or row["status"] in {status.value for status in TERMINAL_STATUSES}:
        raise SupersededTaskError("run ended before the review commit")


def _commit_review(
    node_task: ScientificTask, expected_seq: int, state: dict[str, Any], successor: str | None
) -> tuple[int, str]:
    from co_scientist.checkpoint import CHECKPOINT_VERSION, serialize_workflow_state

    from app.engine_tasks.portfolio import _enqueue_node_portfolio

    envelope = serialize_workflow_state(
        state, last_event_seq=events.latest_event_seq(node_task.run_id)
    )
    successor_type = _successor_task_type(successor)
    with db.transaction() as conn:
        _commit_fence(node_task, expected_seq, conn)
        seq = store.save_checkpoint(
            node_task.run_id,
            NewCheckpoint(
                stage=f"engine_task:{node_task.id}",
                schema_version=CHECKPOINT_VERSION,
                last_event_seq=envelope["last_event_seq"],
                state={"provider": "engine", "resume_successor": successor_type, **envelope},
            ),
            conn=conn,
        )
        head = _enqueue_node_portfolio(node_task, state, successor, successor_type, conn)
        retrieval.save_run_metrics(node_task.run_id, _metrics_snapshot(state), conn=conn)
    return seq, head.id


@DBOS.step(name="coscientist.review.commit")
async def commit_review(
    run_id: str, node_task_id: str, checkpoint_seq: int, outcomes: list[dict[str, Any]]
) -> dict[str, Any]:
    from co_scientist.task_runtime import apply_task_update, next_task_type

    from app.engine_tasks.fanout_aggregates import _review_aggregate_update
    from app.engine_tasks.support import restore_checkpoint_state

    node_task = tasks.get_task(node_task_id)
    if node_task is None:
        raise RuntimeError(f"review node task {node_task_id} disappeared")
    checkpoint = store.get_latest_checkpoint(run_id)
    if checkpoint is None:
        raise RuntimeError("review commit has no checkpoint")
    if checkpoint["stage"] == f"engine_task:{node_task.id}":
        return {"checkpoint_seq": int(checkpoint["seq"]), "replayed": True}
    if int(checkpoint["seq"]) != checkpoint_seq:
        return {"superseded": True}
    state = restore_checkpoint_state(node_task, checkpoint, None)
    by_id = {hypothesis.id: hypothesis for hypothesis in state["hypotheses"]}
    successful, failed, usage = _apply_review_outcomes(by_id, outcomes, state.get("criteria"))
    committed = apply_task_update(
        state, _review_aggregate_update(state, successful, failed, usage)
    )
    successor: str | None = next_task_type("review", committed)
    try:
        seq, successor_id = await asyncio.to_thread(
            _commit_review, node_task, checkpoint_seq, committed, successor
        )
    except _Replayed as replayed:
        return {"checkpoint_seq": replayed.checkpoint_seq, "replayed": True}
    except SupersededTaskError as exc:
        return {"superseded": True, "reason": str(exc)}
    await _emit_node_completion(run_id, NodeCompletion("review", successor, seq), committed, None)
    return {
        "checkpoint_seq": seq,
        "successor_task_id": successor_id,
        "successful_reviews": successful,
        "failed_reviews": failed,
    }


@DBOS.step(name="coscientist.review.stop_run")
async def stop_run_for_budget(run_id: str, error: str) -> None:
    from co_scientist.llm import release_run_call_budget

    from app.store.models import TaskFailure
    from app.store.runs_views import _settle_run_for_failed_task

    def _stop() -> None:
        with db.transaction() as conn:
            _settle_run_for_failed_task(
                conn,
                run_id,
                "engine.fanout.review.aggregate",
                TaskFailure(error, "llm_call_budget_exceeded"),
                retryable=False,
            )

    await asyncio.to_thread(_stop)
    release_run_call_budget(run_id)


@DBOS.workflow(name="coscientist.review.fanout")
async def review_fanout(
    run_id: str, node_task_id: str, checkpoint_seq: int, items: list[list[Any]]
) -> dict[str, Any]:
    with _run_scopes(run_id):
        parent = str(DBOS.workflow_id)
        handles = []
        for hypothesis_id, index in items:
            with SetWorkflowID(f"{parent}:{hypothesis_id}"):
                handles.append(
                    await DBOS.start_workflow_async(
                        review_item, run_id, checkpoint_seq, hypothesis_id, index
                    )
                )
        outcomes = [await handle.get_result() for handle in handles]
        budget = next((item for item in outcomes if item["kind"] == "budget"), None)
        if budget is not None:
            await stop_run_for_budget(run_id, budget["error"])
            return {"stopped": "llm_call_budget_exceeded"}
        return await commit_review(run_id, node_task_id, checkpoint_seq, outcomes)


# --- entry from the hand-built queue --------------------------------------


def start_review_fanout(
    task: ScientificTask, state: dict[str, Any], checkpoint_seq: int, *, db_path: str | None
) -> dict[str, Any]:
    """Replaces `_enqueue_review_fanout`; a redelivered node task reattaches
    to the same workflow because the workflow id is the checkpoint.
    """
    from co_scientist.models import has_peer_review

    items = [
        [hypothesis.id, index]
        for index, hypothesis in enumerate(
            h for h in state["hypotheses"] if not has_peer_review(h)
        )
    ]
    workflow_id = review_workflow_id(task.run_id, checkpoint_seq)
    with SetWorkflowID(workflow_id):
        DBOS.start_workflow(review_fanout, task.run_id, task.id, checkpoint_seq, items)
    return {
        "checkpoint_seq": checkpoint_seq,
        "dbos_workflow_id": workflow_id,
        "fanout_items": len(items),
        "node": "review",
    }


__all__ = [
    "MAX_ATTEMPTS",
    "commit_review",
    "ensure_tables",
    "review_attempt",
    "review_fanout",
    "review_item",
    "start_review_fanout",
]
