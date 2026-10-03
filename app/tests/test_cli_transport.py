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

from app.cli import logs_cmd, render, runs_cmd, runs_stream_cmd
from app.cli.http import ApiClient, ApiUnreachableError, CliError
from tests._cli_helpers import api_client


def test_request_json_returns_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/runs"
        return httpx.Response(200, json={"runs": []})

    assert api_client(handler).request_json("GET", "/api/runs") == {"runs": []}


def test_request_json_sends_client_id_header() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["cid"] = request.headers.get("X-Client-ID", "")
        return httpx.Response(200, json={})

    api_client(handler, client_id="abc").request_json("GET", "/x")
    assert seen["cid"] == "abc"


def test_request_json_omits_client_id_when_unset() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "X-Client-ID" not in request.headers
        return httpx.Response(200, json={})

    api_client(handler).request_json("GET", "/x")


def test_request_json_raises_cli_error_on_http_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "run not found"})

    with pytest.raises(CliError) as excinfo:
        api_client(handler).request_json("GET", "/api/runs/missing")
    assert "HTTP 404" in excinfo.value.message
    assert "run not found" in excinfo.value.message
    assert excinfo.value.exit_code == 1


def test_request_json_raises_on_invalid_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    with pytest.raises(CliError) as excinfo:
        api_client(handler).request_json("GET", "/x")
    assert "invalid JSON" in excinfo.value.message


def test_request_json_raises_on_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(CliError) as excinfo:
        api_client(handler).request_json("GET", "/x")
    assert "could not reach API" in excinfo.value.message


def test_request_text_returns_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="# report\n")

    assert api_client(handler).request_text("GET", "/x") == "# report\n"


def test_request_text_raises_on_error_with_plain_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(CliError) as excinfo:
        api_client(handler).request_text("GET", "/x")
    assert "HTTP 500" in excinfo.value.message
    assert "boom" in excinfo.value.message


def test_stream_lines_yields_frames() -> None:
    body = b'data: {"seq": 1}\n\ndata: {"seq": 2}\n\n'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    with api_client(handler).stream_lines("GET", "/events") as lines:
        collected = [line for line in lines if line.startswith("data:")]
    assert collected == ['data: {"seq": 1}', 'data: {"seq": 2}']


def test_stream_lines_raises_on_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "gone"})

    with (
        pytest.raises(CliError) as excinfo,
        api_client(handler).stream_lines("GET", "/events"),
    ):
        pass
    assert "HTTP 404" in excinfo.value.message


def test_cli_error_custom_exit_code() -> None:
    err = CliError("bad", exit_code=3)
    assert err.exit_code == 3
    assert str(err) == "bad"


_logs_cli_main = importlib.import_module("app.cli.main")


def _args(**overrides: Any) -> argparse.Namespace:
    base: dict[str, Any] = {
        "run": None,
        "level": None,
        "grep": None,
        "after_id": 0,
        "limit": 100,
        "follow": False,
        "interval": 0.0,
        "clear": False,
        "all": False,
        "json": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _row(row_id: int, message: str, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": row_id,
        "created_at": 1752700000.0,
        "level": "INFO",
        "levelno": 20,
        "logger": "app.something",
        "message": message,
        "run_id": None,
        "exc_text": None,
    }
    row.update(extra)
    return row


def test_logs_lists_rows(capsys: pytest.CaptureFixture[str]) -> None:
    urls: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(request.url)
        return httpx.Response(
            200,
            json={
                "logs": [
                    _row(1, "server started"),
                    _row(2, "run scoped", run_id="r1", level="WARNING"),
                ],
                "last_id": 2,
            },
        )

    assert logs_cmd.handle_logs(_args(), api_client(handler)) == 0
    out = capsys.readouterr().out
    assert "server started" in out
    assert "run scoped" in out
    assert "WARNING" in out
    assert "[run_id=r1]" in out
    assert urls[0].path == "/api/logs"
    assert "limit=100" in str(urls[0])


def test_logs_passes_filters(capsys: pytest.CaptureFixture[str]) -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, json={"logs": [], "last_id": 0})

    args = _args(run="r1", level="warning", grep="boom", after_id=5)
    assert logs_cmd.handle_logs(args, api_client(handler)) == 0
    url = urls[0]
    assert "run_id=r1" in url
    assert "min_level=warning" in url
    assert "q=boom" in url
    assert "after_id=5" in url
    assert "verbose" not in url


def test_logs_all_requests_verbose_records(
    capsys: pytest.CaptureFixture[str],
) -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, json={"logs": [], "last_id": 0})

    assert logs_cmd.handle_logs(_args(all=True), api_client(handler)) == 0
    assert "verbose=1" in urls[0]


