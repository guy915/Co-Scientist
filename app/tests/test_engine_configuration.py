from __future__ import annotations

import importlib
import importlib.util
import os
import pathlib
import sys
from typing import Any, ClassVar

import pytest
from co_scientist import HypothesisGenerator

import app.engine_adapter as provider
from app import process_mode, store
from app.config import (
    PROVIDER_CREDENTIAL_ENV,
    any_provider_credential,
    settings,
)
from app.engine_adapter.events import (
    _canonical_engine_payload,
    _canonical_event_type,
    append_node_milestone,
)
from app.engine_adapter.opts import (
    _setup_opts_from_cfg,
    build_engine_opts,
    build_generator,
)
from app.engine_adapter.tools import (
    connectors_report,
    tools_config_report,
    validate_tools_config,
)
from app.run_modes import (
    resolved_run_config,
    setup_config,
)


@pytest.mark.parametrize(
    ("tier", "resolved", "funded"),
    [
        ("express", "express", False),
        ("standard", "standard", False),
        ("extended", "extended", True),
        ("ultra", "ultra", True),
        ("advanced", "ultra", True),
        (None, "standard", False),
    ],
)
def test_tier_funding_reaches_every_expensive_capability(
    isolated_db: str, tier: str | None, resolved: str, funded: bool
) -> None:
    opts = build_engine_opts({"tier": tier}, "unused-run", isolated_db)
    assert opts["research_tier"] == resolved
    assert opts["enable_tool_calling_generation"] is funded
    assert opts["enable_simulation_execution"] is funded
    assert opts["enable_overview_review"] is funded


