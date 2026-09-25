"""Offline tests for the frozen precise-rung paired retrieval runner."""

from __future__ import annotations

import json
from pathlib import Path
import hashlib
import os
import subprocess
from urllib.parse import urlsplit
from typing import Any

import pytest

import novelty_precise_rung_runner as runner

CORRECTED_INPUTS_SHA256 = (
    "cd61e74394735656b9a14f56eea219cd14af069359cb0e4b683a63881ede3a61"
)
CORRECTED_SOURCES_SHA256 = (
    "79adb5adc0129939e3cfa55d7da38703753f52365d86ce9e8db843e13c3eb9af"
)


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_frozen_runner_requests_match_only_the_preregistered_inputs():
    prereg = json.loads(runner.PREREG.read_text(encoding="utf-8"))
    expected = tuple(
        (item["request_id"], item["exact_query"]) for item in prereg["request_inputs"]
    )
    assert tuple((item.request_id, item.query) for item in runner.REQUESTS) == expected
    assert all(len(item.query) < 200 for item in runner.REQUESTS)
    assert len(runner.REQUESTS) == 6


def test_reproducibility_digests_are_recomputed_from_canonical_frozen_payloads():
    prereg = json.loads(runner.PREREG.read_text(encoding="utf-8"))
    corrected_inputs = _canonical_digest(prereg["request_inputs"])
    corrected_sources = _canonical_digest(prereg["source_evidence"])

    assert corrected_inputs == CORRECTED_INPUTS_SHA256
    assert corrected_sources == CORRECTED_SOURCES_SHA256
    assert corrected_inputs != prereg["reproducibility"]["frozen_inputs_sha256"]
    assert corrected_sources != prereg["reproducibility"]["source_manifest_sha256"]


def test_fixed_pair_order_and_hard_call_bounds_are_frozen():
    assert runner.CALL_ORDER == tuple(
        (request_id, arm)
        for request_id in ("R01", "R02", "R03", "R04", "R05", "R06")
        for arm in ("baseline", "candidate")
    )
    assert len(runner.CALL_ORDER) == runner.MAX_OUTER_CALLS == 12
    assert runner.MAX_ESEARCH_CALLS == 36


