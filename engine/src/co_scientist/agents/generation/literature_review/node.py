"""Literature review node orchestrator.

Orchestrates a multi-phase literature review process:
1. Generate search queries (MCP tool or LLM)
2. Collect papers from configured sources
3. Discover PDF links (for sources returning landing pages)
4. Fetch content (for sources without fulltext)
5. Analyze each paper for gaps/limitations
6. Synthesize findings into articles_with_reasoning

The phase-sequence helpers live in the sibling ``run_config``, ``outcomes``,
and ``orchestration`` modules and are re-exported here (tests exercise
several of the private helpers through this namespace). This module keeps the
top-level orchestrator plus the cache/availability gates whose external seams
(``get_node_cache``, ``check_mcp_available``,
``get_mcp_client``) tests monkeypatch on this namespace.
"""

import dataclasses
import logging
from typing import Any

from co_scientist.agents.generation.literature_review.helpers import (
    SearchConfig,
    make_failure_result,
    make_success_result,
)
from co_scientist.agents.generation.literature_review.orchestration import (
    _analyze_and_synthesize as _analyze_and_synthesize,
)
from co_scientist.agents.generation.literature_review.orchestration import (
    _append_kg_evidence_section as _append_kg_evidence_section,
)
from co_scientist.agents.generation.literature_review.orchestration import (
    _cache_result as _cache_result,
)
from co_scientist.agents.generation.literature_review.orchestration import (
    _collect_and_enrich_papers as _collect_and_enrich_papers,
)
from co_scientist.agents.generation.literature_review.orchestration import (
    _CollectionResult as _CollectionResult,
)
from co_scientist.agents.generation.literature_review.orchestration import (
    _count_used_papers as _count_used_papers,
)
from co_scientist.agents.generation.literature_review.orchestration import (
    _emit_and_log_completion as _emit_and_log_completion,
)
from co_scientist.agents.generation.literature_review.orchestration import (
    _fetch_content_and_enrichment as _fetch_content_and_enrichment,
)
from co_scientist.agents.generation.literature_review.orchestration import (
    _finalize_synthesis_and_articles as _finalize_synthesis_and_articles,
)
from co_scientist.agents.generation.literature_review.orchestration import (
    _handle_collection_edge_cases as _handle_collection_edge_cases,
)
from co_scientist.agents.generation.literature_review.orchestration import (
    _phase2_collect_papers as _phase2_collect_papers,
)
from co_scientist.agents.generation.literature_review.orchestration import (
    _ReviewCachePlan as _ReviewCachePlan,
)
from co_scientist.agents.generation.literature_review.orchestration import (
    _ReviewSynthesis as _ReviewSynthesis,
)
from co_scientist.agents.generation.literature_review.outcomes import (
    _describe_exc as _describe_exc,
)
from co_scientist.agents.generation.literature_review.outcomes import (
    _emit_empty_search_diagnostics as _emit_empty_search_diagnostics,
)
from co_scientist.agents.generation.literature_review.outcomes import (
    _handle_no_fulltext_available as _handle_no_fulltext_available,
)
from co_scientist.agents.generation.literature_review.outcomes import (
    _handle_no_papers_found as _handle_no_papers_found,
)
from co_scientist.agents.generation.literature_review.outcomes import (
    _log_sample_papers as _log_sample_papers,
)
from co_scientist.agents.generation.literature_review.queries import (
    QueryPhaseResult,
    _phase1_generate_queries,
)
from co_scientist.agents.generation.literature_review.research_phase import (
    ResearchOutcome,
    run_research_phase,
)
from co_scientist.agents.generation.literature_review.run_config import (
    _get_search_config as _get_search_config,
)
from co_scientist.agents.generation.literature_review.run_config import (
    _log_multi_source_config as _log_multi_source_config,
)
from co_scientist.agents.generation.literature_review.run_config import (
    _resolve_literature_workflow as _resolve_literature_workflow,
)
from co_scientist.agents.generation.literature_review.run_config import (
    _resolve_papers_to_read_count as _resolve_papers_to_read_count,
)
from co_scientist.agents.generation.literature_review.run_config import (
    _resolve_primary_search_source as _resolve_primary_search_source,
)
from co_scientist.agents.generation.literature_review.run_config import (
    _resolve_single_source_tool as _resolve_single_source_tool,
)
from co_scientist.cache import get_node_cache
from co_scientist.constants import LITERATURE_REVIEW_FAILED
from co_scientist.mcp_client import (
    MCPToolClient,
    check_mcp_available,
    get_mcp_client,
)
from co_scientist.models import MetricDeltas, create_metrics_update
from co_scientist.progress import emit_progress
from co_scientist.retrieval_degradation import (
    resolve_retrieval_degradation,
)
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

