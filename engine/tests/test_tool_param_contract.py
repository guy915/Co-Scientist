"""The call arguments each configured tool path sends must exist on the tool.

Every MCP call in this engine is assembled from a *canonical* parameter dict
translated by the tool's own ``parameter_mapping`` (``tools.yaml``), and an
unmapped canonical name passes straight through under its canonical spelling
(``ToolConfig._map_single_parameter``). A tool whose mapping is written in
another path's vocabulary therefore receives arguments its signature never
declared, and the reference MCP server rejects the whole call: the failure
arrives as a pydantic "Unexpected keyword argument" body that the client then
fails to JSON-decode, so it reads as a transport fault and is retried four
times before the source is dropped for that query.

That is not a hypothetical -- ``europepmc_search`` and ``preprint_search``
carried the *enrichment* vocabulary (``limit``) while both are called from the
*search* paths, so every Europe PMC query in every run failed that way. These
tests drive each wired (canonical-dict builder x configured tool list) pair
against the real signatures parsed out of ``engine/mcp_server``, which is the
contract nothing else checks: the config and the server live in separate
packages and no import binds them.
"""

import ast
import logging
from pathlib import Path
from typing import Any

import pytest

from co_scientist.agents.generation.literature_review.enrichment import (
    _build_enrichment_canonical_params,
)
from co_scientist.agents.generation.literature_review.search_query import (
    _build_query_tool_params,
)
from co_scientist.agents.generation.literature_tools.draft_tools import (
    _setup_tool_provider,
)
from co_scientist.agents.generation.literature_tools.validate_search import (
    _build_search_canonical_params,
)
from co_scientist.agents.reflection.reflection_helpers import (
    get_kg_tools_for_workflow,
)
from co_scientist.config.registry import ToolRegistry
from co_scientist.config.tool_schema import ToolConfig

# The reference MCP server, a sibling package of the engine's own sources.
# Parsed rather than imported: it declares its own dependencies (fastmcp) and
# is not installed in the engine's environment.
_MCP_SERVER_ROOT = Path(__file__).resolve().parents[1] / "mcp_server"


def _accepted_arguments(root: Path) -> dict[str, set[str]]:
    """Map every public tool function under root to its parameter names."""
    accepted: dict[str, set[str]] = {}
    for path in sorted(root.rglob("*.py")):
        if "tests" in path.parts:
            continue
        module = ast.parse(path.read_text(encoding="utf-8"))
        for name, params in _public_functions(module):
            accepted.setdefault(name, params)
    return accepted


def _public_functions(module: ast.Module) -> list[tuple[str, set[str]]]:
    """List each public function in module as (name, parameter names)."""
    functions = []
    for node in ast.walk(module):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        if not node.name.startswith("_"):
            functions.append((node.name, _parameter_names(node)))
    return functions


def _parameter_names(node: ast.AsyncFunctionDef | ast.FunctionDef) -> set[str]:
    """Collect the keyword-callable parameter names of one function."""
    return {arg.arg for arg in (*node.args.args, *node.args.kwonlyargs)}


@pytest.fixture(scope="module")
def accepted() -> dict[str, set[str]]:
    """Parameter names the reference MCP server's tools accept, by tool name."""
    return _accepted_arguments(_MCP_SERVER_ROOT)


@pytest.fixture(scope="module")
def registry() -> ToolRegistry:
    """The shipped default tool/workflow configuration."""
    return ToolRegistry()


def _assert_callable(
    tool_config: ToolConfig,
    params: dict[str, object],
    accepted: dict[str, set[str]],
) -> None:
    """Assert every mapped argument exists on the named MCP tool."""
    tool_name = tool_config.mcp_tool_name
    assert tool_name in accepted, f"{tool_name} is not defined by the server"
    unexpected = sorted(set(params) - accepted[tool_name])
    assert not unexpected, (
        f"{tool_name} would be called with {unexpected}, which its signature"
        f" does not accept; fix the parameter_mapping in tools.yaml"
    )


def _sources(registry: ToolRegistry) -> list[ToolConfig]:
    """Every enabled literature-review search source, as tool configs."""
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None
    configs = [
        registry.get_tool(source.tool)
        for source in workflow.get_enabled_search_sources()
    ]
    return [config for config in configs if config is not None]


def test_literature_search_sources_accept_their_query_params(
    registry: ToolRegistry, accepted: dict[str, set[str]]
) -> None:
    """Phase-2 literature search reaches every source with valid arguments."""
    configs = _sources(registry)
    assert configs, "the default config must configure search sources"
    for tool_config in configs:
        params = _build_query_tool_params(
            "resistance reversal", "research_1", "run-1", 3, tool_config
        )
        _assert_callable(tool_config, params, accepted)


