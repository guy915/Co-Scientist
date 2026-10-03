from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

import co_scientist.evidence as evidence
from co_scientist.agents.reflection import deep_verification_evidence as probes
from co_scientist.config.schema import SearchSourceConfig, WorkflowConfig
from co_scientist.evidence import retrieval_support as rs
from co_scientist.generator.initial_state import (
    RunCapabilities,
    RunIdentity,
    _build_initial_state,
)
from co_scientist.retrieval_degradation import (
    CAPABILITIES_LOST_WITHOUT_MCP,
    FLOOR_NONE,
    FLOOR_RUN_ATTACHMENTS,
    MCP_UNREACHABLE,
    resolve_retrieval_degradation,
)
from tests._mcp import make_tool_lookup_registry as _registry
from tests._research_fakes import make_tool_config as _tool
from tests._state import make_state


def test_resolve_content_tool_source_override_wins() -> None:
    source = SearchSourceConfig(
        tool="arxiv_search",
        content_tool="src_content",
        content_url_field="src_field",
    )
    workflow = WorkflowConfig(
        content_tool="wf_content", content_url_field="wf_field"
    )
    registry = _registry({"src_content": _tool("mcp_src_content")})

    result = rs._resolve_content_tool(source, workflow, registry)

    assert result is not None
    assert result.mcp_tool_name == "mcp_src_content"
    assert result.url_field == "src_field"


def test_resolve_content_tool_merges_params_source_wins() -> None:
    source = SearchSourceConfig(
        tool="arxiv_search",
        content_tool="src_content",
        content_params={"b": "source-b", "c": "source-c"},
    )
    workflow = WorkflowConfig(
        content_tool="wf_content",
        content_params={"a": "wf-a", "b": "wf-b"},
    )
    registry = _registry({"src_content": _tool("mcp_src_content")})

    result = rs._resolve_content_tool(source, workflow, registry)

    assert result is not None
    assert result.content_params == {
        "a": "wf-a",
        "b": "source-b",
        "c": "source-c",
    }


def test_resolve_content_tool_falls_back_to_workflow() -> None:
    source = SearchSourceConfig(tool="arxiv_search")
    workflow = WorkflowConfig(
        content_tool="wf_content", content_url_field="wf_field"
    )
    registry = _registry({"wf_content": _tool("mcp_wf_content")})

    result = rs._resolve_content_tool(source, workflow, registry)

    assert result is not None
    assert result.mcp_tool_name == "mcp_wf_content"
    assert result.url_field == "wf_field"


def test_resolve_content_tool_none_configured_returns_none() -> None:
    source = SearchSourceConfig(tool="arxiv_search")
    workflow = WorkflowConfig()
    assert rs._resolve_content_tool(source, workflow, _registry({})) is None


def test_resolve_content_tool_dangling_reference_returns_none() -> None:
    source = SearchSourceConfig(tool="arxiv_search", content_tool="ghost")
    workflow = WorkflowConfig()
    assert rs._resolve_content_tool(source, workflow, _registry({})) is None


def test_build_multi_source_content_config_keys_by_source_tool() -> None:
    workflow = WorkflowConfig(
        search_sources=[
            SearchSourceConfig(
                tool="arxiv", content_tool="arxiv_content", enabled=True
            ),
            SearchSourceConfig(tool="pubmed"),
        ]
    )
    registry = _registry({"arxiv_content": _tool("mcp_arxiv_content")})

    config = rs.build_content_config(workflow, registry, True)

    assert set(config) == {"arxiv"}
    assert config["arxiv"].mcp_tool_name == "mcp_arxiv_content"


def test_build_default_content_config_success() -> None:
    workflow = WorkflowConfig(
        content_tool="wf_content",
        content_url_field="pdf_url",
        content_params={"depth": "full"},
    )
    registry = _registry({"wf_content": _tool("mcp_wf_content")})

    config = rs.build_content_config(workflow, registry, False)

    assert set(config) == {"_default"}
    assert config["_default"].mcp_tool_name == "mcp_wf_content"
    assert config["_default"].url_field == "pdf_url"
    assert config["_default"].content_params == {"depth": "full"}


