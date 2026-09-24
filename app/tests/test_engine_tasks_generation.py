"""Generation-strategy and mature-reflection fan-out tests.

A shared plan fanned into independently leased specialist tasks and one
aggregate.
"""

import asyncio
from typing import Any

import pytest
from co_scientist.models import (
    Article,
    GenerationMethod,
    Hypothesis,
)

from app import engine_tasks, store
from app.config import settings
from tests._client import make_client
from tests._engine_tasks_helpers import (
    _Generator,
    _milestones,
    _patch_generator,
    _seed_checkpoint,
    _task_events,
    _task_state,
)

# Records every generate_with_debate call the strategy executor makes, so
# the E14 diversity wiring (index + batch total per durable task) can be
# asserted end to end.
_debate_calls: list[dict[str, Any]] = []


async def _fake_debate(
    **kwargs: Any,
) -> tuple[list[Hypothesis], list[dict[str, Any]], int]:
    _debate_calls.append(kwargs)
    hypotheses = [
        Hypothesis(
            text=f"debate-{index}",
            generation_method=GenerationMethod.DEBATE,
        )
        for index in range(int(kwargs["count"]))
    ]
    return hypotheses, [{"strategy": "debate"}], len(hypotheses)


async def _fake_assumptions(
    _state: Any, count: int
) -> tuple[list[Hypothesis], int]:
    hypotheses = [
        Hypothesis(
            text=f"assumption-{index}",
            generation_method=GenerationMethod.ASSUMPTIONS,
        )
        for index in range(count)
    ]
    return hypotheses, len(hypotheses)


async def _advance_generation_node(
    run_id: str, monkeypatch: pytest.MonkeyPatch, db_path: str
) -> None:
    """Seed a generate node that plans 7 strategy tasks, then fan it out."""
    state = _task_state(run_id)
    state.update(
        {
            "supervisor_guidance": {"focus": "test"},
            "initial_hypotheses_count": 8,
            "enable_tool_calling_generation": False,
        }
    )
    checkpoint_seq = _seed_checkpoint(run_id, state)
    node = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}generate",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key="generation-node",
        ),
        db_path=db_path,
    )
    _patch_generator(monkeypatch, _Generator(state), restore=True)

    import co_scientist.agents.generation.assumptions as assumptions_module
    import co_scientist.agents.generation.debate as debate_module

    monkeypatch.setattr(debate_module, "generate_with_debate", _fake_debate)
    monkeypatch.setattr(
        assumptions_module, "generate_with_assumptions", _fake_assumptions
    )
    leased = store.claim_task("planner", run_id=run_id, db_path=db_path)
    assert leased is not None and leased.id == node.id
    planned = await engine_tasks.execute_node_task(leased, db_path=db_path)
    assert len(planned["fanout_task_ids"]) == 7
    assert store.complete_task(leased.id, "planner", planned, db_path=db_path)


def _assert_debate_fanout_carries_the_batch_shape(
    strategies: list[Any],
) -> None:
    """Each debate task knows its position and the whole batch (E14).

    Without the batch total every per-debate task would angle its debate
    as debate 1 of 1 and the parallel debates would collapse onto one
    diversity angle (finding E14).
    """
    debate_tasks = [
        item
        for item in strategies
        if item is not None
        and str(item.inputs["strategy"]).startswith("debate")
    ]
    assert debate_tasks, "expected debate strategy tasks in the fan-out"
    by_strategy: dict[str, list[Any]] = {}
    for item in debate_tasks:
        by_strategy.setdefault(str(item.inputs["strategy"]), []).append(item)
    for strategy, items in by_strategy.items():
        assert all(
            int(item.inputs["debate_total"]) == len(items) for item in items
        ), f"{strategy} tasks must carry the family's batch size"
        assert sorted(
            int(item.inputs["strategy_index"]) for item in items
        ) == list(range(len(items)))


async def _run_generation_strategies_and_aggregate(
    run_id: str, db_path: str
) -> None:
    """Lease the seven strategy tasks and commit one aggregate."""
    strategies = [
        store.claim_task(f"strategy-{index}", run_id=run_id, db_path=db_path)
        for index in range(7)
    ]
    assert all(item is not None for item in strategies)
    assert all(
        item is not None
        and item.task_type == engine_tasks.GENERATION_STRATEGY_TASK
        for item in strategies
    )
    _assert_debate_fanout_carries_the_batch_shape(strategies)
    _debate_calls.clear()
    strategy_results = await asyncio.gather(
        *[
            engine_tasks.execute_generation_strategy(item, db_path=db_path)
            for item in strategies
            if item is not None
        ]
    )
    # Every debate task handed the engine its own position in the batch
    # and the batch's full size, so each debate gets a distinct angle.
    debate_tasks = [
        item
        for item in strategies
        if item is not None
        and str(item.inputs["strategy"]).startswith("debate")
    ]
    # This degraded-mode scenario plans a single debate family, so the
    # batch below is unambiguous; a lit/no-lit split would assert per
    # family instead.
    assert len({str(item.inputs["strategy"]) for item in debate_tasks}) == 1
    assert len(_debate_calls) == len(debate_tasks)
    batch_size = len(debate_tasks)
    positions = [call["batch_position"] for call in _debate_calls]
    assert all(position is not None for position in positions)
    assert sorted(
        (position.debate_index, position.total_debates)
        for position in positions
    ) == [(index, batch_size) for index in range(batch_size)]
    for index, (item, result) in enumerate(
        zip(strategies, strategy_results, strict=True)
    ):
        assert item is not None
        assert store.complete_task(
            item.id, f"strategy-{index}", result, db_path=db_path
        )
    aggregate = store.claim_task("aggregate", run_id=run_id, db_path=db_path)
    assert aggregate is not None
    aggregated = await engine_tasks.execute_generation_aggregate(
        aggregate, db_path=db_path
    )
    assert aggregated["hypotheses_generated"] == 8
    assert store.complete_task(
        aggregate.id, "aggregate", aggregated, db_path=db_path
    )


