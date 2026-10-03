from __future__ import annotations

import json
from typing import Any

import pytest

from co_scientist.agents.generation.literature_review import (
    enrichment as lr_enrichment,
)
from co_scientist.agents.generation.literature_review import node as lr
from co_scientist.config import ToolRegistry
from co_scientist.config.schema import ResponseFormat, ToolConfig
from co_scientist.constants import LITERATURE_REVIEW_PAPERS_COUNT_DEV
from co_scientist.evidence import (
    article_support,
    retrieval_support,
    search_support,
)
from co_scientist.evidence import retrieval_support as errors
from co_scientist.models import Article
from tests._research_fakes import make_tool_config
from tests._state import make_state


def _tool_config(
    response_format: ResponseFormat | None = None,
    source_type: str = "academic",
) -> ToolConfig:
    return make_tool_config(
        "t",
        source_type=source_type,
        response_format=response_format or ResponseFormat(),
    )


def test_extract_source_name_none_returns_unknown() -> None:
    assert search_support.extract_source_name(None) == "unknown"


def test_extract_source_name_from_quoted_field_mapping() -> None:
    tc = _tool_config(ResponseFormat(field_mapping={"source": "'pubmed'"}))
    assert search_support.extract_source_name(tc) == "pubmed"


def test_extract_source_name_unquoted_mapping_falls_back_to_source_type() -> (
    None
):
    tc = _tool_config(
        ResponseFormat(field_mapping={"source": "paper.source"}),
        source_type="preprint",
    )
    assert search_support.extract_source_name(tc) == "preprint"


def test_extract_source_name_no_mapping_uses_source_type() -> None:
    tc = _tool_config(ResponseFormat(), source_type="arxiv")
    assert search_support.extract_source_name(tc) == "arxiv"


def test_normalize_non_collection_returns_empty() -> None:
    assert (
        search_support.normalize_search_response("not a collection", None) == {}
    )
    assert search_support.normalize_search_response(42, None) == {}


def test_normalize_no_tool_config_passes_through_dict() -> None:
    data = {"123": {"title": "A"}}
    assert search_support.normalize_search_response(data, None) == data


def test_normalize_no_tool_config_list_returns_empty() -> None:
    assert (
        search_support.normalize_search_response([{"title": "A"}], None) == {}
    )


def test_normalize_dict_response_default_format() -> None:
    tc = _tool_config(ResponseFormat())
    data = {"p1": {"title": "A"}, "p2": {"title": "B"}}
    assert search_support.normalize_search_response(data, tc) == data


def test_normalize_is_dict_returns_dict() -> None:
    tc = _tool_config(ResponseFormat(is_dict=True))
    data = {"p1": {"title": "A"}}
    assert search_support.normalize_search_response(data, tc) == data


def test_normalize_results_path_extracts_nested() -> None:
    tc = _tool_config(ResponseFormat(results_path="results", is_dict=True))
    nested = {"p1": {"title": "A"}}
    data = {"results": nested, "meta": "ignored"}
    assert search_support.normalize_search_response(data, tc) == nested


def test_normalize_list_response_keys_by_source_id() -> None:
    tc = _tool_config(ResponseFormat(field_mapping={"source_id": "pmid"}))
    data = [
        {"pmid": "111", "title": "A"},
        {"pmid": "222", "title": "B"},
    ]
    result = search_support.normalize_search_response(data, tc)
    assert set(result) == {"111", "222"}
    assert result["111"]["title"] == "A"


def test_normalize_list_at_prefixed_source_id_uses_arxiv_id() -> None:
    tc = _tool_config(ResponseFormat(field_mapping={"source_id": "@id"}))
    data = [{"arxiv_id": "2401.0001", "title": "A"}]
    result = search_support.normalize_search_response(data, tc)
    assert list(result) == ["2401.0001"]


def test_normalize_list_missing_ids_uses_positional_index() -> None:
    tc = _tool_config(ResponseFormat())
    data = [{"title": "A"}, {"title": "B"}]
    result = search_support.normalize_search_response(data, tc)
    assert list(result) == ["0", "1"]
    assert result["0"]["title"] == "A"


