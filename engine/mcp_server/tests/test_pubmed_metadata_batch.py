"""Public-path checks for opt-in batched PubMed metadata retrieval."""

import asyncio
import json
import runpy
from functools import partial
from pathlib import Path
from typing import Any, cast

import pytest
from Bio import Entrez
from mcp_server import entrez_rate_limit
from mcp_server import pubmed_metadata_batch as batch
from mcp_server.pubmed_client import _EntrezClient
from mcp_server.pubmed_storage import metadata_no_link_sidecar
from mcp_server.tools.lit_review import pubmed_search_with_fulltext as tool

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


class _Handle:
    def __init__(self, payload: Any = None, body: bytes = b"") -> None:
        self.payload = payload
        self.body = body

    def close(self) -> None:
        pass

    def read(self) -> bytes:
        return self.body

    def __contains__(self, value: str) -> bool:
        return value.encode() in self.body


def _article(paper_id: str) -> dict[str, Any]:
    from test_pubmed_pilot_trace import (  # type: ignore[import-not-found]
        _pubmed_article,
    )

    article = _pubmed_article(paper_id)["PubmedArticle"][0]
    article["MedlineCitation"]["PMID"] = paper_id
    return cast(dict[str, Any], article)


def _install_batch_entrez(
    monkeypatch: pytest.MonkeyPatch,
    efetch: Any,
    elink: Any,
) -> None:
    monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)
    monkeypatch.setattr(Entrez, "max_tries", 1)
    monkeypatch.setattr(Entrez, "sleep_between_tries", 0)
    monkeypatch.setattr(Entrez, "efetch", efetch)
    monkeypatch.setattr(Entrez, "elink", elink)
    monkeypatch.setattr(Entrez, "read", lambda handle: handle.payload)


@pytest.fixture(autouse=True)
def _restore_entrez_retry_policy() -> Any:
    max_tries = Entrez.max_tries
    sleep_between_tries = Entrez.sleep_between_tries
    yield
    Entrez.max_tries = max_tries
    Entrez.sleep_between_tries = sleep_between_tries


