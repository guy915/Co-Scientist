"""Node-level runtime for independently leased durable scientific tasks.

This module mirrors the workflow topology without invoking a monolithic graph.
Each call executes exactly one specialist node, applies the same state reducers
as LangGraph, and returns the next task type(s) to persist after the checkpoint
commit. The app worker owns leases and transactions; this module owns scientific
state semantics.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from langgraph.graph import add_messages

from co_scientist.agents import NODE_REGISTRY
from co_scientist.generator.graph import _TASK_ROUTES as _ORCHESTRATOR_ROUTES
from co_scientist.models import merge_metrics
from co_scientist.state import WorkflowState, deduplicate_hypotheses

TaskNode = Callable[[WorkflowState], Awaitable[dict[str, Any]]]

# Task-name -> node callable, derived from the canonical node registry so the
# durable task runtime can never drift from the graph's registered nodes.
TASK_NODES: dict[str, TaskNode] = {
    key: spec.node for key, spec in NODE_REGISTRY.items()
}


def apply_task_update(
    state: WorkflowState, update: dict[str, Any]
) -> WorkflowState:
    """Apply one node result with the reducers declared by WorkflowState."""
    merged: dict[str, Any] = dict(state)
    for key, value in update.items():
        if key == "hypotheses":
            merged[key] = deduplicate_hypotheses(
                state.get("hypotheses", []), value
            )
        elif key == "metrics":
            merged[key] = merge_metrics(state["metrics"], value)
        elif key == "messages":
            merged[key] = add_messages(
                cast(Any, state.get("messages", [])), cast(Any, value)
            )
        else:
            merged[key] = value
    return merged  # type: ignore[return-value]


def _route_after_supervisor(state: WorkflowState) -> str:
    """Route to literature review when MCP is available, else generate."""
    return "literature_review" if state.get("mcp_available") else "generate"


def _route_after_generate(state: WorkflowState) -> str:
    """Route to reflection when MCP is available, else straight to review."""
    return "reflection" if state.get("mcp_available") else "review"


def _route_after_orchestrator(state: WorkflowState) -> str:
    """Resolve the orchestrator's chosen next task to a task node name."""
    return _ORCHESTRATOR_ROUTES.get(
        state.get("next_task") or "terminate", "research_overview"
    )


# Successor for each completed node: a fixed task name, ``None`` for the
# terminal node, or a resolver called with the committed state when the
# successor depends on live state (MCP availability, orchestrator choice).
_NEXT_TASK_ROUTES: dict[
    str, str | None | Callable[[WorkflowState], str | None]
] = {
    "supervisor": _route_after_supervisor,
    "literature_review": "generate",
    "generate": _route_after_generate,
    "reflection": "review",
    "review": "comprehensive_reflection",
    "comprehensive_reflection": "safety_screen",
    "safety_screen": "deep_verification",
    "deep_verification": "ranking",
    "ranking": "orchestrator",
    "proximity": "orchestrator",
    "meta_review": "evolve",
    "evolve": "review",
    "orchestrator": _route_after_orchestrator,
    "research_overview": None,
}


def next_task_type(completed: str, state: WorkflowState) -> str | None:
    """Return the next specialist task after one committed node.

    Args:
        completed: The task node that just committed.
        state: The workflow state after that node's update was applied.

    Returns:
        The next task node's name, or None once the workflow is terminal.

    Raises:
        ValueError: If ``completed`` is not a recognized task node.
    """
    if completed not in _NEXT_TASK_ROUTES:
        raise ValueError(f"unsupported completed task node: {completed}")
    route = _NEXT_TASK_ROUTES[completed]
    return route(state) if callable(route) else route


async def execute_task_node(
    task_type: str, state: WorkflowState
) -> tuple[WorkflowState, str | None]:
    """Execute one specialist node and return committed state plus successor."""
    try:
        handler = TASK_NODES[task_type]
    except KeyError as exc:
        raise ValueError(f"unsupported task node: {task_type}") from exc
    update = await handler(state)
    committed = apply_task_update(state, update)
    return committed, next_task_type(task_type, committed)


__all__ = [
    "TASK_NODES",
    "apply_task_update",
    "execute_task_node",
    "next_task_type",
]
