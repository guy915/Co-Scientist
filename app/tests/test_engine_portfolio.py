from __future__ import annotations

import pytest

from app.engine_tasks import support as engine_tasks_support
from app.engine_tasks.node import _check_portfolio_predecessor
from app.engine_tasks.support import SupersededTaskError, TaskCommit
from app.store import checkpoints, runs
from app.store import tasks as store
from app.store import tasks_lifecycle as lifecycle
from app.store.models import RunStatus, ScientificTask
from app.task_worker import outcomes as task_worker_outcomes
from tests._engine_tasks_helpers import (
    _seed_checkpoint,
    _task_state,
)
from tests._store_helpers import enqueue_task, seed_run


def _portfolio_seed_predecessor(
    run_id: str, db_path: str, task_type: str = "engine.node.generate"
) -> ScientificTask:
    enqueue_task(run_id, task_type, f"{task_type}:seed", db_path=db_path)
    leased = store.claim_task("worker", run_id=run_id, db_path=db_path)
    assert leased is not None
    return leased


@pytest.mark.asyncio
async def test_commit_plans_the_resolvable_tail_behind_the_successor(
    isolated_db: str,
) -> None:
    run = seed_run("Portfolio lookahead")
    predecessor = _portfolio_seed_predecessor(run.id, isolated_db)
    checkpoint_seq = _seed_checkpoint(
        run.id, _task_state(run.id), db_path=isolated_db
    )
    commit = TaskCommit(predecessor, checkpoint_seq, isolated_db)

    engine_tasks_support._save_state_and_enqueue(
        commit, _task_state(run.id), "reflection"
    )

    tasks = {
        task.task_type: task
        for task in store.list_tasks(run.id, db_path=isolated_db)
    }
    reflection = tasks["engine.node.reflection"]
    review = tasks["engine.node.review"]
    assert reflection.status == "queued"
    assert review.status == "queued"
    assert reflection.dependencies == (predecessor.id,)
    assert review.dependencies == (reflection.id,)
    assert (
        reflection.idempotency_key
        == f"engine.node.reflection:after:{predecessor.id}"
    )
    assert review.idempotency_key == f"engine.node.review:after:{reflection.id}"
    assert "engine.node.comprehensive_reflection" not in tasks


# Cancel whole downstream chains on superseded outcomes; orphan queued rows
# prevent cohort settlement.


@pytest.mark.asyncio
async def test_a_supervisor_cancel_of_a_mid_chain_row_cascades_downstream(
    isolated_db: str,
) -> None:
    # Supervisor cancellation must unwind dependent portfolios or impossible
    # prerequisites strand queued work.
    run = seed_run("Supervisor cancel cascade")
    predecessor = _portfolio_seed_predecessor(
        run.id, isolated_db, task_type="engine.node.orchestrator"
    )
    checkpoint_seq = _seed_checkpoint(
        run.id, _task_state(run.id), db_path=isolated_db
    )
    evolve = enqueue_task(
        run.id,
        "engine.node.evolve",
        f"engine.node.evolve:after:{predecessor.id}",
        dependencies=(predecessor.id,),
        db_path=isolated_db,
    )
    review = enqueue_task(
        run.id,
        "engine.node.review",
        f"engine.node.review:after:{evolve.id}",
        dependencies=(evolve.id,),
        db_path=isolated_db,
    )

    orchestrator_commit = TaskCommit(predecessor, checkpoint_seq, isolated_db)
    state = {
        **_task_state(run.id),
        "next_task_priority": 90,
        "supervisor_queue_actions": [
            {
                "action": "cancel",
                "task_id": evolve.id,
                "reason": "Deprioritized.",
            }
        ],
    }
    engine_tasks_support._save_state_and_enqueue(
        orchestrator_commit, state, "proximity"
    )

    evolve_after = store.get_task(evolve.id, db_path=isolated_db)
    review_after = store.get_task(review.id, db_path=isolated_db)
    assert evolve_after is not None and evolve_after.status == "cancelled"
    assert review_after is not None and review_after.status == "cancelled", (
        "review is chained behind the cancelled evolve row and must be "
        "cancelled too, or it is permanently unclaimable"
    )


def _assert_no_unsatisfiable_dependency(run_id: str, db_path: str) -> None:
    # Queued rows behind failed/cancelled prerequisites are never claimable but
    # keep cohorts alive forever.
    tasks = {t.id: t for t in store.list_tasks(run_id, db_path=db_path)}
    dead = {"cancelled", "failed"}
    for task in tasks.values():
        if task.status != "queued":
            continue
        for dep_id in task.dependencies:
            dep = tasks.get(dep_id)
            if dep is not None and dep.status in dead:
                pytest.fail(
                    f"{task.task_type} ({task.id}) is queued but depends "
                    f"on {dep.task_type} ({dep.id}), status={dep.status}"
                )


