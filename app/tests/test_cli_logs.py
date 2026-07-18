"""Unit tests for the ``cosci logs`` command (httpx MockTransport)."""

from __future__ import annotations

import argparse
import importlib
from typing import Any

import httpx
import pytest

from app.cli import logs_cmd
from app.cli.http import ApiClient

cli_main = importlib.import_module("app.cli.main")


def _client(handler: object) -> ApiClient:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    return ApiClient("http://api.test", transport=transport, retry_wait=0.0)


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

    assert logs_cmd.handle_logs(_args(), _client(handler)) == 0
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
    assert logs_cmd.handle_logs(args, _client(handler)) == 0
    url = urls[0]
    assert "run_id=r1" in url
    assert "min_level=warning" in url
    assert "q=boom" in url
    assert "after_id=5" in url


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

    rc = logs_cmd.handle_logs(_args(follow=True), _client(handler))
    assert rc == 130
    out = capsys.readouterr().out
    assert "first" in out
    assert "second" in out
    assert "after_id=1" in urls[1]
    assert "after_id=2" in urls[2]


def test_logs_json_emits_payload(capsys: pytest.CaptureFixture[str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"logs": [_row(1, "hello")], "last_id": 1}
        )

    assert logs_cmd.handle_logs(_args(json=True), _client(handler)) == 0
    assert '"hello"' in capsys.readouterr().out


def test_logs_clear_deletes_and_reports(
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={"deleted": 7})

    rc = logs_cmd.handle_logs(_args(clear=True), _client(handler))
    assert rc == 0
    assert seen == [("DELETE", "/api/logs")]
    assert "deleted\t7" in capsys.readouterr().out


def test_parser_wires_logs_command() -> None:
    parser = cli_main.build_parser()
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
