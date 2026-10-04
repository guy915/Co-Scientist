from __future__ import annotations

import json
from typing import Any, cast

import pytest

from co_scientist import config as config_mod
from co_scientist.agents.generation import literature_tools as lit_tools_mod
from co_scientist.agents.generation.literature_tools import draft as draft_mod
from co_scientist.agents.generation.literature_tools import (
    validate as validate_mod,
)
from co_scientist.agents.generation.literature_tools.draft import (
    draft_hypotheses,
)
from co_scientist.agents.generation.literature_tools.validate import (
    _articles_to_paper_dict,
    _build_novelty_analysis_prompt,
    _find_search_tool,
    _first,
    _log_synthesis_tool_call_summary,
    _NoveltySearchContext,
    _parse_synthesis_response,
    _retry_failed_synthesis_batches,
    _retry_one_hypothesis,
    _run_synthesis_batches,
    _search_papers_for_hypothesis,
    _search_papers_via_tool_config,
    _setup_validation_tool_provider,
    _SynthesisRetryState,
    validate_hypotheses,
)
from co_scientist.config import ToolConfig, ToolRegistry
from co_scientist.config.schema import ResponseFormat
from co_scientist.constants import corpus_slug
from co_scientist.exceptions import ResponseParseError
from co_scientist.models import GenerationMethod, Hypothesis
from co_scientist.tools.provider import MCPToolProvider
from tests._mcp import FakeCallToolClient
from tests._state import make_article, make_hypothesis, make_state


class _FakeReferenceIndex:
    def __init__(self, text: str, sources: dict[str, dict[str, Any]]) -> None:
        self.text = text
        self.sources = sources


def _disable_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the locally imported collaborator at its source. Without a
    registry whitelist, the provider needs only the legacy call_tool seam."""

    def _raise(*_: Any, **__: Any) -> Any:
        raise RuntimeError("registry disabled for test")

    monkeypatch.setattr(config_mod, "get_tool_registry", _raise)


def _stub_draft_llm(
    monkeypatch: pytest.MonkeyPatch, final_response: str
) -> None:

    async def fake(**_: Any) -> tuple[str, list[Any]]:
        return final_response, []

    monkeypatch.setattr(draft_mod, "call_llm_with_tools", fake)


async def test_draft_parses_plain_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _disable_registry(monkeypatch)
    drafts = [
        {
            "text": "alpha gates the pathway",
            "gap_reasoning": "no prior work on alpha",
            "literature_sources": "Smith 2020",
        },
        {
            "text": "beta inhibits the pathway",
            "gap_reasoning": "beta understudied",
            "literature_sources": "Jones 2021",
        },
    ]
    _stub_draft_llm(monkeypatch, json.dumps({"drafts": drafts}))

    result, _draft_calls = await draft_hypotheses(
        state=make_state(),
        count=2,
        mcp_client=FakeCallToolClient({}),
        tool_registry=None,
    )

    assert result == drafts
    assert result[0]["text"] == "alpha gates the pathway"
    assert result[1]["gap_reasoning"] == "beta understudied"


async def test_draft_strips_json_fence(monkeypatch: pytest.MonkeyPatch) -> None:
    _disable_registry(monkeypatch)
    drafts = [{"text": "fenced hypothesis", "gap_reasoning": "gap"}]
    fenced = "```json\n" + json.dumps({"drafts": drafts}) + "\n```"
    _stub_draft_llm(monkeypatch, fenced)

    result, _draft_calls = await draft_hypotheses(
        state=make_state(),
        count=1,
        mcp_client=FakeCallToolClient({}),
        tool_registry=None,
    )

    assert result == drafts


async def test_draft_repairs_trailing_comma(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_registry(monkeypatch)
    malformed = '{"drafts": [{"text": "repaired hypothesis"},]}'
    _stub_draft_llm(monkeypatch, malformed)

    result, _draft_calls = await draft_hypotheses(
        state=make_state(),
        count=1,
        mcp_client=FakeCallToolClient({}),
        tool_registry=None,
    )

    assert result == [{"text": "repaired hypothesis"}]


async def test_draft_single_dict_not_wrapped_in_list_is_recovered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool-loop final prose is schema-less; a single bare hypothesis is a
    plausible answer."""
    _disable_registry(monkeypatch)
    single_draft = {"text": "unwrapped hypothesis", "gap_reasoning": "gap"}
    _stub_draft_llm(monkeypatch, json.dumps({"drafts": single_draft}))

    result, _draft_calls = await draft_hypotheses(
        state=make_state(),
        count=1,
        mcp_client=FakeCallToolClient({}),
        tool_registry=None,
    )

    assert result == [single_draft]