def test_build_article_maps_all_fields() -> None:
    metadata: dict[str, Any] = {
        "title": "Cancer signaling",
        "authors": ["Smith J", "Doe A"],
        "year": "2020",
        "publication": "Nature",
        "abstract": "An abstract.",
        "fulltext": "Full body text.",
        "url": "https://example.com/article",
        "doi": "10.1000/example",
        "is_retracted": True,
        "correction_status": "retracted",
    }
    article = article_support.build_article_from_metadata(
        "PMID42", metadata, source_name="pubmed", used_in_analysis=True
    )
    assert isinstance(article, Article)
    assert article.title == "Cancer signaling"
    assert article.url == "https://example.com/article"
    assert article.authors == ["Smith J", "Doe A"]
    assert article.year == 2020
    assert article.venue == "Nature"
    assert article.abstract == "An abstract."
    assert article.content == "Full body text."
    assert article.source_id == "PMID42"
    assert article.source == "pubmed"
    assert article.doi == "10.1000/example"
    assert article.is_retracted is True
    assert article.correction_status == "retracted"
    assert article.used_in_analysis is True


def test_build_article_detects_retracted_publication_type() -> None:
    article = article_support.build_article_from_metadata(
        "PMID43",
        {"publication_types": ["Journal Article", "Retracted Publication"]},
    )

    assert article.is_retracted is True
    assert article.correction_status == "retracted"


def test_build_article_carries_the_declared_publication_type() -> None:
    preprint = article_support.build_article_from_metadata(
        "PMID44", {"publication_types": ["Preprint"]}
    )
    assert preprint.publication_type == "Preprint"

    explicit = article_support.build_article_from_metadata(
        "PMID45",
        {"publication_type": "Journal Article", "publication_types": ["x"]},
    )
    assert explicit.publication_type == "Journal Article"

    assert (
        article_support.build_article_from_metadata("x", {}).publication_type
        is None
    )


def test_build_article_defaults_for_missing_fields() -> None:
    article = article_support.build_article_from_metadata(
        "x1", {}, source_name="arxiv", used_in_analysis=False
    )
    assert article.title == "unknown"
    assert article.authors == []
    assert article.year is None
    assert article.venue is None
    assert article.abstract is None
    assert article.content is None
    assert article.used_in_analysis is False


def test_build_articles_marks_metadata_only_record_unanalyzed() -> None:
    articles = article_support.build_articles_from_metadata(
        {
            "abstract": {"title": "A", "abstract": "Evidence passage"},
            "metadata": {"title": "B", "url": "https://example.test/b"},
        },
        "openalex",
    )

    assert [article.used_in_analysis for article in articles] == [True, False]


def test_build_article_venue_falls_back_to_venue_key() -> None:
    article = article_support.build_article_from_metadata(
        "x1", {"venue": "JMLR"}, source_name="arxiv"
    )
    assert article.venue == "JMLR"


def test_build_url_prefers_metadata_url() -> None:
    url = article_support._build_article_url(
        "999", {"url": "https://custom.example/x"}, "pubmed"
    )
    assert url == "https://custom.example/x"


def test_build_url_pubmed_construction() -> None:
    url = article_support._build_article_url("12345", {}, "pubmed")
    assert url == "https://pubmed.ncbi.nlm.nih.gov/12345/"


def test_build_url_doi_construction() -> None:
    url = article_support._build_article_url("10.1000/xyz123", {}, "crossref")
    assert url == "https://doi.org/10.1000/xyz123"


def test_build_url_fallback_returns_paper_id() -> None:
    url = article_support._build_article_url("arxiv:2401.0001", {}, "arxiv")
    assert url == "arxiv:2401.0001"


def test_parse_year_from_year_field() -> None:
    assert article_support.parse_year_from_metadata({"year": "2019"}) == 2019


def test_parse_year_from_year_field_int() -> None:
    assert article_support.parse_year_from_metadata({"year": 2007}) == 2007


