"""Streaming-state accumulation and result shaping for the generator.

LangGraph's ``astream`` only yields the fields updated by each node, not
the full state, so the streaming path keeps a running cumulative state
across nodes. This module seeds that state, merges each node's incremental
update into it, and shapes both the per-node stream payloads and the final
non-streaming result dict.
"""

import logging
from typing import Any

from co_scientist.models import ExecutionMetrics, merge_metrics
from co_scientist.state import WorkflowState, deduplicate_hypotheses

logger = logging.getLogger(__name__)

# State fields streamed to callers as plain last-write-wins copies. Three
# streamed fields are handled separately in _merge_node_state_into_cumulative:
# hypotheses (combined via the deduplicate_hypotheses reducer, matching the
# compiled graph), metrics (merged across nodes), and supervisor_guidance
# (renamed to research_plan).
_STREAMED_STATE_KEYS = (
    "hypotheses",
    "meta_review",
    "research_overview",
    "tournament_matchups",
    "evolution_details",
    "current_iteration",
    # Persisted weighted proximity graph (Milestone 3).
    "proximity_graph",
    # Adaptive orchestration (Milestone 2): the task ledger and the current
    # routing/termination decision, streamed so clients can show the schedule.
    "task_history",
    "next_task",
    "termination_reason",
    "articles_with_reasoning",
    "literature_review_queries",
    "articles",
    "debate_transcripts",
)

# Streamed keys copied last-write-wins; "hypotheses" is excluded because it
# must go through the same reducer the compiled graph uses, or an explicit
# AppendHypotheses op would leak into the streamed snapshot as-is.
_PLAIN_COPY_STATE_KEYS = tuple(
    key for key in _STREAMED_STATE_KEYS if key != "hypotheses"
)


def _merge_node_state_into_cumulative(
    cumulative_state: dict[str, Any],
    node_state: dict[str, Any],
) -> None:
    """Applies one LangGraph node's incremental update to cumulative state.

    LangGraph's astream only yields the fields updated by each node, not the
    full state, so the caller keeps a running ``cumulative_state`` across the
    stream and merges each node's update into it. Most fields are plain
    last-write-wins copies; two are special-cased: ``supervisor_guidance``
    (renamed to ``research_plan``) and ``metrics`` (merged, not replaced).

    Args:
        cumulative_state: Streaming state accumulated across nodes so far;
            updated in place.
        node_state: The incremental state returned by the node that just ran.
    """
    for key in _PLAIN_COPY_STATE_KEYS:
        if key in node_state:
            cumulative_state[key] = node_state[key]
            logger.debug("updated %s", key)
    # hypotheses go through the same reducer the compiled graph uses, so an
    # AppendHypotheses op is applied (append) rather than stored verbatim.
    if "hypotheses" in node_state:
        cumulative_state["hypotheses"] = deduplicate_hypotheses(
            cumulative_state["hypotheses"], node_state["hypotheses"]
        )
        logger.debug("updated hypotheses")
    if "supervisor_guidance" in node_state:
        cumulative_state["research_plan"] = node_state["supervisor_guidance"]
        logger.debug("updated research_plan")
    if "metrics" in node_state:
        cumulative_state["metrics"] = merge_metrics(
            cumulative_state["metrics"], node_state["metrics"]
        )
        logger.debug(
            "merged metrics: reviews=%s, "
            "tournaments=%s, evolutions=%s, llm_calls=%s",
            cumulative_state["metrics"].reviews_count,
            cumulative_state["metrics"].tournaments_count,
            cumulative_state["metrics"].evolutions_count,
            cumulative_state["metrics"].llm_calls,
        )


def cumulative_stream_state_from(state: dict[str, Any]) -> dict[str, Any]:
    """Seed the cumulative streaming state from a restored workflow state.

    On resume (Milestone 4) the run continues mid-flight, so the streamed
    snapshots must already reflect the restored pool/ledger rather than start
    empty. Begins from the fresh seed and overlays the restored values for
    every streamed key (plus metrics and the derived research_plan).
    """
    cumulative = _initial_cumulative_stream_state()
    for key in _STREAMED_STATE_KEYS:
        if key in state and state[key] is not None:
            cumulative[key] = state[key]
    if isinstance(state.get("metrics"), ExecutionMetrics):
        cumulative["metrics"] = state["metrics"]
    if state.get("supervisor_guidance"):
        cumulative["research_plan"] = state["supervisor_guidance"]
    return cumulative


