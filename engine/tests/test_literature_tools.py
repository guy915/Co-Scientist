"""Offline contracts for literature tools."""

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

# -----------------------------------------------------------------------------
# Shared fixtures / fakes
# -----------------------------------------------------------------------------


# The MCP client here is the shared ``FakeCallToolClient``, which
# implements ``call_tool`` and nothing else. That is enough because
# ``MCPToolProvider`` only reaches for ``get_tools``/``execute_tool_call``
# when a whitelist is supplied; with the registry disabled neither runs,
# leaving ``call_tool`` (the legacy paper-search fallback) as the only
# method under test. Its canned response is the papers dict a search
# returns.


class _FakeReferenceIndex:
    """Stand-in for a citation reference index (``.text`` / ``.sources``)."""

    def __init__(self, text: str, sources: dict[str, dict[str, Any]]) -> None:
        self.text = text
        self.sources = sources


def _disable_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the no-registry fallback in both generation phases.

    ``get_tool_registry`` is imported locally (``from co_scientist.config
    import get_tool_registry``) so it is patched at its source module; making it
    raise drives both phases down the documented "No tool registry" branch.
    """

    def _raise(*_: Any, **__: Any) -> Any:
        raise RuntimeError("registry disabled for test")

    monkeypatch.setattr(config_mod, "get_tool_registry", _raise)


def _stub_draft_llm(
    monkeypatch: pytest.MonkeyPatch, final_response: str
) -> None:
    """Stub ``draft.call_llm_with_tools`` to return a fixed final response."""

    async def fake(**_: Any) -> tuple[str, list[Any]]:
        return final_response, []

    monkeypatch.setattr(draft_mod, "call_llm_with_tools", fake)


# -----------------------------------------------------------------------------
# draft_hypotheses
# -----------------------------------------------------------------------------


async def test_draft_parses_plain_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bare JSON object yields the parsed list of draft dicts verbatim."""
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
    """A ```json fenced response is unwrapped before parsing."""
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
    """A malformed response with a trailing comma is repaired, not rejected."""
    _disable_registry(monkeypatch)
    # Trailing comma after the array element -- invalid JSON that
    # attempt_json_repair fixes via its minor-repair path.
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
    """A single draft object (not wrapped in a list) still parses.

    A model asked to draft one hypothesis can plausibly write the single
    object directly rather than wrapping it in a one-element array; the
    draft-parsing seam is schema-less (a tool-calling loop's freeform
    final turn), so this must be recovered rather than silently dropped.
    """
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
    """A well-formed object lacking a 'drafts' key defaults to an empty list."""
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
    """A response surviving every repair attempt raises ResponseParseError."""
    _disable_registry(monkeypatch)
    # No braces anywhere: attempt_json_repair cannot recover a dict.
    _stub_draft_llm(monkeypatch, "the agent failed to emit any json output")

    with pytest.raises(ResponseParseError):
        await draft_hypotheses(
            state=make_state(),
            count=1,
            mcp_client=FakeCallToolClient({}),
            tool_registry=None,
        )


def test_corpus_slug_is_deterministic() -> None:
    """Draft and validation derive the same corpus slug from the goal."""
    slug = corpus_slug("cure the common cold")
    assert slug == corpus_slug("cure the common cold")
    assert slug.startswith("research_")
    # Deterministic: derived from research_goal via md5, length "research_" + 8.
    assert len(slug) == len("research_") + 8


# -----------------------------------------------------------------------------
# validate_hypotheses
# -----------------------------------------------------------------------------


def _stub_synthesis_llm(
    monkeypatch: pytest.MonkeyPatch, hypotheses: list[dict[str, Any]]
) -> None:
    """Stub ``validate.call_llm_with_tools`` (the synthesis pass)."""

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
    """Synthesis output is assembled into LITERATURE_TOOLS Hypothesis objects.

    Papers search returns empty, so the novelty pass is skipped and only the
    synthesis seam is exercised -- the clean synthesis-only path.
    """
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
    # No reference index -> citation_map stays empty.
    assert result[0].citation_map == {}


