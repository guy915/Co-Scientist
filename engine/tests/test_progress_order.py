"""Progress checkpoints are monotonic in the durable path's actual order.

Each node emits fixed ``PROGRESS_*`` checkpoints (0-100) as it starts and
completes, and surfaces read them as how far the run has got. They were
once numbered for a pipeline shape that does not exist: deep verification
held 81-84 while proximity held 75-85, yet the durable path runs deep
verification *before* the tournament and proximity *after* it -- so a run
reported 84, then 65, then 75: progress visibly moving backward while the
run made none.

The invariant is stated over a run's first pass -- the order each node
first executes -- because the workflow loops: the orchestrator routes
later work cycles back through earlier nodes, and those revisits
legitimately re-emit the earlier phase's checkpoints (the values name the
phase the run is in, not a completion fraction). The first pass is where
every step is a new phase, so it is where a backward step is a defect.

The order is derived from the durable successor table
(``task_runtime.next_task_type``) rather than restated by hand, so a
topology change re-derives the walk instead of passing silently against a
stale list.
"""

import itertools

from co_scientist import constants
from co_scientist.task_runtime import next_task_type
from tests._state import make_state

# The checkpoints each node emits, in emission order. Nodes absent here are
# covered by _EXEMPT_NODES below; a node the walk visits that is in neither
# fails test_every_walked_node_is_covered_or_exempt.
_NODE_CHECKPOINTS: dict[str, tuple[int, ...]] = {
    "supervisor": (
        constants.PROGRESS_SUPERVISOR_START,
        constants.PROGRESS_SUPERVISOR_COMPLETE,
    ),
    "generate": (
        constants.PROGRESS_GENERATE_START,
        constants.PROGRESS_GENERATE_COMPLETE,
    ),
    "reflection": (
        constants.PROGRESS_REFLECTION_START,
        constants.PROGRESS_REFLECTION_COMPLETE,
    ),
    "review": (
        constants.PROGRESS_REVIEW_START,
        constants.PROGRESS_REVIEW_COMPLETE,
    ),
    "safety_screen": (
        constants.PROGRESS_SAFETY_SCREEN_START,
        constants.PROGRESS_SAFETY_SCREEN_COMPLETE,
    ),
    "deep_verification": (
        constants.PROGRESS_DEEP_VERIFICATION_START,
        constants.PROGRESS_DEEP_VERIFICATION_COMPLETE,
    ),
    "ranking": (
        constants.PROGRESS_TOURNAMENT_START,
        constants.PROGRESS_TOURNAMENT_COMPLETE,
    ),
    "orchestrator": (constants.PROGRESS_ORCHESTRATOR_DECISION,),
    "proximity": (
        constants.PROGRESS_PROXIMITY_START,
        constants.PROGRESS_PROXIMITY_COMPLETE,
    ),
    "meta_review": (
        constants.PROGRESS_META_REVIEW_START,
        constants.PROGRESS_META_REVIEW_COMPLETE,
    ),
    "evolve": (
        constants.PROGRESS_EVOLVE_START,
        constants.PROGRESS_EVOLVE_COMPLETE,
    ),
    "research_overview": (
        constants.PROGRESS_RESEARCH_OVERVIEW_START,
        constants.PROGRESS_RESEARCH_OVERVIEW_COMPLETE,
    ),
}

# Walked nodes that emit no checkpoint from constants.py.
_EXEMPT_NODES = {
    # Emits no PROGRESS_* checkpoint at all.
    "comprehensive_reflection",
    # Its progress values are hardcoded fractions (0.1-0.2) in its node
    # module -- a 0-1 vs 0-100 scale mismatch that predates this invariant
    # and lives outside constants.py, so it cannot join the walk yet.
    "literature_review",
}


