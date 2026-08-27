"""What a run loses when it can reach no literature source, said out loud.

Without the MCP server the graph routes around the literature review and
the observation reviews, the deep reviews' own probes find nothing to
search, and evolution grounds nothing. Each of those is a quiet branch
taken correctly: the run completes, the report reads like any other, and
nothing on the record says the ideas in it were never checked against a
paper. That is the failure this module exists to end -- not by changing
what the run does, but by making it a fact the run carries, the same way
a fallback-served section is.

The only thing that survives an MCP outage is a run's own attached
documents, searched in-process. There is no second source behind them:
most runs fall back to nothing, and reporting which of the two actually
applied is the whole point.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

# What stops happening without a reachable literature source, in the
# order a run would have reached it. Every entry is a real branch
# elsewhere in this package, not a category: the first two are routed
# around entirely (``task_runtime``), and the rest each refuse
# themselves on ``mcp_available``.
CAPABILITIES_LOST_WITHOUT_MCP: tuple[str, ...] = (
    "literature_review",
    "observation_review",
    "deep_research",
    "review_evidence",
    "verification_probes",
    "evolution_grounding",
)

# Reason codes. A code rather than a sentence because the app renders
# this and a report should not quote an engine log line.
MCP_UNREACHABLE = "mcp_unreachable"

# What is left to search, worst first. "none" is a real answer.
FLOOR_NONE = "none"
FLOOR_RUN_ATTACHMENTS = "run_attachments"


def resolve_retrieval_degradation(
    *,
    mcp_available: bool,
    private_sources: Sequence[Any] | None,
) -> dict[str, Any] | None:
    """State whether this run can reach literature, and what is left if not.

    Args:
        mcp_available: Whether the MCP server answered its availability
            probe. Every network literature source in the shipped tool
            config is served through it, so this one flag decides all of
            them together.
        private_sources: The run's own attached documents, as the app
            passes them in (``context_enrichment_sources``). These are
            searched in-process and survive the outage.

    Returns:
        The degradation as plain JSON-safe data, or None when the run
        can retrieve normally -- which callers read as "nothing to
        report", never as an error.
    """
    if mcp_available:
        return None
    return {
        "reason": MCP_UNREACHABLE,
        "lost": list(CAPABILITIES_LOST_WITHOUT_MCP),
        "floor": FLOOR_RUN_ATTACHMENTS if private_sources else FLOOR_NONE,
    }
