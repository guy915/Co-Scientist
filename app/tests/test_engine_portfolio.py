from __future__ import annotations

from typing import Any

import pytest

from app import engine_tasks, task_worker
from app.engine_tasks import support as engine_tasks_support
from app.engine_tasks.node import _check_portfolio_predecessor
from app.engine_tasks.support import SupersededTaskError, TaskCommit
from app.store import checkpoints, db, runs
from app.store import tasks as store
from app.store import tasks_lifecycle as lifecycle
from app.store.checkpoints import NewCheckpoint
from app.store.models import RunStatus, ScientificTask
from app.store.tasks import NewTask
from app.task_worker import outcomes as task_worker_outcomes
from tests._engine_tasks_helpers import (
    _Generator,
    _patch_generator,
    _patch_task_node,
    _seed_checkpoint,
    _task_state,
)


def _portfolio_seed_predecessor(
    run_id: str, db_path: str, task_type: str = "engine.node.generate"
) -> ScientificTask:
    store.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=task_type,
            inputs={},
            idempotency_key=f"{task_type}:seed",
        ),
        db_path=db_path,
    )
    leased = store.claim_task("worker", run_id=run_id, db_path=db_path)
    assert leased is not None
    return leased


def _seed_resume_checkpoint(
    run_id: str,
    state: dict[str, Any],
    *,
    stage: str,
    resume_successor: str,
    db_path: str,
) -> int:
    # Resume successor belongs beside provider at checkpoint top level, not
    # inside serialized workflow state.
    from co_scientist.checkpoint import (
        CHECKPOINT_VERSION,
        serialize_workflow_state,
    )

    envelope = serialize_workflow_state(state, last_event_seq=0)
    return checkpoints.save_checkpoint(
        run_id,
        NewCheckpoint(
            stage=stage,
            schema_version=CHECKPOINT_VERSION,
            last_event_seq=0,
            state={
                "provider": "engine",
                "resume_successor": resume_successor,
                **envelope,
            },
        ),
        db_path=db_path,
    )


@pytest.mark.asyncio
async def test_commit_plans_the_resolvable_tail_behind_the_successor(
    isolated_db: str,
) -> None:
    run = runs.create_run("Portfolio lookahead", "standard", "engine", {})
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


@pytest.mark.asyncio
async def test_resume_from_a_pre_portfolio_checkpoint_settles_the_run(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Legacy checkpoint-sequence tasks must still progress across edge-key
    # changes even if recovery creates a new row.
    run = runs.create_run("Pre-portfolio resume", "standard", "engine", {})
    # Checkpoint restore supplies next_task_priority; fixtures need an int
    # rather than a restored None.
    state = {**_task_state(run.id), "next_task_priority": 90}
    generator = _Generator(state)
    _patch_generator(monkeypatch, generator, restore=True, screen=True)

    predecessor = _portfolio_seed_predecessor(
        run.id, isolated_db, task_type="engine.node.supervisor"
    )
    assert lifecycle.complete_task(
        predecessor.id, "worker", {}, db_path=isolated_db
    )

    old_successor_type = "engine.node.orchestrator"
    checkpoint_seq = _seed_resume_checkpoint(
        run.id,
        state,
        stage=f"engine_task:{predecessor.id}",
        resume_successor=old_successor_type,
        db_path=isolated_db,
    )
    dead = store.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type=old_successor_type,
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"{old_successor_type}:{checkpoint_seq}",
        ),
        db_path=isolated_db,
    )
    with db.connect(isolated_db) as conn:
        conn.execute(
            "UPDATE scientific_tasks SET status='failed', "
            "attempt=max_attempts WHERE id=?",
            (dead.id,),
        )

    resumed = task_worker.enqueue_run_workflow(
        run.id, resume=True, db_path=isolated_db
    )
    assert resumed.task_type == old_successor_type
    assert resumed.id != dead.id, "the dead old-keyed row is not revived"
    assert resumed.dependencies == (predecessor.id,)

    successors = {
        "orchestrator": "research_overview",
        "research_overview": None,
    }

    async def execute(
        name: str, task_state: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        return task_state, successors[name]

    async def finalize(task: Any, **_: Any) -> dict[str, Any]:
        runs.update_run_status(task.run_id, RunStatus.COMPLETED)
        return {"run_id": task.run_id, "status": "completed"}

    _patch_task_node(monkeypatch, execute)
    # Dispatch binds callables at import; patch the dispatch dictionary rather
    # than an unrelated module name.
    monkeypatch.setitem(
        engine_tasks._ENGINE_TASK_DISPATCH,
        engine_tasks_support.FINALIZE_TASK,
        finalize,
    )
    await task_worker.run_run_until_idle(run.id, "worker", db_path=isolated_db)

    settled = runs.get_run(run.id, db_path=isolated_db)
    assert settled is not None
    assert settled.status == RunStatus.COMPLETED.value


# Cancel whole downstream chains on superseded outcomes; orphan queued rows
# prevent cohort settlement.


def _cancel_seed_predecessor(
    run_id: str, db_path: str, task_type: str = "engine.node.generate"
) -> ScientificTask:
    store.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=task_type,
            inputs={},
            idempotency_key=f"{task_type}:seed",
        ),
        db_path=db_path,
    )
    leased = store.claim_task("worker", run_id=run_id, db_path=db_path)
    assert leased is not None
    return leased


