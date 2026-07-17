"""End-to-end tests for the cosci CLI against a spawned mock-mode server.

Every command is driven through ``app.cli.main.main`` (the same entry point the
``cosci`` console script calls) against a real uvicorn process running the
deterministic mock provider with no API keys, so the whole suite is offline.
The streaming commands (``watch``, ``ask``) need the workflow's background task
to run concurrently with the SSE poll loop, which a real server provides and an
in-process ASGI transport does not; the non-streaming commands run against the
same server for fidelity and simplicity.
"""

from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import time
from collections.abc import Iterator

import httpx
import pytest

from app.cli.main import main

# app/ directory (parent of tests/), used as PYTHONPATH for the subprocess.
APP_DIR = pathlib.Path(__file__).resolve().parents[1]

# Provider keys the parent env might carry; stripped from the server's env so
# `ask` degrades to its offline fallback rather than making a paid call.
_KEY_VARS = (
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "CHAT_MODEL_NAME",
)


def _free_port() -> int:
    """Return an unused localhost TCP port."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


@pytest.fixture(scope="session")
def cli_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Spawn a mock-mode uvicorn server on a free port and yield its base URL.

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
            "COSCIENTIST_FORCE_MOCK": "1",
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
            "--log-level",
            "warning",
        ],
        cwd=str(home),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        _await_health(proc, base)
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _await_health(proc: subprocess.Popen[bytes], base: str) -> None:
    """Block until the server answers /health, or fail the fixture."""
    deadline = time.time() + 30
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
    timeout: float = 30.0,
) -> None:
    """Poll until ``run_id`` reaches ``target`` status, or raise on timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _status(base, run_id, client_id) == target:
            return
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not reach {target}")


