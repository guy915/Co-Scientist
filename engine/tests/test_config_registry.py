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
    parse_bool_env,
    reset_tool_registry,
    substitute_env_vars,
)
from co_scientist.evidence.search_support import normalize_search_response
from co_scientist.exceptions import ConfigError
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


def test_tool_fields_parse_with_defaults(
    _config_registry_registry: ToolRegistry,
) -> None:
    alpha = _config_registry_registry.get_tool("alpha_search")
    assert alpha is not None
    assert alpha.server == "myserver"
    assert alpha.mcp_tool_name == "search_alpha"
    assert alpha.display_name == "Alpha Search"
    assert alpha.category == "search"
    assert alpha.enabled is True

    beta = _config_registry_registry.get_tool("beta_search")
    assert beta is not None
    assert beta.display_name == "beta_search"
    assert beta.category == "utility"
    assert beta.enabled is False


def test_unknown_tool_returns_none(
    _config_registry_registry: ToolRegistry,
) -> None:
    assert _config_registry_registry.get_tool("no_such_tool") is None


def test_get_enabled_servers_filters_disabled(
    _config_registry_registry: ToolRegistry,
) -> None:
    assert set(_config_registry_registry.get_enabled_servers()) == {"myserver"}
    off = _config_registry_registry.get_server("offserver")
    assert off is not None and off.enabled is False


def test_server_configs_for_langchain_shape(
    _config_registry_registry: ToolRegistry,
) -> None:
    assert _config_registry_registry.get_server_configs_for_langchain() == {
        "myserver": {
            "transport": "streamable_http",
            "url": "http://example.test/mcp",
        }
    }


def test_get_enabled_tools_excludes_disabled(
    _config_registry_registry: ToolRegistry,
) -> None:
    assert set(_config_registry_registry.get_enabled_tools()) == {
        "alpha_search",
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


def test_get_tools_for_unknown_workflow_returns_empty(
    _config_registry_registry: ToolRegistry,
) -> None:
    assert (
        _config_registry_registry.get_tools_for_workflow("does_not_exist") == []
    )


def test_get_workflow_returns_config_or_none(
    _config_registry_registry: ToolRegistry,
) -> None:
    workflow = _config_registry_registry.get_workflow("literature_review")
    assert workflow is not None
    assert workflow.primary_search == "alpha_search"
    assert workflow.fallback_search == "beta_search"
    assert workflow.availability_check == "gamma_util"
    assert _config_registry_registry.get_workflow("does_not_exist") is None


def test_get_mcp_tool_names_maps_and_drops_disabled(
    _config_registry_registry: ToolRegistry,
) -> None:
    names = _config_registry_registry.get_mcp_tool_names(
        ["alpha_search", "beta_search", "gamma_util"]
    )
    assert names == ["search_alpha", "util_gamma"]


def test_get_mcp_tool_names_ignores_unknown_ids(
    _config_registry_registry: ToolRegistry,
) -> None:
    assert _config_registry_registry.get_mcp_tool_names(
        ["nope", "alpha_search"]
    ) == [
        "search_alpha",
    ]


def test_get_tool_by_mcp_name(_config_registry_registry: ToolRegistry) -> None:
    found = _config_registry_registry.get_tool_by_mcp_name("util_gamma")
    assert found is not None and found.display_name == "gamma_util"
    assert (
        _config_registry_registry.get_tool_by_mcp_name("absent_mcp_name")
        is None
    )


def test_get_enrichment_configs_filters_by_workflow(
    _config_registry_registry: ToolRegistry,
) -> None:
    generation = _config_registry_registry.get_enrichment_configs("generation")
    assert [e.output_key for e in generation] == ["gamma_out"]

    reflection = _config_registry_registry.get_enrichment_configs("reflection")
    assert [e.output_key for e in reflection] == ["alpha_out"]

    every = _config_registry_registry.get_enrichment_configs("all")
    assert [e.output_key for e in every] == ["gamma_out", "alpha_out"]


def test_get_prompts_config_parses_domain_fields(
    _config_registry_registry: ToolRegistry,
) -> None:
    prompts = _config_registry_registry.get_prompts_config()
    assert prompts.domain_context == "test domain context"
    assert prompts.generation_guidance == "test generation guidance"
    assert prompts.review_guidance == ""


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


def test_config_property_raises_when_uninitialized(
    _config_registry_registry: ToolRegistry,
) -> None:
    _config_registry_registry._config = None
    with pytest.raises(ConfigError):
        _ = _config_registry_registry.config


def test_substitute_env_vars_set_default_and_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COS_TEST_VAR", "hello")
    monkeypatch.delenv("COS_TEST_MISSING", raising=False)

    assert substitute_env_vars("a-${COS_TEST_VAR}-b") == "a-hello-b"
    assert substitute_env_vars("${COS_TEST_MISSING:-fallback}") == "fallback"
    assert substitute_env_vars("${COS_TEST_MISSING}") == ""


def test_substitute_env_vars_recurses_into_containers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COS_TEST_VAR", "X")
    result = substitute_env_vars(
        {
            "url": "${COS_TEST_VAR}",
            "items": ["${COS_TEST_VAR}", 5],
            "flag": True,
        }
    )
    assert result == {"url": "X", "items": ["X", 5], "flag": True}


def test_parse_bool_env_truthy_and_falsy() -> None:
    assert parse_bool_env("true") is True
    assert parse_bool_env("TRUE") is True
    assert parse_bool_env("1") is True
    assert parse_bool_env("yes") is True
    assert parse_bool_env("on") is True
    assert parse_bool_env("false") is False
    assert parse_bool_env("no") is False
    assert parse_bool_env("") is False
    assert parse_bool_env("maybe") is False


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


def test_disabled_tools_argument_flips_enabled(tmp_path: Path) -> None:
    path = _write_config(tmp_path, _REPLACE_CONFIG)
    registry = ToolRegistry(
        config_path=path,
        skip_user_config=True,
        disabled_tools=["alpha_search"],
    )
    alpha = registry.get_tool("alpha_search")
    assert alpha is not None and alpha.enabled is False
    assert registry.get_tools_for_workflow("literature_review") == [
        "gamma_util",
    ]


def test_disabled_tools_also_disables_its_search_source(
    tmp_path: Path,
) -> None:
    """Search selects source flags without consulting the underlying tool
    flag."""
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
    """Source reconciliation covers YAML-disabled and undefined tools too."""
    path = _write_config(tmp_path, _YAML_DISABLED_CONFIG)

    registry = ToolRegistry(config_path=path, skip_user_config=True)
    workflow = registry.get_workflow("literature_review")
    assert workflow is not None
    assert [s.tool for s in workflow.get_enabled_search_sources()] == [
        "alpha_search",
    ]


def test_europepmc_results_normalize_into_individual_papers() -> None:
    """Europe PMC returns records inside an envelope, not a paper-id map."""
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
    """Without records extraction, envelope keys silently become titleless
    papers."""
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


def _tool(registry: ToolRegistry, tool_id: str) -> ToolConfig:
    tool_config = registry.get_tool(tool_id)
    assert tool_config is not None, f"{tool_id} must be configured"
    return tool_config


@pytest.mark.parametrize(
    ("tool_id", "envelope", "expected_source_id"),
    [
        ("arxiv_search", _arxiv_envelope(), "2401.01234"),
        ("biorxiv_search", _biorxiv_envelope(), "PPR/42387642"),
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