_LITERATURE_CACHE_SCHEMA_VERSION = 3


# =============================================================================
# Cache and availability gates
# =============================================================================


def _literature_cache_params(
    state: WorkflowState, config: SearchConfig
) -> dict[str, Any]:
    """Return every material input that can change literature output."""
    registry = config.tool_registry
    tool_contract: dict[str, Any]
    if registry is None:
        tool_contract = {
            "legacy_search_tool": config.search_tool_name,
            "source_name": config.source_name,
        }
    else:
        # The hash receives the resolved typed config, including enabled
        # sources, parameter mappings, response mappings, and endpoint. The
        # cache stores only the resulting digest, never this configuration.
        tool_contract = dataclasses.asdict(registry.config)
    return {
        "cache_schema_version": _LITERATURE_CACHE_SCHEMA_VERSION,
        "research_goal": state["research_goal"],
        "model_name": state.get("model_name"),
        "papers_to_read_count": config.papers_to_read_count,
        # A tier that researches produces a different review from one that
        # does not, so the two must not share a cache entry.
        "research_tier": state.get("research_tier"),
        "tool_contract": tool_contract,
        "run_setup_guidance": state.get("run_setup_guidance"),
        "run_focus_guidance": state.get("run_focus_guidance"),
        "preferences": state.get("preferences"),
        # The query/synthesis prompts now carry the meta-review critique
        # (audit E7), so a different critique cannot replay stale results.
        "meta_review": state.get("meta_review"),
    }


def _initialize_review(
    state: WorkflowState,
) -> tuple[SearchConfig, _ReviewCachePlan]:
    """Resolves search config and cache lookup parameters for this run.

    Returns:
        A (config, cache_plan) tuple.
    """
    config = _get_search_config(state)
    logger.info(
        "Literature review config: dev_mode=%s, papers=%s",
        config.is_dev_mode,
        config.papers_to_read_count,
    )

    node_cache = get_node_cache()
    cache_params = _literature_cache_params(state, config)
    # dev_test_lit_tools_isolation forces cache use even when the global
    # cache is disabled, so a developer iterating on the downstream
    # lit-tools generation phase can skip re-running this expensive node
    # every time.
    force_cache = bool(state.get("dev_test_lit_tools_isolation", False))
    if force_cache:
        logger.info("Dev isolation mode: forcing literature review cache")

    return config, _ReviewCachePlan(node_cache, cache_params, force_cache)


async def _check_cache(
    state: WorkflowState,
    cache_plan: _ReviewCachePlan,
) -> dict[str, Any] | None:
    """Return the cached literature review result, if any.

    Keyed on the goal, model, evidence budget, run guidance, cache schema, and
    complete resolved tool contract. Identical scientific inputs reuse the
    full output, while source/configuration changes cannot replay stale work.

    Returns:
        The cached result dict on a cache hit, else None.
    """
    cached = cache_plan.node_cache.get(
        "literature_review",
        force=cache_plan.force_cache,
        **cache_plan.cache_params,
    )
    if cached is None:
        return None
    if _has_orphaned_research_articles(cached):
        logger.warning(
            "Literature review cache entry has researched articles but no "
            "research ledger; refreshing it"
        )
        return None

    logger.info("Literature review cache hit")
    await emit_progress(
        state,
        "literature_review_complete",
        "Literature review completed (cached)",
        0.2,
        cached=True,
    )
    return cached


