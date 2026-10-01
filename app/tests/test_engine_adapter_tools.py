"""Tests for tools-config wiring: adapter forwarding, validation, /status.

Production sets ``TOOLS_CONFIG=...indra_cancer.yaml`` but the app adapter never
forwarded it to ``HypothesisGenerator``, so real runs silently ran the default
(PubMed-only) tools. These pin the forwarding, the loud startup validation of a
misconfigured path, and the /status disclosure of the effective tools config.
"""

from __future__ import annotations

import pathlib
from typing import Any, ClassVar

import pytest

from app.config import settings
from app.engine_adapter.opts import build_generator
from app.engine_adapter.tools import (
    connectors_report,
    tools_config_report,
    validate_tools_config,
)

# The engine ships this example config; a real, readable local YAML to
# validate/enumerate against without needing a network fetch.
_INDRA_CONFIG = str(
    pathlib.Path(__file__).resolve().parents[2]
    / "engine"
    / "src"
    / "co_scientist"
    / "config"
    / "examples"
    / "indra_cancer.yaml"
)


def _cfg() -> dict[str, Any]:
    """A resolved run-config dict with the numeric keys the adapter reads.

    Mirrors the ``resolved_run_config`` contract: every numeric key is
    present, so the adapter indexes directly instead of re-inventing
    defaults.
    """
    return {
        "max_iterations": 1,
        "initial_hypotheses_count": 4,
        "evolution_max_count": 4,
        "tournament_pairs": 6,
        "evidence_count": 4,
        "k_factor": 36,
        "max_llm_calls": 100,
        # The Supervisor listing's own two loop predicates, sized as the
        # express tier sizes them for the numbers above.
        "max_ideas": 12,
        "max_matches_per_idea": 4,
    }


class _FakeGenerator:
    """Captures the kwargs the adapter passes to HypothesisGenerator."""

    last_kwargs: ClassVar[dict[str, Any]] = {}

    def __init__(self, **kwargs: Any) -> None:
        _FakeGenerator.last_kwargs = kwargs


def test_build_generator_forwards_configured_tools_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured tools_config reaches HypothesisGenerator."""
    monkeypatch.setattr(settings, "tools_config", _INDRA_CONFIG)
    build_generator(_FakeGenerator, _cfg())
    assert _FakeGenerator.last_kwargs["options"].tools_config == _INDRA_CONFIG


def test_build_generator_forwards_none_tools_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unset tools_config forwards None (engine uses its defaults)."""
    monkeypatch.setattr(settings, "tools_config", None)
    build_generator(_FakeGenerator, _cfg())
    assert _FakeGenerator.last_kwargs["options"].tools_config is None


def test_build_generator_forwards_run_elo_k_factor() -> None:
    """The persisted run K-factor governs real-engine Elo updates."""
    build_generator(_FakeGenerator, _cfg())
    assert _FakeGenerator.last_kwargs["options"].elo_k_factor == 36


# --- offline cache scoping ---------------------------------------------


