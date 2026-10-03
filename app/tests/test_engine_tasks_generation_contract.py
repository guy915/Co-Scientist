"""Graph and durable generation share a plan without changing task policy."""

import dataclasses
from typing import Any

import pytest
from co_scientist.agents.generation import (
    assumptions,
    debate,
    literature_tools,
    prepare_generation,
)
from co_scientist.agents.generation import (
    generate as coordinator,
)
from co_scientist.checkpoint import restore_workflow_state
from co_scientist.models import Article, GenerationMethod, Hypothesis

from app import store
from app.engine_tasks import fanout_aggregates as aggregates
from app.engine_tasks import fanout_generation as fanout
from app.engine_tasks import support
from tests._engine_tasks_helpers import _seed_checkpoint, _task_state


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
    # Graph binds callables in its orchestrator; durable tasks resolve the
    # defining strategy modules. Patching both drives the actual callers.
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
) -> tuple[dict[str, Any], list[store.ScientificTask]]:
    checkpoint_seq = _seed_checkpoint(state["run_id"], state, db_path=db_path)
    node = store.enqueue_task(
        store.NewTask(
            run_id=state["run_id"],
            task_type=f"{support.NODE_TASK_PREFIX}generate",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key="generation-contract",
        ),
        db_path=db_path,
    )
    leased = store.claim_task("planner", run_id=node.run_id, db_path=db_path)
    assert leased is not None and leased.id == node.id
    planned = await fanout._enqueue_generation_fanout(
        leased, state, checkpoint_seq, db_path=db_path
    )
    assert store.complete_task(leased.id, "planner", planned, db_path=db_path)
    tasks = [
        store.get_task(task_id, db_path=db_path)
        for task_id in planned["fanout_task_ids"]
    ]
    assert all(task is not None for task in tasks)
    return planned, [task for task in tasks if task is not None]


@pytest.mark.parametrize("mode", ["lit_and_tools", "lit_only", "no_lit"])
async def test_graph_and_durable_contracts_keep_the_same_results(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    run = store.create_run("Generation contract", "standard", "engine", {})
    state = _generation_state(run.id, mode)
    strategies, expansion_calls = _install_strategies(monkeypatch)
    plan = await prepare_generation(state)
    graph = await coordinator.generate_hypotheses(state)
    graph_calls = list(strategies.calls)
    strategies.calls.clear()
    planned, tasks = await _schedule_generation(state, isolated_db)

    assert len(tasks) == (5 if mode == "lit_and_tools" else 7)
    seq = planned["checkpoint_seq"]
    for task in tasks:
        inputs = task.inputs
        assert task.idempotency_key == (
            f"generation:{inputs['strategy']}:{seq}:"
            f"{inputs['strategy_index']}:{inputs['count']}"
        )
        assert inputs["reference_sources"] == plan.reference_index.sources
        assert inputs["reference_text"] == plan.reference_index.text
        assert inputs["literature"] == plan.literature
        assert task.priority == 87
        assert len(task.dependencies) == 1
    aggregate = store.get_task(
        planned["aggregate_task_id"], db_path=isolated_db
    )
    assert aggregate is not None
    assert aggregate.inputs["counts"] == dataclasses.asdict(plan.counts)
    assert aggregate.dependencies == tuple(task.id for task in tasks)
    assert aggregate.idempotency_key == f"generation:aggregate:{seq}"

    for _ in tasks:
        leased = store.claim_task(
            "strategy", run_id=run.id, db_path=isolated_db
        )
        assert leased is not None
        result = await fanout.execute_generation_strategy(
            leased, db_path=isolated_db
        )
        assert store.complete_task(
            leased.id, "strategy", result, db_path=isolated_db
        )
    durable_calls = list(strategies.calls)
    leased = store.claim_task("aggregate", run_id=run.id, db_path=isolated_db)
    assert leased is not None and leased.id == aggregate.id
    result = await aggregates.execute_generation_aggregate(
        leased, db_path=isolated_db
    )
    assert result["failed_strategies"] == 0
    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    committed = restore_workflow_state(checkpoint["state"])

    graph_hypotheses = graph["hypotheses"].items
    assert graph["hypothesis_count"] == 8
    assert graph["llm_call_count"] == (13 if mode == "lit_and_tools" else 15)
    expected_methods = (
        ["literature_tools"] * 3 + ["debate"] * 3 + ["assumptions"] * 2
        if mode == "lit_and_tools"
        else ["debate"] * 6 + ["assumptions"] * 2
    )
    assert [
        hyp.enrichments["base_generation_method"] for hyp in graph_hypotheses
    ] == expected_methods
    assert [hyp.to_dict() for hyp in committed["hypotheses"][1:]] == [
        hyp.to_dict() for hyp in graph_hypotheses
    ]
    assert committed["hypotheses"][0].id == "parent"
    assert committed["debate_transcripts"] == graph["debate_transcripts"]
    assert committed["metrics"].llm_calls == graph["llm_call_count"]
    assert committed["metrics"].hypothesis_count == graph["hypothesis_count"]
    assert all(
        hyp.creation_iteration == 2
        and hyp.generation_method == GenerationMethod.RESEARCH_EXPANSION
        and hyp.parent_id is None
        and "base_generation_method" in hyp.enrichments
        for hyp in graph_hypotheses
    )
    assert expansion_calls == [run.id]  # graph-only research remains graph-only

    graph_assumptions = next(
        call for call in graph_calls if call["strategy"] == "assumptions"
    )
    durable_assumptions = next(
        call for call in durable_calls if call["strategy"] == "assumptions"
    )
    assert graph_assumptions["literature"] == plan.literature
    assert graph_assumptions["refs"].sources == plan.reference_index.sources
    assert durable_assumptions["literature"] is None
    assert durable_assumptions["refs"] is None
    debate_calls = [
        call for call in durable_calls if call["strategy"].startswith("debate")
    ]
    for call in debate_calls:
        assert call["refs"].sources == (
            plan.reference_index.sources if mode != "no_lit" else {}
        )
        assert call["literature"] == (
            plan.literature if mode != "no_lit" else None
        )
    assert sorted(
        (call["position"].debate_index, call["position"].total_debates)
        for call in debate_calls
    ) == [(index, len(debate_calls)) for index in range(len(debate_calls))]


async def test_durable_aggregate_preserves_successes_after_a_strategy_fails(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = store.create_run("Partial generation", "standard", "engine", {})
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
            # Persisted successful-item snapshots sum across independent
            # tasks. A failed item's unreported spend remains excluded.
            result["skills_used"] = {"pubmed": 1}
            result["model_usage"] = {
                "generate:fixture": {"calls": 1, "prompt_tokens": 10}
            }
            assert store.complete_task(
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
    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
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


async def test_pre_diversity_tasks_still_execute_as_one_debate(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = store.create_run("Legacy generation task", "standard", "engine", {})
    state = _generation_state(run.id, "no_lit")
    strategies, _ = _install_strategies(monkeypatch)
    _, tasks = await _schedule_generation(state, isolated_db)
    task = tasks[0]
    legacy = dataclasses.replace(
        task,
        inputs={
            key: value
            for key, value in task.inputs.items()
            if key not in {"strategy_index", "debate_total"}
        },
    )
    result = await fanout.execute_generation_strategy(
        legacy, db_path=isolated_db
    )
    assert len(result["hypotheses"]) == 1
    position = strategies.calls[0]["position"]
    assert (position.debate_index, position.total_debates) == (0, 1)