def test_default_config_keeps_the_existing_capabilities(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FORCE_LITERATURE_REVIEW", raising=False)
    opts = build_engine_opts({}, "unused-run", isolated_db)
    assert opts["research_tier"] == "standard"
    assert opts["enable_tool_calling_generation"] is False
    assert opts["enable_simulation_execution"] is False
    assert opts["enable_overview_review"] is False
    assert opts["enable_literature_review_node"] is True
    assert opts["enable_meta_review"] is True
    assert opts["generation_strategy"] == ""


@pytest.mark.parametrize("enabled", [False, True])
def test_literature_kill_switch_overrides_the_connector(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    cfg = {"enable_literature_review": enabled}
    monkeypatch.delenv("FORCE_LITERATURE_REVIEW", raising=False)
    opts = build_engine_opts(cfg, "unused-run", isolated_db)
    assert opts["enable_literature_review_node"] is enabled
    monkeypatch.setenv("FORCE_LITERATURE_REVIEW", "0")
    opts = build_engine_opts(cfg, "unused-run", isolated_db)
    assert opts["enable_literature_review_node"] is False


@pytest.mark.parametrize("enabled", [False, True, None, 0])
@pytest.mark.parametrize("strategy", ["debate", "unknown", None, 12])
def test_ablation_requests_keep_their_existing_normalization(
    isolated_db: str, enabled: Any, strategy: Any
) -> None:
    opts = build_engine_opts(
        {"enable_meta_review": enabled, "generation_strategy": strategy},
        "unused-run",
        isolated_db,
    )
    assert opts["enable_meta_review"] is (enabled is not False)
    assert opts["generation_strategy"] == (
        strategy if isinstance(strategy, str) else ""
    )


_ENGINE_NODES = [
    "supervisor",
    "literature_review",
    "generate",
    "reflection",
    "review",
    "ranking",
    "deep_verification",
    "meta_review",
    "evolve",
    "proximity",
    "research_overview",
]
_EXPECTED_TYPES = {
    "supervisor": "supervisor.plan",
    "literature_review": "literature_review",
    "generate": "generate",
    "reflection": "reflection",
    "review": "review",
    "ranking": "ranking",
    "deep_verification": "deep_verification",
    "meta_review": "meta_review",
    "evolve": "evolve",
    "proximity": "proximity",
    "research_overview": "research_overview",
}


def _streaming_hypotheses() -> list[dict[str, Any]]:
    return [
        {
            "id": "eng-h1",
            "text": "H1: a mechanistic claim about the pathway.",
            "elo_rating": 1300,
            "win_count": 2,
            "loss_count": 0,
            "evolution_history": [],
            "reviews": [{"review_summary": "Sound mechanism."}],
            "deep_verification_verdict": "verified",
            "deep_verification_probes": [
                {"question": "Does X cause Y?", "answer": "Yes, via Z."}
            ],
        },
        {
            "id": "eng-h2",
            "text": "H2: an evolved variant of the leading claim.",
            "elo_rating": 1250,
            "win_count": 1,
            "loss_count": 1,
            "evolution_history": [{"round": 1}],
            "reviews": [],
        },
    ]


def _streaming_research_overview() -> dict[str, Any]:
    return {
        "overview": {"summary": "Targeting the pathway looks promising."},
        "nih_specific_aims": {
            "disease_description": "Background.",
            "aims": [],
        },
    }


def _streaming_proximity_graph() -> dict[str, Any]:
    return {
        "edges": [
            {
                "source": "eng-h1",
                "target": "eng-h2",
                "similarity": 0.8,
                "cluster_id": "cluster-0",
            }
        ],
        "meta": {"method": "embedding", "version": 1},
    }


def _engine_streaming_state() -> dict[str, Any]:
    return {
        "hypotheses": _streaming_hypotheses(),
        "articles": [
            {
                "title": "A1",
                "url": "https://example.org/a1",
                "abstract": (
                    "H1: a mechanistic claim about the pathway. H2: an "
                    "evolved variant of the leading claim."
                ),
            }
        ],
        "tournament_matchups": [
            {
                "hypothesis_a": "H1: a mechanistic claim about the pathway.",
                "hypothesis_b": "H2: an evolved variant of the leading claim.",
                "hypothesis_a_id": "eng-h1",
                "hypothesis_b_id": "eng-h2",
                "winner_id": "eng-h1",
                "winner": "a",
            }
        ],
        "meta_review": {
            "summary": "Leading hypotheses converge on one mechanism.",
            "common_strengths": ["Clear mechanism"],
            "common_weaknesses": ["Thin evidence"],
        },
        "evolution_details": [],
        "research_overview": _streaming_research_overview(),
        "proximity_graph": _streaming_proximity_graph(),
        "current_iteration": 1,
    }


def _payloads_by_type() -> dict[str, dict[str, Any]]:
    state = _engine_streaming_state()
    by_type: dict[str, dict[str, Any]] = {}
    for node in _ENGINE_NODES:
        node_type = _canonical_event_type(node)
        by_type[node_type] = _canonical_engine_payload(node, node_type, state)
    return by_type


def _assert_canonical_event_types(types_emitted: list[str]) -> None:
    assert not any(t.startswith("engine.") for t in types_emitted)

    for node, expected in _EXPECTED_TYPES.items():
        assert expected in types_emitted, f"{node} -> {expected} missing"


def _assert_normalized_payloads(by_type: dict[str, Any]) -> None:
    generate = by_type["generate"]
    assert generate["count"] == 2
    assert len(generate["hypotheses"]) == 2
    assert isinstance(by_type["ranking"]["matches"], list)
    assert len(by_type["ranking"]["matches"]) == 1
    assert len(by_type["evolve"]["children"]) == 1
    assert by_type["literature_review"]["count"] == 1
    assert len(by_type["literature_review"]["evidence"]) == 1
    assert by_type["supervisor.plan"]["agents"]


def _assert_full_fidelity_payloads(by_type: dict[str, Any]) -> None:
    assert by_type["reflection"]["reviewed"] == 1
    assert by_type["proximity"]["clusters"] == {"cluster-0": 2}
    assert (
        by_type["meta_review"]["critique"]
        == "Leading hypotheses converge on one mechanism."
    )
    assert by_type["meta_review"]["top_k_ids"] == ["eng-h1", "eng-h2"]
    assert by_type["deep_verification"]["verified"] == 1
    assert by_type["deep_verification"]["probes"] == [
        {
            "hypothesis_id": "eng-h1",
            "verdict": "verified",
            "probes": [
                {"question": "Does X cause Y?", "answer": "Yes, via Z."}
            ],
        }
    ]
    assert (
        by_type["research_overview"]["research_overview"]
        == _streaming_research_overview()
    )


def test_engine_adapter_emits_canonical_event_types(isolated_db: str) -> None:
    # Offline CI does not drive every live node; direct mapping coverage
    # protects frontend event vocabulary.
    by_type = _payloads_by_type()

    _assert_canonical_event_types(list(by_type))
    _assert_normalized_payloads(by_type)
    _assert_full_fidelity_payloads(by_type)


def test_engine_adapter_generates_canonical_milestones(
    isolated_db: str,
) -> None:
    run = store.create_run("Milestone goal", "standard", "engine", {})
    for node_type, payload in _payloads_by_type().items():
        append_node_milestone(run.id, node_type, payload, db_path=isolated_db)

    msgs = store.list_messages(run.id, db_path=isolated_db)
    milestones = [m for m in msgs if m.kind == "milestone"]
    text = " | ".join(m.content for m in milestones)
    assert "Research plan ready" in text
    assert "2 hypotheses generated" in text
    assert "1 matches" in text
    assert "1 hypotheses reviewed" in text
    assert "1 clusters identified" in text
    assert "1 hypotheses verified" in text
    assert "Research overview ready" in text


def test_a_retrieval_outage_rides_every_event_after_it() -> None:
    # Skipped literature stages emit nothing; carry capability loss on later
    # events so absence is not mistaken for delay.
    state: dict[str, Any] = {
        "current_iteration": 1,
        "retrieval_degradation": {
            "reason": "mcp_unreachable",
            "lost": ["literature_review"],
            "floor": "none",
        },
    }

    payload = _canonical_engine_payload("generate", "generate", state)

    assert payload["retrieval_degraded"]["reason"] == "mcp_unreachable"


def test_a_healthy_run_carries_no_outage_key() -> None:
    payload = _canonical_engine_payload(
        "generate", "generate", {"current_iteration": 1}
    )

    assert "retrieval_degraded" not in payload


def test_legacy_free_string_attributes_reach_the_engine_as_is() -> None:
    opts = _setup_opts_from_cfg(
        {"attributes": ["Mechanistically specific", "  "], "focus": "balance"}
    )
    assert opts["attributes"] == ["Mechanistically specific"]


def test_published_default_attributes_reach_the_engine_as_bare_names() -> None:
    # Rubric anchor text contains commas; feeding it to a comma-joined names
    # slot invents extra items.
    setup = setup_config(research_goal="goal")
    opts = _setup_opts_from_cfg(setup)
    assert opts["attributes"] == [
        "Mechanistic specificity",
        "Evidence grounding",
        "Experimental readiness",
    ]


def test_a_missing_setup_carries_no_attributes() -> None:
    assert _setup_opts_from_cfg(None) == {}


def test_legacy_free_string_criteria_reach_the_engine_as_is() -> None:
    opts = _setup_opts_from_cfg(
        {"criteria": ["Scientific soundness", "  "], "focus": "balance"}
    )
    assert opts["criteria"] == ["Scientific soundness"]


def test_published_default_criteria_reach_the_engine_as_name_value_lines() -> (
    None
):
    setup = setup_config(research_goal="goal")
    opts = _setup_opts_from_cfg(setup)
    assert opts["criteria"] == [
        "Idea correctness: Required",
        "Idea novelty: Required",
        "Maximize impact: Yes",
    ]


def test_a_missing_setup_carries_no_criteria() -> None:
    assert _setup_opts_from_cfg(None) == {}


# Each run needs fresh tool topology; process singletons otherwise leak
# connector choices across runs.


def _generator_for(**overrides: Any) -> Any:
    return build_generator(
        HypothesisGenerator,
        resolved_run_config(dict(overrides)),
    )


def _enabled_tools(generator: Any) -> set[str]:
    return set(generator._tool_registry.get_enabled_tools())


def _search_sources(generator: Any) -> set[str]:
    # Source enabled flags control retrieval independently of registered tools.
    workflow = generator._tool_registry.get_workflow("literature_review")
    return {source.tool for source in workflow.get_enabled_search_sources()}


def test_second_run_gets_its_own_connector_toggles() -> None:
    without = _generator_for(enable_web_search=False)
    with_web = _generator_for(enable_web_search=True)

    assert "web_search" not in _enabled_tools(without)
    assert "web_search" in _enabled_tools(with_web)
    assert "web_search" not in _search_sources(without)
    assert "web_search" in _search_sources(with_web)


def test_toggle_order_does_not_decide_the_topology() -> None:
    _generator_for(enable_web_search=True)
    without = _generator_for(enable_web_search=False)

    assert "web_search" not in _enabled_tools(without)
    assert "web_search" not in _search_sources(without)


def test_each_run_holds_a_registry_of_its_own() -> None:
    first = _generator_for(enable_web_search=True)
    second = _generator_for(enable_web_search=True)

    assert first._tool_registry is not second._tool_registry


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
    return {
        "max_iterations": 1,
        "initial_hypotheses_count": 4,
        "evolution_max_count": 4,
        "tournament_pairs": 6,
        "evidence_count": 4,
        "k_factor": 36,
        "max_llm_calls": 100,
        "max_ideas": 12,
        "max_matches_per_idea": 4,
    }


class _FakeGenerator:
    last_kwargs: ClassVar[dict[str, Any]] = {}

    def __init__(self, **kwargs: Any) -> None:
        _FakeGenerator.last_kwargs = kwargs


def test_build_generator_forwards_configured_tools_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "tools_config", _INDRA_CONFIG)
    build_generator(_FakeGenerator, _cfg())
    assert _FakeGenerator.last_kwargs["options"].tools_config == _INDRA_CONFIG


def test_build_generator_forwards_none_tools_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "tools_config", None)
    build_generator(_FakeGenerator, _cfg())
    assert _FakeGenerator.last_kwargs["options"].tools_config is None


