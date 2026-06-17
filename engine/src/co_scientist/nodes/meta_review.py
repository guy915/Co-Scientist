"""Meta-review node - synthesize insights from all reviews."""
# pylint: disable=inconsistent-quotes

import json
import logging
from typing import Any

from co_scientist.constants import (
    THINKING_MAX_TOKENS,
    MEDIUM_TEMPERATURE,
    PROGRESS_META_REVIEW_START,
    PROGRESS_META_REVIEW_COMPLETE,
)
from co_scientist.llm import call_llm_json
from co_scientist.models import create_metrics_update
from co_scientist.prompts import get_meta_review_prompt
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


async def meta_review_node(state: WorkflowState) -> dict[str, Any]:
    """Synthesizes insights from all reviews across all hypotheses.

    This node analyzes all the reviews collectively to identify:
    - Common strengths and weaknesses
    - Promising research directions
    - Areas needing improvement
    - Strategic guidance for evolution

    Args:
        state: Current workflow state

    Returns:
        Dictionary with updated state fields (meta_review)
    """
    hypotheses = state["hypotheses"]
    logger.info("Synthesizing meta-review from %s hypotheses", len(hypotheses))

    # Emit progress
    progress_callback = state.get("progress_callback")
    if progress_callback is not None:
        await progress_callback(
            "meta_review_start",
            {
                "message": "Synthesizing insights from all reviews...",
                "progress": PROGRESS_META_REVIEW_START,
            },
        )

    # Collect all reviews
    all_reviews = []
    for i, hyp in enumerate(hypotheses):
        if not hyp.reviews:
            continue

        # Get the latest review for each hypothesis
        latest_review = hyp.reviews[-1]

        review_data = {
            "hypothesis_index":
                i,
            "hypothesis_text":
                hyp.text[:200] + "..." if len(hyp.text) > 200 else hyp.text,
            "overall_score":
                latest_review.overall_score,
            "review_summary":
                latest_review.review_summary,
            "scores":
                latest_review.scores,
            "constructive_feedback":
                latest_review.constructive_feedback,
            "elo_rating":
                hyp.elo_rating,
            "win_loss_record":
                f"{hyp.win_count}W-{hyp.loss_count}L",
        }
        all_reviews.append(review_data)

    if not all_reviews:
        logger.warning("No reviews available for meta-review")
        return {
            "meta_review": {
                "summary": "No reviews available",
                "common_strengths": [],
                "common_weaknesses": [],
                "strategic_recommendations": [],
            }
        }

    # Format all reviews for the LLM
    reviews_text = json.dumps(all_reviews, indent=2)

    # Get supervisor guidance from state
    supervisor_guidance = state.get("supervisor_guidance")

    # Call LLM to synthesize meta-review
    prompt, schema = get_meta_review_prompt(
        research_goal=state["research_goal"],
        all_reviews=reviews_text,
        supervisor_guidance=supervisor_guidance,
        instructions=None,  # for the future
        tool_registry=state.get("tool_registry"),
    )

    # Save prompt to disk for debugging
    from co_scientist.prompts import save_prompt_to_disk  # pylint: disable=import-outside-toplevel

    save_prompt_to_disk(
        run_id=state.get("run_id", "unknown"),
        prompt_name="meta_review",
        content=prompt,
        metadata={
            "prompt_length_chars": len(prompt),
            "hypotheses_count": len(hypotheses),
            "reviews_count": len(all_reviews),
        },
    )

    response = await call_llm_json(
        prompt=prompt,
        model_name=state["supervisor_model_name"],
        max_tokens=THINKING_MAX_TOKENS,  # more space to aggregate all reviews
        temperature=MEDIUM_TEMPERATURE,
        json_schema=schema,
    )

    # Schema returns recurring_themes as objects {theme, description,
    # frequency}; flatten to strings.
    recurring_themes = response.get("recurring_themes", [])
    emerging_themes = [
        t["theme"] if isinstance(t, dict) else str(t) for t in recurring_themes
    ]

    # process_assessment covers generation/review/evolution process notes.
    process = response.get("process_assessment") or {}

    meta_review = {
        "summary":
            response.get("meta_review_summary", ""),
        "common_strengths":
            response.get("strengths", []),
        "common_weaknesses":
            response.get("weaknesses", []),
        "emerging_themes":
            emerging_themes,
        "strategic_recommendations":
            response.get("strategic_recommendations", []),
        "diversity_assessment":
            process.get("generation_process", ""),
        "top_performers_analysis":
            process.get("review_process", ""),
        "areas_for_improvement":
            response.get("weaknesses", []),
    }

    logger.info("Meta-review complete")
    logger.info("Common strengths: %s", len(meta_review['common_strengths']))
    logger.info("Strategic recommendations: %s",
                len(meta_review['strategic_recommendations']))

    # Emit progress
    progress_callback = state.get("progress_callback")
    if progress_callback is not None:
        await progress_callback(
            "meta_review_complete",
            {
                "message":
                    "Meta-review synthesis complete",
                "progress":
                    PROGRESS_META_REVIEW_COMPLETE,
                "strengths_count":
                    len(meta_review["common_strengths"]),
                "recommendations_count":
                    len(meta_review["strategic_recommendations"]),
            },
        )

    # Update metrics (deltas only, merge_metrics will add to existing state)
    metrics = create_metrics_update(llm_calls_delta=1)

    return {
        "meta_review":
            meta_review,
        "metrics":
            metrics,
        "messages": [{
            "role": "assistant",
            "content": "Synthesized meta-review from all hypotheses",
            "metadata": {
                "phase": "meta_review",
                "themes": len(meta_review.get("emerging_themes", [])),
            },
        }],
    }
