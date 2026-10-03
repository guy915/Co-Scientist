"""Offline contracts for literature review helpers."""

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
    """Build a minimal ToolConfig for the helper tests.

    These tests vary the response format and source type rather than the
    tool name, so the shared builder's name argument is pinned to ``"t"``.

    Args:
        response_format: The parsing format under test, or None for the
            schema default.
        source_type: The tool's declared source type.

    Returns:
        A ToolConfig carrying the given format and source type.
    """
    return make_tool_config(
        "t",
        source_type=source_type,
        response_format=response_format or ResponseFormat(),
    )


# =============================================================================
# extract_source_name
# =============================================================================


def test_extract_source_name_none_returns_unknown() -> None:
    """A missing tool config falls back to the literal ``unknown``."""
    assert search_support.extract_source_name(None) == "unknown"


def test_extract_source_name_from_quoted_field_mapping() -> None:
    """A quoted ``source`` literal in the field mapping is unquoted."""
    tc = _tool_config(ResponseFormat(field_mapping={"source": "'pubmed'"}))
    assert search_support.extract_source_name(tc) == "pubmed"


def test_extract_source_name_unquoted_mapping_falls_back_to_source_type() -> (
    None
):
    """A non-literal mapping value falls through to ``source_type``."""
    tc = _tool_config(
        ResponseFormat(field_mapping={"source": "paper.source"}),
        source_type="preprint",
    )
    assert search_support.extract_source_name(tc) == "preprint"


def test_extract_source_name_no_mapping_uses_source_type() -> None:
    """With no field mapping the source type is returned."""
    tc = _tool_config(ResponseFormat(), source_type="arxiv")
    assert search_support.extract_source_name(tc) == "arxiv"


# =============================================================================
# normalize_search_response
# =============================================================================


def test_normalize_non_collection_returns_empty() -> None:
    """A non-dict, non-list payload normalizes to an empty dict."""
    assert (
        search_support.normalize_search_response("not a collection", None) == {}
    )
    assert search_support.normalize_search_response(42, None) == {}


def test_normalize_no_tool_config_passes_through_dict() -> None:
    """Without a tool config, a dict response is returned unchanged."""
    data = {"123": {"title": "A"}}
    assert search_support.normalize_search_response(data, None) == data


def test_normalize_no_tool_config_list_returns_empty() -> None:
    """Without a tool config, a list response yields an empty dict."""
    assert (
        search_support.normalize_search_response([{"title": "A"}], None) == {}
    )


def test_normalize_dict_response_default_format() -> None:
    """A dict response with the default (is_dict=False) format passes through.

    ``results_path`` defaults to ``"."`` so no extraction happens, and a dict
    that is neither a list nor flagged ``is_dict`` returns as-is.
    """
    tc = _tool_config(ResponseFormat())
    data = {"p1": {"title": "A"}, "p2": {"title": "B"}}
    assert search_support.normalize_search_response(data, tc) == data


def test_normalize_is_dict_returns_dict() -> None:
    """An ``is_dict=True`` format returns the dict directly."""
    tc = _tool_config(ResponseFormat(is_dict=True))
    data = {"p1": {"title": "A"}}
    assert search_support.normalize_search_response(data, tc) == data


def test_normalize_results_path_extracts_nested() -> None:
    """A non-trivial ``results_path`` extracts the nested results object."""
    tc = _tool_config(ResponseFormat(results_path="results", is_dict=True))
    nested = {"p1": {"title": "A"}}
    data = {"results": nested, "meta": "ignored"}
    assert search_support.normalize_search_response(data, tc) == nested


def test_normalize_list_response_keys_by_source_id() -> None:
    """A list response is keyed by the configured ``source_id`` field."""
    tc = _tool_config(ResponseFormat(field_mapping={"source_id": "pmid"}))
    data = [
        {"pmid": "111", "title": "A"},
        {"pmid": "222", "title": "B"},
    ]
    result = search_support.normalize_search_response(data, tc)
    assert set(result) == {"111", "222"}
    assert result["111"]["title"] == "A"