async def test_draft_missing_drafts_key_defaults_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_registry(monkeypatch)
    _stub_draft_llm(monkeypatch, json.dumps({"notes": "no drafts here"}))

    result, _draft_calls = await draft_hypotheses(
        state=make_state(),
        count=2,
        mcp_client=FakeCallToolClient({}),
        tool_registry=None,
    )

    assert result == []


async def test_draft_unparseable_response_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_registry(monkeypatch)
    _stub_draft_llm(monkeypatch, "the agent failed to emit any json output")

    with pytest.raises(ResponseParseError):
        await draft_hypotheses(
            state=make_state(),
            count=1,
            mcp_client=FakeCallToolClient({}),
            tool_registry=None,
        )


def test_corpus_slug_is_deterministic() -> None:
    slug = corpus_slug("cure the common cold")
    assert slug == corpus_slug("cure the common cold")
    assert slug.startswith("research_")
    assert len(slug) == len("research_") + 8


def _stub_synthesis_llm(
    monkeypatch: pytest.MonkeyPatch, hypotheses: list[dict[str, Any]]
) -> None:

    async def fake(**_: Any) -> tuple[str, list[Any]]:
        return json.dumps({"hypotheses": hypotheses}), []

    monkeypatch.setattr(validate_mod, "call_llm_with_tools", fake)


_TWO_HYPOTHESIS_SYNTHESIS: list[dict[str, Any]] = [
    {
        "hypothesis": "alpha kinase drives resistance",
        "explanation": "the mechanism fits",
        "literature_grounding": "grounded in prior work",
        "experiment": "run the kinase assay",
        "novelty_validation": "no exact prior match found",
    },
    {
        "hypothesis": "beta receptor modulates response",
        "explanation": "downstream signalling",
        "literature_grounding": None,
        "experiment": "knock out beta",
        "novelty_validation": "partially novel",
    },
]


async def test_validate_builds_literature_tools_hypotheses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_registry(monkeypatch)
    _stub_synthesis_llm(monkeypatch, _TWO_HYPOTHESIS_SYNTHESIS)
    drafts = [
        {"text": "draft one", "gap_reasoning": "gap a"},
        {"text": "draft two", "gap_reasoning": "gap b"},
    ]

    result, _validate_calls = await validate_hypotheses(
        state=make_state(),
        draft_hypotheses=drafts,
        mcp_client=FakeCallToolClient({}),
        tool_registry=None,
    )

    assert len(result) == 2
    assert all(isinstance(h, Hypothesis) for h in result)
    assert all(
        h.generation_method == GenerationMethod.LITERATURE_TOOLS for h in result
    )
    assert result[0].text == "alpha kinase drives resistance"
    assert result[0].experiment == "run the kinase assay"
    assert result[0].novelty_validation == "no exact prior match found"
    assert result[1].literature_grounding is None
    assert result[0].citation_map == {}


