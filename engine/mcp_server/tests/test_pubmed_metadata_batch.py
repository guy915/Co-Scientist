"""Offline contracts for pubmed metadata batch."""

import asyncio
import hashlib
import json
from functools import partial
from pathlib import Path
from typing import Any, cast

import mcp_server.entrez as entrez_rate_limit
import pytest
from Bio import Entrez
from mcp_server import pubmed_metadata_batch as batch
from mcp_server.literature_review import PubmedSource
from mcp_server.pubmed_client import _EntrezClient
from mcp_server.pubmed_storage import metadata_no_link_sidecar
from mcp_server.tests._httpx import validate_batch_trace
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
    from mcp_server.tests.test_pubmed_pilot_trace import (
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


@pytest.mark.usefixtures("_restore_entrez_retry_policy")
class TestPubmedMetadataBatch:
    def test_batched_public_retrieval_maps_records_and_revalidates_cached_no_link(  # noqa: C901, E501
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
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
            return _Handle(
                list(reversed([groups[paper_id] for paper_id in ids]))
            )

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
            assert set(
                json.loads(metadata_path.read_text(encoding="utf-8"))
            ) == (_PUBLIC_METADATA_FIELDS)
        assert metadata_no_link_sidecar(
            shared_dir / "101.metadata.json"
        ).exists()
        assert metadata_no_link_sidecar(
            shared_dir / "102.metadata.json"
        ).exists()
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
        assert (
            second_trace["metadata_batching"]["batches"][0]["efetch_pmids"]
            == []
        )
        assert (
            second_trace["metadata_batching"]["batches"][0]["elink_pmids"] == []
        )

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

    def test_public_tool_can_skip_fulltext_and_preserve_strict_metadata_trace(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
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
            return _Handle(
                body=b"<article><body>PMC full text.</body></article>"
            )

        monkeypatch.setattr(
            Entrez,
            "esearch",
            partial(_matched_selection_esearch, cache_root, ids),
        )
        _install_batch_entrez(monkeypatch, efetch, _matched_selection_elink)
        monkeypatch.setattr(
            tool, "extract_text_from_pmc_html", extract_fulltext
        )

        default_results = asyncio.run(
            tool.pubmed_search_with_fulltext(
                query="matched metadata selection",
                slug="metadata-default-run",
                max_papers=3,
                run_id=default_run_id,
            )
        )
        default_run_dir = (
            cache_root
            / "pubmed"
            / "metadata-default-run"
            / "runs"
            / default_run_id
        )
        default_trace = json.loads(
            (default_run_dir / ".search-trace.json").read_text(encoding="utf-8")
        )
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
                key: value
                for key, value in metadata.items()
                if key != "fulltext"
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
        run_dir = (
            cache_root / "pubmed" / metadata_run_id / "runs" / metadata_run_id
        )
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
                key: value
                for key, value in metadata.items()
                if key != "fulltext"
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
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
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


def test_duplicate_efetch_record_fails_only_that_pmid(
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
                _article("101"),
                _article("103"),
            ]
        },
    )

    metadata, returned_ids, errors = batch._fetch_paper_details(
        client, ["101", "102", "103"]
    )

    assert list(metadata) == ["103"]
    assert returned_ids == ["101", "101", "103"]
    assert set(errors) == {"101", "102"}


def test_efetch_transport_failure_marks_each_requested_pmid_incomplete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        batch, "entrez_call", lambda request, **kwargs: request(**kwargs)
    )
    monkeypatch.setattr(Entrez, "efetch", lambda **_kwargs: object())
    client = _EntrezClient(tmp_path)

    def fail(_handle: Any) -> Any:
        raise RuntimeError("offline")

    monkeypatch.setattr(client, "entrez_read", fail)
    metadata, returned_ids, errors = batch._fetch_paper_details(
        client, ["101", "102"]
    )

    assert metadata == {}
    assert returned_ids == []
    assert set(errors) == {"101", "102"}
    assert all(isinstance(error, RuntimeError) for error in errors.values())


def test_whole_efetch_failure_skips_elink_for_fresh_pmids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paper_ids = ["801", "802"]

    def fail_efetch(**_kwargs: Any) -> _Handle:
        raise RuntimeError("offline")

    def fail_elink(**_kwargs: Any) -> _Handle:
        pytest.fail("ELink must be skipped when every EFetch record failed")

    _install_batch_entrez(monkeypatch, fail_efetch, fail_elink)
    shared_dir = tmp_path / "shared"
    shared_dir.mkdir()
    trace: dict[str, Any] = {
        "selected": {"ids": paper_ids},
        "metadata_origins": {},
        "incomplete_fetch_count": 0,
        "fetch_errors": [],
        "entrez_calls": {"esearch": 0, "efetch": 0, "elink": 0},
    }

    with entrez_rate_limit.pilot_trace_context(trace):
        results = asyncio.run(
            batch.gather_metadata(
                _EntrezClient(tmp_path),
                paper_ids,
                shared_dir,
                None,
                asyncio.Semaphore(1),
            )
        )

    assert results == {}
    assert trace["entrez_calls"] == {"esearch": 0, "efetch": 1, "elink": 0}
    assert [item["pmid"] for item in trace["fetch_errors"]] == paper_ids
    assert trace["metadata_batching"]["batches"][0]["elink_pmids"] == []
    assert not any(shared_dir.iterdir())


