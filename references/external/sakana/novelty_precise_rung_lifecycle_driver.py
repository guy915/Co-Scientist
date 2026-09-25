"""Supervise the keyless M11 precise-rung PubMed trial lifecycle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
HERE = ROOT / "references/external/sakana"
DRIVER_PATH = Path(__file__).resolve()
DRIVER_RELPATH = "references/external/sakana/novelty_precise_rung_lifecycle_driver.py"
LAUNCHER_PATH = HERE / "novelty_precise_rung_server_launcher.py"
LAUNCHER_RELPATH = "references/external/sakana/novelty_precise_rung_server_launcher.py"
RUNNER_PATH = HERE / "novelty_precise_rung_runner.py"
RUNNER_RELPATH = "references/external/sakana/novelty_precise_rung_runner.py"
INPUT_PATH = HERE / "novelty-precise-rung-01b2b-independent-input-v1.json"
INPUT_SHA256 = "a51c88afd45a81b84b614e730f0459f5e6bb567c3c37958982312106a50781c0"
AMENDMENT_PATH = HERE / "novelty-precise-rung-01b2b-protocol-amendment-2026-09-25.json"
CASE_CONTEXT_PATH = "references/external/sakana/novelty-precise-rung-01b2b-independent-case-context-2026-09-25.json"
CASE_CONTEXT_PROTOCOL = "novelty-precise-rung-independent-query-context-v1"
MCP_SECRET_ENV = "COSCIENTIST_MCP_SHARED_SECRET"
CACHE_ENV = "COSCIENTIST_LIT_REVIEW_DIR"
TRACE_ENV = "COSCIENTIST_PUBMED_PILOT_TRACE"
BUILD_ENV = "COSCIENTIST_PUBMED_PILOT_BUILD_ID"
LIFECYCLE_PARENT_PID_ENV = "COSCIENTIST_M11_RUNG_LIFECYCLE_PARENT_PID"
LIFECYCLE_DRIVER_PATH_ENV = "COSCIENTIST_M11_RUNG_LIFECYCLE_DRIVER_PATH"
LIFECYCLE_NONCE_ENV = "COSCIENTIST_M11_RUNG_LIFECYCLE_INVOCATION_NONCE"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_build_pins() -> dict[str, Any]:
    if (
        INPUT_PATH.is_symlink()
        or not INPUT_PATH.is_file()
        or _sha256(INPUT_PATH) != INPUT_SHA256
    ):
        raise ValueError("Independent runner inputs are missing or changed")
    inputs = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    if (
        inputs.get("input_artifact_id") != "M11-NOV-RUNG-01b2b-independent-input-v1"
        or inputs.get("status") != "runner_inputs_only_not_execution_authorization"
    ):
        raise ValueError("Independent runner input identity or status changed")
    return inputs["source_and_build_pins"] | inputs["run_artifact_paths"]


def _create_worktrees(temporary_root: Path, pins: dict[str, Any]) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    worktrees = temporary_root / "worktrees"
    worktrees.mkdir()
    try:
        for name in ("baseline", "candidate"):
            root = worktrees / name
            result = subprocess.run(
                ["git", "worktree", "add", "--detach", str(root), pins[name]["commit"]],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode:
                raise RuntimeError(f"Could not create {name} source worktree")
            roots[name] = root.resolve()
        return roots
    except Exception:
        _remove_worktrees(roots)
        raise


def _remove_worktrees(roots: dict[str, Path]) -> dict[str, bool]:
    result = {}
    for name, root in reversed(tuple(roots.items())):
        removed = (
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(root)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            ).returncode
            == 0
        )
        result[name] = removed
    return result


def _port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _listener_pid(port: int) -> int | None:
    result = subprocess.run(
        ["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        check=False,
    )
    pids = result.stdout.split()
    return (
        int(pids[0])
        if result.returncode == 0 and len(pids) == 1 and pids[0].isdigit()
        else None
    )


def _launch_receipt_path(output: Path, name: str) -> Path:
    return output.with_name(f"{output.stem}-{name}-launch.json")


def _launcher_stderr_path(output: Path, name: str) -> Path:
    return output.with_name(f"{output.stem}-{name}-stderr.log")


def _runner_stderr_path(output: Path) -> Path:
    return output.with_name(f"{output.stem}-runner-stderr.log")


def _launch_server(
    python: Path,
    root: Path,
    build_id: str,
    port: int,
    cache: Path,
    home: Path,
    receipt: Path,
    stderr_path: Path,
    secret: str,
) -> subprocess.Popen[bytes]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "TMPDIR": str(home),
        "PYTHONPATH": str(root / "engine"),
        "PYTHONNOUSERSITE": "1",
        "COSCIENTIST_REQUIRE_FREE_MODELS": "1",
        MCP_SECRET_ENV: secret,
        CACHE_ENV: str(cache),
        TRACE_ENV: "1",
        BUILD_ENV: build_id,
    }
    command = [
        str(python),
        str(LAUNCHER_PATH.resolve()),
        "--source-root",
        str(root),
        "--expected-tree-sha256",
        build_id,
        "--expected-source-sha256",
        _sha256(root / "engine/mcp_server/pubmed_client.py"),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--cache-dir",
        str(cache),
        "--receipt",
        str(receipt),
    ]
    with stderr_path.open("wb") as stderr:
        return subprocess.Popen(
            command,
            cwd=root / "engine",
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=stderr,
        )


def _wait_for_server(
    process: subprocess.Popen[bytes], port: int, receipt: Path, timeout: int
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Launcher exited before writing a ready receipt")
        if receipt.is_file() and not receipt.is_symlink():
            if (
                json.loads(receipt.read_text(encoding="utf-8")).get("serving_pid")
                != process.pid
            ):
                raise ValueError("Launcher receipt PID differs from its child")
            if _listener_pid(port) == process.pid:
                return {
                    "pid": process.pid,
                    "listener_pid": process.pid,
                    "port": port,
                    "receipt_path": str(receipt.resolve()),
                    "receipt_sha256": _sha256(receipt),
                }
        time.sleep(0.1)
    raise TimeoutError("Launcher did not produce a receipt and loopback listener")


def _committed_amendment(path: Path) -> bool:
    try:
        relative = path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return False
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    changed = subprocess.run(
        ["git", "status", "--porcelain", "--", relative],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return (
        tracked.returncode == 0
        and changed.returncode == 0
        and not changed.stdout.strip()
    )


def _amendment_ready(
    path: Path,
    records: dict[str, dict[str, Any]],
    launcher_hash: str,
    runner_hash: str,
    driver_hash: str,
) -> str | None:
    if path.is_symlink() or not path.is_file() or not _committed_amendment(path):
        return None
    raw = path.read_bytes()
    try:
        amendment = json.loads(raw)
    except json.JSONDecodeError:
        return None
    trace = amendment.get("trace_preflight", {})
    if (
        amendment.get("status") != "authorized_for_retrieval"
        or amendment.get("live_retrieval_authorized") is not True
        or amendment.get("runner_path") != RUNNER_RELPATH
        or amendment.get("runner_sha256") != runner_hash
        or amendment.get("case_context_path") != CASE_CONTEXT_PATH
        or amendment.get("case_context_protocol") != CASE_CONTEXT_PROTOCOL
        or trace.get("driver_path") != DRIVER_RELPATH
        or trace.get("driver_sha256") != driver_hash
        or trace.get("launcher_path") != LAUNCHER_RELPATH
        or trace.get("launcher_sha256") != launcher_hash
    ):
        return None
    for name, record in records.items():
        if trace.get(name) != {
            "receipt_path": record["receipt_path"],
            "receipt_sha256": record["receipt_sha256"],
        }:
            return None
        if _sha256(Path(record["receipt_path"])) != record["receipt_sha256"]:
            return None
    return hashlib.sha256(raw).hexdigest()


def _wait_for_amendment(
    path: Path, records: dict[str, dict[str, Any]], hashes: dict[str, str], timeout: int
) -> str:
    deadline = time.monotonic() + timeout
    while True:
        digest = _amendment_ready(
            path, records, hashes["launcher"], hashes["runner"], hashes["driver"]
        )
        if digest:
            return digest
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Independent amendment does not pin this launch")
        time.sleep(min(0.25, remaining))


def _start_runner(
    python: Path,
    roots: dict[str, Path],
    pins: dict[str, Any],
    ports: dict[str, int],
    caches: dict[str, Path],
    records: dict[str, dict[str, Any]],
    secret: str,
    nonce: str,
    home: Path,
    result_path: Path,
    blind_path: Path,
    stderr_path: Path,
) -> subprocess.Popen[bytes]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "TMPDIR": str(home),
        "PYTHONPATH": os.pathsep.join(
            (str(ROOT / "engine/src"), str(ROOT / "engine"), str(HERE))
        ),
        "PYTHONNOUSERSITE": "1",
        "COSCIENTIST_REQUIRE_FREE_MODELS": "1",
        MCP_SECRET_ENV: secret,
        LIFECYCLE_PARENT_PID_ENV: str(os.getpid()),
        LIFECYCLE_DRIVER_PATH_ENV: str(DRIVER_PATH.resolve()),
        LIFECYCLE_NONCE_ENV: nonce,
    }
    command = [str(python), str(RUNNER_PATH.resolve()), "--protocol", "independent"]
    for name in ("baseline", "candidate"):
        command.extend(
            [
                f"--{name}-url",
                f"http://127.0.0.1:{ports[name]}/mcp",
                f"--{name}-root",
                str(roots[name]),
                f"--{name}-cache",
                str(caches[name]),
                f"--{name}-pid",
                str(records[name]["pid"]),
                f"--{name}-launch-receipt",
                records[name]["receipt_path"],
            ]
        )
    command.extend(
        [
            "--output",
            str(result_path),
            "--blind-output",
            str(blind_path),
        ]
    )
    with stderr_path.open("wb") as stderr:
        return subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=stderr,
        )


def _stop(process: subprocess.Popen[bytes]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "pid": process.pid,
        "term_sent": False,
        "kill_sent": False,
    }
    try:
        if process.poll() is None:
            process.terminate()
            result["term_sent"] = True
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                result["kill_sent"] = True
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    result["kill_timed_out"] = True
        else:
            process.wait(timeout=5)
    except OSError as error:
        result["error_class"] = type(error).__name__
    result.update(
        returncode=process.returncode, child_absent=process.poll() is not None
    )
    return result


def _result_status(path: Path) -> str | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    status = record.get("status") if isinstance(record, dict) else None
    return status if isinstance(status, str) else None


def _stop_runner(process: subprocess.Popen[bytes], result_path: Path) -> dict[str, Any]:
    # The runner catches SIGINT and durably writes STOPPED before it exits.
    result: dict[str, Any] = {
        "pid": process.pid,
        "interrupt_sent": False,
        "term_sent": False,
        "kill_sent": False,
    }
    try:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            result["interrupt_sent"] = True
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                result["result_status_before_terminate"] = _result_status(result_path)
                process.terminate()
                result["term_sent"] = True
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    result["result_status_before_kill"] = _result_status(result_path)
                    process.kill()
                    result["kill_sent"] = True
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        result["kill_timed_out"] = True
        else:
            process.wait(timeout=5)
    except OSError as error:
        result["error_class"] = type(error).__name__
    result.update(
        returncode=process.returncode,
        child_absent=process.poll() is not None,
        result_status=_result_status(result_path),
    )
    return result


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _persist_child_stderr(
    source: Path, destination: Path, secret: str
) -> dict[str, Any]:
    limit = 4096
    secret_bytes = secret.encode()
    size = source.stat().st_size
    with source.open("rb") as stream:
        stream.seek(max(0, size - limit - len(secret_bytes)))
        data = stream.read(limit + len(secret_bytes))
    data = data.replace(secret_bytes, b"<redacted>")[-limit:]
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return {
        "path": str(destination),
        "bytes": len(data),
        "truncated": size > limit,
        "secret_redacted": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--amendment", type=Path)
    parser.add_argument("--mcp-python", type=Path)
    parser.add_argument("--engine-python", type=Path)
    parser.add_argument("--startup-timeout-seconds", type=int, default=90)
    parser.add_argument("--amendment-wait-seconds", type=int, default=900)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = args.receipt.expanduser().absolute()
    amendment = (args.amendment or AMENDMENT_PATH).expanduser().resolve()
    mcp_python = args.mcp_python.expanduser().absolute() if args.mcp_python else None
    engine_python = (
        args.engine_python.expanduser().absolute() if args.engine_python else None
    )
    reserved = False
    receipt: dict[str, Any] = {
        "schema_version": "novelty_precise_rung_lifecycle_receipt_v1",
        "pilot": "M11-NOV-RUNG-01b2b",
        "driver_path": DRIVER_RELPATH,
        "driver_sha256": _sha256(DRIVER_PATH),
        "model_inference_calls": 0,
        "runner_started": False,
        "runner_exit_code": None,
        "server_children": {},
        "cleanup": {},
        "mcp_python": str(mcp_python) if mcp_python else None,
        "engine_python": str(engine_python) if engine_python else None,
        "started_at_utc": _now(),
    }
    processes: dict[str, subprocess.Popen[bytes]] = {}
    runner: subprocess.Popen[bytes] | None = None
    roots: dict[str, Path] = {}
    launcher_stderr: dict[str, Path] = {}
    runner_stderr: Path | None = None
    runner_result_path: Path | None = None
    temporary_root: Path | None = None
    secret: str | None = None
    status, stage, error_class = "aborted", "preflight", None
    previous_sigterm_handler: Any = None
    termination_signal: str | None = None

    def handle_sigterm(signum: int, _frame: Any) -> None:
        nonlocal termination_signal
        termination_signal = signal.Signals(signum).name
        raise KeyboardInterrupt

    try:
        if output.resolve() == amendment:
            raise ValueError("Lifecycle receipt path must not be the amendment")
        if output.exists() or output.is_symlink():
            raise FileExistsError("Lifecycle receipt path must be new")
        output.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        reserved = True
        previous_sigterm_handler = signal.signal(signal.SIGTERM, handle_sigterm)
        if args.startup_timeout_seconds < 1 or args.amendment_wait_seconds < 0:
            raise ValueError("Timeouts must be positive; amendment wait may be zero")
        if amendment != AMENDMENT_PATH.resolve():
            raise ValueError("Only the registered independent amendment is accepted")
        if (
            mcp_python is None
            or not mcp_python.is_file()
            or not os.access(mcp_python, os.X_OK)
        ):
            raise FileNotFoundError("MCP Python interpreter is not executable")
        if (
            engine_python is None
            or not engine_python.is_file()
            or not os.access(engine_python, os.X_OK)
        ):
            raise FileNotFoundError("Engine Python interpreter is not executable")
        receipt_paths = {
            name: _launch_receipt_path(output, name)
            for name in ("baseline", "candidate")
        }
        diagnostic_paths = {
            name: _launcher_stderr_path(output, name)
            for name in ("baseline", "candidate")
        }
        diagnostic_paths["runner"] = _runner_stderr_path(output)
        if any(
            path.exists() or path.is_symlink()
            for path in (*receipt_paths.values(), *diagnostic_paths.values())
        ):
            raise FileExistsError("Launcher artifact paths must be new")
        pins = _read_build_pins()
        result_path = ROOT / pins["result_path"]
        blind_path = ROOT / pins["blind_review_path"]
        runner_result_path = result_path.resolve()
        if result_path.exists() or blind_path.exists() or result_path == blind_path:
            raise FileExistsError("Preregistered result paths must be new")

        temporary_root = Path(tempfile.mkdtemp(prefix="m11-rung-", dir=output.parent))
        runner_stderr = temporary_root / "runner.stderr"
        roots = _create_worktrees(temporary_root, pins)
        cache_roots = {name: temporary_root / f"{name}-cache" for name in roots}
        homes = {name: temporary_root / f"{name}-home" for name in roots}
        ports: dict[str, int] = {}
        for name in roots:
            cache_roots[name].mkdir()
            homes[name].mkdir()
            ports[name] = _port()
        if len(set(ports.values())) != 2:
            raise RuntimeError("Baseline and candidate ports must be distinct")

        secret = secrets.token_urlsafe(48)
        hashes = {
            "launcher": _sha256(LAUNCHER_PATH),
            "runner": _sha256(RUNNER_PATH),
            "driver": _sha256(DRIVER_PATH),
        }
        stage = "server_startup"
        for name in ("baseline", "candidate"):
            stderr_path = temporary_root / f"{name}-launcher.stderr"
            launcher_stderr[name] = stderr_path
            process = _launch_server(
                mcp_python,
                roots[name],
                pins[name]["mcp_server_tree_sha256"],
                ports[name],
                cache_roots[name],
                homes[name],
                receipt_paths[name],
                stderr_path,
                secret,
            )
            processes[name] = process
            record = _wait_for_server(
                process,
                ports[name],
                receipt_paths[name],
                args.startup_timeout_seconds,
            )
            receipt["server_children"][name] = record

        stage = "amendment_gate"
        receipt["amendment_path"] = str(amendment)
        receipt["amendment_sha256"] = _wait_for_amendment(
            amendment,
            receipt["server_children"],
            hashes,
            args.amendment_wait_seconds,
        )
        stage = "runner"
        runner_home = temporary_root / "runner-home"
        runner_home.mkdir()
        runner = _start_runner(
            engine_python,
            roots,
            pins,
            ports,
            cache_roots,
            receipt["server_children"],
            secret,
            secrets.token_urlsafe(32),
            runner_home,
            runner_result_path,
            blind_path.resolve(),
            runner_stderr,
        )
        receipt["runner_pid"] = runner.pid
        receipt["runner_started"] = True
        receipt["runner_exit_code"] = runner.wait()
        status = "completed" if receipt["runner_exit_code"] == 0 else "runner_failed"
    except KeyboardInterrupt:
        status, error_class = "interrupted", "KeyboardInterrupt"
        if termination_signal:
            receipt["termination_signal"] = termination_signal
    except Exception as error:
        error_class = type(error).__name__
    finally:
        if previous_sigterm_handler is not None:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if runner is not None:
            try:
                assert runner_result_path is not None
                receipt["cleanup"]["runner"] = _stop_runner(runner, runner_result_path)
            except Exception as error:
                receipt["cleanup"]["runner"] = {
                    "pid": runner.pid,
                    "error_class": type(error).__name__,
                    "child_absent": runner.poll() is not None,
                }
            receipt["runner_exit_code"] = runner.returncode
        for name in reversed(("baseline", "candidate")):
            if name not in processes:
                continue
            process = processes[name]
            try:
                cleanup = _stop(process)
            except Exception as error:
                cleanup = {
                    "pid": process.pid,
                    "error_class": type(error).__name__,
                    "child_absent": process.poll() is not None,
                }
            try:
                cleanup["listener_absent"] = _listener_pid(ports[name]) is None
            except Exception as error:
                cleanup["listener_absent"] = False
                cleanup["listener_error_class"] = type(error).__name__
            receipt["cleanup"][name] = cleanup
        if roots:
            try:
                receipt["cleanup"]["worktrees"] = _remove_worktrees(roots)
            except Exception as error:
                receipt["cleanup"]["worktrees_error_class"] = type(error).__name__
        if status != "completed" and secret:
            diagnostics = {}
            for name, path in launcher_stderr.items():
                if not path.is_file():
                    continue
                try:
                    diagnostics[name] = _persist_child_stderr(
                        path, _launcher_stderr_path(output, name), secret
                    )
                except Exception as error:
                    diagnostics[name] = {"error_class": type(error).__name__}
            if diagnostics:
                receipt["launcher_diagnostics"] = diagnostics
            if (
                runner is not None
                and runner_stderr is not None
                and runner_stderr.is_file()
            ):
                try:
                    receipt["runner_diagnostics"] = _persist_child_stderr(
                        runner_stderr, _runner_stderr_path(output), secret
                    )
                except Exception as error:
                    receipt["runner_diagnostics"] = {
                        "error_class": type(error).__name__
                    }
        if temporary_root is not None:
            shutil.rmtree(temporary_root, ignore_errors=True)
            receipt["cleanup"]["temporary_root_removed"] = not temporary_root.exists()
        receipt.update(status=status, ended_at_utc=_now())
        if error_class:
            receipt.update(error_stage=stage, error_class=error_class)
        if reserved:
            _write_receipt(output, receipt)
        if previous_sigterm_handler is not None:
            signal.signal(signal.SIGTERM, previous_sigterm_handler)

    if status == "completed":
        return 0
    if status == "runner_failed":
        return receipt["runner_exit_code"] or 1
    if status == "interrupted":
        return 130
    print(
        f"Lifecycle driver stopped: {error_class or 'preflight failure'}",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
