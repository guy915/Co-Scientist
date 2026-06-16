# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for the pure, network-free literature review helpers.

The functions under test in ``co_scientist.nodes.literature_review_helpers``
do no I/O: they map response/metadata dicts into ``Article`` objects, parse
years and content payloads, count fulltext availability, and normalize the
raw search-tool responses. These tests lock in that deterministic behavior
without any LLM, MCP, or network mocking.
"""

import json
from typing import Any

from co_scientist.config.schema import ResponseFormat
from co_scientist.config.schema import ToolConfig
from co_scientist.models import Article
from co_scientist.nodes import literature_review_helpers as helpers


def _tool_config(
    response_format: ResponseFormat | None = None,
    source_type: str = "academic",
) -> ToolConfig:
    """Build a minimal ToolConfig for the helper tests."""
    return ToolConfig(
        server="s",
        mcp_tool_name="t",
        source_type=source_type,
        response_format=response_format or ResponseFormat(),
    )


# =============================================================================
# extract_source_name
# =============================================================================


def test_extract_source_name_none_returns_unknown() -> None:
    """A missing tool config falls back to the literal ``unknown``."""
    assert helpers.extract_source_name(None) == "unknown"


def test_extract_source_name_from_quoted_field_mapping() -> None:
    """A quoted ``source`` literal in the field mapping is unquoted."""
    tc = _tool_config(
        ResponseFormat(field_mapping={"source": "'pubmed'"}))
    assert helpers.extract_source_name(tc) == "pubmed"


def test_extract_source_name_unquoted_mapping_falls_back_to_source_type(
) -> None:
    """A non-literal mapping value falls through to ``source_type``."""
    tc = _tool_config(
        ResponseFormat(field_mapping={"source": "paper.source"}),
        source_type="preprint",
    )
    assert helpers.extract_source_name(tc) == "preprint"


def test_extract_source_name_no_mapping_uses_source_type() -> None:
    """With no field mapping the source type is returned."""
    tc = _tool_config(ResponseFormat(), source_type="arxiv")
    assert helpers.extract_source_name(tc) == "arxiv"


# =============================================================================
# normalize_search_response
# =============================================================================


def test_normalize_non_collection_returns_empty() -> None:
    """A non-dict, non-list payload normalizes to an empty dict."""
    assert helpers.normalize_search_response("not a collection", None) == {}
    assert helpers.normalize_search_response(42, None) == {}


def test_normalize_no_tool_config_passes_through_dict() -> None:
    """Without a tool config, a dict response is returned unchanged."""
    data = {"123": {"title": "A"}}
    assert helpers.normalize_search_response(data, None) == data


def test_normalize_no_tool_config_list_returns_empty() -> None:
    """Without a tool config, a list response yields an empty dict."""
    assert helpers.normalize_search_response([{"title": "A"}], None) == {}


def test_normalize_dict_response_default_format() -> None:
    """A dict response with the default (is_dict=False) format passes through.

    ``results_path`` defaults to ``"."`` so no extraction happens, and a dict
    that is neither a list nor flagged ``is_dict`` returns as-is.
    """
    tc = _tool_config(ResponseFormat())
    data = {"p1": {"title": "A"}, "p2": {"title": "B"}}
    assert helpers.normalize_search_response(data, tc) == data


def test_normalize_is_dict_returns_dict() -> None:
    """An ``is_dict=True`` format returns the dict directly."""
    tc = _tool_config(ResponseFormat(is_dict=True))
    data = {"p1": {"title": "A"}}
    assert helpers.normalize_search_response(data, tc) == data


def test_normalize_results_path_extracts_nested() -> None:
    """A non-trivial ``results_path`` extracts the nested results object."""
    tc = _tool_config(ResponseFormat(results_path="results", is_dict=True))
    nested = {"p1": {"title": "A"}}
    data = {"results": nested, "meta": "ignored"}
    assert helpers.normalize_search_response(data, tc) == nested


def test_normalize_list_response_keys_by_source_id() -> None:
    """A list response is keyed by the configured ``source_id`` field."""
    tc = _tool_config(
        ResponseFormat(field_mapping={"source_id": "pmid"}))
    data = [
        {"pmid": "111", "title": "A"},
        {"pmid": "222", "title": "B"},
    ]
    result = helpers.normalize_search_response(data, tc)
    assert set(result) == {"111", "222"}
    assert result["111"]["title"] == "A"


def test_normalize_list_at_prefixed_source_id_uses_arxiv_id() -> None:
    """An ``@``-prefixed source_id mapping falls back to the arxiv_id field."""
    tc = _tool_config(
        ResponseFormat(field_mapping={"source_id": "@id"}))
    data = [{"arxiv_id": "2401.0001", "title": "A"}]
    result = helpers.normalize_search_response(data, tc)
    assert list(result) == ["2401.0001"]


def test_normalize_list_missing_ids_uses_positional_index() -> None:
    """Papers with no id fall back to their positional index as the key."""
    tc = _tool_config(ResponseFormat())
    data = [{"title": "A"}, {"title": "B"}]
    result = helpers.normalize_search_response(data, tc)
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
    }
    article = helpers.build_article_from_metadata(
        "PMID42", metadata, source_name="pubmed", used_in_analysis=True)
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
    assert article.used_in_analysis is True


def test_build_article_defaults_for_missing_fields() -> None:
    """Missing metadata yields safe defaults (title 'unknown', empty authors).
    """
    article = helpers.build_article_from_metadata(
        "x1", {}, source_name="arxiv", used_in_analysis=False)
    assert article.title == "unknown"
    assert article.authors == []
    assert article.year is None
    assert article.venue is None
    assert article.abstract is None
    assert article.content is None
    assert article.used_in_analysis is False


def test_build_article_venue_falls_back_to_venue_key() -> None:
    """When ``publication`` is absent the ``venue`` key is used."""
    article = helpers.build_article_from_metadata(
        "x1", {"venue": "JMLR"}, source_name="arxiv")
    assert article.venue == "JMLR"


# =============================================================================
# _build_article_url
# =============================================================================


def test_build_url_prefers_metadata_url() -> None:
    """An explicit metadata URL takes precedence over construction."""
    url = helpers._build_article_url(  # pylint: disable=protected-access
        "999", {"url": "https://custom.example/x"}, "pubmed")
    assert url == "https://custom.example/x"


def test_build_url_pubmed_construction() -> None:
    """A pubmed source with no URL builds the canonical pubmed URL."""
    url = helpers._build_article_url(  # pylint: disable=protected-access
        "12345", {}, "pubmed")
    assert url == "https://pubmed.ncbi.nlm.nih.gov/12345/"


def test_build_url_doi_construction() -> None:
    """A DOI-style id on a non-pubmed source builds a doi.org URL."""
    url = helpers._build_article_url(  # pylint: disable=protected-access
        "10.1000/xyz123", {}, "crossref")
    assert url == "https://doi.org/10.1000/xyz123"


def test_build_url_fallback_returns_paper_id() -> None:
    """A non-pubmed, non-DOI id with no URL falls back to the raw id."""
    url = helpers._build_article_url(  # pylint: disable=protected-access
        "arxiv:2401.0001", {}, "arxiv")
    assert url == "arxiv:2401.0001"


# =============================================================================
# _parse_year_from_metadata
# =============================================================================


def test_parse_year_from_year_field() -> None:
    """A numeric-string ``year`` field parses to an int."""
    assert helpers._parse_year_from_metadata(  # pylint: disable=protected-access
        {"year": "2019"}) == 2019


def test_parse_year_from_year_field_int() -> None:
    """An int ``year`` field is returned as-is."""
    assert helpers._parse_year_from_metadata(  # pylint: disable=protected-access
        {"year": 2007}) == 2007


def test_parse_year_from_date_revised() -> None:
    """A ``date_revised`` like ``2021/03/01`` yields the leading year."""
    assert helpers._parse_year_from_metadata(  # pylint: disable=protected-access
        {"date_revised": "2021/03/01"}) == 2021


def test_parse_year_garbage_returns_none() -> None:
    """A non-numeric year with no usable fallback returns None."""
    assert helpers._parse_year_from_metadata(  # pylint: disable=protected-access
        {"year": "not-a-year"}) is None


def test_parse_year_missing_returns_none() -> None:
    """Empty metadata yields no year."""
    assert helpers._parse_year_from_metadata({}) is None  # pylint: disable=protected-access


def test_parse_year_falls_back_to_date_revised_when_year_empty() -> None:
    """An empty ``year`` falls through to ``date_revised`` parsing."""
    meta = {"year": "", "date_revised": "1998/12/31"}
    assert helpers._parse_year_from_metadata(meta) == 1998  # pylint: disable=protected-access


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
    with_ft, without_ft = helpers.count_papers_with_fulltext(metadata)
    assert with_ft == 4
    assert without_ft == 2


def test_count_papers_with_fulltext_ignores_non_dicts() -> None:
    """Non-dict metadata entries are skipped but still counted as 'without'."""
    metadata: dict[str, Any] = {
        "a": {"fulltext": "body"},
        "b": "not a dict",
    }
    with_ft, without_ft = helpers.count_papers_with_fulltext(metadata)
    assert with_ft == 1
    assert without_ft == 1


def test_count_papers_with_fulltext_empty() -> None:
    """An empty metadata mapping has zero of both."""
    assert helpers.count_papers_with_fulltext({}) == (0, 0)


# =============================================================================
# parse_content_result
# =============================================================================


def test_parse_content_result_json_content_key() -> None:
    """A JSON string with a ``content`` key extracts that content."""
    result = json.dumps({"content": "the body", "text": "ignored"})
    assert helpers.parse_content_result(result) == "the body"


def test_parse_content_result_json_text_key() -> None:
    """A JSON string with only ``text`` extracts the text value."""
    result = json.dumps({"text": "from text"})
    assert helpers.parse_content_result(result) == "from text"


def test_parse_content_result_non_json_string_returns_raw() -> None:
    """A plain (non-JSON) string is returned verbatim."""
    assert helpers.parse_content_result("just plain text") == "just plain text"


def test_parse_content_result_json_without_keys_returns_raw() -> None:
    """A JSON object lacking content/text falls back to the raw string."""
    result = json.dumps({"other": "x"})
    assert helpers.parse_content_result(result) == result


def test_parse_content_result_dict_content_key() -> None:
    """A dict input with a ``content`` key extracts that content."""
    assert helpers.parse_content_result({"content": "dict body"}) == "dict body"


def test_parse_content_result_dict_without_keys_stringifies() -> None:
    """A dict lacking content/text is stringified."""
    payload = {"other": "x"}
    assert helpers.parse_content_result(payload) == str(payload)


def test_parse_content_result_none_returns_none() -> None:
    """A falsy non-string, non-dict result returns None."""
    assert helpers.parse_content_result(None) is None
    assert helpers.parse_content_result(0) is None


def test_parse_content_result_other_type_stringifies() -> None:
    """A truthy non-string, non-dict result is stringified."""
    assert helpers.parse_content_result(123) == "123"


# =============================================================================
# get_paper_content_for_analysis
# =============================================================================


def test_get_content_prefers_fulltext() -> None:
    """Fulltext is preferred over abstract for analysis content."""
    meta = {"fulltext": "full", "abstract": "abs"}
    assert helpers.get_paper_content_for_analysis(meta) == "full"


def test_get_content_falls_back_to_abstract() -> None:
    """With no fulltext, the abstract is used."""
    assert helpers.get_paper_content_for_analysis({"abstract": "abs"}) == "abs"


def test_get_content_empty_returns_empty_string() -> None:
    """No content yields an empty string, never None."""
    out = helpers.get_paper_content_for_analysis({})
    assert out == ""
    assert isinstance(out, str)


def test_get_content_non_string_coerced_to_string() -> None:
    """A non-string fulltext value is coerced to a string."""
    out = helpers.get_paper_content_for_analysis({"fulltext": 12345})
    assert out == "12345"
    assert isinstance(out, str)


def test_get_content_truncates_at_max_chars() -> None:
    """Content longer than ``max_chars`` is truncated with a marker suffix."""
    long_text = "x" * 500
    out = helpers.get_paper_content_for_analysis({"fulltext": long_text},
                                                 max_chars=100)
    assert out.startswith("x" * 100)
    assert out.endswith("[... truncated for length ...]")
    assert "x" * 101 not in out
    assert isinstance(out, str)


def test_get_content_no_truncation_under_limit() -> None:
    """Content within the limit is returned untouched."""
    text = "short"
    out = helpers.get_paper_content_for_analysis({"fulltext": text},
                                                 max_chars=100)
    assert out == text


# =============================================================================
# parse_mcp_query_result
# =============================================================================


def test_parse_mcp_query_result_json_list() -> None:
    """A JSON-array string parses to the list of queries."""
    result = json.dumps(["q1", "q2"])
    assert helpers.parse_mcp_query_result(result) == ["q1", "q2"]


def test_parse_mcp_query_result_json_queries_key() -> None:
    """A JSON object with a ``queries`` key extracts that list."""
    result = json.dumps({"queries": ["a", "b"]})
    assert helpers.parse_mcp_query_result(result) == ["a", "b"]


def test_parse_mcp_query_result_json_object_without_queries() -> None:
    """A JSON object lacking ``queries`` yields an empty list."""
    assert helpers.parse_mcp_query_result(json.dumps({"x": 1})) == []


def test_parse_mcp_query_result_invalid_json_returns_empty() -> None:
    """A non-JSON string returns an empty list."""
    assert helpers.parse_mcp_query_result("not json") == []


def test_parse_mcp_query_result_list_passthrough() -> None:
    """A list input is returned unchanged."""
    assert helpers.parse_mcp_query_result(["x", "y"]) == ["x", "y"]


def test_parse_mcp_query_result_other_type_returns_empty() -> None:
    """A non-string, non-list input yields an empty list."""
    assert helpers.parse_mcp_query_result({"queries": ["a"]}) == []


# =============================================================================
# calculate_papers_per_query
# =============================================================================


def test_calculate_papers_per_query_even_split() -> None:
    """An even division gives that quotient with a remainder."""
    assert helpers.calculate_papers_per_query(10, 3) == (3, 1)


def test_calculate_papers_per_query_exact() -> None:
    """An exact division leaves no remainder."""
    assert helpers.calculate_papers_per_query(12, 4) == (3, 0)


def test_calculate_papers_per_query_clamps_to_two_minimum() -> None:
    """A sub-2 per-query result is clamped to the 2 minimum.

    The remainder is still computed from the raw division, not the clamp.
    """
    per_query, remainder = helpers.calculate_papers_per_query(3, 5)
    assert per_query == 2
    assert remainder == 3


# =============================================================================
# merge_search_results
# =============================================================================


def test_merge_search_results_combines_and_maps_sources() -> None:
    """Results from multiple sources merge with a paper -> source map."""
    source_results = [
        ("pubmed", {"p1": {"title": "Alpha"}}),
        ("arxiv", {"a1": {"title": "Beta"}}),
    ]
    merged, source_map = helpers.merge_search_results(source_results)
    assert set(merged) == {"p1", "a1"}
    assert source_map == {"p1": "pubmed", "a1": "arxiv"}


def test_merge_search_results_deduplicates_by_title() -> None:
    """A title seen earlier (case/space-insensitive) is dropped."""
    source_results = [
        ("pubmed", {"p1": {"title": "Shared Title"}}),
        ("arxiv", {"a1": {"title": "  shared title  "}}),
    ]
    merged, source_map = helpers.merge_search_results(source_results)
    assert set(merged) == {"p1"}
    assert source_map == {"p1": "pubmed"}


def test_merge_search_results_no_dedup_keeps_duplicates() -> None:
    """With ``deduplicate=False`` duplicate titles are all retained."""
    source_results = [
        ("pubmed", {"p1": {"title": "Same"}}),
        ("arxiv", {"a1": {"title": "Same"}}),
    ]
    merged, _ = helpers.merge_search_results(source_results,
                                             deduplicate=False)
    assert set(merged) == {"p1", "a1"}


# =============================================================================
# parse_pdf_discovery_result
# =============================================================================


def test_parse_pdf_discovery_json_list_first_element() -> None:
    """A JSON-array string returns its first element."""
    result = json.dumps(["http://x/p.pdf", "http://y/p.pdf"])
    assert helpers.parse_pdf_discovery_result(result) == "http://x/p.pdf"


def test_parse_pdf_discovery_json_dict_pdf_links() -> None:
    """A JSON object with ``pdf_links`` returns the first string link."""
    result = json.dumps({"pdf_links": ["http://x/a.pdf"]})
    assert helpers.parse_pdf_discovery_result(result) == "http://x/a.pdf"


def test_parse_pdf_discovery_json_dict_links_with_url() -> None:
    """A ``links`` entry that is a dict resolves via its ``url`` field."""
    result = json.dumps({"links": [{"url": "http://x/b.pdf"}]})
    assert helpers.parse_pdf_discovery_result(result) == "http://x/b.pdf"


def test_parse_pdf_discovery_bare_http_string() -> None:
    """A non-JSON string starting with http is treated as the URL."""
    assert helpers.parse_pdf_discovery_result(
        "http://x/c.pdf") == "http://x/c.pdf"


def test_parse_pdf_discovery_non_url_string_returns_none() -> None:
    """A non-JSON, non-http string yields None."""
    assert helpers.parse_pdf_discovery_result("nope") is None


def test_parse_pdf_discovery_list_input_string() -> None:
    """A list input returns its first element when it is a string."""
    assert helpers.parse_pdf_discovery_result(["http://x/d.pdf"
                                              ]) == "http://x/d.pdf"


def test_parse_pdf_discovery_list_input_dict() -> None:
    """A list input whose first element is a dict resolves via ``url``."""
    assert helpers.parse_pdf_discovery_result([{"url": "http://x/e.pdf"}
                                              ]) == "http://x/e.pdf"


def test_parse_pdf_discovery_empty_returns_none() -> None:
    """Empty / unhandled inputs return None."""
    assert helpers.parse_pdf_discovery_result([]) is None
    assert helpers.parse_pdf_discovery_result(None) is None