def test_build_generator_forwards_run_elo_k_factor() -> None:
    build_generator(_FakeGenerator, _cfg())
    assert _FakeGenerator.last_kwargs["options"].elo_k_factor == 36


def test_build_generator_offline_disables_cache_without_env_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Offline cache settings must remain per-run; mutating env can disable
    # caching for every later real run.
    monkeypatch.delenv("COSCIENTIST_CACHE_ENABLED", raising=False)
    build_generator(_FakeGenerator, _cfg(), offline=True)
    assert _FakeGenerator.last_kwargs["options"].enable_cache is False
    import os

    assert "COSCIENTIST_CACHE_ENABLED" not in os.environ


def test_offline_generator_does_not_poison_cache_for_a_real_generator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The first startup generator may be offline; later real generators must
    # retain process cache defaults.
    from co_scientist import cache as engine_cache
    from co_scientist.generator import HypothesisGenerator

    monkeypatch.setenv("COSCIENTIST_CACHE_ENABLED", "true")
    monkeypatch.setattr(engine_cache, "_global_cache", None)

    build_generator(HypothesisGenerator, _cfg(), offline=True)
    import os

    assert os.environ["COSCIENTIST_CACHE_ENABLED"] == "true"
    assert engine_cache.get_cache().enabled is True


def test_validate_tools_config_accepts_none() -> None:
    validate_tools_config(None)


