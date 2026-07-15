"""Tool-grounded full, simulation, and recurrent Reflection reviews."""

import asyncio
import json
import logging
from dataclasses import asdict
from typing import Any

from co_scientist.agents.reflection.deep_verification import (
    _retrieve_probe_evidence,
    merge_retrieved_articles,
)
from co_scientist.agents.reflection.reflection import analyze_single_hypothesis
from co_scientist.agents.reflection.review_types import (
    ReviewType,
    prompt_name_for,
)
from co_scientist.constants import EXTENDED_MAX_TOKENS, LOW_TEMPERATURE
from co_scientist.llm import call_llm_json
from co_scientist.models import (
    Article,
    Hypothesis,
    create_metrics_update,
    phase_message,
)
from co_scientist.prompts import build_tool_instructions
from co_scientist.prompts._common import _format_meta_review_context
from co_scientist.prompts.loading import load_prompt_with_schema
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


def _prompt_variables(
    state: WorkflowState,
    hypothesis: Hypothesis,
    review_type: ReviewType,
    targeted_articles: list[Article] | None = None,
) -> dict[str, str]:
    """Build disclosed scientific and tool context for one review task."""
    registry = state.get("tool_registry")
    tool_ids = registry.get_tools_for_workflow("reflection") if registry else []
    tool_instructions = build_tool_instructions(tool_ids, registry)
    hypothesis_text = hypothesis.text
    if review_type is ReviewType.RECURRENT:
        tournament = {
            "elo_rating": hypothesis.elo_rating,
            "match_count": hypothesis.total_matches,
            "reviews": [asdict(review) for review in hypothesis.reviews],
        }
        hypothesis_text += (
            "\n\nRecurrent-review context from the growing tournament:\n"
            + json.dumps(tournament, indent=2)
            + "\n\nCross-agent feedback:\n"
            + _format_meta_review_context(state.get("meta_review"))
        )
    evidence = [
        article
        for article in (state.get("articles") or [])
        if article.used_in_analysis and not article.is_retracted
    ]
    evidence.extend(targeted_articles or [])
    evidence_sections = [
        f"[{index + 1}] {article.title}: "
        f"{(article.abstract or article.content or '')[:1800]}"
        for index, article in enumerate(evidence[:12])
    ]
    private_sections = [
        str(source.get("display") or "")[:1800]
        for source in (state.get("context_enrichment_sources") or [])[:4]
    ]
    domain_context = "\n\n".join([*evidence_sections, *private_sections])
    return {
        "research_goal": state["research_goal"],
        "hypothesis_text": hypothesis_text,
        "domain_context": (
            "Evidence available to this review:\n" + domain_context
            if domain_context
            else "No retrieved evidence is available to this review."
        ),
        "tool_instructions": tool_instructions,
    }


async def _run_review(
    state: WorkflowState,
    hypothesis: Hypothesis,
    review_type: ReviewType,
) -> tuple[ReviewType, dict[str, Any] | None]:
    """Execute one independently meaningful Reflection review call."""
    targeted_articles: list[Article] = []
    retrieval_errors: list[str] = []
    retrieval_queries: list[str] = []
    if review_type in {ReviewType.FULL, ReviewType.SIMULATION}:
        retrieval_queries = [
            f"{state['research_goal']} {hypothesis.text}"[:1200]
        ]
        targeted_articles, retrieval_errors = await _retrieve_probe_evidence(
            state, retrieval_queries
        )
    template_type = (
        ReviewType.FULL if review_type is ReviewType.RECURRENT else review_type
    )
    prompt, schema = load_prompt_with_schema(
        prompt_name_for(template_type),
        _prompt_variables(state, hypothesis, review_type, targeted_articles),
    )
    if review_type is ReviewType.RECURRENT:
        prompt = (
            "Perform a recurrent/tournament review. Adapt the full review to "
            "the accumulated reviews, Elo outcomes, recurring issues, and "
            "meta-review feedback below. Identify what changed since the "
            "earlier review.\n\n" + prompt
        )
    try:
        result = await call_llm_json(
            prompt=prompt,
            model_name=state["model_name"],
            max_tokens=EXTENDED_MAX_TOKENS,
            temperature=LOW_TEMPERATURE,
            json_schema=schema,
            run_id=state.get("run_id"),
            prompt_name=f"reflection_{review_type.value}_{hypothesis.id}",
        )
    except Exception as exc:
        logger.error(
            "%s review failed for %s: %s", review_type.value, hypothesis.id, exc
        )
        return review_type, None
    result["retrieval_queries"] = retrieval_queries
    result["retrieval_errors"] = retrieval_errors
    result["retrieved_articles"] = [
        article.to_dict() for article in targeted_articles
    ]
    return review_type, result