def test_batched_public_retrieval_maps_records_and_revalidates_cached_no_link(  # noqa: C901
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_root = tmp_path / "cache"
    shared_dir = cache_root / "pubmed" / "batch-source" / "shared"
    shared_dir.mkdir(parents=True)
    cached = {
        "date_revised": "2024/1/1",
        "title": "Cached paper 102",
        "abstract": "Cached abstract.",
        "doi": "<not found>",
        "authors": [],
        "publication": "Example Journal",
        "pmc_full_text_id": None,
        "publication_types": ["Journal Article"],
    }
    (shared_dir / "102.metadata.json").write_text(json.dumps(cached))

    for key, value in {
        "COSCIENTIST_REQUIRE_FREE_MODELS": "1",
        "COSCIENTIST_PUBMED_METADATA_BATCH": "1",
        "COSCIENTIST_PUBMED_PILOT_TRACE": "1",
        "COSCIENTIST_PUBMED_PILOT_BUILD_ID": "batch-offline-build",
        "COSCIENTIST_LIT_REVIEW_DIR": str(cache_root),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)

    pubmed_ids: list[Any] = []
    metadata_requests: list[dict[str, Any]] = []
    elink_ids: list[Any] = []
    elink_requests: list[dict[str, Any]] = []
    fulltext_requests: list[dict[str, Any]] = []

    def esearch(**_kwargs: Any) -> _Handle:
        return _Handle({"IdList": ["101", "102", "103"]})

    def efetch(**kwargs: Any) -> _Handle:
        if kwargs["db"] == "pubmed":
            pubmed_ids.append(kwargs["id"])
            metadata_requests.append(kwargs.copy())
            requested = kwargs["id"]
            ids = requested if isinstance(requested, list) else [requested]
            records = [_article(paper_id) for paper_id in ids]
            return _Handle({"PubmedArticle": list(reversed(records))})
        fulltext_requests.append(kwargs.copy())
        return _Handle(
            body=(
                b"<article><body><sec><title>Introduction</title>"
                b"<p>Full text 103</p></sec></body></article>"
            )
        )

    def elink(**kwargs: Any) -> _Handle:
        elink_requests.append(kwargs.copy())
        elink_ids.append(kwargs["id"])
        requested = kwargs["id"]
        ids = requested if isinstance(requested, list) else [requested]
        groups = {
            "101": {"IdList": ["101"], "LinkSetDb": []},
            "102": {"IdList": ["102"], "LinkSetDb": []},
            "103": {
                "IdList": ["103"],
                "LinkSetDb": [
                    {
                        "LinkName": "pubmed_pmc",
                        "Link": [{"Id": "1030"}],
                    }
                ],
            },
        }
        return _Handle(list(reversed([groups[paper_id] for paper_id in ids])))

    monkeypatch.setattr(Entrez, "esearch", esearch)
    monkeypatch.setattr(Entrez, "efetch", efetch)
    monkeypatch.setattr(Entrez, "elink", elink)
    monkeypatch.setattr(Entrez, "read", lambda handle: handle.payload)

    results = asyncio.run(
        tool.pubmed_search_with_fulltext(
            query="batched cache mapping",
            slug="batch-source",
            max_papers=1,
            run_id="batch-run",
        )
    )

    trace_path = (
        cache_root
        / "pubmed"
        / "batch-source"
        / "runs"
        / "batch-run"
        / ".search-trace.json"
    )
    trace = json.loads(trace_path.read_text(encoding="utf-8"))

    assert pubmed_ids == [["101", "103"]]
    assert metadata_requests[0]["retmode"] == "xml"
    assert elink_ids == [["101", "102", "103"]]
    assert elink_requests[0]["linkname"] == "pubmed_pmc"
    assert len(pubmed_ids) + len(elink_ids) == 2
    assert list(results) == ["103"]
    assert results["103"]["pmc_full_text_id"] == "1030"
    assert "Full text 103" in results["103"]["fulltext"]
    assert [request["id"] for request in fulltext_requests] == ["1030"]
    assert [item["pmid"] for item in trace["fetched"]] == [
        "101",
        "102",
        "103",
    ]
    run_dir = cache_root / "pubmed" / "batch-source" / "runs" / "batch-run"
    for paper_id in ("101", "102", "103"):
        metadata_path = run_dir / f"{paper_id}.metadata.json"
        assert metadata_path.is_symlink()
        assert set(json.loads(metadata_path.read_text(encoding="utf-8"))) == (
            _PUBLIC_METADATA_FIELDS
        )
    assert metadata_no_link_sidecar(shared_dir / "101.metadata.json").exists()
    assert metadata_no_link_sidecar(shared_dir / "102.metadata.json").exists()
    assert not metadata_no_link_sidecar(
        shared_dir / "103.metadata.json"
    ).exists()
    batch_trace = trace["metadata_batching"]
    assert batch_trace["cache_hits"] == ["102"]
    assert batch_trace["batches"] == [
        {
            "batch_index": 1,
            "input_pmids": ["101", "102", "103"],
            "cache_hit_pmids": ["102"],
            "efetch_pmids": ["101", "103"],
            "efetch_returned_pmids": ["103", "101"],
            "elink_pmids": ["101", "102", "103"],
            "elink_results": [
                {"pmid": "101", "status": "no_link", "pmc_id": None},
                {"pmid": "102", "status": "no_link", "pmc_id": None},
                {"pmid": "103", "status": "linked", "pmc_id": "1030"},
            ],
        }
    ]

    second_results = asyncio.run(
        tool.pubmed_search_with_fulltext(
            query="batched cache mapping",
            slug="batch-source",
            max_papers=1,
            run_id="batch-run-2",
        )
    )
    assert second_results["103"]["pmc_full_text_id"] == "1030"
    second_trace = json.loads(
        (
            cache_root
            / "pubmed"
            / "batch-source"
            / "runs"
            / "batch-run-2"
            / ".search-trace.json"
        ).read_text(encoding="utf-8")
    )
    assert list(pubmed_ids) == [["101", "103"]]
    assert elink_ids == [["101", "102", "103"]]
    assert second_trace["metadata_batching"]["batches"][0]["efetch_pmids"] == []
    assert second_trace["metadata_batching"]["batches"][0]["elink_pmids"] == []

    monkeypatch.delenv("COSCIENTIST_PUBMED_METADATA_BATCH")
    legacy_results = asyncio.run(
        tool.pubmed_search_with_fulltext(
            query="batched cache mapping",
            slug="batch-source",
            max_papers=1,
            run_id="batch-run-3",
        )
    )
    legacy_trace = json.loads(
        (
            cache_root
            / "pubmed"
            / "batch-source"
            / "runs"
            / "batch-run-3"
            / ".search-trace.json"
        ).read_text(encoding="utf-8")
    )
    assert legacy_results["103"]["pmc_full_text_id"] == "1030"
    assert "metadata_batching" not in legacy_trace
    assert pubmed_ids == [["101", "103"]]
    assert elink_ids == [["101", "102", "103"]]


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


def _matched_selection_elink(**kwargs: Any) -> _Handle:
    groups = {
        paper_id: {
            "IdList": [paper_id],
            "LinkSetDb": (
                [
                    {
                        "LinkName": "pubmed_pmc",
                        "Link": [{"Id": f"{paper_id}0"}],
                    }
                ]
                if paper_id in {"102", "105"}
                else []
            ),
        }
        for paper_id in kwargs["id"]
    }
    return _Handle(list(reversed(list(groups.values()))))


def test_public_tool_can_skip_fulltext_and_preserve_strict_metadata_trace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Metadata-only mode keeps PMC-first IDs and the pinned batch proof."""
    cache_root = tmp_path / "metadata-only-cache"
    default_run_id = "metadata-default-run"
    build_id = "metadata-only-build"
    for key, value in {
        "COSCIENTIST_REQUIRE_FREE_MODELS": "1",
        "COSCIENTIST_PUBMED_METADATA_BATCH": "1",
        "COSCIENTIST_PUBMED_PILOT_TRACE": "1",
        "COSCIENTIST_PUBMED_PILOT_BUILD_ID": build_id,
        "COSCIENTIST_LIT_REVIEW_DIR": str(cache_root),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)

    ids = ["101", "102", "103", "104", "105", "106"]
    fulltext_requests: list[dict[str, Any]] = []
    extraction_inputs: list[str] = []

    def extract_fulltext(html: str) -> str:
        extraction_inputs.append(html)
        return "Extracted PMC content"

    def efetch(**kwargs: Any) -> _Handle:
        if kwargs["db"] == "pubmed":
            records = [_article(paper_id) for paper_id in kwargs["id"]]
            return _Handle({"PubmedArticle": list(reversed(records))})
        fulltext_requests.append(kwargs.copy())
        return _Handle(body=b"<article><body>PMC full text.</body></article>")

    monkeypatch.setattr(
        Entrez, "esearch", partial(_matched_selection_esearch, cache_root, ids)
    )
    _install_batch_entrez(monkeypatch, efetch, _matched_selection_elink)
    monkeypatch.setattr(tool, "extract_text_from_pmc_html", extract_fulltext)

    default_results = asyncio.run(
        tool.pubmed_search_with_fulltext(
            query="matched metadata selection",
            slug="metadata-default-run",
            max_papers=3,
            run_id=default_run_id,
        )
    )
    default_run_dir = (
        cache_root / "pubmed" / "metadata-default-run" / "runs" / default_run_id
    )
    default_trace = json.loads(
        (default_run_dir / ".search-trace.json").read_text(encoding="utf-8")
    )
    repo_root = Path(__file__).resolve().parents[3]
    validate_batch_trace = runpy.run_path(
        str(repo_root / "references/external/sakana/novelty_batch_trace.py")
    )["validate_batch_trace"]
    validate_batch_trace(
        default_trace,
        run_id=default_run_id,
        expected_build_id=build_id,
        serving_process={
            "pid": default_trace["process_id"],
            "mcp_tree": build_id,
        },
        returned_ids=list(default_results),
    )

    assert list(default_results) == ["102", "105", "101"]
    assert default_results["102"]["fulltext"] == "Extracted PMC content"
    assert default_results["105"]["fulltext"] == "Extracted PMC content"
    assert len(fulltext_requests) == 2
    assert len(extraction_inputs) == 2
    default_metadata = {
        paper_id: {
            key: value for key, value in metadata.items() if key != "fulltext"
        }
        for paper_id, metadata in default_results.items()
    }

    fulltext_requests.clear()
    extraction_inputs.clear()
    metadata_run_id = "metadata-only-run"
    results = asyncio.run(
        tool.pubmed_search_with_fulltext(
            query="matched metadata selection",
            slug=metadata_run_id,
            max_papers=3,
            run_id=metadata_run_id,
            include_fulltext=False,
        )
    )
    run_dir = cache_root / "pubmed" / metadata_run_id / "runs" / metadata_run_id
    trace = json.loads(
        (run_dir / ".search-trace.json").read_text(encoding="utf-8")
    )
    evidence = validate_batch_trace(
        trace,
        run_id=metadata_run_id,
        expected_build_id=build_id,
        serving_process={"pid": trace["process_id"], "mcp_tree": build_id},
        returned_ids=list(results),
    )

    metadata_only = {
        paper_id: {
            key: value for key, value in metadata.items() if key != "fulltext"
        }
        for paper_id, metadata in results.items()
    }
    assert metadata_only == default_metadata
    assert list(results) == ["102", "105", "101"]
    assert results["102"]["pmc_full_text_id"] == "1020"
    assert results["105"]["pmc_full_text_id"] == "1050"
    assert results["102"]["title"] == "Paper 102"
    assert results["102"]["abstract"] == "A real-shaped abstract."
    assert all("fulltext" not in result for result in results.values())
    assert fulltext_requests == []
    assert extraction_inputs == []
    assert trace["final_ids"] == ["102", "105", "101"]
    assert trace["fetch_errors"] == []
    assert trace["incomplete_fetch_count"] == 0
    assert trace["entrez_calls"] == {"esearch": 1, "efetch": 1, "elink": 1}
    assert evidence["selected_pmids"] == ids
    assert evidence["metadata_batching"]["metadata_efetch_batches"] == 1
    assert evidence["metadata_batching"]["elink_batches"] == 1
    assert (run_dir / ".manifest.json").is_file()


def test_unmappable_efetch_record_does_not_discard_valid_requested_records(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        batch, "entrez_call", lambda request, **kwargs: request(**kwargs)
    )
    monkeypatch.setattr(Entrez, "efetch", lambda **_kwargs: object())
    client = _EntrezClient(tmp_path)
    monkeypatch.setattr(
        client,
        "entrez_read",
        lambda _handle: {
            "PubmedArticle": [
                _article("101"),
                {"malformed": True},
                _article("103"),
            ]
        },
    )

    metadata, returned_ids, errors = batch._fetch_paper_details(
        client, ["101", "102", "103"]
    )

    assert list(metadata) == ["101", "103"]
    assert returned_ids == ["101", "103"]
    assert set(errors) == {"102"}