@pytest.mark.asyncio
async def test_a_supervisor_cancel_of_a_mid_chain_row_cascades_downstream(
    isolated_db: str,
) -> None:
    # Supervisor cancellation must unwind dependent portfolios or impossible
    # prerequisites strand queued work.
    run = runs.create_run("Supervisor cancel cascade", "standard", "engine", {})
    predecessor = _cancel_seed_predecessor(
        run.id, isolated_db, task_type="engine.node.orchestrator"
    )
    checkpoint_seq = _seed_checkpoint(
        run.id, _task_state(run.id), db_path=isolated_db
    )
    evolve = store.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="engine.node.evolve",
            inputs={},
            idempotency_key=f"engine.node.evolve:after:{predecessor.id}",
            dependencies=(predecessor.id,),
        ),
        db_path=isolated_db,
    )
    review = store.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="engine.node.review",
            inputs={},
            idempotency_key=f"engine.node.review:after:{evolve.id}",
            dependencies=(evolve.id,),
        ),
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
    run = runs.create_run("Portfolio deep divergence", "standard", "engine", {})
    predecessor = _cancel_seed_predecessor(
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


@pytest.mark.asyncio
async def test_a_diverging_outcome_cancels_the_superseded_plan(
    isolated_db: str,
) -> None:
    # Real outcomes invalidate planned guesses; cancel stale successors in the
    # same checkpoint commit.
    run = runs.create_run("Portfolio divergence", "standard", "engine", {})
    predecessor = _cancel_seed_predecessor(run.id, isolated_db)
    checkpoint_seq = _seed_checkpoint(
        run.id, _task_state(run.id), db_path=isolated_db
    )
    commit = TaskCommit(predecessor, checkpoint_seq, isolated_db)
    committed_seq, _ = engine_tasks_support._save_state_and_enqueue(
        commit, _task_state(run.id), "reflection"
    )
    assert lifecycle.complete_task(
        predecessor.id, "worker", {}, db_path=isolated_db
    )
    tasks = {
        task.task_type: task
        for task in store.list_tasks(run.id, db_path=isolated_db)
    }
    reflection = tasks["engine.node.reflection"]
    review = tasks["engine.node.review"]
    assert review.status == "queued"

    leased_reflection = store.claim_task(
        "worker", run_id=run.id, db_path=isolated_db
    )
    assert leased_reflection is not None
    assert leased_reflection.id == reflection.id
    halted_state = {**_task_state(run.id), "safety_blocked": True}
    reflection_commit = TaskCommit(
        leased_reflection, committed_seq, isolated_db
    )
    engine_tasks_support._save_state_and_enqueue(
        reflection_commit, halted_state, None
    )

    refreshed = {
        task.task_type: task
        for task in store.list_tasks(run.id, db_path=isolated_db)
    }
    assert refreshed["engine.node.review"].status == "cancelled"
    assert refreshed["engine.finalize"].status == "queued"
    assert refreshed["engine.finalize"].dependencies == (reflection.id,)
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
    run = runs.create_run(
        "Portfolio permanent failure", "standard", "engine", {}
    )
    runs.update_run_status(run.id, RunStatus.RUNNING, db_path=isolated_db)
    evolve = store.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="engine.node.evolve",
            inputs={},
            idempotency_key="evolve:seed",
            max_attempts=1,
        ),
        db_path=isolated_db,
    )
    leased_evolve = store.claim_task(
        "worker", run_id=run.id, db_path=isolated_db
    )
    assert leased_evolve is not None and leased_evolve.id == evolve.id

    review = store.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type="engine.node.review",
            inputs={},
            idempotency_key=f"engine.node.review:after:{evolve.id}",
            dependencies=(evolve.id,),
        ),
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
    store.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=_ORCHESTRATOR,
            inputs={},
            idempotency_key=f"{_ORCHESTRATOR}:seed",
        ),
        db_path=db_path,
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
async def test_one_commit_queues_the_companion_and_the_primary(
    isolated_db: str,
) -> None:
    # Chain stacked companions serially; siblings under one predecessor fork the
    # single-writer checkpoint path.
    run = runs.create_run("Stacked pass", "standard", "engine", {})
    orchestrator = _seed_orchestrator(run.id, isolated_db)
    state = _stacked_state(run.id, "reflect")
    seq = _seed_checkpoint(run.id, state, db_path=isolated_db)

    engine_tasks_support._save_state_and_enqueue(
        TaskCommit(orchestrator, seq, isolated_db), state, "meta_review"
    )

    tasks = {
        task.task_type: task
        for task in store.list_tasks(run.id, db_path=isolated_db)
    }
    meta_review = tasks[_META_REVIEW]
    review = tasks["engine.node.review"]
    assert meta_review.dependencies == (orchestrator.id,)
    assert review.dependencies == (meta_review.id,)
    assert meta_review.status == "queued"
    assert review.status == "queued"