async def _review_hypothesis(
    state: WorkflowState, hypothesis: Hypothesis
) -> int:
    """Apply maturity-appropriate reviews to one viable hypothesis."""
    iteration = int(state.get("current_iteration", 0))
    reviews: list[ReviewType] = []
    if ReviewType.FULL.value not in hypothesis.enrichments:
        reviews.extend((ReviewType.FULL, ReviewType.SIMULATION))
    elif iteration > int(
        hypothesis.enrichments.get("recurrent_review_iteration", -1)
    ):
        reviews.append(ReviewType.RECURRENT)
    if not reviews:
        return 0
    results = await asyncio.gather(
        *[
            _run_review(state, hypothesis, review_type)
            for review_type in reviews
        ]
    )
    successful = 0
    for review_type, result in results:
        if result is None:
            continue
        hypothesis.enrichments[review_type.value] = result
        if review_type is ReviewType.RECURRENT:
            hypothesis.enrichments["recurrent_review_iteration"] = iteration
        successful += 1
    state["articles"] = merge_retrieved_articles(
        state.get("articles"), [result for _, result in results]
    )
    return successful


async def _run_missing_observation_reviews(
    state: WorkflowState, hypotheses: list[Hypothesis]
) -> int:
    """Apply observation review to ideas that bypass the initial node."""
    literature = state.get("articles_with_reasoning")
    if not literature:
        return 0
    pending = [h for h in hypotheses if not h.reflection_notes]
    if not pending:
        return 0
    results = await asyncio.gather(
        *[
            analyze_single_hypothesis(
                hypothesis=hypothesis,
                articles_with_reasoning=literature,
                model_name=state["model_name"],
                hypothesis_index=index + 1,
                total_count=len(pending),
                run_id=state.get("run_id"),
                tool_registry=state.get("tool_registry"),
                meta_review=state.get("meta_review"),
            )
            for index, hypothesis in enumerate(pending)
        ]
    )
    successful = 0
    for hypothesis, result in zip(pending, results, strict=True):
        if result is None:
            continue
        classification = result.get("classification", "neutral")
        reasoning = result.get("reasoning", "")
        hypothesis.reflection_notes = (
            f"{reasoning}\n\nClassification: {classification}"
        )
        hypothesis.enrichments[ReviewType.OBSERVATION.value] = result
        successful += 1
    return successful


async def comprehensive_reflection_node(state: WorkflowState) -> dict[str, Any]:
    """Run full review cascade and recurrent reviews over viable hypotheses."""
    hypotheses = state["hypotheses"]
    viable = [
        hypothesis
        for hypothesis in hypotheses
        if hypothesis.review_disposition == "viable"
    ]
    calls = await _run_missing_observation_reviews(state, viable)
    calls += sum(
        await asyncio.gather(*[_review_hypothesis(state, h) for h in viable])
    )
    return {
        "hypotheses": hypotheses,
        "articles": state.get("articles") or [],
        "metrics": create_metrics_update(llm_calls_delta=calls),
        "messages": phase_message(
            "reflection",
            f"Completed {calls} full, simulation, or recurrent reviews",
        ),
    }
