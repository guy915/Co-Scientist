"""Offline tests for the frozen precise-rung paired retrieval runner."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import hashlib
import os
import subprocess
from contextlib import nullcontext
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
INDEPENDENT_PREREG_SHA256 = (
    "dec79fbe21bec82ee6535cc711cc66b2f37da61d5ef79a2eb4c0f7c2e8b8b3e8"
)
INDEPENDENT_INPUT_SHA256 = (
    "a51c88afd45a81b84b614e730f0459f5e6bb567c3c37958982312106a50781c0"
)


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_independent_protocol_is_explicitly_opt_in_and_stops_before_mcp(
    monkeypatch, tmp_path, capsys
):
    prereg = runner.HERE / "novelty-precise-rung-01b2b-independent-prereg-v1.json"
    assert hashlib.sha256(prereg.read_bytes()).hexdigest() == INDEPENDENT_PREREG_SHA256
    monkeypatch.setattr(
        runner,
        "INDEPENDENT_AMENDMENT",
        tmp_path / "missing-independent-amendment.json",
        raising=False,
    )
    monkeypatch.setattr(
        runner, "MCPToolClient", lambda **_: pytest.fail("MCP must not be contacted")
    )
    output = tmp_path / "result.json"
    argv = [
        "--protocol",
        "independent",
        "--baseline-url",
        "http://127.0.0.1:8898/mcp",
        "--candidate-url",
        "http://127.0.0.1:8899/mcp",
        "--baseline-root",
        str(tmp_path / "baseline-root"),
        "--candidate-root",
        str(tmp_path / "candidate-root"),
        "--baseline-cache",
        str(tmp_path / "baseline-cache"),
        "--candidate-cache",
        str(tmp_path / "candidate-cache"),
        "--baseline-pid",
        "18898",
        "--candidate-pid",
        "18899",
        "--baseline-launch-receipt",
        str(tmp_path / "baseline-launch.json"),
        "--candidate-launch-receipt",
        str(tmp_path / "candidate-launch.json"),
        "--output",
        str(output),
    ]

    assert runner.main(argv) == 2
    assert not output.exists()
    assert "independent amendment is missing" in capsys.readouterr().err.lower()


def test_authorized_independent_preflight_failure_is_durable_without_mcp(
    monkeypatch, tmp_path
):
    amendment = tmp_path / "amendment.json"
    amendment.write_text('{"status":"authorized_for_retrieval"}')
    monkeypatch.setattr(runner, "INDEPENDENT_AMENDMENT", amendment)
    monkeypatch.setattr(
        runner,
        "_preflight",
        lambda _args: (_ for _ in ()).throw(ValueError("pin mismatch")),
    )
    monkeypatch.setattr(
        runner, "MCPToolClient", lambda **_: pytest.fail("MCP must not be contacted")
    )
    output = tmp_path / "result.json"
    argv = ["--protocol", "independent", "--output", str(output)]
    for arm in ("baseline", "candidate"):
        argv.extend(
            [
                f"--{arm}-url",
                "http://127.0.0.1:8898/mcp",
                f"--{arm}-root",
                str(tmp_path / arm),
                f"--{arm}-cache",
                str(tmp_path / f"{arm}-cache"),
                f"--{arm}-pid",
                "18898",
            ]
        )

    assert runner.main(argv) == 2
    stopped = json.loads(output.read_text(encoding="utf-8"))
    assert stopped["status"] == "STOPPED"
    assert stopped["error"] == {"stage": "preflight", "class": "ValueError"}
    assert stopped["calls"] == []
    assert stopped["model_inference_calls"] == 0


def test_independent_protocol_parses_only_key_free_runner_inputs(monkeypatch):
    prereg_text = runner.INDEPENDENT_PREREG.read_text(encoding="utf-8")
    source_text = runner.PREREG.read_text(encoding="utf-8")
    real_loads = json.loads
    loaded: list[str] = []

    def guarded_loads(payload: str, *args: Any, **kwargs: Any):
        assert payload not in {prereg_text, source_text}
        loaded.append(payload)
        return real_loads(payload, *args, **kwargs)

    monkeypatch.setattr(runner.json, "loads", guarded_loads)
    monkeypatch.setattr(
        runner, "INDEPENDENT_AMENDMENT", runner.HERE / "missing-amendment.json"
    )
    with pytest.raises(ValueError, match="Independent amendment is missing"):
        runner._independent_protocol(type("Args", (), {})())
    assert len(loaded) == 1
    assert hashlib.sha256(loaded[0].encode()).hexdigest() == INDEPENDENT_INPUT_SHA256


def test_independent_runtime_support_must_match_committed_pins(monkeypatch, tmp_path):
    support = tmp_path / "co_scientist"
    support.mkdir()
    (support / "mcp_client_session.py").write_text("# fixed client\n")
    shared = tmp_path / "novelty_sort_pilot.py"
    shared.write_text("# fixed helper\n")
    project = tmp_path / "pyproject.toml"
    project.write_text("[project]\nname = 'fixed'\n")
    monkeypatch.setattr(runner, "RUNTIME_SUPPORT_TREE", support)
    monkeypatch.setattr(runner, "SHARED_PILOT_SOURCE", shared)
    monkeypatch.setattr(runner, "ENGINE_PROJECT_SOURCE", project)
    checked: list[Path] = []
    monkeypatch.setattr(
        runner, "_require_committed_clean", lambda path, _label: checked.append(path)
    )
    pins = {
        "engine_source_tree_sha256": runner._tree_sha256(runner._tree_files(support)),
        "shared_pilot_sha256": runner._sha256_file(shared),
        "engine_project_sha256": runner._sha256_file(project),
    }
    runner._validate_runtime_support(pins)
    assert checked == [support, shared, project]

    (support / "mcp_client_session.py").write_text("# changed client\n")
    with pytest.raises(ValueError, match="runtime support"):
        runner._validate_runtime_support(pins)


def test_independent_call_slug_matches_the_single_preregistered_template():
    assert (
        runner._call_slug("independent", runner.INDEPENDENT_PILOT_ID, "R03", "baseline")
        == "m11novrung01b2bindependentv1_r03_baseline"
    )
    assert runner._call_slug("original", "pilot", "R03", "baseline") == (
        "m11novrung_pilot_r03_baseline"
    )


def test_independent_schedule_rejects_a_different_preregistered_slug_template():
    runner_inputs = json.loads(runner.INDEPENDENT_INPUT.read_text(encoding="utf-8"))
    runner_inputs["run_artifact_paths"]["per_call_slug_template"] = (
        "different_{request_id_lower}_{arm}"
    )
    with pytest.raises(ValueError, match="slug template"):
        runner._independent_schedule(runner_inputs)


def test_independent_run_executes_the_eight_frozen_calls_in_order(
    monkeypatch, tmp_path
):
    runner_inputs = json.loads(
        (
            runner.HERE / "novelty-precise-rung-01b2b-independent-input-v1.json"
        ).read_text(encoding="utf-8")
    )
    requests, call_order = runner._independent_schedule(runner_inputs)
    assert tuple(requests) == ("R03", "R04", "R05", "R06")
    assert len(call_order) == runner.INDEPENDENT_MAX_OUTER_CALLS == 8
    assert all(len(request.query) < 200 for request in requests.values())
    runtime = runner.Runtime(
        arms=_fake_arms(tmp_path),
        tool=None,
        pilot_id=runner.INDEPENDENT_PILOT_ID,
        parser=None,
        request_by_id=requests,
        call_order=call_order,
        max_outer_calls=runner.INDEPENDENT_MAX_OUTER_CALLS,
        max_esearch_calls=runner.INDEPENDENT_MAX_ESEARCH_CALLS,
        max_metadata_ids=runner.INDEPENDENT_MAX_OUTER_CALLS * runner.MAX_IDS_PER_CALL,
        pilot_label="M11-NOV-RUNG-01b2b-independent-v1",
        protocol="independent",
    )
    actual: list[tuple[str, str, int]] = []

    async def complete_one(
        _runtime: runner.Runtime, request: runner.Request, arm: runner.Arm, order: int
    ):
        actual.append((request.request_id, arm.name, order))
        return {
            "order": order,
            "request_id": request.request_id,
            "arm": arm.name,
            "status": "complete",
        }

    monkeypatch.setattr(runner, "_execute", complete_one)
    report = {"calls": []}
    output, blind = tmp_path / "result.json", tmp_path / "blind.json"

    context = tmp_path / "case-context.json"
    assert (
        runner.asyncio.run(
            runner._run(runtime, report, output, blind, case_context_output=context)
        )
        == 0
    )
    assert actual == [
        (request_id, arm, index)
        for index, (request_id, arm) in enumerate(call_order, 1)
    ]
    assert len(report["calls"]) == 8
    assert report["status"] == "COMPLETED"
    assert json.loads(blind.read_text(encoding="utf-8"))["items"] == []
    context_artifact = json.loads(context.read_text(encoding="utf-8"))
    assert context_artifact["protocol"] == runner.CASE_CONTEXT_PROTOCOL
    assert (
        context_artifact["result_sha256"]
        == hashlib.sha256(output.read_bytes()).hexdigest()
    )
    assert (
        context_artifact["blind_review_sha256"]
        == hashlib.sha256(blind.read_bytes()).hexdigest()
    )
    assert context_artifact["items"] == []


def test_independent_cli_fails_closed_without_measured_retry_launcher(
    monkeypatch, tmp_path, capsys
):
    roots = [tmp_path / "baseline-root", tmp_path / "candidate-root"]
    caches = [tmp_path / "baseline-cache", tmp_path / "candidate-cache"]
    for path in (*roots, *caches):
        path.mkdir()
    output, blind = tmp_path / "result.json", tmp_path / "blind.json"
    request_ids = ("R03", "R04", "R05", "R06")
    call_order = tuple(
        (request_id, arm)
        for request_id in request_ids
        for arm in ("baseline", "candidate")
    )
    hashes = {
        "protocol": "independent",
        "protocol_id": runner.INDEPENDENT_PROTOCOL_ID,
        "pilot_id": runner.INDEPENDENT_PILOT_ID,
        "baseline": "a" * 64,
        "candidate": "b" * 64,
        "candidate_diff_sha256": "c" * 64,
        "candidate_changed_files": list(runner.EXPECTED_DIFF_PATHS),
        "frozen_inputs_sha256": "d" * 64,
        "source_manifest_sha256": "e" * 64,
        "result_path": str(output),
        "blind_review_path": str(blind),
        "case_context_path": runner.CASE_CONTEXT_RELPATH,
        "case_context_protocol": runner.CASE_CONTEXT_PROTOCOL,
        "request_by_id": {
            request_id: runner.Request(request_id, "query")
            for request_id in request_ids
        },
        "call_order": call_order,
        "trace_preflight": {
            "driver_path": runner.LIFECYCLE_DRIVER_RELPATH,
            "driver_sha256": "e" * 64,
            "launcher_path": runner.SERVER_LAUNCHER_RELPATH,
            "launcher_sha256": "f" * 64,
            "baseline": {},
            "candidate": {},
        },
    }
    monkeypatch.setattr(runner, "_protocol", lambda _args: ({}, hashes))
    monkeypatch.setattr(runner, "_check_environment", lambda _roots: None)
    monkeypatch.setattr(runner, "_commit", lambda _root: "test-commit")
    monkeypatch.setattr(
        runner,
        "_listening_pid",
        lambda port: 18898 if port == 8898 else 18899,
    )
    monkeypatch.setattr(
        runner, "MCPToolClient", lambda **_: pytest.fail("MCP must not be contacted")
    )
    argv = [
        "--protocol",
        "independent",
        "--baseline-url",
        "http://127.0.0.1:8898/mcp",
        "--candidate-url",
        "http://127.0.0.1:8899/mcp",
        "--baseline-root",
        str(roots[0]),
        "--candidate-root",
        str(roots[1]),
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
        "--blind-output",
        str(blind),
    ]

    assert runner.main(argv) == 2
    stopped = json.loads(output.read_text(encoding="utf-8"))
    assert stopped["status"] == "STOPPED"
    assert stopped["error"] == {"stage": "preflight", "class": "ValueError"}
    assert stopped["calls"] == []
    assert "launcher hash" in capsys.readouterr().err.lower()


@pytest.mark.parametrize("failure_stage", ("parse", "trace"))
def test_post_call_parse_or_trace_failure_reports_request_count_unknown(
    monkeypatch, tmp_path, failure_stage
):
    arms = _fake_arms(tmp_path)
    runtime = runner.Runtime(
        arms=arms,
        tool=type(
            "Tool",
            (),
            {
                "mcp_tool_name": "pubmed_search_with_fulltext",
                "map_parameters": staticmethod(lambda params: params),
            },
        )(),
        pilot_id=runner.INDEPENDENT_PILOT_ID,
        parser=None,
        protocol="independent",
        preregistered_slugs={
            ("R03", "baseline"): runner._call_slug(
                "independent", runner.INDEPENDENT_PILOT_ID, "R03", "baseline"
            )
        },
        request_by_id={"R03": runner.Request("R03", "query")},
        call_order=(("R03", "baseline"),),
        max_outer_calls=1,
    )

    monkeypatch.setattr(runner, "_endpoint", lambda _url: nullcontext())

    class Client:
        async def call_tool(self, *_args, **_kwargs):
            return object()

    async def get_client(_runtime, _name):
        return Client()

    monkeypatch.setattr(runner, "_client", get_client)
    if failure_stage == "parse":
        monkeypatch.setattr(
            runner,
            "_papers",
            lambda *_: (_ for _ in ()).throw(ValueError("bad parse")),
        )
    else:
        monkeypatch.setattr(runner, "_papers", lambda *_: ([], []))

    output, blind = tmp_path / "result.json", tmp_path / "blind.json"
    report = {"calls": []}
    assert runner.asyncio.run(runner._run(runtime, report, output, blind)) == 1
    saved = json.loads(output.read_text(encoding="utf-8"))
    entry = saved["calls"][0]

    assert entry["status"] == "error"
    assert entry["external_request_count"] == "unknown"
    assert entry["verified_esearch_rung_count"] == 0
    assert entry["error_stage"] == failure_stage
    assert entry["slug"] == "m11novrung01b2bindependentv1_r03_baseline"
    assert entry["run_id"] == "m11novrung01b2bindependentv1_r03_baseline"
    assert runtime.esearch_calls == 0
    assert saved["esearch_call_count"] == 0
    assert saved["esearch_call_count_scope"] == "verified_trace_only"
    assert entry["external_request_count"] == "unknown"


def test_independent_success_separates_blind_packet_query_context_and_locked_key(
    monkeypatch, tmp_path
):
    arms = _fake_arms(tmp_path)
    arm = arms["baseline"]
    request = runner.Request("R03", "exact preregistered query")
    runtime = runner.Runtime(
        arms=arms,
        tool=type(
            "Tool",
            (),
            {
                "mcp_tool_name": "pubmed_search_with_fulltext",
                "map_parameters": staticmethod(lambda params: params),
            },
        )(),
        pilot_id=runner.INDEPENDENT_PILOT_ID,
        parser=None,
        protocol="independent",
        preregistered_slugs={
            ("R03", "baseline"): runner._call_slug(
                "independent", runner.INDEPENDENT_PILOT_ID, "R03", "baseline"
            )
        },
    )

    class Client:
        async def call_tool(self, *_args, **_kwargs):
            return object()

    async def get_client(_runtime, _name):
        return Client()

    monkeypatch.setattr(runner, "_client", get_client)
    monkeypatch.setattr(runner, "_endpoint", lambda _url: nullcontext())
    monkeypatch.setattr(runner.secrets, "token_urlsafe", lambda _size: "opaque-case")
    monkeypatch.setattr(
        runner,
        "_papers",
        lambda *_: (
            [{"pmid": "12345", "blind_item_id": "internal-item"}],
            [
                {
                    "item_id": "internal-item",
                    "title": "Private source title",
                    "abstract": "Blinded abstract",
                }
            ],
        ),
    )
    monkeypatch.setattr(
        runner,
        "_trace",
        lambda *_: {"final_ids": ["12345"], "attempts": [], "fetched": []},
    )
    slug = runner._call_slug("independent", runtime.pilot_id, "R03", "baseline")
    run_id = f"{runtime.pilot_id}_r03_baseline"

    async def get_client(_runtime, _name):
        class TraceClient:
            async def call_tool(self, *_args, **_kwargs):
                trace_path = (
                    arm.cache / "pubmed" / slug / "runs" / run_id / ".search-trace.json"
                )
                trace_path.parent.mkdir(parents=True)
                trace_path.write_text("{}", encoding="utf-8")
                return object()

        return TraceClient()

    monkeypatch.setattr(runner, "_client", get_client)

    entry = runner.asyncio.run(runner._execute(runtime, request, arm, 1))

    assert entry["status"] == "complete"
    assert entry["papers"] == [{"pmid": "12345", "case_id": "opaque-case"}]
    assert entry["locked_case_map"] == [
        {
            "case_id": "opaque-case",
            "request_id": "R03",
            "arm": "baseline",
            "pmid": "12345",
            "source_title": "Private source title",
        }
    ]
    assert runtime.blind_items == [
        {"case_id": "opaque-case", "abstract": "Blinded abstract"}
    ]
    assert runtime.case_context_items == [
        {"case_id": "opaque-case", "query": request.query}
    ]
    assert not any(
        key in runtime.blind_items[0]
        for key in ("query", "arm", "pmid", "title", "role")
    )


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
    with pytest.raises(ValueError, match="Protocol amendment pins mismatch"):
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


def _launcher_receipt_fixture(tmp_path, monkeypatch, attempts=1):
    arms = _fake_arms(tmp_path)
    launcher = tmp_path / "launcher.py"
    launcher.write_text("# pinned launcher fixture\n", encoding="utf-8")
    monkeypatch.setattr(runner, "SERVER_LAUNCHER", launcher)
    launcher_sha256 = hashlib.sha256(launcher.read_bytes()).hexdigest()
    pinned = {
        "driver_path": runner.LIFECYCLE_DRIVER_RELPATH,
        "driver_sha256": "e" * 64,
        "launcher_path": runner.SERVER_LAUNCHER_RELPATH,
        "launcher_sha256": launcher_sha256,
    }
    receipt_paths = {}
    for name, arm in arms.items():
        probe_id = f"m11_launcher_probe_{arm.pid}"
        trace_path = (
            arm.cache / "pubmed" / probe_id / "runs" / probe_id / ".search-trace.json"
        )
        ids = ["90000001", "90000002", "90000003"]
        receipt = {
            "schema_version": "novelty_precise_rung_launcher_receipt_v1",
            "status": "passed",
            "launcher_path": runner.SERVER_LAUNCHER_RELPATH,
            "launcher_sha256": launcher_sha256,
            "source_root": str(arm.root),
            "source_tree_sha256": arm.tree_sha256,
            "serving_pid": arm.pid,
            "bind_host": "127.0.0.1",
            "bind_port": arm.port,
            "max_workers": 1,
            "reload": False,
            "cache_root": str(arm.cache),
            "trace_enabled": True,
            "credential_env_names": [runner.MCP_SECRET],
            "secret_env_name": runner.MCP_SECRET,
            "secret_length": 48,
            "secret_free": True,
            "entrez": {
                "max_tries": 1,
                "sleep_between_tries": 0,
                "api_key_absent": True,
            },
            "maintained_trace": {
                "enabled": True,
                "run_id": probe_id,
                "slug": probe_id,
                "path": str(trace_path),
                "sha256": "f" * 64,
                "source_file_path": str(arm.source_file),
                "server_build_id": arm.build_id,
                "process_id": arm.pid,
                "sort": arm.sort,
                "selected_ids": ids,
                "final_ids": ids,
                "manifest_run_id": probe_id,
                "manifest_ids": ids,
                "validated": True,
                "readiness_artifacts_removed": True,
                "cache_empty_after_cleanup": True,
                "fake_entrez_calls": {"esearch": 1, "efetch": 6, "elink": 3},
            },
            "transient_probe": {
                "patch_target": "Bio.Entrez.urlopen",
                "injected_status": 503,
                "underlying_attempts": attempts,
                "external_traffic": False,
                "restored": True,
            },
        }
        path = tmp_path / f"{name}-receipt.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        receipt_paths[name] = path
        pinned[name] = {
            "receipt_path": str(path.resolve()),
            "receipt_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    args = type(
        "Args",
        (),
        {f"{name}_launch_receipt": str(path) for name, path in receipt_paths.items()},
    )()
    return arms, args, pinned, receipt_paths


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


def test_independent_launcher_receipts_require_same_process_trace_and_one_attempt(
    monkeypatch, tmp_path
):
    arms, args, pinned, _ = _launcher_receipt_fixture(tmp_path, monkeypatch)
    hashes = runner._validate_launcher_receipts(args, arms, pinned)
    assert set(hashes) == {"baseline", "candidate"}

    attempts_root = tmp_path / "two-attempts"
    attempts_root.mkdir()
    arms, args, pinned, _ = _launcher_receipt_fixture(
        attempts_root, monkeypatch, attempts=2
    )
    with pytest.raises(ValueError, match="exactly one offline transient attempt"):
        runner._validate_launcher_receipts(args, arms, pinned)


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


def test_independent_actual_preflight_keeps_all_report_pins_before_mcp(
    monkeypatch, tmp_path
):
    _offline_environment(monkeypatch)
    arms = _fake_arms(tmp_path)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    output, blind = tmp_path / "result.json", tmp_path / "blind.json"
    hashes = {
        "protocol": "independent",
        "protocol_id": runner.INDEPENDENT_PROTOCOL_ID,
        "pilot_id": runner.INDEPENDENT_PILOT_ID,
        "baseline": arms["baseline"].build_id,
        "candidate": arms["candidate"].build_id,
        "candidate_diff_sha256": "c" * 64,
        "candidate_changed_files": list(runner.EXPECTED_DIFF_PATHS),
        "frozen_inputs_sha256": CORRECTED_INPUTS_SHA256,
        "source_manifest_sha256": CORRECTED_SOURCES_SHA256,
        "runner_input_sha256": INDEPENDENT_INPUT_SHA256,
        "source_prereg_sha256": INDEPENDENT_PREREG_SHA256,
        "max_outer_calls": 8,
        "max_esearch_calls": 24,
        "max_metadata_ids": 72,
        "request_by_id": {},
        "call_order": (),
        "preregistered_slugs": {},
        "result_path": "result.json",
        "blind_review_path": "blind.json",
        "case_context_path": runner.CASE_CONTEXT_RELPATH,
        "case_context_protocol": runner.CASE_CONTEXT_PROTOCOL,
        "amendment_path": runner.INDEPENDENT_AMENDMENT,
        "trace_preflight": {},
    }
    monkeypatch.setattr(runner, "_protocol", lambda _args: ({}, hashes))
    monkeypatch.setattr(runner, "_check_environment", lambda _roots: None)
    monkeypatch.setattr(runner, "_listening_pid", lambda port: port + 10000)
    monkeypatch.setattr(
        runner, "_commit", lambda root: arms[root.name.removesuffix("-root")].commit
    )
    monkeypatch.setattr(runner, "_cache", lambda path: Path(path).resolve())
    monkeypatch.setattr(
        runner,
        "_validate_launcher_receipts",
        lambda *_: {"baseline": "a" * 64, "candidate": "b" * 64},
    )

    tool = type("Tool", (), {"mcp_tool_name": "pubmed_search_with_fulltext"})()

    class StubToolRegistry:
        def __init__(self, **_kwargs: Any):
            pass

        def get_tool(self, _name: str):
            return tool

    monkeypatch.setattr(runner, "ToolRegistry", StubToolRegistry)
    monkeypatch.setattr(runner, "ResponseParser", lambda _tool: None)
    monkeypatch.setattr(
        runner, "MCPToolClient", lambda **_: pytest.fail("MCP must not be contacted")
    )

    async def finish_without_transport(_runtime, report, result_path, _blind_path, **_):
        assert report["runner_input_sha256"] == INDEPENDENT_INPUT_SHA256
        assert report["source_prereg_sha256"] == INDEPENDENT_PREREG_SHA256
        report["status"] = "COMPLETED"
        runner._save(result_path, report)
        return 0

    monkeypatch.setattr(runner, "_run", finish_without_transport)
    argv = [
        "--protocol",
        "independent",
        "--output",
        str(output),
        "--blind-output",
        str(blind),
    ]
    for name, arm in arms.items():
        argv.extend(
            [
                f"--{name}-url",
                arm.url,
                f"--{name}-root",
                str(arm.root),
                f"--{name}-cache",
                str(arm.cache),
                f"--{name}-pid",
                str(arm.pid),
                f"--{name}-launch-receipt",
                str(tmp_path / f"{name}-receipt.json"),
            ]
        )

    assert runner.main(argv) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "COMPLETED"
    assert report["runner_input_sha256"] == INDEPENDENT_INPUT_SHA256
    assert report["source_prereg_sha256"] == INDEPENDENT_PREREG_SHA256
    assert report["calls"] == []
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
            assert output.is_file() and blind_output.is_file()
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
    assert report["esearch_call_count_scope"] == "verified_trace_only"
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


def test_main_cleans_result_reservation_if_blind_reservation_collides(
    monkeypatch, tmp_path
):
    arms = _fake_arms(tmp_path)
    output, blind = tmp_path / "result.json", tmp_path / "blind.json"
    blind.write_text("owned by another run", encoding="utf-8")
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
    monkeypatch.setattr(
        runner, "ToolRegistry", lambda **_: pytest.fail("setup must not begin")
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
    assert not output.exists()
    assert blind.read_text(encoding="utf-8") == "owned by another run"


def test_main_does_not_rewrite_existing_result_on_reservation_collision(
    monkeypatch, tmp_path
):
    arms = _fake_arms(tmp_path)
    output, blind = tmp_path / "result.json", tmp_path / "blind.json"
    original = b'{"status":"COMPLETED","calls":[{"order":1}]}'
    output.write_bytes(original)
    monkeypatch.setattr(
        runner,
        "_preflight",
        lambda _args: (arms, output, blind, {"protocol": "original"}),
    )
    monkeypatch.setattr(
        runner, "ToolRegistry", lambda **_: pytest.fail("setup must not begin")
    )
    argv = ["--output", str(output), "--blind-output", str(blind)]
    for name, arm in arms.items():
        argv.extend(
            [
                f"--{name}-url",
                arm.url,
                f"--{name}-root",
                str(arm.root),
                f"--{name}-cache",
                str(arm.cache),
                f"--{name}-pid",
                str(arm.pid),
            ]
        )

    assert runner.main(argv) == 2
    assert output.read_bytes() == original
    assert not blind.exists()


def test_main_retains_zero_call_stop_after_report_reservation(monkeypatch, tmp_path):
    arms = _fake_arms(tmp_path)
    output, blind = tmp_path / "result.json", tmp_path / "blind.json"
    monkeypatch.setattr(
        runner,
        "_preflight",
        lambda _args: (arms, output, blind, {"protocol": "original"}),
    )
    monkeypatch.setattr(
        runner, "ToolRegistry", lambda **_: pytest.fail("MCP setup must not begin")
    )
    argv = ["--output", str(output), "--blind-output", str(blind)]
    for name, arm in arms.items():
        argv.extend(
            [
                f"--{name}-url",
                arm.url,
                f"--{name}-root",
                str(arm.root),
                f"--{name}-cache",
                str(arm.cache),
                f"--{name}-pid",
                str(arm.pid),
            ]
        )

    assert runner.main(argv) == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "STOPPED"
    assert report["error"] == {"stage": "runner", "class": "KeyError"}
    assert report["calls"] == []
    assert report["model_inference_calls"] == 0
    assert not blind.exists()


@pytest.mark.parametrize("interruption", (asyncio.CancelledError, KeyboardInterrupt))
def test_interruption_persists_stopped_active_request_with_unknown_count(
    monkeypatch, tmp_path, interruption
):
    arms = _fake_arms(tmp_path)
    runtime = runner.Runtime(
        arms=arms,
        tool=None,
        pilot_id=runner.INDEPENDENT_PILOT_ID,
        parser=None,
        request_by_id={"R03": runner.Request("R03", "query")},
        call_order=(("R03", "baseline"),),
        max_outer_calls=1,
        protocol="independent",
    )

    async def cancelled(*_args):
        raise interruption

    monkeypatch.setattr(runner, "_execute", cancelled)
    report, output = {"calls": []}, tmp_path / "result.json"

    result = runner.asyncio.run(
        runner._run(runtime, report, output, tmp_path / "blind.json")
    )

    assert result == 1
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["status"] == "STOPPED"
    assert saved["active_call"] == {
        "order": 1,
        "request_id": "R03",
        "arm": "baseline",
        "external_request_count": "unknown",
    }
    assert saved["calls"][0]["external_request_count"] == "unknown"


@pytest.mark.parametrize("interruption", (asyncio.CancelledError, KeyboardInterrupt))
def test_main_interrupt_during_call_writes_stopped_receipt_without_retry(
    monkeypatch, tmp_path, interruption
):
    _offline_environment(monkeypatch)
    arms = _fake_arms(tmp_path)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    output, blind = tmp_path / "result.json", tmp_path / "blind.json"
    hashes = {
        "protocol": "independent",
        "protocol_id": runner.INDEPENDENT_PROTOCOL_ID,
        "pilot_id": runner.INDEPENDENT_PILOT_ID,
        "baseline_tree_sha256": "a" * 64,
        "candidate_tree_sha256": "b" * 64,
        "candidate_diff_sha256": "c" * 64,
        "candidate_changed_files": list(runner.EXPECTED_DIFF_PATHS),
        "frozen_inputs_sha256": CORRECTED_INPUTS_SHA256,
        "source_manifest_sha256": CORRECTED_SOURCES_SHA256,
        "runner_input_sha256": INDEPENDENT_INPUT_SHA256,
        "source_prereg_sha256": INDEPENDENT_PREREG_SHA256,
        "max_outer_calls": 1,
        "max_esearch_calls": 3,
        "max_metadata_ids": 9,
        "request_by_id": {"R03": runner.Request("R03", "query")},
        "call_order": (("R03", "baseline"),),
        "preregistered_slugs": {
            ("R03", "baseline"): runner._call_slug(
                "independent", runner.INDEPENDENT_PILOT_ID, "R03", "baseline"
            )
        },
        "case_context_path": runner.CASE_CONTEXT_RELPATH,
        "case_context_protocol": runner.CASE_CONTEXT_PROTOCOL,
    }
    monkeypatch.setattr(
        runner, "_preflight", lambda _args: (arms, output, blind, hashes)
    )

    tool = type(
        "Tool",
        (),
        {
            "mcp_tool_name": "pubmed_search_with_fulltext",
            "map_parameters": staticmethod(lambda params: params),
        },
    )()
    monkeypatch.setattr(
        runner,
        "ToolRegistry",
        lambda **_: type("Registry", (), {"get_tool": lambda _self, _name: tool})(),
    )
    monkeypatch.setattr(runner, "ResponseParser", lambda _tool: None)
    attempts = []

    class InterruptingClient:
        def __init__(self, **_kwargs):
            pass

        async def initialize(self):
            return None

        async def call_tool(self, *_args, **_kwargs):
            attempts.append("call")
            raise interruption

    monkeypatch.setattr(runner, "MCPToolClient", InterruptingClient)
    argv = [
        "--protocol",
        "independent",
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
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert attempts == ["call"]
    assert saved["status"] == "STOPPED"
    assert saved["active_call"]["request_id"] == "R03"
    assert saved["active_call"]["arm"] == "baseline"
    assert saved["calls"][0]["external_request_count"] == "unknown"
    assert saved["calls"][0]["verified_esearch_rung_count"] == 0
    assert not blind.exists()