def test_partial_efetch_failure_links_only_valid_returned_pmids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paper_ids = ["811", "812", "813", "814"]
    elink_ids: list[list[str]] = []

    def efetch(**_kwargs: Any) -> _Handle:
        return _Handle(
            {
                "PubmedArticle": [
                    _article("811"),
                    _article("813"),
                    _article("813"),
                    _article("814"),
                    {"malformed": True},
                ]
            }
        )

    def elink(**kwargs: Any) -> _Handle:
        elink_ids.append(kwargs["id"])
        return _Handle(
            [{"IdList": [paper_id]} for paper_id in reversed(kwargs["id"])]
        )

    _install_batch_entrez(monkeypatch, efetch, elink)
    shared_dir = tmp_path / "shared"
    shared_dir.mkdir()
    trace: dict[str, Any] = {
        "selected": {"ids": paper_ids},
        "metadata_origins": {},
        "incomplete_fetch_count": 0,
        "fetch_errors": [],
        "entrez_calls": {"esearch": 0, "efetch": 0, "elink": 0},
    }

    with entrez_rate_limit.pilot_trace_context(trace):
        results = asyncio.run(
            batch.gather_metadata(
                _EntrezClient(tmp_path),
                paper_ids,
                shared_dir,
                None,
                asyncio.Semaphore(1),
            )
        )

    assert list(results) == ["811", "814"]
    assert elink_ids == [["811", "814"]]
    assert trace["metadata_batching"]["batches"][0]["elink_pmids"] == [
        "811",
        "814",
    ]
    assert [item["pmid"] for item in trace["fetch_errors"]] == ["812", "813"]
    assert all(
        (shared_dir / f"{paper_id}.metadata.json").exists()
        for paper_id in ("811", "814")
    )
    assert not (shared_dir / "812.metadata.json").exists()
    assert not (shared_dir / "813.metadata.json").exists()


def test_shuffled_elink_groups_map_by_source_and_accept_no_link() -> None:
    outcomes = batch._map_pmc_link_groups(
        [
            {
                "IdList": ["103"],
                "LinkSetDb": [
                    {"LinkName": "pubmed_pmc", "Link": [{"Id": "1030"}]}
                ],
            },
            {"IdList": ["101"]},
        ],
        ["101", "102", "103"],
    )

    assert outcomes["101"] == (None, None)
    assert isinstance(outcomes["102"][1], ValueError)
    assert outcomes["103"] == ("1030", None)


def test_malformed_and_duplicate_elink_groups_are_isolated_by_pmid() -> None:
    outcomes = batch._map_pmc_link_groups(
        [
            {"IdList": ["101"]},
            {"IdList": ["102"], "LinkSetDb": "malformed"},
            {"IdList": ["103"]},
            {"IdList": ["103"]},
        ],
        ["101", "102", "103"],
    )

    assert outcomes["101"] == (None, None)
    assert isinstance(outcomes["102"][1], ValueError)
    assert isinstance(outcomes["103"][1], ValueError)


@pytest.mark.parametrize(
    "destination", ["", "not-numeric", "\uff11\uff12\uff13"]
)
def test_blank_or_non_ascii_numeric_pmc_destination_is_incomplete(
    destination: str,
) -> None:
    outcomes = batch._map_pmc_link_groups(
        [
            {"IdList": ["101"]},
            {
                "IdList": ["102"],
                "LinkSetDb": [
                    {
                        "LinkName": "pubmed_pmc",
                        "Link": [{"Id": destination}],
                    }
                ],
            },
        ],
        ["101", "102"],
    )

    assert outcomes["101"] == (None, None)
    assert isinstance(outcomes["102"][1], ValueError)


def test_elink_transport_failure_returns_metadata_without_caching_false_no_link(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_batch_entrez(
        monkeypatch,
        lambda **_kwargs: _Handle({"PubmedArticle": [_article("101")]}),
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    shared_dir = tmp_path / "slug" / "shared"
    shared_dir.mkdir(parents=True)
    trace: dict[str, Any] = {
        "selected": {"ids": ["101"]},
        "metadata_origins": {},
        "incomplete_fetch_count": 0,
        "fetch_errors": [],
        "entrez_calls": {"esearch": 0, "efetch": 0, "elink": 0},
    }
    client = _EntrezClient(tmp_path)

    with entrez_rate_limit.pilot_trace_context(trace):
        results = asyncio.run(
            batch.gather_metadata(
                client,
                ["101"],
                shared_dir,
                None,
                asyncio.Semaphore(1),
            )
        )

    assert results["101"]["pmc_full_text_id"] is None
    assert not (shared_dir / "101.metadata.json").exists()
    assert trace["entrez_calls"] == {"esearch": 0, "efetch": 1, "elink": 1}
    assert trace["metadata_origins"] == {"101": "entrez_fetch"}
    assert trace["incomplete_fetch_count"] == 1
    assert trace["fetch_errors"][0]["stage"] == "elink"


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
