"""Offline CLI tests for the precise-rung lifecycle supervisor."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from typing import Any

import pytest

import novelty_precise_rung_lifecycle_driver as driver

MCP_TEST_PYTHON = Path("/Users/guy/Code/co-scientist/.venv-mcp/bin/python")
ENGINE_TEST_PYTHON = Path(
    "/Users/guy/.codex/worktrees/external-m10-robin/co-scientist/.venv/bin/python"
)
TEST_SECRET = "offline-test-secret-" + "x" * 44


class _Process:
    def __init__(
        self,
        pid: int,
        kind: str,
        runner_exit: int | None = 0,
        *,
        server_exit: int | None = None,
        report_path: Path | None = None,
        wait_timeouts: int = 0,
        ignore_terminate: bool = False,
    ) -> None:
        self.pid = pid
        self.kind = kind
        self.returncode = server_exit if kind == "server" else runner_exit
        self.report_path = report_path
        self.wait_timeouts = wait_timeouts
        self.ignore_terminate = ignore_terminate
        self.term_calls = 0
        self.kill_calls = 0
        self.signals: list[int] = []
        self.interrupt_wait = False
        self.interrupt_signal: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.interrupt_wait:
            self.interrupt_wait = False
            raise KeyboardInterrupt
        if self.interrupt_signal is not None:
            signum = self.interrupt_signal
            self.interrupt_signal = None
            os.kill(os.getpid(), signum)
        if self.wait_timeouts:
            self.wait_timeouts -= 1
            raise subprocess.TimeoutExpired("runner", timeout)
        if self.returncode is None:
            self.returncode = -15 if self.term_calls else -9
        return self.returncode

    def terminate(self) -> None:
        self.term_calls += 1
        if not self.ignore_terminate and self.returncode is None:
            self.returncode = -15

    def send_signal(self, signum: int) -> None:
        self.signals.append(signum)
        if signum == signal.SIGINT:
            if self.report_path is not None:
                self.report_path.write_text('{"status": "STOPPED"}', encoding="utf-8")
            if not self.ignore_terminate:
                self.returncode = 2

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9


def _authorized_amendment(
    amendment_path: Path,
    receipt_path: Path,
    launcher_path: Path,
    runner_path: Path,
) -> None:
    deadline = time.monotonic() + 3
    launch_paths = {
        name: receipt_path.with_name(f"{receipt_path.stem}-{name}-launch.json")
        for name in ("baseline", "candidate")
    }
    while time.monotonic() < deadline and not all(
        path.is_file() for path in launch_paths.values()
    ):
        time.sleep(0.005)
    if not all(path.is_file() for path in launch_paths.values()):
        return
    pins = {
        name: {
            "receipt_path": str(path.resolve()),
            "receipt_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for name, path in launch_paths.items()
    }
    amendment_path.write_text(
        json.dumps(
            {
                "status": "authorized_for_retrieval",
                "live_retrieval_authorized": True,
                "runner_path": driver.RUNNER_RELPATH,
                "runner_sha256": hashlib.sha256(runner_path.read_bytes()).hexdigest(),
                "case_context_path": driver.CASE_CONTEXT_PATH,
                "case_context_protocol": driver.CASE_CONTEXT_PROTOCOL,
                "trace_preflight": {
                    "driver_path": driver.DRIVER_RELPATH,
                    "driver_sha256": hashlib.sha256(
                        driver.DRIVER_PATH.read_bytes()
                    ).hexdigest(),
                    "launcher_path": driver.LAUNCHER_RELPATH,
                    "launcher_sha256": hashlib.sha256(
                        launcher_path.read_bytes()
                    ).hexdigest(),
                    **pins,
                },
            }
        ),
        encoding="utf-8",
    )


def _run_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    runner_exit: int | None = 0,
    runner_signal: int | None = None,
    launcher_exit: int | None = None,
    runner_cleanup_timeouts: int = 0,
    amendment_committed: bool = True,
) -> tuple[int, dict[str, Any], list[_Process], list[list[str]]]:
    launcher = tmp_path / "launcher.py"
    runner = tmp_path / "runner.py"
    repository_root = tmp_path / "repo"
    mcp_python = tmp_path / "mcp-python"
    engine_python = tmp_path / "engine-python"
    launcher.write_text("# launcher fixture\n", encoding="utf-8")
    runner.write_text("# runner fixture\n", encoding="utf-8")
    mcp_python_target = tmp_path / "mcp-python-real"
    engine_python_target = tmp_path / "engine-python-real"
    mcp_python_target.write_text("#!/bin/sh\n", encoding="utf-8")
    engine_python_target.write_text("#!/bin/sh\n", encoding="utf-8")
    mcp_python_target.chmod(0o755)
    engine_python_target.chmod(0o755)
    mcp_python.symlink_to(mcp_python_target)
    engine_python.symlink_to(engine_python_target)
    amendment = tmp_path / "independent-amendment.json"
    output = tmp_path / "driver-receipt.json"
    monkeypatch.setattr(driver, "LAUNCHER_PATH", launcher)
    monkeypatch.setattr(driver, "RUNNER_PATH", runner)
    monkeypatch.setattr(driver, "AMENDMENT_PATH", amendment)
    monkeypatch.setattr(
        driver, "_committed_amendment", lambda _path: amendment_committed, raising=False
    )
    monkeypatch.setattr(driver, "ROOT", repository_root)
    monkeypatch.setattr(
        driver.secrets,
        "token_urlsafe",
        lambda length: TEST_SECRET if length == 48 else "n" * length,
    )
    monkeypatch.setattr(
        driver,
        "_read_build_pins",
        lambda: {
            "baseline": {"commit": "1" * 40, "mcp_server_tree_sha256": "a" * 64},
            "candidate": {"commit": "2" * 40, "mcp_server_tree_sha256": "b" * 64},
            "candidate_diff_sha256": "c" * 64,
            "result_path": "references/external/sakana/frozen-result.json",
            "blind_review_path": "references/external/sakana/frozen-blind.json",
        },
    )
    roots = {name: tmp_path / f"{name}-root" for name in ("baseline", "candidate")}
    for root in roots.values():
        source = root / "engine/mcp_server"
        source.mkdir(parents=True)
        (source / "pubmed_client.py").write_text("# pinned fixture\n", encoding="utf-8")
    monkeypatch.setattr(driver, "_create_worktrees", lambda _tmp, _pins: roots)
    monkeypatch.setattr(driver, "_remove_worktrees", lambda _roots: {"removed": True})
    next_port = iter((62837, 62838))
    monkeypatch.setattr(driver, "_port", lambda: next(next_port))
    processes: list[_Process] = []
    commands: list[list[str]] = []
    by_pid: dict[int, _Process] = {}

    def fake_popen(command, **kwargs):
        argv = [str(item) for item in command]
        commands.append(argv)
        if str(launcher) == argv[1]:
            assert argv[0] == str(mcp_python.absolute())
            name = (
                "baseline"
                if "--expected-tree-sha256" in argv and "a" * 64 in argv
                else "candidate"
            )
            pid = 64101 if name == "baseline" else 64102
            receipt_path = Path(argv[argv.index("--receipt") + 1])
            port = int(argv[argv.index("--port") + 1])
            source_root = Path(argv[argv.index("--source-root") + 1])
            cache_root = Path(argv[argv.index("--cache-dir") + 1])
            receipt_path.write_text(
                json.dumps(
                    {
                        "schema_version": "novelty_precise_rung_launcher_receipt_v1",
                        "status": "passed",
                        "launcher_path": driver.LAUNCHER_RELPATH,
                        "launcher_sha256": hashlib.sha256(
                            launcher.read_bytes()
                        ).hexdigest(),
                        "source_root": str(source_root.resolve()),
                        "source_tree_sha256": "a" * 64
                        if name == "baseline"
                        else "b" * 64,
                        "serving_pid": pid,
                        "bind_host": "127.0.0.1",
                        "bind_port": port,
                        "cache_root": str(cache_root.resolve()),
                        "trace_enabled": True,
                        "secret_length": 64,
                        "secret_free": True,
                    }
                ),
                encoding="utf-8",
            )
            if launcher_exit is not None and name == "baseline":
                secret = kwargs["env"][driver.MCP_SECRET_ENV].encode()
                kwargs["stderr"].write(b"x" * 6000 + secret)
            process = _Process(
                pid,
                "server",
                server_exit=launcher_exit if name == "baseline" else None,
            )
            assert kwargs["env"]["PYTHONPATH"] == str(
                Path(argv[argv.index("--source-root") + 1]) / "engine"
            )
        else:
            assert str(runner) == argv[1]
            assert argv[0] == str(engine_python.absolute())
            authorized = json.loads(amendment.read_text(encoding="utf-8"))
            assert authorized["live_retrieval_authorized"] is True
            for name in ("baseline", "candidate"):
                pin = authorized["trace_preflight"][name]
                assert Path(pin["receipt_path"]).is_file()
                assert (
                    hashlib.sha256(Path(pin["receipt_path"]).read_bytes()).hexdigest()
                    == pin["receipt_sha256"]
                )
            process = _Process(64103, "runner", runner_exit)
            report_path = Path(argv[argv.index("--output") + 1])
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_status = "COMPLETED" if runner_exit == 0 else "STOPPED"
            if runner_exit is None:
                report_status = "RUNNING"
            report_path.write_text(
                json.dumps({"status": report_status}), encoding="utf-8"
            )
            process.report_path = report_path
            process.wait_timeouts = runner_cleanup_timeouts
            process.ignore_terminate = runner_cleanup_timeouts > 0
            process.interrupt_wait = runner_exit is None and runner_signal is None
            process.interrupt_signal = runner_signal
            if runner_exit not in (None, 0):
                kwargs["stderr"].write(b"y" * 6000 + TEST_SECRET.encode())
            environment = kwargs["env"]
            assert environment[driver.LIFECYCLE_PARENT_PID_ENV] == str(os.getpid())
            assert environment[driver.LIFECYCLE_DRIVER_PATH_ENV] == str(
                driver.DRIVER_PATH.resolve()
            )
            assert len(environment[driver.LIFECYCLE_NONCE_ENV]) >= 32
            assert environment[driver.MCP_SECRET_ENV] not in argv
            assert environment["PYTHONPATH"].split(os.pathsep) == [
                str(driver.ROOT / "engine/src"),
                str(driver.ROOT / "engine"),
                str(driver.HERE),
            ]
        processes.append(process)
        by_pid[process.pid] = process
        return process

    monkeypatch.setattr(driver.subprocess, "Popen", fake_popen)

    def fake_listener(port: int) -> int | None:
        pid = 64101 if port == 62837 else 64102
        return pid if by_pid[pid].poll() is None else None

    monkeypatch.setattr(driver, "_listener_pid", fake_listener)
    authorizer = None
    if launcher_exit is None:
        authorizer = threading.Thread(
            target=_authorized_amendment,
            args=(amendment, output, launcher, runner),
            daemon=True,
        )
        authorizer.start()
    result = driver.main(
        [
            "--receipt",
            str(output),
            "--mcp-python",
            str(mcp_python),
            "--engine-python",
            str(engine_python),
            "--amendment-wait-seconds",
            "2",
        ]
    )
    if authorizer is not None:
        authorizer.join(timeout=3)
    return result, json.loads(output.read_text(encoding="utf-8")), processes, commands


def test_cli_starts_two_pinned_servers_then_runner_and_retains_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result, receipt, processes, commands = _run_cli(monkeypatch, tmp_path)

    assert result == 0
    assert sum(driver.LAUNCHER_PATH.name in command[1] for command in commands) == 2
    assert str(driver.RUNNER_PATH.resolve()) in commands[-1][1]
    assert commands[-1][commands[-1].index("--protocol") + 1] == "independent"
    assert [process.pid for process in processes] == [64101, 64102, 64103]
    assert [process.term_calls for process in processes[:2]] == [1, 1]
    assert receipt["runner_exit_code"] == 0
    assert receipt["server_children"]["baseline"]["pid"] == 64101
    assert receipt["server_children"]["candidate"]["pid"] == 64102
    assert receipt["cleanup"]["baseline"]["child_absent"] is True
    assert receipt["cleanup"]["candidate"]["child_absent"] is True
    encoded = json.dumps(receipt)
    assert "COSCIENTIST_MCP_SHARED_SECRET" not in encoded
    assert "offline-test-secret" not in encoded
    assert receipt["model_inference_calls"] == 0


def test_uncommitted_authorization_never_starts_runner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result, receipt, processes, _commands = _run_cli(
        monkeypatch, tmp_path, amendment_committed=False
    )

    assert result == 2
    assert receipt["error_stage"] == "amendment_gate"
    assert receipt["runner_started"] is False
    assert [process.pid for process in processes] == [64101, 64102]


def test_driver_requires_absolute_script_invocation() -> None:
    relative = Path("references/external/sakana") / driver.DRIVER_PATH.name
    with pytest.raises(ValueError, match="absolute"):
        driver._require_absolute_script_invocation(relative)
    driver._require_absolute_script_invocation(driver.DRIVER_PATH)


def test_cli_interrupt_still_terminates_children_and_writes_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result, receipt, processes, _commands = _run_cli(
        monkeypatch, tmp_path, runner_exit=None
    )

    assert result == 130
    assert receipt["status"] == "interrupted"
    assert receipt["runner_exit_code"] == 2
    assert [process.term_calls for process in processes] == [1, 1, 0]
    assert receipt["cleanup"]["baseline"]["child_absent"] is True
    assert receipt["cleanup"]["candidate"]["child_absent"] is True
    assert receipt["cleanup"]["runner"]["child_absent"] is True
    assert receipt["cleanup"]["runner"]["result_status"] == "STOPPED"
    assert processes[-1].signals == [signal.SIGINT]
    assert processes[-1].term_calls == 0


def test_runner_stop_verifies_stopped_result_before_kill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result, receipt, processes, _commands = _run_cli(
        monkeypatch,
        tmp_path,
        runner_exit=None,
        runner_signal=signal.SIGTERM,
        runner_cleanup_timeouts=2,
    )

    assert result == 130
    assert receipt["status"] == "interrupted"
    cleanup = receipt["cleanup"]["runner"]
    assert cleanup["result_status_before_terminate"] == "STOPPED"
    assert cleanup["result_status_before_kill"] == "STOPPED"
    assert cleanup["kill_sent"] is True
    assert processes[-1].signals == [signal.SIGINT]


def test_runner_failure_persists_bounded_secret_free_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result, receipt, _processes, _commands = _run_cli(
        monkeypatch, tmp_path, runner_exit=7
    )

    diagnostic = receipt["runner_diagnostics"]
    contents = Path(diagnostic["path"]).read_bytes()
    assert result == 7
    assert receipt["status"] == "runner_failed"
    assert receipt["cleanup"]["runner"]["result_status"] == "STOPPED"
    assert diagnostic["truncated"] is True
    assert diagnostic["secret_redacted"] is True
    assert len(contents) <= 4096
    assert TEST_SECRET.encode() not in contents
    assert b"<redacted>" in contents


def test_cli_sigterm_records_interruption_and_cleans_up_children(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result, receipt, processes, _commands = _run_cli(
        monkeypatch, tmp_path, runner_exit=None, runner_signal=signal.SIGTERM
    )

    assert result == 130
    assert receipt["status"] == "interrupted"
    assert receipt["termination_signal"] == "SIGTERM"
    assert receipt["model_inference_calls"] == 0
    assert [process.term_calls for process in processes] == [1, 1, 0]
    assert receipt["cleanup"]["baseline"]["child_absent"] is True
    assert receipt["cleanup"]["candidate"]["child_absent"] is True
    assert receipt["cleanup"]["runner"]["child_absent"] is True


def test_launcher_failure_persists_bounded_secret_free_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result, receipt, processes, _commands = _run_cli(
        monkeypatch, tmp_path, launcher_exit=2
    )

    diagnostic = receipt["launcher_diagnostics"]["baseline"]
    log_path = Path(diagnostic["path"])
    contents = log_path.read_bytes()
    assert result == 2
    assert receipt["status"] == "aborted"
    assert receipt["error_stage"] == "server_startup"
    assert diagnostic["truncated"] is True
    assert diagnostic["secret_redacted"] is True
    assert len(contents) <= 4096
    assert TEST_SECRET.encode() not in contents
    assert TEST_SECRET not in json.dumps(receipt)
    assert b"<redacted>" in contents
    assert contents.endswith(b"<redacted>")
    assert [process.term_calls for process in processes] == [0]
    assert receipt["cleanup"]["baseline"]["child_absent"] is True


@pytest.mark.parametrize(
    "failure", ["invalid_timeout", "missing_pins", "missing_interpreter"]
)
def test_preflight_failure_writes_abort_receipt_without_starting_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: str,
) -> None:
    amendment = tmp_path / "amendment.json"
    receipt_path = tmp_path / "abort-receipt.json"
    monkeypatch.setattr(driver, "AMENDMENT_PATH", amendment)
    if failure == "missing_pins":
        monkeypatch.setattr(
            driver,
            "_read_build_pins",
            lambda: (_ for _ in ()).throw(ValueError("pins unavailable")),
        )
    monkeypatch.setattr(
        driver.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("preflight failure launched a child"),
    )
    args = [
        "--receipt",
        str(receipt_path),
        "--amendment",
        str(amendment),
    ]
    if failure != "missing_interpreter":
        args.extend(
            [
                "--mcp-python",
                str(MCP_TEST_PYTHON),
                "--engine-python",
                str(ENGINE_TEST_PYTHON),
            ]
        )
    if failure == "invalid_timeout":
        args.extend(["--startup-timeout-seconds", "0"])

    result = driver.main(args)

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert result == 2
    assert receipt["status"] == "aborted"
    assert receipt["error_stage"] == "preflight"
    assert receipt["model_inference_calls"] == 0
    assert receipt["runner_started"] is False


@pytest.mark.skipif(
    not MCP_TEST_PYTHON.is_file() or not ENGINE_TEST_PYTHON.is_file(),
    reason="the pinned local MCP and engine environments are unavailable",
)
def test_runtime_interpreters_import_their_pinned_modules_offline() -> None:
    mcp_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(driver.ROOT / "engine"),
        "PYTHONNOUSERSITE": "1",
    }
    engine_env = {
        **mcp_env,
        "PYTHONPATH": os.pathsep.join(
            (
                str(driver.ROOT / "engine/src"),
                str(driver.ROOT / "engine"),
                str(driver.HERE),
            )
        ),
    }
    subprocess.run(
        [str(MCP_TEST_PYTHON), "-c", "import Bio; import mcp_server.server"],
        cwd=driver.ROOT / "engine",
        env=mcp_env,
        check=True,
        capture_output=True,
        timeout=30,
    )
    subprocess.run(
        [
            str(ENGINE_TEST_PYTHON),
            "-c",
            "import litellm; import co_scientist.mcp_client; "
            "import co_scientist.tools.response_parser; import novelty_sort_pilot",
        ],
        cwd=driver.ROOT,
        env=engine_env,
        check=True,
        capture_output=True,
        timeout=30,
    )
