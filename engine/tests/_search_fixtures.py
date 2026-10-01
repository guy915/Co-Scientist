"""Shared builders for the literature-review search-phase tests.

``search.py``'s phase-2 helpers all take the same three shapes: a
``SearchConfig`` describing how the phase was configured, a
``_SearchRunContext`` carrying the per-run slug/client/error sink, and a
``WorkflowConfig`` naming the sources to search. Several test modules cover
different slices of that one production module, so the builders live here
rather than being restated per module.

``make_search_config`` leaves ``search_tool_name``/``source_name`` at
placeholder values: the phase functions that read them meaningfully are
covered by tests that pass their own.
"""

import dataclasses
from typing import Any, cast

from co_scientist.config import SearchSourceConfig, WorkflowConfig
from co_scientist.evidence import search
from co_scientist.evidence.helpers import (
    SearchConfig,
)
from co_scientist.mcp_client import MCPToolClient

_DEFAULT_SEARCH_CONFIG = SearchConfig(
    tool_registry=None,
    workflow=None,
    is_multi_source=False,
    search_tool_name="search_tool",
    search_tool_config=None,
    source_name="unknown",
    papers_to_read_count=5,
    is_dev_mode=False,
)


def make_search_config(**overrides: Any) -> SearchConfig:
    """Build a SearchConfig with inert defaults, overriding given fields.

    Args:
        **overrides: Any SearchConfig fields to set (e.g. ``workflow``,
            ``tool_registry``, ``is_multi_source``).

    Returns:
        A SearchConfig with every unspecified field left inert.
    """
    return dataclasses.replace(_DEFAULT_SEARCH_CONFIG, **overrides)


def make_search_run_ctx(
    client: Any, errors: list[str], run_id: str = "run1"
) -> search._SearchRunContext:
    """A run context over the shared ``"slug"`` slug for search calls.

    Args:
        client: The duck-typed MCP client the searches call through.
        errors: The list the search path appends swallowed errors to.
        run_id: The run id stamped on progress events.

    Returns:
        A ``_SearchRunContext`` wrapping the given client and error sink.
    """
    return search._SearchRunContext(
        slug="slug",
        run_id=run_id,
        mcp_client=cast(MCPToolClient, client),
        errors=errors,
    )


def make_two_source_workflow(papers_per_query: int) -> WorkflowConfig:
    """A cross-source-deduped workflow with src_a and src_b sources.

    Args:
        papers_per_query: The per-query budget both sources carry.

    Returns:
        A WorkflowConfig over two equally-budgeted search sources.
    """
    return WorkflowConfig(
        search_sources=[
            SearchSourceConfig(tool="src_a", papers_per_query=papers_per_query),
            SearchSourceConfig(tool="src_b", papers_per_query=papers_per_query),
        ],
        deduplicate_across_sources=True,
    )
