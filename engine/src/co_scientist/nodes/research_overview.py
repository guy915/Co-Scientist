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
        return {"research_overview": {}}

    ranked = sorted(hypotheses, key=lambda h: h.elo_rating, reverse=True)
    top = ranked[:RESEARCH_OVERVIEW_TOP_K]
    summary = "\n".join(
        f"{i + 1}. (Elo {h.elo_rating}) {h.text}" for i, h in enumerate(top))

    progress_callback = state.get("progress_callback")
    if progress_callback is not None:
        await progress_callback(
            "research_overview_start", {
                "message": "Synthesizing research overview...",
                "progress": PROGRESS_RESEARCH_OVERVIEW_START,
            })

    prompt, schema = get_research_overview_prompt(
        research_goal=state["research_goal"],
        hypotheses_summary=summary,
        meta_review=state.get("meta_review"),
        tool_registry=state.get("tool_registry"),
    )
    response = await call_llm_json(
        prompt=prompt,
        model_name=state["supervisor_model_name"],
        max_tokens=THINKING_MAX_TOKENS,
        temperature=MEDIUM_TEMPERATURE,
        json_schema=schema,
    )

    research_overview = {
        "overview": response.get("overview", {}),
        "nih_specific_aims": response.get("nih_specific_aims", {}),
    }

    if progress_callback is not None:
        await progress_callback(
            "research_overview_complete", {
                "message": "Research overview ready",
                "progress": PROGRESS_RESEARCH_OVERVIEW_COMPLETE,
            })

    logger.info("Research overview complete")
    metrics = create_metrics_update(llm_calls_delta=1)
    return {
        "research_overview":
            research_overview,
        "metrics":
            metrics,
        "messages": [{
            "role": "assistant",
            "content": "Synthesized research overview and Specific Aims",
            "metadata": {
                "phase": "research_overview"
            },
        }],
    }
