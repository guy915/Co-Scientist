"""Offline boundary tests for the preregistered validator fixture screen."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import novelty_fixture_bank_screen as screen
from co_scientist.config.registry import ToolRegistry


class FakeMCPClient:
    def __init__(
        self,
        cache_root: Path,
        *,
        fail_on_call: int | None = None,
        payload_error_on_call: int | None = None,
    ) -> None:
        self.cache_root = cache_root
        self.fail_on_call = fail_on_call
        self.payload_error_on_call = payload_error_on_call
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.last_response: str | None = None

    async def call_tool(self, tool_name: str, **params: object) -> str:
        self.calls.append((tool_name, params))
        if len(self.calls) == self.fail_on_call:
            error = RuntimeError("HTTP 429")
            error.status_code = 429  # type: ignore[attr-defined]
            error.headers = {"Retry-After": "17"}  # type: ignore[attr-defined]
            raise error
        if len(self.calls) == self.payload_error_on_call:
            self.last_response = json.dumps(
                {"error": "HTTP 429", "status": 429, "retry_after": "23"}
            )
            return self.last_response

        run_id = str(params["run_id"])
        slug = str(params["slug"])
        paper_id = str(90000 + len(self.calls))
        self.last_response = json.dumps(
            {
                paper_id: {
                    "title": "Offline fixture response",
                    "authors": ["Example Author"],
                    "date_revised": "2024/1/1",
                    "abstract": f"Private abstract {paper_id}.",
                    "fulltext": f"Private full text {paper_id}.",
                    "doi": "10.0000/example",
                    "pmc_full_text_id": None,
                }
            }
        )
        trace_path = (
            self.cache_root / "pubmed" / slug / "runs" / run_id / ".search-trace.json"
        )
        trace_path.parent.mkdir(parents=True)
        trace_path.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "server_build_id": "offline-build",
                    "sort": "pub_date",
                    "source_file": "/private/path/that/must/not/escape.json",
                    "attempts": [
                        {
                            "rung_index": 1,
                            "rung_type": "exact",
                            "count": 1,
                            "first_ids": [paper_id],
                            "sort": "pub_date",
                        }
                    ],
                    "selected": {
                        "rung_index": 1,
                        "rung_type": "exact",
                        "count": 1,
                        "ids": [paper_id],
                        "sort": "pub_date",
                    },
                    "fetched": [
                        {
                            "pmid": paper_id,
                            "fetched": True,
                            "pmc_available": False,
                            "abstract_available": True,
                        }
                    ],
                    "final_ids": [paper_id],
                    "shared_pool_supplements": [],
                }
            ),
            encoding="utf-8",
        )
        return self.last_response


def _registry() -> ToolRegistry:
    return ToolRegistry(
        config_path=str(screen.ROOT / screen.TOOL_CONFIG),
        skip_user_config=True,
    )


def _no_wait(_: float) -> asyncio.Future[None]:
    future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    future.set_result(None)
    return future


def test_full_validator_boundary_and_blinded_abstract_output(tmp_path: Path) -> None:
    prereg = json.loads(screen.PREREG.read_text(encoding="utf-8"))
    cache = tmp_path / "cache"
    cache.mkdir()
    result = tmp_path / "screen.json"
    private = tmp_path / "private-abstracts.json"
    client = FakeMCPClient(cache)

    report = asyncio.run(
        screen._screen(
            prereg,
            _registry(),
            client,
            cache,
            result,
            private,
            expected_build_id="offline-build",
            sleep=_no_wait,
        )
    )

    expected_drafts = [
        draft["draft"]
        for pair in prereg["cases_in_fixed_order"]
        for draft in (pair["positive"], pair["distinct_control"])
    ]
    assert len(client.calls) == 12
    assert [name for name, _ in client.calls] == ["pubmed_search_with_fulltext"] * 12
    assert report["prereg_sha256"] == screen.EXPECTED_PREREG_SHA256
    assert [params["query"] for _, params in client.calls] == [
        draft[:200] for draft in expected_drafts
    ]
    assert all(params["max_papers"] == 3 for _, params in client.calls)
    assert len({params["slug"] for _, params in client.calls}) == 12
    assert all(
        params["slug"].startswith("m11_nov_01a3b2_") for _, params in client.calls
    )
    assert [params["run_id"] for _, params in client.calls] == [
        params["slug"] for _, params in client.calls
    ]
    assert report["model_inference_calls"] == 0
    assert "source_file" not in json.dumps(report)
    assert "Private abstract" not in result.read_text(encoding="utf-8")
    packet = json.loads(private.read_text(encoding="utf-8"))
    assert len(packet["items"]) == 12
    assert "Private abstract" in json.dumps(packet)
    assert all("case_id" not in item and "pmid" not in item for item in packet["items"])


def test_first_429_stops_screen_and_preserves_retry_after(tmp_path: Path) -> None:
    prereg = json.loads(screen.PREREG.read_text(encoding="utf-8"))
    cache = tmp_path / "cache"
    cache.mkdir()
    result = tmp_path / "screen.json"
    private = tmp_path / "private-abstracts.json"
    client = FakeMCPClient(cache, fail_on_call=2)

    report = asyncio.run(
        screen._screen(
            prereg,
            _registry(),
            client,
            cache,
            result,
            private,
            expected_build_id="offline-build",
            sleep=_no_wait,
        )
    )

    assert len(client.calls) == 2
    assert report["status"] == "INCOMPLETE_RATE_LIMIT"
    failed = report["calls"][-1]
    assert failed["upstream_http_status"] == 429
    assert failed["retry_after"] == "17"
    assert failed["papers"] == []
    assert len(json.loads(result.read_text(encoding="utf-8"))["calls"]) == 2


def test_admission_rejects_ambient_provider_credentials() -> None:
    with pytest.raises(ValueError, match="credential-free"):
        screen._check_environment(
            {
                "COSCIENTIST_REQUIRE_FREE_MODELS": "1",
                "OPENROUTER_API_KEY": "test-only",
            }
        )


def test_server_tree_rejects_modified_or_untracked_source(monkeypatch) -> None:
    monkeypatch.setattr(
        screen,
        "_git",
        lambda *args: (
            " M engine/mcp_server/server.py" if args[:1] == ("status",) else ""
        ),
    )
    with pytest.raises(ValueError, match="dirty or untracked"):
        screen._check_server_tree_clean()


def test_json_429_stops_and_preserves_retry_after(tmp_path: Path) -> None:
    prereg = json.loads(screen.PREREG.read_text(encoding="utf-8"))
    cache = tmp_path / "cache"
    cache.mkdir()
    result = tmp_path / "screen.json"
    private = tmp_path / "private-abstracts.json"
    client = FakeMCPClient(cache, payload_error_on_call=1)

    report = asyncio.run(
        screen._screen(
            prereg,
            _registry(),
            client,
            cache,
            result,
            private,
            expected_build_id="offline-build",
            sleep=_no_wait,
        )
    )

    assert len(client.calls) == 1
    assert report["status"] == "INCOMPLETE_RATE_LIMIT"
    assert report["calls"][0]["upstream_http_status"] == 429
    assert report["calls"][0]["retry_after"] == "23"


def test_bank_version_selector_keeps_v1_as_default() -> None:
    assert screen._parse_args([]).bank_version == 1
    assert screen._parse_args(["--bank-version", "2"]).bank_version == 2


def test_v2_preregistration_hash_and_status_are_frozen(
    tmp_path: Path, monkeypatch
) -> None:
    bank = screen._bank_config(2)
    prereg = screen._load_preregistration(2)
    cache = tmp_path / "cache"
    cache.mkdir()

    assert bank["path"].name == "novelty-fixture-bank-prereg-v2.json"
    assert bank["sha256"] == (
        "a1b1df652f7c8beb4dfc070f88e1986f555e1d61b9027470086a0508432453ca"
    )
    assert screen._sha256(bank["path"]) == bank["sha256"]
    assert prereg["status"] == "PREREGISTERED_BEFORE_ANY_V2_VALIDATOR_SCREEN"
    assert screen._check_prereg(prereg, cache_root=cache, bank_version=2)

    changed = tmp_path / "changed-prereg.json"
    changed.write_bytes(bank["path"].read_bytes() + b"\n")
    original_path = bank["path"]
    monkeypatch.setitem(screen.BANKS[2], "path", changed)
    with pytest.raises(ValueError, match="hash changed"):
        screen._load_preregistration(2)
    monkeypatch.setitem(screen.BANKS[2], "path", original_path)

    prereg["status"] = "PREREGISTERED_BEFORE_ANY_VALIDATOR_SCREEN"
    with pytest.raises(ValueError, match="not preregistered"):
        screen._check_prereg(prereg, cache_root=cache, bank_version=2)


def test_v2_runs_the_frozen_twelve_calls_with_distinct_namespaces(
    tmp_path: Path,
) -> None:
    prereg = screen._load_preregistration(2)
    cache = tmp_path / "cache"
    cache.mkdir()
    result, private = screen._new_output_paths(
        2, result_dir=tmp_path, private_dir=tmp_path
    )
    next_result, next_private = screen._new_output_paths(
        2, result_dir=tmp_path, private_dir=tmp_path
    )
    client = FakeMCPClient(cache)

    report = asyncio.run(
        screen._screen(
            prereg,
            _registry(),
            client,
            cache,
            result,
            private,
            expected_build_id="offline-build",
            sleep=_no_wait,
            bank_version=2,
        )
    )

    slugs = [params["slug"] for _, params in client.calls]
    assert result.name.startswith("novelty-fixture-bank-screen-results-v2-")
    assert private.name.startswith("cosci-m11-nov-01a3b2-v2-labels-")
    assert result != next_result and private != next_private
    assert len(client.calls) == 12
    assert len(set(slugs)) == 12
    assert all(slug.startswith("m11_nov_01a3b2_v2_") for slug in slugs)
    assert [params["run_id"] for _, params in client.calls] == slugs
    assert report["prereg_sha256"] == screen._bank_config(2)["sha256"]
    assert report["status"] == "SCREEN_COMPLETE_LABELS_PENDING"
