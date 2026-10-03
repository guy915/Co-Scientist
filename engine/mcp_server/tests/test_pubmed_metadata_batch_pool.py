"""Failure isolation, bounded batching, and cache behavior tests."""

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from Bio import Entrez
from mcp_server import entrez_rate_limit
from mcp_server import pubmed_metadata_batch as batch
from mcp_server.literature_review import PubmedSource
from mcp_server.pubmed_client import _EntrezClient
from mcp_server.pubmed_storage import metadata_no_link_sidecar
from mcp_server.tools.lit_review import search_pubmed as tool
from test_pubmed_metadata_batch import (  # type: ignore[import-not-found]
    _article,
    _Handle,
    _install_batch_entrez,
)


def test_batching_deduplicates_orders_valid_pmids_and_chunks_at_nine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    efetch_groups: list[list[str]] = []
    elink_groups: list[list[str]] = []

    def efetch(**kwargs: Any) -> _Handle:
        paper_ids = kwargs["id"]
        efetch_groups.append(paper_ids)
        return _Handle(
            {
                "PubmedArticle": [
                    _article(paper_id) for paper_id in reversed(paper_ids)
                ]
            }
        )

    def elink(**kwargs: Any) -> _Handle:
        paper_ids = kwargs["id"]
        elink_groups.append(paper_ids)
        return _Handle(
            [{"IdList": [paper_id]} for paper_id in reversed(paper_ids)]
        )

    _install_batch_entrez(monkeypatch, efetch, elink)
    paper_ids = [str(value) for value in range(100, 110)]
    shared_dir = tmp_path / "slug-a" / "shared"
    shared_dir.mkdir(parents=True)
    trace: dict[str, Any] = {
        "selected": {"ids": paper_ids[:9], "count": len(paper_ids)},
        "metadata_origins": {},
        "incomplete_fetch_count": 0,
        "fetch_errors": [],
        "entrez_calls": {"esearch": 0, "efetch": 0, "elink": 0},
    }
    client = _EntrezClient(tmp_path)
    request_ids = [
        paper_ids[0],
        "",
        "١٠٣",
        "101,102",
        *paper_ids[1:],
        paper_ids[0],
    ]

    with entrez_rate_limit.pilot_trace_context(trace):
        results = asyncio.run(
            batch.gather_metadata(
                client,
                request_ids,
                shared_dir,
                None,
                asyncio.Semaphore(1),
            )
        )

    assert list(results) == paper_ids
    assert efetch_groups == [paper_ids[:9], paper_ids[9:]]
    assert elink_groups == [paper_ids[:9], paper_ids[9:]]
    assert trace["entrez_calls"]["efetch"] == 2
    assert trace["entrez_calls"]["elink"] == 2
    assert trace["incomplete_fetch_count"] == 3
    assert trace["metadata_batching"]["sampled_pmids"] == paper_ids[:9]
    assert len(trace["metadata_batching"]["batches"]) == 1
    assert all(
        (shared_dir / f"{paper_id}.metadata.json").exists()
        for paper_id in paper_ids
    )


