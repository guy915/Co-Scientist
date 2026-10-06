from __future__ import annotations

import time
from typing import Any

import pytest
from co_scientist.agents.meta_review import research_overview as ro
from co_scientist.exceptions import LLMCallBudgetExceededError
from co_scientist.llm import (
    current_run_call_count,
    release_run_call_budget,
)
from co_scientist.llm.admission.call_budget import record_provider_request
from co_scientist.models import (
    Article,
    ExecutionMetrics,
    Hypothesis,
    HypothesisReview,
)
from litellm.exceptions import APIError

import app.engine_adapter.drain.final_state as drain_claim_grounding
from app import engine_tasks, task_worker
from app.engine_tasks import fanout_aggregates as engine_tasks_fanout_aggregates
from app.engine_tasks import ranking as engine_tasks_ranking
from app.engine_tasks import support as engine_tasks_support
from app.engine_tasks.support import TaskCommit
from app.run_modes import RUN_TIER_DEFAULTS, resolved_run_config
from app.store import events as store_events
from app.store import messages, records, reports, runs
from app.store import retrieval_calls as retrieval
from app.store import tasks as store_tasks
from app.store import tasks_lifecycle as lifecycle
from app.store.messages import NewMessage
from app.store.models import RunStatus, ScientificTask
from tests._engine_tasks_helpers import (
    _Generator,
    _milestones,
    _patch_generator,
    _patch_restore_generator,
    _patch_task_node,
    _seed_checkpoint,
    _task_state,
)
from tests._store_helpers import enqueue_task, seed_checkpoint, seed_run
from tests._store_helpers import leased_node_task as _node_task


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
    seed_checkpoint(
        run_id, {"provider": "engine"}, stage="seed", db_path=db_path
    )
    queued = enqueue_task(
        run_id,
        "engine.node.orchestrator",
        "orchestrator-priority",
        inputs={"checkpoint_seq": 1},
        db_path=db_path,
    )
    task = store_tasks.claim_task("worker", run_id=run_id, db_path=db_path)
    assert task is not None and task.id == queued.id
    deferred = enqueue_task(
        run_id,
        "engine.node.reflect",
        "deferred-reflection",
        priority=10,
        db_path=db_path,
    )
    return task, deferred


def test_node_commit_persists_priority_metrics_and_assessment(
    isolated_db: str,
) -> None:
    run = seed_run("Priority science")
    task, deferred = _seed_orchestrator_task(run.id, isolated_db)
    assessment = {"generation": {"yield": "high", "notes": "productive"}}
    state = {
        **_priority_state(run.id, deferred.id),
        "metrics": ExecutionMetrics(llm_calls=7, hypothesis_count=3),
        "supervisor_guidance": {"performance_assessment": assessment},
    }
    assert retrieval.get_run_metrics(run.id, db_path=isolated_db) is None

    engine_tasks_support._save_state_and_enqueue(
        TaskCommit(task, 1, isolated_db), state, "generate"
    )

    successor = store_tasks.list_tasks(run.id, db_path=isolated_db)[-1]
    assert successor.task_type == "engine.node.generate"
    assert successor.priority == 97
    updated = store_tasks.get_task(deferred.id, db_path=isolated_db)
    assert updated is not None and updated.priority == 98
    live = retrieval.get_run_metrics(run.id, db_path=isolated_db)
    assert live is not None
    assert live["llm_calls"] == 7
    assert live["hypothesis_count"] == 3
    assert live["performance_assessment"] == assessment


