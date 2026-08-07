"""Portfolio chain unwinding on terminal outcomes (finding F4).

A commit plans several hops ahead, so any outcome that supersedes the
plan must unwind the whole downstream chain, not just the row one hop
away. A queued row left depending on a cancelled or failed predecessor
is never claimable and never removed, yet still reads as claimable work
to ``app.store.tasks_probes.cohort_poll`` -- dependency-blind by design
-- so the run's worker cohort never concludes it is done. That is a
hang, and it is what these tests pin against.
"""

from __future__ import annotations

import pytest

from app import (
    engine_tasks_support,
    store,
    task_worker_outcomes,
)
from app.engine_tasks_context import TaskCommit
from app.engine_tasks_node import _check_portfolio_predecessor
from app.engine_tasks_support import SupersededTaskError
from tests._engine_tasks_helpers import (
    _seed_checkpoint,
    _task_state,
)


def _seed_predecessor(
    run_id: str, db_path: str, task_type: str = "engine.node.generate"
) -> store.ScientificTask:
    """Seed and claim a stand-in predecessor task for a portfolio commit."""
    store.enqueue_task(
        store.NewTask(
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
    """The Supervisor's own cancel of a portfolio row cascades too.

    ``_apply_single_queue_action``'s "cancel" is a third path that can
    single-cancel a portfolio-chained row (alongside a diverging outcome
    and a permanent failure, finding F4): the Supervisor may request it
    directly as a scheduling decision, targeting any row its own
    ``_durable_queue_snapshot`` shows it -- including one mid-chain.
    Cancelling only that row would leave anything chained behind it
    ``queued`` forever with a dependency that can now never reach
    ``completed``, exactly as an uncascaded divergence or permanent
    failure would.
    """
    run = store.create_run(
        "Supervisor cancel cascade", "standard", "engine", {}
    )
    predecessor = _seed_predecessor(
        run.id, isolated_db, task_type="engine.node.orchestrator"
    )
    checkpoint_seq = _seed_checkpoint(
        run.id, _task_state(run.id), db_path=isolated_db
    )
    # Plant a two-hop chain to cancel into: evolve -> review.
    evolve = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.node.evolve",
            inputs={},
            idempotency_key=f"engine.node.evolve:after:{predecessor.id}",
            dependencies=(predecessor.id,),
        ),
        db_path=isolated_db,
    )
    review = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type="engine.node.review",
            inputs={},
            idempotency_key=f"engine.node.review:after:{evolve.id}",
            dependencies=(evolve.id,),
        ),
        db_path=isolated_db,
    )

    # The orchestrator's own commit asks to cancel the mid-chain row.
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
    """Fail if any queued row depends on a row that can never complete.

    The concrete shape of finding F4's hang regression (reported against
    ``tests/test_system_safety_monitor.py``): a queued row whose sole
    dependency is ``cancelled`` or ``failed`` will never be claimed and
    is never removed, yet still reads as claimable work to
    ``app.store.tasks_probes.cohort_poll`` -- dependency-blind by design
    -- so a run's worker cohort never concludes there is nothing left to
    do. That is a hang, not a slow settle.
    """
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
    """A divergence two or more hops deep leaves no orphaned dependent.

    Regression (reported against ``tests/test_system_safety_monitor.py``,
    which hung indefinitely): cancelling only the row directly superseded
    left anything chained *behind* that row -- two or more hops into the
    original plan -- permanently ``queued`` with a dependency on a row
    that would never reach ``completed``. A shallower, one-hop-deep
    divergence (the sibling test below) cannot exercise this: there, the
    only planned row *is* the direct dependent, so cancelling it alone
    happened to be enough and this class of bug passed unnoticed.

    Mirrors the real chain a live run plans from an orchestrator decision
    of "meta_review" (``meta_review`` -> ``evolve`` -> ``review``, three
    deep -- confirmed against a real offline run) with a safety halt
    (finding J6) at the first hop.
    """
    run = store.create_run(
        "Portfolio deep divergence", "standard", "engine", {}
    )
    predecessor = _seed_predecessor(
        run.id, isolated_db, task_type="engine.node.orchestrator"
    )
    checkpoint_seq = _seed_checkpoint(
        run.id, _task_state(run.id), db_path=isolated_db
    )
    commit = TaskCommit(predecessor, checkpoint_seq, isolated_db)
    committed_seq, _ = engine_tasks_support._save_state_and_enqueue(
        commit, _task_state(run.id), "meta_review"
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

    # meta_review now actually runs and halts instead of reaching evolve.
    halted_state = {**_task_state(run.id), "safety_blocked": True}
    meta_review_commit = TaskCommit(meta_review, committed_seq, isolated_db)
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
    """A mid-run safety halt cancels the lookahead it invalidates.

    A portfolio can plan a node's successor before that node actually
    runs. When the real outcome differs -- here, ``reflection`` itself
    routes to finalize instead of the ``review`` it was planned to reach
    (finding J6) -- the superseded guess must be cancelled in the same
    commit, not left queued with a dependency the real flow will still
    satisfy.
    """
    run = store.create_run("Portfolio divergence", "standard", "engine", {})
    predecessor = _seed_predecessor(run.id, isolated_db)
    checkpoint_seq = _seed_checkpoint(
        run.id, _task_state(run.id), db_path=isolated_db
    )
    commit = TaskCommit(predecessor, checkpoint_seq, isolated_db)
    committed_seq, _ = engine_tasks_support._save_state_and_enqueue(
        commit, _task_state(run.id), "reflection"
    )
    tasks = {
        task.task_type: task
        for task in store.list_tasks(run.id, db_path=isolated_db)
    }
    reflection = tasks["engine.node.reflection"]
    review = tasks["engine.node.review"]
    assert review.status == "queued"

    # reflection now actually runs and halts instead of reaching review.
    halted_state = {**_task_state(run.id), "safety_blocked": True}
    reflection_commit = TaskCommit(reflection, committed_seq, isolated_db)
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

    # Belt and braces: even an already-claimed review row would refuse to
    # run rather than redo work finalize has already been scheduled over
    # (app.engine_tasks_node._check_portfolio_predecessor).
    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    with pytest.raises(SupersededTaskError):
        _check_portfolio_predecessor(review, checkpoint)


def test_a_permanent_failure_cancels_the_downstream_chain(
    isolated_db: str,
) -> None:
    """A task that exhausts its retry budget cancels its own chain too.

    Regression (reported against ``tests/test_system_safety_monitor.py``,
    which hung indefinitely): a task that never gets to commit a real
    successor -- because it fails permanently instead of running to a
    real outcome -- never reaches ``_save_state_and_enqueue``, so
    ``_cancel_stale_planned_chain`` never runs for it either. A
    lookahead a portfolio chained behind it stays ``queued`` forever
    with a dependency that can now never reach ``completed``.

    ``app.store.runs_reconcile``'s "settle the run if nothing claimable
    remains" check has exactly one chance to see this, inside
    ``fail_task``'s own transaction; if the orphan is still queued at
    that moment the run is never settled failed either -- left
    non-terminal forever with no worker left to advance it, the shape
    ``AGENTS.md`` records from a previous incident.
    """
    run = store.create_run(
        "Portfolio permanent failure", "standard", "engine", {}
    )
    store.update_run_status(
        run.id, store.RunStatus.RUNNING, db_path=isolated_db
    )
    evolve = store.enqueue_task(
        store.NewTask(
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
        store.NewTask(
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
    claimable, _ = store.cohort_poll(run.id, db_path=isolated_db)
    assert not claimable, "nothing should read as claimable once settled"

    settled = store.get_run(run.id, db_path=isolated_db)
    assert settled is not None
    assert settled.status == store.RunStatus.FAILED.value, (
        "with the orphan gone, fail_task's own settlement check must "
        "find no other claimable work and fail the run rather than "
        "leaving it running with nothing left to advance it"
    )
