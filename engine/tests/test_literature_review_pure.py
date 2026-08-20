"""Tests for the in-file pure helpers of the literature_review package.

Covers the network-free functions defined in the ``literature_review``
package's ``node`` and ``enrichment`` modules: ``_describe_exc``,
``_get_search_config``, ``_format_kg_section_with_keys``, and
``_parse_enrichment_result``. The node orchestration itself is covered in
``test_literature_review_node``.
"""

import pytest

from co_scientist.agents.generation.literature_review import (
    enrichment as lr_enrichment,
)
from co_scientist.agents.generation.literature_review import node as lr
from co_scientist.config import ToolRegistry
from co_scientist.constants import LITERATURE_REVIEW_PAPERS_COUNT_DEV
from tests._state import make_state


class _FakeExceptionGroupError(Exception):
    """Duck-typed stand-in for ``ExceptionGroup`` (portable to Python 3.10).

    Exposes the ``exceptions`` tuple that ``_describe_exc`` unwraps, mirroring
    the real ``ExceptionGroup`` the anyio-based MCP transport raises.
    """

    def __init__(self, message: str, exceptions: list[BaseException]) -> None:
        super().__init__(message)
        self.exceptions = tuple(exceptions)


def test_describe_exc_plain_exception() -> None:
    """A plain exception is rendered as ``Type: message``."""
    assert lr._describe_exc(ValueError("bad input")) == "ValueError: bad input"


def test_describe_exc_unwraps_exception_group() -> None:
    """A grouped exception is unwrapped to its underlying leaf cause."""
    leaf = ConnectionError("All connection attempts failed")
    group = _FakeExceptionGroupError("unhandled errors in a TaskGroup", [leaf])
    assert (
        lr._describe_exc(group)
        == "ConnectionError: All connection attempts failed"
    )


def test_get_search_config_defaults_single_source() -> None:
    """With no tool registry the config defaults to single-source pubmed."""
    config = lr._get_search_config(make_state())
    assert config.is_multi_source is False
    assert config.source_name == "pubmed"
    assert config.search_tool_name == "pubmed_search_with_fulltext"
    assert config.search_tool_config is None
    assert config.tool_registry is None
    assert config.papers_to_read_count > 0


def test_get_search_config_honors_run_paper_count() -> None:
    """Per-run literature count overrides the default outside dev mode."""
    config = lr._get_search_config(
        make_state(literature_review_papers_count=12)
    )
    assert config.papers_to_read_count == 12


def test_get_search_config_reads_dev_mode_from_state() -> None:
    """Dev mode arrives as run state and shrinks the evidence budget."""
    config = lr._get_search_config(
        make_state(dev_mode=True, literature_review_papers_count=12)
    )
    assert config.is_dev_mode is True
    assert config.papers_to_read_count == LITERATURE_REVIEW_PAPERS_COUNT_DEV