def _has_orphaned_research_articles(result: dict[str, Any]) -> bool:
    """Return whether cached articles cite research without its ledger."""
    if result.get("research_ledgers"):
        return False
    articles = result.get("articles")
    if not isinstance(articles, list):
        return False
    return any(
        article.get("retrieval_call_id")
        if isinstance(article, dict)
        else getattr(article, "retrieval_call_id", None)
        for article in articles
    )


async def _check_server_available(
    state: WorkflowState,
    config: SearchConfig,
) -> dict[str, Any] | None:
    """Verify the literature MCP server is reachable.

    Fails fast (before spending any LLM calls on query generation) only if
    the MCP server itself is unreachable -- in which case no search source
    can run. It deliberately does not gate on any single source's health:
    the node searches several sources (PubMed, OpenAlex, ...), each of
    whose failures is swallowed downstream so the others still complete.
    Gating on one source (historically PubMed) would let an unavailable
    remote service veto sources that are perfectly reachable.

    Returns:
        A failure result dict if the server is unreachable, else None.
    """
    server_available = await check_mcp_available(
        tool_registry=config.tool_registry
    )
    if server_available:
        return None

    logger.error("Literature review MCP server unavailable")
    await emit_progress(
        state,
        "literature_review_error",
        "Literature review failed (MCP server unavailable)",
        0.2,
    )
    result = make_failure_result("literature source service unavailable")
    # The server was reachable when the run was set up, or the graph would
    # have routed around this node entirely. Losing it here is the same
    # degradation arriving later, so it is recorded the same way rather
    # than left as this node's private failure.
    result["retrieval_degradation"] = resolve_retrieval_degradation(
        mcp_available=False,
        private_sources=state.get("context_enrichment_sources"),
    )
    return result


def _with_llm_call_metrics(
    result: dict[str, Any], llm_calls: int
) -> dict[str, Any]:
    """Attach a metrics delta reporting this node's real LLM calls, in place.

    Every literature-review exit path (cache hit, MCP unavailable, no
    papers found, no fulltext available, full success) routes through this
    so ``max_llm_calls`` sees the node's real spend regardless of which
    phase it exited at (finding L3 -- literature review previously
    reported no llm_calls at all).

    Args:
        result: the node's state-update dict, mutated in place.
        llm_calls: real LLM calls made before this exit.

    Returns:
        The same ``result`` dict, for chaining at a return statement.
    """
    result["metrics"] = create_metrics_update(
        deltas=MetricDeltas(llm_calls=llm_calls)
    )
    return result


# =============================================================================
# Main node function
# =============================================================================


async def _prepare_review(
    state: WorkflowState,
) -> tuple[SearchConfig, _ReviewCachePlan, MCPToolClient] | dict[str, Any]:
    """Resolve config/cache, gate on cache/server, and open the MCP client.

    Returns:
        Either the (config, cache_plan, mcp_client) tuple needed to continue
        the run, or an early-exit result dict on a cache hit or an
        unreachable MCP server.
    """
    config, cache_plan = _initialize_review(state)

    cached = await _check_cache(state, cache_plan)
    if cached is not None:
        return cached

    unavailable_result = await _check_server_available(state, config)
    if unavailable_result is not None:
        return unavailable_result

    await emit_progress(
        state, "literature_review_start", "Conducting literature review...", 0.1
    )

    mcp_client = await get_mcp_client(tool_registry=config.tool_registry)
    return config, cache_plan, mcp_client


@dataclasses.dataclass(frozen=True)
class _ReviewOutput:
    """Everything the phases produced, on the way to the node's result.

    Bundled because finalizing needs all of it and a six-parameter call
    signature reads as an accident rather than a sequence.

    Attributes:
        config: The review's resolved search configuration.
        collected: What Phase 2 collected, enriched.
        query_result: Phase 1's queries and their cost.
        cache_plan: Where the finished result is cached.
        reviewed: Phases 3-4: the synthesis and the analyses behind it.
        research: Phase 6's result, or None when no research ran.
    """

    config: SearchConfig
    collected: _CollectionResult
    query_result: QueryPhaseResult
    cache_plan: _ReviewCachePlan
    reviewed: _ReviewSynthesis
    research: ResearchOutcome | None