def test_build_generator_offline_disables_cache_without_env_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``offline=True`` disables caching for that run without touching env.

    Regression test for a production incident: the offline/demo generator
    used to be constructed through a ``HypothesisGenerator`` whose
    constructor mutated ``COSCIENTIST_CACHE_ENABLED`` as a side effect of
    ``enable_cache=False``; since ``co_scientist.cache.get_cache()``
    memoizes that env var once per process, the embedded worker's first
    generator built (often this offline one, at startup demo-seeding) could
    silently disable caching for every later real run. ``build_generator``
    forwards ``enable_cache=False`` as a plain constructor kwarg; this pins
    that no env mutation reappears at this boundary.
    """
    monkeypatch.delenv("COSCIENTIST_CACHE_ENABLED", raising=False)
    build_generator(_FakeGenerator, _cfg(), offline=True)
    assert _FakeGenerator.last_kwargs["options"].enable_cache is False
    import os

    assert "COSCIENTIST_CACHE_ENABLED" not in os.environ


def test_offline_generator_does_not_poison_cache_for_a_real_generator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An offline build, then a real build, in the same process.

    Uses the real engine ``HypothesisGenerator`` (rather than the
    kwarg-capturing fake above) to reproduce the exact production sequence:
    the embedded worker's first generator is the offline/demo one, and a
    real run's generator is constructed afterward in the same process. The
    real run must see the process's genuine ``COSCIENTIST_CACHE_ENABLED``
    default, never whatever the offline generator's own
    ``enable_cache=False`` happened to be.
    """
    from co_scientist import cache as engine_cache
    from co_scientist.generator import HypothesisGenerator

    monkeypatch.setenv("COSCIENTIST_CACHE_ENABLED", "true")
    monkeypatch.setattr(engine_cache, "_global_cache", None)

    build_generator(HypothesisGenerator, _cfg(), offline=True)
    import os

    assert os.environ["COSCIENTIST_CACHE_ENABLED"] == "true"
    assert engine_cache.get_cache().enabled is True


def test_validate_tools_config_accepts_none() -> None:
    """No configured tools_config is valid (defaults apply)."""
    validate_tools_config(None)  # must not raise


def test_validate_tools_config_accepts_readable_path() -> None:
    """A readable local YAML path validates."""
    validate_tools_config(_INDRA_CONFIG)  # must not raise


def test_validate_tools_config_accepts_url() -> None:
    """A URL is passed through without a local-file check."""
    validate_tools_config("https://example.com/tools.yaml")  # must not raise


def test_validate_tools_config_raises_on_unreadable_path() -> None:
    """A configured local path that does not exist fails loudly."""
    with pytest.raises(RuntimeError, match="tools_config"):
        validate_tools_config("/no/such/tools.yaml")


def test_tools_config_report_enumerates_enabled_tools() -> None:
    """The /status report resolves a readable config to its enabled tools."""
    report = tools_config_report(_INDRA_CONFIG)
    assert report["tools_config"] == _INDRA_CONFIG
    assert report["tools_config_valid"] is True
    assert "indra_statements" in report["enabled_tools"]


def test_tools_config_report_marks_bad_path_invalid() -> None:
    """A misconfigured path is reported invalid with no enabled tools."""
    report = tools_config_report("/no/such/tools.yaml")
    assert report["tools_config_valid"] is False
    assert report["enabled_tools"] is None


def test_tools_config_report_none_enumerates_the_bundled_default() -> None:
    """N10: an unset config is not "nothing to report".

    The engine still runs a determinate set, its own bundled default, and
    /status must name it so a deployment that never set TOOLS_CONFIG is
    visibly running the default rather than reading as broken next to
    "MCP/PubMed up".

    A production api service that never set TOOLS_CONFIG reported
    ``enabled_tools: null``, indistinguishable from "nothing is known" --
    when the engine was in fact running a real, enumerable default that
    simply excludes the domain-specific tools (e.g. INDRA CoGex) a custom
    config would add. INDRA absence pins that the default is genuinely
    the bundled tools.yaml, not the INDRA example.
    """
    report = tools_config_report(None)
    assert report["tools_config"] is None
    assert report["tools_config_valid"] is True
    assert report["enabled_tools"] is not None
    assert "pubmed_search" in report["enabled_tools"]
    assert "indra_statements" not in report["enabled_tools"]


def test_build_generator_enables_web_search_by_default() -> None:
    """A config without the toggle keeps web search on."""
    build_generator(_FakeGenerator, _cfg())
    assert _FakeGenerator.last_kwargs["options"].disable_tools == []


def test_build_generator_disables_web_search_when_toggled_off() -> None:
    """Turning the connector off disables the engine's web_search tool."""
    cfg = _cfg() | {"enable_web_search": False}
    build_generator(_FakeGenerator, cfg)
    assert _FakeGenerator.last_kwargs["options"].disable_tools == [
        "web_search",
    ]


