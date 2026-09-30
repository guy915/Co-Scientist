"""Offline outcome checks for the maintained PubMed pilot trace."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from Bio import Entrez
from mcp_server import entrez_rate_limit
from mcp_server.tools.lit_review import pubmed_search_with_fulltext as tool
from test_pubmed_pilot_trace import (  # type: ignore[import-not-found]
    _CannedEntrezHandle,
    _fixture_trace_reader,
    _install_fake_entrez,
    _pubmed_article,
    restore_biopython_retry_policy,
)

__all__ = ["restore_biopython_retry_policy"]


def test_trace_marks_metadata_fetch_failures_as_incomplete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The tool distinguishes failed EFetch calls from successful empty data."""
    cache_root = tmp_path / "metadata-errors-cache"
    run_id = "metadata-errors-run"
    build_id = "metadata-errors-build"
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_TRACE", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_BUILD_ID", build_id)
    monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(cache_root))
    monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)

    def fake_esearch(**_kwargs: Any) -> _CannedEntrezHandle:
        return _CannedEntrezHandle({"IdList": ["801", "802", "803"]})

    def failed_efetch(**_kwargs: Any) -> _CannedEntrezHandle:
        raise OSError("fake efetch failure")

    monkeypatch.setattr(Entrez, "esearch", fake_esearch)
    monkeypatch.setattr(Entrez, "efetch", failed_efetch)
    monkeypatch.setattr(Entrez, "read", lambda handle: handle.payload)

    results = asyncio.run(
        tool.pubmed_search_with_fulltext(
            query="controlled fetch failures",
            slug=run_id,
            max_papers=1,
            run_id=run_id,
        )
    )
    trace_path = (
        cache_root / "pubmed" / run_id / "runs" / run_id / ".search-trace.json"
    )
    trace = json.loads(trace_path.read_text(encoding="utf-8"))

    assert results == {}
    assert trace["incomplete_fetch_count"] == 3
    assert trace["entrez_calls"] == {"esearch": 1, "efetch": 3, "elink": 0}
    assert {
        (error["stage"], error["pmid"], error["type"])
        for error in trace["fetch_errors"]
    } == {
        ("metadata_fetch", paper_id, "OSError")
        for paper_id in ("801", "802", "803")
    }
    fetched = {paper["pmid"]: paper for paper in trace["fetched"]}
    assert all(
        not paper["fetched"] and paper["incomplete"]
        for paper in fetched.values()
    )


def test_trace_marks_elink_request_failure_as_incomplete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An ELink transport error differs from a valid no-PMC-link result."""
    cache_root = tmp_path / "elink-errors-cache"
    run_id = "elink-errors-run"
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_TRACE", "1")
    monkeypatch.setenv(
        "COSCIENTIST_PUBMED_PILOT_BUILD_ID", "elink-errors-build"
    )
    monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(cache_root))
    monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)

    def fake_esearch(**_kwargs: Any) -> _CannedEntrezHandle:
        return _CannedEntrezHandle({"IdList": ["811", "812", "813"]})

    def failed_elink(**_kwargs: Any) -> _CannedEntrezHandle:
        raise TimeoutError("fake elink failure")

    monkeypatch.setattr(Entrez, "esearch", fake_esearch)
    monkeypatch.setattr(
        Entrez,
        "efetch",
        lambda **kwargs: _CannedEntrezHandle(
            _pubmed_article(str(kwargs["id"]))
        ),
    )
    monkeypatch.setattr(Entrez, "elink", failed_elink)
    monkeypatch.setattr(Entrez, "read", lambda handle: handle.payload)

    results = asyncio.run(
        tool.pubmed_search_with_fulltext(
            query="controlled ELink failure",
            slug=run_id,
            max_papers=1,
            run_id=run_id,
        )
    )
    trace_path = (
        cache_root / "pubmed" / run_id / "runs" / run_id / ".search-trace.json"
    )
    trace = json.loads(trace_path.read_text(encoding="utf-8"))

    assert list(results) == ["811"]
    assert trace["incomplete_fetch_count"] == 3
    assert trace["entrez_calls"] == {"esearch": 1, "efetch": 3, "elink": 3}
    assert {error["stage"] for error in trace["fetch_errors"]} == {"elink"}
    fetched = {paper["pmid"]: paper for paper in trace["fetched"]}
    assert all(
        paper["fetched"] and paper["incomplete"] for paper in fetched.values()
    )


def test_trace_records_swallowed_pmc_fulltext_request_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed optional PMC request is visible while no-link remains normal."""
    cache_root = tmp_path / "fulltext-errors-cache"
    run_id = "fulltext-errors-run"
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_TRACE", "1")
    monkeypatch.setenv(
        "COSCIENTIST_PUBMED_PILOT_BUILD_ID", "fulltext-errors-build"
    )
    monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(cache_root))
    monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)

    def pubmed_fetch(**kwargs: Any) -> _CannedEntrezHandle:
        return _CannedEntrezHandle(_pubmed_article(str(kwargs["id"])))

    def failed_pmc_fetch(**_kwargs: Any) -> _CannedEntrezHandle:
        raise OSError("fake PMC fulltext failure")

    def fake_elink(**_kwargs: Any) -> _CannedEntrezHandle:
        return _CannedEntrezHandle(
            [{"LinkSetDb": [{"Link": [{"Id": "PMC901"}]}]}]
        )

    monkeypatch.setattr(
        Entrez,
        "esearch",
        lambda **_kwargs: _CannedEntrezHandle(
            {"IdList": ["901", "902", "903"]}
        ),
    )
    monkeypatch.setattr(
        Entrez,
        "efetch",
        lambda **kwargs: {
            "pubmed": pubmed_fetch,
            "pmc": failed_pmc_fetch,
        }[str(kwargs["db"])](**kwargs),
    )
    monkeypatch.setattr(Entrez, "elink", fake_elink)
    monkeypatch.setattr(Entrez, "read", lambda handle: handle.payload)

    asyncio.run(
        tool.pubmed_search_with_fulltext(
            query="controlled PMC fulltext failure",
            slug=run_id,
            max_papers=1,
            run_id=run_id,
        )
    )
    trace_path = (
        cache_root / "pubmed" / run_id / "runs" / run_id / ".search-trace.json"
    )
    trace = json.loads(trace_path.read_text(encoding="utf-8"))

    assert trace["incomplete_fetch_count"] == 1
    assert trace["fetch_errors"] == [
        {"stage": "fulltext", "pmid": "901", "type": "OSError"}
    ]
    assert trace["entrez_calls"] == {"esearch": 1, "efetch": 4, "elink": 3}


