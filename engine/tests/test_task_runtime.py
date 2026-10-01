"""Node-level durable task runtime topology and reducer tests."""

from typing import Any

import pytest

from co_scientist.cache import LLMCache
from co_scientist.llm import CompletionSpec, call_llm
from co_scientist.llm.tools import loop as tool_loop
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
    plan_portfolio,
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


def test_a_second_researcher_does_not_erase_the_first_one() -> None:
    """The durable path is the only path production runs.

    A reducer annotated on the state but missing from the runtime's own
    table falls through to last-write-wins in silence -- which is how a
    run whose literature review and whose reviews both researched would
    persist one of their ledgers and lose the other's searches.
    """
    state = make_state(research_ledgers=[{"goal": "from the review"}])

    merged = apply_task_update(
        state, {"research_ledgers": [{"goal": "from a hypothesis"}]}
    )

    assert merged["research_ledgers"] == [
        {"goal": "from the review"},
        {"goal": "from a hypothesis"},
    ]


@pytest.mark.parametrize(
    ("completed", "mcp", "decision", "expected"),
    [
        ("supervisor", True, None, "literature_review"),
        ("supervisor", False, None, "generate"),
        ("generate", True, None, "reflection"),
        ("generate", False, None, "review"),
        # Deep verification precedes tournament entry, mirroring
        # ``03-reflection.md``: ReviewHypothesis verifies the hypothesis
        # and only then creates its AddToTournament task.
        ("safety_screen", False, None, "deep_verification"),
        ("deep_verification", False, None, "ranking"),
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


async def test_execute_task_node_captures_llm_telemetry_by_phase(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A node's real LLM calls are captured into its committed metrics.

    Drives the actual dispatch boundary (``co_scientist.llm.call_llm`` ->
    ``llm.request.completion._acompletion_within_timeout``) with only the
    network edge faked, the same convention every other engine LLM test uses --
    not a fixture of this feature's own logic. Without ``execute_task_node``
    scoping telemetry around the handler call (and without the dispatch boundary
    recording it), ``model_usage`` stays the all-zero default forever, however
    many LLM calls a node makes. Uses a real (empty, per-test-tmp-dir)
    ``LLMCache`` rather than ``disable_llm_cache`` so the resulting cache-miss
    telemetry is also exercised against genuine cache behavior, not a NullCache
    stand-in.
    """
    monkeypatch.setattr(
        tool_loop,
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


@pytest.mark.parametrize(
    ("start", "mcp", "expected"),
    [
        # A fanning node is included as the chain's own head but never
        # walked past -- its real successor is unknowable until its
        # dynamically sized fan-out aggregate commits (finding F4).
        ("generate", True, ["generate"]),
        ("ranking", False, ["ranking"]),
        # A resolver route (mcp_available-gated) is walkable once its
        # state key is already committed, and the walk continues past the
        # resolved hop until it reaches a fanning node.
        ("generate", False, ["generate"]),
        ("reflection", False, ["reflection", "review"]),
        ("safety_screen", False, ["safety_screen", "deep_verification"]),
        # orchestrator is a stop node in its own right: never resolved
        # into, and never resolved past when it is reached mid-walk.
        ("orchestrator", False, ["orchestrator"]),
        ("proximity", False, ["proximity", "orchestrator"]),
        ("evolve", False, ["evolve", "review"]),
        # meta_review is now a resolver route too: it is EVOLVE's prefix
        # *and* a periodic task of its own, and only the orchestrator's
        # recorded decision tells the two apart. With no decision in state
        # the walk refuses to guess, exactly as the mcp_available routes do.
        ("meta_review", False, ["meta_review"]),
        # The terminal node has no successor to walk to.
        ("research_overview", False, ["research_overview"]),
    ],
)
def test_plan_portfolio_walks_the_deterministic_tail(
    start: str, mcp: bool, expected: list[str]
) -> None:
    state = make_state(mcp_available=mcp)
    assert plan_portfolio(start, state) == expected


@pytest.mark.parametrize(
    ("next_task", "expected"),
    [
        ("evolve", ["meta_review", "evolve", "review"]),
        ("meta_review", ["meta_review", "orchestrator"]),
    ],
)
def test_plan_portfolio_walks_meta_review_from_the_decision(
    next_task: str, expected: list[str]
) -> None:
    """The decision that scheduled meta-review decides what follows it.

    An EVOLVE runs the critique first and evolves behind it; a standalone
    firing returns to the loop point instead. Walking the falsy branch of
    a route the orchestrator has not decided is what ``_RESOLVER_REQUIRES``
    exists to prevent.
    """
    state = make_state(mcp_available=False)
    state["next_task"] = next_task
    assert plan_portfolio("meta_review", state) == expected


def test_plan_portfolio_walks_supervisor_when_mcp_is_known() -> None:
    """Supervisor's own resolver route is walkable once bootstrap sets it.

    ``mcp_available`` is populated in the very first state a run ever
    commits (finding F4 relies on this key being present, not on
    supervisor having already run).
    """
    state = make_state(mcp_available=True)
    assert plan_portfolio("supervisor", state) == [
        "supervisor",
        "literature_review",
        "generate",
    ]


def test_plan_portfolio_stops_at_an_unresolvable_resolver_route() -> None:
    """A resolver walk never guesses the falsy branch of a missing key.

    Absence, not falsiness, is what stops the walk: guessing the falsy
    branch of a route whose state has genuinely not been decided yet
    would let a portfolio plan a node the run may never actually reach.
    """
    state = make_state()
    del state["mcp_available"]  # type: ignore[misc]
    assert plan_portfolio("supervisor", state) == ["supervisor"]


def test_plan_portfolio_never_calls_the_orchestrator_resolver() -> None:
    """Orchestrator's route reads state a portfolio walk must never guess.

    ``next_task`` carries the *previous* orchestrator cycle's decision
    until the orchestrator itself runs again and overwrites it, so
    resolving through it ahead of time would silently plan off a stale
    decision instead of stopping. A stale value here must not change the
    walk's outcome.
    """
    state = make_state(mcp_available=False, next_task="evolve")
    assert plan_portfolio("proximity", state) == [
        "proximity",
        "orchestrator",
    ]


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
