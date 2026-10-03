"""Offline readiness checks for the maintained PubMed pilot trace."""

import ast
import asyncio
import json
import threading
from pathlib import Path
from typing import Any

import pytest
from Bio import Entrez
from mcp_server import entrez_rate_limit, pubmed_client
from mcp_server.tools.lit_review import search_pubmed as tool

_DEFAULT_ENTREZ_MAX_TRIES = Entrez.max_tries
_DEFAULT_ENTREZ_SLEEP_BETWEEN_TRIES = Entrez.sleep_between_tries


@pytest.fixture(autouse=True)
def restore_biopython_retry_policy() -> Any:
    """Keep trace-only global settings isolated between offline test cases."""
    yield
    Entrez.max_tries = _DEFAULT_ENTREZ_MAX_TRIES
    Entrez.sleep_between_tries = _DEFAULT_ENTREZ_SLEEP_BETWEEN_TRIES


class _CannedEntrezHandle:
    """Minimal handle matching the shape returned by Bio.Entrez.read."""

    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def close(self) -> None:
        pass


def _fixture_trace_reader() -> Any:
    """Loads the exact stdlib trace reader without its optional engine deps."""
    repo_root = Path(__file__).resolve().parents[3]
    fixture_path = (
        repo_root
        / "references"
        / "external"
        / "sakana"
        / "novelty_fixture_bank_screen.py"
    )
    tree = ast.parse(fixture_path.read_text(encoding="utf-8"))
    trace_reader = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_trace_evidence"
    )
    max_trace_ids = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "MAX_TRACE_IDS"
            for target in node.targets
        )
    )
    nodes: list[ast.stmt] = [max_trace_ids, trace_reader]
    namespace: dict[str, Any] = {"Any": Any, "Path": Path, "json": json}
    compiled = compile(
        ast.Module(body=nodes, type_ignores=[]), str(fixture_path), "exec"
    )
    exec(compiled, namespace)
    return namespace["_trace_evidence"]


def _pubmed_article(paper_id: str) -> dict[str, Any]:
    return {
        "PubmedArticle": [
            {
                "MedlineCitation": {
                    "Article": {
                        "ArticleTitle": f"Paper {paper_id}",
                        "Abstract": {
                            "AbstractText": ["A real-shaped abstract."]
                        },
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


def _install_fake_entrez(
    monkeypatch: pytest.MonkeyPatch, ids: list[str]
) -> list[dict[str, Any]]:
    esearch_calls: list[dict[str, Any]] = []

    def fake_esearch(**kwargs: Any) -> _CannedEntrezHandle:
        esearch_calls.append(kwargs)
        return _CannedEntrezHandle({"IdList": ids})

    def fake_efetch(**kwargs: Any) -> _CannedEntrezHandle:
        return _CannedEntrezHandle(_pubmed_article(str(kwargs["id"])))

    def fake_elink(**_kwargs: Any) -> _CannedEntrezHandle:
        return _CannedEntrezHandle([{"LinkSetDb": []}])

    # Exercise the maintained pacing/counting seam without sleeping.
    monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)
    monkeypatch.setattr(Entrez, "esearch", fake_esearch)
    monkeypatch.setattr(Entrez, "efetch", fake_efetch)
    monkeypatch.setattr(Entrez, "elink", fake_elink)
    monkeypatch.setattr(Entrez, "read", lambda handle: handle.payload)
    return esearch_calls


def test_maintained_pubmed_tool_writes_fixture_readable_trace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The actual tool emits provenance the frozen screen reader accepts."""
    cache_root = tmp_path / "cache"
    slug = "trace_readiness"
    run_id = "offline-trace-readiness"
    build_id = "maintained-test-build"
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_TRACE", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_BUILD_ID", build_id)
    monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(cache_root))

    esearch_calls = _install_fake_entrez(monkeypatch, ["101", "102", "103"])

    results = asyncio.run(
        tool.pubmed_search_with_fulltext(
            query="pubmed trace readiness",
            slug=slug,
            max_papers=1,
            run_id=run_id,
        )
    )

    trace_path = (
        cache_root / "pubmed" / slug / "runs" / run_id / ".search-trace.json"
    )
    evidence = _fixture_trace_reader()(trace_path, run_id, build_id)
    trace = json.loads(trace_path.read_text(encoding="utf-8"))

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
    assert all(
        item["metadata_origin"] == "entrez_fetch" for item in trace["fetched"]
    )
    trace_text = trace_path.read_text(encoding="utf-8")
    assert "A real-shaped abstract." not in trace_text
    assert list(trace_path.parent.glob(".search-trace-*.tmp")) == []
    assert trace_path.stat().st_mode & 0o777 == 0o600


def test_trace_call_fails_closed_if_retry_policy_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No traced Entrez request runs after the process retry setting drifts."""
    monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)
    Entrez.max_tries = 1
    Entrez.sleep_between_tries = 0
    trace: dict[str, Any] = {
        "entrez_calls": {"esearch": 0, "efetch": 0, "elink": 0}
    }
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
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Normal retrieval keeps its output and does not create pilot files."""
    cache_root = tmp_path / "ordinary-cache"
    run_id = "ordinary-trace-readiness"
    retry_policy = (Entrez.max_tries, Entrez.sleep_between_tries)
    monkeypatch.delenv("COSCIENTIST_PUBMED_PILOT_TRACE", raising=False)
    monkeypatch.delenv("COSCIENTIST_PUBMED_PILOT_BUILD_ID", raising=False)
    monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(cache_root))
    esearch_calls = _install_fake_entrez(monkeypatch, ["201", "202", "203"])

    results = asyncio.run(
        tool.pubmed_search_with_fulltext(
            query="ordinary retrieval parity",
            slug=run_id,
            max_papers=1,
            run_id=run_id,
        )
    )

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
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Existing trace identity is rejected before the next search request."""
    cache_root = tmp_path / "reused-cache"
    run_id = "reused-trace-readiness"
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_TRACE", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_BUILD_ID", "reuse-test-build")
    monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(cache_root))
    esearch_calls = _install_fake_entrez(monkeypatch, ["301", "302", "303"])

    asyncio.run(
        tool.pubmed_search_with_fulltext(
            query="first unique trace",
            slug=run_id,
            max_papers=1,
            run_id=run_id,
        )
    )
    esearch_calls.clear()

    with pytest.raises(ValueError, match="trace run_id is not empty"):
        asyncio.run(
            tool.pubmed_search_with_fulltext(
                query="second unique trace",
                slug=run_id,
                max_papers=1,
                run_id=run_id,
            )
        )
    assert esearch_calls == []


def test_nonempty_untraced_run_directory_is_rejected_before_entrez(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Legacy manifests and symlinks cannot be mistaken for fresh pilot runs."""
    cache_root = tmp_path / "dirty-cache"
    run_id = "untraced-existing-run"
    run_dir = cache_root / "pubmed" / run_id / "runs" / run_id
    run_dir.mkdir(parents=True)
    target = tmp_path / "existing-paper.json"
    target.write_text("{}", encoding="utf-8")
    (run_dir / "101.metadata.json").symlink_to(target)
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_TRACE", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_BUILD_ID", "dirty-run-build")
    monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(cache_root))
    esearch_calls = _install_fake_entrez(monkeypatch, ["101"])

    with pytest.raises(ValueError, match="trace run_id is not empty"):
        asyncio.run(
            tool.pubmed_search_with_fulltext(
                query="do not replay an existing run",
                slug=run_id,
                max_papers=1,
                run_id=run_id,
            )
        )

    assert esearch_calls == []
    assert (run_dir / "101.metadata.json").is_symlink()
    assert not (run_dir / ".trace-reservation.json").exists()


def test_failed_trace_run_remains_reserved_before_any_reuse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A failed first search leaves an exclusive, non-reusable run claim."""
    cache_root = tmp_path / "failed-cache"
    run_id = "failed-reserved-run"
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_TRACE", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_BUILD_ID", "failed-run-build")
    monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(cache_root))
    monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)
    calls: list[int] = []

    def failed_esearch(**_kwargs: Any) -> _CannedEntrezHandle:
        calls.append(1)
        raise TimeoutError("offline fake timeout")

    monkeypatch.setattr(Entrez, "esearch", failed_esearch)
    monkeypatch.setattr(Entrez, "read", lambda handle: handle.payload)

    def call() -> Any:
        return asyncio.run(
            tool.pubmed_search_with_fulltext(
                query="one failed request only",
                slug=run_id,
                max_papers=1,
                run_id=run_id,
            )
        )

    with pytest.raises(TimeoutError, match="offline fake timeout"):
        call()
    run_dir = cache_root / "pubmed" / run_id / "runs" / run_id
    assert (run_dir / ".trace-reservation.json").is_file()
    assert (run_dir / ".search-trace.json").is_file()
    with pytest.raises(ValueError, match="trace run_id is not empty"):
        call()
    assert len(calls) == 1


