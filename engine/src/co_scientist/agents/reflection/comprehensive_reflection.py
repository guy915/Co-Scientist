"""Tool-grounded observation, full, simulation, and recurrent reviews.

Also runs the observation review for hypotheses that reached this node
without passing through the initial reflection node.
"""

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
from co_scientist.constants import (
    DEFAULT_MAX_TOKENS,
    EXTENDED_MAX_TOKENS,
    LOW_TEMPERATURE,
)
from co_scientist.llm import call_llm_json
from co_scientist.models import (
    Article,
    Hypothesis,
    create_metrics_update,
    phase_message,
)
from co_scientist.prompts import (
    build_tool_instructions,
    get_hypothesis_query_generation_prompt,
)
from co_scientist.prompts._common import _format_meta_review_context
from co_scientist.prompts.loading import load_prompt_with_schema
from co_scientist.schemas import LITERATURE_QUERY_SCHEMA
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

# Bounds the searches (and downstream paper fan-out) per reviewed hypothesis,
# mirroring the literature-review node's own cap.
_MAX_HYPOTHESIS_QUERIES = 3


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


async def _hypothesis_search_queries(
    state: WorkflowState, hypothesis: Hypothesis
) -> list[str]:
    """Formulate keyword search queries targeting one hypothesis.

    The search back end is a keyword index that ANDs every term, so prose
    retrieves nothing: sending the goal and the hypothesis text as one string
    asks for a paper containing every word of both, down to the numbers. This
    asks the model for the few terms a relevant paper would actually carry,
    the same shape the literature-review node's own queries take.

    Args:
        state: The workflow state, for the research goal and worker model.
        hypothesis: The hypothesis whose mechanism the queries must target.

    Returns:
        Up to ``_MAX_HYPOTHESIS_QUERIES`` keyword queries; empty when there is
        no search back end to spend them on, or when the model call fails,
        which leaves the review ungrounded rather than sending a query that
        cannot match.
    """
    # Mirrors _retrieve_probe_evidence's own guard: without MCP the searches
    # never run, so formulating queries would just burn a call per review.
    if not state.get("mcp_available"):
        return []
    try:
        result = await call_llm_json(
            prompt=get_hypothesis_query_generation_prompt(
                research_goal=state["research_goal"],
                hypothesis=hypothesis.text,
            ),
            model_name=state["model_name"],
            max_tokens=DEFAULT_MAX_TOKENS,
            temperature=LOW_TEMPERATURE,
            json_schema=LITERATURE_QUERY_SCHEMA,
            run_id=state.get("run_id"),
            prompt_name=f"hypothesis_queries_{hypothesis.id}",
            # Mechanical extraction of terms already present in the
            # hypothesis, run once per reviewed hypothesis; reasoning adds
            # nothing here and this is a high-frequency call.
            enable_thinking=False,
        )
    except Exception as exc:
        logger.warning("Query generation failed for %s: %s", hypothesis.id, exc)
        return []
    queries = [
        " ".join(str(query).split())
        for query in result.get("queries") or []
        if str(query).strip()
    ]
    return queries[:_MAX_HYPOTHESIS_QUERIES]


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
        retrieval_queries = await _hypothesis_search_queries(state, hypothesis)
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
    # The observation reviews and the full/simulation/recurrent review batch
    # have no data dependency on each other, so overlap their LLM latency.
    observation_calls, review_counts = await asyncio.gather(
        _run_missing_observation_reviews(state, viable),
        asyncio.gather(*[_review_hypothesis(state, h) for h in viable]),
    )
    calls = observation_calls + sum(review_counts)
    return {
        "hypotheses": hypotheses,
        "articles": state.get("articles") or [],
        "metrics": create_metrics_update(llm_calls_delta=calls),
        "messages": phase_message(
            "reflection",
            f"Completed {calls} full, simulation, or recurrent reviews",
        ),
    }