def test_build_default_content_config_no_tool_configured() -> None:
    assert rs.build_content_config(WorkflowConfig(), _registry({}), False) == {}


def test_build_default_content_config_dangling_reference() -> None:
    workflow = WorkflowConfig(content_tool="ghost")
    assert rs.build_content_config(workflow, _registry({}), False) == {}


def test_build_content_config_no_workflow_returns_empty() -> None:
    assert rs.build_content_config(None, _registry({}), False) == {}


def test_build_content_config_no_registry_returns_empty() -> None:
    workflow = WorkflowConfig(content_tool="wf_content")
    assert rs.build_content_config(workflow, None, False) == {}


def test_build_content_config_multi_source_dispatch() -> None:
    workflow = WorkflowConfig(
        search_sources=[
            SearchSourceConfig(tool="arxiv", content_tool="arxiv_content")
        ]
    )
    registry = _registry({"arxiv_content": _tool("mcp_arxiv_content")})

    config = rs.build_content_config(workflow, registry, True)

    assert set(config) == {"arxiv"}


def test_build_content_config_single_source_dispatch() -> None:
    workflow = WorkflowConfig(content_tool="wf_content")
    registry = _registry({"wf_content": _tool("mcp_wf_content")})

    config = rs.build_content_config(workflow, registry, False)

    assert set(config) == {"_default"}


def test_lookup_content_config_by_source() -> None:
    cfg = rs.ContentToolConfig(
        mcp_tool_name="mcp_arxiv", url_field="pdf_url", content_params={}
    )
    default_cfg = rs.ContentToolConfig(
        mcp_tool_name="mcp_def", url_field="pdf_url", content_params={}
    )
    config = {"arxiv": cfg, "_default": default_cfg}

    result = rs._lookup_source_config("p1", {"p1": "arxiv"}, config)

    assert result is cfg


def test_lookup_content_config_falls_back_to_default() -> None:
    default_cfg = rs.ContentToolConfig(
        mcp_tool_name="mcp_def", url_field="pdf_url", content_params={}
    )
    result = rs._lookup_source_config("p1", {}, {"_default": default_cfg})
    assert result is default_cfg


def test_lookup_content_config_none_available() -> None:
    assert rs._lookup_source_config("p1", {}, {}) is None


def _content_config() -> dict[str, rs.ContentToolConfig]:
    return {
        "_default": rs.ContentToolConfig(
            mcp_tool_name="mcp_content", url_field="pdf_url", content_params={}
        )
    }


def test_resolve_content_entry_non_dict_metadata_returns_none() -> None:
    bad_meta = cast(dict[str, Any], "not-a-dict")
    assert (
        rs._resolve_content_entry("p1", bad_meta, {}, _content_config()) is None
    )


def test_resolve_content_entry_already_has_fulltext_returns_none() -> None:
    meta = {"fulltext": "already have it", "pdf_url": "http://x.pdf"}
    assert rs._resolve_content_entry("p1", meta, {}, _content_config()) is None


def test_resolve_content_entry_no_config_returns_none() -> None:
    meta = {"pdf_url": "http://x.pdf"}
    assert rs._resolve_content_entry("p1", meta, {}, {}) is None


def test_resolve_content_entry_no_content_url_returns_none() -> None:
    meta = {"title": "no pdf_url field"}
    assert rs._resolve_content_entry("p1", meta, {}, _content_config()) is None


def test_resolve_content_entry_success() -> None:
    meta = {"pdf_url": "http://x.pdf"}
    result = rs._resolve_content_entry("p1", meta, {}, _content_config())
    assert result is not None
    pid, resolved_meta, cfg = result
    assert pid == "p1"
    assert resolved_meta is meta
    assert cfg.mcp_tool_name == "mcp_content"


