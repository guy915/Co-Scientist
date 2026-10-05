from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

from co_scientist.agents.generation.literature_tools.validate import (
    _NoveltySearchContext,
    _search_papers_via_tool_config,
)
from co_scientist.config import ToolConfig, ToolRegistry
from co_scientist.config.registry import (
    get_tool_registry,
    reset_tool_registry,
    substitute_env_vars,
)
from co_scientist.evidence.search_support import normalize_search_response
from tests._mcp import FakeCallToolClient
from tests._research_fakes import REPLACE_CONFIG as _REPLACE_CONFIG
from tests._research_fakes import write_config as _write_config


@pytest.fixture()
def _config_registry_registry(tmp_path: Path) -> ToolRegistry:
    path = _write_config(tmp_path, _REPLACE_CONFIG)
    return ToolRegistry(config_path=path, skip_user_config=True)


def test_replace_strategy_yields_only_custom_config(
    _config_registry_registry: ToolRegistry,
) -> None:
    assert _config_registry_registry.config.version == "2.0"
    assert set(_config_registry_registry.config.servers) == {
        "myserver",
        "offserver",
    }
    assert _config_registry_registry.get_tool("pubmed_search") is None
    assert set(_config_registry_registry.config.get_all_tools()) == {
        "alpha_search",
        "beta_search",
        "gamma_util",
    }


def test_get_tools_for_workflow_returns_enabled_ids(
    _config_registry_registry: ToolRegistry,
) -> None:
    assert _config_registry_registry.get_tools_for_workflow(
        "literature_review"
    ) == [
        "alpha_search",
        "gamma_util",
    ]
    assert _config_registry_registry.get_tools_for_workflow(
        "draft_generation"
    ) == [
        "alpha_search",
    ]


def test_get_mcp_tool_names_maps_and_drops_disabled(
    _config_registry_registry: ToolRegistry,
) -> None:
    names = _config_registry_registry.get_mcp_tool_names(
        ["alpha_search", "beta_search", "gamma_util"]
    )
    assert names == ["search_alpha", "util_gamma"]


def test_get_enrichment_configs_filters_by_workflow(
    _config_registry_registry: ToolRegistry,
) -> None:
    generation = _config_registry_registry.get_enrichment_configs("generation")
    assert [e.output_key for e in generation] == ["gamma_out"]

    reflection = _config_registry_registry.get_enrichment_configs("reflection")
    assert [e.output_key for e in reflection] == ["alpha_out"]

    every = _config_registry_registry.get_enrichment_configs("all")
    assert [e.output_key for e in every] == ["gamma_out", "alpha_out"]


def test_override_merge_keeps_defaults_and_adds_custom(tmp_path: Path) -> None:
    custom = textwrap.dedent("""
        tools:
          search_tools:
            custom_search:
              server: "default_pubmed"
              mcp_tool_name: "search_custom"
              enabled: true
        """)
    path = _write_config(tmp_path, custom)
    _config_registry_registry = ToolRegistry(
        config_path=path, skip_user_config=True
    )
    custom_tool = _config_registry_registry.get_tool("custom_search")
    assert custom_tool is not None
    assert custom_tool.mcp_tool_name == "search_custom"
    assert _config_registry_registry.get_tool("pubmed_search") is not None


def test_extend_merge_strategy_appends_to_default_lists(
    tmp_path: Path,
) -> None:
    custom = textwrap.dedent("""
        settings:
          merge_strategy: "extend"
        workflows:
          literature_review:
            search_sources:
              - tool: "custom_search"
                enabled: true
        """)
    path = _write_config(tmp_path, custom)
    registry = ToolRegistry(config_path=path, skip_user_config=True)
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None
    tools = [s.tool for s in workflow.search_sources]
    assert tools[0] == "pubmed_fulltext"
    assert tools[-1] == "custom_search"