@pytest.fixture(scope="module")
def completed_run(cli_server: str) -> tuple[str, str, str]:
    """Return (base, run_id, client_id) for one completed express run."""
    client_id = "reads"
    run_id = _create(cli_server, client_id, tier="standard")
    _start(cli_server, run_id, client_id)
    _wait_status(cli_server, run_id, "completed", client_id)
    return cli_server, run_id, client_id


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def test_status_reports_mock_mode(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _invoke(cli_server, "status") == 0
    out = capsys.readouterr().out
    assert "provider" in out
    assert "mock" in out


def test_status_json(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _invoke(cli_server, "status", "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["health"]["status"] == "healthy"
    assert data["status"]["provider"] == "mock"


# ---------------------------------------------------------------------------
# Create / list / show
# ---------------------------------------------------------------------------


def test_create_prints_id_and_status(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _invoke(cli_server, "runs", "create", "A goal", client_id="c1") == 0
    fields = capsys.readouterr().out.strip().split("\t")
    assert len(fields) == 2
    run_id, status = fields
    assert status == "draft"
    assert _status(cli_server, run_id, "c1") == "draft"


def test_create_json_with_config(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _invoke(
        cli_server,
        "runs",
        "create",
        "Config goal",
        "--tier",
        "standard",
        "--focus",
        "prefer_novelty",
        "--json",
        client_id="c2",
    )
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "draft"
    assert data["config"]["tier"] == "standard"
    assert data["config"]["focus"] == "prefer_novelty"


def test_list_scoped_to_client(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    client_id = "list-client"
    _create(cli_server, client_id)
    _create(cli_server, client_id)
    assert _invoke(cli_server, "runs", "list", client_id=client_id) == 0
    lines = [
        line for line in capsys.readouterr().out.splitlines() if line.strip()
    ]
    assert len(lines) == 2
    for line in lines:
        assert len(line.split("\t")) == 4


def test_show_summary_and_json(
    completed_run: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    base, run_id, client_id = completed_run
    assert _invoke(base, "runs", "show", run_id, client_id=client_id) == 0
    out = capsys.readouterr().out
    assert "status" in out
    assert "completed" in out

    assert (
        _invoke(base, "runs", "show", run_id, "--json", client_id=client_id)
        == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert data["id"] == run_id
    assert isinstance(data["summary"], dict)


# ---------------------------------------------------------------------------
# Start + watch streaming
# ---------------------------------------------------------------------------


def test_start_and_watch_to_terminal(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = _create(cli_server, "watch-client", tier="standard")
    assert (
        _invoke(cli_server, "runs", "start", run_id, client_id="watch-client")
        == 0
    )
    capsys.readouterr()  # drop the start line
    assert (
        _invoke(cli_server, "runs", "watch", run_id, client_id="watch-client")
        == 0
    )
    lines = capsys.readouterr().out.splitlines()
    assert any("\tstatus\t" in line for line in lines)
    assert lines[-1].endswith("_terminal\tcompleted")


def test_watch_after_skips_replayed_events(
    completed_run: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    base, run_id, client_id = completed_run
    events = _api(
        base, "GET", f"/api/runs/{run_id}/events", client_id=client_id
    )
    # An already-terminal run's stream replays history then closes, so the SSE
    # endpoint returns synchronously here.
    max_seq = max(
        frame["seq"]
        for line in events.text.splitlines()
        if line.startswith("data:")
        for frame in [json.loads(line[len("data:") :])]
    )
    assert (
        _invoke(
            base,
            "runs",
            "watch",
            run_id,
            "--after",
            str(max_seq),
            client_id=client_id,
        )
        == 0
    )
    lines = capsys.readouterr().out.splitlines()
    # Only the synthetic terminal frame remains after the last real event.
    assert len(lines) == 1
    assert lines[0].endswith("_terminal\tcompleted")


def test_watch_json_emits_jsonl(
    completed_run: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    base, run_id, client_id = completed_run
    assert (
        _invoke(base, "runs", "watch", run_id, "--json", client_id=client_id)
        == 0
    )
    lines = capsys.readouterr().out.splitlines()
    frames = [json.loads(line) for line in lines]
    assert frames[-1]["type"] == "_terminal"
    assert frames[-1]["payload"]["status"] == "completed"


# ---------------------------------------------------------------------------
# Data reads
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "key"),
    [
        ("hypotheses", "hypotheses"),
        ("evidence", "evidence"),
        ("reviews", "reviews"),
        ("citations", "citations"),
        ("safety", "safety"),
    ],
)
def test_read_collection_text_and_json(
    completed_run: tuple[str, str, str],
    capsys: pytest.CaptureFixture[str],
    command: str,
    key: str,
) -> None:
    base, run_id, client_id = completed_run
    assert _invoke(base, "runs", command, run_id, client_id=client_id) == 0
    text_lines = [
        line for line in capsys.readouterr().out.splitlines() if line.strip()
    ]
    assert text_lines, f"{command} produced no lines"

    assert (
        _invoke(base, "runs", command, run_id, "--json", client_id=client_id)
        == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data[key], list)
    assert len(data[key]) == len(text_lines)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def test_report_summary(
    completed_run: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    base, run_id, client_id = completed_run
    assert _invoke(base, "runs", "report", run_id, client_id=client_id) == 0
    out = capsys.readouterr().out
    assert "research_goal" in out
    assert "leaderboard" in out


def test_report_markdown(
    completed_run: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    base, run_id, client_id = completed_run
    assert (
        _invoke(base, "runs", "report", run_id, "--md", client_id=client_id)
        == 0
    )
    assert "#" in capsys.readouterr().out


def test_report_json(
    completed_run: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    base, run_id, client_id = completed_run
    assert (
        _invoke(base, "runs", "report", run_id, "--json", client_id=client_id)
        == 0
    )
    data = json.loads(capsys.readouterr().out)
    assert "payload" in data
    assert data["payload"]["provider"] == "mock"


# ---------------------------------------------------------------------------
# Steering and Q&A
# ---------------------------------------------------------------------------


def test_steer_queues_message(
    completed_run: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    base, run_id, client_id = completed_run
    assert (
        _invoke(
            base,
            "runs",
            "steer",
            run_id,
            "Prioritize testability",
            client_id=client_id,
        )
        == 0
    )
    assert "queued" in capsys.readouterr().out
    msgs = _api(
        base, "GET", f"/api/runs/{run_id}/messages", client_id=client_id
    ).json()["messages"]
    assert any(m["content"] == "Prioritize testability" for m in msgs)


def test_ask_offline_returns_grounded_answer(
    completed_run: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    base, run_id, client_id = completed_run
    code = _invoke(
        base, "runs", "ask", run_id, "Which idea won?", client_id=client_id
    )
    # Offline (mock provider) the endpoint streams a grounded answer built
    # from the run's own artifacts, not an API-key error frame, so the CLI
    # writes the answer to stdout and exits zero.
    assert code == 0
    captured = capsys.readouterr()
    assert "offline mode" in captured.out
    assert captured.err.strip() == ""


def test_ask_json_streams_answer_frames(
    completed_run: tuple[str, str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    base, run_id, client_id = completed_run
    code = _invoke(
        base,
        "runs",
        "ask",
        run_id,
        "Which idea won?",
        "--json",
        client_id=client_id,
    )
    assert code == 0
    frames = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    types = {frame["type"] for frame in frames}
    # The offline grounded answer streams chunk(s) then done, with no error
    # frame; the CLI echoes each SSE frame verbatim in --json mode.
    assert "chunk" in types
    assert "done" in types
    assert "error" not in types


# ---------------------------------------------------------------------------
# Lifecycle: pause / resume / cancel
# ---------------------------------------------------------------------------


def test_pause_then_resume_cycle(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # A multi-iteration run stays active for seconds, so the pause request
    # lands well inside its run window.
    run_id = _create(cli_server, "pause-client", tier="ultra")
    _start(cli_server, run_id, "pause-client")
    assert (
        _invoke(cli_server, "runs", "pause", run_id, client_id="pause-client")
        == 0
    )
    assert "pausing" in capsys.readouterr().out
    _wait_status(cli_server, run_id, "paused", "pause-client")

    assert (
        _invoke(cli_server, "runs", "resume", run_id, client_id="pause-client")
        == 0
    )
    assert "queued" in capsys.readouterr().out
    _wait_status(cli_server, run_id, "completed", "pause-client", timeout=60)


def test_cancel_active_run(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = _create(cli_server, "cancel-client", tier="ultra")
    _start(cli_server, run_id, "cancel-client")
    assert (
        _invoke(cli_server, "runs", "cancel", run_id, client_id="cancel-client")
        == 0
    )
    assert "cancelling" in capsys.readouterr().out
    _wait_status(cli_server, run_id, "cancelled", "cancel-client")


@pytest.mark.parametrize(
    ("verb", "expected_err"),
    [
        ("cancel", "already finished"),
        ("resume", "already completed"),
    ],
)
def test_terminal_run_verb_errors(
    completed_run: tuple[str, str, str],
    capsys: pytest.CaptureFixture[str],
    verb: str,
    expected_err: str,
) -> None:
    """A finished run rejects cancel/resume.

    The API 409s and the CLI relays it as a non-zero exit with a message.
    """
    base, run_id, client_id = completed_run
    assert _invoke(base, "runs", verb, run_id, client_id=client_id) == 1
    assert expected_err in capsys.readouterr().err


def test_missing_run_errors(
    cli_server: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _invoke(cli_server, "runs", "show", "no-such-run") == 1
    err = capsys.readouterr().err
    assert "404" in err
    assert "run not found" in err


def test_no_command_prints_help_and_returns_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 2
    assert "usage: cosci" in capsys.readouterr().err