def test_prior_pool_supplement_is_recorded_in_run_trace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The trace distinguishes prior shared-pool evidence from search hits."""
    cache_root = tmp_path / "pool-cache"
    run_id = "pool-trace-readiness"
    slug_dir = cache_root / "pubmed" / run_id
    shared_dir = slug_dir / "shared"
    shared_dir.mkdir(parents=True)
    (shared_dir / "999.metadata.json").write_text(
        json.dumps(
            {
                "date_revised": "2023/1/1",
                "title": "Cached paper",
                "abstract": "Cached abstract.",
                "authors": [],
                "publication": "Example Journal",
                "pmc_full_text_id": "PMC999",
            }
        ),
        encoding="utf-8",
    )
    (shared_dir / "PMC999.fulltext.html").write_text(
        "<html><body>Cached full text.</body></html>", encoding="utf-8"
    )
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_TRACE", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_BUILD_ID", "pool-test-build")
    monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(cache_root))
    _install_fake_entrez(monkeypatch, ["401", "402", "403"])

    results = asyncio.run(
        tool.pubmed_search_with_fulltext(
            query="pool supplement provenance",
            slug=run_id,
            max_papers=1,
            run_id=run_id,
        )
    )

    trace_path = slug_dir / "runs" / run_id / ".search-trace.json"
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    evidence = _fixture_trace_reader()(trace_path, run_id, "pool-test-build")
    assert list(results) == ["999"]
    assert trace["pre_search_shared_pool"] == {
        "file_count": 2,
        "metadata_count": 1,
        "first_ids": ["999"],
    }
    assert trace["shared_pool_supplements"] == [
        {
            "pmid": "999",
            "source": "shared_pool",
            "origin": "prior_pool",
            "preexisting": True,
            "matched_esearch_first_ids": False,
        }
    ]
    assert evidence["final_ids"] == ["999"]
    assert (trace_path.parent / ".manifest.json").is_file()


def test_trace_distinguishes_selected_shared_cache_hits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cached selected records explain why no matching Entrez calls occurred."""
    cache_root = tmp_path / "cache-hit-cache"
    run_id = "cache-hit-trace"
    shared_dir = cache_root / "pubmed" / run_id / "shared"
    shared_dir.mkdir(parents=True)
    (shared_dir / "901.metadata.json").write_text(
        json.dumps(
            {
                "date_revised": "2024/1/1",
                "title": "Cached paper",
                "abstract": "Cached abstract.",
                "authors": [],
                "publication": "Example Journal",
                "pmc_full_text_id": "PMC901",
            }
        ),
        encoding="utf-8",
    )
    (shared_dir / "PMC901.fulltext.html").write_text(
        "<html><body>Cached full text.</body></html>", encoding="utf-8"
    )
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_TRACE", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_BUILD_ID", "cache-hit-build")
    monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(cache_root))
    esearch_calls = _install_fake_entrez(monkeypatch, ["901", "902", "903"])

    results = asyncio.run(
        tool.pubmed_search_with_fulltext(
            query="shared metadata cache hit",
            slug=run_id,
            max_papers=1,
            run_id=run_id,
        )
    )

    trace_path = (
        cache_root / "pubmed" / run_id / "runs" / run_id / ".search-trace.json"
    )
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert list(results) == ["901"]
    assert len(esearch_calls) == 1
    assert trace["metadata_origins"] == {
        "901": "shared_pool_cache",
        "902": "entrez_fetch",
        "903": "entrez_fetch",
    }
    assert trace["entrez_calls"] == {"esearch": 1, "efetch": 2, "elink": 2}
    fetched = {paper["pmid"]: paper for paper in trace["fetched"]}
    assert fetched["901"]["metadata_origin"] == "shared_pool_cache"
    assert fetched["901"]["fetched"] is True
    assert fetched["901"]["incomplete"] is False


