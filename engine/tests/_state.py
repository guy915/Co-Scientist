"""Shared test fixtures for state."""

from __future__ import annotations

from typing import Any, cast

import pytest
from langgraph.graph import END, START, StateGraph

from co_scientist.agents.generation import generate as coordinator
from co_scientist.generator import HypothesisGenerator
from co_scientist.generator.graph import (
    _add_workflow_edges,
    _add_workflow_nodes,
)
from co_scientist.models import (
    Article,
    ExecutionMetrics,
    Hypothesis,
    HypothesisReview,
)
from co_scientist.scheduling import Budget, SchedulerStats, TaskType
from co_scientist.state import WorkflowState


def make_article(title: str = "An article", **overrides: Any) -> Article:
    """Build an Article with the given title and field overrides.

    Args:
        title: The article title.
        **overrides: Any Article dataclass fields to override (e.g. ``authors``,
            ``year``, ``source_id``, ``content``).

    Returns:
        An Article instance.
    """
    fields: dict[str, Any] = {"title": title}
    fields.update(overrides)
    return Article(**fields)


def make_hypothesis(text: str = "a hypothesis", **overrides: Any) -> Hypothesis:
    """Build a Hypothesis with the given text and field overrides.

    Args:
        text: The hypothesis text.
        **overrides: Any Hypothesis dataclass fields to override (e.g.
            ``elo_rating``, ``score``, ``reviews``).

    Returns:
        A Hypothesis instance.
    """
    fields: dict[str, Any] = {"text": text}
    fields.update(overrides)
    return Hypothesis(**fields)


def make_review(**overrides: Any) -> HypothesisReview:
    """Build a HypothesisReview with all six required fields populated.

    Args:
        **overrides: Any HypothesisReview fields to override (e.g.
            ``review_summary``, ``scores``, ``overall_score``).

    Returns:
        A HypothesisReview instance.
    """
    fields: dict[str, Any] = {
        "review_summary": "a solid review",
        "scores": {"novelty": 8, "relevance": 7},
        "safety_ethical_concerns": "none",
        "detailed_feedback": {"novelty": "novel angle"},
        "constructive_feedback": "tighten the experiment",
        "overall_score": 7.5,
    }
    fields.update(overrides)
    return HypothesisReview(**fields)


def _run_and_pool_defaults() -> dict[str, Any]:
    """Run configuration plus the hypothesis-pool / bookkeeping channels."""
    return {
        "research_goal": "test research goal",
        "model_name": "test-model",
        "supervisor_model_name": "test-model",
        "max_iterations": 1,
        "initial_hypotheses_count": 2,
        "evolution_max_count": 2,
        "hypotheses": [],
        "current_iteration": 0,
        "supervisor_guidance": {},
        "meta_review": {},
        "research_overview": None,
        "removed_duplicates": [],
        "tournament_matchups": [],
        "evolution_details": [],
        "safety_decisions": [],
        "held_for_review": [],
        "metrics": ExecutionMetrics(),
        "start_time": 0.0,
        "run_id": "test-run",
        "progress_callback": None,
        "messages": [],
    }


def _input_and_literature_defaults() -> dict[str, Any]:
    """Scientist inputs, literature channels, and runtime feature flags."""
    return {
        "preferences": None,
        "attributes": None,
        "constraints": None,
        "lab_constraints": None,
        "starting_hypotheses": None,
        "literature": None,
        "articles_with_reasoning": None,
        "literature_review_queries": None,
        "articles": None,
        "debate_transcripts": None,
        "mcp_available": False,
        "pubmed_available": False,
        "enable_tool_calling_generation": False,
        "enable_overview_review": False,
        "enable_meta_review": True,
        "generation_strategy": "",
        "dev_test_lit_tools_isolation": False,
        "dev_mode": False,
        "tool_registry": None,
        "context_enrichment_sources": None,
    }


def make_state(**overrides: Any) -> WorkflowState:
    """Build a complete WorkflowState with inert defaults.

    Args:
        **overrides: WorkflowState keys to override (e.g. ``hypotheses``,
            ``model_name``, ``current_iteration``).

    Returns:
        A WorkflowState with every key populated; overrides applied last.
    """
    base: dict[str, Any] = {
        **_run_and_pool_defaults(),
        **_input_and_literature_defaults(),
    }
    base.update(overrides)
    return cast(WorkflowState, base)


class _ToolsRecorder:
    """Records calls to the stubbed ``generate_with_tools`` leaf strategy."""

    def __init__(
        self, hypotheses: list[Hypothesis], llm_calls: int = 0
    ) -> None:
        self._hypotheses = hypotheses
        self.llm_calls = llm_calls
        self.called = False
        self.count: int | None = None

    async def __call__(
        self, _state: Any, count: int, _reference_index: Any
    ) -> tuple[list[Hypothesis], int]:
        self.called = True
        self.count = count
        return list(self._hypotheses), self.llm_calls


class _DebateRecorder:
    """Records calls to the stubbed ``generate_with_debate`` leaf strategy."""

    def __init__(
        self,
        hypotheses: list[Hypothesis],
        transcripts: list[dict[str, Any]],
        llm_calls: int = 0,
    ) -> None:
        self._hypotheses = hypotheses
        self._transcripts = transcripts
        self.llm_calls = llm_calls
        self.called = False
        self.count: int | None = None
        self.articles_with_reasoning: str | None = None

    async def __call__(
        self,
        *,
        state: Any,
        count: int,
        articles_with_reasoning: str | None = None,
        reference_index: Any = None,
    ) -> tuple[list[Hypothesis], list[dict[str, Any]], int]:
        self.called = True
        self.count = count
        self.articles_with_reasoning = articles_with_reasoning
        return list(self._hypotheses), list(self._transcripts), self.llm_calls