def test_parse_year_from_date_revised() -> None:
    assert (
        article_support.parse_year_from_metadata({"date_revised": "2021/03/01"})
        == 2021
    )


def test_parse_year_garbage_returns_none() -> None:
    assert (
        article_support.parse_year_from_metadata({"year": "not-a-year"}) is None
    )


def test_parse_year_missing_returns_none() -> None:
    assert article_support.parse_year_from_metadata({}) is None


def test_parse_year_falls_back_to_date_revised_when_year_empty() -> None:
    meta = {"year": "", "date_revised": "1998/12/31"}
    assert article_support.parse_year_from_metadata(meta) == 1998


def test_count_papers_with_fulltext_mixed() -> None:
    metadata: dict[str, dict[str, Any]] = {
        "a": {"fulltext": "body"},
        "b": {"pmc_full_text_id": "PMC1"},
        "c": {"has_fulltext": True},
        "d": {"pdf_url": "http://x/p.pdf"},
        "e": {"title": "no content"},
        "f": {"abstract": "only abstract"},
    }
    with_ft, without_ft = article_support.count_papers_with_fulltext(metadata)
    assert with_ft == 4
    assert without_ft == 2


def test_count_papers_with_fulltext_ignores_non_dicts() -> None:
    metadata: dict[str, Any] = {
        "a": {"fulltext": "body"},
        "b": "not a dict",
    }
    with_ft, without_ft = article_support.count_papers_with_fulltext(metadata)
    assert with_ft == 1
    assert without_ft == 1


def test_count_papers_with_fulltext_empty() -> None:
    assert article_support.count_papers_with_fulltext({}) == (0, 0)


def test_parse_content_result_json_content_key() -> None:
    result = json.dumps({"content": "the body", "text": "ignored"})
    assert retrieval_support.parse_content_result(result) == "the body"


def test_parse_content_result_json_text_key() -> None:
    result = json.dumps({"text": "from text"})
    assert retrieval_support.parse_content_result(result) == "from text"


def test_parse_content_result_non_json_string_returns_raw() -> None:
    assert (
        retrieval_support.parse_content_result("just plain text")
        == "just plain text"
    )


def test_parse_content_result_json_without_keys_returns_raw() -> None:
    result = json.dumps({"other": "x"})
    assert retrieval_support.parse_content_result(result) == result


def test_parse_content_result_dict_content_key() -> None:
    assert (
        retrieval_support.parse_content_result({"content": "dict body"})
        == "dict body"
    )


def test_parse_content_result_dict_without_keys_stringifies() -> None:
    payload = {"other": "x"}
    assert retrieval_support.parse_content_result(payload) == str(payload)


def test_parse_content_result_none_returns_none() -> None:
    assert retrieval_support.parse_content_result(None) is None
    assert retrieval_support.parse_content_result(0) is None


def test_parse_content_result_other_type_stringifies() -> None:
    assert retrieval_support.parse_content_result(123) == "123"


def test_get_content_prefers_fulltext() -> None:
    meta = {"fulltext": "full", "abstract": "abs"}
    assert article_support.get_paper_content_for_analysis(meta) == "full"


def test_get_content_falls_back_to_abstract() -> None:
    assert (
        article_support.get_paper_content_for_analysis({"abstract": "abs"})
        == "abs"
    )


def test_abstract_only_paper_is_selected_for_analysis() -> None:
    papers = {
        "openalex-1": {"title": "A", "abstract": "Explicit abstract"},
        "metadata-only": {"title": "B"},
    }

    selected = article_support.get_papers_with_content(papers)

    assert list(selected) == ["openalex-1"]


def test_get_content_empty_returns_empty_string() -> None:
    out = article_support.get_paper_content_for_analysis({})
    assert out == ""
    assert isinstance(out, str)


def test_get_content_non_string_coerced_to_string() -> None:
    out = article_support.get_paper_content_for_analysis({"fulltext": 12345})
    assert out == "12345"
    assert isinstance(out, str)