def test_trace_rejects_incomplete_or_nonempty_presearch_pool(tmp_path):
    arm = runner.Arm(
        name="baseline",
        url="http://127.0.0.1:8898/mcp",
        root=tmp_path,
        cache=tmp_path,
        build_id="b" * 64,
        commit="1" * 40,
        tree_sha256="a" * 64,
        diff_sha256="c" * 64,
        sort="pub_date",
        port=8898,
        pid=18898,
        source_file=tmp_path / "engine/mcp_server/pubmed_client.py",
    )
    valid = {
        "run_id": "run-1",
        "server_build_id": arm.build_id,
        "process_id": arm.pid,
        "source_file": str(arm.source_file),
        "sort": arm.sort,
        "attempts": [
            {
                "rung_index": 1,
                "rung_type": "exact",
                "count": 9,
                "first_ids": [str(i) for i in range(1, 10)],
                "sort": arm.sort,
            }
        ],
        "selected": {
            "rung_index": 1,
            "rung_type": "exact",
            "count": 9,
            "ids": [str(i) for i in range(1, 10)],
            "sort": arm.sort,
        },
        "fetched": [
            {
                "pmid": str(i),
                "fetched": True,
                "pmc_available": False,
                "abstract_available": True,
            }
            for i in range(1, 10)
        ],
        "final_ids": ["1", "2", "3"],
        "pre_search_shared_pool": {
            "file_count": 0,
            "metadata_count": 0,
            "first_ids": [],
        },
        "shared_pool_supplements": [],
    }
    assert runner._trace(valid, arm, "run-1")["final_ids"] == ["1", "2", "3"]

    for edit in (
        {"server_build_id": "f" * 64},
        {"attempts": []},
        {
            "pre_search_shared_pool": {
                "file_count": 1,
                "metadata_count": 0,
                "first_ids": [],
            }
        },
        {"attempts": valid["attempts"] * 4},
        {"fetched": valid["fetched"][:-1]},
        {"final_ids": ["1", "2", "3", "4"]},
    ):
        with pytest.raises(ValueError):
            runner._trace({**valid, **edit}, arm, "run-1")


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _tree_sha(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


@pytest.fixture
def attested_trees(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "--quiet", str(repo))
    _git(repo, "config", "user.name", "Offline Test")
    _git(repo, "config", "user.email", "offline@example.invalid")
    mcp = repo / "engine/mcp_server"
    tests = mcp / "tests"
    tests.mkdir(parents=True)
    (mcp / "pubmed_client.py").write_text('SORT = "pub_date"\n', encoding="utf-8")
    (mcp / "pubmed_query.py").write_text(
        "def select(ids):\n    return ids[-9:]\n", encoding="utf-8"
    )
    test_file = tests / "test_pubmed_query.py"
    test_file.write_text("def test_old():\n    assert True\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "baseline")
    baseline_commit = _git(repo, "rev-parse", "HEAD")
    baseline_root = tmp_path / "baseline"
    _git(repo, "worktree", "add", "--quiet", str(baseline_root), baseline_commit)

    (mcp / "pubmed_query.py").write_text(
        "def select(ids):\n    return list(dict.fromkeys(ids))[:9]\n",
        encoding="utf-8",
    )
    test_file.write_text("def test_new():\n    assert True\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "candidate")
    candidate_commit = _git(repo, "rev-parse", "HEAD")
    candidate_root = tmp_path / "candidate"
    _git(repo, "worktree", "add", "--quiet", str(candidate_root), candidate_commit)

    monkeypatch.setattr(runner, "BASELINE_COMMIT", baseline_commit)
    diff = subprocess.run(
        [
            "git",
            "diff",
            "--no-ext-diff",
            "--binary",
            baseline_commit,
            candidate_commit,
            "--",
            "engine/mcp_server/pubmed_query.py",
        ],
        cwd=candidate_root,
        check=True,
        capture_output=True,
    ).stdout
    amendment = {
        "status": "authorized_for_retrieval",
        "live_retrieval_authorized": True,
        "prereg_sha256": runner.PREREG_SHA256,
        "baseline_commit": baseline_commit,
        "baseline_tree_sha256": _tree_sha(baseline_root / "engine/mcp_server"),
        "candidate_commit": candidate_commit,
        "candidate_tree_sha256": _tree_sha(candidate_root / "engine/mcp_server"),
        "candidate_diff_sha256": hashlib.sha256(diff).hexdigest(),
        "runner_path": runner.RUNNER_RELPATH,
        "runner_sha256": runner._sha256_file(Path(runner.__file__).resolve()),
        "corrected_frozen_inputs_sha256": _canonical_digest(
            json.loads(runner.PREREG.read_text(encoding="utf-8"))["request_inputs"]
        ),
        "corrected_source_manifest_sha256": _canonical_digest(
            json.loads(runner.PREREG.read_text(encoding="utf-8"))["source_evidence"]
        ),
    }
    amendment_path = tmp_path / "protocol-amendment.json"
    amendment_path.write_text(json.dumps(amendment), encoding="utf-8")
    monkeypatch.setattr(runner, "AMENDMENT", amendment_path)
    args = type(
        "Args",
        (),
        {"baseline_root": str(baseline_root), "candidate_root": str(candidate_root)},
    )()
    return args, amendment, amendment_path


def test_protocol_attests_pinned_baseline_candidate_and_runner(attested_trees):
    args, amendment, _ = attested_trees
    actual, hashes = runner._protocol(args)
    assert actual == amendment
    assert hashes["baseline"] == amendment["baseline_tree_sha256"]
    assert hashes["candidate"] == amendment["candidate_tree_sha256"]
    assert hashes["candidate_diff_sha256"] == amendment["candidate_diff_sha256"]
    assert hashes["candidate_changed_files"] == list(runner.EXPECTED_DIFF_PATHS)
    assert hashes["frozen_inputs_sha256"] == amendment["corrected_frozen_inputs_sha256"]
    assert (
        hashes["source_manifest_sha256"]
        == amendment["corrected_source_manifest_sha256"]
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "candidate_verified_runner_hash_pending"),
        ("live_retrieval_authorized", False),
        ("prereg_sha256", "f" * 64),
        ("baseline_tree_sha256", "f" * 64),
        ("candidate_tree_sha256", "f" * 64),
        ("candidate_diff_sha256", "f" * 64),
        ("runner_sha256", "f" * 64),
        ("corrected_frozen_inputs_sha256", "f" * 64),
        ("corrected_source_manifest_sha256", "f" * 64),
    ],
)
def test_protocol_rejects_unfinalized_or_tampered_amendment(
    attested_trees, field, value
):
    args, amendment, path = attested_trees
    amendment[field] = value
    path.write_text(json.dumps(amendment), encoding="utf-8")
    with pytest.raises(ValueError):
        runner._protocol(args)


@pytest.mark.parametrize(
    "field",
    ("corrected_frozen_inputs_sha256", "corrected_source_manifest_sha256"),
)
def test_protocol_requires_canonical_digest_amendment_fields(attested_trees, field):
    args, amendment, path = attested_trees
    amendment.pop(field)
    path.write_text(json.dumps(amendment), encoding="utf-8")
    with pytest.raises(ValueError, match="Protocol amendment is incomplete"):
        runner._protocol(args)


def test_runner_stops_before_mcp_when_dated_amendment_is_missing(
    monkeypatch, tmp_path, capsys
):
    caches = [tmp_path / "baseline", tmp_path / "candidate"]
    for cache in caches:
        cache.mkdir()
    monkeypatch.setattr(runner, "AMENDMENT", tmp_path / "missing-amendment.json")
    monkeypatch.setattr(
        runner, "MCPToolClient", lambda **_: pytest.fail("MCP must not be contacted")
    )
    output = tmp_path / "result.json"
    argv = [
        "--baseline-url",
        "http://127.0.0.1:8898/mcp",
        "--candidate-url",
        "http://127.0.0.1:8899/mcp",
        "--baseline-root",
        str(tmp_path / "base-root"),
        "--candidate-root",
        str(tmp_path / "candidate-root"),
        "--baseline-cache",
        str(caches[0]),
        "--candidate-cache",
        str(caches[1]),
        "--baseline-pid",
        "18898",
        "--candidate-pid",
        "18899",
        "--output",
        str(output),
    ]
    assert runner.main(argv) == 2
    assert not output.exists()
    assert "amendment is missing" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["OPENROUTER_API_KEY", "AWS_ACCESS_KEY_ID"])
