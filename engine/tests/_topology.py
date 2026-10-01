"""Read the workflow's successors back off the compiled LangGraph.

The topology tests compare two independent answers to "what runs after this
node?": the durable path's ``next_task_type`` and the graph LangGraph actually
compiled. Reading the second off the compiled builder (not off the declaration
in ``workflow_topology``) is what makes the comparison a test of the wiring
rather than of a table against itself.
"""

from typing import Any

from langgraph.graph import END, START, StateGraph

from co_scientist.generator.graph import (
    _add_workflow_edges,
    _add_workflow_nodes,
)
from co_scientist.scheduling import TaskType
from co_scientist.state import WorkflowState
from tests._state import make_state

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