def test_get_content_truncates_at_max_chars() -> None:
    long_text = "x" * 500
    out = article_support.get_paper_content_for_analysis(
        {"fulltext": long_text}, max_chars=100
    )
    assert out.startswith("x" * 100)
    assert out.endswith("[... truncated for length ...]")
    assert "x" * 101 not in out
    assert isinstance(out, str)


def test_get_content_no_truncation_under_limit() -> None:
    text = "short"
    out = article_support.get_paper_content_for_analysis(
        {"fulltext": text}, max_chars=100
    )
    assert out == text


def test_get_content_strips_citation_markers() -> None:
    """Source citations copied into model prose can misattribute generated
    claims."""
    meta = {"fulltext": "This was shown before (Smith et al. 2019) [12]."}
    out = article_support.get_paper_content_for_analysis(meta)
    assert "(Smith et al. 2019)" not in out
    assert "[12]" not in out


def test_get_content_leaves_stored_metadata_unchanged() -> None:
    """Citation readers need the published source; only prompt copies are
    stripped."""
    original = "This was shown before (Smith et al. 2019) [12]."
    meta = {"fulltext": original}
    article_support.get_paper_content_for_analysis(meta)
    assert meta["fulltext"] == original


def test_parse_mcp_query_result_json_list() -> None:
    result = json.dumps(["q1", "q2"])
    assert search_support.parse_mcp_query_result(result) == ["q1", "q2"]


def test_parse_mcp_query_result_json_queries_key() -> None:
    result = json.dumps({"queries": ["a", "b"]})
    assert search_support.parse_mcp_query_result(result) == ["a", "b"]


def test_parse_mcp_query_result_json_object_without_queries() -> None:
    assert search_support.parse_mcp_query_result(json.dumps({"x": 1})) == []


def test_parse_mcp_query_result_invalid_json_returns_empty() -> None:
    assert search_support.parse_mcp_query_result("not json") == []


def test_parse_mcp_query_result_list_passthrough() -> None:
    assert search_support.parse_mcp_query_result(["x", "y"]) == ["x", "y"]


def test_parse_mcp_query_result_other_type_returns_empty() -> None:
    assert search_support.parse_mcp_query_result({"queries": ["a"]}) == []


def test_merge_search_results_combines_and_maps_sources() -> None:
    source_results = [
        ("pubmed", {"p1": {"title": "Alpha"}}),
        ("arxiv", {"a1": {"title": "Beta"}}),
    ]
    merged, source_map = search_support.merge_search_results(source_results)
    assert set(merged) == {"p1", "a1"}
    assert source_map == {"p1": "pubmed", "a1": "arxiv"}


def test_merge_search_results_deduplicates_by_title() -> None:
    source_results = [
        ("pubmed", {"p1": {"title": "Shared Title"}}),
        ("arxiv", {"a1": {"title": "  shared title  "}}),
    ]
    merged, source_map = search_support.merge_search_results(source_results)
    assert set(merged) == {"p1"}
    assert source_map == {"p1": "pubmed"}


def test_merge_search_results_no_dedup_keeps_duplicates() -> None:
    source_results = [
        ("pubmed", {"p1": {"title": "Same"}}),
        ("arxiv", {"a1": {"title": "Same"}}),
    ]
    merged, _ = search_support.merge_search_results(
        source_results, deduplicate=False
    )
    assert set(merged) == {"p1", "a1"}


def test_merge_search_results_ranks_quality_and_flags_retractions() -> None:
    """Retraction overrides source rank even when a source ranks it first."""
    source_results = [
        (
            "openalex",
            {
                "weak": {
                    "title": "Weak",
                    "source": "openalex",
                    "year": 2000,
                },
                "strong": {
                    "title": "Strong",
                    "source": "pubmed",
                    "year": 2026,
                    "cited_by_count": 1000,
                },
                "retracted": {
                    "title": "Retracted",
                    "source": "pubmed",
                    "is_retracted": True,
                },
            },
        )
    ]

    merged, _ = search_support.merge_search_results(source_results)

    assert list(merged) == ["weak", "strong", "retracted"]
    assert merged["retracted"]["correction_status"] == "retracted"


