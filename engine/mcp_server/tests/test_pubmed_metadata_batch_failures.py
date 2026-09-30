"""Failure isolation, bounded batching, and cache behavior tests."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from Bio import Entrez
from mcp_server import entrez_rate_limit
from mcp_server import pubmed_metadata_batch as batch
from mcp_server.pubmed_client import _EntrezClient
from test_pubmed_metadata_batch import (  # type: ignore[import-not-found]
    _article,
    _Handle,
    _install_batch_entrez,
)


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
