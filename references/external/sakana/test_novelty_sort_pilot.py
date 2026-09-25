"""Offline tests for the frozen sort-pilot command boundary."""

from __future__ import annotations

import os
import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

import novelty_sort_pilot as pilot


@pytest.fixture(autouse=True)
def isolated_build_receipt(monkeypatch, tmp_path):
    root = tmp_path / "builds"
    files = {}
    for arm, sort in pilot.EXPECTED_SORT.items():
        source = root / arm / "engine/mcp_server"
        source.mkdir(parents=True)
        (source / "pubmed_client.py").write_text(
            f'PUBMED_SEARCH_SORT = "{sort}"\n', encoding="utf-8"
        )
        (source / "entrez.py").write_text("UNCHANGED = True\n", encoding="utf-8")
        files[arm] = source

    def digest(source):
        sha = hashlib.sha256()
        for path in sorted(p for p in source.rglob("*") if p.is_file()):
            sha.update(str(path.relative_to(source)).encode())
            sha.update(b"\0")
            sha.update(path.read_bytes())
            sha.update(b"\0")
        return sha.hexdigest()

    receipt = tmp_path / "builds.json"
    receipt.write_text(
        json.dumps(
            {
                "build_root": str(root),
                "source_commit": "a" * 40,
                "baseline_build_id": digest(files["baseline"]),
                "candidate_build_id": digest(files["candidate"]),
                "sole_modified_file": "pubmed_client.py",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(pilot, "BUILD_RECEIPT", receipt, raising=False)
    monkeypatch.setattr(
        pilot,
        "BUILD_RECEIPT_SHA256",
        hashlib.sha256(receipt.read_bytes()).hexdigest(),
        raising=False,
    )
    monkeypatch.setattr(pilot, "EXPECTED_SOURCE_COMMIT", "a" * 40, raising=False)
    original_run = subprocess.run

    def listener(command, **kwargs):
        if command[0] != "lsof":
            return original_run(command, **kwargs)
        port = 8898 if "-iTCP:8898" in command else 8899
        return subprocess.CompletedProcess(
            command, 0, f"p{port + 10000}\nn127.0.0.1:{port}\n", ""
        )

    monkeypatch.setattr(subprocess, "run", listener)
    return receipt


def test_frozen_queries_match_the_pinned_subject_first_builder():
    source = subprocess.run(
        [
            "git",
            "show",
            "dd61ae99:engine/src/co_scientist/agents/generation/literature_tools/validate_search.py",
        ],
        cwd=pilot.ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert hashlib.sha256(source.encode()).hexdigest() == (
        "9b2a2838e57fb059733ca9a989d7622aa77d6f7ab0e1019c6267bae94214bee0"
    )
    tree = ast.parse(source)
    constants = {
        "_SEARCH_QUERY_MAX_LENGTH",
        "_SEARCH_QUERY_TOKEN",
        "_SEARCH_QUERY_STOPWORDS",
    }
    body = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "_build_novelty_search_query"
        )
        or (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id in constants
                for target in node.targets
            )
        )
    ]
    namespace = {"re": re}
    exec(
        compile(ast.Module(body=body, type_ignores=[]), "pinned-builder", "exec"),
        namespace,
    )
    recovery = json.loads(pilot.RECOVERY.read_text(encoding="utf-8"))
    positives = {item["case_id"]: item for item in recovery["calls"]}
    fixture = json.loads(pilot.FIXTURE.read_text(encoding="utf-8"))
    controls = {item["id"]: item for item in fixture["distinct_idea_controls"]}
    paired_targets = {"stmn2": "30643298", "sars": "32142651", "qa1b": "36151395"}
    for case in pilot.CASES:
        if case.kind == "positive":
            source_case = positives[case.case_id]
            draft = source_case["raw_draft"]
            assert source_case["wire_query"] == case.query
            assert source_case["target_pmid"] == case.target_pmid
        else:
            draft = controls[case.case_id]["draft"]
            assert (
                controls[case.case_id]["control_source"]["pmid"] == case.own_anchor_pmid
            )
            assert case.target_pmid == paired_targets[case.pair]
        assert draft == case.draft
        assert namespace["_build_novelty_search_query"](draft) == case.query


def _clear_credentials(monkeypatch) -> None:
    suffixes = (
        "_API_KEY",
        "_TOKEN",
        "_SECRET",
        "_ACCESS_KEY",
        "_PASSWORD",
        "_PRIVATE_KEY",
    )
    for name in os.environ:
        if name.endswith(suffixes) and name != "COSCIENTIST_MCP_SHARED_SECRET":
            monkeypatch.delenv(name, raising=False)


def _argv(
    baseline_cache: Path,
    candidate_cache: Path,
    output: Path,
) -> list[str]:
    receipt = json.loads(pilot.BUILD_RECEIPT.read_text(encoding="utf-8"))
    return [
        "--baseline-url",
        "http://127.0.0.1:8898/mcp",
        "--candidate-url",
        "http://127.0.0.1:8899/mcp",
        "--baseline-cache",
        str(baseline_cache),
        "--candidate-cache",
        str(candidate_cache),
        "--baseline-build-id",
        receipt["baseline_build_id"],
        "--candidate-build-id",
        receipt["candidate_build_id"],
        "--baseline-pid",
        "18898",
        "--candidate-pid",
        "18899",
        "--output",
        str(output),
    ]


def test_cli_rejects_provider_credentials_before_connecting(
    monkeypatch, tmp_path, capsys
):
    _clear_credentials(monkeypatch)
    baseline_cache = tmp_path / "baseline"
    candidate_cache = tmp_path / "candidate"
    baseline_cache.mkdir()
    candidate_cache.mkdir()
    output = tmp_path / "result.json"
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("COSCIENTIST_MCP_SHARED_SECRET", "s" * 40)
    monkeypatch.setenv("OPENROUTER_API_KEY", "must-not-be-read")

    def client_must_not_be_created(*args, **kwargs):
        raise AssertionError("credential admission must precede MCP access")

    monkeypatch.setattr(pilot, "MCPToolClient", client_must_not_be_created)

    status = pilot.main(_argv(baseline_cache, candidate_cache, output))

    assert status != 0
    assert not output.exists()
    assert "OPENROUTER_API_KEY" in capsys.readouterr().err


@pytest.mark.parametrize("alter", ["source", "receipt", "receipt-metadata", "pid"])
def test_preflight_rejects_unattested_servers_before_connecting(
    monkeypatch, tmp_path, alter
):
    _clear_credentials(monkeypatch)
    baseline_cache = tmp_path / "baseline"
    candidate_cache = tmp_path / "candidate"
    baseline_cache.mkdir()
    candidate_cache.mkdir()
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("COSCIENTIST_MCP_SHARED_SECRET", "s" * 40)
    argv = _argv(baseline_cache, candidate_cache, tmp_path / "result.json")
    receipt = json.loads(pilot.BUILD_RECEIPT.read_text(encoding="utf-8"))
    if alter == "source":
        source = Path(receipt["build_root"]) / "candidate/engine/mcp_server/entrez.py"
        source.write_text("CHANGED = True\n", encoding="utf-8")
    elif alter == "receipt":
        receipt["candidate_build_id"] = "f" * 64
        pilot.BUILD_RECEIPT.write_text(json.dumps(receipt), encoding="utf-8")
    elif alter == "receipt-metadata":
        receipt["note"] = "tampered"
        pilot.BUILD_RECEIPT.write_text(json.dumps(receipt), encoding="utf-8")
    else:
        argv[argv.index("--candidate-pid") + 1] = "1"
    monkeypatch.setattr(pilot, "MCPToolClient", lambda *_: pytest.fail("connected"))

    assert pilot.main(argv) != 0
    assert not (tmp_path / "result.json").exists()


def test_listener_rejects_non_loopback_even_with_expected_pid(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, "p18898\nn*:8898\n", ""
        ),
    )
    with pytest.raises(ValueError, match="loopback"):
        pilot._listening_pid(8898)


