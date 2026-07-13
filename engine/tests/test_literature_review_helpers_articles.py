"""Tests for the article-building literature review helpers.

Covers ``extract_source_name``, ``normalize_search_response``,
``build_article_from_metadata``, ``_build_article_url``, and
``parse_year_from_metadata`` in ``co_scientist.nodes.literature_review.
helpers``. The result/content parsing helpers are covered in
``test_literature_review_helpers_parsing``.

The functions under test do no I/O: they map response/metadata dicts into
``Article`` objects, parse years, and normalize raw search-tool responses. These
tests lock in that deterministic behavior without any LLM, MCP, or network
mocking.
"""

from typing import Any

from co_scientist.config.schema import ResponseFormat, ToolConfig
from co_scientist.models import Article
from co_scientist.nodes.literature_review import helpers


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
    tc = _tool_config(ResponseFormat(field_mapping={"source": "'pubmed'"}))
    assert helpers.extract_source_name(tc) == "pubmed"


def test_extract_source_name_unquoted_mapping_falls_back_to_source_type() -> (
    None
):
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
    tc = _tool_config(ResponseFormat(field_mapping={"source_id": "pmid"}))
    data = [
        {"pmid": "111", "title": "A"},
        {"pmid": "222", "title": "B"},
    ]
    result = helpers.normalize_search_response(data, tc)
    assert set(result) == {"111", "222"}
    assert result["111"]["title"] == "A"


def test_normalize_list_at_prefixed_source_id_uses_arxiv_id() -> None:
    """An ``@``-prefixed source_id mapping falls back to the arxiv_id field."""
    tc = _tool_config(ResponseFormat(field_mapping={"source_id": "@id"}))
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
        "doi": "10.1000/example",
        "is_retracted": True,
        "correction_status": "retracted",
    }
    article = helpers.build_article_from_metadata(
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
    article = helpers.build_article_from_metadata(
        "PMID43",
        {"publication_types": ["Journal Article", "Retracted Publication"]},
    )

    assert article.is_retracted is True
    assert article.correction_status == "retracted"


def test_build_article_defaults_for_missing_fields() -> None:
    """Missing metadata yields safe defaults (unknown title, no authors)."""
    article = helpers.build_article_from_metadata(
        "x1", {}, source_name="arxiv", used_in_analysis=False
    )
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
        "x1", {"venue": "JMLR"}, source_name="arxiv"
    )
    assert article.venue == "JMLR"


# =============================================================================
# _build_article_url
# =============================================================================


def test_build_url_prefers_metadata_url() -> None:
    """An explicit metadata URL takes precedence over construction."""
    url = helpers._build_article_url(
        "999", {"url": "https://custom.example/x"}, "pubmed"
    )
    assert url == "https://custom.example/x"


def test_build_url_pubmed_construction() -> None:
    """A pubmed source with no URL builds the canonical pubmed URL."""
    url = helpers._build_article_url("12345", {}, "pubmed")
    assert url == "https://pubmed.ncbi.nlm.nih.gov/12345/"


def test_build_url_doi_construction() -> None:
    """A DOI-style id on a non-pubmed source builds a doi.org URL."""
    url = helpers._build_article_url("10.1000/xyz123", {}, "crossref")
    assert url == "https://doi.org/10.1000/xyz123"


def test_build_url_fallback_returns_paper_id() -> None:
    """A non-pubmed, non-DOI id with no URL falls back to the raw id."""
    url = helpers._build_article_url("arxiv:2401.0001", {}, "arxiv")
    assert url == "arxiv:2401.0001"


# =============================================================================
# parse_year_from_metadata
# =============================================================================


def test_parse_year_from_year_field() -> None:
    """A numeric-string ``year`` field parses to an int."""
    assert helpers.parse_year_from_metadata({"year": "2019"}) == 2019


def test_parse_year_from_year_field_int() -> None:
    """An int ``year`` field is returned as-is."""
    assert helpers.parse_year_from_metadata({"year": 2007}) == 2007


def test_parse_year_from_date_revised() -> None:
    """A ``date_revised`` like ``2021/03/01`` yields the leading year."""
    assert (
        helpers.parse_year_from_metadata({"date_revised": "2021/03/01"}) == 2021
    )


def test_parse_year_garbage_returns_none() -> None:
    """A non-numeric year with no usable fallback returns None."""
    assert helpers.parse_year_from_metadata({"year": "not-a-year"}) is None


def test_parse_year_missing_returns_none() -> None:
    """Empty metadata yields no year."""
    assert helpers.parse_year_from_metadata({}) is None


def test_parse_year_falls_back_to_date_revised_when_year_empty() -> None:
    """An empty ``year`` falls through to ``date_revised`` parsing."""
    meta = {"year": "", "date_revised": "1998/12/31"}
    assert helpers.parse_year_from_metadata(meta) == 1998
