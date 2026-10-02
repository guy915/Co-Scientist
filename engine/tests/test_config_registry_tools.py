"""Tests for per-run tool disabling in the tool registry.

Split from ``test_config_registry.py``: covers the ``disabled_tools``
constructor argument and the load-time reconciliation that keeps a dead
tool's search source from staying live -- the multi-source literature
pipeline selects sources on ``SearchSourceConfig.enabled`` alone, so a
disabled (or never-defined) tool must also flip its source's flag.
"""

import textwrap
from pathlib import Path

from co_scientist.config.registry import ToolRegistry
from tests._registry_config import REPLACE_CONFIG as _REPLACE_CONFIG
from tests._registry_config import write_config as _write_config

# A two-source workflow whose tools are both enabled in the YAML, so any
# disabling under test comes from the ``disabled_tools`` constructor argument.
_TWO_SOURCE_CONFIG = textwrap.dedent("""
    version: "2.0"
    servers:
      myserver:
        url: "http://example.test/mcp"
        enabled: true
    tools:
      search_tools:
        alpha_search:
          server: "myserver"
          mcp_tool_name: "search_alpha"
          enabled: true
        beta_search:
          server: "myserver"
          mcp_tool_name: "search_beta"
          enabled: true
    workflows:
      literature_review:
        search_sources:
          - tool: "alpha_search"
            papers_per_query: 4
            enabled: true
          - tool: "beta_search"
            papers_per_query: 4
            enabled: true
""")

# beta_search is disabled in the YAML and ghost_search names a tool that is
# never defined -- both cases the load-time reconciliation must cover.
_YAML_DISABLED_CONFIG = textwrap.dedent("""
    version: "2.0"
    servers:
      myserver:
        url: "http://example.test/mcp"
        enabled: true
    tools:
      search_tools:
        alpha_search:
          server: "myserver"
          mcp_tool_name: "search_alpha"
          enabled: true
        beta_search:
          server: "myserver"
          mcp_tool_name: "search_beta"
          enabled: false
    workflows:
      literature_review:
        search_sources:
          - tool: "alpha_search"
            papers_per_query: 4
            enabled: true
          - tool: "beta_search"
            papers_per_query: 4
            enabled: true
          - tool: "ghost_search"
            papers_per_query: 4
            enabled: true
""")


# --- disabled_tools constructor argument ----------------------------------


def test_disabled_tools_argument_flips_enabled(tmp_path: Path) -> None:
    """``disabled_tools`` disables a tool that was enabled in the config."""
    path = _write_config(tmp_path, _REPLACE_CONFIG)
    registry = ToolRegistry(
        config_path=path,
        skip_user_config=True,
        disabled_tools=["alpha_search"],
    )
    alpha = registry.get_tool("alpha_search")
    assert alpha is not None and alpha.enabled is False
    # With alpha disabled, the literature_review workflow drops to gamma only.
    assert registry.get_tools_for_workflow("literature_review") == [
        "gamma_util",
    ]


def test_disabled_tools_also_disables_its_search_source(
    tmp_path: Path,
) -> None:
    """A disabled tool must not survive as a live search source.

    The multi-source literature pipeline picks sources on
    ``SearchSourceConfig.enabled`` and never consults the tool's own flag,
    so a caller-disabled tool would otherwise keep being searched while the
    workflow whitelists correctly dropped it -- the gap that let a
    caller's tool restriction leak into the literature review.
    """
    path = _write_config(tmp_path, _TWO_SOURCE_CONFIG)

    enabled = ToolRegistry(config_path=path, skip_user_config=True)
    workflow = enabled.get_workflow("literature_review")
    assert workflow is not None
    assert [s.tool for s in workflow.get_enabled_search_sources()] == [
        "alpha_search",
        "beta_search",
    ]

    restricted = ToolRegistry(
        config_path=path,
        skip_user_config=True,
        disabled_tools=["alpha_search"],
    )
    restricted_workflow = restricted.get_workflow("literature_review")
    assert restricted_workflow is not None
    assert [
        s.tool for s in restricted_workflow.get_enabled_search_sources()
    ] == ["beta_search"]