def _merge_research(output: _ReviewOutput) -> str:
    """Fold Phase 6's papers into the pool and its findings into the text.

    A researched paper the ordinary search already collected keeps the
    record it was collected with: that record has been through content
    fetch and per-paper analysis, and replacing it with a search result
    would trade an analyzed paper for an unanalyzed one.

    Returns:
        The synthesis with the research section appended, unchanged when
        no research ran. A failed review keeps the bare
        LITERATURE_REVIEW_FAILED sentinel however much research found,
        because downstream generation compares against it exactly
        (see coordinator_strategy) and an appended section would read as
        a review that succeeded.
    """
    research = output.research
    if research is None:
        return output.reviewed.text
    pool = output.collected.all_paper_metadata
    for locator, record in research.records.items():
        if locator not in pool:
            pool[locator] = record
    if output.reviewed.text == LITERATURE_REVIEW_FAILED:
        return output.reviewed.text
    return output.reviewed.text + research.section


async def _finalize_review(
    state: WorkflowState, output: _ReviewOutput
) -> dict[str, Any]:
    """Phase 5: merge research, build articles, finalize and cache."""
    collected = output.collected
    queries = output.query_result.queries
    synthesis, articles = _finalize_synthesis_and_articles(
        _merge_research(output),
        collected.all_paper_metadata,
        collected.context_enrichment_sources,
        output.config.source_name,
    )

    await _emit_and_log_completion(
        state, queries, articles, collected.search_errors, synthesis
    )

    result = make_success_result(synthesis, queries, articles)
    if collected.context_enrichment_sources:
        result["context_enrichment_sources"] = (
            collected.context_enrichment_sources
        )
    if output.research is not None:
        result["research_ledgers"] = [output.research.ledger]
    result = _cache_result(result, output.cache_plan)
    return _with_llm_call_metrics(
        result, output.query_result.llm_calls + output.reviewed.llm_calls
    )


async def _run_search_phases(
    state: WorkflowState,
    config: SearchConfig,
    mcp_client: MCPToolClient,
) -> tuple[QueryPhaseResult, _CollectionResult] | dict[str, Any]:
    """Phase 1 + 2-2.6: generate queries, collect papers, and gate on them.

    Returns:
        Either the (query_result, collected) pair to continue with, or an
        early-exit failure result dict (carrying query_result.llm_calls as
        its own metrics delta) if collection yielded nothing usable.
    """
    query_result = await _phase1_generate_queries(state, config, mcp_client)
    queries = query_result.queries

    collected = await _collect_and_enrich_papers(
        queries, state, config, mcp_client
    )

    edge_case_result = await _handle_collection_edge_cases(
        state, collected, queries, config
    )
    if edge_case_result is not None:
        return _with_llm_call_metrics(edge_case_result, query_result.llm_calls)

    _log_sample_papers(collected.all_paper_metadata)
    return query_result, collected


async def literature_review_node(state: WorkflowState) -> dict[str, Any]:
    """Conducts literature review using configured MCP tools with LLM analysis.

    Orchestrates the following phases:
    1. Generate search queries (MCP tool or LLM)
    2. Collect papers from configured sources
    3. Discover PDF links (for sources returning landing pages)
    4. Fetch content (for sources without fulltext)
    5. Analyze each paper for gaps/limitations
    6. Synthesize findings into articles_with_reasoning
    7. Research what the synthesis left open, where the tier funds it
    """
    logger.info("Starting literature review node")

    prepared = await _prepare_review(state)
    if isinstance(prepared, dict):
        return prepared
    config, cache_plan, mcp_client = prepared

    phase_result = await _run_search_phases(state, config, mcp_client)
    if isinstance(phase_result, dict):
        return phase_result
    query_result, collected = phase_result

    reviewed = await _analyze_and_synthesize(
        collected.all_paper_metadata, state, collected.background_context
    )
    research = await run_research_phase(
        state, config, mcp_client, reviewed.analyses
    )

    return await _finalize_review(
        state,
        _ReviewOutput(
            config=config,
            collected=collected,
            query_result=query_result,
            cache_plan=cache_plan,
            reviewed=reviewed,
            research=research,
        ),
    )