def test_validate_tools_config_accepts_readable_path() -> None:
    validate_tools_config(_INDRA_CONFIG)


def test_validate_tools_config_accepts_url() -> None:
    validate_tools_config("https://example.com/tools.yaml")


def test_validate_tools_config_raises_on_unreadable_path() -> None:
    with pytest.raises(RuntimeError, match="tools_config"):
        validate_tools_config("/no/such/tools.yaml")


def test_tools_config_report_enumerates_enabled_tools() -> None:
    report = tools_config_report(_INDRA_CONFIG)
    assert report["tools_config"] == _INDRA_CONFIG
    assert report["tools_config_valid"] is True
    assert "indra_statements" in report["enabled_tools"]


def test_tools_config_report_marks_bad_path_invalid() -> None:
    report = tools_config_report("/no/such/tools.yaml")
    assert report["tools_config_valid"] is False
    assert report["enabled_tools"] is None


def test_tools_config_report_none_enumerates_the_bundled_default() -> None:
    # Unset TOOLS_CONFIG still runs bundled defaults; status must disclose the
    # effective topology.
    report = tools_config_report(None)
    assert report["tools_config"] is None
    assert report["tools_config_valid"] is True
    assert report["enabled_tools"] is not None
    assert "pubmed_search" in report["enabled_tools"]
    assert "indra_statements" not in report["enabled_tools"]