def test_empty_input_makes_no_metadata_or_link_requests(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail(**_kwargs: Any) -> _Handle:
        pytest.fail("empty input must not call Entrez")

    _install_batch_entrez(monkeypatch, fail, fail)
    results = asyncio.run(
        batch.gather_metadata(
            _EntrezClient(tmp_path),
            [],
            tmp_path / "empty" / "shared",
            None,
            asyncio.Semaphore(1),
        )
    )

    assert results == {}
    assert not (tmp_path / "empty").exists()


def test_metadata_cache_is_isolated_by_slug_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    efetch_ids: list[list[str]] = []
    elink_ids: list[list[str]] = []

    def efetch(**kwargs: Any) -> _Handle:
        efetch_ids.append(kwargs["id"])
        return _Handle({"PubmedArticle": [_article("101")]})

    def elink(**kwargs: Any) -> _Handle:
        elink_ids.append(kwargs["id"])
        return _Handle([{"IdList": ["101"]}])

    _install_batch_entrez(monkeypatch, efetch, elink)
    client = _EntrezClient(tmp_path)
    for slug in ("slug-a", "slug-b"):
        shared_dir = tmp_path / slug / "shared"
        shared_dir.mkdir(parents=True)
        results = asyncio.run(
            batch.gather_metadata(
                client,
                ["101"],
                shared_dir,
                None,
                asyncio.Semaphore(1),
            )
        )
        assert "pmc_full_text_id" in results["101"]

    assert efetch_ids == [["101"], ["101"]]
    assert elink_ids == [["101"], ["101"]]
    assert (tmp_path / "slug-a" / "shared" / "101.metadata.json").exists()
    assert (tmp_path / "slug-b" / "shared" / "101.metadata.json").exists()


def test_legacy_fetch_write_invalidates_no_link_proof_even_when_bytes_match(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    metadata = {
        "title": "Cached title",
        "abstract": "Cached abstract",
        "pmc_full_text_id": None,
    }
    shared_dir = tmp_path / "shared"
    shared_dir.mkdir()
    metadata_file = shared_dir / "101.metadata.json"
    serialized = json.dumps(metadata)
    metadata_file.write_text(serialized, encoding="utf-8")
    sidecar = metadata_no_link_sidecar(metadata_file)
    sidecar.write_text(
        hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        encoding="ascii",
    )
    # A missing cache entry must invalidate any orphaned no-link proof when
    # legacy retrieval writes the same metadata bytes again.
    metadata_file.unlink()
    source = PubmedSource(tmp_path)
    monkeypatch.setattr(
        source, "_fetch_paper_details", lambda _paper_id: metadata
    )

    result = asyncio.run(
        source._fetch_one_paper_metadata(
            "101", shared_dir, None, asyncio.Semaphore(1)
        )
    )

    assert result == ("101", metadata)
    assert metadata_file.read_text(encoding="utf-8") == serialized
    assert not sidecar.exists()


def test_public_search_returns_metadata_on_elink_error_and_recovers_next_run(  # noqa: C901
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_root = tmp_path / "cache"
    for key, value in {
        "COSCIENTIST_REQUIRE_FREE_MODELS": "1",
        "COSCIENTIST_PUBMED_METADATA_BATCH": "1",
        "COSCIENTIST_PUBMED_PILOT_TRACE": "1",
        "COSCIENTIST_PUBMED_PILOT_BUILD_ID": "batch-offline-build",
        "COSCIENTIST_LIT_REVIEW_DIR": str(cache_root),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)

    paper_ids = ["701", "702", "703"]
    pubmed_requests: list[list[str]] = []
    elink_requests: list[dict[str, Any]] = []
    fulltext_requests: list[str] = []
    fail_elink = True

    def esearch(**_kwargs: Any) -> _Handle:
        return _Handle({"IdList": paper_ids})

    def efetch(**kwargs: Any) -> _Handle:
        if kwargs["db"] == "pubmed":
            pubmed_requests.append(kwargs["id"])
            return _Handle(
                {
                    "PubmedArticle": [
                        _article(paper_id)
                        for paper_id in reversed(kwargs["id"])
                    ]
                }
            )
        fulltext_requests.append(kwargs["id"])
        return _Handle(
            body=(
                b"<article><body><sec><title>Introduction</title>"
                b"<p>Recovered PMC full text.</p></sec></body></article>"
            )
        )

    def elink(**kwargs: Any) -> _Handle:
        nonlocal fail_elink
        elink_requests.append(kwargs.copy())
        if fail_elink:
            raise RuntimeError("offline")
        return _Handle(
            [
                {
                    "IdList": [paper_id],
                    "LinkSetDb": (
                        [
                            {
                                "LinkName": "pubmed_pmc",
                                "Link": [{"Id": "1701"}],
                            }
                        ]
                        if paper_id == "701"
                        else []
                    ),
                }
                for paper_id in reversed(kwargs["id"])
            ]
        )

    monkeypatch.setattr(Entrez, "esearch", esearch)
    _install_batch_entrez(monkeypatch, efetch, elink)

    first_results = asyncio.run(
        tool.pubmed_search_with_fulltext(
            query="batch ELink recovery",
            slug="batch-elink-recovery",
            max_papers=1,
            run_id="elink-failure-run",
        )
    )
    shared_dir = cache_root / "pubmed" / "batch-elink-recovery" / "shared"
    first_trace = json.loads(
        (
            cache_root
            / "pubmed"
            / "batch-elink-recovery"
            / "runs"
            / "elink-failure-run"
            / ".search-trace.json"
        ).read_text(encoding="utf-8")
    )

    assert list(first_results) == ["701"]
    assert first_results["701"]["title"]
    assert first_results["701"]["pmc_full_text_id"] is None
    assert not any(shared_dir.glob("*.metadata.json"))
    assert first_trace["metadata_origins"] == dict.fromkeys(
        paper_ids, "entrez_fetch"
    )
    assert [error["pmid"] for error in first_trace["fetch_errors"]] == paper_ids
    assert all(
        error["stage"] == "elink" for error in first_trace["fetch_errors"]
    )

    fail_elink = False
    second_results = asyncio.run(
        tool.pubmed_search_with_fulltext(
            query="batch ELink recovery",
            slug="batch-elink-recovery",
            max_papers=1,
            run_id="elink-recovered-run",
        )
    )

    assert pubmed_requests == [paper_ids, paper_ids]
    assert [request["id"] for request in elink_requests] == [
        paper_ids,
        paper_ids,
    ]
    assert all(
        request["linkname"] == "pubmed_pmc" for request in elink_requests
    )
    assert list(second_results) == ["701"]
    assert "Recovered PMC full text." in second_results["701"]["fulltext"]
    assert fulltext_requests == ["1701"]
    assert all(
        (shared_dir / f"{paper_id}.metadata.json").exists()
        for paper_id in paper_ids
    )