@pytest.mark.asyncio
async def test_a_diverging_outcome_cancels_the_whole_downstream_tail(
    isolated_db: str,
) -> None:
    # Use multi-hop divergence; single-hop fixtures cannot expose orphaned
    # descendants.
    run = seed_run("Portfolio deep divergence")
    predecessor = _portfolio_seed_predecessor(
        run.id, isolated_db, task_type="engine.node.orchestrator"
    )
    decided = {**_task_state(run.id), "next_task": "evolve"}
    checkpoint_seq = _seed_checkpoint(run.id, decided, db_path=isolated_db)
    commit = TaskCommit(predecessor, checkpoint_seq, isolated_db)
    committed_seq, _ = engine_tasks_support._save_state_and_enqueue(
        commit, decided, "meta_review"
    )
    assert lifecycle.complete_task(
        predecessor.id, "worker", {}, db_path=isolated_db
    )
    tasks = {
        task.task_type: task
        for task in store.list_tasks(run.id, db_path=isolated_db)
    }
    meta_review = tasks["engine.node.meta_review"]
    evolve = tasks["engine.node.evolve"]
    review = tasks["engine.node.review"]
    assert evolve.status == "queued"
    assert review.status == "queued"
    assert review.dependencies == (evolve.id,), (
        "review must depend on evolve, not on meta_review directly, or "
        "this test is not exercising the transitive case"
    )

    leased_meta_review = store.claim_task(
        "worker", run_id=run.id, db_path=isolated_db
    )
    assert leased_meta_review is not None
    assert leased_meta_review.id == meta_review.id
    halted_state = {**_task_state(run.id), "safety_blocked": True}
    meta_review_commit = TaskCommit(
        leased_meta_review, committed_seq, isolated_db
    )
    engine_tasks_support._save_state_and_enqueue(
        meta_review_commit, halted_state, None
    )

    refreshed = {
        task.task_type: task
        for task in store.list_tasks(run.id, db_path=isolated_db)
    }
    assert refreshed["engine.node.evolve"].status == "cancelled"
    assert refreshed["engine.node.review"].status == "cancelled", (
        "review is two hops from the diverging task and must be "
        "cancelled too, or it is permanently unclaimable"
    )
    assert refreshed["engine.finalize"].status == "queued"
    _assert_no_unsatisfiable_dependency(run.id, isolated_db)

    checkpoint = checkpoints.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    with pytest.raises(SupersededTaskError):
        _check_portfolio_predecessor(review, checkpoint)


def test_a_permanent_failure_cancels_the_downstream_chain(
    isolated_db: str,
) -> None:
    # Permanent failure must cancel dependent chains within settlement's
    # transaction or the run stays nonterminal.
    run = seed_run("Portfolio permanent failure")
    runs.update_run_status(run.id, RunStatus.RUNNING, db_path=isolated_db)
    evolve = enqueue_task(
        run.id,
        "engine.node.evolve",
        "evolve:seed",
        max_attempts=1,
        db_path=isolated_db,
    )
    leased_evolve = store.claim_task(
        "worker", run_id=run.id, db_path=isolated_db
    )
    assert leased_evolve is not None and leased_evolve.id == evolve.id

    review = enqueue_task(
        run.id,
        "engine.node.review",
        f"engine.node.review:after:{evolve.id}",
        dependencies=(evolve.id,),
        db_path=isolated_db,
    )
    assert review.status == "queued"

    task_worker_outcomes._fail_retryable_task(
        leased_evolve, "worker", RuntimeError("provider error"), isolated_db
    )

    evolve_after = store.get_task(evolve.id, db_path=isolated_db)
    review_after = store.get_task(review.id, db_path=isolated_db)
    assert evolve_after is not None and evolve_after.status == "failed"
    assert review_after is not None and review_after.status == "cancelled", (
        "the downstream row must be cancelled, or it is permanently "
        "queued and unclaimable"
    )
    claimable, _, _park = lifecycle.cohort_poll(run.id, db_path=isolated_db)
    assert not claimable, "nothing should read as claimable once settled"

    settled = runs.get_run(run.id, db_path=isolated_db)
    assert settled is not None
    assert settled.status == RunStatus.FAILED.value, (
        "with the orphan gone, fail_task's own settlement check must "
        "find no other claimable work and fail the run rather than "
        "leaving it running with nothing left to advance it"
    )


_ORCHESTRATOR = "engine.node.orchestrator"
_META_REVIEW = "engine.node.meta_review"
_OVERVIEW = "engine.node.research_overview"
_FINALIZE = "engine.finalize"


def _seed_orchestrator(run_id: str, db_path: str) -> ScientificTask:
    enqueue_task(
        run_id, _ORCHESTRATOR, f"{_ORCHESTRATOR}:seed", db_path=db_path
    )
    leased = store.claim_task("worker", run_id=run_id, db_path=db_path)
    assert leased is not None
    return leased


