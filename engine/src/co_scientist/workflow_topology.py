"""The workflow topology, declared once, for both execution paths.

Two paths run this workflow. The streaming path compiles a LangGraph
(``generator.graph``); the durable path -- the only one production runs --
never invokes the graph and instead asks ``task_runtime.next_task_type``
which node follows each committed one. Both read ``WORKFLOW_ROUTES``, so a
new edge or a re-route reaches both by construction rather than by someone
remembering the second copy. (That copy used to be hand-restated, and a test
listing ten of its rows stood in for the guarantee.)

Each entry names a node's successor as one of three things: a fixed node, a
``LiteratureGated`` pair, or a resolver called with the committed state.

The two paths are **not** edge-for-edge identical, on purpose. Every
divergence is listed here, and each has a test in
``tests/test_workflow_topology.py``:

1. **Literature-review shape.** Whether ``literature_review`` and
   ``reflection`` exist is a *graph build-time* fact (the compiled graph
   either registers those nodes or does not) and a *commit-time* fact on the
   durable path, read from ``state["mcp_available"]`` -- absent meaning off.
   ``LiteratureGated`` is where the table says so; the two selectors live in
   ``generator.graph._add_workflow_edges`` and ``task_runtime.next_task_type``.
   The durable path also still routes ``literature_review -> generate`` and
   ``reflection -> review`` when the flag is off, where the graph has no such
   nodes at all.
2. **Mid-flight safety halt.** ``next_task_type`` ends the run from any node
   once ``state["safety_blocked"]`` is set; the graph has no equivalent (the
   scheduler's own safety stop covers it).
3. **Entry.** The graph enters through a START branch (``_resume_router``:
   a resumed run re-enters at the orchestrator). The durable path has no
   entry edge: the app seeds the first task, and a resumed run simply
   continues from its persisted queue.
4. **Terminal encoding.** A resolver's ``None`` is the durable path's end of
   run and becomes ``END`` on the graph.
5. **Path maps.** LangGraph wants every value a conditional edge may return
   enumerated up front (``generator.graph``'s ``_*_ROUTE_NODES``, derived
   from ``TASK_ROUTES``) and rejects anything outside it at run time. The
   durable path returns the resolver's value unchecked. The two differ only
   for a state the scheduler never produces (meta-review stacked ahead of
   EVOLVE, which already runs it).

What is not shared because it is not topology: ``plan_portfolio``,
``FANNING_NODES`` and the walk's ``_RESOLVER_REQUIRES`` are durable-only
scheduling policy layered over this table, in ``task_runtime``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from co_scientist.scheduling.models import TaskType, stacked_task_values
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


# Maps the scheduler's chosen TaskType value (recorded by orchestrator_node in
# state["next_task"]) to the graph node that begins that task. EVOLVE enters at
# meta_review (its critique feeds evolve); META_REVIEW enters the same node and
# returns to the loop point instead (see route_after_meta_review); TERMINATE
# enters the terminal synthesis. Keep in sync with
# scheduling.policy.ALLOWED_LOOP_TASKS.
TASK_ROUTES: dict[str, str] = {
    "generate": "generate",
    "reflect": "review",
    "rank": "safety_screen",
    "evolve": "meta_review",
    "meta_review": "meta_review",
    "proximity": "proximity",
    # Both firings of the terminal synthesis node: TERMINATE ends the run
    # there, SYNTHESIZE is the periodic one that returns to the loop point
    # (see route_after_research_overview).
    "synthesize": "research_overview",
    "terminate": "research_overview",
}


def _stacked_companions(state: WorkflowState) -> tuple[str, ...]:
    """The companion task values this pass queued ahead of its primary.

    One ``DecideNextSteps`` pass may queue several companions alongside
    the task it chose (``scheduling.policy.stack_companions``). They ride
    the decision's own queue actions, and stacking is an *ordering*: the
    companions run first in this order, the primary behind them, so
    ``next_task`` still names the primary for every consumer that reads
    it. Rewritten in full by every orchestrator pass, so a previous
    pass's companions can never leak into this one.
    """
    return stacked_task_values(state.get("supervisor_queue_actions") or [])


def _companion_successor(state: WorkflowState, after: str) -> str | None:
    """The node to run once the companion ``after`` has committed.

    Returns None when ``after`` did not run as a companion on this pass,
    which is the signal for its own router to fall back to whatever that
    node means outside a stacked pass.
    """
    companions = _stacked_companions(state)
    if after not in companions:
        return None
    remaining = companions[companions.index(after) + 1 :]
    value = remaining[0] if remaining else (state.get("next_task") or "")
    return TASK_ROUTES.get(value, "research_overview")


def route_next_task(state: WorkflowState) -> str:
    """Route to the node that starts the orchestrator's chosen next task.

    Reads ``next_task`` (set by ``orchestrator_node``) and maps it to a node,
    unless the same pass stacked companions ahead of it -- then the first
    of those. Falls back to terminal synthesis if the scheduler produced no
    decision, so the workflow can never dead-end.
    """
    next_task = state.get("next_task") or "terminate"
    companions = _stacked_companions(state)
    node = TASK_ROUTES.get(
        companions[0] if companions else next_task, "research_overview"
    )
    logger.info("Orchestrator routing next_task=%s -> %s", next_task, node)
    return node


# Where meta-review hands over when it was *not* reached as a stacked
# companion: EVOLVE's own prefix falls through to evolve, and a standalone
# periodic firing returns to the loop point. Every other task value is a
# stacked primary and resolves through TASK_ROUTES like any other.
_AFTER_META_REVIEW: dict[str, str] = {
    "evolve": "evolve",
    "meta_review": "orchestrator",
}


def route_after_meta_review(state: WorkflowState) -> str:
    """Route meta-review's successor from the task it was scheduled with.

    Meta-review is three things at once: the prefix node EVOLVE enters at,
    so the critique feeds the evolution prompts; a periodic task of its own
    (listing 01 L60-63); and the stacked companion one pass may queue ahead
    of whatever else it chose. Only the orchestrator's recorded decision
    tells them apart, and it is the same value ``route_next_task`` already
    routed on.
    """
    stacked = _companion_successor(state, TaskType.META_REVIEW.value)
    if stacked is not None:
        return stacked
    next_task = state.get("next_task") or "terminate"
    fixed = _AFTER_META_REVIEW.get(next_task)
    if fixed is not None:
        return fixed
    return TASK_ROUTES.get(next_task, "research_overview")


def route_after_research_overview(state: WorkflowState) -> str | None:
    """Route the overview node's successor from the task it was run for.

    The node is three things: the terminal synthesis every completion path
    ends at (listing 01 L65-69's ``RETURN FinalReport``), the periodic
    firing that listing's own "IF enough time has passed" describes, whose
    interim overview the next generate cycle reads (FIX-6), and the
    stacked companion form of that same periodic branch. Only the
    orchestrator's recorded decision tells them apart, exactly as it does
    for meta-review above.

    ``None`` is the terminal answer and is reachable only from the first
    of the three: ``engine.finalize`` is enqueued as this node's successor
    and nowhere else, so a stacked firing that returned it would end the
    run from the middle of a cycle.
    """
    stacked = _companion_successor(state, TaskType.SYNTHESIZE.value)
    if stacked is not None:
        return stacked
    if state.get("next_task") == TaskType.SYNTHESIZE.value:
        return "orchestrator"
    return None


@dataclass(frozen=True)
class LiteratureGated:
    """A successor that depends on whether the literature-review flow is on.

    ``on`` is the node the full flow continues to; ``off`` is where the
    simplified flow skips to. Every ``on`` target is a node that exists only
    when the flow is on (``literature_review_nodes``), so the gated node set
    is read off the table rather than listed beside it.
    """

    on: str
    off: str

    def pick(self, enabled: bool) -> str:
        """The successor for the flow shape ``enabled`` selects."""
        return self.on if enabled else self.off


# A resolver is called with the committed state when the successor depends on
# live state. It returns None where the workflow ends.
Resolver = Callable[[WorkflowState], str | None]
Route = str | LiteratureGated | Resolver


# The successor of each completed node, for the full (literature-review-on)
# flow; see the module docstring for how the two paths read it.
WORKFLOW_ROUTES: dict[str, Route] = {
    "supervisor": LiteratureGated(on="literature_review", off="generate"),
    "literature_review": "generate",
    "generate": LiteratureGated(on="reflection", off="review"),
    "reflection": "review",
    "review": "comprehensive_reflection",
    "comprehensive_reflection": "safety_screen",
    # Deep verification precedes tournament entry, mirroring
    # ``03-reflection.md``: ReviewHypothesis performs the deep
    # verification and only then creates that hypothesis's
    # AddToTournament task, so no idea is ranked or bred from before its
    # core assumptions have been probed.
    "safety_screen": "deep_verification",
    "deep_verification": "ranking",
    "ranking": "orchestrator",
    "proximity": "orchestrator",
    # Meta-review is EVOLVE's prefix *and* a periodic task of its own
    # (listing 01 L60-63), so its successor depends on the decision that
    # scheduled it rather than being fixed.
    "meta_review": route_after_meta_review,
    "evolve": "review",
    "orchestrator": route_next_task,
    # The terminal node for a TERMINATE decision, and a loop-point return
    # for the periodic firing (FIX-6).
    "research_overview": route_after_research_overview,
}


def literature_review_nodes() -> frozenset[str]:
    """The nodes that exist only when the literature-review flow is on."""
    return frozenset(
        route.on
        for route in WORKFLOW_ROUTES.values()
        if isinstance(route, LiteratureGated)
    )