def test_string_enabled_values_parse_to_bools(tmp_path: Path) -> None:
    config = textwrap.dedent("""
        servers:
          s1:
            url: "http://x.test"
            enabled: "false"
        tools:
          search_tools:
            t1:
              server: "s1"
              mcp_tool_name: "m1"
              enabled: "true"
            t2:
              server: "s1"
              mcp_tool_name: "m2"
              enabled: "no"
        settings:
          merge_strategy: "replace"
        """)
    path = _write_config(tmp_path, config)
    _config_registry_registry = ToolRegistry(
        config_path=path, skip_user_config=True
    )

    server = _config_registry_registry.get_server("s1")
    assert server is not None and server.enabled is False

    tool_one = _config_registry_registry.get_tool("t1")
    assert tool_one is not None and tool_one.enabled is True

    tool_two = _config_registry_registry.get_tool("t2")
    assert tool_two is not None and tool_two.enabled is False


def test_malformed_config_falls_back_to_default(tmp_path: Path) -> None:
    path = _write_config(tmp_path, "this: is: : not valid: yaml: :\n  - x")
    _config_registry_registry = ToolRegistry(
        config_path=path, skip_user_config=True
    )
    assert _config_registry_registry.get_tool("pubmed_search") is not None


def test_substitute_env_vars_set_default_and_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COS_TEST_VAR", "hello")
    monkeypatch.delenv("COS_TEST_MISSING", raising=False)

    assert substitute_env_vars("a-${COS_TEST_VAR}-b") == "a-hello-b"
    assert substitute_env_vars("${COS_TEST_MISSING:-fallback}") == "fallback"
    assert substitute_env_vars("${COS_TEST_MISSING}") == ""


def test_get_tool_registry_caches_and_force_reloads(tmp_path: Path) -> None:
    path = _write_config(tmp_path, _REPLACE_CONFIG)
    reset_tool_registry()
    try:
        first = get_tool_registry(config_path=path)
        assert get_tool_registry() is first
        reloaded = get_tool_registry(config_path=path, force_reload=True)
        assert reloaded is not first
    finally:
        # Restore global state so other tests/modules are unaffected.
        reset_tool_registry()


_SOURCE_CONFIG = textwrap.dedent("""
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
        gamma_search:
          server: "myserver"
          mcp_tool_name: "search_gamma"
          enabled: false
    workflows:
      literature_review:
        search_sources:
          - tool: "alpha_search"
            enabled: true
          - tool: "beta_search"
            enabled: true
          - tool: "gamma_search"
            enabled: true
          - tool: "ghost_search"
            enabled: true
""")


def _enabled_sources(tmp_path: Path, **kwargs: Any) -> list[str]:
    registry = ToolRegistry(
        config_path=_write_config(tmp_path, _SOURCE_CONFIG),
        skip_user_config=True,
        **kwargs,
    )
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None
    return [s.tool for s in workflow.get_enabled_search_sources()]


def test_disabled_tools_argument_removes_tool_from_workflows(
    tmp_path: Path,
) -> None:
    registry = ToolRegistry(
        config_path=_write_config(tmp_path, _REPLACE_CONFIG),
        skip_user_config=True,
        disabled_tools=["alpha_search"],
    )
    assert registry.get_tools_for_workflow("literature_review") == [
        "gamma_util",
    ]


def test_yaml_disabled_or_missing_tool_disables_its_search_source(
    tmp_path: Path,
) -> None:
    """Source reconciliation covers YAML-disabled and undefined tools too."""
    assert _enabled_sources(tmp_path) == ["alpha_search", "beta_search"]


def test_disabled_tools_argument_disables_tool_and_its_search_source(
    tmp_path: Path,
) -> None:
    """Search selects source flags without consulting the underlying tool
    flag."""
    sources = _enabled_sources(tmp_path, disabled_tools=["alpha_search"])
    assert sources == ["beta_search"]


def test_gwas_catalog_associations_are_available_to_draft_tool_calls() -> None:
    registry = ToolRegistry(skip_user_config=True)

    tool_ids = registry.get_tools_for_workflow("draft_generation")
    assert "gwas_catalog_associations" in tool_ids
    assert "search_gwas_catalog_associations" in registry.get_mcp_tool_names(
        tool_ids
    )


@pytest.fixture(scope="module")
def _arxiv_biorxiv_search_sources_registry() -> ToolRegistry:
    return ToolRegistry(skip_user_config=True)