def test_build_generator_enables_web_search_by_default() -> None:
    build_generator(_FakeGenerator, _cfg())
    assert _FakeGenerator.last_kwargs["options"].disable_tools == []


def test_build_generator_disables_web_search_when_toggled_off() -> None:
    cfg = _cfg() | {"enable_web_search": False}
    build_generator(_FakeGenerator, cfg)
    assert _FakeGenerator.last_kwargs["options"].disable_tools == [
        "web_search",
    ]


def test_disabling_web_search_keeps_read_url() -> None:
    # read_url fetches full text for unrelated literature sources; disabling web
    # search must not disable it.
    cfg = _cfg() | {"enable_web_search": False}
    build_generator(_FakeGenerator, cfg)
    assert "read_url" not in _FakeGenerator.last_kwargs["options"].disable_tools


def test_connectors_report_lists_web_search_when_available() -> None:
    connectors = connectors_report(
        literature_available=True,
        enabled_tools=None,
        web_search_available=True,
    )
    assert {"id": "web_search", "display": "Web search"} in connectors


def test_connectors_report_omits_web_search_when_unavailable() -> None:
    connectors = connectors_report(
        literature_available=True,
        enabled_tools=None,
        web_search_available=False,
    )
    assert all(item["id"] != "web_search" for item in connectors)


def test_connectors_report_defaults_web_search_unavailable() -> None:
    connectors = connectors_report(
        literature_available=True, enabled_tools=None
    )
    assert all(item["id"] != "web_search" for item in connectors)


def test_connectors_report_still_falls_back_to_pubmed() -> None:
    connectors = connectors_report(
        literature_available=False,
        enabled_tools=None,
        web_search_available=False,
    )
    assert connectors == [{"id": "pubmed", "display": "PubMed"}]


def test_connectors_report_orders_web_then_pubmed() -> None:
    connectors = connectors_report(
        literature_available=True,
        enabled_tools=None,
        web_search_available=True,
    )
    assert [item["id"] for item in connectors] == ["web_search", "pubmed"]


def test_connectors_report_lists_arxiv_and_biorxiv_when_configured() -> None:
    connectors = connectors_report(
        literature_available=True,
        enabled_tools=["pubmed_fulltext", "arxiv_search", "biorxiv_search"],
    )
    ids = [item["id"] for item in connectors]
    assert "arxiv" in ids
    assert "biorxiv" in ids


def test_connectors_report_omits_arxiv_when_not_configured() -> None:
    connectors = connectors_report(
        literature_available=True,
        enabled_tools=["pubmed_fulltext"],
    )
    assert all(item["id"] != "arxiv" for item in connectors)


def test_connectors_report_omits_arxiv_when_mcp_is_down() -> None:
    # Configured keyless sources still depend on live MCP; configuration alone
    # cannot establish availability.
    connectors = connectors_report(
        literature_available=False,
        enabled_tools=["pubmed_fulltext", "arxiv_search", "biorxiv_search"],
    )
    assert all(item["id"] not in ("arxiv", "biorxiv") for item in connectors)


def test_resolved_run_config_enables_web_search_by_default() -> None:
    from app.run_modes import resolved_run_config

    assert resolved_run_config().get("enable_web_search") is True


