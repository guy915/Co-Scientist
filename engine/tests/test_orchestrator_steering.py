"""The orchestrator consumes durable high-priority steering (SSR §5).

When steering is pending, the scheduler schedules a high-priority GENERATE to
incorporate it, and the orchestrator clears the flag so the same message is not
re-triggered on the next loop.
"""

import asyncio

from co_scientist.nodes.orchestrator import orchestrator_node
from co_scientist.scheduling import TaskType
from co_scientist.state import WorkflowState
from tests._state import make_hypothesis, make_state


def _state_with_steering(pending: bool) -> WorkflowState:
    # A healthy, reviewed pool so nothing else forces the decision; only the
    # steering flag should change what the orchestrator schedules.
    hyps = [make_hypothesis(f"h{i}", elo_rating=1200) for i in range(4)]
    return make_state(
        hypotheses=hyps,
        pending_steering=pending,
        current_iteration=1,
    )


def test_pending_steering_schedules_generate_and_clears_flag() -> None:
    delta = asyncio.run(orchestrator_node(_state_with_steering(True)))
    assert delta["next_task"] == TaskType.GENERATE.value
    # The flag is cleared so the loop does not re-trigger on the same steering.
    assert delta["pending_steering"] is False


def test_no_steering_does_not_force_generate_for_steering() -> None:
    delta = asyncio.run(orchestrator_node(_state_with_steering(False)))
    # A healthy reviewed pool without steering does not schedule the
    # steering-driven generate; the reason never mentions steering.
    assert "steering" not in str(delta["messages"]).lower()
    assert delta["pending_steering"] is False