def test_get_papers_needing_content_filters_eligible() -> None:
    all_metadata = {
        "eligible": {"pdf_url": "http://x.pdf"},
        "already_has_fulltext": {
            "pdf_url": "http://y.pdf",
            "fulltext": "already have it",
        },
        "no_pdf_url": {"title": "nothing to fetch"},
    }
    result = rs.get_papers_needing_content(all_metadata, {}, _content_config())
    assert [pid for pid, *_ in result] == ["eligible"]


def test_get_papers_needing_content_empty_metadata() -> None:
    assert rs.get_papers_needing_content({}, {}, _content_config()) == []


def test_resolve_pdf_discovery_tool_source_override_wins() -> None:
    source = SearchSourceConfig(
        tool="arxiv_search",
        pdf_discovery_tool="src_discovery",
        pdf_discovery_url_field="src_url",
    )
    workflow = WorkflowConfig(
        pdf_discovery_tool="wf_discovery", pdf_discovery_url_field="wf_url"
    )
    registry = _registry({"src_discovery": _tool("mcp_src_discovery")})

    result = rs._resolve_pdf_discovery_tool(source, workflow, registry)

    assert result == ("mcp_src_discovery", "src_url")


def test_resolve_pdf_discovery_tool_falls_back_to_workflow() -> None:
    source = SearchSourceConfig(tool="arxiv_search")
    workflow = WorkflowConfig(
        pdf_discovery_tool="wf_discovery", pdf_discovery_url_field="wf_url"
    )
    registry = _registry({"wf_discovery": _tool("mcp_wf_discovery")})

    result = rs._resolve_pdf_discovery_tool(source, workflow, registry)

    assert result == ("mcp_wf_discovery", "wf_url")


def test_resolve_pdf_discovery_tool_none_configured_returns_none() -> None:
    source = SearchSourceConfig(tool="arxiv_search")
    workflow = WorkflowConfig()
    registry = _registry({})

    assert rs._resolve_pdf_discovery_tool(source, workflow, registry) is None


def test_resolve_pdf_discovery_tool_dangling_reference_returns_none() -> None:
    source = SearchSourceConfig(tool="arxiv_search", pdf_discovery_tool="ghost")
    workflow = WorkflowConfig()
    registry = _registry({})

    assert rs._resolve_pdf_discovery_tool(source, workflow, registry) is None


def test_build_multi_source_pdf_config_keys_by_source_tool() -> None:
    workflow = WorkflowConfig(
        search_sources=[
            SearchSourceConfig(
                tool="scholar",
                pdf_discovery_tool="scholar_discovery",
                pdf_discovery_url_field="url",
            ),
            SearchSourceConfig(tool="pubmed"),
        ]
    )
    registry = _registry({"scholar_discovery": _tool("mcp_scholar_discovery")})

    config = rs.build_pdf_discovery_config(workflow, registry, True)

    assert config == {"scholar": ("mcp_scholar_discovery", "url")}


def test_build_default_pdf_config_success() -> None:
    workflow = WorkflowConfig(
        pdf_discovery_tool="wf_discovery", pdf_discovery_url_field="landing_url"
    )
    registry = _registry({"wf_discovery": _tool("mcp_wf_discovery")})

    config = rs.build_pdf_discovery_config(workflow, registry, False)

    assert config == {"_default": ("mcp_wf_discovery", "landing_url")}


def test_build_default_pdf_config_no_tool_configured() -> None:
    workflow = WorkflowConfig()
    assert rs.build_pdf_discovery_config(workflow, _registry({}), False) == {}


def test_build_default_pdf_config_dangling_reference() -> None:
    workflow = WorkflowConfig(pdf_discovery_tool="ghost")
    assert rs.build_pdf_discovery_config(workflow, _registry({}), False) == {}