def _assert_generation_committed(run_id: str, db_path: str) -> None:
    """Pin the mixed-method commit, milestone, and review successor."""
    from co_scientist.checkpoint import restore_workflow_state

    checkpoint = store.get_latest_checkpoint(run_id, db_path=db_path)
    assert checkpoint is not None
    restored = restore_workflow_state(checkpoint["state"])
    methods = {
        hypothesis.generation_method for hypothesis in restored["hypotheses"]
    }
    assert methods == {GenerationMethod.DEBATE, GenerationMethod.ASSUMPTIONS}
    # Every strategy item reported real llm_calls (finding L3); the
    # aggregate must fold them into the committed metrics instead of
    # discarding them the way it did before the fix. Each fake strategy
    # reports one call per hypothesis it produced, so this sums to the
    # same 8 hypotheses_generated asserted above.
    assert restored["metrics"].llm_calls == 8
    assert _milestones(run_id, db_path=db_path) == [
        "3 hypotheses generated (initial)"
    ]
    generate_events = _task_events(run_id, "generate", db_path=db_path)
    assert len(generate_events) == 1
    assert generate_events[0]["payload"]["successor"] == "review"
    successor = store.claim_task("review", run_id=run_id, db_path=db_path)
    assert successor is not None
    assert successor.task_type == f"{engine_tasks.NODE_TASK_PREFIX}review"


@pytest.mark.asyncio
async def test_generation_strategies_are_independently_leased_and_aggregated(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Debate and assumptions generation share a plan but execute separately."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    await _advance_generation_node(run.id, monkeypatch, isolated_db)
    await _run_generation_strategies_and_aggregate(run.id, isolated_db)
    _assert_generation_committed(run.id, isolated_db)


@pytest.mark.asyncio
async def test_generation_fanout_created_during_pause_waits_for_resume(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A leased generation planner may finish, but its wave waits for resume."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    original_dispatch = engine_tasks._dispatch_node_fanout

    with make_client() as client:
        created = client.post(
            "/api/runs", json={"research_goal": "Paused generation fan-out"}
        )
        assert created.status_code == 200, created.text
        run_id = str(created.json()["id"])
        store.update_run_status(
            run_id, store.RunStatus.RUNNING, db_path=isolated_db
        )

        async def pause_during_dispatch(
            task: Any,
            state: dict[str, Any],
            node_name: str,
            checkpoint_seq: int,
            db_path: str | None,
        ) -> dict[str, Any] | None:
            if node_name == "generate":
                paused = client.post(f"/api/runs/{run_id}/pause")
                assert paused.status_code == 200, paused.text
                assert paused.json()["status"] == "paused"
            return await original_dispatch(
                task, state, node_name, checkpoint_seq, db_path
            )

        monkeypatch.setattr(
            engine_tasks, "_dispatch_node_fanout", pause_during_dispatch
        )
        await _advance_generation_node(run_id, monkeypatch, isolated_db)

        scheduled = store.list_tasks(run_id, db_path=isolated_db)
        fanout = [
            task
            for task in scheduled
            if task.task_type != f"{engine_tasks.NODE_TASK_PREFIX}generate"
        ]
        assert fanout
        saved_run = store.get_run(run_id, db_path=isolated_db)
        assert saved_run is not None and saved_run.status == "paused"
        assert (
            store.claim_task(
                "before-resume", run_id=run_id, db_path=isolated_db
            )
            is None
        )

        resumed = client.post(f"/api/runs/{run_id}/resume")
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["status"] == "queued"
        aggregate = next(
            task
            for task in store.list_tasks(run_id, db_path=isolated_db)
            if task.task_type == engine_tasks.GENERATION_AGGREGATE_TASK
        )
        assert aggregate.status == "queued"
        claimed = store.claim_task(
            "after-resume", run_id=run_id, db_path=isolated_db
        )
        assert claimed is not None
        assert claimed.task_type == engine_tasks.GENERATION_STRATEGY_TASK


async def _fake_mature_review(
    _state: Any, _hypothesis: Any, mode: Any
) -> tuple[Any, dict[str, Any], dict[str, Any] | None]:
    result: dict[str, Any] = {"verdict": f"{mode.value}-complete"}
    if mode.value == "full":
        result["retrieved_articles"] = [
            Article(
                title="Full-review source",
                source_id="full-review-1",
                abstract="Targeted review evidence.",
            ).to_dict()
        ]
    # A review that researched nothing, which is every review on a tier
    # that does not fund it.
    return mode, result, None


async def _fake_observation(**_: Any) -> dict[str, Any]:
    return {"classification": "missing_piece", "reasoning": "explains x"}


async def _advance_mature_reflection_node(
    run_id: str, monkeypatch: pytest.MonkeyPatch, db_path: str
) -> None:
    """Seed a mixed fresh/mature comprehensive_reflection node; fan it out."""
    state = _task_state(run_id)
    fresh = Hypothesis(text="fresh")
    fresh.review_disposition = "viable"
    mature = Hypothesis(text="mature")
    mature.review_disposition = "viable"
    mature.enrichments.update({"full": {}, "simulation": {}})
    mature.reflection_notes = "prior observation"
    state.update(
        {
            "hypotheses": [fresh, mature],
            "articles_with_reasoning": "retrieved observations",
            "current_iteration": 2,
        }
    )
    checkpoint_seq = _seed_checkpoint(run_id, state)
    node = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}comprehensive_reflection",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key="mature-reflection-node",
        ),
        db_path=db_path,
    )
    _patch_generator(monkeypatch, _Generator(state), restore=True)

    import co_scientist.agents.reflection.comprehensive_reflection as comp_refl
    import co_scientist.agents.reflection.reflection as observation_module

    monkeypatch.setattr(comp_refl, "_run_review", _fake_mature_review)
    monkeypatch.setattr(
        observation_module, "analyze_single_hypothesis", _fake_observation
    )
    leased = store.claim_task("planner", run_id=run_id, db_path=db_path)
    assert leased is not None and leased.id == node.id
    planned = await engine_tasks.execute_node_task(leased, db_path=db_path)
    assert len(planned["fanout_task_ids"]) == 4
    assert store.complete_task(leased.id, "planner", planned, db_path=db_path)