def test_normalize_list_at_prefixed_source_id_uses_arxiv_id() -> None:
    """An ``@``-prefixed source_id mapping falls back to the arxiv_id field."""
    tc = _tool_config(ResponseFormat(field_mapping={"source_id": "@id"}))
    data = [{"arxiv_id": "2401.0001", "title": "A"}]
    result = search_support.normalize_search_response(data, tc)
    assert list(result) == ["2401.0001"]


def test_normalize_list_missing_ids_uses_positional_index() -> None:
    """Papers with no id fall back to their positional index as the key."""
    tc = _tool_config(ResponseFormat())
    data = [{"title": "A"}, {"title": "B"}]
    result = search_support.normalize_search_response(data, tc)
    # Default source_id field is "source_id"; absent on both, so str(index).
    assert list(result) == ["0", "1"]
    assert result["0"]["title"] == "A"


# =============================================================================
# build_article_from_metadata
# =============================================================================


def test_build_article_maps_all_fields() -> None:
    """Metadata fields map onto the corresponding Article attributes."""
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
    """PubMed retraction metadata survives into the durable Article."""
    article = article_support.build_article_from_metadata(
        "PMID43",
        {"publication_types": ["Journal Article", "Retracted Publication"]},
    )

    assert article.is_retracted is True
    assert article.correction_status == "retracted"


def test_build_article_carries_the_declared_publication_type() -> None:
    """PubMed's plural ``publication_types`` reaches ``publication_type``.

    Only the singular key was read, and no source sends it, so the field
    was always None -- discarding the one signal that separates a preprint
    PubMed indexes from the journal articles beside it (the app classifies
    a citation's source type from it; see ``app/citations/metadata.py``).
    """
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
    """Missing metadata yields safe defaults (unknown title, no authors)."""
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
    """A title and URL alone cannot inflate the analyzed-source count."""
    articles = article_support.build_articles_from_metadata(
        {
            "abstract": {"title": "A", "abstract": "Evidence passage"},
            "metadata": {"title": "B", "url": "https://example.test/b"},
        },
        "openalex",
    )

    assert [article.used_in_analysis for article in articles] == [True, False]


def test_build_article_venue_falls_back_to_venue_key() -> None:
    """When ``publication`` is absent the ``venue`` key is used."""
    article = article_support.build_article_from_metadata(
        "x1", {"venue": "JMLR"}, source_name="arxiv"
    )
    assert article.venue == "JMLR"


# =============================================================================
# _build_article_url
# =============================================================================


def test_build_url_prefers_metadata_url() -> None:
    """An explicit metadata URL takes precedence over construction."""
    url = article_support._build_article_url(
        "999", {"url": "https://custom.example/x"}, "pubmed"
    )
    assert url == "https://custom.example/x"


def test_build_url_pubmed_construction() -> None:
    """A pubmed source with no URL builds the canonical pubmed URL."""
    url = article_support._build_article_url("12345", {}, "pubmed")
    assert url == "https://pubmed.ncbi.nlm.nih.gov/12345/"


def test_build_url_doi_construction() -> None:
    """A DOI-style id on a non-pubmed source builds a doi.org URL."""
    url = article_support._build_article_url("10.1000/xyz123", {}, "crossref")
    assert url == "https://doi.org/10.1000/xyz123"


def test_build_url_fallback_returns_paper_id() -> None:
    """A non-pubmed, non-DOI id with no URL falls back to the raw id."""
    url = article_support._build_article_url("arxiv:2401.0001", {}, "arxiv")
    assert url == "arxiv:2401.0001"


# =============================================================================
# parse_year_from_metadata
# =============================================================================


def test_parse_year_from_year_field() -> None:
    """A numeric-string ``year`` field parses to an int."""
    assert article_support.parse_year_from_metadata({"year": "2019"}) == 2019


