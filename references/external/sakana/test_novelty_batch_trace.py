"""Strict offline checks for the maintained PubMed batch trace."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from Bio import Entrez
from mcp_server import entrez_rate_limit
from mcp_server.tools.lit_review import pubmed_search_with_fulltext as tool
from novelty_batch_trace import validate_batch_trace

_ROOT = Path(__file__).resolve().parents[3]
_BUILD_ID = "batch-offline-build"
_RUN_ID = "batch-run"
_SOURCE_FILE = str((_ROOT / "engine/mcp_server/pubmed_client.py").resolve())
_IDS = ["101", "102", "103"]
_RETRY_POLICY = {"max_tries": 1, "sleep_between_tries": 0}


def _batch_records(ids: list[str]) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    for index in range(0, len(ids), 9):
        chunk = ids[index : index + 9]
        outcomes = []
        for paper_id in chunk:
            linked = paper_id == ids[0]
            outcomes.append(
                {
                    "pmid": paper_id,
                    "status": "linked" if linked else "no_link",
                    "pmc_id": "1101" if linked else None,
                }
            )
        batches.append(
            {
                "batch_index": len(batches) + 1,
                "input_pmids": chunk,
                "cache_hit_pmids": [],
                "efetch_pmids": chunk,
                "efetch_returned_pmids": list(reversed(chunk)),
                "elink_pmids": chunk,
                "elink_results": outcomes,
            }
        )
    return batches


def _valid_trace(ids: list[str] | None = None) -> dict[str, Any]:
    selected_ids = list(_IDS if ids is None else ids)
    batches = _batch_records(selected_ids)
    linked_id = selected_ids[0] if selected_ids else None
    fetched = [
        {
            "pmid": paper_id,
            "fetched": True,
            "metadata_origin": "entrez_fetch",
            "pmc_available": paper_id == linked_id,
            "abstract_available": True,
            "incomplete": False,
        }
        for paper_id in selected_ids
    ]
    trace: dict[str, Any] = {
        "run_id": _RUN_ID,
        "server_build_id": _BUILD_ID,
        "process_id": 321,
        "source_file": _SOURCE_FILE,
        "sort": "pub_date",
        "entrez_retry_policy": _RETRY_POLICY.copy(),
        "entrez_calls": {
            "esearch": 1,
            "efetch": len(batches) + (2 if linked_id else 0),
            "elink": len(batches),
        },
        "incomplete_fetch_count": 0,
        "fetch_errors": [],
        "metadata_origins": {paper_id: "entrez_fetch" for paper_id in selected_ids},
        "attempts": [
            {
                "rung_index": 1,
                "rung_type": "original",
                "operation": "esearch",
                "count": len(selected_ids),
                "first_ids": selected_ids,
                "sort": "pub_date",
            }
        ],
        "selected": (
            {
                "rung_index": 1,
                "rung_type": "original",
                "count": len(selected_ids),
                "ids": selected_ids,
                "sort": "pub_date",
            }
            if selected_ids
            else None
        ),
        "pre_search_shared_pool": {
            "file_count": 0,
            "metadata_count": 0,
            "first_ids": [],
        },
        "fetched": fetched,
        "final_ids": [linked_id] if linked_id else [],
        "shared_pool_supplements": [],
        "error": None,
        "outcome": "nonempty" if selected_ids else "empty",
    }
    if selected_ids:
        trace["metadata_batching"] = {
            "sampled_pmids": selected_ids,
            "cache_hits": [],
            "batches": batches,
        }
    return trace


def _validate(
    trace: dict[str, Any],
    returned_ids: list[str] | None = None,
    serving_process: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return validate_batch_trace(
        trace,
        run_id=_RUN_ID,
        expected_build_id=_BUILD_ID,
        serving_process=serving_process or {"pid": 321},
        returned_ids=(trace["final_ids"] if returned_ids is None else returned_ids),
    )


def test_valid_shuffled_batch_trace_distinguishes_metadata_from_pmc_pages() -> None:
    trace = _valid_trace()
    trace["metadata_batching"]["batches"][0]["efetch_returned_pmids"] = [
        "103",
        "101",
        "102",
    ]

    evidence = _validate(trace, returned_ids=["101"])

    assert evidence["selected_pmids"] == _IDS
    assert evidence["metadata_batching"]["metadata_efetch_batches"] == 1
    assert evidence["metadata_batching"]["elink_batches"] == 1
    assert evidence["entrez_calls"]["efetch"] == 3
    assert evidence["metadata_savings"]["efetch_entries_saved"] == 2
    assert evidence["metadata_savings"]["elink_entries_saved"] == 2
    assert "total HTTP requests" not in evidence["count_semantics"]


def test_valid_empty_search_has_no_batch_metadata() -> None:
    trace = _valid_trace([])

    evidence = _validate(trace, returned_ids=[])

    assert evidence["selected_pmids"] == []
    assert evidence["metadata_batching"]["batch_count"] == 0
    assert evidence["entrez_calls"] == {
        "esearch": 1,
        "efetch": 0,
        "elink": 0,
    }


@pytest.mark.parametrize(
    "tamper",
    [
        "duplicate_sample",
        "missing_sample",
        "selected_over_cap",
        "duplicate_batch_id",
        "wrong_batch_id",
        "partial_efetch_request",
        "wrong_efetch_response",
        "duplicate_efetch_response",
        "missing_elink_result",
        "duplicate_elink_result",
        "invalid_pmc_id",
        "link_availability_mismatch",
        "cache_hit",
        "nonempty_pool",
        "efetch_under_counted",
        "elink_over_counted",
        "batch_truncated",
        "fetch_error",
        "incomplete_fetch",
        "unknown_cache_origin",
        "recovery_trace",
    ],
)
def test_tampered_batch_trace_is_rejected(tamper: str) -> None:
    trace = _valid_trace()
    batch = trace["metadata_batching"]["batches"][0]
    if tamper == "duplicate_sample":
        trace["metadata_batching"]["sampled_pmids"] = ["101", "101", "103"]
    elif tamper == "missing_sample":
        trace["metadata_batching"]["sampled_pmids"].pop()
    elif tamper == "selected_over_cap":
        trace = _valid_trace([str(value) for value in range(100, 110)])
    elif tamper == "duplicate_batch_id":
        batch["input_pmids"] = ["101", "101", "103"]
    elif tamper == "wrong_batch_id":
        batch["elink_pmids"][-1] = "999"
    elif tamper == "partial_efetch_request":
        batch["efetch_pmids"].pop()
    elif tamper == "wrong_efetch_response":
        batch["efetch_returned_pmids"][-1] = "999"
    elif tamper == "duplicate_efetch_response":
        batch["efetch_returned_pmids"][-1] = batch["efetch_returned_pmids"][0]
    elif tamper == "missing_elink_result":
        batch["elink_results"].pop()
    elif tamper == "duplicate_elink_result":
        batch["elink_results"][-1]["pmid"] = "101"
    elif tamper == "invalid_pmc_id":
        batch["elink_results"][0]["pmc_id"] = ""
    elif tamper == "link_availability_mismatch":
        batch["elink_results"][0]["status"] = "no_link"
        batch["elink_results"][0]["pmc_id"] = None
    elif tamper == "cache_hit":
        trace["metadata_batching"]["cache_hits"] = ["101"]
        batch["cache_hit_pmids"] = ["101"]
    elif tamper == "nonempty_pool":
        trace["pre_search_shared_pool"]["file_count"] = 1
    elif tamper == "efetch_under_counted":
        trace["entrez_calls"]["efetch"] = 0
    elif tamper == "elink_over_counted":
        trace["entrez_calls"]["elink"] = 2
    elif tamper == "batch_truncated":
        trace["metadata_batching"]["truncated_batches"] = 1
    elif tamper == "fetch_error":
        trace["fetch_errors"] = [{"stage": "elink", "pmid": "101"}]
    elif tamper == "incomplete_fetch":
        trace["incomplete_fetch_count"] = 1
    elif tamper == "unknown_cache_origin":
        trace["metadata_origins"]["101"] = "shared_pool_cache"
        trace["fetched"][0]["metadata_origin"] = "shared_pool_cache"
    elif tamper == "recovery_trace":
        trace["entrez_recovery"] = {"enabled": True}

    with pytest.raises(ValueError, match="batch trace attestation"):
        _validate(trace)


def test_empty_search_rejects_emitted_batch_trace() -> None:
    trace = _valid_trace([])
    trace["metadata_batching"] = {
        "sampled_pmids": [],
        "cache_hits": [],
        "batches": [],
    }

    with pytest.raises(ValueError, match="batch trace attestation"):
        _validate(trace, returned_ids=[])


def test_runtime_recovery_attestation_is_rejected() -> None:
    with pytest.raises(ValueError, match="batch trace attestation"):
        _validate(
            _valid_trace(),
            serving_process={"pid": 321, "study4_recovery": {"enabled": True}},
        )


class _CannedHandle:
    def __init__(
        self,
        payload: Any = None,
        body: bytes = b"",
        *,
        truncated: bool = False,
    ) -> None:
        self.payload = payload
        self.body = body
        self.truncated = truncated

    def close(self) -> None:
        pass

    def read(self) -> bytes:
        return self.body

    def __contains__(self, marker: str) -> bool:
        return marker == "[truncated]" and self.truncated


def _pubmed_article(paper_id: str) -> dict[str, Any]:
    return {
        "MedlineCitation": {
            "PMID": paper_id,
            "DateRevised": {"Year": "2024", "Month": "1", "Day": "1"},
            "Article": {
                "ArticleTitle": f"Paper {paper_id}",
                "Abstract": {"AbstractText": ["A real shaped abstract."]},
                "Journal": {"Title": "Example Journal"},
                "AuthorList": [],
                "PublicationTypeList": ["Journal Article"],
            },
        },
        "PubmedData": {"ArticleIdList": []},
    }


@pytest.fixture(autouse=True)
def _reset_entrez_retry_policy() -> Any:
    max_tries = Entrez.max_tries
    sleep_between_tries = Entrez.sleep_between_tries
    yield
    Entrez.max_tries = max_tries
    Entrez.sleep_between_tries = sleep_between_tries


def test_maintained_public_producer_emits_valid_paginated_batch_trace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_root = tmp_path / "cache"
    for key, value in {
        "COSCIENTIST_REQUIRE_FREE_MODELS": "1",
        "COSCIENTIST_PUBMED_METADATA_BATCH": "1",
        "COSCIENTIST_PUBMED_PILOT_TRACE": "1",
        "COSCIENTIST_PUBMED_PILOT_BUILD_ID": _BUILD_ID,
        "COSCIENTIST_PUBMED_STUDY4_RECOVERY": "0",
        "COSCIENTIST_LIT_REVIEW_DIR": str(cache_root),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("COSCIENTIST_PUBMED_STUDY_ID", raising=False)
    monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)
    monkeypatch.setattr(Entrez, "max_tries", 1)
    monkeypatch.setattr(Entrez, "sleep_between_tries", 0)
    monkeypatch.setattr(Entrez, "read", lambda handle: handle.payload)
    fulltext_calls: list[dict[str, Any]] = []

    def esearch(**_kwargs: Any) -> _CannedHandle:
        return _CannedHandle({"IdList": _IDS})

    def efetch(**kwargs: Any) -> _CannedHandle:
        if kwargs["db"] == "pubmed":
            return _CannedHandle(
                {"PubmedArticle": [_pubmed_article(value) for value in reversed(_IDS)]}
            )
        fulltext_calls.append(kwargs.copy())
        if kwargs["retstart"] == 0:
            return _CannedHandle(
                body=b"<article><body><sec><p>First page</p></sec>",
                truncated=True,
            )
        return _CannedHandle(body=b"<sec><p>Second page</p></sec></body></article>")

    def elink(**kwargs: Any) -> _CannedHandle:
        return _CannedHandle(
            [
                {
                    "IdList": [paper_id],
                    "LinkSetDb": (
                        [
                            {
                                "LinkName": "pubmed_pmc",
                                "Link": [{"Id": "1101"}],
                            }
                        ]
                        if paper_id == "101"
                        else []
                    ),
                }
                for paper_id in reversed(kwargs["id"])
            ]
        )

    monkeypatch.setattr(Entrez, "esearch", esearch)
    monkeypatch.setattr(Entrez, "efetch", efetch)
    monkeypatch.setattr(Entrez, "elink", elink)

    results = asyncio.run(
        tool.pubmed_search_with_fulltext(
            query="offline batch trace",
            slug="batch-trace-unique",
            max_papers=1,
            run_id=_RUN_ID,
        )
    )
    trace_path = (
        cache_root
        / "pubmed"
        / "batch-trace-unique"
        / "runs"
        / _RUN_ID
        / ".search-trace.json"
    )
    trace = json.loads(trace_path.read_text(encoding="utf-8"))

    assert list(results) == ["101"]
    assert "First page" in results["101"]["fulltext"]
    assert "Second page" in results["101"]["fulltext"]
    assert len(fulltext_calls) == 2
    assert [call["retstart"] for call in fulltext_calls] == [
        0,
        len(b"<article><body><sec><p>First page</p></sec>"),
    ]
    assert trace["entrez_calls"]["efetch"] == 3
    evidence = validate_batch_trace(
        trace,
        run_id=_RUN_ID,
        expected_build_id=_BUILD_ID,
        serving_process={"pid": os.getpid()},
        returned_ids=list(results),
    )
    assert evidence["metadata_batching"]["metadata_efetch_batches"] == 1
    assert evidence["entrez_calls"]["efetch"] == 3