def test_environment_rejects_ambient_provider_credentials(monkeypatch, tmp_path, name):
    _offline_environment(monkeypatch)
    monkeypatch.setenv(name, "synthetic-only")
    with pytest.raises(ValueError, match=name):
        runner._check_environment({"baseline": tmp_path, "candidate": tmp_path})


def _fake_arms(tmp_path):
    arms = {}
    for name, port, sort in (
        ("baseline", 8898, "pub_date"),
        ("candidate", 8899, "pub_date"),
    ):
        root = tmp_path / f"{name}-root"
        source = root / "engine/mcp_server/pubmed_client.py"
        source.parent.mkdir(parents=True)
        source.write_text("synthetic source\n", encoding="utf-8")
        cache = tmp_path / f"{name}-cache"
        cache.mkdir()
        arms[name] = runner.Arm(
            name=name,
            url=f"http://127.0.0.1:{port}/mcp",
            root=root,
            cache=cache,
            build_id=("a" if name == "baseline" else "b") * 64,
            commit=("1" if name == "baseline" else "2") * 40,
            tree_sha256=("a" if name == "baseline" else "b") * 64,
            diff_sha256="c" * 64,
            sort=sort,
            port=port,
            pid=port + 10000,
            source_file=source.resolve(),
        )
    return arms


def _offline_environment(monkeypatch):
    for name in tuple(os.environ):
        if (
            name.endswith(
                (
                    "_API_KEY",
                    "_ACCESS_KEY",
                    "_ACCESS_KEY_ID",
                    "_KEY",
                    "_TOKEN",
                    "_SECRET",
                    "_PASSWORD",
                    "_PRIVATE_KEY",
                    "_CREDENTIALS",
                )
            )
            and name != runner.MCP_SECRET
        ):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(runner.MCP_SECRET, "s" * 40)