def test_parse_year_from_year_field_int() -> None:
    """An int ``year`` field is returned as-is."""
    assert article_support.parse_year_from_metadata({"year": 2007}) == 2007


def test_parse_year_from_date_revised() -> None:
    """A ``date_revised`` like ``2021/03/01`` yields the leading year."""
    assert (
        article_support.parse_year_from_metadata({"date_revised": "2021/03/01"})
        == 2021
    )


def test_parse_year_garbage_returns_none() -> None:
    """A non-numeric year with no usable fallback returns None."""
    assert (
        article_support.parse_year_from_metadata({"year": "not-a-year"}) is None
    )


def test_parse_year_missing_returns_none() -> None:
    """Empty metadata yields no year."""
    assert article_support.parse_year_from_metadata({}) is None


def test_parse_year_falls_back_to_date_revised_when_year_empty() -> None:
    """An empty ``year`` falls through to ``date_revised`` parsing."""
    meta = {"year": "", "date_revised": "1998/12/31"}
    assert article_support.parse_year_from_metadata(meta) == 1998


# =============================================================================
# count_papers_with_fulltext
# =============================================================================


def test_count_papers_with_fulltext_mixed() -> None:
    """A mix of fulltext indicators is counted as (with, without)."""
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
    """Non-dict metadata entries are skipped but still counted as 'without'."""
    metadata: dict[str, Any] = {
        "a": {"fulltext": "body"},
        "b": "not a dict",
    }
    with_ft, without_ft = article_support.count_papers_with_fulltext(metadata)
    assert with_ft == 1
    assert without_ft == 1


def test_count_papers_with_fulltext_empty() -> None:
    """An empty metadata mapping has zero of both."""
    assert article_support.count_papers_with_fulltext({}) == (0, 0)


# =============================================================================
# parse_content_result
# =============================================================================


def test_parse_content_result_json_content_key() -> None:
    """A JSON string with a ``content`` key extracts that content."""
    result = json.dumps({"content": "the body", "text": "ignored"})
    assert retrieval_support.parse_content_result(result) == "the body"


def test_parse_content_result_json_text_key() -> None:
    """A JSON string with only ``text`` extracts the text value."""
    result = json.dumps({"text": "from text"})
    assert retrieval_support.parse_content_result(result) == "from text"


def test_parse_content_result_non_json_string_returns_raw() -> None:
    """A plain (non-JSON) string is returned verbatim."""
    assert (
        retrieval_support.parse_content_result("just plain text")
        == "just plain text"
    )


def test_parse_content_result_json_without_keys_returns_raw() -> None:
    """A JSON object lacking content/text falls back to the raw string."""
    result = json.dumps({"other": "x"})
    assert retrieval_support.parse_content_result(result) == result


def test_parse_content_result_dict_content_key() -> None:
    """A dict input with a ``content`` key extracts that content."""
    assert (
        retrieval_support.parse_content_result({"content": "dict body"})
        == "dict body"
    )


def test_parse_content_result_dict_without_keys_stringifies() -> None:
    """A dict lacking content/text is stringified."""
    payload = {"other": "x"}
    assert retrieval_support.parse_content_result(payload) == str(payload)


def test_parse_content_result_none_returns_none() -> None:
    """A falsy non-string, non-dict result returns None."""
    assert retrieval_support.parse_content_result(None) is None
    assert retrieval_support.parse_content_result(0) is None


def test_parse_content_result_other_type_stringifies() -> None:
    """A truthy non-string, non-dict result is stringified."""
    assert retrieval_support.parse_content_result(123) == "123"


# =============================================================================
# get_paper_content_for_analysis
# =============================================================================


def test_get_content_prefers_fulltext() -> None:
    """Fulltext is preferred over abstract for analysis content."""
    meta = {"fulltext": "full", "abstract": "abs"}
    assert article_support.get_paper_content_for_analysis(meta) == "full"


