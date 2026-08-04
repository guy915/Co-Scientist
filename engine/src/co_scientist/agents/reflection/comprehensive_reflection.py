"""Tool-grounded observation, full, simulation, and recurrent reviews.

Also runs the observation review for hypotheses that reached this node
without passing through the initial reflection node.
"""

import asyncio
import dataclasses
import hashlib
import json
import logging
import weakref
from dataclasses import asdict
from typing import Any

from co_scientist.agents.reflection.deep_verification import (
    _retrieve_probe_evidence,
    merge_retrieved_articles,
)
from co_scientist.agents.reflection.evidence_context import (
    EvidenceCaps,
    build_evidence_context,
    showable_articles,
)
from co_scientist.agents.reflection.reflection import (
    _ReflectionContext,
    analyze_single_hypothesis,
)
from co_scientist.agents.reflection.review_types import (
    ReviewType,
    prompt_name_for,
)
from co_scientist.constants import (
    DEFAULT_MAX_TOKENS,
    EXTENDED_MAX_TOKENS,
    LITERATURE_REVIEW_MAX_QUERIES,
    LOW_TEMPERATURE,
)
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm_json,
)
from co_scientist.models import (
    Article,
    Hypothesis,
    MetricDeltas,
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
# sharing the literature-review node's own Phase 1 cap.
_MAX_HYPOTHESIS_QUERIES = LITERATURE_REVIEW_MAX_QUERIES

# How many sources one review prompt carries. Public papers and private
# scientist-supplied sources are capped separately so a full run corpus
# cannot squeeze the private context out of the prompt entirely.
_MAX_REVIEW_ARTICLES = 12
_MAX_REVIEW_PRIVATE_SOURCES = 4


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
        hypothesis_text += _recurrent_review_suffix(state, hypothesis)
    domain_context = _build_domain_context(state, targeted_articles)
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


def _recurrent_review_suffix(
    state: WorkflowState, hypothesis: Hypothesis
) -> str:
    """Builds the tournament + meta-review context for a recurrent review."""
    tournament = {
        "elo_rating": hypothesis.elo_rating,
        "match_count": hypothesis.total_matches,
        "reviews": [asdict(review) for review in hypothesis.reviews],
    }
    return (
        "\n\nRecurrent-review context from the growing tournament:\n"
        + json.dumps(tournament, indent=2)
        + "\n\nCross-agent feedback:\n"
        + _format_meta_review_context(state.get("meta_review"))
    )


def _build_domain_context(
    state: WorkflowState, targeted_articles: list[Article] | None
) -> str:
    """Formats retrieved public and private evidence for a review prompt.

    Bounds the block by source count rather than by total length: a review
    weighs a handful of papers in depth, so it is the number of voices that
    has to stay reviewable, not the character budget.
    """
    evidence = [
        # The run corpus and this review's own targeted retrieval are
        # filtered separately because only the former has been marked
        # analyzed; both are then capped as one list, so a full corpus
        # crowds out the targeted sources exactly as it did before.
        *showable_articles(state.get("articles")),
        *showable_articles(targeted_articles, require_analyzed=False),
    ]
    return build_evidence_context(
        evidence,
        private_sources=state.get("context_enrichment_sources"),
        caps=EvidenceCaps(
            articles=_MAX_REVIEW_ARTICLES,
            private_sources=_MAX_REVIEW_PRIVATE_SOURCES,
        ),
        require_analyzed=False,
    )


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
    result = await _call_hypothesis_query_llm(state, hypothesis)
    if result is None:
        return []
    queries = [
        " ".join(str(query).split())
        for query in result.get("queries") or []
        if str(query).strip()
    ]
    return queries[:_MAX_HYPOTHESIS_QUERIES]


async def _call_hypothesis_query_llm(
    state: WorkflowState, hypothesis: Hypothesis
) -> dict[str, Any] | None:
    """Calls the LLM to generate keyword queries for one hypothesis.

    Runs once per reviewed hypothesis, with thinking on as everywhere
    else. Returns None on failure.
    """
    try:
        return await call_llm_json(
            prompt=get_hypothesis_query_generation_prompt(
                research_goal=state["research_goal"],
                hypothesis=hypothesis.text,
            ),
            spec=CompletionSpec(
                model_name=state["model_name"],
                max_tokens=DEFAULT_MAX_TOKENS,
                temperature=LOW_TEMPERATURE,
                json_schema=LITERATURE_QUERY_SCHEMA,
            ),
            options=LLMCallOptions(
                run_id=state.get("run_id"),
                prompt_name=f"hypothesis_queries_{hypothesis.id}",
            ),
        )
    except Exception as exc:
        logger.warning("Query generation failed for %s: %s", hypothesis.id, exc)
        return None


async def _run_review(
    state: WorkflowState,
    hypothesis: Hypothesis,
    review_type: ReviewType,
) -> tuple[ReviewType, dict[str, Any] | None]:
    """Execute one independently meaningful Reflection review call."""
    evidence = await _review_evidence_for(state, hypothesis, review_type)
    targeted_articles = evidence.articles
    prompt, schema = _build_review_prompt(
        state, hypothesis, review_type, targeted_articles
    )
    try:
        result = await call_llm_json(
            prompt=prompt,
            spec=CompletionSpec(
                model_name=state["model_name"],
                max_tokens=EXTENDED_MAX_TOKENS,
                temperature=LOW_TEMPERATURE,
                json_schema=schema,
            ),
            options=LLMCallOptions(
                run_id=state.get("run_id"),
                prompt_name=f"reflection_{review_type.value}_{hypothesis.id}",
            ),
        )
    except Exception as exc:
        logger.error(
            "%s review failed for %s: %s", review_type.value, hypothesis.id, exc
        )
        return review_type, None
    result["retrieval_queries"] = evidence.queries
    result["retrieval_errors"] = evidence.errors
    # Each review persists the evidence it was given, so the shared
    # retrieval survives the checkpoint through both of their results
    # rather than depending on the in-process cache outliving the task.
    result["retrieved_articles"] = [
        article.to_dict() for article in targeted_articles
    ]
    return review_type, result


# In-flight targeted retrievals, one map per event loop.
#
# The full and simulation reviews of a hypothesis ask the same question of
# the same literature: queries are formulated from the hypothesis text and
# the research goal, neither of which differs by review mode. Run
# independently they cost two query-generation calls and two rounds of
# searches for one hypothesis, all of it on the run's critical path.
#
# Keyed by loop because the durable worker runs each task on its own thread
# with its own loop, and the shared task below is an asyncio object bound to
# whichever loop created it. Weakly held so a finished cohort's loop does
# not keep its retrievals alive.
_review_evidence_flights: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[str, "asyncio.Task[_ReviewEvidence]"]
] = weakref.WeakKeyDictionary()


