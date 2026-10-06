import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn, cast

import mcp_server.entrez as entrez_rate_limit
import pytest
from Bio import Entrez
from mcp_server.tools.lit_review.search_pubmed import (
    pubmed_search_with_fulltext,
)


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


def search(
    query: str,
    run_id: str,
    *,
    slug: str | None = None,
    max_papers: int = 1,
    **kwargs: Any,
) -> dict[str, Any]:
    return asyncio.run(
        pubmed_search_with_fulltext(
            query=query,
            slug=slug or run_id,
            max_papers=max_papers,
            run_id=run_id,
            **kwargs,
        )
    )


def trace_path(cache_root: Path, slug: str, run_id: str) -> Path:
    run_dir = cache_root / "pubmed" / slug / "runs" / run_id
    return run_dir / ".search-trace.json"


def read_trace(cache_root: Path, slug: str, run_id: str) -> dict[str, Any]:
    text = trace_path(cache_root, slug, run_id).read_text(encoding="utf-8")
    return cast(dict[str, Any], json.loads(text))


def install_entrez(monkeypatch: pytest.MonkeyPatch, **requests: Callable[..., Any]) -> None:
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
                        "Abstract": {"AbstractText": ["A real-shaped abstract."]},
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


def seed_shared_pool(cache_root: Path, slug: str, paper_id: str) -> Path:
    shared_dir = cache_root / "pubmed" / slug / "shared"
    shared_dir.mkdir(parents=True)
    metadata = {
        "date_revised": "2023/1/1",
        "title": "Cached paper",
        "abstract": "Cached abstract.",
        "authors": [],
        "publication": "Example Journal",
        "pmc_full_text_id": f"PMC{paper_id}",
    }
    (shared_dir / f"{paper_id}.metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (shared_dir / f"PMC{paper_id}.fulltext.html").write_text(
        "<html><body>Cached full text.</body></html>", encoding="utf-8"
    )
    return shared_dir


def esearch_ids(*ids: str) -> Callable[..., CannedEntrezHandle]:
    return lambda **_kwargs: CannedEntrezHandle({"IdList": list(ids)})


def efetch_article(**kwargs: Any) -> CannedEntrezHandle:
    return CannedEntrezHandle(pubmed_article(str(kwargs["id"])))


def elink_without_pmc(**_kwargs: Any) -> CannedEntrezHandle:
    return CannedEntrezHandle([{"LinkSetDb": []}])


def raising(error: Exception) -> Callable[..., NoReturn]:
    def request(**_kwargs: Any) -> NoReturn:
        raise error

    return request


def install_fake_entrez(monkeypatch: pytest.MonkeyPatch, ids: list[str]) -> list[dict[str, Any]]:
    esearch_calls: list[dict[str, Any]] = []

    def esearch(**kwargs: Any) -> CannedEntrezHandle:
        esearch_calls.append(kwargs)
        return esearch_ids(*ids)()

    install_entrez(
        monkeypatch,
        esearch=esearch,
        efetch=efetch_article,
        elink=elink_without_pmc,
    )
    return esearch_calls
