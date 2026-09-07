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
from co_scientist.generator.graph import (
    _route_after_meta_review as _route_after_meta_review,
)
from co_scientist.generator.graph import _route_next_task
from co_scientist.llm_telemetry import scoped_telemetry
from co_scientist.models import create_metrics_update, merge_metrics
from co_scientist.state import (
    WorkflowState,
    accumulate_matchups,
    deduplicate_hypotheses,
)
from co_scientist.state_reducers import accumulate_research_ledgers

TaskNode = Callable[[WorkflowState], Awaitable[dict[str, Any]]]

# Task-name -> node callable, derived from the canonical node registry so the
# durable task runtime can never drift from the graph's registered nodes.
TASK_NODES: dict[str, TaskNode] = {
    key: spec.node for key, spec in NODE_REGISTRY.items()
}


def apply_task_update(
    state: WorkflowState, update: dict[str, Any]
) -> WorkflowState:
    """Apply one node result with the reducers declared by WorkflowState.

    This is a hand-written mirror of the ``Annotated[T, reducer]`` channels
    on ``WorkflowState``, not a reading of them: the durable path never
    invokes the graph, so LangGraph never applies them here. Every channel
    absent from the table below silently falls through to last-write-wins.

    **Adding a reducer to WorkflowState means adding it here too.**
    ``tournament_matchups`` was annotated on the state but missing from this
    table, so on the durable path -- the only path production runs -- each
    tournament's matchups overwrote the previous cycle's instead of
    accumulating, and every run persisted a single cycle of Elo history.
    """
    merged: dict[str, Any] = dict(state)
    for key, value in update.items():
        reducer = _CHANNEL_REDUCERS.get(key)
        if reducer is None:
            merged[key] = value
            continue
        merged[key] = reducer(state.get(key), value)
    return merged  # type: ignore[return-value]


def _reduce_messages(existing: Any, value: Any) -> Any:
    """Apply LangGraph's id-based message append with the runtime's casts."""
    return add_messages(cast(Any, existing or []), cast(Any, value))


# The reducer for each Annotated channel on WorkflowState. Kept as a table
# rather than a branch chain so the set of mirrored channels is one readable
# list to diff against the state definition -- see apply_task_update.
_CHANNEL_REDUCERS: dict[str, Callable[[Any, Any], Any]] = {
    "hypotheses": lambda existing, value: deduplicate_hypotheses(
        existing or [], value
    ),
    "metrics": merge_metrics,
    "messages": _reduce_messages,
    "tournament_matchups": lambda existing, value: accumulate_matchups(
        existing or [], value
    ),
    "research_ledgers": lambda existing, value: accumulate_research_ledgers(
        existing or [], value
    ),
}


def _route_after_supervisor(state: WorkflowState) -> str:
    """Route to literature review when MCP is available, else generate."""
    return "literature_review" if state.get("mcp_available") else "generate"


def _route_after_generate(state: WorkflowState) -> str:
    """Route to reflection when MCP is available, else straight to review."""
    return "reflection" if state.get("mcp_available") else "review"


def _route_after_orchestrator(state: WorkflowState) -> str:
    """Resolve the orchestrator's chosen next task to a task node name.

    Delegates to the graph's own conditional-edge function rather than
    repeating its lookup: the decision may also carry a stacked companion
    that runs ahead of the chosen task (listing 01's independent ``IF``s,
    ``scheduling.policy.stack_companions``), and a second implementation
    of that rule here would apply on one execution path only.
    """
    return _route_next_task(state)


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
    "safety_screen": "ranking",
    # Deep verification probes the post-tournament leaders (audit E9):
    # after ranking, so the Elo ordering it selects by is the tournament's
    # rather than the all-tied pool order of a pre-ranking pass.
    "ranking": "deep_verification",
    "deep_verification": "orchestrator",
    "proximity": "orchestrator",
    # Meta-review is EVOLVE's prefix *and* a periodic task of its own
    # (listing 01 L60-63), so its successor is the graph's own conditional
    # edge function rather than a fixed route -- imported rather than
    # restated so the durable path cannot answer this differently.
    "meta_review": _route_after_meta_review,
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
    # A halt written by the mid-flight safety monitor (J6) ends the run from
    # whichever node observed it, rather than letting the rest of the cycle
    # run and stopping only at the next orchestrator loop point. The
    # scheduler's own safety stop still covers the graph path, which has no
    # equivalent of this table.
    if state.get("safety_blocked"):
        return None
    route = _NEXT_TASK_ROUTES[completed]
    return route(state) if callable(route) else route


# Nodes whose real successor is decided only once their own execution
# commits: the fan-out family (its aggregate is created dynamically, at a
# size unknown until the node runs) plus the orchestrator (whose successor
# is the adaptive decision made during its own run, never a fixed route --
# see _route_after_orchestrator). A portfolio plan may include one of these
# as its last entry, but must never resolve what follows it (finding F4).
FANNING_NODES = frozenset(
    {
        "generate",
        "ranking",
        "review",
        "comprehensive_reflection",
        "deep_verification",
    }
)
_PORTFOLIO_STOP_NODES = FANNING_NODES | {"orchestrator"}