def test_yaml_disabled_or_missing_tool_disables_its_search_source(
    tmp_path: Path,
) -> None:
    """Source flags are reconciled with tool flags however a tool is off.

    ``disabled_tools`` is not the only way a source's tool can be dead: the
    YAML itself may disable the tool while leaving the source enabled, or a
    source may name a tool that was never defined. The load-time
    reconciliation must cover those too, since the search phase trusts
    ``get_enabled_search_sources()`` alone.
    """
    path = _write_config(tmp_path, _YAML_DISABLED_CONFIG)

    registry = ToolRegistry(config_path=path, skip_user_config=True)
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None
    assert [s.tool for s in workflow.get_enabled_search_sources()] == [
        "alpha_search",
    ]


def test_europepmc_results_normalize_into_individual_papers() -> None:
    """Europe PMC's envelope must be unwrapped into one entry per record.

    The tool returns ``{"source": ..., "query": ..., "records": [...]}``
    rather than the ``{paper_id: metadata}`` map the pipeline expects.
    Without a response_format that names ``records``, the three envelope
    keys are themselves taken for paper ids -- so every real record is
    discarded and ``merge_search_results`` is handed a string where it
    expects metadata, raising ``AttributeError`` out of Phase 2 and
    failing the whole literature review node with its retry budget spent
    on the identical failure.
    """
    from co_scientist.config import ToolRegistry
    from co_scientist.evidence.search_support import (
        merge_search_results,
        normalize_search_response,
    )

    tool_config = ToolRegistry().get_tool("europepmc_search")
    assert tool_config is not None
    envelope = {
        "source": "Europe PMC",
        "query": "NHE1 in cancer",
        "records": [
            {
                "source_id": "MED/42387642",
                "title": "PKMYT1 in Cancer",
                "abstract": "PKMYT1 has emerged as a target.",
                "year": "2026",
                "cited_by_count": 3,
                "is_preprint": False,
                "url": "https://doi.org/10.1002/gcc.70151",
            },
            {
                "source_id": "PPR/1234567",
                "title": "NHE1 regulation of tumour pH",
                "abstract": "A preprint on pH regulation.",
                "year": "2026",
                "cited_by_count": 0,
                "is_preprint": True,
                "url": "https://europepmc.org/article/PPR/1234567",
            },
        ],
    }

    normalized = normalize_search_response(envelope, tool_config)

    assert set(normalized) == {"MED/42387642", "PPR/1234567"}
    assert normalized["MED/42387642"]["title"] == "PKMYT1 in Cancer"

    merged, _ = merge_search_results(
        [("europepmc_search", normalized)], deduplicate=True
    )
    assert len(merged) == 2


def test_preprint_search_results_parse_into_articles() -> None:
    """The novelty fallback must actually yield articles, not silently none.

    ``preprint_search`` shares Europe PMC's envelope shape. Without a
    response_format naming ``records`` the parser walks the envelope's own
    keys, finds no title on any of them, and drops every one -- so the
    validation path's last academic source reports zero preprints for
    every query and a novelty claim about the last eighteen months goes
    unchecked. It fails silently rather than loudly because this path
    skips a malformed article instead of raising.
    """
    from co_scientist.config import ToolRegistry
    from co_scientist.tools.response_parser import ResponseParser

    tool_config = ToolRegistry().get_tool("preprint_search")
    assert tool_config is not None
    envelope = {
        "source": "Preprints",
        "query": "NHE1 in cancer",
        "records": [
            {
                "source_id": "PPR/1234567",
                "title": "NHE1 regulation of tumour pH",
                "abstract": "A preprint on pH regulation.",
                "year": "2026",
                "url": "https://europepmc.org/article/PPR/1234567",
            }
        ],
    }

    articles = ResponseParser(tool_config).parse_to_articles(envelope)

    assert [article.title for article in articles] == [
        "NHE1 regulation of tumour pH"
    ]


def test_gwas_catalog_associations_are_available_to_draft_tool_calls() -> None:
    """The rsID lookup must reach the actual draft-generation MCP whitelist."""
    registry = ToolRegistry(skip_user_config=True)

    tool_ids = registry.get_tools_for_workflow("draft_generation")
    assert "gwas_catalog_associations" in tool_ids
    assert "search_gwas_catalog_associations" in registry.get_mcp_tool_names(
        tool_ids
    )
