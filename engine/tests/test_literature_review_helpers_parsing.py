"""Tests for the result/content parsing literature review helpers.

Covers ``count_papers_with_fulltext``, ``parse_content_result``,
``get_paper_content_for_analysis``, ``parse_mcp_query_result``,
``merge_search_results``, and ``parse_pdf_discovery_result`` in
``literature_review.helpers``. The article-building helpers are covered in
``test_literature_review_helpers_articles``.

The functions under test do no I/O: they parse content payloads, count fulltext
availability, merge multi-source results, and pull PDF links out of raw
responses. These tests lock in that deterministic behavior without any LLM,
MCP, or network mocking.
"""

import json
from typing import Any

from co_scientist.agents.generation.literature_review import helpers

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


def test_abstract_only_paper_is_selected_for_analysis() -> None:
    """Abstract-index sources contribute bounded evidence without a PDF."""
    papers = {
        "openalex-1": {"title": "A", "abstract": "Explicit abstract"},
        "metadata-only": {"title": "B"},
    }

    selected = helpers.get_papers_with_content(papers)

    assert list(selected) == ["openalex-1"]


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
    out = helpers.get_paper_content_for_analysis(
        {"fulltext": long_text}, max_chars=100
    )
    assert out.startswith("x" * 100)
    assert out.endswith("[... truncated for length ...]")
    assert "x" * 101 not in out
    assert isinstance(out, str)


def test_get_content_no_truncation_under_limit() -> None:
    """Content within the limit is returned untouched."""
    text = "short"
    out = helpers.get_paper_content_for_analysis(
        {"fulltext": text}, max_chars=100
    )
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
    merged, _ = helpers.merge_search_results(source_results, deduplicate=False)
    assert set(merged) == {"p1", "a1"}


def test_merge_search_results_ranks_quality_and_flags_retractions() -> None:
    """Merged retrieval is best-first and exposes correction status."""
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

    merged, _ = helpers.merge_search_results(source_results)

    assert list(merged) == ["strong", "weak", "retracted"]
    assert (
        merged["strong"]["retrieval_score"] > merged["weak"]["retrieval_score"]
    )
    assert merged["retracted"]["correction_status"] == "retracted"


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
    assert (
        helpers.parse_pdf_discovery_result("http://x/c.pdf") == "http://x/c.pdf"
    )


def test_parse_pdf_discovery_non_url_string_returns_none() -> None:
    """A non-JSON, non-http string yields None."""
    assert helpers.parse_pdf_discovery_result("nope") is None


def test_parse_pdf_discovery_list_input_string() -> None:
    """A list input returns its first element when it is a string."""
    assert (
        helpers.parse_pdf_discovery_result(["http://x/d.pdf"])
        == "http://x/d.pdf"
    )


def test_parse_pdf_discovery_list_input_dict() -> None:
    """A list input whose first element is a dict resolves via ``url``."""
    assert (
        helpers.parse_pdf_discovery_result([{"url": "http://x/e.pdf"}])
        == "http://x/e.pdf"
    )


def test_parse_pdf_discovery_empty_returns_none() -> None:
    """Empty / unhandled inputs return None."""
    assert helpers.parse_pdf_discovery_result([]) is None
    assert helpers.parse_pdf_discovery_result(None) is None