@pytest.mark.asyncio
async def test_the_companion_row_is_keyed_for_collision(
    isolated_db: str,
) -> None:
    # Edge-derived idempotency makes planned and reactive enqueue resolve to the
    # same row.
    run = runs.create_run("Stacked key", "standard", "engine", {})
    orchestrator = _seed_orchestrator(run.id, isolated_db)
    state = _stacked_state(run.id, "proximity")
    seq = _seed_checkpoint(run.id, state, db_path=isolated_db)

    engine_tasks_support._save_state_and_enqueue(
        TaskCommit(orchestrator, seq, isolated_db), state, "meta_review"
    )

    rows = [
        task
        for task in store.list_tasks(run.id, db_path=isolated_db)
        if task.task_type == _META_REVIEW
    ]
    assert len(rows) == 1
    assert rows[0].idempotency_key == f"{_META_REVIEW}:after:{orchestrator.id}"


@pytest.mark.asyncio
async def test_an_unstacked_commit_queues_only_its_own_successor(
    isolated_db: str,
) -> None:
    run = runs.create_run("Unstacked pass", "standard", "engine", {})
    orchestrator = _seed_orchestrator(run.id, isolated_db)
    state = {
        **_task_state(run.id),
        "next_task": "proximity",
        "next_task_priority": 90,
    }
    seq = _seed_checkpoint(run.id, state, db_path=isolated_db)

    engine_tasks_support._save_state_and_enqueue(
        TaskCommit(orchestrator, seq, isolated_db), state, "proximity"
    )

    types = {
        task.task_type for task in store.list_tasks(run.id, db_path=isolated_db)
    }
    assert _META_REVIEW not in types
    assert "engine.node.proximity" in types


@pytest.mark.asyncio
async def test_two_companions_chain_rather_than_fork(
    isolated_db: str,
) -> None:
    # Only one stacked head can be claimable so checkpoint commits remain
    # single-writer.
    run = runs.create_run("Two companions", "extended", "engine", {})
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


@pytest.mark.asyncio
async def test_the_companion_edge_collides_with_its_reactive_enqueue(
    isolated_db: str,
) -> None:
    run = runs.create_run("Companion edge", "extended", "engine", {})
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
    run = runs.create_run("Terminal pass", "extended", "engine", {})
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


@pytest.mark.asyncio
async def test_a_stacked_task_cannot_run_before_its_inputs(
    isolated_db: str,
) -> None:
    # Dependency edges enforce data ordering, not enqueue order; overview
    # consumes feedback before the primary.
    run = runs.create_run("Stacked claim", "extended", "engine", {})
    orchestrator = _seed_orchestrator(run.id, isolated_db)
    state = _stacked_state(run.id, "reflect", "meta_review", "synthesize")
    seq = _seed_checkpoint(run.id, state, db_path=isolated_db)

    engine_tasks_support._save_state_and_enqueue(
        TaskCommit(orchestrator, seq, isolated_db), state, "meta_review"
    )
    lifecycle.complete_task(orchestrator.id, "worker", {}, db_path=isolated_db)

    claimed = store.claim_task("w2", run_id=run.id, db_path=isolated_db)
    assert claimed is not None and claimed.task_type == _META_REVIEW
    assert store.claim_task("w3", run_id=run.id, db_path=isolated_db) is None