async def test_validate_single_hypothesis_not_wrapped_in_list_is_recovered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A synthesis batch of one can plausibly return a bare object.

    Mirrors the draft-phase recovery test: the synthesis pass shares the
    same schema-less ``parse_tool_loop_json`` seam, so a single hypothesis
    object under ``"hypotheses"`` (not wrapped in a list) must still be
    assembled rather than silently dropped.
    """
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
    """A populated paper search drives the parallel per-paper novelty pass.

    This exercises ``call_llm_json`` (the novelty seam) for real, which the
    empty-papers path never reaches.
    """
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

    # The novelty pass ran once for the single found paper.
    assert novelty_calls == [True]
    assert len(result) == 1
    assert result[0].text == "alpha hypothesis validated"
    assert result[0].generation_method == GenerationMethod.LITERATURE_TOOLS


async def test_validate_empty_drafts_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No drafts means no synthesis batches and an empty result list."""
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
    # Zero batches -> the synthesis LLM is never invoked.
    assert called == []


async def test_validate_text_fallback_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synthesis output using 'text' (not 'hypothesis') is still assembled."""
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
    """A [C*] key in the grounding resolves against the reference index."""
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


# -----------------------------------------------------------------------------
# _count_used_articles / _count_used_articles_with_pdfs
# -----------------------------------------------------------------------------


def test_count_used_articles_counts_only_flagged() -> None:
    """Only articles with used_in_analysis=True are counted."""
    articles = [
        make_article(used_in_analysis=True),
        make_article(used_in_analysis=False),
        make_article(used_in_analysis=True),
    ]
    assert lit_tools_mod._count_used_articles(articles) == 2


def test_count_used_articles_with_pdfs_requires_both_flags() -> None:
    """Only used-and-PDF-backed articles count toward the PDF subset."""
    articles = [
        make_article(used_in_analysis=True, pdf_links=["http://a"]),
        make_article(used_in_analysis=True, pdf_links=[]),
        make_article(used_in_analysis=False, pdf_links=["http://b"]),
    ]
    assert lit_tools_mod._count_used_articles_with_pdfs(articles) == 1


# -----------------------------------------------------------------------------
# _log_warm_start_diagnostics
# -----------------------------------------------------------------------------


def test_log_warm_start_diagnostics_none_returns_early() -> None:
    """None articles is a no-op (does not raise)."""
    lit_tools_mod._log_warm_start_diagnostics(None)


def test_log_warm_start_diagnostics_empty_returns_early() -> None:
    """An empty articles list is a no-op (does not raise)."""
    lit_tools_mod._log_warm_start_diagnostics([])


def test_log_warm_start_diagnostics_zero_used_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No used_in_analysis articles logs the fresh-search warning."""
    caplog.set_level("WARNING", logger=lit_tools_mod.__name__)
    articles = [make_article(used_in_analysis=False)]
    lit_tools_mod._log_warm_start_diagnostics(articles)
    assert "agent will search fresh" in caplog.text


def test_log_warm_start_diagnostics_used_with_mixed_pdfs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Used articles log the pdf/abstract-only split, not the warning."""
    caplog.set_level("INFO", logger=lit_tools_mod.__name__)
    articles = [
        make_article(used_in_analysis=True, pdf_links=["http://a"]),
        make_article(used_in_analysis=True, pdf_links=[]),
    ]
    lit_tools_mod._log_warm_start_diagnostics(articles)
    assert "Including 2 analyzed articles" in caplog.text
    assert "agent will search fresh" not in caplog.text


# -----------------------------------------------------------------------------
# _get_mcp_client_for_generation
# -----------------------------------------------------------------------------


async def test_get_mcp_client_for_generation_returns_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful get_mcp_client call returns its client unchanged."""
    sentinel = object()

    async def fake_get_mcp_client(**_: Any) -> Any:
        return sentinel

    monkeypatch.setattr(lit_tools_mod, "get_mcp_client", fake_get_mcp_client)

    result = await lit_tools_mod._get_mcp_client_for_generation(None)
    assert result is sentinel


