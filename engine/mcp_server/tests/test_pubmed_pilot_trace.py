import json
import threading
from pathlib import Path
from typing import Any

import mcp_server.entrez as entrez_rate_limit
import pytest
from Bio import Entrez
from mcp_server import pubmed_client
from mcp_server.tests._entrez import CannedEntrezHandle as _CannedEntrezHandle
from mcp_server.tests._entrez import (
    configure_trace,
    efetch_article,
    elink_without_pmc,
    esearch_ids,
    install_entrez,
    raising,
    read_trace,
    search,
    seed_shared_pool,
    trace_path,
)
from mcp_server.tests._entrez import install_fake_entrez as _install_fake_entrez
from mcp_server.tests._trace import _trace_evidence

_DEFAULT_ENTREZ_MAX_TRIES = Entrez.max_tries
_DEFAULT_ENTREZ_SLEEP_BETWEEN_TRIES = Entrez.sleep_between_tries


@pytest.fixture
def restore_biopython_retry_policy() -> Any:
    """Trace calls change Biopython's process-wide retry settings."""
    yield
    Entrez.max_tries = _DEFAULT_ENTREZ_MAX_TRIES
    Entrez.sleep_between_tries = _DEFAULT_ENTREZ_SLEEP_BETWEEN_TRIES


