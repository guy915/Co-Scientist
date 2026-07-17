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

from co_scientist.generator.graph import _TASK_ROUTES as _ORCHESTRATOR_ROUTES
from co_scientist.models import merge_metrics
from co_scientist.nodes.comprehensive_reflection import (
    comprehensive_reflection_node,
)
from co_scientist.nodes.deep_verification import deep_verification_node
from co_scientist.nodes.evolve import evolve_node
from co_scientist.nodes.generate import generate_node
from co_scientist.nodes.literature_review import literature_review_node
from co_scientist.nodes.meta_review import meta_review_node
from co_scientist.nodes.orchestrator import orchestrator_node
from co_scientist.nodes.proximity import proximity_node
from co_scientist.nodes.ranking import ranking_node
from co_scientist.nodes.reflection import reflection_node
from co_scientist.nodes.research_overview import research_overview_node
from co_scientist.nodes.review import review_node
from co_scientist.nodes.safety_screen import safety_screen_node
from co_scientist.nodes.supervisor import supervisor_node
from co_scientist.state import WorkflowState, deduplicate_hypotheses

TaskNode = Callable[[WorkflowState], Awaitable[dict[str, Any]]]

TASK_NODES: dict[str, TaskNode] = {
    "supervisor": supervisor_node,
    "literature_review": literature_review_node,
    "generate": generate_node,
    "reflection": reflection_node,
    "review": review_node,
    "comprehensive_reflection": comprehensive_reflection_node,
    "safety_screen": safety_screen_node,
    "deep_verification": deep_verification_node,
    "ranking": ranking_node,
    "orchestrator": orchestrator_node,
    "meta_review": meta_review_node,
    "evolve": evolve_node,
    "proximity": proximity_node,
    "research_overview": research_overview_node,
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


def next_task_type(completed: str, state: WorkflowState) -> str | None:
    """Return the next specialist task after one committed node."""
    if completed == "supervisor":
        return "literature_review" if state.get("mcp_available") else "generate"
    if completed == "literature_review":
        return "generate"
    if completed == "generate":
        return "reflection" if state.get("mcp_available") else "review"
    if completed == "reflection":
        return "review"
    if completed == "review":
        return "comprehensive_reflection"
    if completed == "comprehensive_reflection":
        return "safety_screen"
    if completed == "safety_screen":
        return "deep_verification"
    if completed == "deep_verification":
        return "ranking"
    if completed == "ranking" or completed == "proximity":
        return "orchestrator"
    if completed == "meta_review":
        return "evolve"
    if completed == "evolve":
        return "review"
    if completed == "orchestrator":
        return _ORCHESTRATOR_ROUTES.get(
            state.get("next_task") or "terminate", "research_overview"
        )
    if completed == "research_overview":
        return None
    raise ValueError(f"unsupported completed task node: {completed}")


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