def test_validation_search_tools_accept_their_query_params(
    registry: ToolRegistry, accepted: dict[str, set[str]]
) -> None:
    """Novelty validation reaches any of its candidate tools the same way."""
    tool_ids = registry.get_tools_for_workflow("validation")
    assert tool_ids, "the default config must configure validation tools"
    for tool_id in tool_ids:
        tool_config = registry.get_tool(tool_id)
        assert tool_config is not None
        if tool_config.category not in ("search", "search_with_content"):
            continue
        canonical = _build_search_canonical_params(
            "resistance reversal", 3, "research_1", "run-1"
        )
        _assert_callable(
            tool_config, tool_config.map_parameters(canonical), accepted
        )


def test_context_enrichment_tools_accept_their_entity_params(
    registry: ToolRegistry, accepted: dict[str, set[str]]
) -> None:
    """Context enrichment reaches every knowledge-base tool it is given."""
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None
    assert workflow.context_enrichment_tools
    for tool_id in workflow.context_enrichment_tools:
        tool_config = registry.get_tool(tool_id)
        assert tool_config is not None
        canonical = _build_enrichment_canonical_params("MCR-1")
        _assert_callable(
            tool_config, tool_config.map_parameters(canonical), accepted
        )


# The reflection knowledge-graph path does not go through parameter_mapping
# at all: it calls whichever configured tool the server has with INDRA's own
# entity arguments. Same contract, so the same test -- the default config
# lists literature tools under `reflection.search_tools`, and calling one of
# those with `agent=` is rejected exactly as Europe PMC was.
_KG_ENTITY_ARGUMENTS = {"agent", "limit", "evidence_limit"}


def test_reflection_kg_tools_accept_entity_arguments(
    registry: ToolRegistry, accepted: dict[str, set[str]]
) -> None:
    """Reflection only reaches for tools that take an INDRA entity query."""
    for tool_name in get_kg_tools_for_workflow(registry, "reflection"):
        assert tool_name in accepted, f"{tool_name} is not defined"
        unexpected = sorted(_KG_ENTITY_ARGUMENTS - accepted[tool_name])
        assert not unexpected, (
            f"{tool_name} would be queried with {unexpected}, which its"
            f" signature does not accept; it is not a knowledge-graph tool"
        )


def test_indra_example_config_selects_its_knowledge_graph_tool(
    accepted: dict[str, set[str]],
) -> None:
    """Opting INDRA in wires the reflection path to the INDRA tools.

    The example config extends the shipped reflection list rather than
    replacing it, so its tools arrive *after* the literature ones; selecting
    by source type rather than by position is what makes the opt-in work.
    """
    example = (
        Path(__file__).resolve().parents[1]
        / "src/co_scientist/config/examples/indra_hfpef.yaml"
    )
    registry = ToolRegistry(config_path=str(example), skip_user_config=True)
    kg_tools = get_kg_tools_for_workflow(registry, "reflection")
    assert kg_tools, "the INDRA example must reach a knowledge-graph tool"
    for tool_name in kg_tools:
        assert accepted[tool_name] >= _KG_ENTITY_ARGUMENTS


def test_opencitations_is_exposed_only_through_draft_read_tools(
    registry: ToolRegistry,
) -> None:
    """The draft provider offers this lookup from its configured read list."""
    tool_id = "opencitations_citation_edges"
    tool_config = registry.get_tool(tool_id)
    assert tool_config is not None
    assert tool_config.mcp_tool_name == "get_opencitations_citation_edges"
    assert tool_config.category == "read"

    draft = registry.get_workflow("draft_generation")
    assert draft is not None
    assert tool_id in draft.read_tools
    assert tool_id in registry.get_tools_for_workflow("draft_generation")
    for workflow_name in ("literature_review", "validation", "reflection"):
        assert tool_id not in registry.get_tools_for_workflow(workflow_name)

    class DraftMCPClient:
        """Return schemas only for the whitelist used by the draft setup."""

        def get_tools(
            self, whitelist: list[str] | None = None
        ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
            names = registry.get_mcp_tool_names(
                registry.get_tools_for_workflow("draft_generation")
            )
            selected = (
                names
                if whitelist is None
                else [name for name in names if name in whitelist]
            )
            return (
                {name: object() for name in selected},
                [
                    {"type": "function", "function": {"name": name}}
                    for name in selected
                ],
            )

    _, model_tools, _ = _setup_tool_provider(
        DraftMCPClient(),
        registry,
        "draft_generation",
        "draft-test",
        logging.getLogger(__name__),
    )
    assert "get_opencitations_citation_edges" in {
        tool["function"]["name"] for tool in model_tools
    }
