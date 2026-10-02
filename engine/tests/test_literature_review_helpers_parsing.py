"""Tests for the result/content parsing literature review helpers.

Covers ``count_papers_with_fulltext``, ``parse_content_result``,
``get_paper_content_for_analysis``, ``parse_mcp_query_result``,
``merge_search_results``, and ``parse_pdf_discovery_result`` in
the defining evidence modules. The article-building helpers are covered in
``test_literature_review_helpers_articles``.

The functions under test do no I/O: they parse content payloads, count fulltext
availability, merge multi-source results, and pull PDF links out of raw
responses. These tests lock in that deterministic behavior without any LLM,
MCP, or network mocking.
"""

import json
from typing import Any

from co_scientist.evidence import (
    article_support,
    retrieval_support,
    search_support,
)

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
