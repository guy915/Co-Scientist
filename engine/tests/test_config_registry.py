"""Offline contracts for config registry."""

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
    """A registry built from ``_REPLACE_CONFIG`` with no default/user merge."""
    path = _write_config(tmp_path, _REPLACE_CONFIG)
    return ToolRegistry(config_path=path, skip_user_config=True)


# --- Parsing: servers, tools, and field defaults --------------------------


def test_replace_strategy_yields_only_custom_config(
    _config_registry_registry: ToolRegistry,
) -> None:
    """``merge_strategy: replace`` drops the bundled defaults entirely."""
    assert _config_registry_registry.config.version == "2.0"
    assert set(_config_registry_registry.config.servers) == {
        "myserver",
        "offserver",
    }
    # The default tools.yaml ships ``pubmed_search``; replace must remove it.
    assert _config_registry_registry.get_tool("pubmed_search") is None
    assert set(_config_registry_registry.config.get_all_tools()) == {
        "alpha_search",
        "beta_search",
        "gamma_util",
    }


def test_tool_fields_parse_with_defaults(
    _config_registry_registry: ToolRegistry,
) -> None:
    """Tool dicts parse into ToolConfig, with documented field defaults."""
    alpha = _config_registry_registry.get_tool("alpha_search")
    assert alpha is not None
    assert alpha.server == "myserver"
    assert alpha.mcp_tool_name == "search_alpha"
    assert alpha.display_name == "Alpha Search"
    assert alpha.category == "search"
    assert alpha.enabled is True

    # beta omits display_name -> it defaults to the YAML tool id, and omits
    # category -> defaults to "utility".
    beta = _config_registry_registry.get_tool("beta_search")
    assert beta is not None
    assert beta.display_name == "beta_search"
    assert beta.category == "utility"
    assert beta.enabled is False


def test_unknown_tool_returns_none(
    _config_registry_registry: ToolRegistry,
) -> None:
    """Looking up a tool id that is not configured returns None."""
    assert _config_registry_registry.get_tool("no_such_tool") is None


# --- Server queries -------------------------------------------------------


def test_get_enabled_servers_filters_disabled(
    _config_registry_registry: ToolRegistry,
) -> None:
    """Only servers with ``enabled: true`` are returned."""
    assert set(_config_registry_registry.get_enabled_servers()) == {"myserver"}
    off = _config_registry_registry.get_server("offserver")
    assert off is not None and off.enabled is False


def test_server_configs_for_langchain_shape(
    _config_registry_registry: ToolRegistry,
) -> None:
    """Langchain mapping contains transport+url for enabled servers only."""
    assert _config_registry_registry.get_server_configs_for_langchain() == {
        "myserver": {
            "transport": "streamable_http",
            "url": "http://example.test/mcp",
        }
    }


# --- Enabled-tool queries -------------------------------------------------


def test_get_enabled_tools_excludes_disabled(
    _config_registry_registry: ToolRegistry,
) -> None:
    """``beta_search`` is disabled and must not appear in enabled tools."""
    assert set(_config_registry_registry.get_enabled_tools()) == {
        "alpha_search",
        "gamma_util",
    }


# --- Workflow queries -----------------------------------------------------


def test_get_tools_for_workflow_returns_enabled_ids(
    _config_registry_registry: ToolRegistry,
) -> None:
    """Workflow tool lists are filtered down to enabled tools only.

    literature_review references alpha (enabled), beta (disabled), and gamma
    (enabled); the disabled beta is dropped.
    """
    assert _config_registry_registry.get_tools_for_workflow(
        "literature_review"
    ) == [
        "alpha_search",
        "gamma_util",
    ]
    # draft_generation lists alpha + beta; only the enabled alpha survives.
    assert _config_registry_registry.get_tools_for_workflow(
        "draft_generation"
    ) == [
        "alpha_search",
    ]


def test_get_tools_for_unknown_workflow_returns_empty(
    _config_registry_registry: ToolRegistry,
) -> None:
    """An unknown workflow name resolves to an empty list (documented)."""
    assert (
        _config_registry_registry.get_tools_for_workflow("does_not_exist") == []
    )