async def test_get_mcp_client_for_generation_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing get_mcp_client call is logged and re-raised, not swallowed."""

    async def fake_get_mcp_client(**_: Any) -> Any:
        raise RuntimeError("mcp unreachable")

    monkeypatch.setattr(lit_tools_mod, "get_mcp_client", fake_get_mcp_client)

    with pytest.raises(RuntimeError, match="mcp unreachable"):
        await lit_tools_mod._get_mcp_client_for_generation(None)


# -----------------------------------------------------------------------------
# _log_generated_hypothesis_methods
# -----------------------------------------------------------------------------


def test_log_generated_hypothesis_methods_handles_set_and_none() -> None:
    """Logging tolerates both a set generation_method and a None one."""
    hyps = [
        make_hypothesis(
            text="a", generation_method=GenerationMethod.LITERATURE_TOOLS
        ),
        make_hypothesis(text="b", generation_method=None),
    ]
    # No assertion beyond "does not raise": this is a debug-trace helper.
    lit_tools_mod._log_generated_hypothesis_methods(hyps)


# -----------------------------------------------------------------------------
# generate_with_tools
# -----------------------------------------------------------------------------


class _OrchestrationProbe:
    """Sentinels and recorded phase calls for the orchestration test."""

    def __init__(self) -> None:
        self.client = object()
        self.registry = object()
        self.final: list[Hypothesis] = [make_hypothesis(text="validated one")]
        self.draft_calls: list[dict[str, Any]] = []
        self.validate_calls: list[dict[str, Any]] = []


def _install_orchestration_fakes(
    monkeypatch: pytest.MonkeyPatch, probe: _OrchestrationProbe
) -> None:
    """Stub client resolution and both phases to record onto ``probe``."""

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
    """generate_with_tools threads the resolved client/registry through.

    Resolves the MCP client and threads it and the registry into both
    phases, returning phase 2's hypotheses unchanged.
    """
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
    """The candidate paper's own citation markers do not reach the prompt.

    Left in, the novelty-verdict model can copy one into its own
    reasoning -- a real-looking reference attached to a claim the cited
    source never made.
    """
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
    """Stripping is for the prompt copy only, never for storage."""
    original = "This confirms an earlier result (Smith et al. 2019) [12]."
    metadata = {
        "title": "Prior work",
        "authors": ["Doe"],
        "year": 2020,
        "fulltext": original,
    }

    _build_novelty_analysis_prompt("a draft hypothesis", metadata)

    assert metadata["fulltext"] == original


# -----------------------------------------------------------------------------
# _first
# -----------------------------------------------------------------------------


def test_first_returns_first_truthy_value() -> None:
    """The first truthy positional value wins."""
    assert _first(None, "", "b", "c") == "b"


def test_first_returns_last_value_when_none_truthy() -> None:
    """With no truthy value, the last (falsy) value is returned."""
    assert _first(None, "", 0) == 0


def test_first_returns_none_for_no_values() -> None:
    """Calling with zero values returns None."""
    assert _first() is None


# -----------------------------------------------------------------------------
# _articles_to_paper_dict
# -----------------------------------------------------------------------------


def test_articles_to_paper_dict_maps_fields_and_keys_by_source_id() -> None:
    """Articles are keyed by the first available id and content fallback."""
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


# -----------------------------------------------------------------------------
# _find_search_tool
# -----------------------------------------------------------------------------


class _FakeRegistry:
    """Minimal stand-in exposing only what _find_search_tool reads."""

    def __init__(self, tool_ids: list[str], tools: dict[str, ToolConfig]):
        self._tool_ids = tool_ids
        self._tools = tools

    def get_tools_for_workflow(self, _workflow: str) -> list[str]:
        """Return the configured workflow tool ids."""
        return self._tool_ids

    def get_tool(self, tool_id: str) -> ToolConfig | None:
        """Resolve a tool id to its config, or None if unconfigured."""
        return self._tools.get(tool_id)


def test_find_search_tool_no_registry_returns_none() -> None:
    """A falsy tool_registry short-circuits to (None, None)."""
    assert _find_search_tool(None) == (None, None)


def test_find_search_tool_returns_first_matching_category() -> None:
    """The first search/search_with_content-category tool wins."""
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
    """Non-search-category tools are skipped, falling through to None."""
    utility_tool = ToolConfig(
        server="s", mcp_tool_name="util_x", category="utility"
    )
    registry = cast(
        ToolRegistry,
        _FakeRegistry(["util_x"], {"util_x": utility_tool}),
    )

    assert _find_search_tool(registry) == (None, None)


# -----------------------------------------------------------------------------
# _search_papers_via_tool_config
# -----------------------------------------------------------------------------


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
    """A config-driven search maps the parsed articles into a paper dict."""
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
    """A falsy run_id is not injected into the canonical search params."""
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


# -----------------------------------------------------------------------------
# _search_papers_for_hypothesis
# -----------------------------------------------------------------------------


async def test_search_papers_for_hypothesis_uses_config_tool() -> None:
    """A resolved search tool routes through the config-driven path."""
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
    """A registry with no matching search tool skips the novelty search."""
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
    """No tool_registry at all falls back to the legacy direct call."""
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


# -----------------------------------------------------------------------------
# _setup_validation_tool_provider
# -----------------------------------------------------------------------------


class _FakeGlobalRegistry:
    """Minimal registry stand-in for the "resolve global registry" branch."""

    def get_tools_for_workflow(self, _workflow: str) -> list[str]:
        """Return one configured tool id."""
        return ["search_tool"]

    def get_mcp_tool_names(self, _tool_ids: list[str]) -> list[str]:
        """Return the resolved MCP tool names for the given tool ids."""
        return ["mcp_search_tool"]


def test_setup_validation_tool_provider_resolves_global_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tool_registry=None resolves the global registry's whitelist."""
    fake_registry = cast(Any, _FakeGlobalRegistry())
    monkeypatch.setattr(config_mod, "get_tool_registry", lambda: fake_registry)

    # A None mcp_client is safe here: MCPToolProvider.get_tools degrades to
    # an empty tools dict when no client is configured, so this only
    # exercises the registry-resolution branches under test.
    provider, openai_tools, resolved_registry, max_iterations = (
        _setup_validation_tool_provider(None, None, 3)
    )

    assert resolved_registry is fake_registry
    assert isinstance(provider, MCPToolProvider)
    assert openai_tools == []
    assert max_iterations > 0


