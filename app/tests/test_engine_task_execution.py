from __future__ import annotations

import dataclasses
import time
from typing import Any

import pytest
from co_scientist.agents.meta_review import research_overview as ro
from co_scientist.llm import (
    ModelCallStats,
    current_run_call_count,
    record_call,
    release_run_call_budget,
)
from co_scientist.llm.admission.call_budget import record_provider_request
from co_scientist.models import (
    Article,
    ExecutionMetrics,
    Hypothesis,
    HypothesisReview,
)
from co_scientist.workflow_topology import LiteratureGated
from litellm.exceptions import APIError

import app.engine_adapter.drain.final_state as drain_claim_grounding
import app.engine_tasks.fanout as engine_tasks_fanout_items
import app.engine_tasks.support as engine_tasks_context
from app import engine_tasks, safety, task_worker
from app.engine_tasks import fanout_aggregates as engine_tasks_fanout_aggregates
from app.engine_tasks import finalize as engine_tasks_node
from app.engine_tasks import node as engine_tasks_restore
from app.engine_tasks import ranking as engine_tasks_ranking
from app.engine_tasks import runtime as engine_tasks_runtime
from app.engine_tasks import support as engine_tasks_support
from app.engine_tasks.runtime import ProductionEngineTaskRuntime
from app.engine_tasks.support import TaskCommit
from app.run_modes import RUN_TIER_DEFAULTS, resolved_run_config
from app.safety import ScreenSubject
from app.store import checkpoints, messages, records, reports, runs
from app.store import events as store_events
from app.store import retrieval_calls as retrieval
from app.store import tasks as store_tasks
from app.store import tasks_lifecycle as lifecycle
from app.store.checkpoints import NewCheckpoint
from app.store.messages import NewMessage
from app.store.models import RunStatus, ScientificTask
from app.store.tasks import NewTask
from tests._engine_tasks_helpers import (
    FakeEngineTaskRuntime,
    _Generator,
    _install_plain_fake_judge,
    _install_runtime,
    _milestones,
    _patch_generator,
    _patch_restore_generator,
    _patch_task_node,
    _RankingSeed,
    _run_ranking_node,
    _seed_checkpoint,
    _seed_ranking_node,
    _task_state,
)


def _priority_state(run_id: str, deferred_id: str) -> dict[str, Any]:
    return {
        **_task_state(run_id),
        "next_task_priority": 97,
        "supervisor_queue_actions": [
            {
                "action": "reprioritize",
                "task_id": deferred_id,
                "priority": 98,
                "reason": "Review backlog is urgent.",
            }
        ],
    }


def _seed_orchestrator_task(run_id: str, db_path: str) -> tuple[Any, Any]:
    checkpoints.save_checkpoint(
        run_id,
        NewCheckpoint(
            stage="seed",
            schema_version=1,
            last_event_seq=0,
            state={"provider": "engine"},
        ),
        db_path=db_path,
    )
    queued = store_tasks.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type="engine.node.orchestrator",
            inputs={"checkpoint_seq": 1},
            idempotency_key="orchestrator-priority",
        ),
        db_path=db_path,
    )
    task = store_tasks.claim_task("worker", run_id=run_id, db_path=db_path)
    assert task is not None and task.id == queued.id
    deferred = store_tasks.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type="engine.node.reflect",
            inputs={},
            idempotency_key="deferred-reflection",
            priority=10,
        ),
        db_path=db_path,
    )
    return task, deferred


def test_orchestrator_priority_reaches_durable_successor(
    isolated_db: str,
) -> None:
    run = runs.create_run("Priority science", "standard", "engine", {})
    task, deferred = _seed_orchestrator_task(run.id, isolated_db)

    engine_tasks_support._save_state_and_enqueue(
        engine_tasks_context.TaskCommit(task, 1, isolated_db),
        _priority_state(run.id, deferred.id),
        "generate",
    )

    successor = store_tasks.list_tasks(run.id, db_path=isolated_db)[-1]
    assert successor.task_type == "engine.node.generate"
    assert successor.priority == 97
    updated = store_tasks.get_task(deferred.id, db_path=isolated_db)
    assert updated is not None and updated.priority == 98


def test_node_commit_persists_live_metrics(isolated_db: str) -> None:
    run = runs.create_run("Live metrics science", "standard", "engine", {})
    task, deferred = _seed_orchestrator_task(run.id, isolated_db)
    state = {
        **_priority_state(run.id, deferred.id),
        "metrics": ExecutionMetrics(llm_calls=7, hypothesis_count=3),
    }

    assert retrieval.get_run_metrics(run.id, db_path=isolated_db) is None

    engine_tasks_support._save_state_and_enqueue(
        engine_tasks_context.TaskCommit(task, 1, isolated_db),
        state,
        "generate",
    )

    live = retrieval.get_run_metrics(run.id, db_path=isolated_db)
    assert live is not None
    assert live["llm_calls"] == 7
    assert live["hypothesis_count"] == 3


def test_node_commit_persists_supervisor_performance_assessment(
    isolated_db: str,
) -> None:
    run = runs.create_run("Assessed science", "standard", "engine", {})
    task, deferred = _seed_orchestrator_task(run.id, isolated_db)
    assessment = {
        "generation": {"yield": "high", "notes": "productive so far"},
        "evolution": {"yield": "low", "notes": "little improvement"},
    }
    state = {
        **_priority_state(run.id, deferred.id),
        "supervisor_guidance": {"performance_assessment": assessment},
    }

    engine_tasks_support._save_state_and_enqueue(
        engine_tasks_context.TaskCommit(task, 1, isolated_db),
        state,
        "generate",
    )

    live = retrieval.get_run_metrics(run.id, db_path=isolated_db)
    assert live is not None
    assert live["performance_assessment"] == assessment