def test_logs_follow_polls_from_last_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if len(urls) == 1:
            return httpx.Response(
                200, json={"logs": [_row(1, "first")], "last_id": 1}
            )
        if len(urls) == 2:
            return httpx.Response(
                200, json={"logs": [_row(2, "second")], "last_id": 2}
            )
        raise KeyboardInterrupt()

    rc = logs_cmd.handle_logs(_args(follow=True), api_client(handler))
    assert rc == 130
    out = capsys.readouterr().out
    assert "first" in out
    assert "second" in out
    assert "after_id=1" in urls[1]
    assert "after_id=2" in urls[2]


def test_logs_follow_recovers_from_a_server_clear(
    capsys: pytest.CaptureFixture[str],
) -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if len(urls) == 1:
            return httpx.Response(
                200, json={"logs": [_row(50, "old line")], "last_id": 50}
            )
        if len(urls) == 2:
            return httpx.Response(200, json={"logs": [], "last_id": 0})
        if len(urls) == 3:
            return httpx.Response(
                200, json={"logs": [_row(1, "fresh line")], "last_id": 1}
            )
        raise KeyboardInterrupt()

    rc = logs_cmd.handle_logs(_args(follow=True), api_client(handler))
    assert rc == 130
    out = capsys.readouterr().out
    assert "old line" in out
    assert "fresh line" in out
    assert "after_id=0" in urls[2]


def test_logs_json_emits_payload(capsys: pytest.CaptureFixture[str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"logs": [_row(1, "hello")], "last_id": 1}
        )

    assert logs_cmd.handle_logs(_args(json=True), api_client(handler)) == 0
    assert '"hello"' in capsys.readouterr().out


def test_logs_clear_deletes_and_reports(
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={"deleted": 7})

    rc = logs_cmd.handle_logs(_args(clear=True), api_client(handler))
    assert rc == 0
    assert seen == [("DELETE", "/api/logs")]
    assert "deleted\t7" in capsys.readouterr().out


def test_parser_wires_logs_command() -> None:
    parser = _logs_cli_main.build_parser()
    args = parser.parse_args(["logs"])
    assert args.handler is logs_cmd.handle_logs
    assert args.limit == 100
    assert args.follow is False
    assert args.interval == 2.0
    args = parser.parse_args(
        ["logs", "--run", "r1", "--level", "warning", "--follow"]
    )
    assert args.run == "r1"
    assert args.level == "warning"
    assert args.follow is True


def test_oneline_collapses_whitespace() -> None:
    assert render.oneline("a  b\n\tc") == "a b c"


def test_oneline_truncates_with_ellipsis() -> None:
    out = render.oneline("x" * 200, limit=10)
    assert len(out) == 10
    assert out.endswith("…")


def test_format_run_line_is_tab_separated() -> None:
    run = {
        "id": "r1",
        "status": "completed",
        "provider": "mock",
        "research_goal": "Study  neurons",
    }
    assert render.format_run_line(run) == "r1\tcompleted\tmock\tStudy neurons"


def test_format_action_line() -> None:
    assert render.format_action_line({"id": "r1", "status": "queued"}) == (
        "r1\tqueued"
    )


def test_format_kv_aligns_keys() -> None:
    out = render.format_kv([("a", 1), ("bb", 2)])
    assert out == "a  : 1\nbb : 2"


def test_format_kv_empty() -> None:
    assert render.format_kv([]) == ""


def test_format_record_line_selects_first_present_key() -> None:
    record = {"id": 5, "state": "verified", "claim": "a  claim"}
    line = render.format_record_line(record, (("id",), ("state",), ("claim",)))
    assert line == "5\tverified\ta claim"


def test_format_record_line_drops_trailing_empty_columns() -> None:
    line = render.format_record_line(
        {"id": 5}, (("id",), ("state",), ("claim",))
    )
    assert line == "5"


def test_format_record_line_uses_fallback_key() -> None:
    line = render.format_record_line(
        {"id": "h1", "statement": "S"}, (("id",), ("title", "statement"))
    )
    assert line == "h1\tS"


def test_sse_data_parses_data_frame() -> None:
    assert render.sse_data('data: {"type": "x", "seq": 3}') == {
        "type": "x",
        "seq": 3,
    }


def test_sse_data_ignores_non_data_and_malformed() -> None:
    assert render.sse_data(": keep-alive comment") is None
    assert render.sse_data("event: message") is None
    assert render.sse_data("data: not json") is None
    assert render.sse_data("data: ") is None
    assert render.sse_data("data: [1, 2]") is None


def test_format_event_line_renders_seq_type_payload() -> None:
    line = render.format_event_line(
        {"seq": 5, "type": "status", "payload": {"status": "running"}}
    )
    assert line == '5\tstatus\t{"status": "running"}'


def test_format_event_line_omits_empty_payload() -> None:
    line = render.format_event_line(
        {"seq": 2, "type": "lifecycle", "payload": {}}
    )
    assert line == "2\tlifecycle"