@dataclasses.dataclass(frozen=True)
class _ReviewEvidence:
    """One hypothesis's targeted literature evidence for its reviews.

    Attributes:
        queries: The keyword searches formulated for this hypothesis.
        articles: Sources the searches returned, bounded by the probe cap.
        errors: Per-source retrieval failures, kept so a review can tell
            "found nothing" from "search broke".
    """

    queries: list[str]
    articles: list[Article]
    errors: list[str]


def _evidence_key(state: WorkflowState, hypothesis: Hypothesis) -> str:
    """Return the sharing key for one hypothesis's targeted retrieval.

    Includes the text, not just the id: evolution rewrites a hypothesis in
    place, and evidence retrieved for the claim it used to make does not
    answer the one it makes now.
    """
    text = " ".join((hypothesis.text or "").split())
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"{state.get('run_id')}:{hypothesis.id}:{digest}"


async def _shared_review_evidence(
    state: WorkflowState, hypothesis: Hypothesis
) -> _ReviewEvidence:
    """Retrieve this hypothesis's targeted evidence once, sharing the result.

    Concurrent callers await one shared task rather than each starting a
    retrieval: the full and simulation reviews of a hypothesis are gathered
    together, so a plain check-then-fill cache would let both find it empty
    and stampede, which is the case that costs the duplicate work.

    A failed retrieval is evicted rather than cached, so a retry gets a
    fresh attempt instead of inheriting the failure.
    """
    loop = asyncio.get_running_loop()
    flights = _review_evidence_flights.setdefault(loop, {})
    key = _evidence_key(state, hypothesis)
    flight = flights.get(key)
    if flight is None:
        flight = loop.create_task(_retrieve_review_evidence(state, hypothesis))
        flights[key] = flight
    try:
        return await flight
    except Exception:
        flights.pop(key, None)
        raise