def _stacked_state(
    run_id: str, next_task: str, *companions: str
) -> dict[str, object]:
    return {
        **_task_state(run_id),
        "next_task": next_task,
        "next_task_priority": 90,
        "supervisor_queue_actions": [
            {
                "action": "enqueue",
                "task_type": companion,
                "reason": "a periodic branch is due",
            }
            for companion in (companions or ("meta_review",))
        ],
    }


@pytest.mark.asyncio
async def test_two_companions_chain_rather_than_fork(
    isolated_db: str,
) -> None:
    # Only one stacked head can be claimable so checkpoint commits remain
    # single-writer.
    run = seed_run("Two companions", profile="extended")
    orchestrator = _seed_orchestrator(run.id, isolated_db)
    state = _stacked_state(run.id, "reflect", "meta_review", "synthesize")
    seq = _seed_checkpoint(run.id, state, db_path=isolated_db)

    engine_tasks_support._save_state_and_enqueue(
        TaskCommit(orchestrator, seq, isolated_db), state, "meta_review"
    )

    tasks = {
        task.task_type: task
        for task in store.list_tasks(run.id, db_path=isolated_db)
    }
    assert tasks[_META_REVIEW].dependencies == (orchestrator.id,)
    assert tasks[_OVERVIEW].dependencies == (tasks[_META_REVIEW].id,)
    assert tasks["engine.node.review"].dependencies == (tasks[_OVERVIEW].id,)
    # Edge-derived keys make planned and reactive enqueues resolve to one row.
    assert (
        tasks[_META_REVIEW].idempotency_key
        == f"{_META_REVIEW}:after:{orchestrator.id}"
    )
    # Dependency edges enforce data ordering, not enqueue order.
    lifecycle.complete_task(orchestrator.id, "worker", {}, db_path=isolated_db)
    claimed = store.claim_task("w2", run_id=run.id, db_path=isolated_db)
    assert claimed is not None and claimed.task_type == _META_REVIEW
    assert store.claim_task("w3", run_id=run.id, db_path=isolated_db) is None


@pytest.mark.asyncio
async def test_the_companion_edge_collides_with_its_reactive_enqueue(
    isolated_db: str,
) -> None:
    run = seed_run("Companion edge", profile="extended")
    orchestrator = _seed_orchestrator(run.id, isolated_db)
    state = _stacked_state(run.id, "reflect", "meta_review", "synthesize")
    seq = _seed_checkpoint(run.id, state, db_path=isolated_db)

    committed = engine_tasks_support._save_state_and_enqueue(
        TaskCommit(orchestrator, seq, isolated_db), state, "meta_review"
    )
    assert lifecycle.complete_task(
        orchestrator.id, "worker", {}, db_path=isolated_db
    )
    meta_review = next(
        task
        for task in store.list_tasks(run.id, db_path=isolated_db)
        if task.task_type == _META_REVIEW
    )
    leased_meta_review = store.claim_task(
        "worker", run_id=run.id, db_path=isolated_db
    )
    assert leased_meta_review is not None
    assert leased_meta_review.id == meta_review.id
    engine_tasks_support._save_state_and_enqueue(
        TaskCommit(leased_meta_review, committed[0], isolated_db),
        state,
        "research_overview",
    )

    rows = [
        task
        for task in store.list_tasks(run.id, db_path=isolated_db)
        if task.task_type == _OVERVIEW
    ]
    assert len(rows) == 1
    assert rows[0].idempotency_key == f"{_OVERVIEW}:after:{meta_review.id}"


@pytest.mark.asyncio
async def test_the_terminal_decision_writes_an_overview_then_a_report(
    isolated_db: str,
) -> None:
    run = seed_run("Terminal pass", profile="extended")
    orchestrator = _seed_orchestrator(run.id, isolated_db)
    state = {
        **_task_state(run.id),
        "next_task": "terminate",
        "next_task_priority": 90,
        "supervisor_queue_actions": [],
    }
    seq = _seed_checkpoint(run.id, state, db_path=isolated_db)

    committed = engine_tasks_support._save_state_and_enqueue(
        TaskCommit(orchestrator, seq, isolated_db), state, "research_overview"
    )
    assert lifecycle.complete_task(
        orchestrator.id, "worker", {}, db_path=isolated_db
    )
    overview = next(
        task
        for task in store.list_tasks(run.id, db_path=isolated_db)
        if task.task_type == _OVERVIEW
    )
    leased_overview = store.claim_task(
        "worker", run_id=run.id, db_path=isolated_db
    )
    assert leased_overview is not None
    assert leased_overview.id == overview.id
    engine_tasks_support._save_state_and_enqueue(
        TaskCommit(leased_overview, committed[0], isolated_db), state, None
    )

    finalize = next(
        task
        for task in store.list_tasks(run.id, db_path=isolated_db)
        if task.task_type == _FINALIZE
    )
    assert overview.dependencies == (orchestrator.id,)
    assert finalize.dependencies == (overview.id,)