def _arxiv_envelope() -> dict[str, Any]:
    return {
        "source": "arXiv",
        "query": "resistance reversal",
        "records": [
            {
                "source_id": "2401.01234",
                "title": "A Model of Resistance Reversal",
                "abstract": "An abstract.",
                "year": 2024,
                "authors": ["Jane Doe"],
                "doi": None,
                "is_preprint": True,
                "url": "http://arxiv.org/abs/2401.01234v2",
            }
        ],
    }


def _biorxiv_envelope() -> dict[str, Any]:
    return {
        "source": "bioRxiv",
        "query": "resistance reversal",
        "records": [
            {
                "source_id": "PPR/42387642",
                "title": "PKMYT1 in Cancer",
                "abstract": "PKMYT1 has emerged as a target.",
                "year": "2026",
                "authors": "Li Y, Chen X.",
                "doi": "10.1002/gcc.70151",
                "is_preprint": True,
                "url": "https://doi.org/10.1002/gcc.70151",
            }
        ],
    }


def _preprint_envelope(source: str) -> dict[str, Any]:
    return {
        "source": source,
        "query": "NHE1 in cancer",
        "records": [
            {
                "source_id": "PPR/1234567",
                "title": "NHE1 regulation of tumour pH",
                "abstract": "A preprint on pH regulation.",
                "year": "2026",
                "is_preprint": True,
                "url": "https://europepmc.org/article/PPR/1234567",
            }
        ],
    }


def _tool(registry: ToolRegistry, tool_id: str) -> ToolConfig:
    tool_config = registry.get_tool(tool_id)
    assert tool_config is not None, f"{tool_id} must be configured"
    return tool_config


@pytest.mark.parametrize(
    ("tool_id", "envelope", "expected_source_id"),
    [
        ("arxiv_search", _arxiv_envelope(), "2401.01234"),
        ("biorxiv_search", _biorxiv_envelope(), "PPR/42387642"),
        ("europepmc_search", _preprint_envelope("Europe PMC"), "PPR/1234567"),
        ("preprint_search", _preprint_envelope("Preprints"), "PPR/1234567"),
    ],
)
def test_the_envelope_normalizes_for_literature_review(
    _arxiv_biorxiv_search_sources_registry: ToolRegistry,
    tool_id: str,
    envelope: dict[str, Any],
    expected_source_id: str,
) -> None:
    """Without records extraction, envelope keys masquerade as paper ids."""
    normalized = normalize_search_response(
        envelope, _tool(_arxiv_biorxiv_search_sources_registry, tool_id)
    )

    assert expected_source_id in normalized
    assert normalized[expected_source_id]["title"]


@pytest.mark.parametrize(
    ("tool_id", "envelope", "expected_title"),
    [
        ("arxiv_search", _arxiv_envelope(), "A Model of Resistance Reversal"),
        ("biorxiv_search", _biorxiv_envelope(), "PKMYT1 in Cancer"),
        (
            "europepmc_search",
            _preprint_envelope("Europe PMC"),
            "NHE1 regulation of tumour pH",
        ),
        (
            "preprint_search",
            _preprint_envelope("Preprints"),
            "NHE1 regulation of tumour pH",
        ),
    ],
)
async def test_the_envelope_parses_for_validation(
    _arxiv_biorxiv_search_sources_registry: ToolRegistry,
    tool_id: str,
    envelope: dict[str, Any],
    expected_title: str,
) -> None:
    """Malformed validation entries are skipped; broken envelopes fail
    silently."""
    mcp_client = FakeCallToolClient(envelope)

    papers = await _search_papers_via_tool_config(
        _tool(_arxiv_biorxiv_search_sources_registry, tool_id),
        "hypothesis text",
        _NoveltySearchContext(
            mcp_client=mcp_client,
            tool_registry=None,
            shared_slug="slug-1",
            run_id="run-1",
        ),
        max_papers=5,
    )

    assert papers, "a real envelope must not parse to zero papers"
    (paper,) = papers.values()
    assert paper["title"] == expected_title