def test_resolved_run_config_honors_web_search_override() -> None:
    from app.run_modes import resolved_run_config

    cfg = resolved_run_config(overrides={"enable_web_search": False})
    assert cfg["enable_web_search"] is False


_ALL_CREDENTIAL_ENV = tuple(
    name for names in PROVIDER_CREDENTIAL_ENV.values() for name in names
)


def _clear_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ALL_CREDENTIAL_ENV:
        monkeypatch.delenv(key, raising=False)


def test_a_non_default_provider_key_counts_as_a_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_credentials(monkeypatch)
    assert any_provider_credential() is False

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert any_provider_credential() is True


@pytest.mark.parametrize("credential", _ALL_CREDENTIAL_ENV)
def test_every_known_credential_keeps_the_run_on_a_real_provider(
    monkeypatch: pytest.MonkeyPatch, credential: str
) -> None:
    # Shared credential vocabulary prevents a usable provider key silently
    # selecting fabricated offline science.
    monkeypatch.delenv("COSCIENTIST_FORCE_OFFLINE", raising=False)
    monkeypatch.delenv("COSCIENTIST_FORCE_MOCK", raising=False)
    _clear_credentials(monkeypatch)
    assert provider.offline_mode() is True

    monkeypatch.setenv(credential, "sk-test")
    assert any_provider_credential() is True
    assert provider.offline_mode() is False


def test_credential_lookup_has_one_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Offline detection and safety must recognize provider credentials from the
    # same map.
    _clear_credentials(monkeypatch)
    monkeypatch.setitem(
        PROVIDER_CREDENTIAL_ENV, "fictional", ("FICTIONAL_KEY",)
    )
    monkeypatch.setenv("FICTIONAL_KEY", "sk-test")
    monkeypatch.delenv("COSCIENTIST_FORCE_OFFLINE", raising=False)

    assert provider.offline_mode() is False
    assert process_mode.credential_available("fictional/model-x") is True


def test_engine_importable_returns_false_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(name: str) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(importlib.util, "find_spec", _boom)
    assert provider._engine_importable() is False


@pytest.mark.parametrize("has_key", [False, True])
def test_select_provider_is_always_engine(
    monkeypatch: pytest.MonkeyPatch, has_key: bool
) -> None:
    if has_key:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(provider, "_engine_importable", lambda: True)
    assert provider.select_provider() == "engine"


def test_select_provider_raises_when_engine_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provider, "_engine_importable", lambda: False)
    with pytest.raises(RuntimeError, match="hard dependency"):
        provider.select_provider()


@pytest.mark.parametrize(
    ("force_offline", "force_mock", "has_key", "expected"),
    [
        (None, None, True, False),
        (None, None, False, True),
        ("1", None, True, True),
        (None, "1", True, True),
    ],
    ids=[
        "real_when_key_present",
        "offline_when_no_provider_key",
        "offline_when_force_offline",
        "offline_when_force_mock_deprecated_alias",
    ],
)
def test_offline_mode(
    monkeypatch: pytest.MonkeyPatch,
    force_offline: str | None,
    force_mock: str | None,
    has_key: bool,
    expected: bool,
) -> None:
    monkeypatch.delenv("COSCIENTIST_FORCE_OFFLINE", raising=False)
    monkeypatch.delenv("COSCIENTIST_FORCE_MOCK", raising=False)
    if force_offline is not None:
        monkeypatch.setenv("COSCIENTIST_FORCE_OFFLINE", force_offline)
    if force_mock is not None:
        monkeypatch.setenv("COSCIENTIST_FORCE_MOCK", force_mock)
    _clear_credentials(monkeypatch)
    if has_key:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert provider.offline_mode() is expected


def test_missing_engine_src_gets_added_to_syspath_on_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Editable installs already add engine src; remove it first to exercise the
    # import-time bridge.
    engine_src = provider._engine_src
    assert os.path.isdir(engine_src), "test assumes a local engine checkout"

    trimmed = [p for p in sys.path if p != engine_src]
    monkeypatch.setattr(sys, "path", trimmed)
    assert engine_src not in sys.path

    importlib.reload(provider)

    assert engine_src in sys.path