# -----------------------------------------------------------------------------
# _log_synthesis_tool_call_summary
# -----------------------------------------------------------------------------


def test_log_synthesis_tool_call_summary_logs_when_calls_present(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A non-empty call-count map logs a per-tool summary line."""
    caplog.set_level("INFO")
    _log_synthesis_tool_call_summary("1", {"search": 2, "read": 1})
    assert "3 tool calls" in caplog.text


def test_log_synthesis_tool_call_summary_silent_when_empty(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A zero-call-count map logs nothing."""
    caplog.set_level("INFO")
    _log_synthesis_tool_call_summary("1", {})
    assert "tool calls" not in caplog.text


# -----------------------------------------------------------------------------
# _parse_synthesis_response
# -----------------------------------------------------------------------------


def test_parse_synthesis_response_raises_on_unparseable() -> None:
    """A response with no recoverable JSON raises ResponseParseError."""
    with pytest.raises(ResponseParseError):
        _parse_synthesis_response("no json anywhere in this text", "1")


def test_parse_synthesis_response_repairs_truncated_json(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A truncated-but-repairable response logs a repair warning."""
    caplog.set_level("WARNING")
    truncated = '{"hypotheses": [{"hypothesis": "x"}'
    result = _parse_synthesis_response(truncated, "1")
    assert result == [{"hypothesis": "x"}]
    # The warning names the batch, so a log reader can still tell which
    # synthesis phase needed repairing.
    assert "required major repairs" in caplog.text
    assert "batch 1" in caplog.text


# -----------------------------------------------------------------------------
# _run_synthesis_batches
# -----------------------------------------------------------------------------


async def test_run_synthesis_batches_isolates_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One batch raising does not prevent the others from succeeding."""
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


# -----------------------------------------------------------------------------
# _retry_one_hypothesis
# -----------------------------------------------------------------------------


async def test_retry_one_hypothesis_success_accumulates_text() -> None:
    """A successful retry extends both the result list and text context."""

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
    """A result without a hypothesis text is not added to the text context."""

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
    """A retry that raises is dropped, leaving the accumulators unchanged."""
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


# -----------------------------------------------------------------------------
# _retry_failed_synthesis_batches
# -----------------------------------------------------------------------------


async def test_retry_failed_synthesis_batches_seeds_context_and_retries() -> (
    None
):
    """Retries run per-hypothesis, seeded with already-validated texts."""
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
    # The pre-existing validated hypothesis seeds the first retry's context.
    assert calls[0] == ("1_retry_1", ["seed"])
