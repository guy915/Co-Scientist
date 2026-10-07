from __future__ import annotations

import socket

import httpx
import pytest

from app import pinned_http


def _dns(_host: str, _port: object) -> list[tuple[object, ...]]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


def test_pinned_transport_dials_ip_and_preserves_tls_name_and_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _dns)
    requests: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, request=request)

    with httpx.Client(transport=httpx.MockTransport(capture)) as client:
        pinned_http.request_with_screened_redirects(client, "HEAD", "https://example.org/paper")

    (request,) = requests
    assert request.url.host == "93.184.216.34"
    assert request.headers["host"] == "example.org"
    assert request.extensions["sni_hostname"] == "example.org"


def test_redirect_private_hop_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _dns)

    def redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"}, request=request)

    with (
        httpx.Client(transport=httpx.MockTransport(redirect)) as client,
        pytest.raises(pinned_http.UnsafeUrlError, match="non-public"),
    ):
        pinned_http.request_with_screened_redirects(client, "HEAD", "https://example.org/")