def test_get_content_falls_back_to_abstract() -> None:
    """With no fulltext, the abstract is used."""
    assert (
        article_support.get_paper_content_for_analysis({"abstract": "abs"})
        == "abs"
    )


def test_abstract_only_paper_is_selected_for_analysis() -> None:
    """Abstract-index sources contribute bounded evidence without a PDF."""
    papers = {
        "openalex-1": {"title": "A", "abstract": "Explicit abstract"},
        "metadata-only": {"title": "B"},
    }

    selected = article_support.get_papers_with_content(papers)

    assert list(selected) == ["openalex-1"]


def test_get_content_empty_returns_empty_string() -> None:
    """No content yields an empty string, never None."""
    out = article_support.get_paper_content_for_analysis({})
    assert out == ""
    assert isinstance(out, str)


def test_get_content_non_string_coerced_to_string() -> None:
    """A non-string fulltext value is coerced to a string."""
    out = article_support.get_paper_content_for_analysis({"fulltext": 12345})
    assert out == "12345"
    assert isinstance(out, str)


def test_get_content_truncates_at_max_chars() -> None:
    """Content longer than ``max_chars`` is truncated with a marker suffix."""
    long_text = "x" * 500
    out = article_support.get_paper_content_for_analysis(
        {"fulltext": long_text}, max_chars=100
    )
    assert out.startswith("x" * 100)
    assert out.endswith("[... truncated for length ...]")
    assert "x" * 101 not in out
    assert isinstance(out, str)


def test_get_content_no_truncation_under_limit() -> None:
    """Content within the limit is returned untouched."""
    text = "short"
    out = article_support.get_paper_content_for_analysis(
        {"fulltext": text}, max_chars=100
    )
    assert out == text


def test_get_content_strips_citation_markers() -> None:
    """The source paper's own citation markers do not reach the prompt.

    Left in, a drafting model can copy one into its own prose -- a
    real-looking reference attached to a claim the cited source never
    made.
    """
    meta = {"fulltext": "This was shown before (Smith et al. 2019) [12]."}
    out = article_support.get_paper_content_for_analysis(meta)
    assert "(Smith et al. 2019)" not in out
    assert "[12]" not in out


def test_get_content_leaves_stored_metadata_unchanged() -> None:
    """Stripping is for the prompt copy only, never for storage.

    ``metadata`` stands in for what an ``Article`` is built from; a
    reader following a citation into the source needs the source as
    published.
    """
    original = "This was shown before (Smith et al. 2019) [12]."
    meta = {"fulltext": original}
    article_support.get_paper_content_for_analysis(meta)
    assert meta["fulltext"] == original


# =============================================================================
# parse_mcp_query_result
# =============================================================================


def test_parse_mcp_query_result_json_list() -> None:
    """A JSON-array string parses to the list of queries."""
    result = json.dumps(["q1", "q2"])
    assert search_support.parse_mcp_query_result(result) == ["q1", "q2"]


def test_parse_mcp_query_result_json_queries_key() -> None:
    """A JSON object with a ``queries`` key extracts that list."""
    result = json.dumps({"queries": ["a", "b"]})
    assert search_support.parse_mcp_query_result(result) == ["a", "b"]


def test_parse_mcp_query_result_json_object_without_queries() -> None:
    """A JSON object lacking ``queries`` yields an empty list."""
    assert search_support.parse_mcp_query_result(json.dumps({"x": 1})) == []


def test_parse_mcp_query_result_invalid_json_returns_empty() -> None:
    """A non-JSON string returns an empty list."""
    assert search_support.parse_mcp_query_result("not json") == []


def test_parse_mcp_query_result_list_passthrough() -> None:
    """A list input is returned unchanged."""
    assert search_support.parse_mcp_query_result(["x", "y"]) == ["x", "y"]


def test_parse_mcp_query_result_other_type_returns_empty() -> None:
    """A non-string, non-list input yields an empty list."""
    assert search_support.parse_mcp_query_result({"queries": ["a"]}) == []


