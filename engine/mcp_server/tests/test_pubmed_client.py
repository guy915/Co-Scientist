"""Tests for Entrez-backed PubMed metadata parsing (pubmed_client.py).

Covers publication-type extraction, including the wiring that lets a
retracted PubMed article's ``publication_types`` reach the metadata dict --
the shared multi-shape retraction detector
(``article_support._metadata_is_retracted``) already checks for "retracted
publication" there, but PubMed metadata never carried the field for it to
find. No network I/O: Entrez calls are monkeypatched with canned data.
"""

from pathlib import Path

import pytest
from mcp_server.pubmed_client import (
    _EntrezClient,
    _extract_abstract,
    _extract_publication_types,
)


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


def test_extract_abstract_keeps_the_missing_sentinel() -> None:
    """An article with no abstract still reports "<not found>".

    The sentinel is angle-bracketed but is not markup, which is why only
    real formatting tags are stripped.
    """
    assert _extract_abstract({}) == "<not found>"
