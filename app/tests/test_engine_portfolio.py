"""Tests for engine portfolio."""

from __future__ import annotations

from typing import Any

import pytest

from app import engine_tasks, store, task_worker
from app.engine_tasks import support as engine_tasks_support
from app.engine_tasks.node import _check_portfolio_predecessor
from app.engine_tasks.support import SupersededTaskError, TaskCommit
from app.task_worker import outcomes as task_worker_outcomes
from tests._engine_tasks_helpers import (
    _Generator,
    _patch_generator,
    _patch_task_node,
    _seed_checkpoint,
    _task_state,
)

# Bounded node-task portfolio coverage (finding F4).
#
# Execution used to enqueue exactly one successor node task per commit,
# reactively. These tests drive the shared commit path
# (``app.engine_tasks.support._save_state_and_enqueue``) directly to prove
# a commit now also chains however much of the deterministic tail
# ``co_scientist.task_runtime.plan_portfolio`` can already resolve, that a
# plan superseded by a real outcome (a mid-run safety halt) is cancelled
# rather than left claimable, and that a checkpoint shaped exactly as the
# pre-portfolio spine produced it still resumes and the run still settles.


def _portfolio_seed_predecessor(
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


def _seed_resume_checkpoint(
    run_id: str,
    state: dict[str, Any],
    *,
    stage: str,
    resume_successor: str,
    db_path: str,
) -> int:
    """Seed a checkpoint shaped exactly as ``_save_node_checkpoint`` would.

    ``resume_successor`` lives beside ``provider`` at the checkpoint's own
    top level, alongside (not inside) the serialized workflow-state
    payload -- the shape ``app.task_worker.enqueue._enqueue_resume_task``
    reads.
    """
    from co_scientist.checkpoint import (
        CHECKPOINT_VERSION,
        serialize_workflow_state,
    )

    envelope = serialize_workflow_state(state, last_event_seq=0)
    return store.save_checkpoint(
        run_id,
        store.NewCheckpoint(
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
    """A commit chains the deterministic hops behind its immediate successor.

    Mirrors what the real generation aggregate's commit does once
    ``mcp_available`` routes it to ``reflection``: the aggregate's own
    commit here is standing in as ``task``, and ``reflection`` is the
    successor it decided on. ``review`` -- ``reflection``'s own fixed,
    non-fanning-adjacent successor -- must already be queued and chained
    behind it, not created only once ``reflection`` itself later runs.
    """
    run = store.create_run("Portfolio lookahead", "standard", "engine", {})
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
    # review is itself a fanning node (finding F4's stop set): the plan
    # never guesses what comes after it.
    assert "engine.node.comprehensive_reflection" not in tasks


@pytest.mark.asyncio
async def test_resume_from_a_pre_portfolio_checkpoint_settles_the_run(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checkpoint shaped exactly as the old spine produced it still resumes.

    The checkpoint's own shape (``stage``, ``resume_successor``) is
    unchanged by this feature -- only how a *fresh* successor gets keyed
    changed. This seeds the checkpoint plus a successor task exactly as
    the pre-portfolio code would have left them (checkpoint-sequence
    key, no ``dependencies``) and then lets that task die, the way an
    interrupted worker's boundary would at the moment of this deploy.
    Resume does not need to revive that exact old-keyed row -- it is not
    findable under a key this code would ever construct -- but the run
    must still make forward progress and settle.
    """
    run = store.create_run("Pre-portfolio resume", "standard", "engine", {})
    # `next_task_priority` is a required (non-Optional) WorkflowState field,
    # so a round trip through a real checkpoint always restores it -- unset
    # here, it would restore as `None` rather than being absent, which the
    # orchestrator-priority read in `_enqueue_node_portfolio` (unrelated to
    # this feature -- it already read the same way before it) requires a
    # real int for.
    state = {**_task_state(run.id), "next_task_priority": 90}
    generator = _Generator(state)
    _patch_generator(monkeypatch, generator, restore=True, screen=True)

    # A real predecessor task, exactly as `_save_node_checkpoint` leaves
    # one committing today.
    predecessor = _portfolio_seed_predecessor(
        run.id, isolated_db, task_type="engine.node.supervisor"
    )
    assert store.complete_task(
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
    # The old, checkpoint-sequence-keyed successor row, already dead --
    # exhausted its retry budget, exactly as `test_task_worker_resume.py`
    # reproduces for the pre-existing scheme.
    dead = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=old_successor_type,
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"{old_successor_type}:{checkpoint_seq}",
        ),
        db_path=isolated_db,
    )
    with store.connect(isolated_db) as conn:
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
        store.update_run_status(task.run_id, store.RunStatus.COMPLETED)
        return {"run_id": task.run_id, "status": "completed"}

    _patch_task_node(monkeypatch, execute)
    # `_ENGINE_TASK_DISPATCH` binds `execute_finalize` at import time, so
    # only patching the dict entry itself (not the module attribute)
    # actually redirects dispatch, matching the stand-in used elsewhere in
    # this module.
    monkeypatch.setitem(
        engine_tasks._ENGINE_TASK_DISPATCH,
        engine_tasks_support.FINALIZE_TASK,
        finalize,
    )
    await task_worker.run_run_until_idle(run.id, "worker", db_path=isolated_db)

    settled = store.get_run(run.id, db_path=isolated_db)
    assert settled is not None
    assert settled.status == store.RunStatus.COMPLETED.value


# Portfolio chain unwinding on terminal outcomes (finding F4).
#
# A commit plans several hops ahead, so any outcome that supersedes the
# plan must unwind the whole downstream chain, not just the row one hop
# away. A queued row left depending on a cancelled or failed predecessor
# is never claimable and never removed, yet still reads as claimable work
# to ``app.store.tasks_lifecycle.cohort_poll`` -- dependency-blind by design
# -- so the run's worker cohort never concludes it is done. That is a
# hang, and it is what these tests pin against.


def _cancel_seed_predecessor(
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
    predecessor = _cancel_seed_predecessor(
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
    ``app.store.tasks_lifecycle.cohort_poll`` -- dependency-blind by design
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
    predecessor = _cancel_seed_predecessor(
        run.id, isolated_db, task_type="engine.node.orchestrator"
    )
    # meta_review is EVOLVE's prefix node *and* a periodic task of its own,
    # so what follows it is the orchestrator's own recorded decision; the
    # three-deep chain this test needs is the EVOLVE one.
    decided = {**_task_state(run.id), "next_task": "evolve"}
    checkpoint_seq = _seed_checkpoint(run.id, decided, db_path=isolated_db)
    commit = TaskCommit(predecessor, checkpoint_seq, isolated_db)
    committed_seq, _ = engine_tasks_support._save_state_and_enqueue(
        commit, decided, "meta_review"
    )
    assert store.complete_task(
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

    # meta_review now actually runs and halts instead of reaching evolve.
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
    """A mid-run safety halt cancels the lookahead it invalidates.

    A portfolio can plan a node's successor before that node actually
    runs. When the real outcome differs -- here, ``reflection`` itself
    routes to finalize instead of the ``review`` it was planned to reach
    (finding J6) -- the superseded guess must be cancelled in the same
    commit, not left queued with a dependency the real flow will still
    satisfy.
    """
    run = store.create_run("Portfolio divergence", "standard", "engine", {})
    predecessor = _cancel_seed_predecessor(run.id, isolated_db)
    checkpoint_seq = _seed_checkpoint(
        run.id, _task_state(run.id), db_path=isolated_db
    )
    commit = TaskCommit(predecessor, checkpoint_seq, isolated_db)
    committed_seq, _ = engine_tasks_support._save_state_and_enqueue(
        commit, _task_state(run.id), "reflection"
    )
    assert store.complete_task(
        predecessor.id, "worker", {}, db_path=isolated_db
    )
    tasks = {
        task.task_type: task
        for task in store.list_tasks(run.id, db_path=isolated_db)
    }
    reflection = tasks["engine.node.reflection"]
    review = tasks["engine.node.review"]
    assert review.status == "queued"

    # reflection now actually runs and halts instead of reaching review.
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

    # Belt and braces: even an already-claimed review row would refuse to
    # run rather than redo work finalize has already been scheduled over
    # (app.engine_tasks.node._check_portfolio_predecessor).
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

    ``app.store.runs_views``'s "settle the run if nothing claimable
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
    claimable, _, _park = store.cohort_poll(run.id, db_path=isolated_db)
    assert not claimable, "nothing should read as claimable once settled"

    settled = store.get_run(run.id, db_path=isolated_db)
    assert settled is not None
    assert settled.status == store.RunStatus.FAILED.value, (
        "with the orphan gone, fail_task's own settlement check must "
        "find no other claimable work and fail the run rather than "
        "leaving it running with nothing left to advance it"
    )


# One orchestrator commit materializes a stacked pass (FIX-3).
#
# Listing 01's ``DecideNextSteps`` queues several tasks from one pass; our
# precedence chain returns one. ``scheduling.policy.stack_companions`` lets
# a pass carry the listing's two periodic companions -- system feedback,
# then the research overview -- alongside its primary decision, riding the
# ``supervisor_queue_actions`` that already travel inside the
# orchestrator's own commit transaction.
#
# These tests drive the real commit path and assert the durable shape:
# several node rows from one commit, chained serially so the checkpoint
# chain cannot fork and only the head is ever claimable, each row keyed
# exactly as the later reactive enqueue of the same edge would key it, and
# the primary still named as the decision's ``next_task`` for everything
# that reads it.


_ORCHESTRATOR = "engine.node.orchestrator"
_META_REVIEW = "engine.node.meta_review"
_OVERVIEW = "engine.node.research_overview"
_FINALIZE = "engine.finalize"


def _seed_orchestrator(run_id: str, db_path: str) -> store.ScientificTask:
    """Seed and claim an orchestrator task to commit a decision from."""
    store.enqueue_task(
        store.NewTask(
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
    """Workflow state as a stacked orchestrator decision commits it."""
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
    """A stacked pass leaves two node rows, chained in order.

    The companion runs first and the primary is anchored to it, never to
    the orchestrator: two rows under the same predecessor would both be
    claimable at once and fork the single-writer checkpoint chain.
    """
    run = store.create_run("Stacked pass", "standard", "engine", {})
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
    """The stacked row and a reactive one for the same edge are one row.

    ``_enqueue_after``'s ``{task_type}:after:{predecessor id}`` key is a
    pure function of the edge, so applying the queue action and enqueueing
    the successor resolve to the same row rather than racing as two
    claimable duplicates.
    """
    run = store.create_run("Stacked key", "standard", "engine", {})
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
    """Without a companion the orchestrator commit is exactly as it was."""
    run = store.create_run("Unstacked pass", "standard", "engine", {})
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
    """Both periodic branches from one pass leave one claimable head.

    Anchoring the second companion to the orchestrator as well would put
    two rows under the same predecessor, both claimable at once against a
    single-writer checkpoint chain. Each stacked row is anchored to the
    one before it instead, so exactly one task is ever in flight and the
    rate-limit park (``task_worker.outcomes._park_rate_limited_task``)
    applies to it as it would to any single task.
    """
    run = store.create_run("Two companions", "extended", "engine", {})
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
    """The stacked row and the row meta-review's own commit makes are one.

    Both derive ``{task_type}:after:{predecessor id}`` from the same
    edge, so committing the companion for real reuses the row the
    orchestrator's pass already planned instead of racing a duplicate.
    """
    run = store.create_run("Companion edge", "extended", "engine", {})
    orchestrator = _seed_orchestrator(run.id, isolated_db)
    state = _stacked_state(run.id, "reflect", "meta_review", "synthesize")
    seq = _seed_checkpoint(run.id, state, db_path=isolated_db)

    committed = engine_tasks_support._save_state_and_enqueue(
        TaskCommit(orchestrator, seq, isolated_db), state, "meta_review"
    )
    assert store.complete_task(
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
    """A stop stacks nothing and still ends overview -> report.

    ``engine.finalize`` is enqueued only as the overview node's own
    successor, so this is the edge a stacking change must not disturb.
    """
    run = store.create_run("Terminal pass", "extended", "engine", {})
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
    assert store.complete_task(
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
    """Only the head of a stacked chain is claimable.

    Ordering exists for a reason at every hop -- the overview reads the
    critique the feedback pass writes, and the primary reads both -- so
    the dependency edges, not the enqueue order, are what has to hold.
    """
    run = store.create_run("Stacked claim", "extended", "engine", {})
    orchestrator = _seed_orchestrator(run.id, isolated_db)
    state = _stacked_state(run.id, "reflect", "meta_review", "synthesize")
    seq = _seed_checkpoint(run.id, state, db_path=isolated_db)

    engine_tasks_support._save_state_and_enqueue(
        TaskCommit(orchestrator, seq, isolated_db), state, "meta_review"
    )
    store.complete_task(orchestrator.id, "worker", {}, db_path=isolated_db)

    claimed = store.claim_task("w2", run_id=run.id, db_path=isolated_db)
    assert claimed is not None and claimed.task_type == _META_REVIEW
    assert store.claim_task("w3", run_id=run.id, db_path=isolated_db) is None