def test_trace_rejects_wrong_server_identity_or_carryover(tmp_path):
    receipt = json.loads(pilot.BUILD_RECEIPT.read_text(encoding="utf-8"))
    arm = pilot.Arm(
        "baseline",
        "http://127.0.0.1:8898/mcp",
        tmp_path,
        receipt["baseline_build_id"],
        "pub_date",
        8898,
        18898,
        Path(receipt["build_root"]) / "baseline/engine/mcp_server/pubmed_client.py",
    )
    valid = {
        "run_id": "run",
        "server_build_id": arm.build_id,
        "process_id": arm.pid,
        "source_file": str(arm.source_file),
        "sort": arm.sort,
        "attempts": [
            {
                "rung_index": 0,
                "rung_type": "exact",
                "count": 0,
                "first_ids": [],
                "sort": arm.sort,
            }
        ],
        "selected": None,
        "fetched": [],
        "final_ids": [],
        "pre_search_shared_pool": {
            "file_count": 0,
            "metadata_count": 0,
            "first_ids": [],
        },
        "shared_pool_supplements": [],
    }
    for edit in (
        {"process_id": 18899},
        {"source_file": "/tmp/other/pubmed_client.py"},
        {
            "pre_search_shared_pool": {
                "file_count": 1,
                "metadata_count": 0,
                "first_ids": [],
            }
        },
        {
            "shared_pool_supplements": [
                {
                    "pmid": "123",
                    "source": "shared_pool",
                    "origin": "prior_pool",
                    "preexisting": True,
                }
            ]
        },
        {
            "selected": {
                "rung_index": 0,
                "rung_type": "exact",
                "count": 1,
                "ids": ["123"],
                "sort": arm.sort,
            },
            "fetched": [
                {
                    "pmid": "123",
                    "fetched": False,
                    "pmc_available": False,
                    "abstract_available": False,
                }
            ],
        },
    ):
        with pytest.raises(ValueError):
            pilot._trace({**valid, **edit}, arm, "run")