def test_missing_maintained_trace_records_expected_path_without_retry(
    monkeypatch, tmp_path
):
    arms = _fake_arms(tmp_path)
    tool = type(
        "Tool",
        (),
        {
            "mcp_tool_name": "pubmed_search_with_fulltext",
            "map_parameters": staticmethod(lambda params: params),
        },
    )()
    calls: list[dict[str, Any]] = []

    class OfflineMaintainedClient:
        async def call_tool(self, name: str, **params: Any):
            assert name == tool.mcp_tool_name
            calls.append(params)
            # Model the maintained tool's per-run cache and response with
            # tracing disabled.
            run_dir = (
                arms["baseline"].cache
                / "pubmed"
                / params["slug"]
                / "runs"
                / params["run_id"]
            )
            run_dir.mkdir(parents=True)
            (run_dir / ".manifest.json").write_text("{}", encoding="utf-8")
            return {
                "123": {"title": "Synthetic paper", "abstract": "Synthetic abstract"}
            }

    async def fake_client(_runtime: Any, _name: str):
        return OfflineMaintainedClient()

    monkeypatch.setattr(runner, "_client", fake_client)
    monkeypatch.setattr(
        runner,
        "_papers",
        lambda _raw, _parser: (
            [{"pmid": "123", "blind_item_id": "synthetic"}],
            [
                {
                    "item_id": "synthetic",
                    "title": "Synthetic paper",
                    "abstract": "Synthetic abstract",
                }
            ],
        ),
    )
    runtime = runner.Runtime(
        arms=arms,
        tool=tool,
        pilot_id="offline-pilot",
        parser=None,
    )

    entry = runner.asyncio.run(
        runner._execute(runtime, runner.REQUESTS[0], arms["baseline"], 1)
    )

    expected_path = (
        arms["baseline"].cache
        / "pubmed"
        / entry["slug"]
        / "runs"
        / entry["run_id"]
        / ".search-trace.json"
    )
    assert entry["status"] == "error"
    assert entry["error_stage"] == "trace"
    assert entry["error_class"] == "FileNotFoundError"
    assert entry["missing_trace_path"] == str(expected_path)
    assert calls == [entry["parameters"]]


def test_main_persists_report_from_actual_preflight_hashes(
    monkeypatch, tmp_path, capsys
):
    _offline_environment(monkeypatch)
    arms = _fake_arms(tmp_path)
    output = tmp_path / "result.json"
    blind = tmp_path / "blind.json"
    protocol_hashes = {
        "baseline": arms["baseline"].build_id,
        "candidate": arms["candidate"].build_id,
        "candidate_diff_sha256": "c" * 64,
        "candidate_changed_files": list(runner.EXPECTED_DIFF_PATHS),
        "frozen_inputs_sha256": CORRECTED_INPUTS_SHA256,
        "source_manifest_sha256": CORRECTED_SOURCES_SHA256,
    }
    monkeypatch.setattr(runner, "_protocol", lambda _args: ({}, protocol_hashes))
    monkeypatch.setattr(runner, "_check_environment", lambda _roots: None)
    monkeypatch.setattr(runner, "_listening_pid", lambda port: port + 10000)
    monkeypatch.setattr(
        runner,
        "_commit",
        lambda root: arms[root.name.removesuffix("-root")].commit,
    )
    monkeypatch.setattr(runner, "_cache", lambda path: Path(path).resolve())

    class MissingToolRegistry:
        def __init__(self, **_kwargs: Any):
            pass

        def get_tool(self, _name: str):
            return None

    monkeypatch.setattr(runner, "ToolRegistry", MissingToolRegistry)
    monkeypatch.setattr(
        runner,
        "MCPToolClient",
        lambda **_kwargs: pytest.fail("MCP must not be contacted"),
    )
    argv = [
        "--baseline-url",
        arms["baseline"].url,
        "--candidate-url",
        arms["candidate"].url,
        "--baseline-root",
        str(arms["baseline"].root),
        "--candidate-root",
        str(arms["candidate"].root),
        "--baseline-cache",
        str(arms["baseline"].cache),
        "--candidate-cache",
        str(arms["candidate"].cache),
        "--baseline-pid",
        str(arms["baseline"].pid),
        "--candidate-pid",
        str(arms["candidate"].pid),
        "--output",
        str(output),
        "--blind-output",
        str(blind),
    ]

    assert runner.main(argv) == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    captured = capsys.readouterr()
    assert "Maintained PubMed ToolConfig is unavailable" in captured.err
    assert report["candidate_changed_files"] == list(runner.EXPECTED_DIFF_PATHS)
    assert report["frozen_inputs_sha256"] == CORRECTED_INPUTS_SHA256
    assert report["source_manifest_sha256"] == CORRECTED_SOURCES_SHA256
    assert report["status"] == "STOPPED"
    assert not blind.exists()


