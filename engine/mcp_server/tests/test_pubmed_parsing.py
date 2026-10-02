"""Tests for the Entrez record parser behind ``search_pubmed``.

The other PubMed tool (``pubmed_search_with_fulltext``) parses through
``pubmed_client.py`` and is covered in ``test_pubmed_client.py``; the two
paths read the same Entrez fields and have to agree about what an agent
sees, which is what these pin here. No network I/O: the Entrez call is
monkeypatched with canned data.
"""

from typing import Any

import pytest
from mcp_server.tools.lit_review import pubmed_parsing


def _canned(article: dict[str, Any]) -> dict[str, Any]:
    """Wraps one Article mapping in the efetch response shape."""
    return {
        "PubmedArticle": [
            {
                "MedlineCitation": {"Article": article},
                "PubmedData": {"ArticleIdList": []},
            }
        ]
    }


@pytest.fixture
def entrez(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Stubs the Entrez round-trip with whatever the test hands back."""

    def _install(article: dict[str, Any]) -> None:
        monkeypatch.setattr(
            "mcp_server.tools.lit_review.pubmed_parsing.entrez_call",
            lambda *_a, **_k: None,
        )
        monkeypatch.setattr(
            "mcp_server.tools.lit_review.pubmed_parsing.read_entrez",
            lambda _handle: _canned(article),
        )

    return _install


def test_an_article_reads_as_plain_text(entrez: Any) -> None:
    """PubMed italicizes species names and subscripts gene symbols."""
    entrez(
        {
            "ArticleTitle": "Emergence of <i>mcr-1.1</i> in bla<sub>NDM</sub>",
            "Abstract": {
                "AbstractText": [
                    "<b>Background:</b>",
                    "Colistin is a last resort.",
                ]
            },
            "Journal": {"Title": "Nature", "JournalIssue": {}},
            "AuthorList": [],
        }
    )

    article = pubmed_parsing._fetch_pubmed_article("123")

    assert article.title == "Emergence of mcr-1.1 in blaNDM"
    assert article.abstract == "Background: Colistin is a last resort."


def test_an_article_without_an_abstract_reports_none(entrez: Any) -> None:
    """Absent stays absent: cleaning must not turn None into "".

    Downstream ranking treats an empty abstract as evidence it can read
    and a missing one as a paper to fetch, so the two are not the same.
    """
    entrez(
        {
            "ArticleTitle": "A paper with no abstract",
            "Journal": {"Title": "Nature", "JournalIssue": {}},
            "AuthorList": [],
        }
    )

    assert pubmed_parsing._fetch_pubmed_article("123").abstract is None