@pytest.mark.asyncio
async def test_worker_consumes_independent_specialist_task_chain(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("Task-level science", "standard", "engine", {})
    engine_tasks.enqueue_bootstrap(run.id, db_path=isolated_db)
    generator = _Generator(_task_state(run.id))
    _patch_generator(monkeypatch, generator, restore=True, screen=True)

    successors = {"supervisor": "research_overview", "research_overview": None}
    finalized: list[str] = []

    async def execute(
        name: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        return state, successors[name]

    async def finalize(task: Any, **_: Any) -> dict[str, Any]:
        finalized.append(task.run_id)
        runs.update_run_status(task.run_id, RunStatus.COMPLETED)
        return {"run_id": task.run_id, "status": "completed"}

    _patch_task_node(monkeypatch, execute)
    monkeypatch.setitem(
        engine_tasks._ENGINE_TASK_DISPATCH,
        engine_tasks_support.FINALIZE_TASK,
        finalize,
    )
    await task_worker.run_run_until_idle(run.id, "worker", db_path=isolated_db)
    assert finalized == [run.id]

    tasks = store_tasks.list_tasks(run.id, db_path=isolated_db)
    # Bootstrap lookahead rows remain in history when fictional fixture
    # successors supersede and cancel them.
    assert [task.task_type for task in tasks] == [
        "engine.bootstrap",
        "engine.node.supervisor",
        "engine.node.generate",
        "engine.node.research_overview",
        "engine.finalize",
    ]
    by_type = {task.task_type: task.status for task in tasks}
    assert by_type.pop("engine.node.generate") == "cancelled"
    assert all(status == "completed" for status in by_type.values())
    assert _milestones(run.id, db_path=isolated_db) == [
        "Research plan ready — supervisor complete",
        "Research overview ready",
    ]


def _dispatch_seed_finalize_task(
    run_id: str, monkeypatch: pytest.MonkeyPatch, db_path: str
) -> Any:
    hypothesis = Hypothesis(
        text="Astrocyte lactate accelerates synaptic ATP recovery.",
        literature_grounding=(
            "Astrocyte lactate accelerates synaptic ATP recovery."
        ),
    )
    state = _task_state(run_id)
    state["hypotheses"] = [hypothesis]
    state["articles"] = [
        Article(
            title="Synaptic energetics",
            url="https://example.org/synaptic",
            abstract="Astrocyte lactate accelerates synaptic ATP recovery.",
        )
    ]
    _seed_checkpoint(run_id, state, db_path=db_path)
    queued = store_tasks.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=engine_tasks_support.FINALIZE_TASK,
            inputs={},
            idempotency_key="finalize",
        ),
        db_path=db_path,
    )
    task = store_tasks.claim_task(
        "finalize-dispatch-worker", run_id=run_id, db_path=db_path
    )
    assert task is not None and task.id == queued.id
    _patch_restore_generator(monkeypatch, _Generator(state))
    return task


def _assert_post_drain_counts(by_type: dict[str, Any]) -> None:
    assert set(by_type["safety.hypothesis"]) == {
        "screened",
        "blocked",
        "eligible",
        "activity",
    }
    assert by_type["safety.hypothesis"] == {
        "screened": 1,
        "blocked": 0,
        "eligible": 1,
        "activity": "safety",
    }
    assert set(by_type["citation.grounding"]) == {
        "assessed",
        "grounded",
        "blocked",
        "eligible",
        "activity",
    }
    assert by_type["citation.grounding"] == {
        "assessed": 1,
        "grounded": 1,
        "blocked": 0,
        "eligible": 1,
        "activity": "other",
    }
    citation_audit = dict(by_type["citation_audit"])
    assert citation_audit.pop("activity") == "other"
    assert citation_audit
    assert all(isinstance(v, int) for v in citation_audit.values())


