"""Tests for Entrez-backed PubMed metadata parsing (pubmed_client.py).

Covers publication-type extraction, including the wiring that lets a
retracted PubMed article's ``publication_types`` reach the metadata dict --
the shared multi-shape retraction detector
(``article_support._metadata_is_retracted``) already checks for "retracted
publication" there, but PubMed metadata never carried the field for it to
find. No network I/O: Entrez calls are monkeypatched with canned data.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from Bio import Entrez
from mcp_server.pubmed_client import (
    _EntrezClient,
    _extract_abstract,
    _extract_publication_types,
)
from mcp_server.tools.lit_review import search_pubmed as tool


class _CannedEntrezHandle:
    """Minimal response handle for the offline public-tool test."""

    def __init__(self, response: Any) -> None:
        self.response = response

    def close(self) -> None:
        pass


def test_extract_publication_types_reads_the_list() -> None:
    """Every entry in an article's PublicationTypeList is returned as-is."""
    article = {
        "PublicationTypeList": ["Journal Article", "Retracted Publication"]
    }
    assert _extract_publication_types(article) == [
        "Journal Article",
        "Retracted Publication",
    ]


def test_extract_publication_types_defaults_to_empty() -> None:
    """An article with no PublicationTypeList yields an empty list."""
    assert _extract_publication_types({}) == []


def test_fetch_paper_details_surfaces_publication_types(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A retracted article's publication type reaches the metadata dict."""
    canned = {
        "PubmedArticle": [
            {
                "MedlineCitation": {
                    "Article": {
                        "ArticleTitle": "A retracted paper",
                        "Journal": {"Title": "Nature"},
                        "PublicationTypeList": [
                            "Journal Article",
                            "Retracted Publication",
                        ],
                        "AuthorList": [],
                    },
                    "DateRevised": {
                        "Year": "2020",
                        "Month": "1",
                        "Day": "1",
                    },
                },
                "PubmedData": {"ArticleIdList": []},
            }
        ]
    }

    client = _EntrezClient(tmp_path)
    monkeypatch.setattr(
        "mcp_server.pubmed_client.entrez_call", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        _EntrezClient, "entrez_read", lambda self, handle: canned
    )
    monkeypatch.setattr(
        _EntrezClient, "_fetch_pmc_fulltext_id", lambda self, *_a: None
    )

    metadata = client._fetch_paper_details("123")

    assert metadata["publication_types"] == [
        "Journal Article",
        "Retracted Publication",
    ]


def test_fetch_paper_details_reads_as_plain_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """PubMed italicizes species and gene names inside its metadata.

    A live query returns them on roughly half of all records, and the tag
    travels straight into whatever an agent quotes.
    """
    canned = {
        "PubmedArticle": [
            {
                "MedlineCitation": {
                    "Article": {
                        "ArticleTitle": (
                            "Repurposing loratadine in "
                            "<i>Klebsiella pneumoniae</i>"
                        ),
                        "Abstract": {
                            "AbstractText": [
                                "<b>Background:</b>",
                                "bla<sub>NDM-1</sub> is widespread.",
                            ]
                        },
                        "Journal": {"Title": "Nature"},
                        "AuthorList": [],
                    },
                    "DateRevised": {"Year": "2020", "Month": "1", "Day": "1"},
                },
                "PubmedData": {"ArticleIdList": []},
            }
        ]
    }

    client = _EntrezClient(tmp_path)
    monkeypatch.setattr(
        "mcp_server.pubmed_client.entrez_call", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        _EntrezClient, "entrez_read", lambda self, handle: canned
    )
    monkeypatch.setattr(
        _EntrezClient, "_fetch_pmc_fulltext_id", lambda self, *_a: None
    )

    metadata = client._fetch_paper_details("123")

    assert metadata["title"] == (
        "Repurposing loratadine in Klebsiella pneumoniae"
    )
    assert metadata["abstract"] == "Background: blaNDM-1 is widespread."


def test_fetch_paper_details_keeps_article_without_author_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An optional AuthorList does not discard otherwise valid metadata."""
    canned = {
        "PubmedArticle": [
            {
                "MedlineCitation": {
                    "Article": {
                        "ArticleTitle": "A paper without an author list",
                        "Abstract": {"AbstractText": ["Useful abstract."]},
                        "Journal": {"Title": "Nature"},
                    },
                    "DateRevised": {"Year": "2020", "Month": "1", "Day": "1"},
                },
                "PubmedData": {"ArticleIdList": []},
            }
        ]
    }

    client = _EntrezClient(tmp_path)
    monkeypatch.setattr(
        "mcp_server.pubmed_client.entrez_call", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        _EntrezClient, "entrez_read", lambda self, handle: canned
    )
    monkeypatch.setattr(
        _EntrezClient, "_fetch_pmc_fulltext_id", lambda self, *_a: None
    )

    metadata = client._fetch_paper_details("123")

    assert metadata["title"] == "A paper without an author list"
    assert metadata["abstract"] == "Useful abstract."
    assert metadata["publication"] == "Nature"
    assert metadata["authors"] == []


def test_pubmed_tool_returns_article_without_author_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The maintained tool keeps valid results when Entrez omits authors."""
    paper = {
        "PubmedArticle": [
            {
                "MedlineCitation": {
                    "Article": {
                        "ArticleTitle": "A paper without an author list",
                        "Abstract": {"AbstractText": ["Useful abstract."]},
                        "Journal": {"Title": "Nature"},
                    },
                    "DateRevised": {"Year": "2020", "Month": "1", "Day": "1"},
                },
                "PubmedData": {"ArticleIdList": []},
            }
        ]
    }

    monkeypatch.delenv("COSCIENTIST_PUBMED_PILOT_TRACE", raising=False)
    monkeypatch.setattr(tool, "_pubmed_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "mcp_server.pubmed_client.entrez_call",
        lambda request, **kwargs: request(**kwargs),
    )
    monkeypatch.setattr(
        Entrez,
        "esearch",
        lambda **_kwargs: _CannedEntrezHandle({"IdList": ["123"]}),
    )
    monkeypatch.setattr(
        Entrez, "efetch", lambda **_kwargs: _CannedEntrezHandle(paper)
    )
    monkeypatch.setattr(
        Entrez,
        "elink",
        lambda **_kwargs: _CannedEntrezHandle([{"LinkSetDb": []}]),
    )
    monkeypatch.setattr(Entrez, "read", lambda handle: handle.response)

    results = asyncio.run(
        tool.pubmed_search_with_fulltext(
            query="authorless",
            slug="authorless",
            max_papers=1,
            run_id="offline-test",
        )
    )

    assert results.keys() == {"123"}
    assert results["123"]["title"] == "A paper without an author list"
    assert results["123"]["abstract"] == "Useful abstract."
    assert results["123"]["authors"] == []
    metadata_path = (
        tmp_path
        / "pubmed"
        / "authorless"
        / "runs"
        / "offline-test"
        / "123.metadata.json"
    )
    assert metadata_path.is_symlink()
    assert (
        json.loads(metadata_path.read_text(encoding="utf-8")) == results["123"]
    )


def test_extract_abstract_keeps_the_missing_sentinel() -> None:
    """An article with no abstract still reports "<not found>".

    The sentinel is angle-bracketed but is not markup, which is why only
    real formatting tags are stripped.
    """
    assert _extract_abstract({}) == "<not found>"