def test_get_search_config_ignores_the_ambient_dev_mode_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The node reads its run's state, not the process environment.

    ``COSCIENTIST_DEV_MODE`` is resolved once at the generator boundary
    (``generator/run_setup._resolve_dev_mode_flag``). Read again down here it
    would silently override the run's own evidence budget, so a run's
    literature size would depend on how the process happened to be started.
    """
    monkeypatch.setenv("COSCIENTIST_DEV_MODE", "true")
    config = lr._get_search_config(
        make_state(literature_review_papers_count=12)
    )
    assert config.is_dev_mode is False
    assert config.papers_to_read_count == 12


def test_literature_cache_key_covers_tool_contract_and_budget() -> None:
    """A source or evidence-budget change cannot replay stale literature."""
    legacy_state = make_state(
        model_name="model-a", literature_review_papers_count=4
    )
    registry_state = make_state(
        model_name="model-a",
        literature_review_papers_count=8,
        tool_registry=ToolRegistry(skip_user_config=True),
    )
    legacy = lr._literature_cache_params(
        legacy_state, lr._get_search_config(legacy_state)
    )
    multi_source = lr._literature_cache_params(
        registry_state, lr._get_search_config(registry_state)
    )

    assert legacy["cache_schema_version"] == 3
    assert legacy["papers_to_read_count"] == 4
    assert legacy["tool_contract"]["legacy_search_tool"] == (
        "pubmed_search_with_fulltext"
    )
    assert multi_source["papers_to_read_count"] == 8
    workflow = multi_source["tool_contract"]["workflows"]["literature_review"]
    # The literature review searches the public databases; the group's own
    # papers reach a run as an injected catalog, not as a search source.
    assert [source["tool"] for source in workflow["search_sources"]] == [
        "pubmed_fulltext",
        "openalex_search",
        "web_search",
    ]
    assert legacy != multi_source


def test_a_tier_that_researches_cannot_replay_one_that_did_not() -> None:
    """The review a deep tier produces is a different review.

    Without the tier in the key, an extended run replays an express
    run's cached review and gets no research despite paying for the
    tier, and the reverse imports another tier's ledger.
    """
    shallow = make_state(model_name="model-a", research_tier="")
    deep = make_state(model_name="model-a", research_tier="extended")

    assert lr._literature_cache_params(
        shallow, lr._get_search_config(shallow)
    ) != lr._literature_cache_params(deep, lr._get_search_config(deep))


def test_format_kg_section_empty_returns_empty_string() -> None:
    """No enrichment sources produces no knowledge-graph section."""
    assert lr_enrichment._format_kg_section_with_keys([], 0) == ""


def test_format_kg_section_keys_start_after_paper_count() -> None:
    """KG keys continue the [C*] numbering after the analyzed papers."""
    sources = [{"display": "Gene X -> Gene Y"}, {"display": "Gene Y -> Gene Z"}]
    section = lr_enrichment._format_kg_section_with_keys(sources, 2)
    assert "## Knowledge Graph Evidence" in section
    # paper_count == 2, so the first KG key is C3, the second C4.
    assert "[C3] Gene X -> Gene Y" in section
    assert "[C4] Gene Y -> Gene Z" in section


def test_format_kg_section_missing_display_uses_default() -> None:
    """An item lacking a ``display`` key falls back to a default label."""
    section = lr_enrichment._format_kg_section_with_keys([{}], 0)
    assert "[C1] External source" in section


def test_parse_enrichment_indra_empty_statements() -> None:
    """An INDRA response with empty ``statements`` yields no text or items."""
    text, items = lr_enrichment._parse_enrichment_result({"statements": []})
    assert text == ""
    assert items == []


def test_parse_enrichment_indra_statements_formatted() -> None:
    """INDRA statements format as 'subj -> obj [type] (belief: ..)' lines."""
    raw = {
        "statements": [
            {
                "subj": {"name": "KRAS"},
                "obj": {"name": "MAPK1"},
                "type": "Activation",
                "belief": 0.97,
            }
        ]
    }
    text, items = lr_enrichment._parse_enrichment_result(raw)
    assert "KRAS" in text and "MAPK1" in text
    assert "Activation" in text
    assert len(items) == 1
    assert items[0]["display"].startswith("INDRA:")


def test_parse_enrichment_results_list_caps_items() -> None:
    """A generic ``results`` list is capped to the per-entity limit."""
    raw = {"results": [{"n": i} for i in range(10)]}
    text, items = lr_enrichment._parse_enrichment_result(raw)
    cap = lr_enrichment._CONTEXT_ENRICHMENT_RESULTS_PER_ENTITY
    assert len(items) == cap
    assert text  # non-empty formatted text


def test_parse_enrichment_plain_string_non_json() -> None:
    """A non-JSON string becomes a single display item of truncated text."""
    text, items = lr_enrichment._parse_enrichment_result("free-form text")
    assert text == "free-form text"
    assert items == [{"display": "free-form text", "data": {}}]