@pytest.mark.asyncio
async def test_execute_finalize_emits_post_drain_stage_events(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("Task-level science", "standard", "engine", {})
    task = _dispatch_seed_finalize_task(run.id, monkeypatch, isolated_db)

    result = await engine_tasks.execute_finalize(task, db_path=isolated_db)

    assert result["status"] == RunStatus.COMPLETED.value
    assert reports.get_latest_report(run.id, db_path=isolated_db) is not None

    events = store_events.list_events(run.id, db_path=isolated_db)
    by_type = {e["type"]: e["payload"] for e in events}
    _assert_post_drain_counts(by_type)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("node_name", "extra_state", "expected_milestone"),
    [
        pytest.param(
            "reflection",
            {
                "hypotheses": [
                    Hypothesis(
                        text="Reviewed idea",
                        reviews=[
                            HypothesisReview(
                                review_summary="ok",
                                scores={},
                                safety_ethical_concerns="",
                                detailed_feedback={},
                                constructive_feedback="",
                                overall_score=70.0,
                            )
                        ],
                    )
                ]
            },
            "1 hypotheses reviewed",
            id="reflection",
        ),
        pytest.param(
            "evolve",
            {
                "hypotheses": [
                    Hypothesis(
                        text="Evolved idea", evolution_history=["refined"]
                    )
                ]
            },
            "1 hypotheses evolved (iteration 0)",
            id="evolve",
        ),
        pytest.param(
            "proximity",
            {
                "proximity_graph": {
                    "edges": [
                        {"source": "h1", "target": "h2", "cluster_id": "c1"}
                    ]
                }
            },
            "1 clusters identified",
            id="proximity",
        ),
        pytest.param(
            "meta_review",
            {"meta_review": {"summary": "Synthesis complete."}},
            "Meta-review complete",
            id="meta_review",
        ),
    ],
)
async def test_generic_node_completion_emits_matching_milestone(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    node_name: str,
    extra_state: dict[str, Any],
    expected_milestone: str,
) -> None:
    run = runs.create_run("Task-level science", "standard", "engine", {})
    checkpoint_seq = _seed_checkpoint(run.id, _task_state(run.id))
    node = store_tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}{node_name}",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"milestone-{node_name}",
        ),
        db_path=isolated_db,
    )
    leased = store_tasks.claim_task(
        "worker", run_id=run.id, db_path=isolated_db
    )
    assert leased is not None and leased.id == node.id

    async def execute(
        _name: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        return {**state, **extra_state}, None

    _patch_task_node(monkeypatch, execute)
    result = await engine_tasks.execute_node_task(leased, db_path=isolated_db)
    assert lifecycle.complete_task(
        leased.id, "worker", result, db_path=isolated_db
    )
    assert _milestones(run.id, db_path=isolated_db) == [expected_milestone]


# Run grounding off the task loop so heartbeat renewal can continue during
# synchronous provider waves.


def _lease_seed_finalize_task(
    run_id: str, monkeypatch: pytest.MonkeyPatch, db_path: str
) -> Any:
    hypothesis = Hypothesis(
        text="Astrocyte lactate accelerates synaptic ATP recovery.",
        literature_grounding=(
            "Astrocyte lactate accelerates synaptic ATP recovery."
        ),
    )
    state = _task_state(run_id)
    state["hypotheses"] = [hypothesis]
    state["articles"] = [
        Article(
            title="Synaptic energetics",
            url="https://example.org/synaptic",
            abstract="Astrocyte lactate accelerates synaptic ATP recovery.",
        )
    ]
    _seed_checkpoint(run_id, state, db_path=db_path)
    task = store_tasks.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=engine_tasks_support.FINALIZE_TASK,
            inputs={},
            idempotency_key="finalize",
        ),
        db_path=db_path,
    )
    _patch_restore_generator(monkeypatch, _Generator(state))
    return task