def _first_pass_order(mcp_available: bool) -> list[str]:
    """The order a run's nodes first execute, from the successor table.

    Walks ``next_task_type`` the way the durable worker does: the fixed
    pipeline out of the supervisor, then the orchestrator's routing. The
    scheduling policy shapes the loop decisions along the way: a proximity
    refresh is owed -- and therefore scheduled -- before any generate/evolve
    fall-through on the first pass (``policy_checks._check_proximity_refresh``
    outranks the yield choice), and the evolve task enters at meta_review.
    The walk stops where the evolve task re-enters the review pipeline,
    since that is the second cycle's first step, not the first pass's.

    Args:
        mcp_available: Whether the MCP-gated literature-review path is on.

    Returns:
        Node names in first-execution order.
    """
    state = make_state(mcp_available=mcp_available)

    def step(completed: str) -> str:
        """One successor hop, rejecting the terminal None mid-walk."""
        successor = next_task_type(completed, state)
        assert successor is not None
        return successor

    order: list[str] = ["supervisor"]
    node = "supervisor"
    while node != "orchestrator":
        node = step(node)
        order.append(node)

    state["next_task"] = "proximity"
    node = step("orchestrator")
    order.append(node)
    node = step(node)  # proximity -> orchestrator
    order.append(node)

    state["next_task"] = "evolve"
    node = step("orchestrator")
    order.append(node)  # meta_review
    node = step(node)
    order.append(node)  # evolve

    state["next_task"] = "terminate"
    order.append(step("orchestrator"))  # research_overview
    return order


def test_walk_is_the_first_pass_it_claims_to_cover() -> None:
    """Guards the walk itself against a topology change shrinking it.

    If the walk silently dropped part of the first pass, the monotonicity
    test below would keep passing against a shorter order and hide a
    regression in the part it lost.
    """
    assert _first_pass_order(mcp_available=True) == [
        "supervisor",
        "literature_review",
        "generate",
        "reflection",
        "review",
        "comprehensive_reflection",
        "safety_screen",
        "deep_verification",
        "ranking",
        "orchestrator",
        "proximity",
        "orchestrator",
        "meta_review",
        "evolve",
        "research_overview",
    ]
    assert _first_pass_order(mcp_available=False) == [
        "supervisor",
        "generate",
        "review",
        "comprehensive_reflection",
        "safety_screen",
        "deep_verification",
        "ranking",
        "orchestrator",
        "proximity",
        "orchestrator",
        "meta_review",
        "evolve",
        "research_overview",
    ]


def test_first_pass_progress_never_decreases() -> None:
    """Reported progress never moves backward on a run's first pass.

    Every checkpoint each node emits, in the order the durable path first
    reaches them, must be at least the previous one: a smaller value after
    a larger one is the run reporting that it got less far than it just
    said. The walk covers the loop point on both sides of proximity
    (ranking -> orchestrator -> proximity -> orchestrator), so the seams a
    backward-stepping band would trip on are in the sequence twice.
    """
    for mcp_available in (True, False):
        values: list[int] = []
        for node in _first_pass_order(mcp_available):
            values.extend(_NODE_CHECKPOINTS.get(node, ()))

        decreases = [
            (before, after)
            for before, after in itertools.pairwise(values)
            if after < before
        ]
        assert not decreases, (
            f"progress steps backward (mcp_available={mcp_available}): "
            f"{decreases}"
        )


def test_every_checkpoint_starts_before_it_completes() -> None:
    """A node's start checkpoint never reports more than its completion."""
    for name, checkpoints in _NODE_CHECKPOINTS.items():
        if len(checkpoints) < 2:
            continue
        start, complete = checkpoints[0], checkpoints[-1]
        assert start <= complete, name


def test_every_walked_node_is_covered_or_exempt() -> None:
    """A node the walk visits must join the invariant or be exempted by name.

    Without this, a new node with its own checkpoints could enter the
    topology and slip past the monotonicity check simply by not being in
    ``_NODE_CHECKPOINTS``.
    """
    walked = set(_first_pass_order(True)) | set(_first_pass_order(False))
    uncovered = walked - set(_NODE_CHECKPOINTS) - _EXEMPT_NODES
    assert not uncovered, (
        f"walked nodes with no checkpoint coverage and no exemption: "
        f"{sorted(uncovered)}"
    )


def test_every_declared_progress_constant_is_pinned() -> None:
    """A new PROGRESS_* constant must join the invariant, not slip past it.

    Discovery is by value, which a constant sharing a pinned value could
    evade; the walk-coverage test above is the finer guard, and this one
    catches the common case of a new constant at a fresh value.
    """
    pinned = {
        value
        for checkpoints in _NODE_CHECKPOINTS.values()
        for value in checkpoints
    }
    unpinned = {
        name: value
        for name, value in vars(constants).items()
        if name.startswith("PROGRESS_") and value not in pinned
    }
    assert not unpinned, (
        f"PROGRESS_* constants outside the monotonicity invariant: "
        f"{unpinned}. Add their node to _NODE_CHECKPOINTS (or exempt it "
        "by name) so the first-pass walk covers them."
    )