def test_get_workflow_returns_config_or_none(
    _config_registry_registry: ToolRegistry,
) -> None:
    """``get_workflow`` returns the parsed WorkflowConfig or None."""
    workflow = _config_registry_registry.get_workflow("literature_review")
    assert workflow is not None
    assert workflow.primary_search == "alpha_search"
    assert workflow.fallback_search == "beta_search"
    assert workflow.availability_check == "gamma_util"
    assert _config_registry_registry.get_workflow("does_not_exist") is None


# --- MCP-name mapping -----------------------------------------------------


def test_get_mcp_tool_names_maps_and_drops_disabled(
    _config_registry_registry: ToolRegistry,
) -> None:
    """IDs map to mcp_tool_name; disabled tools are skipped, order preserved."""
    names = _config_registry_registry.get_mcp_tool_names(
        ["alpha_search", "beta_search", "gamma_util"]
    )
    # beta_search is disabled -> dropped, leaving alpha + gamma in order.
    assert names == ["search_alpha", "util_gamma"]


def test_get_mcp_tool_names_ignores_unknown_ids(
    _config_registry_registry: ToolRegistry,
) -> None:
    """Unknown tool ids are silently skipped."""
    assert _config_registry_registry.get_mcp_tool_names(
        ["nope", "alpha_search"]
    ) == [
        "search_alpha",
    ]


def test_get_tool_by_mcp_name(_config_registry_registry: ToolRegistry) -> None:
    """Reverse lookup finds a tool by its MCP name, or returns None."""
    found = _config_registry_registry.get_tool_by_mcp_name("util_gamma")
    assert found is not None and found.display_name == "gamma_util"
    assert (
        _config_registry_registry.get_tool_by_mcp_name("absent_mcp_name")
        is None
    )


# --- Enrichment queries ---------------------------------------------------


def test_get_enrichment_configs_filters_by_workflow(
    _config_registry_registry: ToolRegistry,
) -> None:
    """Enrichments are filtered by ``enabled`` and ``workflow`` phase."""
    generation = _config_registry_registry.get_enrichment_configs("generation")
    assert [e.output_key for e in generation] == ["gamma_out"]

    reflection = _config_registry_registry.get_enrichment_configs("reflection")
    assert [e.output_key for e in reflection] == ["alpha_out"]

    # "all" returns every *enabled* enrichment regardless of phase; the
    # disabled beta_out enrichment is excluded.
    every = _config_registry_registry.get_enrichment_configs("all")
    assert [e.output_key for e in every] == ["gamma_out", "alpha_out"]


# --- prompts config -------------------------------------------------------


def test_get_prompts_config_parses_domain_fields(
    _config_registry_registry: ToolRegistry,
) -> None:
    """The domain-specific prompts section parses into a PromptsConfig."""
    prompts = _config_registry_registry.get_prompts_config()
    assert prompts.domain_context == "test domain context"
    assert prompts.generation_guidance == "test generation guidance"
    # Unset fields default to empty strings.
    assert prompts.review_guidance == ""


# --- override merge strategy (default) ------------------------------------


def test_override_merge_keeps_defaults_and_adds_custom(tmp_path: Path) -> None:
    """Without ``replace``, custom tools are added on top of the defaults."""
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
    # The custom tool is present...
    custom_tool = _config_registry_registry.get_tool("custom_search")
    assert custom_tool is not None
    assert custom_tool.mcp_tool_name == "search_custom"
    # ...and the bundled default tool is still present (merge, not replace).
    assert _config_registry_registry.get_tool("pubmed_search") is not None


# --- string-boolean env values (_parse_enabled_values) --------------------


def test_string_enabled_values_parse_to_bools(tmp_path: Path) -> None:
    """``enabled`` given as a string (e.g. from an env var) becomes a bool."""
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


# --- malformed config: silent fallback to default -------------------------