def _count_lease_renewals(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    box = {"renewals": 0}
    real_renew = lifecycle.renew_task_lease

    def _renew(*args: Any, **kwargs: Any) -> bool:
        box["renewals"] += 1
        return real_renew(*args, **kwargs)

    monkeypatch.setattr(lifecycle, "renew_task_lease", _renew)
    return box


@pytest.mark.asyncio
async def test_finalize_lease_survives_a_slow_grounding_wave(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A blocked loop can renew once belatedly; multiple renewals during
    # assessment prove a live heartbeat.
    run = runs.create_run("Task-level science", "standard", "engine", {})
    task = _lease_seed_finalize_task(run.id, monkeypatch, isolated_db)
    renewals = _count_lease_renewals(monkeypatch)

    real_assess = (
        drain_claim_grounding.assess_hypothesis_claims  # type: ignore[attr-defined]
    )
    sleep_seconds = 0.3

    def _slow_assess(*args: Any, **kwargs: Any) -> Any:
        time.sleep(sleep_seconds)
        return real_assess(*args, **kwargs)

    monkeypatch.setattr(
        drain_claim_grounding, "assess_hypothesis_claims", _slow_assess
    )

    completed = await task_worker.run_once(
        "worker-a", db_path=isolated_db, lease_seconds=0.06
    )

    assert completed
    # One catch-up renewal occurs even on a blocked loop; multiple renewals
    # distinguish continuous lease health.
    assert renewals["renewals"] >= 3, (
        "the lease heartbeat barely renewed during the grounding wave -- "
        "the wave is blocking the task's event loop again"
    )
    persisted_run = runs.get_run(run.id, db_path=isolated_db)
    assert persisted_run is not None
    assert persisted_run.status == "completed"
    saved = store_tasks.get_task(task.id, db_path=isolated_db)
    assert saved is not None
    assert saved.status == "completed"


def _node_task(run_id: str) -> ScientificTask:
    return ScientificTask(
        id="task-1",
        run_id=run_id,
        task_type="engine.node.generate",
        status="leased",
        priority=90,
        inputs={},
        dependencies=(),
        provenance={},
        idempotency_key="engine.node.generate:0",
        budget={},
        attempt=1,
        max_attempts=3,
        lease_owner="test",
        lease_expires_at=None,
        result=None,
        error=None,
        created_at=0.0,
        updated_at=0.0,
        started_at=None,
        completed_at=None,
    )


async def test_execute_engine_task_scopes_the_llm_call_ceiling(
    monkeypatch: Any,
) -> None:
    run = runs.create_run(
        "Budget scoping",
        "express",
        "engine",
        resolved_run_config({"tier": "express"}),
    )
    try:
        seen: dict[str, int] = {}

        async def fake_node_task(
            task: Any, *, db_path: str | None = None
        ) -> dict[str, Any]:
            record_provider_request()
            record_provider_request()
            seen["count_during"] = current_run_call_count(run.id)
            return {"status": "completed"}

        monkeypatch.setattr(engine_tasks, "execute_node_task", fake_node_task)
        await engine_tasks.execute_engine_task(_node_task(run.id))

        assert seen["count_during"] == 2
        seen2: dict[str, int] = {}

        async def fake_node_task_2(
            task: Any, *, db_path: str | None = None
        ) -> dict[str, Any]:
            record_provider_request()
            seen2["count_during"] = current_run_call_count(run.id)
            return {"status": "completed"}

        monkeypatch.setattr(engine_tasks, "execute_node_task", fake_node_task_2)
        await engine_tasks.execute_engine_task(_node_task(run.id))
        assert seen2["count_during"] == 3

        record_provider_request()
        assert current_run_call_count(run.id) == 3
    finally:
        release_run_call_budget(run.id)


async def test_execute_engine_task_enforces_the_ceiling(
    monkeypatch: Any,
) -> None:
    tier_ceiling = RUN_TIER_DEFAULTS["express"]["max_llm_calls"]
    run = runs.create_run(
        "Budget enforcement",
        "express",
        "engine",
        resolved_run_config({"tier": "express"}),
    )
    try:
        from co_scientist.exceptions import LLMCallBudgetExceededError

        async def spend_to_ceiling(
            task: Any, *, db_path: str | None = None
        ) -> dict[str, Any]:
            for _ in range(tier_ceiling):
                record_provider_request()
            return {"status": "completed"}

        monkeypatch.setattr(engine_tasks, "execute_node_task", spend_to_ceiling)
        await engine_tasks.execute_engine_task(_node_task(run.id))
        assert current_run_call_count(run.id) == tier_ceiling

        async def one_more(
            task: Any, *, db_path: str | None = None
        ) -> dict[str, Any]:
            record_provider_request()
            return {"status": "completed"}

        monkeypatch.setattr(engine_tasks, "execute_node_task", one_more)
        try:
            await engine_tasks.execute_engine_task(_node_task(run.id))
            raised = False
        except LLMCallBudgetExceededError:
            raised = True
        assert raised, "the request past the ceiling must be refused"
    finally:
        release_run_call_budget(run.id)


# An optional terminal overview must degrade after retries and still enqueue
# report finalization.


_UPSTREAM = APIError(
    status_code=500,
    message="OpenrouterException - Upstream error from Nvidia: overloaded",
    llm_provider="openrouter",
    model="minimax/minimax-m3:free",
)


def _grounded_state(run_id: str) -> dict[str, Any]:
    claim = "Astrocyte lactate accelerates synaptic ATP recovery."
    hypothesis = Hypothesis(text=claim, literature_grounding=claim)
    hypothesis.review_disposition = "viable"
    state = _task_state(run_id)
    state["hypotheses"] = [hypothesis]
    state["articles"] = [
        Article(
            title="Synaptic energetics",
            url="https://example.org/synaptic",
            abstract=claim,
        )
    ]
    return state


def _seed_overview_task(
    run_id: str, monkeypatch: pytest.MonkeyPatch, db_path: str
) -> None:
    state = _grounded_state(run_id)
    checkpoint_seq = _seed_checkpoint(run_id, state, db_path=db_path)
    store_tasks.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type="engine.node.research_overview",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key="overview",
        ),
        db_path=db_path,
    )
    _patch_generator(monkeypatch, _Generator(state), restore=True, screen=True)

    async def _unreachable(*_: Any, **__: Any) -> dict[str, Any]:
        raise _UPSTREAM

    monkeypatch.setattr(ro, "call_llm_json", _unreachable)