# =============================================================================
# merge_search_results
# =============================================================================


def test_merge_search_results_combines_and_maps_sources() -> None:
    """Results from multiple sources merge with a paper -> source map."""
    source_results = [
        ("pubmed", {"p1": {"title": "Alpha"}}),
        ("arxiv", {"a1": {"title": "Beta"}}),
    ]
    merged, source_map = search_support.merge_search_results(source_results)
    assert set(merged) == {"p1", "a1"}
    assert source_map == {"p1": "pubmed", "a1": "arxiv"}


def test_merge_search_results_deduplicates_by_title() -> None:
    """A title seen earlier (case/space-insensitive) is dropped."""
    source_results = [
        ("pubmed", {"p1": {"title": "Shared Title"}}),
        ("arxiv", {"a1": {"title": "  shared title  "}}),
    ]
    merged, source_map = search_support.merge_search_results(source_results)
    assert set(merged) == {"p1"}
    assert source_map == {"p1": "pubmed"}


def test_merge_search_results_no_dedup_keeps_duplicates() -> None:
    """With ``deduplicate=False`` duplicate titles are all retained."""
    source_results = [
        ("pubmed", {"p1": {"title": "Same"}}),
        ("arxiv", {"a1": {"title": "Same"}}),
    ]
    merged, _ = search_support.merge_search_results(
        source_results, deduplicate=False
    )
    assert set(merged) == {"p1", "a1"}


def test_merge_search_results_ranks_quality_and_flags_retractions() -> None:
    """A single source's own order survives; a retracted paper sorts last.

    Fusion is rank-based (Reciprocal Rank Fusion), not score-based, so a
    single source degenerates to exactly its own insertion order --
    "weak" outranks "strong" here only because the source itself
    returned it first, regardless of either paper's citation count or
    year. Retraction is the one thing that overrides rank: it always
    sorts last, whatever position the source gave it.
    """
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
    """A source's own rank-1 result places near the top of the fused pool.

    Regression for the additive scorer this replaces: a source
    contributing no ``cited_by_count``/``year`` was capped at the
    "anything else" quality floor, which the semantic pass's normalizer
    then floors to exactly 0.0 -- so that source's best result could never
    outrank a citation-rich source's, however highly its own search
    ranked it. Reciprocal rank fusion scores by each source's own rank
    order instead, so a source's rank-1 result competes on rank alone,
    not on metadata it structurally cannot carry.
    """
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
    """A paper both sources rank outranks one only source ranks slightly higher.

    Regression for the dedup branch: folding a duplicate title into its
    earlier entry must still let the duplicate's own rank contribute to
    that entry's fused score, the same as if it were a distinct paper
    RRF happened to score identically. The old code's dedup branch hit
    ``continue`` before the accumulation line ever ran, so a paper found
    by two sources silently kept only the first source's contribution --
    exactly the cross-source agreement RRF exists to reward.

    Every item here carries no ``source``/``_source_name`` tag, so every
    position score uses the same default weight (1.0) and the math is
    verifiable by hand: position 0 scores 1/(0+2)=0.5, position 1 scores
    1/(1+2)=0.3333. "shared" sits at position 1 in both source lists
    (0.3333 + 0.3333 = 0.6667 once folded); "solo" sits at position 0 in
    one list only (0.5) -- a strictly better rank in its own source, but
    the paper only one source ever saw.
    """
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
    # The folded duplicate contributes its rank but not its own entry:
    # the surviving id keeps the first-seen source's metadata and
    # provenance, never overwritten by the later duplicate.
    assert "shared_b" not in merged
    assert merged["shared_a"]["note"] == "from A"
    assert source_map["shared_a"] == "source_a_tool"


# =============================================================================
# parse_pdf_discovery_result
# =============================================================================


