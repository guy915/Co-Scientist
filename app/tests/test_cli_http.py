"""Unit tests for the cosci CLI HTTP client (httpx MockTransport)."""

from __future__ import annotations

import httpx
import pytest

from app.cli.http import CliError
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

    # The client reads the body and raises on context entry, before yielding.
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
