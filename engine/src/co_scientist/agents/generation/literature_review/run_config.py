"""Search-configuration resolution for the literature review node.

Resolves the per-run ``SearchConfig`` from workflow state and the YAML tool
registry: the papers-to-read budget (with dev-mode override), the configured
literature-review workflow, and the primary search tool for the legacy
single-source path.
"""

import logging
from typing import TYPE_CHECKING

from co_scientist.agents.generation.literature_review.helpers import (
    SearchConfig,
    extract_source_name,
)
from co_scientist.constants import (
    LITERATURE_REVIEW_PAPERS_COUNT,
    LITERATURE_REVIEW_PAPERS_COUNT_DEV,
)
from co_scientist.state import WorkflowState

if TYPE_CHECKING:
    from co_scientist.config import ToolConfig, ToolRegistry, WorkflowConfig

logger = logging.getLogger(__name__)


def _resolve_papers_to_read_count(state: WorkflowState) -> tuple[int, bool]:
    """Resolve the papers-to-read budget and dev-mode status for this run.

    Dev mode uses a far smaller paper budget for fast iteration; a per-run
    override in state takes priority over the default when not in dev mode.
    The flag itself is resolved once per run, at the generator boundary
    (``generator/run_setup._resolve_dev_mode_flag``), and read from state
    here -- so the budget this node uses is visible in the run's state
    rather than in the process environment.

    Returns:
        A (papers_to_read_count, is_dev_mode) tuple.
    """
    is_dev_mode = bool(state.get("dev_mode", False))
    run_papers_count = state.get("literature_review_papers_count")
    papers_to_read_count = (
        LITERATURE_REVIEW_PAPERS_COUNT_DEV
        if is_dev_mode
        else int(run_papers_count or LITERATURE_REVIEW_PAPERS_COUNT)
    )
    return papers_to_read_count, is_dev_mode


def _resolve_literature_workflow(
    state: WorkflowState,
) -> tuple["ToolRegistry | None", "WorkflowConfig | None", bool]:
    """Resolve the tool registry, lit-review workflow, and multi-source flag.

    Returns:
        A (tool_registry, workflow, is_multi_source) tuple. is_multi_source
        is the branch point used throughout this file to pick between the
        multi-source and single-source Phase 2 code paths.
    """
    tool_registry = state.get("tool_registry")
    workflow = (
        tool_registry.get_workflow("literature_review")
        if tool_registry
        else None
    )
    is_multi_source = bool(workflow and workflow.is_multi_source())
    return tool_registry, workflow, is_multi_source


def _log_multi_source_config(workflow: "WorkflowConfig") -> None:
    """Log the enabled search sources for multi-source mode."""
    enabled_sources = workflow.get_enabled_search_sources()
    source_names = [s.tool for s in enabled_sources]
    logger.info(
        "Multi-source mode: %s sources configured: %s",
        len(enabled_sources),
        source_names,
    )


def _resolve_single_source_tool(
    tool_registry: "ToolRegistry | None",
    workflow: "WorkflowConfig | None",
) -> tuple[str, str, "ToolConfig | None"]:
    """Resolve the legacy single-source search tool name/source/config.

    If there is no tool registry (or no configured primary_search), falls
    back to the legacy hardcoded PubMed tool so the node still works
    without a YAML tools config.
    """
    search_tool_name = "pubmed_search_with_fulltext"
    source_name = "pubmed"
    search_tool_config = None

    if tool_registry and workflow and workflow.primary_search:
        search_tool_config = tool_registry.get_tool(workflow.primary_search)
        if search_tool_config:
            search_tool_name = search_tool_config.mcp_tool_name
            source_name = extract_source_name(search_tool_config)
            logger.info(
                "Single-source mode: %s (source: %s)",
                search_tool_name,
                source_name,
            )

    return search_tool_name, source_name, search_tool_config


def _resolve_primary_search_source(
    tool_registry: "ToolRegistry | None",
    workflow: "WorkflowConfig | None",
    is_multi_source: bool,
) -> tuple[str, str, "ToolConfig | None"]:
    """Resolve the search tool name/source/config for Phase 1's fallback path.

    Multi-source mode only logs the configured sources here; the actual
    per-source tools are resolved later, in Phase 2.
    """
    if is_multi_source and workflow is not None:
        _log_multi_source_config(workflow)
        return "pubmed_search_with_fulltext", "pubmed", None
    return _resolve_single_source_tool(tool_registry, workflow)


def _get_search_config(state: WorkflowState) -> SearchConfig:
    """Extract search configuration from state and tool registry."""
    tool_registry, workflow, is_multi_source = _resolve_literature_workflow(
        state
    )

    search_tool_name, source_name, search_tool_config = (
        _resolve_primary_search_source(tool_registry, workflow, is_multi_source)
    )

    papers_to_read_count, is_dev_mode = _resolve_papers_to_read_count(state)

    return SearchConfig(
        tool_registry=tool_registry,
        workflow=workflow,
        is_multi_source=is_multi_source,
        search_tool_name=search_tool_name,
        search_tool_config=search_tool_config,
        source_name=source_name,
        papers_to_read_count=papers_to_read_count,
        is_dev_mode=is_dev_mode,
    )