def test_parse_pdf_discovery_json_list_first_element() -> None:
    """A JSON-array string returns its first element."""
    result = json.dumps(["http://x/p.pdf", "http://y/p.pdf"])
    assert (
        retrieval_support.parse_pdf_discovery_result(result) == "http://x/p.pdf"
    )


def test_parse_pdf_discovery_json_dict_pdf_links() -> None:
    """A JSON object with ``pdf_links`` returns the first string link."""
    result = json.dumps({"pdf_links": ["http://x/a.pdf"]})
    assert (
        retrieval_support.parse_pdf_discovery_result(result) == "http://x/a.pdf"
    )


def test_parse_pdf_discovery_json_dict_links_with_url() -> None:
    """A ``links`` entry that is a dict resolves via its ``url`` field."""
    result = json.dumps({"links": [{"url": "http://x/b.pdf"}]})
    assert (
        retrieval_support.parse_pdf_discovery_result(result) == "http://x/b.pdf"
    )


def test_parse_pdf_discovery_bare_http_string() -> None:
    """A non-JSON string starting with http is treated as the URL."""
    assert (
        retrieval_support.parse_pdf_discovery_result("http://x/c.pdf")
        == "http://x/c.pdf"
    )


def test_parse_pdf_discovery_non_url_string_returns_none() -> None:
    """A non-JSON, non-http string yields None."""
    assert retrieval_support.parse_pdf_discovery_result("nope") is None


def test_parse_pdf_discovery_list_input_string() -> None:
    """A list input returns its first element when it is a string."""
    assert (
        retrieval_support.parse_pdf_discovery_result(["http://x/d.pdf"])
        == "http://x/d.pdf"
    )


def test_parse_pdf_discovery_list_input_dict() -> None:
    """A list input whose first element is a dict resolves via ``url``."""
    assert (
        retrieval_support.parse_pdf_discovery_result(
            [{"url": "http://x/e.pdf"}]
        )
        == "http://x/e.pdf"
    )


def test_parse_pdf_discovery_empty_returns_none() -> None:
    """Empty / unhandled inputs return None."""
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
    """A plain exception is rendered as ``Type: message``."""
    assert (
        errors.describe_exception(ValueError("bad input"))
        == "ValueError: bad input"
    )


def test_describe_exc_unwraps_exception_group() -> None:
    """A grouped exception is unwrapped to its underlying leaf cause."""
    leaf = ConnectionError("All connection attempts failed")
    group = _FakeExceptionGroupError("unhandled errors in a TaskGroup", [leaf])
    assert (
        errors.describe_exception(group)
        == "ConnectionError: All connection attempts failed"
    )


def test_get_search_config_defaults_single_source() -> None:
    """With no tool registry the config defaults to single-source pubmed."""
    config = lr.search_config_for(make_state())
    assert config.is_multi_source is False
    assert config.source_name == "pubmed"
    assert config.search_tool_name == "pubmed_search_with_fulltext"
    assert config.search_tool_config is None
    assert config.tool_registry is None
    assert config.papers_to_read_count > 0


def test_get_search_config_honors_run_paper_count() -> None:
    """Per-run literature count overrides the default outside dev mode."""
    config = lr.search_config_for(make_state(literature_review_papers_count=12))
    assert config.papers_to_read_count == 12


def test_get_search_config_reads_dev_mode_from_state() -> None:
    """Dev mode arrives as run state and shrinks the evidence budget."""
    config = lr.search_config_for(
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
    config = lr.search_config_for(make_state(literature_review_papers_count=12))
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
    """The review a deep tier produces is a different review.

    Without the tier in the key, an extended run replays an express
    run's cached review and gets no research despite paying for the
    tier, and the reverse imports another tier's ledger.
    """
    shallow = make_state(model_name="model-a", research_tier="")
    deep = make_state(model_name="model-a", research_tier="extended")

    assert lr._literature_cache_params(
        shallow, lr.search_config_for(shallow)
    ) != lr._literature_cache_params(deep, lr.search_config_for(deep))


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
