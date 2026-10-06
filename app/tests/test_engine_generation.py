import asyncio
from typing import Any

import pytest
from co_scientist.agents.generation import (
    assumptions,
    debate,
    literature_tools,
)
from co_scientist.agents.generation import (
    generate as coordinator,
)
from co_scientist.checkpoint import restore_workflow_state
from co_scientist.models import (
    Article,
    GenerationMethod,
    Hypothesis,
)

import app.engine_tasks.fanout as engine_tasks_fanout_generation
import app.engine_tasks.fanout as fanout
from app import engine_tasks
from app.config import settings
from app.engine_tasks import fanout_aggregates as aggregates
from app.engine_tasks import fanout_aggregates as engine_tasks_fanout_aggregates
from app.engine_tasks import node as engine_tasks_node
from app.engine_tasks import support
from app.engine_tasks import support as engine_tasks_support
from app.store import checkpoints, runs
from app.store import tasks as store
from app.store import tasks_lifecycle as lifecycle
from app.store.models import RunStatus, ScientificTask
from tests._client import create_run as _create_run
from tests._client import make_client
from tests._engine_tasks_helpers import (
    _Generator,
    _milestones,
    _patch_generator,
    _seed_checkpoint,
    _task_events,
    _task_state,
)
from tests._store_helpers import enqueue_task, seed_run

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
    state = _task_state(run_id)
    state.update(
        {
            "supervisor_guidance": {"focus": "test"},
            "initial_hypotheses_count": 8,
            "enable_tool_calling_generation": False,
        }
    )
    checkpoint_seq = _seed_checkpoint(run_id, state)
    node = enqueue_task(
        run_id,
        f"{engine_tasks.NODE_TASK_PREFIX}generate",
        "generation-node",
        inputs={"checkpoint_seq": checkpoint_seq},
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
    assert lifecycle.complete_task(
        leased.id, "planner", planned, db_path=db_path
    )


def _assert_debate_fanout_carries_the_batch_shape(
    strategies: list[Any],
) -> None:
    # Debate needs batch size or parallel angles all identify as the first
    # angle.
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
    strategies = [
        store.claim_task(f"strategy-{index}", run_id=run_id, db_path=db_path)
        for index in range(7)
    ]
    assert all(item is not None for item in strategies)
    assert all(
        item is not None
        and item.task_type == engine_tasks_support.GENERATION_STRATEGY_TASK
        for item in strategies
    )
    _assert_debate_fanout_carries_the_batch_shape(strategies)
    _debate_calls.clear()
    strategy_results = await asyncio.gather(
        *[
            engine_tasks_fanout_generation.execute_generation_strategy(
                item, db_path=db_path
            )
            for item in strategies
            if item is not None
        ]
    )
    debate_tasks = [
        item
        for item in strategies
        if item is not None
        and str(item.inputs["strategy"]).startswith("debate")
    ]
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
        assert lifecycle.complete_task(
            item.id, f"strategy-{index}", result, db_path=db_path
        )
    aggregate = store.claim_task("aggregate", run_id=run_id, db_path=db_path)
    assert aggregate is not None
    aggregated = (
        await engine_tasks_fanout_aggregates.execute_generation_aggregate(
            aggregate, db_path=db_path
        )
    )
    assert aggregated["hypotheses_generated"] == 8
    assert lifecycle.complete_task(
        aggregate.id, "aggregate", aggregated, db_path=db_path
    )


def _assert_generation_committed(run_id: str, db_path: str) -> None:
    from co_scientist.checkpoint import restore_workflow_state

    checkpoint = checkpoints.get_latest_checkpoint(run_id, db_path=db_path)
    assert checkpoint is not None
    restored = restore_workflow_state(checkpoint["state"])
    methods = {
        hypothesis.generation_method for hypothesis in restored["hypotheses"]
    }
    assert methods == {GenerationMethod.DEBATE, GenerationMethod.ASSUMPTIONS}
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
    run = seed_run("Task-level science")
    await _advance_generation_node(run.id, monkeypatch, isolated_db)
    await _run_generation_strategies_and_aggregate(run.id, isolated_db)
    _assert_generation_committed(run.id, isolated_db)


@pytest.mark.asyncio
async def test_generation_fanout_created_during_pause_waits_for_resume(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    original_dispatch = engine_tasks_node._dispatch_node_fanout

    with make_client() as client:
        created = _create_run(client, "Paused generation fan-out")
        assert created.status_code == 200, created.text
        run_id = str(created.json()["id"])
        runs.update_run_status(run_id, RunStatus.RUNNING, db_path=isolated_db)

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
            engine_tasks_node, "_dispatch_node_fanout", pause_during_dispatch
        )
        await _advance_generation_node(run_id, monkeypatch, isolated_db)

        scheduled = store.list_tasks(run_id, db_path=isolated_db)
        fanout = [
            task
            for task in scheduled
            if task.task_type != f"{engine_tasks.NODE_TASK_PREFIX}generate"
        ]
        assert fanout
        saved_run = runs.get_run(run_id, db_path=isolated_db)
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
            if task.task_type == engine_tasks_support.GENERATION_AGGREGATE_TASK
        )
        assert aggregate.status == "queued"
        claimed = store.claim_task(
            "after-resume", run_id=run_id, db_path=isolated_db
        )
        assert claimed is not None
        assert (
            claimed.task_type == engine_tasks_support.GENERATION_STRATEGY_TASK
        )


