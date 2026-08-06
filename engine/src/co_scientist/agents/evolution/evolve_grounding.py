"""Live literature grounding for enhancement evolution.

The paper's enhancement strategy is enhancement *through grounding*: the
agent identifies the hypothesis's weaknesses, generates search queries,
retrieves and reads articles, and elaborates details to fill the reasoning
gaps (SSR §4). This module performs that live retrieval for the parent
idea being enhanced and renders it into a prompt-ready evidence block.

Degradation is the same convention the reflection cascade uses: without an
MCP server (or when the retrieval itself fails) the block falls back to the
run's existing articles, and a retrieval never raises into the evolution
call -- tools degrade to an empty result rather than fail the refinement.
"""

import logging

from co_scientist.agents.reflection.deep_verification import (
    _retrieve_probe_evidence,
)
from co_scientist.agents.reflection.evidence_context import (
    RETRIEVED_LABEL,
    EvidenceCaps,
    build_evidence_context,
)
from co_scientist.constants import (
    DEFAULT_MAX_TOKENS,
    LITERATURE_REVIEW_MAX_QUERIES,
    LOW_TEMPERATURE,
)
from co_scientist.llm import CompletionSpec, LLMCallOptions, call_llm_json
from co_scientist.models import Article, Hypothesis
from co_scientist.prompts import get_hypothesis_query_generation_prompt
from co_scientist.schemas import LITERATURE_QUERY_SCHEMA
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

# Bounds the per-parent grounding retrieval the same way the reflection
# cascade bounds its own targeted retrievals: at most this many keyword
# queries, and at most this many sources rendered into the prompt.
_MAX_GROUNDING_QUERIES = LITERATURE_REVIEW_MAX_QUERIES
_MAX_GROUNDING_ARTICLES = 6

# Rendered when neither a live retrieval nor the run's accumulated articles
# can ground the refinement, so the section never renders hollow.
_NO_EVIDENCE_TEXT = (
    "No retrieved evidence is available to ground this refinement."
)

# Placeholder for operators whose brief carries no targeted retrieval, so
# the shared template variable always renders an explicit statement rather
# than an unexplained blank.
_NOT_APPLICABLE_TEXT = (
    "Targeted literature retrieval applies to the enhancement operator "
    "only; this operator works from the context already provided."
)


def not_applicable_block() -> str:
    """The grounding-block placeholder for non-enhancement operators."""
    return _NOT_APPLICABLE_TEXT


async def enhancement_grounding_block(
    state: WorkflowState, hypothesis: Hypothesis
) -> str:
    """Build the targeted-evidence block for one enhancement refinement.

    Performs a live retrieval for the parent idea being enhanced; when the
    MCP server is unavailable or the retrieval returns nothing, falls back
    to the run's existing articles so the operator still grounds in what
    the run already read.

    Args:
        state: The workflow state (MCP availability, search config, and the
            run's accumulated articles).
        hypothesis: The parent hypothesis being enhanced.

    Returns:
        A prompt-ready evidence block, never empty.
    """
    articles = await _retrieve_parent_evidence(state, hypothesis)
    if articles:
        return build_evidence_context(
            articles,
            require_analyzed=False,
            article_label=RETRIEVED_LABEL,
            caps=EvidenceCaps(articles=_MAX_GROUNDING_ARTICLES),
        )
    run_articles = state.get("articles") or []
    if run_articles:
        # The run corpus mixes literature-review papers with the targeted
        # sources reflection retrieved (only the former are marked
        # analyzed), and both may ground an enhancement.
        return build_evidence_context(
            run_articles,
            require_analyzed=False,
            article_label=RETRIEVED_LABEL,
            caps=EvidenceCaps(articles=_MAX_GROUNDING_ARTICLES),
        )
    return _NO_EVIDENCE_TEXT


async def _retrieve_parent_evidence(
    state: WorkflowState, hypothesis: Hypothesis
) -> list[Article]:
    """Formulate queries for one parent and run its targeted searches.

    Returns an empty list -- never raises -- when the MCP server is down,
    query generation fails, or the retrieval does, leaving the caller to
    fall back to the run's accumulated articles.
    """
    if not state.get("mcp_available"):
        return []
    queries = await _parent_search_queries(state, hypothesis)
    if not queries:
        return []
    articles, errors = await _retrieve_probe_evidence(state, queries)
    if errors:
        logger.warning(
            "Enhancement grounding retrieval degraded for %s: %s",
            hypothesis.id,
            errors,
        )
    return articles


async def _parent_search_queries(
    state: WorkflowState, hypothesis: Hypothesis
) -> list[str]:
    """Formulate keyword search queries targeting the parent's mechanism.

    The search back end ANDs every term, so prose retrieves nothing: this
    asks the model for the few terms a relevant paper would actually carry,
    the same shape the reflection cascade's own queries take. Returns an
    empty list when the model call fails, which leaves the enhancement
    ungrounded rather than sending a query that cannot match.
    """
    try:
        result = await call_llm_json(
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
                prompt_name=f"evolution_grounding_queries_{hypothesis.id}",
            ),
        )
    except Exception as exc:
        logger.warning(
            "Enhancement query generation failed for %s: %s",
            hypothesis.id,
            exc,
        )
        return []
    queries = [
        " ".join(str(query).split())
        for query in result.get("queries") or []
        if str(query).strip()
    ]
    return queries[:_MAX_GROUNDING_QUERIES]


def counts_query_call(state: WorkflowState, operator_value: str) -> bool:
    """Whether one enhancement task will spend a query-generation LLM call."""
    return bool(state.get("mcp_available")) and operator_value == "enhancement"


def grounding_metrics_extra(
    state: WorkflowState, operator_values: list[str]
) -> int:
    """Count the query-generation calls a round's enhancements will spend.

    The retrieval itself is an MCP tool call, not an LLM call; only the
    query formulation is, and it runs exactly when the MCP server is up.
    """
    return sum(
        1 for value in operator_values if counts_query_call(state, value)
    )