def test_merge_search_results_lets_a_metadata_poor_source_compete() -> None:
    """Source-rank fusion avoids penalizing sources without citation/year
    metadata."""
    rich_source: dict[str, dict[str, Any]] = {
        f"op{i}": {
            "title": f"Openalex paper {i}",
            "source": "openalex",
            "cited_by_count": 500,
            "year": 2020,
        }
        for i in range(1, 7)
    }
    source_results = [
        ("openalex_tool", rich_source),
        ("web_tool", {"web1": {"title": "Web paper", "source": "web"}}),
    ]

    merged, _ = search_support.merge_search_results(source_results)

    assert list(merged).index("web1") <= 2


def test_merge_search_results_accumulates_cross_source_agreement() -> None:
    """Title dedup must keep both source rank contributions without
    overwrites."""
    source_results = [
        (
            "source_a_tool",
            {
                "solo": {"title": "Solo Paper"},
                "shared_a": {"title": "Shared Paper", "note": "from A"},
                "filler_a": {"title": "Filler A"},
            },
        ),
        (
            "source_b_tool",
            {
                "other_b": {"title": "Other B"},
                "shared_b": {"title": "Shared Paper", "note": "from B"},
                "filler_b": {"title": "Filler B"},
            },
        ),
    ]

    merged, source_map = search_support.merge_search_results(source_results)

    assert list(merged).index("shared_a") < list(merged).index("solo")
    # Dedup accumulates rank while preserving first-source metadata/provenance.
    assert "shared_b" not in merged
    assert merged["shared_a"]["note"] == "from A"
    assert source_map["shared_a"] == "source_a_tool"


def test_parse_pdf_discovery_json_list_first_element() -> None:
    result = json.dumps(["http://x/p.pdf", "http://y/p.pdf"])
    assert (
        retrieval_support.parse_pdf_discovery_result(result) == "http://x/p.pdf"
    )


def test_parse_pdf_discovery_json_dict_pdf_links() -> None:
    result = json.dumps({"pdf_links": ["http://x/a.pdf"]})
    assert (
        retrieval_support.parse_pdf_discovery_result(result) == "http://x/a.pdf"
    )


def test_parse_pdf_discovery_json_dict_links_with_url() -> None:
    result = json.dumps({"links": [{"url": "http://x/b.pdf"}]})
    assert (
        retrieval_support.parse_pdf_discovery_result(result) == "http://x/b.pdf"
    )


def test_parse_pdf_discovery_bare_http_string() -> None:
    assert (
        retrieval_support.parse_pdf_discovery_result("http://x/c.pdf")
        == "http://x/c.pdf"
    )


def test_parse_pdf_discovery_non_url_string_returns_none() -> None:
    assert retrieval_support.parse_pdf_discovery_result("nope") is None


def test_parse_pdf_discovery_list_input_string() -> None:
    assert (
        retrieval_support.parse_pdf_discovery_result(["http://x/d.pdf"])
        == "http://x/d.pdf"
    )


def test_parse_pdf_discovery_list_input_dict() -> None:
    assert (
        retrieval_support.parse_pdf_discovery_result(
            [{"url": "http://x/e.pdf"}]
        )
        == "http://x/e.pdf"
    )


def test_parse_pdf_discovery_empty_returns_none() -> None:
    assert retrieval_support.parse_pdf_discovery_result([]) is None
    assert retrieval_support.parse_pdf_discovery_result(None) is None


class _FakeExceptionGroupError(Exception):
    """Duck-typed stand-in for ``ExceptionGroup`` (portable to Python 3.10).

    Exposes the ``exceptions`` tuple that ``describe_exception`` unwraps,
    mirroring the real ``ExceptionGroup`` the anyio-based MCP transport raises.
    """

    def __init__(self, message: str, exceptions: list[BaseException]) -> None:
        super().__init__(message)
        self.exceptions = tuple(exceptions)


def test_describe_exc_plain_exception() -> None:
    assert (
        errors.describe_exception(ValueError("bad input"))
        == "ValueError: bad input"
    )