def test_empty_pubmed_search_records_each_physical_rung(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An empty search has a complete readable trace and no selected rung."""
    cache_root = tmp_path / "empty-cache"
    run_id = "empty-trace-readiness"
    build_id = "empty-test-build"
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_TRACE", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_BUILD_ID", build_id)
    monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(cache_root))
    esearch_calls: list[dict[str, Any]] = []

    def fake_esearch(**kwargs: Any) -> _CannedEntrezHandle:
        esearch_calls.append(kwargs)
        return _CannedEntrezHandle({"IdList": []})

    monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)
    monkeypatch.setattr(Entrez, "esearch", fake_esearch)
    monkeypatch.setattr(Entrez, "read", lambda handle: handle.payload)

    results = asyncio.run(
        tool.pubmed_search_with_fulltext(
            query="alpha beta gamma",
            slug=run_id,
            max_papers=1,
            recency_years=1,
            run_id=run_id,
        )
    )

    trace_path = (
        cache_root / "pubmed" / run_id / "runs" / run_id / ".search-trace.json"
    )
    evidence = _fixture_trace_reader()(trace_path, run_id, build_id)
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert results == {}
    assert len(evidence["attempts"]) == len(esearch_calls) == 4
    assert [item["rung_type"] for item in evidence["attempts"]] == [
        "exact",
        "recency_dropped",
        "anchored",
        "or",
    ]
    assert all(item["operation"] == "esearch" for item in trace["attempts"])
    assert evidence["selected"] is None
    assert evidence["fetched"] == []
    assert evidence["final_ids"] == []
    assert trace["outcome"] == "empty"
    assert trace["error"] is None
    assert trace["entrez_calls"]["esearch"] == len(trace["attempts"]) == 4


def test_pubmed_search_error_writes_bounded_attempt_error_trace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed physical ESearch remains diagnosable through the same reader."""
    cache_root = tmp_path / "error-cache"
    run_id = "error-trace-readiness"
    build_id = "error-test-build"
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_TRACE", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_BUILD_ID", build_id)
    monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(cache_root))

    def failed_esearch(**_kwargs: Any) -> _CannedEntrezHandle:
        raise TimeoutError("fake Entrez timeout")

    monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)
    monkeypatch.setattr(Entrez, "esearch", failed_esearch)

    with pytest.raises(TimeoutError, match="fake Entrez timeout"):
        asyncio.run(
            tool.pubmed_search_with_fulltext(
                query="timeout query",
                slug=run_id,
                max_papers=1,
                run_id=run_id,
            )
        )

    trace_path = (
        cache_root / "pubmed" / run_id / "runs" / run_id / ".search-trace.json"
    )
    evidence = _fixture_trace_reader()(trace_path, run_id, build_id)
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert evidence["attempts"] == [
        {
            "rung_index": 1,
            "rung_type": "exact",
            "count": 0,
            "first_ids": [],
            "sort": "pub_date",
        }
    ]
    assert trace["attempts"][0]["operation"] == "esearch"
    assert trace["attempts"][0]["error_type"] == "TimeoutError"
    assert trace["error"] == {"stage": "esearch", "type": "TimeoutError"}
    assert trace["outcome"] == "error"
    assert trace["selected"] is None
    assert trace["entrez_calls"]["esearch"] == len(trace["attempts"]) == 1
    assert evidence["final_ids"] == []
