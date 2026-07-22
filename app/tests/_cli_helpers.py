"""Shared server fixture and HTTP helpers for the cosci CLI e2e suites.

Both CLI test modules (``test_cli_commands.py`` and
``test_cli_commands_runs.py``) drive ``app.cli.main.main`` (the same entry
point the ``cosci`` console script calls) against a real uvicorn process
running the real engine on the deterministic offline backend with no API
keys, so the whole suite is offline. The streaming commands (``watch``,
``ask``) need the workflow's background task to run concurrently with the
SSE poll loop, which a real server provides and an in-process ASGI transport
does not; the non-streaming commands run against the same server for
fidelity and simplicity.

The ``cli_server`` fixture defined here is imported by name into each test
module (pytest resolves fixtures from the module namespace, so each module
gets its own FixtureDef with its own cache). The underlying uvicorn process
is therefore a refcounted module-level singleton: the first module to need
it spawns it, later modules reuse it, and the last finalizer terminates it —
one server process serves the whole session.
"""

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

from app.cli.main import main
from tests._client import wait_for

# app/ directory (parent of tests/), used as PYTHONPATH for the subprocess.
APP_DIR = pathlib.Path(__file__).resolve().parents[1]

# Ceiling for every poll loop in the CLI suites (server boot, run progress,
# status transitions). Offline runs finish in seconds standalone, but under
# the full app suite CPU contention stretches the same envelope past 30s,
# which is how these fixtures used to flake. Polling returns as soon as the
# predicate holds, so a generous ceiling costs green runs nothing while a
# genuine hang still fails deterministically.
_WAIT_BUDGET = 90.0

# Provider keys the parent env might carry; stripped from the server's env so
# the run and `ask` take the deterministic offline path rather than a paid call.
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
    """Return an unused localhost TCP port."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


def _spawn_server(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[str, subprocess.Popen[bytes]]:
    """Spawn an offline-backend uvicorn server on a free port.

    The server runs from an isolated cwd so neither ``load_dotenv`` nor
    pydantic-settings find the repo ``.env`` (no provider keys leak in), with a
    temp SQLite database and reports directory.
    """
    home = tmp_path_factory.mktemp("cli_server_home")
    reports = home / "reports"
    reports.mkdir()
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if k not in _KEY_VARS}
    env.update(
        {
            "PYTHONPATH": str(APP_DIR),
            # Force the deterministic offline backend and disable the
            # literature-review node so the spawned server never makes a paid
            # call or probes a (possibly live) local MCP server.
            "COSCIENTIST_FORCE_OFFLINE": "1",
            "FORCE_LITERATURE_REVIEW": "0",
            # Offline runs already skip contextual screening, but assert that
            # here rather than inheriting it: the screen calls a real (never
            # offline-routed) model, so leaving it on would make the suite's
            # offline guarantee depend on no provider key being reachable.
            "SEMANTIC_SAFETY_ENABLED": "false",
            "COSCIENTIST_DB_PATH": str(home / "coscientist.db"),
            "COSCIENTIST_REPORTS_DIR": str(reports),
        }
    )
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            # INFO so uvicorn emits HTTP access records, which the log
            # capture pipeline persists (asserted by the logs tests).
            "--log-level",
            "info",
        ],
        cwd=str(home),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        _await_health(proc, base)
    except BaseException:
        _terminate(proc)
        raise
    return base, proc


def _terminate(proc: subprocess.Popen[bytes]) -> None:
    """Stop the spawned server, escalating to kill if it lingers."""
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


_shared_server: tuple[str, subprocess.Popen[bytes]] | None = None
_shared_server_refs = 0


@pytest.fixture(scope="session")
def cli_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Yield the shared offline-backend server's base URL.

    See the module docstring: the process behind this fixture is shared
    across every CLI test module that imports it.
    """
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
    """Block until the server answers /health, or fail the fixture."""
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


# ---------------------------------------------------------------------------
# Helpers: invoke the CLI, and arrange/inspect state directly over HTTP.
# ---------------------------------------------------------------------------


def _invoke(base: str, *command: str, client_id: str | None = None) -> int:
    """Run one CLI command against ``base`` and return its exit code."""
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
    """Make a raw API call for arranging or inspecting test state."""
    headers = {"X-Client-ID": client_id} if client_id else {}
    return httpx.request(
        method, f"{base}{path}", headers=headers, json=json_body, timeout=30
    )


def _create(base: str, client_id: str, **config: object) -> str:
    """Create a run over HTTP and return its id."""
    body: dict[str, object] = {"research_goal": "CLI test: mitochondria"}
    body.update(config)
    resp = _api(base, "POST", "/api/runs", client_id=client_id, json_body=body)
    resp.raise_for_status()
    return str(resp.json()["id"])


def _start(base: str, run_id: str, client_id: str) -> None:
    """Start a run over HTTP (the endpoint requires a JSON body)."""
    resp = _api(
        base,
        "POST",
        f"/api/runs/{run_id}/start",
        client_id=client_id,
        json_body={},
    )
    resp.raise_for_status()


def _grep_logs(base: str, needle: str) -> bool:
    """Return whether any persisted log message contains ``needle``.

    Queries verbosely: these helpers verify capture, and high-volume
    records are hidden from the default view.
    """
    response = _api(base, "GET", f"/api/logs?q={needle}&limit=200&verbose=1")
    if response.status_code != 200:
        return False
    return bool(response.json().get("logs"))


def _status(base: str, run_id: str, client_id: str) -> str:
    """Return a run's current status over HTTP."""
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
    """Poll until ``run_id`` reaches ``target`` status, or raise on timeout."""
    if not wait_for(
        lambda: _status(base, run_id, client_id) == target, timeout=timeout
    ):
        raise AssertionError(f"run {run_id} did not reach {target}")


def _run_summary(base: str, run_id: str, client_id: str) -> dict[str, Any]:
    """Return a run's summary block over HTTP."""
    resp = _api(base, "GET", f"/api/runs/{run_id}", client_id=client_id)
    resp.raise_for_status()
    return dict(resp.json().get("summary") or {})
