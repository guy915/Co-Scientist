"""Shared streaming-API collector for generator end-to-end suites.

Leading underscore so pytest does not collect this module.
"""

from typing import Any

from co_scientist.generator import HypothesisGenerator


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