def test_describe_exc_unwraps_exception_group() -> None:
    leaf = ConnectionError("All connection attempts failed")
    group = _FakeExceptionGroupError("unhandled errors in a TaskGroup", [leaf])
    assert (
        errors.describe_exception(group)
        == "ConnectionError: All connection attempts failed"
    )


def test_get_search_config_defaults_single_source() -> None:
    config = lr.search_config_for(make_state())
    assert config.is_multi_source is False
    assert config.source_name == "pubmed"
    assert config.search_tool_name == "pubmed_search_with_fulltext"
    assert config.search_tool_config is None
    assert config.tool_registry is None
    assert config.papers_to_read_count > 0


def test_get_search_config_honors_run_paper_count() -> None:
    config = lr.search_config_for(make_state(literature_review_papers_count=12))
    assert config.papers_to_read_count == 12


def test_get_search_config_reads_dev_mode_from_state() -> None:
    config = lr.search_config_for(
        make_state(dev_mode=True, literature_review_papers_count=12)
    )
    assert config.is_dev_mode is True
    assert config.papers_to_read_count == LITERATURE_REVIEW_PAPERS_COUNT_DEV


def test_get_search_config_ignores_the_ambient_dev_mode_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run boundary resolves dev mode; rereading process env changes its
    budget."""
    monkeypatch.setenv("COSCIENTIST_DEV_MODE", "true")
    config = lr.search_config_for(make_state(literature_review_papers_count=12))
    assert config.is_dev_mode is False
    assert config.papers_to_read_count == 12


def test_literature_cache_key_covers_tool_contract_and_budget() -> None:
    legacy_state = make_state(
        model_name="model-a", literature_review_papers_count=4
    )
    registry_state = make_state(
        model_name="model-a",
        literature_review_papers_count=8,
        tool_registry=ToolRegistry(skip_user_config=True),
    )
    legacy = lr._literature_cache_params(
        legacy_state, lr.search_config_for(legacy_state)
    )
    multi_source = lr._literature_cache_params(
        registry_state, lr.search_config_for(registry_state)
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
        "europepmc_search",
        "web_search",
        "arxiv_search",
        "biorxiv_search",
    ]
    assert legacy != multi_source


def test_a_tier_that_researches_cannot_replay_one_that_did_not() -> None:
    """Cross-tier cache reuse can import or erase another tier research
    ledger."""
    shallow = make_state(model_name="model-a", research_tier="")
    deep = make_state(model_name="model-a", research_tier="extended")

    assert lr._literature_cache_params(
        shallow, lr.search_config_for(shallow)
    ) != lr._literature_cache_params(deep, lr.search_config_for(deep))


def test_format_kg_section_empty_returns_empty_string() -> None:
    assert lr_enrichment._format_kg_section_with_keys([], 0) == ""


def test_format_kg_section_keys_start_after_paper_count() -> None:
    sources = [{"display": "Gene X -> Gene Y"}, {"display": "Gene Y -> Gene Z"}]
    section = lr_enrichment._format_kg_section_with_keys(sources, 2)
    assert "## Knowledge Graph Evidence" in section
    assert "[C3] Gene X -> Gene Y" in section
    assert "[C4] Gene Y -> Gene Z" in section


def test_format_kg_section_missing_display_uses_default() -> None:
    section = lr_enrichment._format_kg_section_with_keys([{}], 0)
    assert "[C1] External source" in section


def test_parse_enrichment_indra_empty_statements() -> None:
    text, items = lr_enrichment._parse_enrichment_result({"statements": []})
    assert text == ""
    assert items == []


def test_parse_enrichment_indra_statements_formatted() -> None:
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
    raw = {"results": [{"n": i} for i in range(10)]}
    text, items = lr_enrichment._parse_enrichment_result(raw)
    cap = lr_enrichment._CONTEXT_ENRICHMENT_RESULTS_PER_ENTITY
    assert len(items) == cap
    assert text


def test_parse_enrichment_plain_string_non_json() -> None:
    text, items = lr_enrichment._parse_enrichment_result("free-form text")
    assert text == "free-form text"
    assert items == [{"display": "free-form text", "data": {}}]