def test_build_pdf_discovery_config_no_workflow_returns_empty() -> None:
    registry = _registry({})
    assert rs.build_pdf_discovery_config(None, registry, False) == {}


def test_build_pdf_discovery_config_no_registry_returns_empty() -> None:
    workflow = WorkflowConfig(pdf_discovery_tool="wf_discovery")
    assert rs.build_pdf_discovery_config(workflow, None, False) == {}


def test_build_pdf_discovery_config_multi_source_dispatch() -> None:
    workflow = WorkflowConfig(
        search_sources=[
            SearchSourceConfig(
                tool="scholar",
                pdf_discovery_tool="scholar_discovery",
                pdf_discovery_url_field="url",
            )
        ]
    )
    registry = _registry({"scholar_discovery": _tool("mcp_scholar_discovery")})

    config = rs.build_pdf_discovery_config(workflow, registry, True)

    assert config == {"scholar": ("mcp_scholar_discovery", "url")}


def test_build_pdf_discovery_config_single_source_dispatch() -> None:
    workflow = WorkflowConfig(
        pdf_discovery_tool="wf_discovery", pdf_discovery_url_field="url"
    )
    registry = _registry({"wf_discovery": _tool("mcp_wf_discovery")})

    config = rs.build_pdf_discovery_config(workflow, registry, False)

    assert config == {"_default": ("mcp_wf_discovery", "url")}


def test_lookup_pdf_discovery_config_by_source() -> None:
    config = {"pubmed": ("mcp_pubmed", "url"), "_default": ("mcp_def", "url2")}
    result = rs._lookup_source_config("p1", {"p1": "pubmed"}, config)
    assert result == ("mcp_pubmed", "url")


def test_lookup_pdf_discovery_config_falls_back_to_default() -> None:
    config = {"_default": ("mcp_def", "url2")}
    result = rs._lookup_source_config("p1", {}, config)
    assert result == ("mcp_def", "url2")


def test_lookup_pdf_discovery_config_none_available() -> None:
    assert rs._lookup_source_config("p1", {}, {}) is None


def _pdf_config() -> dict[str, tuple[str, str]]:
    return {"_default": ("mcp_discovery", "url")}


def test_resolve_pdf_discovery_entry_non_dict_metadata_returns_none() -> None:
    bad_meta = cast(dict[str, Any], "not-a-dict")
    assert (
        rs._resolve_pdf_discovery_entry("p1", bad_meta, {}, _pdf_config())
        is None
    )


def test_resolve_pdf_discovery_entry_already_has_pdf_url_returns_none() -> None:
    meta = {"pdf_url": "http://already.pdf", "url": "http://landing"}
    assert (
        rs._resolve_pdf_discovery_entry("p1", meta, {}, _pdf_config()) is None
    )


def test_resolve_pdf_discovery_entry_no_config_returns_none() -> None:
    meta = {"url": "http://landing"}
    assert rs._resolve_pdf_discovery_entry("p1", meta, {}, {}) is None


def test_resolve_pdf_discovery_entry_no_landing_url_returns_none() -> None:
    meta = {"title": "no url field"}
    assert (
        rs._resolve_pdf_discovery_entry("p1", meta, {}, _pdf_config()) is None
    )


def test_resolve_pdf_discovery_entry_success() -> None:
    meta = {"url": "http://landing"}
    result = rs._resolve_pdf_discovery_entry("p1", meta, {}, _pdf_config())
    assert result == ("p1", meta, "mcp_discovery", "url")


def test_get_papers_needing_pdf_discovery_filters_eligible() -> None:
    all_metadata = {
        "eligible": {"url": "http://landing"},
        "already_has_pdf": {"pdf_url": "http://x.pdf", "url": "http://landing"},
        "no_url": {"title": "nothing to discover from"},
    }
    result = rs.get_papers_needing_pdf_discovery(
        all_metadata, {}, _pdf_config()
    )
    assert [pid for pid, *_ in result] == ["eligible"]