class _AssumptionsRecorder:
    """Records calls to the stubbed ``generate_with_assumptions`` leaf."""

    def __init__(
        self, hypotheses: list[Hypothesis], llm_calls: int = 0
    ) -> None:
        self._hypotheses = hypotheses
        self.llm_calls = llm_calls
        self.called = False
        self.count: int | None = None
        self.articles_with_reasoning: str | None = None
        self.reference_index: Any = None

    async def __call__(
        self,
        _state: Any,
        count: int,
        articles_with_reasoning: str | None = None,
        reference_index: Any = None,
    ) -> tuple[list[Hypothesis], int]:
        self.called = True
        self.count = count
        self.articles_with_reasoning = articles_with_reasoning
        self.reference_index = reference_index
        return list(self._hypotheses), self.llm_calls


def _install(
    monkeypatch: pytest.MonkeyPatch,
    tools: _ToolsRecorder,
    debate: _DebateRecorder,
    assumptions: _AssumptionsRecorder | None = None,
) -> None:
    """Patch the leaf strategies on the coordinator's namespace."""
    monkeypatch.setattr(coordinator, "generate_with_tools", tools)
    monkeypatch.setattr(coordinator, "generate_with_debate", debate)
    monkeypatch.setattr(
        coordinator,
        "generate_with_assumptions",
        assumptions or _AssumptionsRecorder([]),
    )


# A generous budget so budget ceilings never fire unless a test sets them.
BUDGET = Budget(max_iterations=5, max_llm_calls=1000, max_tasks=100)


def healthy_stats(**overrides: object) -> SchedulerStats:
    """A mid-run pool with no backlog, adequate coverage, room to iterate."""
    base: dict[str, object] = {
        "pool_size": 6,
        "reviewed_count": 6,
        "unreviewed_count": 0,
        "rankable_count": 6,
        "match_coverage": 3.0,
        "iteration": 1,
        "rank_stable_cycles": 0,
    }
    base.update(overrides)
    return SchedulerStats(**base)  # type: ignore[arg-type]


async def collect_stream_events(
    gen: HypothesisGenerator, goal: str
) -> list[tuple[str, dict[str, Any]]]:
    """Consume the streaming API into a list of (node_name, state) tuples.

    Args:
        gen: The generator whose streaming run is consumed.
        goal: The research goal to run with.

    Returns:
        One ``(node_name, cumulative_state_dict)`` tuple per yielded event.
    """
    events: list[tuple[str, dict[str, Any]]] = []
    async for node_name, state_dict in gen.generate_hypotheses(
        goal,
        opts={"enable_literature_review_node": False},
        stream=True,
    ):
        events.append((node_name, state_dict))
    return events


# Marks a node the compiled graph does not register at all (the
# literature-review nodes in the simplified flow); distinct from ``None``,
# which is the end of the run.
ABSENT = "<absent>"


def build_graph(literature_review: bool) -> StateGraph[Any, Any, Any, Any]:
    """The workflow graph, wired and compiled, in one flow shape.

    Returned as the builder: its ``edges`` and ``branches`` are the wiring
    that was declared, and compiling it proves LangGraph accepts that wiring.
    """
    workflow = StateGraph(WorkflowState)
    _add_workflow_nodes(workflow, literature_review)
    _add_workflow_edges(workflow, literature_review)
    workflow.compile()
    return workflow


def graph_successor(
    graph: StateGraph[Any, Any, Any, Any], node: str, state: WorkflowState
) -> str | None:
    """What the compiled graph runs after ``node`` in ``state``.

    Returns:
        The successor's name, ``None`` where the graph ends, or ``ABSENT``
        when the graph has no such node.

    Raises:
        AssertionError: If the node has anything but exactly one outgoing
            edge (one fixed edge, or one conditional branch).
    """
    if node not in graph.nodes and node != START:
        return ABSENT
    fixed = [target for source, target in graph.edges if source == node]
    branches = list(graph.branches.get(node, {}).values())
    assert len(fixed) + len(branches) == 1, (node, fixed, branches)
    if fixed:
        return fixed[0]
    branch = branches[0]
    chosen: Any = branch.path.invoke(state)
    target = branch.ends[chosen] if branch.ends else chosen
    return None if target == END else str(target)


def _stacked(*companions: str) -> list[dict[str, Any]]:
    return [
        {"action": "enqueue", "task_type": task, "reason": "stacked"}
        for task in companions
    ]


def decision_states() -> list[WorkflowState]:
    """States covering every branch a resolver route reads.

    No decision, each task the orchestrator can record, an unknown task, and
    the passes that stack the periodic companions ahead of a primary. Only
    stackings the scheduler can produce (``scheduling.policy.stack_companions``)
    appear: LangGraph rejects a resolver value outside its path map, and the
    unproducible ones (meta-review stacked ahead of EVOLVE, an overview
    stacked onto its own SYNTHESIZE or onto TERMINATE) are exactly those.
    """
    meta, overview = TaskType.META_REVIEW.value, TaskType.SYNTHESIZE.value
    decisions: list[dict[str, Any]] = [{}, {"next_task": None}]
    decisions += [{"next_task": task.value} for task in TaskType]
    decisions.append({"next_task": "not_a_task"})
    stackings = [
        (TaskType.REFLECT, (meta,)),
        (TaskType.REFLECT, (overview,)),
        (TaskType.REFLECT, (meta, overview)),
        (TaskType.SYNTHESIZE, (meta,)),
    ]
    for primary, companions in stackings:
        decisions.append(
            {
                "next_task": primary.value,
                "supervisor_queue_actions": _stacked(*companions),
            }
        )
    return [make_state(**decision) for decision in decisions]