@pytest.mark.asyncio
async def test_degraded_overview_still_reaches_a_written_report(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("Task-level science", "standard", "engine", {})
    _seed_overview_task(run.id, monkeypatch, isolated_db)

    await task_worker.run_run_until_idle(run.id, "worker", db_path=isolated_db)

    by_type = {
        task.task_type: task.status
        for task in store_tasks.list_tasks(run.id, db_path=isolated_db)
    }
    assert by_type["engine.node.research_overview"] == "completed"
    assert by_type[engine_tasks_support.FINALIZE_TASK] == "completed"

    report = reports.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["markdown_text"]

    run_row = runs.get_run(run.id, db_path=isolated_db)
    assert run_row is not None
    assert run_row.status != RunStatus.FAILED.value


@pytest.mark.asyncio
async def test_the_report_names_the_overview_as_a_degraded_section(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("Task-level science", "standard", "engine", {})
    _seed_overview_task(run.id, monkeypatch, isolated_db)

    await task_worker.run_run_until_idle(run.id, "worker", db_path=isolated_db)

    report = reports.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert "research_overview" in report["payload"]["degraded_sections"]


@pytest.mark.asyncio
async def test_the_overview_degrades_only_once_its_retries_are_spent(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Degrade optional terminal sections only after exhausting durable retries
    # so recoverable failures can recover.
    run = runs.create_run("Task-level science", "standard", "engine", {})
    _seed_overview_task(run.id, monkeypatch, isolated_db)

    await task_worker.run_run_until_idle(run.id, "worker", db_path=isolated_db)

    overview = next(
        task
        for task in store_tasks.list_tasks(run.id, db_path=isolated_db)
        if task.task_type == "engine.node.research_overview"
    )
    assert overview.status == "completed"
    assert overview.attempt == overview.max_attempts == 3
    assert len(overview.attempts) == 2


def _restored_state(attempt: int, run_id: str, db_path: str) -> dict[str, Any]:
    from co_scientist.checkpoint import serialize_workflow_state

    state = _task_state(run_id)
    task = store_tasks.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type="engine.node.research_overview",
            inputs={},
            idempotency_key=f"overlay-{attempt}",
        ),
        db_path=db_path,
    )
    checkpoint = {
        "state": {
            "provider": "engine",
            **serialize_workflow_state(state, last_event_seq=0),
        }
    }
    return engine_tasks_restore._restore_node_task_state(
        dataclasses.replace(task, attempt=attempt),
        checkpoint,
        _Generator(state),
        {},
        db_path,
    )


def test_the_restored_state_names_the_task_s_last_attempt(
    isolated_db: str,
) -> None:
    # The terminal-attempt flag must use the same retry-left formula as the
    # worker.
    run = runs.create_run("Task-level science", "standard", "engine", {})

    first = _restored_state(1, run.id, isolated_db)
    last = _restored_state(3, run.id, isolated_db)

    assert first["durable_retries_remain"] is True
    assert last["durable_retries_remain"] is False


# Durable commits must follow the shared route table so engine reroutes also
# reach production.


_ROUTED_NODES = (
    "generate",
    "review",
    "comprehensive_reflection",
    "deep_verification",
    "ranking",
)

_DIVERTED_TO = "proximity"


async def _schedule_successor(
    node: str, commit: TaskCommit, state: dict[str, Any]
) -> str:
    if node == "ranking":
        result = await engine_tasks_ranking._commit_ranking_finalize(
            commit, state, {}
        )
        return str(result["successor_task_id"])
    advance = engine_tasks_fanout_aggregates._checkpoint_and_advance
    _, successor_id = await advance(commit, state, node)
    return str(successor_id)


async def _commit_node(
    run_id: str, node: str, db_path: str, *, mcp_available: bool = False
) -> str:
    state = _task_state(run_id)
    state["mcp_available"] = mcp_available
    checkpoint_seq = _seed_checkpoint(run_id, state, db_path=db_path)
    queued = store_tasks.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}{node}",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"{node}:commit",
        ),
        db_path=db_path,
    )
    task = store_tasks.claim_task(
        f"routing-{node}", run_id=run_id, db_path=db_path
    )
    assert task is not None and task.id == queued.id
    successor_id = await _schedule_successor(
        node, TaskCommit(task, checkpoint_seq, db_path), state
    )
    successor = store_tasks.get_task(successor_id, db_path=db_path)
    assert successor is not None
    return successor.task_type


@pytest.mark.asyncio
@pytest.mark.parametrize("node", _ROUTED_NODES)
async def test_durable_successor_matches_the_engine_route_table(
    isolated_db: str, node: str
) -> None:
    # Read successor expectations from the route table so topology changes
    # remain authoritative.
    from co_scientist.task_runtime import next_task_type

    run = runs.create_run("Durable routing", "standard", "engine", {})
    scheduled = await _commit_node(run.id, node, isolated_db)
    expected = next_task_type(node, {"mcp_available": False})
    assert scheduled == f"{engine_tasks.NODE_TASK_PREFIX}{expected}"


@pytest.mark.asyncio
@pytest.mark.parametrize("node", _ROUTED_NODES)
async def test_durable_successor_follows_a_rerouted_graph(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, node: str
) -> None:
    from co_scientist import workflow_topology

    monkeypatch.setitem(workflow_topology.WORKFLOW_ROUTES, node, _DIVERTED_TO)
    run = runs.create_run("Durable routing", "standard", "engine", {})
    scheduled = await _commit_node(run.id, node, isolated_db)
    assert scheduled == f"{engine_tasks.NODE_TASK_PREFIX}{_DIVERTED_TO}"


_INVERTED_GENERATE_ROUTE = LiteratureGated(on="review", off="reflection")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mcp_available", "expected"),
    [(True, "review"), (False, "reflection")],
)
async def test_generate_mcp_branch_is_not_reimplemented(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    mcp_available: bool,
    expected: str,
) -> None:
    # Invert the route table branch to expose a copied MCP conditional in the
    # durable executor.
    from co_scientist import workflow_topology

    monkeypatch.setitem(
        workflow_topology.WORKFLOW_ROUTES, "generate", _INVERTED_GENERATE_ROUTE
    )
    run = runs.create_run("Durable routing", "standard", "engine", {})
    scheduled = await _commit_node(
        run.id, "generate", isolated_db, mcp_available=mcp_available
    )
    assert scheduled == f"{engine_tasks.NODE_TASK_PREFIX}{expected}"


def test_production_adapter_is_the_default() -> None:
    assert isinstance(
        engine_tasks_runtime.active(), ProductionEngineTaskRuntime
    )


@pytest.mark.asyncio
async def test_production_adapter_reaches_the_real_collaborators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def stub(name: str, result: Any) -> Any:
        def call(*_: Any, **__: Any) -> Any:
            calls.append(name)
            return result

        async def acall(*_: Any, **__: Any) -> Any:
            return call()

        return acall if name in {"screen", "drain"} else call

    monkeypatch.setattr(
        engine_tasks_support, "_generator_and_opts", stub("new", ("g", {}))
    )
    monkeypatch.setattr(
        engine_tasks_support, "_generator_for_restore", stub("restore", "g")
    )
    monkeypatch.setattr(safety, "screen_with_escalation", stub("screen", 1))
    monkeypatch.setattr(
        engine_tasks_node, "_drain_and_persist_final_state", stub("drain", 2)
    )
    adapter = ProductionEngineTaskRuntime()
    anything: Any = object()

    assert adapter.generator_and_opts(anything, None) == ("g", {})
    assert adapter.generator_for_restore(anything, None) == "g"
    screened: Any = await adapter.screen("run", anything, provider="p")
    drained: Any = await adapter.drain_final_state(anything, {}, None)

    assert (screened, drained) == (1, 2)

    assert calls == ["new", "restore", "screen", "drain"]