_robustness_cli_main = importlib.import_module("app.cli.main")


def test_get_retries_transient_connect_error() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectError("refused")
        return httpx.Response(200, json={"ok": True})

    assert api_client(handler).request_json("GET", "/x") == {"ok": True}
    assert attempts == 3


def test_get_retries_retryable_status() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"ok": True})

    assert api_client(handler).request_json("GET", "/x") == {"ok": True}
    assert attempts == 2


def test_get_does_not_retry_client_errors() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(404, json={"detail": "missing"})

    with pytest.raises(CliError):
        api_client(handler).request_json("GET", "/x")
    assert attempts == 1


def test_get_exhausts_retries_then_raises() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("refused")

    with pytest.raises(CliError) as excinfo:
        api_client(handler).request_json("GET", "/x")
    assert "could not reach API" in excinfo.value.message
    assert attempts == 3


def test_post_is_not_retried() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("refused")

    with pytest.raises(CliError):
        api_client(handler).request_json("POST", "/x", json_body={})
    assert attempts == 1


def test_base_url_without_scheme_defaults_to_http() -> None:
    assert ApiClient("localhost:8008").base_url == "http://localhost:8008"


def test_base_url_with_scheme_is_preserved() -> None:
    assert ApiClient("https://api.test/").base_url == "https://api.test"


class _RecordingClient:
    captured: ClassVar[dict[str, Any]] = {}

    def __init__(
        self,
        base_url: str,
        client_id: str | None = None,
        *,
        options: Any = None,
        **kwargs: Any,
    ) -> None:
        _RecordingClient.captured = {
            "base_url": base_url,
            "client_id": client_id,
            "timeout": options.timeout if options else 30.0,
            **kwargs,
        }

    def request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        return {}

    def close(self) -> None:
        """Match ApiClient's interface; main() closes the client on exit."""


def test_timeout_flag_reaches_client(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(_robustness_cli_main, "ApiClient", _RecordingClient)
    rc = _robustness_cli_main.main(
        ["status", "--api-url", "http://x", "--timeout", "5", "--json"]
    )
    assert rc == 0
    assert _RecordingClient.captured["timeout"] == 5.0


def test_timeout_env_var_is_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("COSCIENTIST_TIMEOUT", "7.5")
    monkeypatch.setattr(_robustness_cli_main, "ApiClient", _RecordingClient)
    rc = _robustness_cli_main.main(
        ["status", "--api-url", "http://x", "--json"]
    )
    assert rc == 0
    assert _RecordingClient.captured["timeout"] == 7.5


def _dispatch_raising(
    monkeypatch: pytest.MonkeyPatch, exc: BaseException
) -> int:

    def handler(args: argparse.Namespace, client: Any) -> int:
        raise exc

    monkeypatch.setattr(_robustness_cli_main, "handle_status", handler)
    return cast(
        int, _robustness_cli_main.main(["status", "--api-url", "http://x"])
    )


def test_keyboard_interrupt_exits_130(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _dispatch_raising(monkeypatch, KeyboardInterrupt()) == 130


def test_run_id_is_percent_quoted_in_paths(
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"id": "x", "status": "draft"})

    args = argparse.Namespace(run_id="a/b c", json=True)
    rc = runs_cmd.handle_show(args, api_client(handler))
    assert rc == 0
    assert "/api/runs/a%2Fb%20c" in seen["url"]


def test_show_non_object_body_is_a_clean_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "an", "object"])

    args = argparse.Namespace(run_id="r1", json=False)
    with pytest.raises(CliError) as excinfo:
        runs_cmd.handle_show(args, api_client(handler))
    assert "unexpected non-object response" in excinfo.value.message


def test_lifecycle_non_object_body_is_a_clean_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json="oops")

    args = argparse.Namespace(run_id="r1", json=False, runs_command="cancel")
    with pytest.raises(CliError) as excinfo:
        runs_cmd.handle_lifecycle(args, api_client(handler))
    assert "unexpected non-object response" in excinfo.value.message


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
    monkeypatch.setattr(runs_stream_cmd, "WATCH_RECONNECT_WAIT", 0.0)
    return api_client(handler)


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

    rc = runs_stream_cmd.handle_watch(
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

    rc = runs_stream_cmd.handle_watch(
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
        runs_stream_cmd.handle_watch(
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
        runs_stream_cmd.handle_watch(
            _watch_args(), _watch_client(handler, monkeypatch)
        )
    assert attempts == 1 + runs_stream_cmd.WATCH_RECONNECT_ATTEMPTS


def test_broken_pipe_exits_141() -> None:
    code = (
        "import importlib, sys\n"
        "m = importlib.import_module('app.cli.main')\n"
        "def boom(args, client):\n"
        "    raise BrokenPipeError()\n"
        "m.handle_status = boom\n"
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
