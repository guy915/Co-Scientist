# Real servers permit concurrent SSE/workflow execution; fixture imports share a
# refcounted server process.

from __future__ import annotations

import os
import pathlib
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from app.cli.http import ApiClient, ApiClientOptions
from app.cli.main import main
from tests._client import wait_for

APP_DIR = pathlib.Path(__file__).resolve().parents[1]

# Full-suite CPU contention stretches offline latency; generous polling bounds
# cost successful runs nothing.
_WAIT_BUDGET = 90.0

_KEY_VARS = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AZURE_API_KEY",
    "DEEPSEEK_API_KEY",
    "CHAT_MODEL_NAME",
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


def _offline_server_env(
    home: pathlib.Path, reports: pathlib.Path
) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _KEY_VARS}
    env.update(
        {
            # Explicit engine PYTHONPATH prevents editable installs resolving
            # the main checkout instead of this branch.
            "PYTHONPATH": os.pathsep.join(
                [str(APP_DIR), str(APP_DIR.parent / "engine" / "src")]
            ),
            "COSCIENTIST_FORCE_OFFLINE": "1",
            "FORCE_LITERATURE_REVIEW": "0",
            # Disable contextual screening explicitly so hermeticity cannot
            # depend on credentials being absent.
            "SEMANTIC_SAFETY_ENABLED": "false",
            "COSCIENTIST_DB_PATH": str(home / "coscientist.db"),
            "COSCIENTIST_REPORTS_DIR": str(reports),
        }
    )
    return env


def _spawn_uvicorn(
    env: dict[str, str], home: pathlib.Path, port: int
) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "info",
        ],
        cwd=str(home),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _spawn_server(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[str, subprocess.Popen[bytes]]:
    # Use an isolated cwd so local dotenv credentials cannot leak into hermetic
    # server tests.
    home = tmp_path_factory.mktemp("cli_server_home")
    reports = home / "reports"
    reports.mkdir()
    port = _free_port()
    env = _offline_server_env(home, reports)
    proc = _spawn_uvicorn(env, home, port)
    base = f"http://127.0.0.1:{port}"
    try:
        _await_health(proc, base)
    except BaseException:
        _terminate(proc)
        raise
    return base, proc


def _terminate(proc: subprocess.Popen[bytes]) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


_shared_server: tuple[str, subprocess.Popen[bytes]] | None = None
_shared_server_refs = 0


@pytest.fixture(scope="session")
def cli_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    global _shared_server, _shared_server_refs
    if _shared_server is None:
        _shared_server = _spawn_server(tmp_path_factory)
    _shared_server_refs += 1
    try:
        yield _shared_server[0]
    finally:
        _shared_server_refs -= 1
        if _shared_server_refs == 0 and _shared_server is not None:
            _terminate(_shared_server[1])
            _shared_server = None


def _await_health(proc: subprocess.Popen[bytes], base: str) -> None:
    deadline = time.time() + _WAIT_BUDGET
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"server exited early (code {proc.returncode})")
        try:
            resp = httpx.get(f"{base}/health", timeout=1)
            if resp.status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.2)
    raise RuntimeError("server did not become healthy in time")


def _invoke(base: str, *command: str, client_id: str | None = None) -> int:
    argv = [*command, "--api-url", base]
    if client_id:
        argv += ["--client-id", client_id]
    return main(argv)


def _api(
    base: str,
    method: str,
    path: str,
    *,
    client_id: str | None = None,
    json_body: dict[str, object] | None = None,
) -> httpx.Response:
    headers = {"X-Client-ID": client_id} if client_id else {}
    return httpx.request(
        method, f"{base}{path}", headers=headers, json=json_body, timeout=30
    )


def _create(base: str, client_id: str, **config: object) -> str:
    body: dict[str, object] = {"research_goal": "CLI test: mitochondria"}
    body.update(config)
    resp = _api(base, "POST", "/api/runs", client_id=client_id, json_body=body)
    resp.raise_for_status()
    return str(resp.json()["id"])


def _start(base: str, run_id: str, client_id: str) -> None:
    resp = _api(
        base,
        "POST",
        f"/api/runs/{run_id}/start",
        client_id=client_id,
        json_body={},
    )
    resp.raise_for_status()


def _grep_logs(base: str, needle: str) -> bool:
    # Read verbose logs to verify capture; default views hide high-volume
    # records.
    response = _api(base, "GET", f"/api/logs?q={needle}&limit=200&verbose=1")
    if response.status_code != 200:
        return False
    return bool(response.json().get("logs"))


def _status(base: str, run_id: str, client_id: str) -> str:
    resp = _api(base, "GET", f"/api/runs/{run_id}", client_id=client_id)
    resp.raise_for_status()
    return str(resp.json()["status"])


def _wait_status(
    base: str,
    run_id: str,
    target: str,
    client_id: str,
    *,
    timeout: float = _WAIT_BUDGET,
) -> None:
    if not wait_for(
        lambda: _status(base, run_id, client_id) == target, timeout=timeout
    ):
        raise AssertionError(f"run {run_id} did not reach {target}")


def _run_summary(base: str, run_id: str, client_id: str) -> dict[str, Any]:
    resp = _api(base, "GET", f"/api/runs/{run_id}", client_id=client_id)
    resp.raise_for_status()
    return dict(resp.json().get("summary") or {})


def api_client(handler: object, **kwargs: object) -> ApiClient:
    # Remove retry waits without removing attempts so transport tests keep
    # production retry semantics.
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return ApiClient(
        "http://api.test",
        options=ApiClientOptions(transport=transport, retry_wait=0.0),
        **kwargs,  # type: ignore[arg-type]
    )