@pytest.mark.usefixtures("restore_biopython_retry_policy")
class TestPubmedPilotTrace:
    def test_maintained_pubmed_tool_writes_fixture_readable_trace(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cache_root = tmp_path / "cache"
        slug = "trace_readiness"
        run_id = "offline-trace-readiness"
        build_id = "maintained-test-build"
        configure_trace(monkeypatch, cache_root, build_id, free_models=True)

        esearch_calls = _install_fake_entrez(monkeypatch, ["101", "102", "103"])

        results = search("pubmed trace readiness", run_id, slug=slug)

        trace_file = trace_path(cache_root, slug, run_id)
        evidence = _trace_evidence(trace_file, run_id, build_id)
        trace = json.loads(trace_file.read_text(encoding="utf-8"))

        assert list(results) == ["101"]
        assert len(esearch_calls) == 1
        assert evidence["run_id"] == run_id
        assert evidence["server_build_id"] == build_id
        assert evidence["attempts"] == [
            {
                "rung_index": 1,
                "rung_type": "exact",
                "count": 3,
                "first_ids": ["101", "102", "103"],
                "sort": "pub_date",
            }
        ]
        assert evidence["selected"]["ids"] == ["101", "102", "103"]
        assert evidence["fetched"] == [
            {
                "pmid": paper_id,
                "fetched": True,
                "pmc_available": False,
                "abstract_available": True,
            }
            for paper_id in ("101", "102", "103")
        ]
        assert evidence["final_ids"] == ["101"]
        assert trace["source_file"] == str(Path(pubmed_client.__file__).resolve())
        assert trace["process_id"] > 0
        assert trace["entrez_retry_policy"] == {
            "max_tries": 1,
            "sleep_between_tries": 0,
        }
        assert trace["entrez_calls"] == {"esearch": 1, "efetch": 3, "elink": 3}
        assert trace["metadata_origins"] == {
            "101": "entrez_fetch",
            "102": "entrez_fetch",
            "103": "entrez_fetch",
        }
        assert all(item["metadata_origin"] == "entrez_fetch" for item in trace["fetched"])
        trace_text = trace_file.read_text(encoding="utf-8")
        assert "A real-shaped abstract." not in trace_text
        assert list(trace_file.parent.glob(".search-trace-*.tmp")) == []
        assert trace_file.stat().st_mode & 0o777 == 0o600

    def test_trace_call_fails_closed_if_retry_policy_changes(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)
        Entrez.max_tries = 1
        Entrez.sleep_between_tries = 0
        trace: dict[str, Any] = {"entrez_calls": {"esearch": 0, "efetch": 0, "elink": 0}}
        request_called = False

        def fake_esearch(**_kwargs: Any) -> _CannedEntrezHandle:
            nonlocal request_called
            request_called = True
            return _CannedEntrezHandle({"IdList": []})

        with entrez_rate_limit.pilot_trace_context(trace):
            Entrez.max_tries = 3
            with pytest.raises(RuntimeError, match="retry policy changed"):
                entrez_rate_limit.entrez_call(fake_esearch)

        assert not request_called
        assert trace["entrez_calls"] == {"esearch": 0, "efetch": 0, "elink": 0}

    def test_trace_disabled_tool_keeps_results_without_trace_artifact(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cache_root = tmp_path / "ordinary-cache"
        run_id = "ordinary-trace-readiness"
        retry_policy = (Entrez.max_tries, Entrez.sleep_between_tries)
        monkeypatch.delenv("COSCIENTIST_PUBMED_PILOT_TRACE", raising=False)
        monkeypatch.delenv("COSCIENTIST_PUBMED_PILOT_BUILD_ID", raising=False)
        monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(cache_root))
        esearch_calls = _install_fake_entrez(monkeypatch, ["201", "202", "203"])

        results = search("ordinary retrieval parity", run_id)

        run_dir = cache_root / "pubmed" / run_id / "runs" / run_id
        assert list(results) == ["201"]
        assert esearch_calls == [
            {
                "db": "pubmed",
                "term": "ordinary retrieval parity",
                "retmax": 3,
                "sort": "pub_date",
            }
        ]
        assert (run_dir / ".manifest.json").is_file()
        assert not (run_dir / ".search-trace.json").exists()
        assert (Entrez.max_tries, Entrez.sleep_between_tries) == retry_policy

    def test_reused_trace_run_id_is_rejected_before_entrez(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cache_root = tmp_path / "reused-cache"
        run_id = "reused-trace-readiness"
        configure_trace(monkeypatch, cache_root, "reuse-test-build")
        esearch_calls = _install_fake_entrez(monkeypatch, ["301", "302", "303"])

        search("first unique trace", run_id)
        esearch_calls.clear()

        with pytest.raises(ValueError, match="trace run_id is not empty"):
            search("second unique trace", run_id)
        assert esearch_calls == []

    def test_nonempty_untraced_run_directory_is_rejected_before_entrez(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Pre-trace manifests and symlinks are not fresh pilot runs."""
        cache_root = tmp_path / "dirty-cache"
        run_id = "untraced-existing-run"
        run_dir = cache_root / "pubmed" / run_id / "runs" / run_id
        run_dir.mkdir(parents=True)
        target = tmp_path / "existing-paper.json"
        target.write_text("{}", encoding="utf-8")
        (run_dir / "101.metadata.json").symlink_to(target)
        configure_trace(monkeypatch, cache_root, "dirty-run-build")
        esearch_calls = _install_fake_entrez(monkeypatch, ["101"])

        with pytest.raises(ValueError, match="trace run_id is not empty"):
            search("do not replay an existing run", run_id)

        assert esearch_calls == []
        assert (run_dir / "101.metadata.json").is_symlink()
        assert not (run_dir / ".trace-reservation.json").exists()

    def test_failed_trace_run_remains_reserved_before_any_reuse(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cache_root = tmp_path / "failed-cache"
        run_id = "failed-reserved-run"
        configure_trace(monkeypatch, cache_root, "failed-run-build")
        calls: list[int] = []

        def failed_esearch(**_kwargs: Any) -> _CannedEntrezHandle:
            calls.append(1)
            raise TimeoutError("offline fake timeout")

        install_entrez(monkeypatch, esearch=failed_esearch)

        def call() -> Any:
            return search("one failed request only", run_id)

        with pytest.raises(TimeoutError, match="offline fake timeout"):
            call()
        run_dir = cache_root / "pubmed" / run_id / "runs" / run_id
        assert (run_dir / ".trace-reservation.json").is_file()
        assert (run_dir / ".search-trace.json").is_file()
        with pytest.raises(ValueError, match="trace run_id is not empty"):
            call()
        assert len(calls) == 1

    def test_concurrent_trace_run_id_has_one_search_owner(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cache_root = tmp_path / "concurrent-cache"
        run_id = "concurrent-reserved-run"
        configure_trace(monkeypatch, cache_root, "concurrent-build")
        entered_search = threading.Event()
        release_search = threading.Event()
        calls: list[int] = []

        def blocked_esearch(**_kwargs: Any) -> _CannedEntrezHandle:
            calls.append(1)
            entered_search.set()
            if not release_search.wait(timeout=5):
                raise TimeoutError("test did not release first search")
            return _CannedEntrezHandle({"IdList": ["701", "702", "703"]})

        install_entrez(
            monkeypatch,
            esearch=blocked_esearch,
            efetch=efetch_article,
            elink=elink_without_pmc,
        )
        failures: list[Exception] = []

        def run_first() -> None:
            try:
                search("first owner", run_id)
            except Exception as exc:
                failures.append(exc)

        first = threading.Thread(target=run_first)
        first.start()
        assert entered_search.wait(timeout=5)
        try:
            with pytest.raises(ValueError, match="trace run_id is not empty"):
                search("concurrent duplicate", run_id)
        finally:
            release_search.set()
            first.join(timeout=5)

        assert not first.is_alive()
        assert failures == []
        assert len(calls) == 1


@pytest.mark.usefixtures("restore_biopython_retry_policy")
class TestPubmedPilotTraceOutcomes:
    def test_trace_marks_metadata_fetch_failures_as_incomplete(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cache_root = tmp_path / "metadata-errors-cache"
        run_id = "metadata-errors-run"
        build_id = "metadata-errors-build"
        configure_trace(monkeypatch, cache_root, build_id, free_models=True)

        install_entrez(
            monkeypatch,
            esearch=esearch_ids("801", "802", "803"),
            efetch=raising(OSError("fake efetch failure")),
        )

        results = search("controlled fetch failures", run_id)
        trace = read_trace(cache_root, run_id, run_id)

        assert results == {}
        assert trace["incomplete_fetch_count"] == 3
        assert trace["entrez_calls"] == {"esearch": 1, "efetch": 3, "elink": 0}
        assert {
            (error["stage"], error["pmid"], error["type"]) for error in trace["fetch_errors"]
        } == {("metadata_fetch", paper_id, "OSError") for paper_id in ("801", "802", "803")}
        fetched = {paper["pmid"]: paper for paper in trace["fetched"]}
        assert all(not paper["fetched"] and paper["incomplete"] for paper in fetched.values())

    def test_trace_marks_elink_request_failure_as_incomplete(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Only a successful ELink response can prove PMC text is absent."""
        cache_root = tmp_path / "elink-errors-cache"
        run_id = "elink-errors-run"
        configure_trace(monkeypatch, cache_root, "elink-errors-build", free_models=True)

        install_entrez(
            monkeypatch,
            esearch=esearch_ids("811", "812", "813"),
            efetch=efetch_article,
            elink=raising(TimeoutError("fake elink failure")),
        )

        results = search("controlled ELink failure", run_id)
        trace = read_trace(cache_root, run_id, run_id)

        assert list(results) == ["811"]
        assert trace["incomplete_fetch_count"] == 3
        assert trace["entrez_calls"] == {"esearch": 1, "efetch": 3, "elink": 3}
        assert {error["stage"] for error in trace["fetch_errors"]} == {"elink"}
        fetched = {paper["pmid"]: paper for paper in trace["fetched"]}
        assert all(paper["fetched"] and paper["incomplete"] for paper in fetched.values())

    def test_trace_records_swallowed_pmc_fulltext_request_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cache_root = tmp_path / "fulltext-errors-cache"
        run_id = "fulltext-errors-run"
        configure_trace(monkeypatch, cache_root, "fulltext-errors-build", free_models=True)

        failed_pmc_fetch = raising(OSError("fake PMC fulltext failure"))

        install_entrez(
            monkeypatch,
            esearch=esearch_ids("901", "902", "903"),
            efetch=lambda **kwargs: {
                "pubmed": efetch_article,
                "pmc": failed_pmc_fetch,
            }[str(kwargs["db"])](**kwargs),
            elink=lambda **_kwargs: _CannedEntrezHandle(
                [{"LinkSetDb": [{"Link": [{"Id": "PMC901"}]}]}]
            ),
        )

        search("controlled PMC fulltext failure", run_id)
        trace = read_trace(cache_root, run_id, run_id)

        assert trace["incomplete_fetch_count"] == 1
        assert trace["fetch_errors"] == [{"stage": "fulltext", "pmid": "901", "type": "OSError"}]
        assert trace["entrez_calls"] == {"esearch": 1, "efetch": 4, "elink": 3}

    def test_prior_pool_supplement_is_recorded_in_run_trace(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cache_root = tmp_path / "pool-cache"
        run_id = "pool-trace-readiness"
        seed_shared_pool(cache_root, run_id, "999")
        configure_trace(monkeypatch, cache_root, "pool-test-build", free_models=True)
        _install_fake_entrez(monkeypatch, ["401", "402", "403"])

        results = search("pool supplement provenance", run_id)

        trace_file = trace_path(cache_root, run_id, run_id)
        trace = read_trace(cache_root, run_id, run_id)
        evidence = _trace_evidence(trace_file, run_id, "pool-test-build")
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
        assert (trace_file.parent / ".manifest.json").is_file()

    def test_trace_distinguishes_selected_shared_cache_hits(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cache_root = tmp_path / "cache-hit-cache"
        run_id = "cache-hit-trace"
        seed_shared_pool(cache_root, run_id, "901")
        configure_trace(monkeypatch, cache_root, "cache-hit-build", free_models=True)
        esearch_calls = _install_fake_entrez(monkeypatch, ["901", "902", "903"])

        results = search("shared metadata cache hit", run_id)

        trace = read_trace(cache_root, run_id, run_id)
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
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cache_root = tmp_path / "empty-cache"
        run_id = "empty-trace-readiness"
        build_id = "empty-test-build"
        configure_trace(monkeypatch, cache_root, build_id, free_models=True)
        esearch_calls: list[dict[str, Any]] = []

        def fake_esearch(**kwargs: Any) -> _CannedEntrezHandle:
            esearch_calls.append(kwargs)
            return _CannedEntrezHandle({"IdList": []})

        install_entrez(monkeypatch, esearch=fake_esearch)

        results = search("alpha beta gamma", run_id, recency_years=1)

        trace_file = trace_path(cache_root, run_id, run_id)
        evidence = _trace_evidence(trace_file, run_id, build_id)
        trace = read_trace(cache_root, run_id, run_id)
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
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cache_root = tmp_path / "error-cache"
        run_id = "error-trace-readiness"
        build_id = "error-test-build"
        configure_trace(monkeypatch, cache_root, build_id, free_models=True)

        install_entrez(monkeypatch, esearch=raising(TimeoutError("fake Entrez timeout")))

        with pytest.raises(TimeoutError, match="fake Entrez timeout"):
            search("timeout query", run_id)

        trace_file = trace_path(cache_root, run_id, run_id)
        evidence = _trace_evidence(trace_file, run_id, build_id)
        trace = read_trace(cache_root, run_id, run_id)
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
