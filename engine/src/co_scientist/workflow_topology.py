"""Persisted node keys require a migration before renaming."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from co_scientist.scheduling.models import TaskType, stacked_task_values
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


# Maps the scheduler's chosen TaskType value (recorded by orchestrator_node in
# state["next_task"]) to its first durable node. EVOLVE enters at
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
    """Companions precede the primary; next_task keeps its primary identity."""
    return stacked_task_values(state.get("supervisor_queue_actions") or [])


def _companion_successor(state: WorkflowState, after: str) -> str | None:
    """None delegates non-companions to their ordinary route."""
    companions = _stacked_companions(state)
    if after not in companions:
        return None
    remaining = companions[companions.index(after) + 1 :]
    value = remaining[0] if remaining else (state.get("next_task") or "")
    return TASK_ROUTES.get(value, "research_overview")


def route_next_task(state: WorkflowState) -> str:
    """A missing scheduler decision falls back to terminal synthesis."""
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
    """EVOLVE requires critique first; periodic critique returns to the loop."""
    stacked = _companion_successor(state, TaskType.META_REVIEW.value)
    if stacked is not None:
        return stacked
    next_task = state.get("next_task") or "terminate"
    fixed = _AFTER_META_REVIEW.get(next_task)
    if fixed is not None:
        return fixed
    return TASK_ROUTES.get(next_task, "research_overview")


def route_after_research_overview(state: WorkflowState) -> str | None:
    """Only terminal synthesis finalizes; companions must continue."""
    stacked = _companion_successor(state, TaskType.SYNTHESIZE.value)
    if stacked is not None:
        return stacked
    if state.get("next_task") == TaskType.SYNTHESIZE.value:
        return "orchestrator"
    return None


@dataclass(frozen=True)
class LiteratureGated:
    """Committed MCP availability selects the retrieval flow."""

    on: str
    off: str

    def pick(self, enabled: bool) -> str:
        return self.on if enabled else self.off


# A resolver is called with the committed state when the successor depends on
# live state. It returns None where the workflow ends.
Resolver = Callable[[WorkflowState], str | None]
Route = str | LiteratureGated | Resolver


# The successor of each completed node, for the full (literature-review-on)
# flow; state-dependent routes resolve only after their node commits.
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
    return frozenset(
        route.on
        for route in WORKFLOW_ROUTES.values()
        if isinstance(route, LiteratureGated)
    )
