"""Node-level durable task runtime topology and reducer tests."""

from typing import Any

import pytest

from co_scientist import llm_tool_loop
from co_scientist.cache import LLMCache
from co_scientist.llm import CompletionSpec, call_llm
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
from tests._llm_wrapper_fakes import (
    make_completion,
    make_message,
    make_usage,
    patch_acompletion,
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
        ("safety_screen", False, None, "ranking"),
        # Deep verification probes the post-tournament leaders (audit E9),
        # so ranking runs first and the loop point comes after it.
        ("ranking", False, None, "deep_verification"),
        ("deep_verification", False, None, "orchestrator"),
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


async def test_execute_task_node_captures_llm_telemetry_by_phase(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A node's real LLM calls are captured into its committed metrics.

    Drives the actual dispatch boundary (``co_scientist.llm.call_llm`` ->
    ``llm_request._acompletion_within_timeout``) with only the network
    edge faked, the same convention every other engine LLM test uses --
    not a fixture of this feature's own logic. Without
    ``execute_task_node`` scoping telemetry around the handler call (and
    without the dispatch boundary recording it), ``model_usage`` stays the
    all-zero default forever, however many LLM calls a node makes. Uses a
    real (empty, per-test-tmp-dir) ``LLMCache`` rather than
    ``disable_llm_cache`` so the resulting cache-miss telemetry is also
    exercised against genuine cache behavior, not a NullCache stand-in.
    """
    monkeypatch.setattr(
        llm_tool_loop,
        "get_cache",
        lambda: LLMCache(cache_dir=str(tmp_path), enabled=True),
    )
    patch_acompletion(
        monkeypatch,
        [make_completion(make_message("ok"), usage=make_usage(100, 40, 5))],
    )

    async def handler(state: Any) -> dict[str, Any]:
        await call_llm(
            "a prompt", CompletionSpec(model_name="task-runtime-test-model")
        )
        return {"current_iteration": 1}

    monkeypatch.setitem(TASK_NODES, "review", handler)
    committed, _ = await execute_task_node("review", make_state())

    usage = committed["metrics"].model_usage
    assert set(usage) == {"review::task-runtime-test-model"}
    entry = usage["review::task-runtime-test-model"]
    assert entry["calls"] == 1
    assert entry["prompt_tokens"] == 100
    assert entry["completion_tokens"] == 40
    assert entry["reasoning_tokens"] == 5
    assert entry["cache_misses"] == 1
    assert entry["cache_hits"] == 0
    assert entry["latency_seconds"] >= 0
    assert entry["errors"] == {}


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