# The longest deterministic run observed in this table today is three hops
# (meta_review -> evolve -> review); this leaves headroom without letting a
# future routing change walk unbounded.
_MAX_PORTFOLIO_DEPTH = 4

# Resolver routes that read live state instead of naming a fixed successor,
# keyed by the completed node, mapped to the state key that must already be
# present for a portfolio walk to resolve them ahead of that node's own
# execution. Absent means walkable only once the node commits for real.
_RESOLVER_REQUIRES: dict[str, str] = {
    "supervisor": "mcp_available",
    "generate": "mcp_available",
    # Meta-review's successor is the orchestrator decision that scheduled
    # it; a plan built before that decision exists must not guess evolve.
    "meta_review": "next_task",
}


def _resolve_walkable_hop(current: str, state: WorkflowState) -> str | None:
    """Resolve one portfolio hop, or None where it cannot be known yet.

    Mirrors the lookup inside ``next_task_type`` for a state-dependent
    resolver, but refuses to guess: a resolver named in
    ``_RESOLVER_REQUIRES`` only resolves once its state key is present, so
    a plan built before that key exists stops there rather than walking
    the falsy branch of a route that has not actually been decided.
    """
    required = _RESOLVER_REQUIRES.get(current)
    if required is not None and required not in state:
        return None
    route = _NEXT_TASK_ROUTES.get(current)
    if route is None:
        return None
    return route(state) if callable(route) else route


def plan_portfolio(start: str, state: WorkflowState) -> list[str]:
    """Return the deterministic node run starting at ``start`` (finding F4).

    Execution otherwise enqueues one successor at a time even across a run
    of nodes whose outcome the route table already fixes. This walks
    ``_NEXT_TASK_ROUTES`` forward from ``start`` using only state already
    committed, stopping at a fanning node (its own successor cannot be
    known until its dynamically sized fan-out aggregate commits), at
    ``orchestrator`` (an adaptive decision made during its own run, never
    resolved ahead of it), at the terminal node, at an unresolvable
    resolver route, or after ``_MAX_PORTFOLIO_DEPTH`` hops -- whichever
    comes first. ``start`` is always included, even when it is itself a
    stop node, so a caller never special-cases a portfolio of one.

    Args:
        start: The node about to be scheduled.
        state: Workflow state committed so far. Read only.

    Returns:
        The deterministic chain from ``start``, one to
        ``_MAX_PORTFOLIO_DEPTH`` entries long.
    """
    chain = [start]
    current = start
    while (
        current not in _PORTFOLIO_STOP_NODES
        and len(chain) < _MAX_PORTFOLIO_DEPTH
    ):
        next_hop = _resolve_walkable_hop(current, state)
        if next_hop is None:
            break
        chain.append(next_hop)
        current = next_hop
    return chain


def _fold_telemetry_into_update(
    update: dict[str, Any], usage: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Merge one node's captured LLM telemetry into its state update.

    ``handler`` below may already return its own "metrics" delta
    (llm_calls, phase_times, ...); this folds in the token/cost/latency
    delta ``scoped_telemetry`` captured during that same call, using the
    same reducer WorkflowState already merges concurrent node metrics
    with -- so a node that sets no "metrics" key at all still gets one.

    Args:
        update: The node's own state-update dict, returned unmodified when
            there was no telemetry to fold in.
        usage: The (phase, model) usage snapshot captured during the
            node's execution.

    Returns:
        ``update``, with "metrics" replaced by the merge of its own value
        (if any) and the captured telemetry.
    """
    if not usage:
        return update
    telemetry_metrics = create_metrics_update(model_usage=usage)
    existing_metrics = update.get("metrics")
    merged_metrics = (
        merge_metrics(existing_metrics, telemetry_metrics)
        if existing_metrics is not None
        else telemetry_metrics
    )
    return {**update, "metrics": merged_metrics}


async def execute_task_node(
    task_type: str, state: WorkflowState
) -> tuple[WorkflowState, str | None]:
    """Execute one specialist node and return committed state plus successor."""
    try:
        handler = TASK_NODES[task_type]
    except KeyError as exc:
        raise ValueError(f"unsupported task node: {task_type}") from exc
    with scoped_telemetry(task_type) as telemetry:
        update = await handler(state)
    update = _fold_telemetry_into_update(update, telemetry.snapshot())
    committed = apply_task_update(state, update)
    return committed, next_task_type(task_type, committed)


__all__ = [
    "FANNING_NODES",
    "TASK_NODES",
    "apply_task_update",
    "execute_task_node",
    "next_task_type",
    "plan_portfolio",
]