def test_malformed_config_falls_back_to_default(tmp_path: Path) -> None:
    """A syntactically broken config is swallowed; defaults load instead.

    ``_load_yaml_file`` catches the YAML parse error and returns None, so the
    custom config is treated as absent and the registry serves the bundled
    default ``tools.yaml`` (which defines ``pubmed_search``).
    """
    path = _write_config(tmp_path, "this: is: : not valid: yaml: :\n  - x")
    _config_registry_registry = ToolRegistry(
        config_path=path, skip_user_config=True
    )
    assert _config_registry_registry.get_tool("pubmed_search") is not None


# --- ConfigError guard ----------------------------------------------------


def test_config_property_raises_when_uninitialized(
    _config_registry_registry: ToolRegistry,
) -> None:
    """The ``config`` property raises ConfigError when state is missing.

    This is the only path in the registry that raises ConfigError. Malformed
    files do not raise (they fall back); they only leave ``_config`` unset if it
    were never loaded, which we simulate here.
    """
    _config_registry_registry._config = None
    with pytest.raises(ConfigError):
        _ = _config_registry_registry.config


# --- module-level helpers -------------------------------------------------


def test_substitute_env_vars_set_default_and_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``${VAR}`` / ``${VAR:-default}`` expand from env, default, or empty."""
    monkeypatch.setenv("COS_TEST_VAR", "hello")
    monkeypatch.delenv("COS_TEST_MISSING", raising=False)

    assert substitute_env_vars("a-${COS_TEST_VAR}-b") == "a-hello-b"
    assert substitute_env_vars("${COS_TEST_MISSING:-fallback}") == "fallback"
    # No env var and no default -> empty string.
    assert substitute_env_vars("${COS_TEST_MISSING}") == ""


def test_substitute_env_vars_recurses_into_containers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Substitution recurses through dicts and lists; leaves non-strings."""
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
    """Only a known set of strings parse to True; everything else is False."""
    assert parse_bool_env("true") is True
    assert parse_bool_env("TRUE") is True
    assert parse_bool_env("1") is True
    assert parse_bool_env("yes") is True
    assert parse_bool_env("on") is True
    assert parse_bool_env("false") is False
    assert parse_bool_env("no") is False
    assert parse_bool_env("") is False
    assert parse_bool_env("maybe") is False


# --- global registry singleton --------------------------------------------


def test_get_tool_registry_caches_and_force_reloads(tmp_path: Path) -> None:
    """The module-global registry is cached and rebuilt on force_reload.

    Identity is asserted (not contents) so the test stays deterministic even
    though ``get_tool_registry`` has no ``skip_user_config`` knob.
    """
    path = _write_config(tmp_path, _REPLACE_CONFIG)
    reset_tool_registry()
    try:
        first = get_tool_registry(config_path=path)
        # A subsequent call without force_reload returns the same instance.
        assert get_tool_registry() is first
        # force_reload builds a fresh instance.
        reloaded = get_tool_registry(config_path=path, force_reload=True)
        assert reloaded is not first
    finally:
        # Restore global state so other tests/modules are unaffected.
        reset_tool_registry()


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


@pytest.fixture(scope="module")
def _arxiv_biorxiv_search_sources_registry() -> ToolRegistry:
    """The shipped default tool/workflow configuration."""
    return ToolRegistry(skip_user_config=True)


def _arxiv_envelope() -> dict[str, Any]:
    """A response shaped exactly like the reference server's search_arxiv."""
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
    """A response shaped exactly like the reference server's search_biorxiv."""
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
    """Phase 2's normalizer re-keys the envelope's records by source_id.

    Without ``results_path: "records"`` the three envelope keys
    (source/query/records) would be taken for paper ids and every real
    record dropped.
    """
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
    """Validation's ResponseParser reads the same envelope to a paper dict.

    Unlike literature review, a missing/wrong results_path here degrades
    silently: the parser logs and skips a titleless item rather than
    raising, so a broken config would just report "nothing found" instead
    of failing loudly -- this drives the actual production call path
    (``_search_papers_via_tool_config``) rather than the parser alone.
    """
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