def test_get_papers_needing_pdf_discovery_empty_metadata() -> None:
    assert rs.get_papers_needing_pdf_discovery({}, {}, _pdf_config()) == []


def test_parse_pdf_discovery_result_empty_json_list_returns_none() -> None:
    assert rs.parse_pdf_discovery_result(json.dumps([])) is None


def test_parse_pdf_discovery_result_dict_without_link_fields_returns_none() -> (
    None
):
    assert rs.parse_pdf_discovery_result(json.dumps({"other": "value"})) is None


def test_parse_pdf_discovery_result_scalar_json_returns_none() -> None:
    assert rs.parse_pdf_discovery_result(json.dumps(42)) is None


async def test_probe_search_preserves_sources_and_excludes_retractions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = {
        "W123": {
            "title": "Current evidence",
            "abstract": "A measured result.",
            "_source_name": "openalex",
        },
        "retracted": {
            "title": "Retracted evidence",
            "abstract": "A withdrawn result.",
            "is_retracted": True,
        },
    }

    async def collect(*args: Any) -> tuple[Any, Any]:
        assert args[2].semantic_relevance_enabled is False
        assert args[2].papers_to_read_count == 6
        args[4].append("One source unavailable")
        return records, {}

    monkeypatch.setattr(
        "co_scientist.evidence.search.collect_papers",
        collect,
    )
    monkeypatch.setattr(
        "co_scientist.mcp_client.get_mcp_client",
        AsyncMock(return_value=object()),
    )
    articles, errors = await probes._retrieve_probe_evidence(
        make_state(mcp_available=True), ["measured result"]
    )
    assert [(a.source, a.source_id) for a in articles] == [("openalex", "W123")]
    assert errors == ["One source unavailable"]


def test_shared_evidence_modules_do_not_import_agents() -> None:
    for path in Path(evidence.__file__).parent.glob("*.py"):
        tree = ast.parse(path.read_text())
        modules = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ]
        modules += [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        assert not any(
            module.startswith("co_scientist.agents") for module in modules
        ), path


def _state(*, mcp_available: bool, opts: dict[str, Any] | None = None) -> Any:
    return _build_initial_state(
        config_fields={},
        identity=RunIdentity(
            research_goal="reverse fibrosis", start_time=0.0, run_id="run-1"
        ),
        capabilities=RunCapabilities(mcp_available=mcp_available),
        opts=opts or {},
        user_inputs={},
    )


def test_a_run_that_can_retrieve_reports_nothing() -> None:
    assert _state(mcp_available=True)["retrieval_degradation"] is None


def test_a_run_that_cannot_retrieve_names_what_it_lost() -> None:
    """Ideas and reviews can look healthy without retrieval; the loss must
    reach the report."""
    degradation = _state(mcp_available=False)["retrieval_degradation"]

    assert degradation is not None
    assert degradation["reason"] == MCP_UNREACHABLE
    assert degradation["lost"] == list(CAPABILITIES_LOST_WITHOUT_MCP)
    assert "literature_review" in degradation["lost"]
    assert "deep_research" in degradation["lost"]


def test_with_no_documents_of_its_own_the_floor_is_nothing() -> None:
    degradation = _state(mcp_available=False)["retrieval_degradation"]

    assert degradation is not None
    assert degradation["floor"] == FLOOR_NONE


def test_a_run_with_attachments_still_has_those() -> None:
    degradation = _state(
        mcp_available=False,
        opts={"context_enrichment_sources": [{"title": "a memo"}]},
    )["retrieval_degradation"]

    assert degradation is not None
    assert degradation["floor"] == FLOOR_RUN_ATTACHMENTS


def test_the_fact_is_plain_data() -> None:
    import json

    degradation = resolve_retrieval_degradation(
        mcp_available=False, private_sources=None
    )

    assert json.loads(json.dumps(degradation)) == degradation