@pytest.mark.asyncio
async def test_dispatcher_binds_the_adapter_it_resolved_once(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    started_with = _install_runtime(monkeypatch)
    replacement = FakeEngineTaskRuntime()
    seen: list[Any] = []

    async def handler(task: Any, **_: Any) -> dict[str, Any]:
        seen.append(engine_tasks_runtime.active())
        monkeypatch.setattr(engine_tasks_runtime, "_installed", replacement)
        seen.append(engine_tasks_runtime.active())
        return {}

    monkeypatch.setitem(
        engine_tasks._ENGINE_TASK_DISPATCH,
        engine_tasks_support.FINALIZE_TASK,
        handler,
    )
    run = runs.create_run("Task-level science", "standard", "engine", {})
    task = store_tasks.enqueue_task(
        NewTask(
            run_id=run.id,
            task_type=engine_tasks_support.FINALIZE_TASK,
            inputs={},
            idempotency_key="finalize",
        ),
        db_path=isolated_db,
    )

    await engine_tasks.execute_engine_task(task, db_path=isolated_db)

    assert seen == [started_with, started_with]
    installed: Any = engine_tasks_runtime.active()
    assert installed is replacement


async def _deterministic_final_screen(
    _run_id: str, subject: ScreenSubject, *_: Any, **__: Any
) -> Any:
    return subject.deterministic


def _seed_halted_finalize(
    run_id: str, monkeypatch: pytest.MonkeyPatch, db_path: str, *, halted: bool
) -> Any:
    state = _task_state(run_id)
    state["hypotheses"] = [
        Hypothesis(
            text="Astrocyte lactate accelerates synaptic ATP recovery.",
            literature_grounding=(
                "Astrocyte lactate accelerates synaptic ATP recovery."
            ),
        )
    ]
    if halted:
        state["safety_blocked"] = True
        state["safety_decisions"] = [
            {
                "stage": "research_direction",
                "outcome": "prohibited",
                "reason": "Content matches a prohibited policy rule.",
                "matches": ["engineer smallpox for greater transmiss"],
                "policy_version": "coscientist-safety-v5",
            }
        ]
    _seed_checkpoint(run_id, state, db_path=db_path)
    queued = store_tasks.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=engine_tasks_support.FINALIZE_TASK,
            inputs={},
            idempotency_key="finalize",
        ),
        db_path=db_path,
    )
    task = store_tasks.claim_task(
        "finalize-safety-worker", run_id=run_id, db_path=db_path
    )
    assert task is not None and task.id == queued.id
    _patch_restore_generator(monkeypatch, _Generator(state))
    return task


@pytest.mark.asyncio
async def test_a_halted_run_blocks_instead_of_publishing(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("Task-level science", "standard", "engine", {})
    task = _seed_halted_finalize(run.id, monkeypatch, isolated_db, halted=True)

    result = await engine_tasks.execute_finalize(task, db_path=isolated_db)

    assert result["status"] == RunStatus.BLOCKED.value
    assert reports.get_latest_report(run.id, db_path=isolated_db) is None

    settled = runs.get_run(run.id, db_path=isolated_db)
    assert settled is not None
    assert settled.status == RunStatus.BLOCKED.value
    assert settled.error

    decisions = records.list_safety_decisions(run.id, db_path=isolated_db)
    monitor = [d for d in decisions if d["stage"] == "research_direction"]
    assert len(monitor) == 1
    assert monitor[0]["decision"] == "block"
    assert monitor[0]["matches"]

    events = store_events.list_events(run.id, db_path=isolated_db)
    types = [event["type"] for event in events]
    assert "safety.research_direction" in types
    assert "report" not in types


@pytest.mark.asyncio
async def test_an_unhalted_run_still_publishes(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("Task-level science", "standard", "engine", {})
    task = _seed_halted_finalize(run.id, monkeypatch, isolated_db, halted=False)
    _install_runtime(monkeypatch).screen = _deterministic_final_screen

    result = await engine_tasks.execute_finalize(task, db_path=isolated_db)

    assert result["status"] == RunStatus.COMPLETED.value
    assert reports.get_latest_report(run.id, db_path=isolated_db) is not None


_STEER = "Prioritise kinase inhibitors over metabolic routes"


def _seed_steered_node_task(
    run_id: str,
    monkeypatch: pytest.MonkeyPatch,
    db_path: str,
    *,
    node: str = "proximity",
) -> ScientificTask:
    # Proximity lacks fan-out and exercises plain commit; orchestrator alone can
    # acknowledge steering.
    state = _task_state(run_id)
    checkpoint_seq = _seed_checkpoint(run_id, state, db_path=db_path)
    messages.append_message(
        NewMessage(
            run_id=run_id, sender="user", content=_STEER, kind="steering"
        ),
        db_path=db_path,
    )
    store_tasks.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}{node}",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"engine.node.{node}:{checkpoint_seq}",
        ),
        db_path=db_path,
    )
    monkeypatch.setattr(
        engine_tasks_support,
        "build_generator",
        lambda *_, **__: _Generator(state),
    )
    leased = store_tasks.claim_task("worker", run_id=run_id, db_path=db_path)
    assert leased is not None
    return leased