@pytest.mark.asyncio
async def test_worker_consumes_independent_specialist_task_chain(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = seed_run("Task-level science")
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


def _seed_finalize_task(
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
    task = enqueue_task(
        run_id, engine_tasks_support.FINALIZE_TASK, "finalize", db_path=db_path
    )
    _patch_restore_generator(monkeypatch, _Generator(state))
    return task


def _assert_post_drain_counts(by_type: dict[str, Any]) -> None:
    assert by_type["safety.hypothesis"] == {
        "screened": 1,
        "blocked": 0,
        "eligible": 1,
        "activity": "safety",
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
    run = seed_run("Task-level science")
    queued = _seed_finalize_task(run.id, monkeypatch, isolated_db)
    task = store_tasks.claim_task(
        "finalize-worker", run_id=run.id, db_path=isolated_db
    )
    assert task is not None and task.id == queued.id

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
    run = seed_run("Task-level science")
    checkpoint_seq = _seed_checkpoint(run.id, _task_state(run.id))
    node = enqueue_task(
        run.id,
        f"{engine_tasks.NODE_TASK_PREFIX}{node_name}",
        f"milestone-{node_name}",
        inputs={"checkpoint_seq": checkpoint_seq},
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
    run = seed_run("Task-level science")
    task = _seed_finalize_task(run.id, monkeypatch, isolated_db)
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


async def test_execute_engine_task_enforces_the_ceiling_across_tasks(
    monkeypatch: Any,
) -> None:
    ceiling = RUN_TIER_DEFAULTS["express"]["max_llm_calls"]
    run = seed_run(
        "Budget enforcement",
        profile="express",
        config=resolved_run_config({"tier": "express"}),
    )

    def spend(count: int) -> Any:
        async def node_task(
            task: Any, *, db_path: str | None = None
        ) -> dict[str, Any]:
            for _ in range(count):
                record_provider_request()
            return {"status": "completed"}

        return node_task

    try:
        monkeypatch.setattr(engine_tasks, "execute_node_task", spend(ceiling))
        await engine_tasks.execute_engine_task(_node_task(run.id))
        assert current_run_call_count(run.id) == ceiling

        monkeypatch.setattr(engine_tasks, "execute_node_task", spend(1))
        with pytest.raises(LLMCallBudgetExceededError):
            await engine_tasks.execute_engine_task(_node_task(run.id))
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
    enqueue_task(
        run_id,
        "engine.node.research_overview",
        "overview",
        inputs={"checkpoint_seq": checkpoint_seq},
        db_path=db_path,
    )
    _patch_generator(monkeypatch, _Generator(state), restore=True, screen=True)

    async def _unreachable(*_: Any, **__: Any) -> dict[str, Any]:
        raise _UPSTREAM

    monkeypatch.setattr(ro, "call_llm_json", _unreachable)


@pytest.mark.asyncio
async def test_overview_degrades_only_after_its_retries_and_still_reports(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Degrade optional terminal sections only after exhausting durable retries
    # so recoverable failures can recover.
    run = seed_run("Task-level science")
    _seed_overview_task(run.id, monkeypatch, isolated_db)

    await task_worker.run_run_until_idle(run.id, "worker", db_path=isolated_db)

    by_type = {
        task.task_type: task
        for task in store_tasks.list_tasks(run.id, db_path=isolated_db)
    }
    overview = by_type["engine.node.research_overview"]
    assert overview.status == "completed"
    assert overview.attempt == overview.max_attempts == 3
    assert len(overview.attempts) == 2
    assert by_type[engine_tasks_support.FINALIZE_TASK].status == "completed"

    report = reports.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["markdown_text"]
    assert "research_overview" in report["payload"]["degraded_sections"]
    run_row = runs.get_run(run.id, db_path=isolated_db)
    assert run_row is not None
    assert run_row.status != RunStatus.FAILED.value


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
    queued = enqueue_task(
        run_id,
        f"{engine_tasks.NODE_TASK_PREFIX}{node}",
        f"{node}:commit",
        inputs={"checkpoint_seq": checkpoint_seq},
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
async def test_durable_successor_follows_a_rerouted_graph(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, node: str
) -> None:
    from co_scientist import workflow_topology

    monkeypatch.setitem(workflow_topology.WORKFLOW_ROUTES, node, _DIVERTED_TO)
    run = seed_run("Durable routing")
    scheduled = await _commit_node(run.id, node, isolated_db)
    assert scheduled == f"{engine_tasks.NODE_TASK_PREFIX}{_DIVERTED_TO}"


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
    queued = enqueue_task(
        run_id, engine_tasks_support.FINALIZE_TASK, "finalize", db_path=db_path
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
    run = seed_run("Task-level science")
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
    enqueue_task(
        run_id,
        f"{engine_tasks.NODE_TASK_PREFIX}{node}",
        f"engine.node.{node}:{checkpoint_seq}",
        inputs={"checkpoint_seq": checkpoint_seq},
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
    run = seed_run("Steering durability")
    leased = _seed_steered_node_task(run.id, monkeypatch, isolated_db)

    async def _crash(*_: Any, **__: Any) -> Any:
        raise RuntimeError("worker died mid-node")

    _patch_task_node(monkeypatch, _crash)

    with pytest.raises(RuntimeError, match="worker died mid-node"):
        await engine_tasks.execute_node_task(leased, db_path=isolated_db)

    pending = messages.get_pending_steering(run.id, db_path=isolated_db)
    assert [message.content for message in pending] == [_STEER]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("node", "acknowledged"), [("proximity", False), ("orchestrator", True)]
)
async def test_only_the_orchestrator_commit_acknowledges_steering(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    node: str,
    acknowledged: bool,
) -> None:
    # Only the orchestrator schedules from pending_steering; earlier
    # acknowledgment loses the decision input.
    run = seed_run("Steering durability")
    leased = _seed_steered_node_task(
        run.id, monkeypatch, isolated_db, node=node
    )
    seen: list[str] = []
    _patch_task_node(
        monkeypatch,
        _record_preferences_and_commit(seen, priority=acknowledged),
    )

    await engine_tasks.execute_node_task(leased, db_path=isolated_db)

    assert _STEER in seen[0]
    pending = messages.get_pending_steering(run.id, db_path=isolated_db)
    assert [message.content for message in pending] == (
        [] if acknowledged else [_STEER]
    )


@pytest.mark.asyncio
async def test_steering_text_survives_to_the_node_it_was_meant_for(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Applied steering must remain folded into preferences after acknowledgment
    # or the successor loses guidance.
    run = seed_run("Steering survives")
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
