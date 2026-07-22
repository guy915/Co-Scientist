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
)
from co_scientist.agents.generation.literature_review.orchestration import (
    _analyze_and_synthesize as _analyze_and_synthesize,
)
from co_scientist.agents.generation.literature_review.orchestration import (
    _append_kg_evidence_section as _append_kg_evidence_section,
)
from co_scientist.agents.generation.literature_review.orchestration import (
    _build_and_cache_result as _build_and_cache_result,
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
    _phase1_generate_queries,
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
from co_scientist.cache import NodeCache, get_node_cache
from co_scientist.mcp_client import (
    MCPToolClient,
    check_mcp_available,
    get_mcp_client,
)
from co_scientist.progress import emit_progress
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
        "tool_contract": tool_contract,
        "run_setup_guidance": state.get("run_setup_guidance"),
        "run_focus_guidance": state.get("run_focus_guidance"),
        "preferences": state.get("preferences"),
    }


def _initialize_review(
    state: WorkflowState,
) -> tuple[SearchConfig, NodeCache, dict[str, Any], bool]:
    """Resolves search config and cache lookup parameters for this run.

    Returns:
        A (config, node_cache, cache_params, force_cache) tuple.
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

    return config, node_cache, cache_params, force_cache


async def _check_cache(
    state: WorkflowState,
    node_cache: NodeCache,
    cache_params: dict[str, Any],
    force_cache: bool,
) -> dict[str, Any] | None:
    """Return the cached literature review result, if any.

    Keyed on the goal, model, evidence budget, run guidance, cache schema, and
    complete resolved tool contract. Identical scientific inputs reuse the
    full output, while source/configuration changes cannot replay stale work.

    Returns:
        The cached result dict on a cache hit, else None.
    """
    cached = node_cache.get(
        "literature_review", force=force_cache, **cache_params
    )
    if cached is None:
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


async def _check_server_available(
    state: WorkflowState,
    config: SearchConfig,
) -> dict[str, Any] | None:
    """Verify the literature MCP server is reachable.

    Fails fast (before spending any LLM calls on query generation) only if
    the MCP server itself is unreachable -- in which case no search source
    can run. It deliberately does not gate on any single source's health:
    the node searches several sources (the group's local corpus, PubMed,
    OpenAlex), each of whose failures is swallowed downstream so the others
    still complete. Gating on one source (historically PubMed) would let an
    unavailable remote service veto sources that are perfectly reachable,
    including the always-available local corpus.

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
    return make_failure_result("literature source service unavailable")


# =============================================================================
# Main node function
# =============================================================================


async def _prepare_review(
    state: WorkflowState,
) -> (
    tuple[SearchConfig, NodeCache, dict[str, Any], bool, MCPToolClient]
    | dict[str, Any]
):
    """Resolve config/cache, gate on cache/server, and open the MCP client.

    Returns:
        Either the (config, node_cache, cache_params, force_cache, mcp_client)
        tuple needed to continue the run, or an early-exit result dict on a
        cache hit or an unreachable MCP server.
    """
    config, node_cache, cache_params, force_cache = _initialize_review(state)

    cached = await _check_cache(state, node_cache, cache_params, force_cache)
    if cached is not None:
        return cached

    unavailable_result = await _check_server_available(state, config)
    if unavailable_result is not None:
        return unavailable_result

    await emit_progress(
        state, "literature_review_start", "Conducting literature review...", 0.1
    )

    mcp_client = await get_mcp_client(tool_registry=config.tool_registry)
    return config, node_cache, cache_params, force_cache, mcp_client


async def _finalize_review(
    state: WorkflowState,
    config: SearchConfig,
    collected: _CollectionResult,
    queries: list[str],
    node_cache: NodeCache,
    cache_params: dict[str, Any],
    force_cache: bool,
) -> dict[str, Any]:
    """Phases 3-5: analyze, synthesize, finalize, and cache the result."""
    synthesis = await _analyze_and_synthesize(
        collected.all_paper_metadata, state, collected.background_context
    )

    synthesis, articles = _finalize_synthesis_and_articles(
        synthesis,
        collected.all_paper_metadata,
        collected.context_enrichment_sources,
        config.source_name,
    )

    await _emit_and_log_completion(
        state, queries, articles, collected.search_errors, synthesis
    )

    return _build_and_cache_result(
        synthesis,
        queries,
        articles,
        collected.context_enrichment_sources,
        node_cache,
        cache_params,
        force_cache,
    )


async def _run_search_phases(
    state: WorkflowState,
    config: SearchConfig,
    mcp_client: MCPToolClient,
) -> tuple[list[str], _CollectionResult] | dict[str, Any]:
    """Phase 1 + 2-2.6: generate queries, collect papers, and gate on them.

    Returns:
        Either the (queries, collected) pair to continue with, or an
        early-exit failure result dict if collection yielded nothing usable.
    """
    queries = await _phase1_generate_queries(state, config, mcp_client)

    collected = await _collect_and_enrich_papers(
        queries, state, config, mcp_client
    )

    edge_case_result = await _handle_collection_edge_cases(
        state, collected, queries, config
    )
    if edge_case_result is not None:
        return edge_case_result

    _log_sample_papers(collected.all_paper_metadata)
    return queries, collected


async def literature_review_node(state: WorkflowState) -> dict[str, Any]:
    """Conducts literature review using configured MCP tools with LLM analysis.

    Orchestrates the following phases:
    1. Generate search queries (MCP tool or LLM)
    2. Collect papers from configured sources
    3. Discover PDF links (for sources returning landing pages)
    4. Fetch content (for sources without fulltext)
    5. Analyze each paper for gaps/limitations
    6. Synthesize findings into articles_with_reasoning
    """
    logger.info("Starting literature review node")

    prepared = await _prepare_review(state)
    if isinstance(prepared, dict):
        return prepared
    config, node_cache, cache_params, force_cache, mcp_client = prepared

    phase_result = await _run_search_phases(state, config, mcp_client)
    if isinstance(phase_result, dict):
        return phase_result
    queries, collected = phase_result

    return await _finalize_review(
        state,
        config,
        collected,
        queries,
        node_cache,
        cache_params,
        force_cache,
    )