def _record_preferences_and_commit(seen: list[str], *, priority: bool) -> Any:
    # Orchestrator successor planning unconditionally reads next_task_priority.

    async def _run_node(
        _node: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        seen.append(str(state.get("preferences") or ""))
        if priority:
            state["next_task_priority"] = 90
        return state, "meta_review"

    return _run_node


@pytest.mark.asyncio
async def test_steering_survives_a_crash_before_the_checkpoint_commits(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("Steering durability", "standard", "engine", {})
    leased = _seed_steered_node_task(run.id, monkeypatch, isolated_db)

    async def _crash(*_: Any, **__: Any) -> Any:
        raise RuntimeError("worker died mid-node")

    _patch_task_node(monkeypatch, _crash)

    with pytest.raises(RuntimeError, match="worker died mid-node"):
        await engine_tasks.execute_node_task(leased, db_path=isolated_db)

    pending = messages.get_pending_steering(run.id, db_path=isolated_db)
    assert [message.content for message in pending] == [_STEER]


@pytest.mark.asyncio
async def test_a_non_orchestrator_commit_never_acknowledges_steering(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only the orchestrator schedules from pending_steering; earlier
    # acknowledgment loses the decision input.
    run = runs.create_run("Steering durability", "standard", "engine", {})
    leased = _seed_steered_node_task(run.id, monkeypatch, isolated_db)
    seen: list[str] = []
    _patch_task_node(
        monkeypatch, _record_preferences_and_commit(seen, priority=False)
    )

    await engine_tasks.execute_node_task(leased, db_path=isolated_db)

    assert _STEER in seen[0]
    pending = messages.get_pending_steering(run.id, db_path=isolated_db)
    assert [message.content for message in pending] == [_STEER]


@pytest.mark.asyncio
async def test_committed_orchestrator_acknowledges_its_steering_exactly_once(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("Steering durability", "standard", "engine", {})
    leased = _seed_steered_node_task(
        run.id, monkeypatch, isolated_db, node="orchestrator"
    )
    seen: list[str] = []
    _patch_task_node(
        monkeypatch, _record_preferences_and_commit(seen, priority=True)
    )

    await engine_tasks.execute_node_task(leased, db_path=isolated_db)

    assert _STEER in seen[0]
    assert messages.get_pending_steering(run.id, db_path=isolated_db) == []


@pytest.mark.asyncio
async def test_steering_reaches_the_orchestrators_retry_after_a_crash(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("Steering durability", "standard", "engine", {})
    leased = _seed_steered_node_task(
        run.id, monkeypatch, isolated_db, node="orchestrator"
    )
    seen: list[str] = []

    async def _crash_then_commit(
        _node: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        seen.append(str(state.get("preferences") or ""))
        if len(seen) == 1:
            raise RuntimeError("worker died mid-node")
        state["next_task_priority"] = 90
        return state, "meta_review"

    _patch_task_node(monkeypatch, _crash_then_commit)

    with pytest.raises(RuntimeError):
        await engine_tasks.execute_node_task(leased, db_path=isolated_db)
    await engine_tasks.execute_node_task(leased, db_path=isolated_db)

    assert [_STEER in text for text in seen] == [True, True]
    assert messages.get_pending_steering(run.id, db_path=isolated_db) == []


@pytest.mark.asyncio
async def test_steering_text_survives_to_the_node_it_was_meant_for(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Applied steering must remain folded into preferences after acknowledgment
    # or the successor loses guidance.
    run = runs.create_run("Steering survives", "standard", "engine", {})
    orchestrator = _seed_steered_node_task(
        run.id, monkeypatch, isolated_db, node="orchestrator"
    )

    async def _orchestrator_run(
        name: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        assert name == "orchestrator"
        out = dict(state)
        out["next_task"] = "reflection"
        out["next_task_priority"] = 90
        return out, "reflection"

    _patch_task_node(monkeypatch, _orchestrator_run)
    committed = await engine_tasks.execute_node_task(
        orchestrator, db_path=isolated_db
    )
    assert lifecycle.complete_task(
        orchestrator.id, "worker", committed, db_path=isolated_db
    )

    reflection = store_tasks.claim_task(
        "worker", run_id=run.id, db_path=isolated_db
    )
    assert reflection is not None
    assert reflection.task_type == "engine.node.reflection"
    seen: list[str] = []
    _patch_task_node(
        monkeypatch, _record_preferences_and_commit(seen, priority=False)
    )

    await engine_tasks.execute_node_task(reflection, db_path=isolated_db)

    assert seen and "kinase" in seen[0].lower()


async def _fake_review_with_telemetry(**kwargs: Any) -> HypothesisReview:
    record_call(
        "fixture-model",
        ModelCallStats(calls=1, prompt_tokens=20, completion_tokens=10),
    )
    return HypothesisReview(
        review_summary=f"reviewed {kwargs['hypothesis_text']}",
        scores={"scientific_soundness": 8, "novelty": 8},
        safety_ethical_concerns="none",
        detailed_feedback={},
        constructive_feedback="continue",
        overall_score=8.0,
    )


async def _advance_review_node(
    run_id: str, monkeypatch: pytest.MonkeyPatch, db_path: str
) -> None:
    state = _task_state(run_id)
    state["hypotheses"] = [Hypothesis(text="alpha"), Hypothesis(text="beta")]
    checkpoint_seq = _seed_checkpoint(run_id, state)
    node = store_tasks.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}review",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key="review-node",
        ),
        db_path=db_path,
    )
    _patch_generator(monkeypatch, _Generator(state), restore=True)
    leased = store_tasks.claim_task("node", run_id=run_id, db_path=db_path)
    assert leased is not None and leased.id == node.id
    result = await engine_tasks.execute_node_task(leased, db_path=db_path)
    assert lifecycle.complete_task(leased.id, "node", result, db_path=db_path)


@pytest.mark.asyncio
async def test_review_fanout_folds_item_telemetry_into_committed_metrics(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("Task-level science", "standard", "engine", {})
    await _advance_review_node(run.id, monkeypatch, isolated_db)

    import co_scientist.agents.reflection.review as review_module

    monkeypatch.setattr(
        review_module, "review_single_hypothesis", _fake_review_with_telemetry
    )
    first = store_tasks.claim_task(
        "child-a", run_id=run.id, db_path=isolated_db
    )
    second = store_tasks.claim_task(
        "child-b", run_id=run.id, db_path=isolated_db
    )
    assert first is not None and second is not None
    first_result = await engine_tasks_fanout_items.execute_review_item(
        first, db_path=isolated_db
    )
    second_result = await engine_tasks_fanout_items.execute_review_item(
        second, db_path=isolated_db
    )
    assert first_result["model_usage"] == {
        "review::fixture-model": ModelCallStats(
            calls=1, prompt_tokens=20, completion_tokens=10
        ).as_dict()
    }
    assert lifecycle.complete_task(
        first.id, "child-a", first_result, db_path=isolated_db
    )
    assert lifecycle.complete_task(
        second.id, "child-b", second_result, db_path=isolated_db
    )

    aggregate = store_tasks.claim_task(
        "aggregate", run_id=run.id, db_path=isolated_db
    )
    assert aggregate is not None
    aggregate_result = (
        await engine_tasks_fanout_aggregates.execute_review_aggregate(
            aggregate, db_path=isolated_db
        )
    )
    assert lifecycle.complete_task(
        aggregate.id, "aggregate", aggregate_result, db_path=isolated_db
    )

    from co_scientist.checkpoint import restore_workflow_state

    checkpoint = checkpoints.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    restored = restore_workflow_state(checkpoint["state"])
    usage = restored["metrics"].model_usage["review::fixture-model"]
    assert usage["calls"] == 2
    assert usage["prompt_tokens"] == 40
    assert usage["completion_tokens"] == 20


async def _fake_judge_with_telemetry(
    *_: Any, **kwargs: Any
) -> tuple[str, dict[str, Any]]:
    record_call("fixture-model", ModelCallStats(calls=1, prompt_tokens=5))
    return "a", {
        "decision_summary": "A is stronger",
        "confidence_level": "high",
        "debate_turns": int(kwargs["debate_turns"]),
        "debate_transcript": [],
        "judge_model": "fixture-model",
    }


async def _drain_and_finalize_ranking(run_id: str, db_path: str) -> int:
    matches = 0
    while True:
        task = store_tasks.claim_task(
            f"match-{matches}", run_id=run_id, db_path=db_path
        )
        assert task is not None
        if task.task_type != engine_tasks_support.RANKING_MATCH_TASK:
            break
        result = await engine_tasks_ranking.execute_ranking_match(
            task, db_path=db_path
        )
        assert lifecycle.complete_task(
            task.id, f"match-{matches}", result, db_path=db_path
        )
        matches += 1
    assert task.task_type == engine_tasks_support.RANKING_FINALIZE_TASK
    result = await engine_tasks_ranking.execute_ranking_finalize(
        task, db_path=db_path
    )
    assert lifecycle.complete_task(
        task.id, f"match-{matches}", result, db_path=db_path
    )
    return matches


@pytest.mark.asyncio
async def test_ranking_matches_fold_telemetry_into_finalized_metrics(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Sequential match usage rides successor inputs until the final checkpoint;
    # intermediate commits omit metrics.
    run = runs.create_run("Task-level science", "standard", "engine", {})
    _seed_ranking_node(
        run.id,
        monkeypatch,
        _RankingSeed(
            hypothesis_count=4,
            tournament_pairs=8,
            idempotency_key="telemetry-ranking-node",
        ),
        isolated_db,
    )
    import co_scientist.agents.ranking.operations as ranking_module

    monkeypatch.setattr(
        ranking_module, "judge_matchup", _fake_judge_with_telemetry
    )

    await _run_ranking_node(run.id, isolated_db)
    await _drain_and_finalize_ranking(run.id, isolated_db)

    from co_scientist.checkpoint import restore_workflow_state

    checkpoint = checkpoints.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    restored = restore_workflow_state(checkpoint["state"])
    played = len(restored["tournament_matchups"])
    assert played > 1, "fixture must judge more than one matchup"
    usage = restored["metrics"].model_usage["ranking::fixture-model"]
    assert usage["calls"] == played
    assert usage["prompt_tokens"] == played * 5


@pytest.mark.asyncio
async def test_baseline_fake_judge_leaves_no_telemetry(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = runs.create_run("Task-level science", "standard", "engine", {})
    _seed_ranking_node(
        run.id,
        monkeypatch,
        _RankingSeed(
            hypothesis_count=4,
            tournament_pairs=8,
            idempotency_key="baseline-ranking-node",
        ),
        isolated_db,
    )
    _install_plain_fake_judge(monkeypatch)

    await _run_ranking_node(run.id, isolated_db)
    await _drain_and_finalize_ranking(run.id, isolated_db)

    from co_scientist.checkpoint import restore_workflow_state

    checkpoint = checkpoints.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    restored = restore_workflow_state(checkpoint["state"])
    assert not any(
        key.startswith("ranking::") for key in restored["metrics"].model_usage
    )
