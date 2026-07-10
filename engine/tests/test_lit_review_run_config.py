"""Tests for literature review search-configuration resolution (run_config.py).

Covers ``_get_search_config``'s multi-source branch (which logs the enabled
search sources and still defaults Phase 1's fallback tool to the legacy
PubMed values) and its single-source branch when a resolvable
``primary_search`` tool is configured. Neither branch is reached by the
existing ``test_literature_review_pure`` default-state tests, since those run
with ``tool_registry=None``.
"""

from typing import cast

from co_scientist.config import (
    SearchSourceConfig,
    ToolConfig,
    ToolRegistry,
    WorkflowConfig,
)
from co_scientist.nodes.literature_review import run_config
from tests._state import make_state


class _StubRegistry:
    """Minimal ``ToolRegistry`` stand-in for ``get_workflow``/``get_tool``."""

    def __init__(
        self,
        workflow: WorkflowConfig,
        tools: dict[str, ToolConfig] | None = None,
    ) -> None:
        """Store the workflow ``get_workflow`` returns and the tool map.

        Args:
            workflow: The ``WorkflowConfig`` returned for the
                ``"literature_review"`` workflow name.
            tools: Tool-id -> ToolConfig map ``get_tool`` resolves.
        """
        self._workflow = workflow
        self._tools = tools or {}

    def get_workflow(self, name: str) -> WorkflowConfig | None:
        """Return the configured workflow for ``"literature_review"``."""
        return self._workflow if name == "literature_review" else None

    def get_tool(self, tool_id: str) -> ToolConfig | None:
        """Resolve a tool id to its configured ToolConfig, or None."""
        return self._tools.get(tool_id)


def test_get_search_config_multi_source_logs_sources_and_defaults_pubmed() -> (
    None
):
    """Multi-source mode still defaults Phase 1's fallback tool to pubmed.

    Per-source tool resolution happens later, in Phase 2; only the enabled
    (non-disabled) search sources are logged here.
    """
    workflow = WorkflowConfig(
        search_sources=[
            SearchSourceConfig(tool="src_a"),
            SearchSourceConfig(tool="src_b", enabled=False),
        ]
    )
    registry = _StubRegistry(workflow)
    state = make_state(tool_registry=cast(ToolRegistry, registry))

    config = run_config._get_search_config(state)

    assert config.is_multi_source is True
    assert config.search_tool_name == "pubmed_search_with_fulltext"
    assert config.source_name == "pubmed"
    assert config.search_tool_config is None


def test_get_search_config_single_source_resolves_configured_tool() -> None:
    """A configured, resolvable ``primary_search`` tool drives Phase 1."""
    tool_config = ToolConfig(
        server="s", mcp_tool_name="pubmed_ft", source_type="academic"
    )
    workflow = WorkflowConfig(primary_search="pubmed_primary")
    registry = _StubRegistry(workflow, {"pubmed_primary": tool_config})
    state = make_state(tool_registry=cast(ToolRegistry, registry))

    config = run_config._get_search_config(state)

    assert config.is_multi_source is False
    assert config.search_tool_name == "pubmed_ft"
    assert config.source_name == "academic"
    assert config.search_tool_config is tool_config
