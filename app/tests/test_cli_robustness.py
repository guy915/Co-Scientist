"""Robustness tests for the cosci CLI: retries, reconnects, and guards."""

from __future__ import annotations

import argparse
import importlib
import os
import pathlib
import subprocess
import sys
from typing import Any, ClassVar, cast

import httpx
import pytest

from app.cli import runs_cmd
from app.cli.http import ApiClient, ApiUnreachableError, CliError

# The package re-exports the ``main`` function under the same name as the
# module, so fetch the module itself for monkeypatching.
cli_main = importlib.import_module("app.cli.main")


def _client(handler: object, **kwargs: object) -> ApiClient:
    """Build an ApiClient whose requests are served by ``handler``."""
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return ApiClient(
        "http://api.test",
        transport=transport,
        retry_wait=0.0,
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# GET retries
# ---------------------------------------------------------------------------


def test_get_retries_transient_connect_error() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={"ok": True})

    assert _client(handler).request_json("GET", "/x") == {"ok": True}
    assert attempts == 3


def test_get_retries_retryable_status() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"ok": True})

    assert _client(handler).request_json("GET", "/x") == {"ok": True}
    assert attempts == 2


def test_get_does_not_retry_client_errors() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(404, json={"detail": "missing"})

    with pytest.raises(CliError):
        _client(handler).request_json("GET", "/x")
    assert attempts == 1


def test_get_exhausts_retries_then_raises() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("refused")

    with pytest.raises(CliError) as excinfo:
        _client(handler).request_json("GET", "/x")
    assert "could not reach API" in excinfo.value.message
    assert attempts == 3


def test_post_is_not_retried() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("refused")

    with pytest.raises(CliError):
        _client(handler).request_json("POST", "/x", json_body={})
    assert attempts == 1


# ---------------------------------------------------------------------------
# Base URL and timeout handling
# ---------------------------------------------------------------------------


def test_base_url_without_scheme_defaults_to_http() -> None:
    assert ApiClient("localhost:8008").base_url == "http://localhost:8008"


def test_base_url_with_scheme_is_preserved() -> None:
    assert ApiClient("https://api.test/").base_url == "https://api.test"


class _RecordingClient:
    """Stand-in for ApiClient that records constructor arguments."""

    captured: ClassVar[dict[str, Any]] = {}

    def __init__(
        self,
        base_url: str,
        client_id: str | None = None,
        *,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> None:
        _RecordingClient.captured = {
            "base_url": base_url,
            "client_id": client_id,
            "timeout": timeout,
            **kwargs,
        }

    def request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        return {}

    def close(self) -> None:
        """Match ApiClient's interface; main() closes the client on exit."""


def test_timeout_flag_reaches_client(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli_main, "ApiClient", _RecordingClient)
    rc = cli_main.main(
        ["status", "--api-url", "http://x", "--timeout", "5", "--json"]
    )
    assert rc == 0
    assert _RecordingClient.captured["timeout"] == 5.0


def test_timeout_env_var_is_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("COSCIENTIST_TIMEOUT", "7.5")
    monkeypatch.setattr(cli_main, "ApiClient", _RecordingClient)
    rc = cli_main.main(["status", "--api-url", "http://x", "--json"])
    assert rc == 0
    assert _RecordingClient.captured["timeout"] == 7.5


# ---------------------------------------------------------------------------
# Interrupt and pipe handling in main
# ---------------------------------------------------------------------------


def _dispatch_raising(
    monkeypatch: pytest.MonkeyPatch, exc: BaseException
) -> int:
    """Run ``cosci status`` with a handler that raises ``exc``."""

    def handler(args: argparse.Namespace, client: Any) -> int:
        raise exc

    monkeypatch.setattr(cli_main.status_cmd, "handle_status", handler)
    return cast(int, cli_main.main(["status", "--api-url", "http://x"]))


def test_keyboard_interrupt_exits_130(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _dispatch_raising(monkeypatch, KeyboardInterrupt()) == 130


# ---------------------------------------------------------------------------
# Path quoting and response-shape guards
# ---------------------------------------------------------------------------


def test_run_id_is_percent_quoted_in_paths(
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"id": "x", "status": "draft"})

    args = argparse.Namespace(run_id="a/b c", json=True)
    rc = runs_cmd.handle_show(args, _client(handler))
    assert rc == 0
    assert "/api/runs/a%2Fb%20c" in seen["url"]


def test_show_non_object_body_is_a_clean_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "an", "object"])

    args = argparse.Namespace(run_id="r1", json=False)
    with pytest.raises(CliError) as excinfo:
        runs_cmd.handle_show(args, _client(handler))
    assert "unexpected non-object response" in excinfo.value.message


