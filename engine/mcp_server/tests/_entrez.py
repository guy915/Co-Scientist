from collections.abc import Callable
from pathlib import Path
from typing import Any

import mcp_server.entrez as entrez_rate_limit
import pytest
from Bio import Entrez


class CannedEntrezHandle:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def close(self) -> None:
        pass


def configure_trace(
    monkeypatch: pytest.MonkeyPatch,
    cache_root: Path,
    build_id: str,
    *,
    free_models: bool = False,
    study_id: str | None = None,
) -> None:
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_TRACE", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_BUILD_ID", build_id)
    monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(cache_root))
    if free_models:
        monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    if study_id is not None:
        monkeypatch.setenv("COSCIENTIST_PUBMED_STUDY4_RECOVERY", "1")
        monkeypatch.setenv("COSCIENTIST_PUBMED_STUDY_ID", study_id)


def install_entrez(
    monkeypatch: pytest.MonkeyPatch, **requests: Callable[..., Any]
) -> None:
    # Keep Entrez callback names for trace attribution while bypassing waits.
    monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)
    for name, request in requests.items():
        monkeypatch.setattr(Entrez, name, request)
    monkeypatch.setattr(Entrez, "read", lambda handle: handle.payload)


def pubmed_article(paper_id: str) -> dict[str, Any]:
    return {
        "PubmedArticle": [
            {
                "MedlineCitation": {
                    "Article": {
                        "ArticleTitle": f"Paper {paper_id}",
                        "Abstract": {
                            "AbstractText": ["A real-shaped abstract."]
                        },
                        "Journal": {"Title": "Example Journal"},
                        "AuthorList": [{"LastName": "Smith", "ForeName": "A"}],
                        "PublicationTypeList": ["Journal Article"],
                    },
                    "DateRevised": {"Year": "2024", "Month": "1", "Day": "1"},
                },
                "PubmedData": {"ArticleIdList": []},
            }
        ]
    }


def install_fake_entrez(
    monkeypatch: pytest.MonkeyPatch, ids: list[str]
) -> list[dict[str, Any]]:
    esearch_calls: list[dict[str, Any]] = []

    def fake_esearch(**kwargs: Any) -> CannedEntrezHandle:
        esearch_calls.append(kwargs)
        return CannedEntrezHandle({"IdList": ids})

    def fake_efetch(**kwargs: Any) -> CannedEntrezHandle:
        return CannedEntrezHandle(pubmed_article(str(kwargs["id"])))

    def fake_elink(**_kwargs: Any) -> CannedEntrezHandle:
        return CannedEntrezHandle([{"LinkSetDb": []}])

    install_entrez(
        monkeypatch, esearch=fake_esearch, efetch=fake_efetch, elink=fake_elink
    )
    return esearch_calls
