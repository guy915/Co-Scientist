import asyncio
from pathlib import Path
from typing import Any, cast

import mcp_server.entrez as entrez_rate_limit
import pytest
from Bio import Entrez
from mcp_server.tests._entrez import (
    CannedEntrezHandle,
    configure_trace,
    install_entrez,
    read_trace,
)
from mcp_server.tests._entrez import pubmed_article as _pubmed_article
from mcp_server.tools.lit_review import search_pubmed as tool

_PUBLIC_METADATA_FIELDS = {
    "date_revised",
    "title",
    "abstract",
    "doi",
    "authors",
    "publication",
    "pmc_full_text_id",
    "publication_types",
}


class _Handle(CannedEntrezHandle):
    def __init__(self, payload: Any = None, body: bytes = b"") -> None:
        super().__init__(payload)
        self.body = body

    def read(self) -> bytes:
        return self.body

    def __contains__(self, value: str) -> bool:
        return value.encode() in self.body


def _article(paper_id: str) -> dict[str, Any]:
    article = _pubmed_article(paper_id)["PubmedArticle"][0]
    article["MedlineCitation"]["PMID"] = paper_id
    return cast(dict[str, Any], article)


def _efetch_reversed(**kwargs: Any) -> _Handle:
    records = [_article(paper_id) for paper_id in kwargs["id"]]
    return _Handle({"PubmedArticle": list(reversed(records))})


def _elink_groups(links: dict[str, str]) -> Any:
    def elink(**kwargs: Any) -> _Handle:
        groups = [
            {
                "IdList": [paper_id],
                "LinkSetDb": (
                    [
                        {
                            "LinkName": "pubmed_pmc",
                            "Link": [{"Id": links[paper_id]}],
                        }
                    ]
                    if paper_id in links
                    else []
                ),
            }
            for paper_id in kwargs["id"]
        ]
        return _Handle(list(reversed(groups)))

    return elink


def _install_batch_entrez(
    monkeypatch: pytest.MonkeyPatch,
    efetch: Any,
    elink: Any,
) -> None:
    install_entrez(monkeypatch, efetch=efetch, elink=elink)
    monkeypatch.setattr(Entrez, "max_tries", 1)
    monkeypatch.setattr(Entrez, "sleep_between_tries", 0)


@pytest.fixture
def _restore_entrez_retry_policy() -> Any:
    max_tries = Entrez.max_tries
    sleep_between_tries = Entrez.sleep_between_tries
    yield
    Entrez.max_tries = max_tries
    Entrez.sleep_between_tries = sleep_between_tries


def _matched_selection_esearch(
    cache_root: Path, ids: list[str], **_kwargs: Any
) -> _Handle:
    run_dir = (
        cache_root
        / "pubmed"
        / "metadata-only-run"
        / "runs"
        / "metadata-only-run"
    )
    if run_dir.exists():
        (run_dir / "1020.fulltext.html").write_text(
            "cached PMC text", encoding="utf-8"
        )
    return _Handle({"IdList": ids})


@pytest.mark.usefixtures("_restore_entrez_retry_policy")
class TestPubmedMetadataBatch:
    def test_public_search_keeps_metadata_on_elink_error_and_recovers_next_run(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cache_root = tmp_path / "cache"
        configure_trace(
            monkeypatch, cache_root, "batch-offline-build", free_models=True
        )
        monkeypatch.setenv("COSCIENTIST_PUBMED_METADATA_BATCH", "1")
        monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)

        paper_ids = ["701", "702", "703"]
        pubmed_requests: list[list[str]] = []
        elink_requests: list[dict[str, Any]] = []
        fulltext_requests: list[str] = []
        fail_elink = True
        link = _elink_groups({"701": "1701"})

        def efetch(**kwargs: Any) -> _Handle:
            if kwargs["db"] == "pubmed":
                pubmed_requests.append(kwargs["id"])
                return _efetch_reversed(**kwargs)
            fulltext_requests.append(kwargs["id"])
            return _Handle(
                body=(
                    b"<article><body><sec><title>Introduction</title>"
                    b"<p>Recovered PMC full text.</p></sec></body></article>"
                )
            )

        def elink(**kwargs: Any) -> _Handle:
            elink_requests.append(kwargs.copy())
            if fail_elink:
                raise RuntimeError("offline")
            return cast(_Handle, link(**kwargs))

        monkeypatch.setattr(
            Entrez, "esearch", lambda **_kwargs: _Handle({"IdList": paper_ids})
        )
        _install_batch_entrez(monkeypatch, efetch, elink)

        def search(run_id: str) -> dict[str, Any]:
            return asyncio.run(
                tool.pubmed_search_with_fulltext(
                    query="batch ELink recovery",
                    slug="batch-elink-recovery",
                    max_papers=1,
                    run_id=run_id,
                )
            )

        first_results = search("elink-failure-run")
        shared_dir = cache_root / "pubmed" / "batch-elink-recovery" / "shared"
        first_trace = read_trace(
            cache_root, "batch-elink-recovery", "elink-failure-run"
        )

        assert list(first_results) == ["701"]
        assert first_results["701"]["pmc_full_text_id"] is None
        assert not any(shared_dir.glob("*.metadata.json"))
        assert first_trace["metadata_origins"] == dict.fromkeys(
            paper_ids, "entrez_fetch"
        )
        assert [
            (error["pmid"], error["stage"])
            for error in first_trace["fetch_errors"]
        ] == [(paper_id, "elink") for paper_id in paper_ids]

        fail_elink = False
        second_results = search("elink-recovered-run")

        assert pubmed_requests == [paper_ids, paper_ids]
        assert [request["id"] for request in elink_requests] == [paper_ids] * 2
        assert list(second_results) == ["701"]
        assert "Recovered PMC full text." in second_results["701"]["fulltext"]
        assert fulltext_requests == ["1701"]
        assert all(
            (shared_dir / f"{paper_id}.metadata.json").exists()
            for paper_id in paper_ids
        )