def test_disabling_web_search_keeps_read_url() -> None:
    """read_url is the shared content-fetch tool and must survive.

    It is the ``content_tool`` for PDF/full-text retrieval in the arXiv,
    Google Scholar, and web configs, so disabling it with web search would
    break literature retrieval for unrelated sources.
    """
    cfg = _cfg() | {"enable_web_search": False}
    build_generator(_FakeGenerator, cfg)
    assert "read_url" not in _FakeGenerator.last_kwargs["options"].disable_tools


def test_connectors_report_lists_web_search_when_available() -> None:
    """The connector appears on live availability, with no tools config.

    enabled_tools is None whenever TOOLS_CONFIG is unset (the default), so
    without the availability route the row would never render.
    """
    connectors = connectors_report(
        literature_available=True,
        enabled_tools=None,
        web_search_available=True,
    )
    assert {"id": "web_search", "display": "Web search"} in connectors


def test_connectors_report_omits_web_search_when_unavailable() -> None:
    """No provider key on the MCP server means no web search row."""
    connectors = connectors_report(
        literature_available=True,
        enabled_tools=None,
        web_search_available=False,
    )
    assert all(item["id"] != "web_search" for item in connectors)


def test_connectors_report_defaults_web_search_unavailable() -> None:
    """Callers that omit the flag get the conservative answer."""
    connectors = connectors_report(
        literature_available=True, enabled_tools=None
    )
    assert all(item["id"] != "web_search" for item in connectors)


def test_connectors_report_still_falls_back_to_pubmed() -> None:
    """Nothing available still yields a non-empty menu."""
    connectors = connectors_report(
        literature_available=False,
        enabled_tools=None,
        web_search_available=False,
    )
    assert connectors == [{"id": "pubmed", "display": "PubMed"}]


def test_connectors_report_orders_web_then_pubmed() -> None:
    """The menu order is web search, then PubMed."""
    connectors = connectors_report(
        literature_available=True,
        enabled_tools=None,
        web_search_available=True,
    )
    assert [item["id"] for item in connectors] == ["web_search", "pubmed"]


def test_connectors_report_lists_arxiv_and_biorxiv_when_configured() -> None:
    """Both toggles appear once MCP is up and the config enables them."""
    connectors = connectors_report(
        literature_available=True,
        enabled_tools=["pubmed_fulltext", "arxiv_search", "biorxiv_search"],
    )
    ids = [item["id"] for item in connectors]
    assert "arxiv" in ids
    assert "biorxiv" in ids


def test_connectors_report_omits_arxiv_when_not_configured() -> None:
    """A tools config that never enables arxiv_search omits the row."""
    connectors = connectors_report(
        literature_available=True,
        enabled_tools=["pubmed_fulltext"],
    )
    assert all(item["id"] != "arxiv" for item in connectors)


def test_connectors_report_omits_arxiv_when_mcp_is_down() -> None:
    """Configured but unreachable must not read as available.

    Both are keyless -- neither has its own credential to be refused --
    but they run through the same MCP process PubMed does, so a down
    server takes them down with it exactly as it does PubMed. Gating on
    config membership alone (the pattern every other non-probed connector
    uses) would show them as available here, which is the "the agent
    never searched the web" failure mode PubMed's own live probe exists
    to avoid.
    """
    connectors = connectors_report(
        literature_available=False,
        enabled_tools=["pubmed_fulltext", "arxiv_search", "biorxiv_search"],
    )
    assert all(item["id"] not in ("arxiv", "biorxiv") for item in connectors)


def test_resolved_run_config_enables_web_search_by_default() -> None:
    """The toggle is on by default, matching the literature stack."""
    from app.run_modes import resolved_run_config

    assert resolved_run_config().get("enable_web_search") is True


def test_resolved_run_config_honors_web_search_override() -> None:
    """An explicit off from the request survives config resolution."""
    from app.run_modes import resolved_run_config

    cfg = resolved_run_config(overrides={"enable_web_search": False})
    assert cfg["enable_web_search"] is False