def test_main_runs_twelve_offline_calls_in_order_and_writes_bounded_traces(
    monkeypatch, tmp_path
):
    _offline_environment(monkeypatch)
    arms = _fake_arms(tmp_path)
    output = tmp_path / "result.json"
    blind_output = tmp_path / "blind.json"
    monkeypatch.setattr(
        runner,
        "_preflight",
        lambda _args: (
            arms,
            output,
            blind_output,
            {
                "baseline_tree_sha256": arms["baseline"].tree_sha256,
                "candidate_tree_sha256": arms["candidate"].tree_sha256,
                "candidate_diff_sha256": "c" * 64,
                "candidate_changed_files": list(runner.EXPECTED_DIFF_PATHS),
                "frozen_inputs_sha256": CORRECTED_INPUTS_SHA256,
                "source_manifest_sha256": CORRECTED_SOURCES_SHA256,
            },
        ),
    )
    clock = [0.0]
    starts: list[float] = []
    calls: list[dict[str, Any]] = []

    async def fake_sleep(seconds: float):
        clock[0] += seconds

    class FakeClient:
        def __init__(self, server_url: str):
            self.arm = arms[
                urlsplit(server_url).port == 8899 and "candidate" or "baseline"
            ]

        async def initialize(self):
            return None

        async def call_tool(self, name: str, **params: Any):
            assert name == "pubmed_search_with_fulltext"
            starts.append(clock[0])
            calls.append(params)
            ids_by_rung = [
                [str(90000000 + len(calls) * 100 + rung * 10 + i) for i in range(1, 10)]
                for rung in range(1, 4)
            ]
            selected_ids = ids_by_rung[-1]
            run_dir = (
                self.arm.cache / "pubmed" / params["slug"] / "runs" / params["run_id"]
            )
            run_dir.mkdir(parents=True)
            trace = {
                "run_id": params["run_id"],
                "server_build_id": self.arm.build_id,
                "process_id": self.arm.pid,
                "source_file": str(self.arm.source_file),
                "sort": self.arm.sort,
                "attempts": [
                    {
                        "rung_index": rung,
                        "rung_type": ["exact", "anchored", "or"][rung - 1],
                        "count": 9,
                        "first_ids": ids_by_rung[rung - 1],
                        "sort": self.arm.sort,
                    }
                    for rung in (1, 2, 3)
                ],
                "selected": {
                    "rung_index": 3,
                    "rung_type": "or",
                    "count": 9,
                    "ids": selected_ids,
                    "sort": self.arm.sort,
                },
                "fetched": [
                    {
                        "pmid": pmid,
                        "fetched": True,
                        "pmc_available": False,
                        "abstract_available": True,
                    }
                    for pmid in selected_ids
                ],
                "final_ids": selected_ids[:3],
                "pre_search_shared_pool": {
                    "file_count": 0,
                    "metadata_count": 0,
                    "first_ids": [],
                },
                "shared_pool_supplements": [],
            }
            (run_dir / ".search-trace.json").write_text(
                json.dumps(trace), encoding="utf-8"
            )
            clock[0] += 0.2
            return {
                pmid: {
                    "title": f"Synthetic title {pmid}",
                    "authors": [],
                    "date_revised": "2024/01/01",
                    "abstract": f"Synthetic abstract {pmid}",
                    "fulltext": "",
                    "publication": "Synthetic journal",
                    "pmc_full_text_id": None,
                }
                for pmid in selected_ids[:3]
            }

    monkeypatch.setattr(runner, "MCPToolClient", FakeClient)
    monkeypatch.setattr(runner.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(runner.time, "monotonic", lambda: clock[0])
    argv = [
        "--baseline-url",
        arms["baseline"].url,
        "--candidate-url",
        arms["candidate"].url,
        "--baseline-root",
        str(arms["baseline"].root),
        "--candidate-root",
        str(arms["candidate"].root),
        "--baseline-cache",
        str(arms["baseline"].cache),
        "--candidate-cache",
        str(arms["candidate"].cache),
        "--baseline-pid",
        str(arms["baseline"].pid),
        "--candidate-pid",
        str(arms["candidate"].pid),
        "--output",
        str(output),
        "--blind-output",
        str(blind_output),
    ]

    assert runner.main(argv) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    blind = json.loads(blind_output.read_text(encoding="utf-8"))
    assert report["status"] == "COMPLETED"
    assert report["frozen_inputs_sha256"] == CORRECTED_INPUTS_SHA256
    assert report["source_manifest_sha256"] == CORRECTED_SOURCES_SHA256
    assert (
        tuple((row["request_id"], row["arm"]) for row in report["calls"])
        == runner.CALL_ORDER
    )
    assert len(calls) == runner.MAX_OUTER_CALLS == 12
    assert len({params["slug"] for params in calls}) == 12
    assert len({params["run_id"] for params in calls}) == 12
    assert report["esearch_call_count"] == runner.MAX_ESEARCH_CALLS == 36
    assert report["metadata_ids_submitted"] == 108
    assert all(second - first >= 2.0 for first, second in zip(starts, starts[1:]))
    assert all(
        set(params) == {"query", "max_papers", "recency_years", "slug", "run_id"}
        and params["max_papers"] == 3
        and params["recency_years"] == 0
        for params in calls
    )
    assert [params["query"] for params in calls] == [
        runner.REQUEST_BY_ID[request_id].query for request_id, _arm in runner.CALL_ORDER
    ]
    prereg = json.loads(runner.PREREG.read_text(encoding="utf-8"))
    forbidden = {
        value
        for row in prereg["scoring_key"]
        for value in (
            row.get("target_pmid", row.get("anchor_pmid")),
            row["target_title"],
        )
    }
    assert not any(value in json.dumps(calls) for value in forbidden)
    assert all(
        "abstract" not in paper and "title" not in paper
        for row in report["calls"]
        for paper in row["papers"]
    )
    assert all(set(item) == {"item_id", "title", "abstract"} for item in blind["items"])
    assert report["model_inference_calls"] == report["paid_calls"] == 0


def test_main_stops_at_the_first_transport_error_without_retry(monkeypatch, tmp_path):
    _offline_environment(monkeypatch)
    arms = _fake_arms(tmp_path)
    output = tmp_path / "result.json"
    blind = tmp_path / "blind.json"
    monkeypatch.setattr(
        runner,
        "_preflight",
        lambda _args: (
            arms,
            output,
            blind,
            {
                "baseline_tree_sha256": "a" * 64,
                "candidate_tree_sha256": "b" * 64,
                "candidate_diff_sha256": "c" * 64,
                "candidate_changed_files": list(runner.EXPECTED_DIFF_PATHS),
                "frozen_inputs_sha256": CORRECTED_INPUTS_SHA256,
                "source_manifest_sha256": CORRECTED_SOURCES_SHA256,
            },
        ),
    )
    calls: list[str] = []

    class FailingClient:
        def __init__(self, server_url: str):
            pass

        async def initialize(self):
            return None

        async def call_tool(self, name: str, **params: Any):
            calls.append(name)
            raise TimeoutError("synthetic transport failure")

    monkeypatch.setattr(runner, "MCPToolClient", FailingClient)
    argv = [
        "--baseline-url",
        arms["baseline"].url,
        "--candidate-url",
        arms["candidate"].url,
        "--baseline-root",
        str(arms["baseline"].root),
        "--candidate-root",
        str(arms["candidate"].root),
        "--baseline-cache",
        str(arms["baseline"].cache),
        "--candidate-cache",
        str(arms["candidate"].cache),
        "--baseline-pid",
        str(arms["baseline"].pid),
        "--candidate-pid",
        str(arms["candidate"].pid),
        "--output",
        str(output),
        "--blind-output",
        str(blind),
    ]

    assert runner.main(argv) == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert calls == ["pubmed_search_with_fulltext"]
    assert len(report["calls"]) == 1
    assert report["calls"][0]["error_class"] == "TimeoutError"
    assert report["status"] == "STOPPED"
    assert not blind.exists()
