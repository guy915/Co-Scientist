"""Node-level durable task runtime topology and reducer tests."""

from typing import Any

import pytest

from co_scientist.models import (
    Hypothesis,
    MetricDeltas,
    create_metrics_update,
)
from co_scientist.state import AppendHypotheses
from co_scientist.task_runtime import (
    TASK_NODES,
    apply_task_update,
    execute_task_node,
    next_task_type,
)
from tests._state import make_state


def test_apply_task_update_uses_graph_state_reducers() -> None:
    """Task commits append hypotheses and merge metric deltas like LangGraph."""
    state = make_state(hypotheses=[Hypothesis(text="parent")])
    child = Hypothesis(text="child")
    merged = apply_task_update(
        state,
        {
            "hypotheses": AppendHypotheses([child]),
            "metrics": create_metrics_update(deltas=MetricDeltas(llm_calls=2)),
        },
    )
    assert [hypothesis.text for hypothesis in merged["hypotheses"]] == [
        "parent",
        "child",
    ]
    assert merged["metrics"].llm_calls == 2


@pytest.mark.parametrize(
    ("completed", "mcp", "decision", "expected"),
    [
        ("supervisor", True, None, "literature_review"),
        ("supervisor", False, None, "generate"),
        ("generate", True, None, "reflection"),
        ("generate", False, None, "review"),
        ("ranking", False, None, "orchestrator"),
        ("orchestrator", False, "evolve", "meta_review"),
        ("orchestrator", False, "terminate", "research_overview"),
        ("research_overview", False, None, None),
    ],
)
def test_next_task_type_mirrors_graph_topology(
    completed: str,
    mcp: bool,
    decision: str | None,
    expected: str | None,
) -> None:
    state = make_state()
    state["mcp_available"] = mcp
    state["next_task"] = decision
    assert next_task_type(completed, state) == expected


async def test_execute_task_node_runs_only_named_specialist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def handler(state: Any) -> dict[str, Any]:
        calls.append("review")
        return {"current_iteration": 7}

    monkeypatch.setitem(TASK_NODES, "review", handler)
    committed, successor = await execute_task_node("review", make_state())
    assert calls == ["review"]
    assert committed["current_iteration"] == 7
    assert successor == "comprehensive_reflection"


def test_durable_path_accumulates_tournament_matchups() -> None:
    """The durable runtime mirrors reducers by hand, so this can drift.

    ``tournament_matchups`` was annotated on WorkflowState but missing from
    the runtime's table, and the durable path is the only path production
    runs -- so each tournament's matchups overwrote the previous cycle's.
    """
    from co_scientist.task_runtime import apply_task_update

    state = make_state(
        hypotheses=[],
        tournament_matchups=[{"hypothesis_a_id": "a", "hypothesis_b_id": "b"}],
    )

    merged = apply_task_update(
        state,
        {
            "tournament_matchups": [
                {"hypothesis_a_id": "c", "hypothesis_b_id": "d"}
            ]
        },
    )

    assert [m["hypothesis_a_id"] for m in merged["tournament_matchups"]] == [
        "a",
        "c",
    ]
