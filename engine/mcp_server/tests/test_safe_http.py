from __future__ import annotations

import socket

import httpx
import pytest
from mcp_server import safe_http


def _dns(_host: str, _port: object) -> list[tuple[object, ...]]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


async def test_pinned_transport_dials_ip_and_preserves_tls_name_and_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _dns)
    requests: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(capture)) as client:
        await safe_http.get_with_screened_redirects(client, "https://example.org/paper")

    (request,) = requests
    assert request.url.host == "93.184.216.34"
    assert request.headers["host"] == "example.org"
    assert request.extensions["sni_hostname"] == "example.org"


async def test_each_redirect_target_is_screened_and_private_hops_are_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _dns)

    def redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(redirect)) as client:
        with pytest.raises(safe_http.UnsafeUrlError, match="non-public"):
            await safe_http.get_with_screened_redirects(client, "https://example.org/")
