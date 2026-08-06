"""Compiled-graph cache and configuration invalidation for the generator.

The workflow topology is derived, not declared: whether the literature-review
and reflection nodes exist at all depends on the caller's per-call opts and on
whether MCP answered. Compiling that once and keeping it forever means the
*first* call decides the topology every later call executes -- silently, and
in both directions. A call that turns literature review off still runs it and
still reaches MCP; a call that turns it on gets the simplified supervisor ->
generate flow with no literature grounding, while its state says otherwise.

So the cache is keyed on the shape it was compiled for, and everything
derived from the tool configuration -- the compiled graph and the MCP/PubMed
availability answers alike -- is dropped together when that configuration is
reloaded. Invalidating the graph without the availability probe would only
move the staleness one layer down, since the probe is what decides the shape.

A graph the generator did not compile itself is left alone: the tests install
a fake compiled graph directly on ``_graph`` to drive execution without a real
workflow, and replacing it here would silently undo that.
"""

from typing import Any, cast

from langgraph.graph import StateGraph

from co_scientist.generator.graph import (
    CompiledWorkflow,
    _add_workflow_edges,
    _add_workflow_nodes,
)
from co_scientist.state import WorkflowState


class GraphCacheMixin:
    """Builds, caches, and invalidates the generator's compiled workflow.

    ``HypothesisGenerator`` mixes this in; its ``__init__`` assigns
    ``_tool_registry`` and then calls ``invalidate_configuration_caches``
    for the rest, so a fresh generator and a reconfigured one start from
    the same cleared state.
    """

    _tool_registry: Any | None
    _mcp_available: bool | None
    _pubmed_available: bool | None
    _graph: CompiledWorkflow | None
    # The ``enable_literature_review_node`` value ``_graph`` was compiled
    # for, or None when no graph here compiled it.
    _graph_shape: bool | None

    def _build_graph(
        self, enable_literature_review_node: bool = True
    ) -> CompiledWorkflow:
        """Build the LangGraph workflow.

        Complete workflow:
        1. SUPERVISOR -> creates research plan
        2. LITERATURE_REVIEW -> search and analyze literature (optional, if
           MCP available)
        3. GENERATE -> initial hypotheses
        4. REFLECTION -> analyze hypotheses against literature (skipped if no
           lit review)
        5. REVIEW -> parallel peer reviews
        6. RANKING -> sort by score, then run Elo tournaments
        7. ITERATIONS (if max_iterations > 0):
           - META_REVIEW -> synthesize insights
           - EVOLVE -> refine top-k hypotheses
           - REVIEW -> re-review evolved hypotheses
           - RANKING -> update Elo ratings
           - PROXIMITY -> deduplicate similar hypotheses
           - Loop back or END
        8. END -> return top hypotheses

        Args:
            enable_literature_review_node: Whether to include the literature
                review node (requires MCP server).

        Returns:
            The compiled workflow.
        """
        workflow = StateGraph(WorkflowState)
        _add_workflow_nodes(workflow, enable_literature_review_node)
        _add_workflow_edges(workflow, enable_literature_review_node)
        return cast(CompiledWorkflow, workflow.compile())

    def _ensure_graph_built(self, enable_literature_review_node: bool) -> None:
        """Compile the graph unless a graph for this shape is already held.

        Args:
            enable_literature_review_node: Whether the literature review and
                reflection nodes belong in the graph this call executes. A
                cached graph compiled for the other answer is discarded.
        """
        if self._graph is not None and self._graph_shape in (
            None,
            enable_literature_review_node,
        ):
            return
        self._graph = self._build_graph(
            enable_literature_review_node=enable_literature_review_node
        )
        self._graph_shape = enable_literature_review_node

    def invalidate_configuration_caches(self) -> None:
        """Drop every cached answer derived from the tool configuration."""
        self._graph = None
        self._graph_shape = None
        self._mcp_available = None
        self._pubmed_available = None

    def reload_tool_registry(
        self,
        tools_config: str | None = None,
        disable_tools: list[str] | None = None,
    ) -> None:
        """Rebuild the tool registry and invalidate what it decided.

        The registry selects the MCP servers the availability probes reach
        and the search sources a run may use, so swapping it while the
        previous answers stand is exactly the stale-topology failure this
        module exists to prevent.

        Args:
            tools_config: Path or URL to a tools YAML, or None for the
                bundled default registry.
            disable_tools: Tool ids to disable for later calls, or None.
        """
        from co_scientist.generator.run_setup import _build_tool_registry

        self._tool_registry = _build_tool_registry(tools_config, disable_tools)
        self.invalidate_configuration_caches()
