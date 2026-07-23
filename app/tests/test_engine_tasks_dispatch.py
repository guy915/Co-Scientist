"""Dispatch and lifecycle tests for the durable engine executor.

Supervisor priority reaching a successor, the specialist task chain,
finalize's post-drain stage events, and generic node-completion milestones.
"""

from typing import Any

import pytest
from co_scientist.models import (
    Article,
    Hypothesis,
    HypothesisReview,
)

from app import engine_tasks, store, task_worker
from tests._engine_tasks_helpers import (
    _Generator,
    _milestones,
    _patch_generator,
    _patch_task_node,
    _seed_checkpoint,
    _task_state,
)


def _priority_state(run_id: str, deferred_id: str) -> dict[str, Any]:
    """State carrying a next-task priority and a reprioritize queue action."""
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
    """Seed a claimed orchestrator task plus a low-priority deferred task."""
    store.save_checkpoint(
        run_id,
        store.NewCheckpoint(
            stage="seed",
            schema_version=1,
            last_event_seq=0,
            state={"provider": "engine"},
        ),
        db_path=db_path,
    )
    queued = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type="engine.node.orchestrator",
            inputs={"checkpoint_seq": 1},
            idempotency_key="orchestrator-priority",
        ),
        db_path=db_path,
    )
    task = store.claim_task("worker", run_id=run_id, db_path=db_path)
    assert task is not None and task.id == queued.id
    deferred = store.enqueue_task(
        store.NewTask(
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
    """The Supervisor's selected priority controls queue claim order."""
    run = store.create_run("Priority science", "standard", "engine", {})
    task, deferred = _seed_orchestrator_task(run.id, isolated_db)

    engine_tasks._save_state_and_enqueue(
        task,
        _priority_state(run.id, deferred.id),
        "generate",
        expected_checkpoint_seq=1,
        db_path=isolated_db,
    )

    successor = store.list_tasks(run.id, db_path=isolated_db)[-1]
    assert successor.task_type == "engine.node.generate"
    assert successor.priority == 97
    updated = store.get_task(deferred.id, db_path=isolated_db)
    assert updated is not None and updated.priority == 98


@pytest.mark.asyncio
async def test_worker_consumes_independent_specialist_task_chain(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One run advances through separately committed and leased node tasks."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    engine_tasks.enqueue_bootstrap(run.id, db_path=isolated_db)
    generator = _Generator(_task_state(run.id))
    _patch_generator(monkeypatch, generator, restore=True, screen=True)

    successors = {"supervisor": "research_overview", "research_overview": None}

    async def execute(
        name: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        return state, successors[name]

    async def finalize(task: Any, **_: Any) -> dict[str, Any]:
        store.update_run_status(task.run_id, store.RunStatus.COMPLETED)
        return {"run_id": task.run_id, "status": "completed"}

    _patch_task_node(monkeypatch, execute)
    monkeypatch.setattr(engine_tasks, "execute_finalize", finalize)
    await task_worker.run_run_until_idle(run.id, "worker", db_path=isolated_db)

    tasks = store.list_tasks(run.id, db_path=isolated_db)
    assert [task.task_type for task in tasks] == [
        "engine.bootstrap",
        "engine.node.supervisor",
        "engine.node.research_overview",
        "engine.finalize",
    ]
    assert all(task.status == "completed" for task in tasks)
    # Milestones append once in commit order, matching the streaming path's
    # `supervisor.plan` and `research_overview` emissions (see events.py).
    assert _milestones(run.id, db_path=isolated_db) == [
        "Research plan ready — supervisor complete",
        "Research overview ready",
    ]


def _seed_finalize_task(
    run_id: str, monkeypatch: pytest.MonkeyPatch, db_path: str
) -> Any:
    """Seed a grounded finalize task; patch restore to the fixture generator."""
    hypothesis = Hypothesis(
        text="Astrocyte lactate accelerates synaptic ATP recovery.",
        literature_grounding=(
            "Astrocyte lactate accelerates synaptic ATP recovery."
        ),
    )
    state = _task_state(run_id)
    state["hypotheses"] = [hypothesis]
    # An article whose abstract carries the hypothesis's claim so grounding
    # finds support (blocked=0) rather than quarantining it as unsupported.
    state["articles"] = [
        Article(
            title="Synaptic energetics",
            url="https://example.org/synaptic",
            abstract="Astrocyte lactate accelerates synaptic ATP recovery.",
        )
    ]
    _seed_checkpoint(run_id, state, db_path=db_path)
    task = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=engine_tasks.FINALIZE_TASK,
            inputs={},
            idempotency_key="finalize",
        ),
        db_path=db_path,
    )
    # Restore builds a real generator otherwise; the fixture generator carries a
    # null tool_registry, which restore_workflow_state accepts.
    monkeypatch.setattr(
        engine_tasks, "_generator_for_restore", lambda *_: _Generator(state)
    )
    return task


def _assert_post_drain_counts(by_type: dict[str, Any]) -> None:
    """Pin the safety/grounding/citation-audit stage-event payloads."""
    assert set(by_type["safety.hypothesis"]) == {
        "screened",
        "blocked",
        "eligible",
    }
    assert by_type["safety.hypothesis"] == {
        "screened": 1,
        "blocked": 0,
        "eligible": 1,
    }
    assert set(by_type["citation.grounding"]) == {
        "grounded",
        "blocked",
        "eligible",
    }
    assert by_type["citation.grounding"] == {
        "grounded": 1,
        "blocked": 0,
        "eligible": 1,
    }
    # No citation_map on the hypothesis, so every state count is zero, but the
    # full citation-state vocabulary is present in the audit payload.
    citation_audit = by_type["citation_audit"]
    assert citation_audit
    assert all(isinstance(v, int) for v in citation_audit.values())


@pytest.mark.asyncio
async def test_execute_finalize_emits_post_drain_stage_events(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The durable finalize task emits the three post-drain stage events.

    Pins the production ``execute_finalize`` path end to end: it must pop the
    drain's ``safety_counts``/``grounding_counts`` (which are not
    ``finalize_report`` kwargs), emit ``safety.hypothesis``,
    ``citation.grounding``, and ``citation_audit`` from them, and still run
    ``finalize_report`` to completion. Without the pop this path would raise
    ``TypeError: finalize_report() got an unexpected keyword argument``.
    """
    run = store.create_run("Task-level science", "standard", "engine", {})
    task = _seed_finalize_task(run.id, monkeypatch, isolated_db)

    result = await engine_tasks.execute_finalize(task, db_path=isolated_db)

    # finalize_report ran to completion (no leaked kwargs, no TypeError).
    assert result["status"] == store.RunStatus.COMPLETED.value
    assert store.get_latest_report(run.id, db_path=isolated_db) is not None

    events = store.list_events(run.id, db_path=isolated_db)
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
    """The remaining milestone-bearing nodes append their canonical chat text.

    Covers the four node types (reflection, evolve, proximity, meta_review)
    the streaming path milestones (see events.py's ``_MILESTONE_BUILDERS``)
    that no other durable-executor test happens to exercise through
    ``execute_node_task``'s generic completion path. The rest are covered
    elsewhere: supervisor.plan and research_overview by
    ``test_worker_consumes_independent_specialist_task_chain``, generate by
    ``test_generation_strategies_are_independently_leased_and_aggregated``,
    ranking by ``test_ranking_matches_..._checkpointed_tasks``, and
    deep_verification by ``test_verification_children_..._aggregator``.
    """
    run = store.create_run("Task-level science", "standard", "engine", {})
    checkpoint_seq = _seed_checkpoint(run.id, _task_state(run.id))
    node = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}{node_name}",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"milestone-{node_name}",
        ),
        db_path=isolated_db,
    )
    leased = store.claim_task("worker", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == node.id

    async def execute(
        _name: str, state: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        return {**state, **extra_state}, None

    _patch_task_node(monkeypatch, execute)
    result = await engine_tasks.execute_node_task(leased, db_path=isolated_db)
    assert store.complete_task(leased.id, "worker", result, db_path=isolated_db)
    assert _milestones(run.id, db_path=isolated_db) == [expected_milestone]