def test_concurrent_trace_run_id_has_one_search_owner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Only one concurrent call can reserve the run before its ESearch."""
    cache_root = tmp_path / "concurrent-cache"
    run_id = "concurrent-reserved-run"
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_TRACE", "1")
    monkeypatch.setenv("COSCIENTIST_PUBMED_PILOT_BUILD_ID", "concurrent-build")
    monkeypatch.setenv("COSCIENTIST_LIT_REVIEW_DIR", str(cache_root))
    monkeypatch.setattr(entrez_rate_limit, "_await_slot", lambda: None)
    entered_search = threading.Event()
    release_search = threading.Event()
    calls: list[int] = []

    def blocked_esearch(**_kwargs: Any) -> _CannedEntrezHandle:
        calls.append(1)
        entered_search.set()
        if not release_search.wait(timeout=5):
            raise TimeoutError("test did not release first search")
        return _CannedEntrezHandle({"IdList": ["701", "702", "703"]})

    monkeypatch.setattr(Entrez, "esearch", blocked_esearch)
    monkeypatch.setattr(
        Entrez,
        "efetch",
        lambda **kwargs: _CannedEntrezHandle(
            _pubmed_article(str(kwargs["id"]))
        ),
    )
    monkeypatch.setattr(
        Entrez,
        "elink",
        lambda **_kwargs: _CannedEntrezHandle([{"LinkSetDb": []}]),
    )
    monkeypatch.setattr(Entrez, "read", lambda handle: handle.payload)
    failures: list[Exception] = []

    def run_first() -> None:
        try:
            asyncio.run(
                tool.pubmed_search_with_fulltext(
                    query="first owner",
                    slug=run_id,
                    max_papers=1,
                    run_id=run_id,
                )
            )
        except Exception as exc:
            failures.append(exc)

    first = threading.Thread(target=run_first)
    first.start()
    assert entered_search.wait(timeout=5)
    try:
        with pytest.raises(ValueError, match="trace run_id is not empty"):
            asyncio.run(
                tool.pubmed_search_with_fulltext(
                    query="concurrent duplicate",
                    slug=run_id,
                    max_papers=1,
                    run_id=run_id,
                )
            )
    finally:
        release_search.set()
        first.join(timeout=5)

    assert not first.is_alive()
    assert failures == []
    assert len(calls) == 1