def _initial_cumulative_stream_state() -> dict[str, Any]:
    """Seeds the cumulative streaming state before any node has run.

    LangGraph's astream only yields the fields updated by each node, not
    the full state, so the caller keeps a running cumulative state across
    the stream; this seeds every field a caller might read before its node
    has run yet. "research_plan" is not in _STREAMED_STATE_KEYS because it
    is derived from supervisor_guidance in
    _merge_node_state_into_cumulative rather than copied directly.

    Returns:
        The initial cumulative streaming state dict.
    """
    return {
        "hypotheses": [],
        "meta_review": {},
        "research_overview": {},
        "research_plan": {},
        "tournament_matchups": [],
        "evolution_details": [],
        "current_iteration": 0,
        "proximity_graph": {},
        "task_history": [],
        "next_task": None,
        "termination_reason": None,
        "metrics": ExecutionMetrics(),
        "articles_with_reasoning": None,
        "literature_review_queries": [],
        "articles": [],
        "debate_transcripts": None,
    }


def _build_stream_state_dict(
    cumulative_state: dict[str, Any],
) -> dict[str, Any]:
    """Shapes cumulative streaming state into a per-node yield payload.

    Args:
        cumulative_state: Streaming state accumulated across nodes so far.

    Returns:
        The dict yielded to the caller alongside the completed node's name.
    """
    metrics = cumulative_state["metrics"]
    state_dict = {key: cumulative_state[key] for key in _STREAMED_STATE_KEYS}
    state_dict.update(
        {
            "hypotheses": [h.to_dict() for h in cumulative_state["hypotheses"]],
            "articles": [a.to_dict() for a in cumulative_state["articles"]],
            "research_plan": cumulative_state["research_plan"],
            "metrics": {
                "hypothesis_count": metrics.hypothesis_count,
                "reviews_count": metrics.reviews_count,
                "tournaments_count": metrics.tournaments_count,
                "evolutions_count": metrics.evolutions_count,
                "llm_calls": metrics.llm_calls,
                # Included so streaming callers see the full
                # ExecutionMetrics, matching _build_generation_result.
                "total_time": metrics.total_time,
                "phase_times": metrics.phase_times,
            },
        }
    )
    return state_dict


def _build_generation_result(
    final_state: WorkflowState,
    execution_time: float,
) -> dict[str, Any]:
    """Formats a completed workflow's final state into the result dict.

    Args:
        final_state: The workflow state returned by the graph's ``ainvoke``.
        execution_time: Wall-clock seconds spent in ``ainvoke``.

    Returns:
        The dictionary returned to callers of ``generate_hypotheses`` when
        ``stream=False``.
    """
    metrics = final_state["metrics"]
    return {
        "hypotheses": [h.to_dict() for h in final_state["hypotheses"]],
        "meta_review": final_state.get("meta_review", {}),
        "research_overview": final_state.get("research_overview", {}),
        "research_plan": final_state.get("supervisor_guidance", {}),
        "tournament_matchups": final_state.get("tournament_matchups", []),
        "evolution_details": final_state.get("evolution_details", []),
        "debate_transcripts": final_state.get("debate_transcripts"),
        # Persisted weighted proximity graph (Milestone 3).
        "proximity_graph": final_state.get("proximity_graph", {}),
        # Adaptive-orchestration ledger and final stop (Milestone 2).
        "task_history": final_state.get("task_history", []),
        "termination_reason": final_state.get("termination_reason"),
        "execution_time": execution_time,
        "metrics": {
            "total_time": execution_time,
            "hypothesis_count": metrics.hypothesis_count,
            "reviews_count": metrics.reviews_count,
            "tournaments_count": metrics.tournaments_count,
            "evolutions_count": metrics.evolutions_count,
            "phase_times": metrics.phase_times,
            "llm_calls": metrics.llm_calls,
        },
    }