def test_cli_runs_the_frozen_twelve_calls_and_blinds_parsed_papers(
    monkeypatch, tmp_path
):
    _clear_credentials(monkeypatch)
    baseline_cache = tmp_path / "baseline"
    candidate_cache = tmp_path / "candidate"
    baseline_cache.mkdir()
    candidate_cache.mkdir()
    output = tmp_path / "result.json"
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("COSCIENTIST_MCP_SHARED_SECRET", "s" * 40)
    clock = [0.0]
    waits: list[float] = []
    calls: list[dict[str, object]] = []
    settings = {
        8898: (
            baseline_cache,
            json.loads(pilot.BUILD_RECEIPT.read_text())["baseline_build_id"],
            "pub_date",
        ),
        8899: (
            candidate_cache,
            json.loads(pilot.BUILD_RECEIPT.read_text())["candidate_build_id"],
            "relevance",
        ),
    }

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)
        clock[0] += seconds

    class FakeClient:
        def __init__(self, server_url: str):
            self.server_url = server_url
            self.port = pilot.urlsplit(server_url).port

        async def initialize(self) -> None:
            return None

        async def call_tool(self, name: str, **params: object) -> dict[str, object]:
            assert name == "pubmed_search_with_fulltext"
            calls.append({"port": self.port, **params, "start": clock[0]})
            cache, build_id, sort = settings[self.port]
            slug = str(params["slug"])
            run_id = str(params["run_id"])
            pmid = str(90000000 + len(calls))
            run_dir = cache / "pubmed" / slug / "runs" / run_id
            run_dir.mkdir(parents=True)
            trace = {
                "run_id": run_id,
                "server_build_id": build_id,
                "process_id": self.port + 10000,
                "source_file": str(
                    (
                        Path(pilot.BUILD_RECEIPT.parent / "builds")
                        / ("baseline" if self.port == 8898 else "candidate")
                        / "engine/mcp_server/pubmed_client.py"
                    ).resolve()
                ),
                "sort": sort,
                "pre_search_shared_pool": {
                    "file_count": 0,
                    "metadata_count": 0,
                    "first_ids": [],
                },
                "attempts": [
                    {
                        "rung_index": 0,
                        "rung_type": "exact",
                        "count": 1,
                        "first_ids": [pmid],
                        "sort": sort,
                    }
                ],
                "selected": {
                    "rung_index": 0,
                    "rung_type": "exact",
                    "count": 1,
                    "ids": [pmid],
                    "sort": sort,
                },
                "fetched": [
                    {
                        "pmid": pmid,
                        "fetched": True,
                        "pmc_available": False,
                        "abstract_available": True,
                    }
                ],
                "final_ids": [pmid],
                "shared_pool_supplements": [],
            }
            (run_dir / ".search-trace.json").write_text(
                __import__("json").dumps(trace), encoding="utf-8"
            )
            clock[0] += 0.25
            return {
                pmid: {
                    "title": f"Synthetic title {len(calls)}",
                    "authors": [],
                    "date_revised": "2024/01/01",
                    "abstract": f"Synthetic abstract {len(calls)}.",
                }
            }

    monkeypatch.setattr(pilot, "MCPToolClient", FakeClient)
    monkeypatch.setattr(pilot.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(pilot.time, "monotonic", lambda: clock[0])

    status = pilot.main(_argv(baseline_cache, candidate_cache, output))

    report = __import__("json").loads(output.read_text(encoding="utf-8"))
    blind_path = tmp_path / "result-blind-review.json"
    blind = __import__("json").loads(blind_path.read_text(encoding="utf-8"))
    expected = [
        ("stmn2-tdp43-recovery", "baseline"),
        ("stmn2-tdp43-recovery", "candidate"),
        ("unc13a-cognitive-control", "candidate"),
        ("unc13a-cognitive-control", "baseline"),
        ("sars-entry-recovery", "candidate"),
        ("sars-entry-recovery", "baseline"),
        ("sars-isg15-endothelium-control", "baseline"),
        ("sars-isg15-endothelium-control", "candidate"),
        ("qa1b-tumor-recovery", "baseline"),
        ("qa1b-tumor-recovery", "candidate"),
        ("qa1-cmv-effector-control", "candidate"),
        ("qa1-cmv-effector-control", "baseline"),
    ]
    assert status == 0
    assert report["status"] == "COMPLETED"
    assert len(report["calls"]) == pilot.MAX_OUTER_CALLS == 12
    assert [(item["case_id"], item["arm"]) for item in report["calls"]] == expected
    assert len({item["slug"] for item in report["calls"]}) == 12
    assert len({item["run_id"] for item in report["calls"]}) == 12
    assert len(waits) == 11 and all(delay >= 0 for delay in waits)
    assert all(
        second["start"] - first["start"] >= 2.0
        for first, second in zip(calls, calls[1:])
    )
    assert all(set(call) >= {"query", "max_papers", "slug", "run_id"} for call in calls)
    assert all("recency_years" not in call for call in calls)
    assert all(
        "control" not in str(call["slug"]) and "recovery" not in str(call["slug"])
        for call in calls
    )
    assert all(call["max_papers"] == 3 for call in calls)
    assert all(item["status"] == "complete" for item in report["calls"])
    assert all(
        item["trace"]["server_build_id"] == item["server_build_id"]
        for item in report["calls"]
    )
    assert len(blind["items"]) == 12
    assert all(
        set(item) == {"item_id", "draft", "title", "abstract"}
        for item in blind["items"]
    )
    assert not any(
        "pmid" in item or "arm" in item or "sort" in item for item in blind["items"]
    )
    assert all(
        "abstract" not in item and "title" not in item
        for call in report["calls"]
        for item in call["papers"]
    )


def test_cli_retains_first_error_and_never_retries(monkeypatch, tmp_path):
    _clear_credentials(monkeypatch)
    baseline_cache = tmp_path / "baseline"
    candidate_cache = tmp_path / "candidate"
    baseline_cache.mkdir()
    candidate_cache.mkdir()
    output = tmp_path / "result.json"
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("COSCIENTIST_MCP_SHARED_SECRET", "s" * 40)
    calls: list[str] = []

    class FailingClient:
        def __init__(self, server_url: str):
            self.server_url = server_url

        async def initialize(self) -> None:
            return None

        async def call_tool(self, name: str, **params: object) -> str:
            calls.append(name)
            raise TimeoutError("synthetic transport failure")

    monkeypatch.setattr(pilot, "MCPToolClient", FailingClient)

    status = pilot.main(_argv(baseline_cache, candidate_cache, output))

    report = __import__("json").loads(output.read_text(encoding="utf-8"))
    assert status != 0
    assert calls == ["pubmed_search_with_fulltext"]
    assert len(report["calls"]) == 1
    assert report["calls"][0]["status"] == "error"
    assert report["calls"][0]["error_class"] == "TimeoutError"
    assert report["status"] == "STOPPED"
    assert report["error"] == {"stage": "transport", "class": "TimeoutError"}
    assert not (tmp_path / "result-blind-review.json").exists()