async def _retrieve_review_evidence(
    state: WorkflowState, hypothesis: Hypothesis
) -> _ReviewEvidence:
    """Formulate queries for one hypothesis and run their searches."""
    queries = await _hypothesis_search_queries(state, hypothesis)
    articles, errors = await _retrieve_probe_evidence(state, queries)
    return _ReviewEvidence(queries, articles, errors)


async def _review_evidence_for(
    state: WorkflowState, hypothesis: Hypothesis, review_type: ReviewType
) -> _ReviewEvidence:
    """Return targeted evidence for the review types that search.

    Recurrent reviews reuse the accumulated tournament context instead of
    re-searching, so they get nothing here.
    """
    if review_type not in {ReviewType.FULL, ReviewType.SIMULATION}:
        return _ReviewEvidence([], [], [])
    return await _shared_review_evidence(state, hypothesis)


def _build_review_prompt(
    state: WorkflowState,
    hypothesis: Hypothesis,
    review_type: ReviewType,
    targeted_articles: list[Article],
) -> tuple[str, dict[str, Any] | None]:
    """Builds the review prompt/schema, adding the recurrent-review preamble."""
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
    return prompt, schema


def _reviews_needed(hypothesis: Hypothesis, iteration: int) -> list[ReviewType]:
    """Return the maturity-appropriate reviews due for one hypothesis.

    A hypothesis with no full review yet gets full + simulation; one
    already reviewed gets a recurrent review only if a later iteration
    has not yet been recorded.
    """
    if ReviewType.FULL.value not in hypothesis.enrichments:
        return [ReviewType.FULL, ReviewType.SIMULATION]
    recorded = int(hypothesis.enrichments.get("recurrent_review_iteration", -1))
    if iteration > recorded:
        return [ReviewType.RECURRENT]
    return []


def _apply_review_results(
    hypothesis: Hypothesis,
    iteration: int,
    results: list[tuple[ReviewType, dict[str, Any] | None]],
) -> int:
    """Store each successful review result on the hypothesis's enrichments.

    Returns:
        The number of results that were not None.
    """
    successful = 0
    for review_type, result in results:
        if result is None:
            continue
        hypothesis.enrichments[review_type.value] = result
        if review_type is ReviewType.RECURRENT:
            hypothesis.enrichments["recurrent_review_iteration"] = iteration
        successful += 1
    return successful


async def _review_hypothesis(
    state: WorkflowState, hypothesis: Hypothesis
) -> int:
    """Apply maturity-appropriate reviews to one viable hypothesis."""
    iteration = int(state.get("current_iteration", 0))
    reviews = _reviews_needed(hypothesis, iteration)
    if not reviews:
        return 0
    results = await asyncio.gather(
        *[
            _run_review(state, hypothesis, review_type)
            for review_type in reviews
        ]
    )
    successful = _apply_review_results(hypothesis, iteration, results)
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
    context = _ReflectionContext(
        articles_with_reasoning=literature,
        model_name=state["model_name"],
        run_id=state.get("run_id"),
        tool_registry=state.get("tool_registry"),
        meta_review=state.get("meta_review"),
    )
    results = await asyncio.gather(
        *[
            analyze_single_hypothesis(
                hypothesis=hypothesis,
                hypothesis_index=index + 1,
                total_count=len(pending),
                context=context,
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
        "metrics": create_metrics_update(deltas=MetricDeltas(llm_calls=calls)),
        "messages": phase_message(
            "reflection",
            f"Completed {calls} full, simulation, or recurrent reviews",
        ),
    }