async def test_validate_single_hypothesis_not_wrapped_in_list_is_recovered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool-loop synthesis is schema-less; a single bare hypothesis is a
    plausible answer."""
    _disable_registry(monkeypatch)
    single_hypothesis = {
        "hypothesis": "unwrapped hypothesis",
        "explanation": "fits",
        "experiment": "assay",
    }

    async def fake(**_: Any) -> tuple[str, list[Any]]:
        return json.dumps({"hypotheses": single_hypothesis}), []

    monkeypatch.setattr(validate_mod, "call_llm_with_tools", fake)
    drafts = [{"text": "draft one", "gap_reasoning": "gap a"}]

    result, _validate_calls = await validate_hypotheses(
        state=make_state(),
        draft_hypotheses=drafts,
        mcp_client=FakeCallToolClient({}),
        tool_registry=None,
    )

    assert len(result) == 1
    assert result[0].text == "unwrapped hypothesis"


_PRIOR_ALPHA_PAPERS: dict[str, Any] = {
    "p1": {
        "title": "Prior alpha study",
        "authors": ["Smith"],
        "year": 2020,
        "fulltext": "some body text about alpha",
    }
}

_VALIDATED_ALPHA_SYNTHESIS: list[dict[str, Any]] = [
    {
        "hypothesis": "alpha hypothesis validated",
        "explanation": "fits",
        "experiment": "assay",
    }
]


async def test_validate_runs_novelty_pass_when_papers_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_registry(monkeypatch)
    novelty_calls: list[bool] = []

    async def fake_novelty(**_: Any) -> dict[str, Any]:
        novelty_calls.append(True)
        return {"novelty_assessment": "novel", "key_findings": "kf"}

    monkeypatch.setattr(validate_mod, "call_llm_json", fake_novelty)
    _stub_synthesis_llm(monkeypatch, _VALIDATED_ALPHA_SYNTHESIS)

    result, _validate_calls = await validate_hypotheses(
        state=make_state(),
        draft_hypotheses=[{"text": "alpha draft"}],
        mcp_client=FakeCallToolClient(_PRIOR_ALPHA_PAPERS),
        tool_registry=None,
    )

    assert novelty_calls == [True]
    assert len(result) == 1
    assert result[0].text == "alpha hypothesis validated"
    assert result[0].generation_method == GenerationMethod.LITERATURE_TOOLS


async def test_validate_empty_drafts_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_registry(monkeypatch)

    called: list[bool] = []

    async def fake_synth(**_: Any) -> tuple[str, list[Any]]:
        called.append(True)
        return json.dumps({"hypotheses": []}), []

    monkeypatch.setattr(validate_mod, "call_llm_with_tools", fake_synth)

    result, _validate_calls = await validate_hypotheses(
        state=make_state(),
        draft_hypotheses=[],
        mcp_client=FakeCallToolClient({}),
        tool_registry=None,
    )

    assert result == []
    assert called == []


async def test_validate_text_fallback_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_registry(monkeypatch)
    _stub_synthesis_llm(
        monkeypatch,
        [
            {
                "text": "fallback-keyed hypothesis",
                "explanation": "uses text key",
            }
        ],
    )

    result, _validate_calls = await validate_hypotheses(
        state=make_state(),
        draft_hypotheses=[{"text": "d"}],
        mcp_client=FakeCallToolClient({}),
        tool_registry=None,
    )

    assert len(result) == 1
    assert result[0].text == "fallback-keyed hypothesis"
    assert result[0].experiment is None


async def test_validate_resolves_citation_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_registry(monkeypatch)
    _stub_synthesis_llm(
        monkeypatch,
        [
            {
                "hypothesis": "cited hypothesis",
                "explanation": "fits",
                "literature_grounding": "as shown in [C1] the effect holds",
                "experiment": "assay",
            }
        ],
    )
    ref_index = _FakeReferenceIndex(
        text="[C1] Smith 2020",
        sources={"C1": {"type": "paper", "title": "Smith 2020"}},
    )

    result, _validate_calls = await validate_hypotheses(
        state=make_state(),
        draft_hypotheses=[{"text": "d"}],
        mcp_client=FakeCallToolClient({}),
        tool_registry=None,
        reference_index=ref_index,
    )

    assert len(result) == 1
    assert result[0].citation_map == {
        "C1": {"type": "paper", "title": "Smith 2020"}
    }


def test_count_used_articles_counts_only_flagged() -> None:
    articles = [
        make_article(used_in_analysis=True),
        make_article(used_in_analysis=False),
        make_article(used_in_analysis=True),
    ]
    assert lit_tools_mod._count_used_articles(articles) == 2


def test_count_used_articles_with_pdfs_requires_both_flags() -> None:
    articles = [
        make_article(used_in_analysis=True, pdf_links=["http://a"]),
        make_article(used_in_analysis=True, pdf_links=[]),
        make_article(used_in_analysis=False, pdf_links=["http://b"]),
    ]
    assert lit_tools_mod._count_used_articles_with_pdfs(articles) == 1


def test_log_warm_start_diagnostics_none_returns_early() -> None:
    lit_tools_mod._log_warm_start_diagnostics(None)


def test_log_warm_start_diagnostics_empty_returns_early() -> None:
    lit_tools_mod._log_warm_start_diagnostics([])


def test_log_warm_start_diagnostics_zero_used_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING", logger=lit_tools_mod.__name__)
    articles = [make_article(used_in_analysis=False)]
    lit_tools_mod._log_warm_start_diagnostics(articles)
    assert "agent will search fresh" in caplog.text


def test_log_warm_start_diagnostics_used_with_mixed_pdfs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO", logger=lit_tools_mod.__name__)
    articles = [
        make_article(used_in_analysis=True, pdf_links=["http://a"]),
        make_article(used_in_analysis=True, pdf_links=[]),
    ]
    lit_tools_mod._log_warm_start_diagnostics(articles)
    assert "Including 2 analyzed articles" in caplog.text
    assert "agent will search fresh" not in caplog.text


async def test_get_mcp_client_for_generation_returns_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()

    async def fake_get_mcp_client(**_: Any) -> Any:
        return sentinel

    monkeypatch.setattr(lit_tools_mod, "get_mcp_client", fake_get_mcp_client)

    result = await lit_tools_mod._get_mcp_client_for_generation(None)
    assert result is sentinel


async def test_get_mcp_client_for_generation_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    async def fake_get_mcp_client(**_: Any) -> Any:
        raise RuntimeError("mcp unreachable")

    monkeypatch.setattr(lit_tools_mod, "get_mcp_client", fake_get_mcp_client)

    with pytest.raises(RuntimeError, match="mcp unreachable"):
        await lit_tools_mod._get_mcp_client_for_generation(None)


def test_log_generated_hypothesis_methods_handles_set_and_none() -> None:
    hyps = [
        make_hypothesis(
            text="a", generation_method=GenerationMethod.LITERATURE_TOOLS
        ),
        make_hypothesis(text="b", generation_method=None),
    ]
    lit_tools_mod._log_generated_hypothesis_methods(hyps)


class _OrchestrationProbe:
    def __init__(self) -> None:
        self.client = object()
        self.registry = object()
        self.final: list[Hypothesis] = [make_hypothesis(text="validated one")]
        self.draft_calls: list[dict[str, Any]] = []
        self.validate_calls: list[dict[str, Any]] = []


def _install_orchestration_fakes(
    monkeypatch: pytest.MonkeyPatch, probe: _OrchestrationProbe
) -> None:

    async def fake_get_mcp_client(**kwargs: Any) -> Any:
        assert kwargs["tool_registry"] is probe.registry
        return probe.client

    async def fake_draft_hypotheses(
        **kwargs: Any,
    ) -> tuple[list[dict[str, Any]], int]:
        probe.draft_calls.append(kwargs)
        return [{"text": "draft one"}], 2

    async def fake_validate_hypotheses(
        **kwargs: Any,
    ) -> tuple[list[Hypothesis], int]:
        probe.validate_calls.append(kwargs)
        return probe.final, 5

    monkeypatch.setattr(lit_tools_mod, "get_mcp_client", fake_get_mcp_client)
    monkeypatch.setattr(
        lit_tools_mod, "draft_hypotheses", fake_draft_hypotheses
    )
    monkeypatch.setattr(
        lit_tools_mod, "validate_hypotheses", fake_validate_hypotheses
    )


async def test_generate_with_tools_orchestrates_both_phases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = _OrchestrationProbe()
    _install_orchestration_fakes(monkeypatch, probe)

    state = make_state(
        tool_registry=probe.registry,
        articles=[make_article(used_in_analysis=True)],
    )
    result, llm_calls = await lit_tools_mod.generate_with_tools(
        state, count=3, reference_index=None
    )

    assert result == probe.final
    assert llm_calls == 2 + 5
    assert probe.draft_calls[0]["count"] == 3
    assert probe.draft_calls[0]["mcp_client"] is probe.client
    assert probe.draft_calls[0]["tool_registry"] is probe.registry
    assert probe.validate_calls[0]["draft_hypotheses"] == [
        {"text": "draft one"}
    ]
    assert probe.validate_calls[0]["mcp_client"] is probe.client
    assert probe.validate_calls[0]["tool_registry"] is probe.registry


def test_novelty_prompt_strips_citation_markers() -> None:
    """Copied source citations can misattribute generated claims to real
    sources."""
    metadata = {
        "title": "Prior work",
        "authors": ["Doe"],
        "year": 2020,
        "fulltext": "This confirms an earlier result (Smith et al. 2019) [12].",
    }

    prompt = _build_novelty_analysis_prompt("a draft hypothesis", metadata)

    assert "(Smith et al. 2019)" not in prompt
    assert "[12]" not in prompt


def test_novelty_prompt_leaves_stored_metadata_unchanged() -> None:
    original = "This confirms an earlier result (Smith et al. 2019) [12]."
    metadata = {
        "title": "Prior work",
        "authors": ["Doe"],
        "year": 2020,
        "fulltext": original,
    }

    _build_novelty_analysis_prompt("a draft hypothesis", metadata)

    assert metadata["fulltext"] == original


def test_first_returns_first_truthy_value() -> None:
    assert _first(None, "", "b", "c") == "b"


def test_first_returns_last_value_when_none_truthy() -> None:
    assert _first(None, "", 0) == 0


def test_first_returns_none_for_no_values() -> None:
    assert _first() is None


def test_articles_to_paper_dict_maps_fields_and_keys_by_source_id() -> None:
    articles = [
        make_article(
            title="Paper A",
            source_id="pmid-1",
            authors=["Smith"],
            year=2021,
            content="full body",
            abstract="short abstract",
        ),
        make_article(
            title="Paper B",
            source_id=None,
            url="http://example.test/b",
            content=None,
            abstract="only an abstract",
        ),
    ]

    result = _articles_to_paper_dict(articles)

    assert result["pmid-1"] == {
        "title": "Paper A",
        "authors": ["Smith"],
        "year": 2021,
        "fulltext": "full body",
    }
    assert result["http://example.test/b"]["fulltext"] == ("only an abstract")


class _FakeRegistry:
    def __init__(self, tool_ids: list[str], tools: dict[str, ToolConfig]):
        self._tool_ids = tool_ids
        self._tools = tools

    def get_tools_for_workflow(self, _workflow: str) -> list[str]:
        return self._tool_ids

    def get_tool(self, tool_id: str) -> ToolConfig | None:
        return self._tools.get(tool_id)


def test_find_search_tool_no_registry_returns_none() -> None:
    assert _find_search_tool(None) == (None, None)


def test_find_search_tool_returns_first_matching_category() -> None:
    search_tool = ToolConfig(
        server="s", mcp_tool_name="search_x", category="search"
    )
    registry = cast(
        ToolRegistry,
        _FakeRegistry(["search_x"], {"search_x": search_tool}),
    )

    tool_id, tool_config = _find_search_tool(registry)

    assert tool_id == "search_x"
    assert tool_config is search_tool


def test_find_search_tool_skips_non_matching_categories() -> None:
    utility_tool = ToolConfig(
        server="s", mcp_tool_name="util_x", category="utility"
    )
    registry = cast(
        ToolRegistry,
        _FakeRegistry(["util_x"], {"util_x": utility_tool}),
    )

    assert _find_search_tool(registry) == (None, None)


def _search_tool_config() -> ToolConfig:
    return ToolConfig(
        server="s",
        mcp_tool_name="search_papers",
        category="search",
        response_format=ResponseFormat(
            results_path=".",
            is_dict=True,
            field_mapping={
                "title": "title",
                "authors": "authors",
                "year": "year",
                "content": "fulltext",
                "source_id": "@key",
            },
        ),
    )


async def test_search_papers_via_tool_config_returns_paper_dict() -> None:
    tool_config = _search_tool_config()
    mcp_client = FakeCallToolClient(
        {"p1": {"title": "Paper One", "authors": ["A"], "year": 2020}}
    )

    result = await _search_papers_via_tool_config(
        tool_config,
        "hypothesis text",
        _NoveltySearchContext(
            mcp_client=mcp_client,
            tool_registry=None,
            shared_slug="slug-1",
            run_id="run-1",
        ),
        max_papers=5,
    )

    assert result == {
        "p1": {
            "title": "Paper One",
            "authors": ["A"],
            "year": 2020,
            "fulltext": "",
        }
    }
    name, kwargs = mcp_client.calls[0]
    assert name == "search_papers"
    assert kwargs["run_id"] == "run-1"
    assert kwargs["slug"] == "slug-1"


async def test_search_papers_via_tool_config_omits_run_id_when_absent() -> None:
    tool_config = _search_tool_config()
    mcp_client = FakeCallToolClient({})

    await _search_papers_via_tool_config(
        tool_config,
        "hypothesis text",
        _NoveltySearchContext(
            mcp_client=mcp_client,
            tool_registry=None,
            shared_slug="slug-1",
            run_id=None,
        ),
        max_papers=5,
    )

    _, kwargs = mcp_client.calls[0]
    assert "run_id" not in kwargs


async def test_search_papers_for_hypothesis_uses_config_tool() -> None:
    tool_config = _search_tool_config()
    registry = cast(
        ToolRegistry,
        _FakeRegistry(["search_papers"], {"search_papers": tool_config}),
    )
    mcp_client = FakeCallToolClient(
        {"p1": {"title": "Paper One", "authors": [], "year": 2020}}
    )

    result = await _search_papers_for_hypothesis(
        "hypothesis text",
        _NoveltySearchContext(
            mcp_client=mcp_client,
            tool_registry=registry,
            shared_slug="slug-1",
            run_id=None,
        ),
        max_papers=3,
    )

    assert "p1" in result


async def test_search_papers_for_hypothesis_no_tool_returns_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = cast(ToolRegistry, _FakeRegistry([], {}))
    mcp_client = FakeCallToolClient({})

    result = await _search_papers_for_hypothesis(
        "hypothesis text",
        _NoveltySearchContext(
            mcp_client=mcp_client,
            tool_registry=registry,
            shared_slug="slug-1",
            run_id=None,
        ),
        max_papers=3,
    )

    assert result == {}
    assert "skipping novelty search" in caplog.text


async def test_search_papers_for_hypothesis_legacy_fallback() -> None:
    mcp_client = FakeCallToolClient({"p1": {"title": "Legacy paper"}})

    result = await _search_papers_for_hypothesis(
        "hypothesis text",
        _NoveltySearchContext(
            mcp_client=mcp_client,
            tool_registry=None,
            shared_slug="slug-1",
            run_id=None,
        ),
        max_papers=3,
    )

    assert result == {"p1": {"title": "Legacy paper"}}
    name, kwargs = mcp_client.calls[0]
    assert name == "pubmed_search_with_fulltext"
    assert kwargs["slug"] == "slug-1"


class _FakeGlobalRegistry:
    def get_tools_for_workflow(self, _workflow: str) -> list[str]:
        return ["search_tool"]

    def get_mcp_tool_names(self, _tool_ids: list[str]) -> list[str]:
        return ["mcp_search_tool"]


def test_setup_validation_tool_provider_resolves_global_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_registry = cast(Any, _FakeGlobalRegistry())
    monkeypatch.setattr(config_mod, "get_tool_registry", lambda: fake_registry)

    provider, openai_tools, resolved_registry, max_iterations = (
        _setup_validation_tool_provider(None, None, 3)
    )

    assert resolved_registry is fake_registry
    assert isinstance(provider, MCPToolProvider)
    assert openai_tools == []
    assert max_iterations > 0


def test_log_synthesis_tool_call_summary_logs_when_calls_present(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
    _log_synthesis_tool_call_summary("1", {"search": 2, "read": 1})
    assert "3 tool calls" in caplog.text


def test_log_synthesis_tool_call_summary_silent_when_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")
    _log_synthesis_tool_call_summary("1", {})
    assert "tool calls" not in caplog.text


def test_parse_synthesis_response_raises_on_unparseable() -> None:
    with pytest.raises(ResponseParseError):
        _parse_synthesis_response("no json anywhere in this text", "1")


def test_parse_synthesis_response_repairs_truncated_json(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING")
    truncated = '{"hypotheses": [{"hypothesis": "x"}'
    result = _parse_synthesis_response(truncated, "1")
    assert result == [{"hypothesis": "x"}]
    assert "required major repairs" in caplog.text
    assert "batch 1" in caplog.text


async def test_run_synthesis_batches_isolates_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING")

    async def call_synthesis(
        batch: list[dict[str, Any]],
        label: str,
        _texts: list[str] | None,
    ) -> list[dict[str, Any]]:
        if label == "1":
            raise RuntimeError("batch one exploded")
        return [{"hypothesis": f"h-{label}"}]

    batches = [[{"a": 1}], [{"b": 2}]]
    validated, failed = await _run_synthesis_batches(batches, call_synthesis)

    assert validated == [{"hypothesis": "h-2"}]
    assert failed == [(0, batches[0])]
    assert "will retry hypotheses individually" in caplog.text


async def test_retry_one_hypothesis_success_accumulates_text() -> None:

    async def call_synthesis(
        batch: list[dict[str, Any]],
        label: str,
        texts: list[str] | None,
    ) -> list[dict[str, Any]]:
        assert label == "1_retry_1"
        assert texts == ["prior hypothesis"]
        return [{"hypothesis": "retried hypothesis"}]

    accumulated_texts = ["prior hypothesis"]
    all_validated: list[dict[str, Any]] = []

    await _retry_one_hypothesis(
        0,
        0,
        {"draft": "x"},
        _SynthesisRetryState(all_validated, accumulated_texts, call_synthesis),
    )

    assert all_validated == [{"hypothesis": "retried hypothesis"}]
    assert accumulated_texts == ["prior hypothesis", "retried hypothesis"]


async def test_retry_one_hypothesis_skips_empty_text_result() -> None:

    async def call_synthesis(
        _batch: list[dict[str, Any]],
        _label: str,
        _texts: list[str] | None,
    ) -> list[dict[str, Any]]:
        return [{"other_field": "no hypothesis key"}]

    accumulated_texts: list[str] = []
    all_validated: list[dict[str, Any]] = []

    await _retry_one_hypothesis(
        0,
        0,
        {"draft": "x"},
        _SynthesisRetryState(all_validated, accumulated_texts, call_synthesis),
    )

    assert all_validated == [{"other_field": "no hypothesis key"}]
    assert accumulated_texts == []


async def test_retry_one_hypothesis_failure_drops_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("ERROR")

    async def call_synthesis(
        _batch: list[dict[str, Any]],
        _label: str,
        _texts: list[str] | None,
    ) -> list[dict[str, Any]]:
        raise RuntimeError("still failing")

    accumulated_texts: list[str] = []
    all_validated: list[dict[str, Any]] = []

    await _retry_one_hypothesis(
        1,
        2,
        {"draft": "y"},
        _SynthesisRetryState(all_validated, accumulated_texts, call_synthesis),
    )

    assert all_validated == []
    assert accumulated_texts == []
    assert "Individual retry failed" in caplog.text


async def test_retry_failed_synthesis_batches_seeds_context_and_retries() -> (
    None
):
    calls: list[tuple[str, list[str] | None]] = []

    async def call_synthesis(
        batch: list[dict[str, Any]],
        label: str,
        texts: list[str] | None,
    ) -> list[dict[str, Any]]:
        calls.append((label, list(texts) if texts else None))
        hyp_data = batch[0]
        if hyp_data.get("fail"):
            raise RuntimeError("nope")
        return [{"hypothesis": hyp_data["draft"]}]

    failed_batches: list[tuple[int, list[dict[str, Any]]]] = [
        (0, [{"draft": "a"}, {"draft": "b", "fail": True}]),
    ]
    all_validated: list[dict[str, Any]] = [{"hypothesis": "seed"}]

    await _retry_failed_synthesis_batches(
        failed_batches, all_validated, call_synthesis
    )

    assert {"hypothesis": "a"} in all_validated
    assert len(all_validated) == 2
    assert len(calls) == 2
    assert calls[0] == ("1_retry_1", ["seed"])


async def test_draft_counts_tool_loop_completions_including_closing_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_registry(monkeypatch)
    drafts = [{"text": "grounded draft", "gap_reasoning": "gap"}]

    async def complete(**_: Any) -> tuple[str, list[dict[str, Any]]]:
        return json.dumps({"drafts": drafts}), [
            {"role": "user"},
            {"role": "assistant", "tool_calls": [{"id": "lookup"}]},
            {"role": "tool", "content": "evidence"},
            {"role": "assistant", "content": "closing draft"},
        ]

    monkeypatch.setattr(draft_mod, "call_llm_with_tools", complete)
    result, calls = await draft_hypotheses(
        state=make_state(),
        count=1,
        mcp_client=FakeCallToolClient({}),
        tool_registry=None,
    )
    assert result == drafts
    assert calls == 2