def _hypotheses(strategy: str, count: int, start: int = 0) -> list[Hypothesis]:
    methods = {
        "tools": GenerationMethod.LITERATURE_TOOLS,
        "debate_lit": GenerationMethod.DEBATE,
        "debate_only": GenerationMethod.DEBATE,
        "assumptions": GenerationMethod.ASSUMPTIONS,
    }
    return [
        Hypothesis(
            id=f"{strategy}-{index}",
            text=f"{strategy}-{index}",
            generation_method=methods[strategy],
            literature_grounding="Fixture grounding",
        )
        for index in range(start, start + count)
    ]


class _Strategies:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def tools(
        self, _state: Any, count: int, reference_index: Any
    ) -> tuple[list[Hypothesis], int]:
        self.calls.append(
            {"strategy": "tools", "count": count, "refs": reference_index}
        )
        return _hypotheses("tools", count), 4

    async def debate(
        self,
        *,
        state: Any,
        count: int,
        articles_with_reasoning: str | None,
        reference_index: Any,
        batch_position: Any = None,
    ) -> tuple[list[Hypothesis], list[dict[str, Any]], int]:
        strategy = "debate_lit" if articles_with_reasoning else "debate_only"
        start = batch_position.debate_index if batch_position else 0
        self.calls.append(
            {
                "strategy": strategy,
                "count": count,
                "literature": articles_with_reasoning,
                "refs": reference_index,
                "position": batch_position,
            }
        )
        hypotheses = _hypotheses(strategy, count, start)
        return (
            hypotheses,
            [{"debate_id": hyp.id} for hyp in hypotheses],
            count * 2,
        )

    async def assumptions(
        self,
        _state: Any,
        count: int,
        articles_with_reasoning: str | None = None,
        reference_index: Any = None,
    ) -> tuple[list[Hypothesis], int]:
        self.calls.append(
            {
                "strategy": "assumptions",
                "count": count,
                "literature": articles_with_reasoning,
                "refs": reference_index,
            }
        )
        return _hypotheses("assumptions", count), 3