async def _run_mature_reflection_items_and_aggregate(
    run_id: str, db_path: str
) -> None:
    """Lease the four review-mode tasks and commit one aggregate."""
    items = [
        store.claim_task(f"mode-{index}", run_id=run_id, db_path=db_path)
        for index in range(4)
    ]
    assert all(item is not None for item in items)
    results = await asyncio.gather(
        *[
            engine_tasks.execute_mature_reflection_item(item, db_path=db_path)
            for item in items
            if item is not None
        ]
    )
    assert {result["review_mode"] for result in results} == {
        "observation",
        "full",
        "simulation",
        "recurrent",
    }
    for index, (item, result) in enumerate(zip(items, results, strict=True)):
        assert item is not None
        assert store.complete_task(
            item.id, f"mode-{index}", result, db_path=db_path
        )
    aggregate = store.claim_task("aggregate", run_id=run_id, db_path=db_path)
    assert aggregate is not None
    aggregated = await engine_tasks.execute_mature_reflection_aggregate(
        aggregate, db_path=db_path
    )
    assert aggregated["successful_reviews"] == 4
    assert store.complete_task(
        aggregate.id, "aggregate", aggregated, db_path=db_path
    )


def _assert_mature_reflection_committed(run_id: str, db_path: str) -> None:
    """Pin per-hypothesis enrichments, evidence, and safety_screen successor."""
    from co_scientist.checkpoint import restore_workflow_state

    checkpoint = store.get_latest_checkpoint(run_id, db_path=db_path)
    assert checkpoint is not None
    restored = restore_workflow_state(checkpoint["state"])
    restored_fresh, restored_mature = restored["hypotheses"]
    assert {"observation", "full", "simulation"} <= set(
        restored_fresh.enrichments
    )
    assert restored_mature.enrichments["recurrent_review_iteration"] == 2
    assert restored["articles"][-1].source_id == "full-review-1"
    successor = store.claim_task("safety", run_id=run_id, db_path=db_path)
    assert successor is not None
    assert (
        successor.task_type == f"{engine_tasks.NODE_TASK_PREFIX}safety_screen"
    )
    # The mature-reflection fan-out aggregate now emits its own
    # scientific_task completion, matching the other four aggregates.
    reflection_events = _task_events(
        run_id, "comprehensive_reflection", db_path=db_path
    )
    assert len(reflection_events) == 1
    assert reflection_events[0]["payload"]["successor"] == "safety_screen"


@pytest.mark.asyncio
async def test_mature_reflection_modes_are_independent_durable_tasks(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Observation, full, simulation, and recurrent modes lease separately."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    await _advance_mature_reflection_node(run.id, monkeypatch, isolated_db)
    await _run_mature_reflection_items_and_aggregate(run.id, isolated_db)
    _assert_mature_reflection_committed(run.id, isolated_db)
