from pathlib import Path
from typing import Any

import pytest
from Bio.Entrez.Parser import StringElement
from mcp_server.pubmed_client import _EntrezClient
from mcp_server.tests._entrez import CannedEntrezHandle, install_entrez
from mcp_server.tools.lit_review import search_pubmed


@pytest.mark.parametrize("abstract", [None, ["<b>Methods:</b>", "Two parts."]])
@pytest.mark.parametrize("doi", [None, "10.1234/paper"])
def test_both_pubmed_entrypoints_share_optional_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, abstract: list[str] | None, doi: str | None
) -> None:
    article: dict[str, Any] = {
        "ArticleTitle": "<i>Paper</i>",
        "AuthorList": [{"ForeName": "Ada", "LastName": "Lovelace"}, {"CollectiveName": "Team"}],
        "Journal": {"Title": "Journal", "JournalIssue": {"PubDate": {"Year": "2024"}}},
        "PublicationTypeList": ["Journal Article"],
    }
    if abstract is not None:
        article["Abstract"] = {"AbstractText": abstract}
    raw = {
        "MedlineCitation": {
            "Article": article,
            "DateRevised": {"Year": "2025", "Month": "2", "Day": "1"},
        },
        "PubmedData": {
            "ArticleIdList": [StringElement(doi, "ArticleId", {"IdType": "doi"}, "ArticleId")]
            if doi
            else [],
        },
    }
    install_entrez(
        monkeypatch,
        efetch=lambda **_kwargs: CannedEntrezHandle({"PubmedArticle": [raw]}),
        elink=lambda **_kwargs: CannedEntrezHandle([{"LinkSetDb": []}]),
    )
    fulltext = _EntrezClient(tmp_path)._fetch_paper_details("123")
    metadata = search_pubmed._fetch_pubmed_article("123")
    expected_abstract = "Methods: Two parts." if abstract else None
    assert (fulltext["title"], metadata.title) == ("Paper", "Paper")
    assert (fulltext["abstract"], metadata.abstract) == (expected_abstract, expected_abstract)
    assert fulltext["authors"] == metadata.authors == ["Ada Lovelace"]
    assert fulltext["publication"] == metadata.venue == "Journal"
    assert fulltext["doi"] == doi
    assert metadata.url == (
        f"https://doi.org/{doi}" if doi else "https://pubmed.ncbi.nlm.nih.gov/123/"
    )
    assert metadata.year == 2024
    assert fulltext["date_revised"] == "2025/2/1"
    assert fulltext["publication_types"] == ["Journal Article"]
