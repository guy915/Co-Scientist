"""Generation-strategy and mature-reflection fan-out tests.

A shared plan fanned into independently leased specialist tasks and one
aggregate.
"""

import asyncio
from typing import Any

import pytest
from co_scientist.models import (
    Article,
    Hypothesis,
)

from app import engine_tasks, store
from tests._engine_tasks_helpers import (
    _Generator,
    _seed_checkpoint,
    _task_state,
)


@pytest.mark.asyncio
async def test_generation_strategies_are_independently_leased_and_aggregated(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Debate and assumptions generation share a plan but execute separately."""
    from co_scientist.checkpoint import restore_workflow_state
    from co_scientist.models import GenerationMethod

    run = store.create_run("Task-level science", "standard", "engine", {})
    state = _task_state(run.id)
    state.update(
        {
            "supervisor_guidance": {"focus": "test"},
            "initial_hypotheses_count": 8,
            "enable_tool_calling_generation": False,
        }
    )
    checkpoint_seq = _seed_checkpoint(run.id, state)
    node = store.enqueue_task(
        run.id,
        f"{engine_tasks.NODE_TASK_PREFIX}generate",
        {"checkpoint_seq": checkpoint_seq},
        idempotency_key="generation-node",
        db_path=isolated_db,
    )
    generator = _Generator(state)
    monkeypatch.setattr(
        engine_tasks, "_generator_and_opts", lambda *_: (generator, {})
    )
    monkeypatch.setattr(
        engine_tasks, "_generator_for_restore", lambda *_: generator
    )

    import co_scientist.agents.generation.assumptions as assumptions_module
    import co_scientist.agents.generation.debate as debate_module

    async def fake_debate(
        **kwargs: Any,
    ) -> tuple[list[Hypothesis], list[dict[str, Any]]]:
        hypotheses = [
            Hypothesis(
                text=f"debate-{index}",
                generation_method=GenerationMethod.DEBATE,
            )
            for index in range(int(kwargs["count"]))
        ]
        return hypotheses, [{"strategy": "debate"}]

    async def fake_assumptions(_state: Any, count: int) -> list[Hypothesis]:
        return [
            Hypothesis(
                text=f"assumption-{index}",
                generation_method=GenerationMethod.ASSUMPTIONS,
            )
            for index in range(count)
        ]

    monkeypatch.setattr(debate_module, "generate_with_debate", fake_debate)
    monkeypatch.setattr(
        assumptions_module, "generate_with_assumptions", fake_assumptions
    )
    leased = store.claim_task("planner", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == node.id
    planned = await engine_tasks.execute_node_task(leased, db_path=isolated_db)
    assert len(planned["fanout_task_ids"]) == 7
    assert store.complete_task(
        leased.id, "planner", planned, db_path=isolated_db
    )

    strategies = [
        store.claim_task(
            f"strategy-{index}", run_id=run.id, db_path=isolated_db
        )
        for index in range(7)
    ]
    assert all(item is not None for item in strategies)
    assert all(
        item is not None
        and item.task_type == engine_tasks.GENERATION_STRATEGY_TASK
        for item in strategies
    )
    strategy_results = await asyncio.gather(
        *[
            engine_tasks.execute_generation_strategy(item, db_path=isolated_db)
            for item in strategies
            if item is not None
        ]
    )
    for index, (item, result) in enumerate(
        zip(strategies, strategy_results, strict=True)
    ):
        assert item is not None
        assert store.complete_task(
            item.id, f"strategy-{index}", result, db_path=isolated_db
        )
    aggregate = store.claim_task(
        "aggregate", run_id=run.id, db_path=isolated_db
    )
    assert aggregate is not None
    aggregated = await engine_tasks.execute_generation_aggregate(
        aggregate, db_path=isolated_db
    )
    assert aggregated["hypotheses_generated"] == 8
    assert store.complete_task(
        aggregate.id, "aggregate", aggregated, db_path=isolated_db
    )
    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    restored = restore_workflow_state(checkpoint["state"])
    methods = {
        hypothesis.generation_method for hypothesis in restored["hypotheses"]
    }
    assert methods == {GenerationMethod.DEBATE, GenerationMethod.ASSUMPTIONS}
    milestones = [
        message
        for message in store.list_messages(run.id, db_path=isolated_db)
        if message.kind == "milestone"
    ]
    assert [message.content for message in milestones] == [
        "3 hypotheses generated (initial)"
    ]
    events = store.list_events(run.id, db_path=isolated_db)
    generate_events = [
        e for e in events if e["payload"].get("task") == "generate"
    ]
    assert len(generate_events) == 1
    assert generate_events[0]["payload"]["successor"] == "review"
    successor = store.claim_task("review", run_id=run.id, db_path=isolated_db)
    assert successor is not None
    assert successor.task_type == f"{engine_tasks.NODE_TASK_PREFIX}review"


@pytest.mark.asyncio
async def test_mature_reflection_modes_are_independent_durable_tasks(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Observation, full, simulation, and recurrent modes lease separately."""
    from co_scientist.checkpoint import restore_workflow_state

    run = store.create_run("Task-level science", "standard", "engine", {})
    state = _task_state(run.id)
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
    checkpoint_seq = _seed_checkpoint(run.id, state)
    node = store.enqueue_task(
        run.id,
        f"{engine_tasks.NODE_TASK_PREFIX}comprehensive_reflection",
        {"checkpoint_seq": checkpoint_seq},
        idempotency_key="mature-reflection-node",
        db_path=isolated_db,
    )
    generator = _Generator(state)
    monkeypatch.setattr(
        engine_tasks, "_generator_and_opts", lambda *_: (generator, {})
    )
    monkeypatch.setattr(
        engine_tasks, "_generator_for_restore", lambda *_: generator
    )

    import co_scientist.agents.reflection.comprehensive_reflection as comp_refl
    import co_scientist.agents.reflection.reflection as observation_module

    async def fake_review(
        _state: Any, _hypothesis: Any, mode: Any
    ) -> tuple[Any, dict[str, Any]]:
        result: dict[str, Any] = {"verdict": f"{mode.value}-complete"}
        if mode.value == "full":
            result["retrieved_articles"] = [
                Article(
                    title="Full-review source",
                    source_id="full-review-1",
                    abstract="Targeted review evidence.",
                ).to_dict()
            ]
        return mode, result

    async def fake_observation(**_: Any) -> dict[str, Any]:
        return {"classification": "missing_piece", "reasoning": "explains x"}

    monkeypatch.setattr(comp_refl, "_run_review", fake_review)
    monkeypatch.setattr(
        observation_module, "analyze_single_hypothesis", fake_observation
    )
    leased = store.claim_task("planner", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == node.id
    planned = await engine_tasks.execute_node_task(leased, db_path=isolated_db)
    assert len(planned["fanout_task_ids"]) == 4
    assert store.complete_task(
        leased.id, "planner", planned, db_path=isolated_db
    )
    items = [
        store.claim_task(f"mode-{index}", run_id=run.id, db_path=isolated_db)
        for index in range(4)
    ]
    assert all(item is not None for item in items)
    results = await asyncio.gather(
        *[
            engine_tasks.execute_mature_reflection_item(
                item, db_path=isolated_db
            )
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
            item.id, f"mode-{index}", result, db_path=isolated_db
        )
    aggregate = store.claim_task(
        "aggregate", run_id=run.id, db_path=isolated_db
    )
    assert aggregate is not None
    aggregated = await engine_tasks.execute_mature_reflection_aggregate(
        aggregate, db_path=isolated_db
    )
    assert aggregated["successful_reviews"] == 4
    assert store.complete_task(
        aggregate.id, "aggregate", aggregated, db_path=isolated_db
    )
    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    restored = restore_workflow_state(checkpoint["state"])
    restored_fresh, restored_mature = restored["hypotheses"]
    assert {"observation", "full", "simulation"} <= set(
        restored_fresh.enrichments
    )
    assert restored_mature.enrichments["recurrent_review_iteration"] == 2
    assert restored["articles"][-1].source_id == "full-review-1"
    successor = store.claim_task("safety", run_id=run.id, db_path=isolated_db)
    assert successor is not None
    assert (
        successor.task_type == f"{engine_tasks.NODE_TASK_PREFIX}safety_screen"
    )
    # The mature-reflection fan-out aggregate now emits its own
    # scientific_task completion, matching the other four aggregates.
    events = store.list_events(run.id, db_path=isolated_db)
    reflection_events = [
        e
        for e in events
        if e["payload"].get("task") == "comprehensive_reflection"
    ]
    assert len(reflection_events) == 1
    assert reflection_events[0]["payload"]["successor"] == "safety_screen"