def test_lifecycle_non_object_body_is_a_clean_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json="oops")

    args = argparse.Namespace(run_id="r1", json=False)
    with pytest.raises(CliError) as excinfo:
        runs_cmd.handle_cancel(args, _client(handler))
    assert "unexpected non-object response" in excinfo.value.message


# ---------------------------------------------------------------------------
# Watch reconnection
# ---------------------------------------------------------------------------

_TERMINAL_BODY = (
    b'data: {"seq": 2, "type": "generation", "payload": {}}\n\n'
    b'data: {"seq": 3, "type": "_terminal",'
    b' "payload": {"status": "completed"}}\n\n'
)


def _watch_args(after: int = 0) -> argparse.Namespace:
    return argparse.Namespace(run_id="r1", after=after, json=False)


def _watch_client(
    handler: object, monkeypatch: pytest.MonkeyPatch
) -> ApiClient:
    monkeypatch.setattr(runs_cmd, "WATCH_RECONNECT_WAIT", 0.0)
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return ApiClient("http://api.test", transport=transport, retry_wait=0.0)


def test_watch_reconnects_after_mid_stream_drop(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    urls: list[str] = []

    def first_stream() -> Any:
        yield b'data: {"seq": 1, "type": "planning", "payload": {}}\n\n'
        raise httpx.ReadError("connection dropped")

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if len(urls) == 1:
            return httpx.Response(200, content=first_stream())
        return httpx.Response(200, content=_TERMINAL_BODY)

    rc = runs_cmd.handle_watch(
        _watch_args(), _watch_client(handler, monkeypatch)
    )
    assert rc == 0
    assert len(urls) == 2
    assert "after=0" in urls[0]
    assert "after=1" in urls[1]
    out = capsys.readouterr().out
    assert "planning" in out
    assert "_terminal" in out


def test_watch_reconnects_after_clean_close_without_terminal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if len(urls) == 1:
            return httpx.Response(
                200,
                content=b'data: {"seq": 1, "type": "planning",'
                b' "payload": {}}\n\n',
            )
        return httpx.Response(200, content=_TERMINAL_BODY)

    rc = runs_cmd.handle_watch(
        _watch_args(), _watch_client(handler, monkeypatch)
    )
    assert rc == 0
    assert len(urls) == 2
    assert "after=1" in urls[1]


def test_watch_does_not_reconnect_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(404, json={"detail": "run not found"})

    with pytest.raises(CliError) as excinfo:
        runs_cmd.handle_watch(
            _watch_args(), _watch_client(handler, monkeypatch)
        )
    assert "HTTP 404" in excinfo.value.message
    assert len(urls) == 1


def test_watch_gives_up_after_repeated_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("refused")

    with pytest.raises(ApiUnreachableError):
        runs_cmd.handle_watch(
            _watch_args(), _watch_client(handler, monkeypatch)
        )
    assert attempts == 1 + runs_cmd.WATCH_RECONNECT_ATTEMPTS


def test_broken_pipe_exits_141() -> None:
    # Run in a subprocess: the handler's fd-level devnull redirect would
    # break pytest's own capture if exercised in-process.
    code = (
        "import importlib, sys\n"
        "m = importlib.import_module('app.cli.main')\n"
        "def boom(args, client):\n"
        "    raise BrokenPipeError()\n"
        "m.status_cmd.handle_status = boom\n"
        "sys.exit(m.main(['status', '--api-url', 'http://x']))\n"
    )
    app_dir = pathlib.Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONPATH": str(app_dir)},
        capture_output=True,
        timeout=30,
    )
    assert proc.returncode == 141