def _install_strategies(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[_Strategies, list[str]]:
    strategies = _Strategies()
    for module in (coordinator, literature_tools):
        monkeypatch.setattr(module, "generate_with_tools", strategies.tools)
    for module in (coordinator, debate):
        monkeypatch.setattr(module, "generate_with_debate", strategies.debate)
    for module in (coordinator, assumptions):
        monkeypatch.setattr(
            module, "generate_with_assumptions", strategies.assumptions
        )
    expansion_calls: list[str] = []

    async def no_expansion(state: Any) -> None:
        expansion_calls.append(str(state["run_id"]))

    monkeypatch.setattr(coordinator, "research_for_expansion", no_expansion)
    return strategies, expansion_calls


def _generation_state(run_id: str, mode: str) -> dict[str, Any]:
    state = _task_state(run_id)
    state.update(
        {
            "supervisor_guidance": {"focus": "test"},
            "initial_hypotheses_count": 8,
            "current_iteration": 2,
            "hypotheses": [Hypothesis(id="parent", text="existing idea")],
            "articles": [Article(title="Read source", used_in_analysis=True)],
            "mcp_available": mode != "no_lit",
            "articles_with_reasoning": "Read evidence",
            "enable_tool_calling_generation": mode == "lit_and_tools",
        }
    )
    return state


async def _schedule_generation(
    state: dict[str, Any], db_path: str
) -> tuple[dict[str, Any], list[ScientificTask]]:
    checkpoint_seq = _seed_checkpoint(state["run_id"], state, db_path=db_path)
    node = enqueue_task(
        state["run_id"],
        f"{support.NODE_TASK_PREFIX}generate",
        "generation-contract",
        inputs={"checkpoint_seq": checkpoint_seq},
        db_path=db_path,
    )
    leased = store.claim_task("planner", run_id=node.run_id, db_path=db_path)
    assert leased is not None and leased.id == node.id
    planned = await fanout._enqueue_generation_fanout(
        leased, state, checkpoint_seq, db_path=db_path
    )
    assert lifecycle.complete_task(
        leased.id, "planner", planned, db_path=db_path
    )
    tasks = [
        store.get_task(task_id, db_path=db_path)
        for task_id in planned["fanout_task_ids"]
    ]
    assert all(task is not None for task in tasks)
    return planned, [task for task in tasks if task is not None]


async def test_durable_aggregate_preserves_successes_after_a_strategy_fails(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = seed_run("Partial generation")
    state = _generation_state(run.id, "lit_and_tools")
    _install_strategies(monkeypatch)

    async def failed_tools(*_args: Any) -> Any:
        raise RuntimeError("draft failed")

    monkeypatch.setattr(coordinator, "generate_with_tools", failed_tools)
    with pytest.raises(RuntimeError, match="draft failed"):
        await coordinator.generate_hypotheses(state)

    monkeypatch.setattr(literature_tools, "generate_with_tools", failed_tools)
    planned, tasks = await _schedule_generation(state, isolated_db)
    for _ in tasks:
        leased = store.claim_task(
            "strategy", run_id=run.id, db_path=isolated_db
        )
        assert leased is not None
        if leased.inputs["strategy"] == "tools":
            with pytest.raises(RuntimeError, match="draft failed"):
                await fanout.execute_generation_strategy(
                    leased, db_path=isolated_db
                )
            assert store.fail_task(
                leased.id,
                "strategy",
                "draft failed",
                retryable=False,
                db_path=isolated_db,
            )
        else:
            result = await fanout.execute_generation_strategy(
                leased, db_path=isolated_db
            )
            result["skills_used"] = {"pubmed": 1}
            result["model_usage"] = {
                "generate:fixture": {"calls": 1, "prompt_tokens": 10}
            }
            assert lifecycle.complete_task(
                leased.id, "strategy", result, db_path=isolated_db
            )

    aggregate = store.claim_task(
        "aggregate", run_id=run.id, db_path=isolated_db
    )
    assert (
        aggregate is not None and aggregate.id == planned["aggregate_task_id"]
    )
    result = await aggregates.execute_generation_aggregate(
        aggregate, db_path=isolated_db
    )
    assert result["failed_strategies"] == 1
    assert result["hypotheses_generated"] == 5
    checkpoint = checkpoints.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    committed = restore_workflow_state(checkpoint["state"])
    assert [hyp.id for hyp in committed["hypotheses"]] == [
        "parent",
        "debate_lit-0",
        "debate_lit-1",
        "debate_lit-2",
        "assumptions-0",
        "assumptions-1",
    ]
    assert committed["metrics"].llm_calls == 9
    assert committed["metrics"].skills_used == {"pubmed": 4}
    assert committed["metrics"].model_usage["generate:fixture"]["calls"] == 4
    assert (
        committed["metrics"].model_usage["generate:fixture"]["prompt_tokens"]
        == 40
    )
    assert [item["debate_id"] for item in committed["debate_transcripts"]] == [
        "debate_lit-0",
        "debate_lit-1",
        "debate_lit-2",
    ]
