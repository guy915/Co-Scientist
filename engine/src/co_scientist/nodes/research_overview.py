"""Research-overview node - terminal synthesis into a roadmap + NIH aims."""

import logging
from typing import Any

from co_scientist.constants import MEDIUM_TEMPERATURE
from co_scientist.constants import PROGRESS_RESEARCH_OVERVIEW_COMPLETE
from co_scientist.constants import PROGRESS_RESEARCH_OVERVIEW_START
from co_scientist.constants import RESEARCH_OVERVIEW_TOP_K
from co_scientist.constants import THINKING_MAX_TOKENS
from co_scientist.llm import call_llm_json
from co_scientist.models import create_metrics_update
from co_scientist.models import phase_message
from co_scientist.models import rank_by_elo
from co_scientist.nodes.progress import emit_progress
from co_scientist.prompts import get_research_overview_prompt
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


async def research_overview_node(state: WorkflowState) -> dict[str, Any]:
    """Synthesize the top-k hypotheses into an overview + NIH Specific Aims.

    Args:
        state: The current workflow state.

    Returns:
        A state delta carrying the research overview, metrics, and a message.
    """
    hypotheses = state.get("hypotheses", [])
    if not hypotheses:
        # Nothing survived to this terminal node (e.g. an earlier failure
        # or all hypotheses were pruned); skip the LLM call rather than
        # synthesizing an overview from an empty pool.
        return {"research_overview": {}}

    # Re-rank defensively (do not assume the incoming list is already
    # Elo-sorted) and keep only the strongest RESEARCH_OVERVIEW_TOP_K (10)
    # hypotheses so the synthesis prompt stays a bounded size.
    ranked = rank_by_elo(hypotheses)
    top = ranked[:RESEARCH_OVERVIEW_TOP_K]
    summary = "\n".join(
        f"{i + 1}. (Elo {h.elo_rating}) {h.text}" for i, h in enumerate(top))

    await emit_progress(state, "research_overview_start",
                        "Synthesizing research overview...",
                        PROGRESS_RESEARCH_OVERVIEW_START)

    # meta_review and the durable run guidance fields steer the synthesis
    # toward the same strategic themes used elsewhere in the workflow.
    prompt, schema = get_research_overview_prompt(
        research_goal=state["research_goal"],
        hypotheses_summary=summary,
        meta_review=state.get("meta_review"),
        tool_registry=state.get("tool_registry"),
        run_setup_guidance=state.get("run_setup_guidance"),
        run_focus_guidance=state.get("run_focus_guidance"),
    )
    # Uses the supervisor model (strategic synthesis, not a worker task)
    # and the larger THINKING_MAX_TOKENS budget, since the roadmap and
    # Specific Aims sections can each be long structured output.
    response = await call_llm_json(
        prompt=prompt,
        model_name=state["supervisor_model_name"],
        max_tokens=THINKING_MAX_TOKENS,
        temperature=MEDIUM_TEMPERATURE,
        json_schema=schema,
    )

    # Default to empty dicts if the LLM omits either section, so
    # downstream consumers always see a well-formed research_overview
    # shape rather than a missing key.
    research_overview = {
        "overview": response.get("overview", {}),
        "nih_specific_aims": response.get("nih_specific_aims", {}),
    }

    await emit_progress(state, "research_overview_complete",
                        "Research overview ready",
                        PROGRESS_RESEARCH_OVERVIEW_COMPLETE)

    logger.info("Research overview complete")
    # Only the delta (one LLM call) is passed here; merge_metrics (models.py)
    # adds it to the existing cumulative totals in state.
    metrics = create_metrics_update(llm_calls_delta=1)
    # research_overview has no reducer annotation in state.py, so this is a
    # plain overwrite -- appropriate since this node runs once, terminally.
    return {
        "research_overview":
            research_overview,
        "metrics":
            metrics,
        "messages":
            phase_message("research_overview",
                          "Synthesized research overview and Specific Aims"),
    }
