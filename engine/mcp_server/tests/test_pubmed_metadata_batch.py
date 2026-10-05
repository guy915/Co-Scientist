import asyncio
import json
from contextlib import nullcontext
from functools import partial
from pathlib import Path
from typing import Any, cast

import mcp_server.entrez as entrez_rate_limit
import pytest
from Bio import Entrez
from mcp_server import pubmed_metadata_batch as batch
from mcp_server.pubmed_client import _EntrezClient
from mcp_server.pubmed_storage import metadata_no_link_sidecar
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


def _gather(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    paper_ids: list[str],
    efetch: Any,
    elink: Any,
    slug: str = "slug",
    traced: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    _install_batch_entrez(monkeypatch, efetch, elink)
    shared_dir = tmp_path / slug / "shared"
    shared_dir.mkdir(parents=True)
    trace: dict[str, Any] = {
        "selected": {"ids": paper_ids[:9], "count": len(paper_ids)},
        "metadata_origins": {},
        "incomplete_fetch_count": 0,
        "fetch_errors": [],
        "entrez_calls": {"esearch": 0, "efetch": 0, "elink": 0},
    }
    with (
        entrez_rate_limit.pilot_trace_context(trace)
        if traced
        else nullcontext()
    ):
        results = asyncio.run(
            batch.gather_metadata(
                _EntrezClient(tmp_path),
                paper_ids,
                shared_dir,
                None,
                asyncio.Semaphore(1),
            )
        )
    return results, trace, shared_dir


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
    def test_batched_public_retrieval_maps_records_and_revalidates_cached_no_link(  # noqa: E501
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

        configure_trace(
            monkeypatch, cache_root, "batch-offline-build", free_models=True
        )
        monkeypatch.setenv("COSCIENTIST_PUBMED_METADATA_BATCH", "1")

        pubmed_ids: list[Any] = []
        elink_ids: list[Any] = []
        fulltext_requests: list[dict[str, Any]] = []
        link = _elink_groups({"103": "1030"})

        def efetch(**kwargs: Any) -> _Handle:
            if kwargs["db"] == "pubmed":
                pubmed_ids.append(kwargs["id"])
                return _efetch_reversed(**kwargs)
            fulltext_requests.append(kwargs.copy())
            return _Handle(
                body=(
                    b"<article><body><sec><title>Introduction</title>"
                    b"<p>Full text 103</p></sec></body></article>"
                )
            )

        def elink(**kwargs: Any) -> _Handle:
            elink_ids.append(kwargs["id"])
            return cast(_Handle, link(**kwargs))

        install_entrez(
            monkeypatch,
            esearch=lambda **_kwargs: _Handle(
                {"IdList": ["101", "102", "103"]}
            ),
            efetch=efetch,
            elink=elink,
        )

        def search(run_id: str) -> dict[str, Any]:
            return asyncio.run(
                tool.pubmed_search_with_fulltext(
                    query="batched cache mapping",
                    slug="batch-source",
                    max_papers=1,
                    run_id=run_id,
                )
            )

        results = search("batch-run")
        trace = read_trace(cache_root, "batch-source", "batch-run")

        assert pubmed_ids == [["101", "103"]]
        assert elink_ids == [["101", "102", "103"]]
        assert list(results) == ["103"]
        assert results["103"]["pmc_full_text_id"] == "1030"
        assert "Full text 103" in results["103"]["fulltext"]
        assert [request["id"] for request in fulltext_requests] == ["1030"]
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
        assert trace["metadata_batching"]["cache_hits"] == ["102"]
        assert trace["metadata_batching"]["batches"] == [
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

        second_results = search("batch-run-2")
        second_batch = read_trace(cache_root, "batch-source", "batch-run-2")[
            "metadata_batching"
        ]["batches"][0]
        assert second_results["103"]["pmc_full_text_id"] == "1030"
        assert pubmed_ids == [["101", "103"]]
        assert elink_ids == [["101", "102", "103"]]
        assert second_batch["efetch_pmids"] == second_batch["elink_pmids"] == []

        monkeypatch.delenv("COSCIENTIST_PUBMED_METADATA_BATCH")
        legacy_results = search("batch-run-3")
        legacy_trace = read_trace(cache_root, "batch-source", "batch-run-3")
        assert legacy_results["103"]["pmc_full_text_id"] == "1030"
        assert "metadata_batching" not in legacy_trace
        assert pubmed_ids == [["101", "103"]]
        assert elink_ids == [["101", "102", "103"]]

    def test_public_tool_can_skip_fulltext_and_preserve_strict_metadata_trace(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cache_root = tmp_path / "metadata-only-cache"
        configure_trace(
            monkeypatch, cache_root, "metadata-only-build", free_models=True
        )
        monkeypatch.setenv("COSCIENTIST_PUBMED_METADATA_BATCH", "1")
        monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)

        ids = ["101", "102", "103", "104", "105", "106"]
        fulltext_requests: list[dict[str, Any]] = []
        extraction_inputs: list[str] = []

        def extract_fulltext(html: str) -> str:
            extraction_inputs.append(html)
            return "Extracted PMC content"

        def efetch(**kwargs: Any) -> _Handle:
            if kwargs["db"] == "pubmed":
                return _efetch_reversed(**kwargs)
            fulltext_requests.append(kwargs.copy())
            return _Handle(
                body=b"<article><body>PMC full text.</body></article>"
            )

        monkeypatch.setattr(
            Entrez,
            "esearch",
            partial(_matched_selection_esearch, cache_root, ids),
        )
        _install_batch_entrez(
            monkeypatch, efetch, _elink_groups({"102": "1020", "105": "1050"})
        )
        monkeypatch.setattr(
            tool, "extract_text_from_pmc_html", extract_fulltext
        )

        def search(slug: str, **kwargs: Any) -> dict[str, Any]:
            return asyncio.run(
                tool.pubmed_search_with_fulltext(
                    query="matched metadata selection",
                    slug=slug,
                    max_papers=3,
                    run_id=slug,
                    **kwargs,
                )
            )

        default_results = search("metadata-default-run")
        assert list(default_results) == ["102", "105", "101"]
        assert default_results["102"]["fulltext"] == "Extracted PMC content"
        assert len(fulltext_requests) == len(extraction_inputs) == 2
        fulltext_requests.clear()
        extraction_inputs.clear()

        results = search("metadata-only-run", include_fulltext=False)
        trace = read_trace(cache_root, "metadata-only-run", "metadata-only-run")
        run_dir = cache_root / "pubmed" / "metadata-only-run" / "runs"

        assert list(results) == ["102", "105", "101"]
        assert results["102"]["pmc_full_text_id"] == "1020"
        assert results["105"]["pmc_full_text_id"] == "1050"
        assert all("fulltext" not in result for result in results.values())
        assert {
            paper_id: {k: v for k, v in metadata.items() if k != "fulltext"}
            for paper_id, metadata in default_results.items()
        } == results
        assert fulltext_requests == []
        assert extraction_inputs == []
        assert trace["final_ids"] == ["102", "105", "101"]
        assert trace["fetch_errors"] == []
        assert trace["incomplete_fetch_count"] == 0
        assert trace["entrez_calls"] == {"esearch": 1, "efetch": 1, "elink": 1}
        (only_batch,) = trace["metadata_batching"]["batches"]
        assert only_batch["efetch_pmids"] == only_batch["elink_pmids"] == ids
        assert (run_dir / "metadata-only-run" / ".manifest.json").is_file()

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


def test_whole_efetch_failure_skips_elink_for_fresh_pmids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail_efetch(**_kwargs: Any) -> _Handle:
        raise RuntimeError("offline")

    def fail_elink(**_kwargs: Any) -> _Handle:
        pytest.fail("ELink must be skipped when every EFetch record failed")

    paper_ids = ["801", "802"]
    results, trace, shared_dir = _gather(
        monkeypatch, tmp_path, paper_ids, fail_efetch, fail_elink
    )

    assert results == {}
    assert trace["entrez_calls"] == {"esearch": 0, "efetch": 1, "elink": 0}
    assert [item["pmid"] for item in trace["fetch_errors"]] == paper_ids
    assert trace["metadata_batching"]["batches"][0]["elink_pmids"] == []
    assert not any(shared_dir.iterdir())


def test_partial_efetch_failure_links_only_valid_returned_pmids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    elink_ids: list[list[str]] = []

    def efetch(**_kwargs: Any) -> _Handle:
        records = [_article(p) for p in ("811", "813", "813", "814")]
        return _Handle({"PubmedArticle": [*records, {"malformed": True}]})

    def elink(**kwargs: Any) -> _Handle:
        elink_ids.append(kwargs["id"])
        return _Handle([{"IdList": [paper_id]} for paper_id in kwargs["id"]])

    results, trace, shared_dir = _gather(
        monkeypatch, tmp_path, ["811", "812", "813", "814"], efetch, elink
    )

    assert list(results) == ["811", "814"]
    assert elink_ids == [["811", "814"]]
    assert [item["pmid"] for item in trace["fetch_errors"]] == ["812", "813"]
    assert sorted(path.name for path in shared_dir.glob("*.json")) == [
        "811.metadata.json",
        "814.metadata.json",
    ]


def _destination_group(destination: str) -> list[dict[str, Any]]:
    link = {"LinkName": "pubmed_pmc", "Link": [{"Id": destination}]}
    return [{"IdList": ["101"]}, {"IdList": ["102"], "LinkSetDb": [link]}]


@pytest.mark.parametrize(
    ("paper_ids", "groups", "expected_links", "incomplete"),
    [
        pytest.param(
            ["101", "102", "103"],
            [
                {
                    "IdList": ["103"],
                    "LinkSetDb": [
                        {"LinkName": "pubmed_pmc", "Link": [{"Id": "1030"}]}
                    ],
                },
                {"IdList": ["101"]},
            ],
            {"101": None, "103": "1030"},
            {"102"},
            id="shuffled groups map by source pmid and accept no-link",
        ),
        pytest.param(
            ["101", "102", "103"],
            [
                {"IdList": ["101"]},
                {"IdList": ["102"], "LinkSetDb": "malformed"},
                {"IdList": ["103"]},
                {"IdList": ["103"]},
            ],
            {"101": None},
            {"102", "103"},
            id="malformed and duplicate groups are isolated by pmid",
        ),
        *(
            pytest.param(
                ["101", "102"],
                _destination_group(destination),
                {"101": None},
                {"102"},
                id=f"destination {destination!r} is incomplete",
            )
            for destination in ("", "not-numeric", "\uff11\uff12\uff13")
        ),
    ],
)
def test_elink_groups_map_to_pmc_ids_or_incomplete_by_source_pmid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    paper_ids: list[str],
    groups: list[dict[str, Any]],
    expected_links: dict[str, str | None],
    incomplete: set[str],
) -> None:
    results, trace, _ = _gather(
        monkeypatch,
        tmp_path,
        paper_ids,
        _efetch_reversed,
        lambda **_kwargs: _Handle(groups),
    )

    assert {
        paper_id: results[paper_id]["pmc_full_text_id"]
        for paper_id in expected_links
    } == expected_links
    assert {item["pmid"] for item in trace["fetch_errors"]} == incomplete
    assert all(
        item["stage"].startswith("elink") for item in trace["fetch_errors"]
    )


def test_batching_deduplicates_orders_valid_pmids_and_chunks_at_nine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    efetch_groups: list[list[str]] = []
    elink_groups: list[list[str]] = []

    def efetch(**kwargs: Any) -> _Handle:
        efetch_groups.append(kwargs["id"])
        return _efetch_reversed(**kwargs)

    def elink(**kwargs: Any) -> _Handle:
        elink_groups.append(kwargs["id"])
        return _Handle([{"IdList": [paper_id]} for paper_id in kwargs["id"]])

    paper_ids = [str(value) for value in range(100, 110)]
    request_ids = [
        paper_ids[0],
        "",
        "١٠٣",
        "101,102",
        *paper_ids[1:],
        paper_ids[0],
    ]
    results, trace, shared_dir = _gather(
        monkeypatch, tmp_path, request_ids, efetch, elink
    )

    assert list(results) == paper_ids
    assert efetch_groups == elink_groups == [paper_ids[:9], paper_ids[9:]]
    assert trace["incomplete_fetch_count"] == 3
    assert len(list(shared_dir.glob("*.metadata.json"))) == len(paper_ids)


def test_metadata_cache_is_isolated_by_slug_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    efetch_ids: list[list[str]] = []

    def efetch(**kwargs: Any) -> _Handle:
        efetch_ids.append(kwargs["id"])
        return _efetch_reversed(**kwargs)

    for slug in ("slug-a", "slug-b"):
        _, _, shared_dir = _gather(
            monkeypatch,
            tmp_path,
            ["101"],
            efetch,
            lambda **_kwargs: _Handle([{"IdList": ["101"]}]),
            slug=slug,
            traced=False,
        )
        assert (shared_dir / "101.metadata.json").exists()

    assert efetch_ids == [["101"], ["101"]]
