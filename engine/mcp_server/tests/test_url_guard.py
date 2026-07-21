"""Tests for the URL safety screen.

``read_url`` fetches URLs chosen by an LLM from search results it did not
write, and the server runs on a private network next to the API service.
These are the tests that keep it from becoming an internal-network read
primitive, so they cover the bypass tricks rather than just the happy path.
"""

import socket
from typing import Any

import pytest
from mcp_server.tools.web.url_guard import (
    UrlNotFetchableError,
    check_fetchable,
)


def _fake_getaddrinfo(mapping: dict[str, str]) -> Any:
    """Builds a getaddrinfo stub resolving hosts per the given mapping.

    Args:
        mapping: Hostname to IP address string.

    Returns:
        A callable with getaddrinfo's signature.
    """

    def _resolve(host: str, *args: Any, **kwargs: Any) -> list[Any]:
        if host not in mapping:
            raise socket.gaierror(f"unknown host {host}")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (mapping[host], 0))]

    return _resolve


@pytest.fixture
def resolve_to(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Patches DNS resolution so tests never touch the network."""

    def _apply(mapping: dict[str, str]) -> None:
        monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo(mapping))

    return _apply


def test_allows_public_https_url(resolve_to: Any) -> None:
    resolve_to({"example.com": "93.184.216.34"})
    check_fetchable("https://example.com/article")


def test_rejects_non_http_scheme(resolve_to: Any) -> None:
    resolve_to({})
    with pytest.raises(UrlNotFetchableError, match="scheme"):
        check_fetchable("file:///etc/passwd")


def test_rejects_url_without_host(resolve_to: Any) -> None:
    resolve_to({})
    with pytest.raises(UrlNotFetchableError, match="no host"):
        check_fetchable("http:///nowhere")


def test_rejects_loopback(resolve_to: Any) -> None:
    resolve_to({"localhost": "127.0.0.1"})
    with pytest.raises(UrlNotFetchableError, match="non-public"):
        check_fetchable("http://localhost:8008/api/runs")


def test_rejects_private_range(resolve_to: Any) -> None:
    resolve_to({"mcp.railway.internal": "10.0.1.5"})
    with pytest.raises(UrlNotFetchableError, match="non-public"):
        check_fetchable("http://mcp.railway.internal:8888/mcp")


def test_rejects_public_hostname_resolving_to_loopback(resolve_to: Any) -> None:
    """Rejects a public hostname that resolves to loopback.

    A string check on the host would let this through; DNS resolution is
    what catches it.
    """
    resolve_to({"127.0.0.1.nip.io": "127.0.0.1"})
    with pytest.raises(UrlNotFetchableError, match="non-public"):
        check_fetchable("http://127.0.0.1.nip.io/admin")


def test_rejects_decimal_encoded_loopback(resolve_to: Any) -> None:
    resolve_to({"2130706433": "127.0.0.1"})
    with pytest.raises(UrlNotFetchableError, match="non-public"):
        check_fetchable("http://2130706433/")


def test_rejects_cloud_metadata_host(resolve_to: Any) -> None:
    # Named explicitly, so it is refused before DNS is even consulted.
    resolve_to({})
    with pytest.raises(UrlNotFetchableError, match="not allowed"):
        check_fetchable("http://169.254.169.254/latest/meta-data/")


def test_rejects_link_local(resolve_to: Any) -> None:
    resolve_to({"metadata.example": "169.254.169.254"})
    with pytest.raises(UrlNotFetchableError, match="non-public"):
        check_fetchable("http://metadata.example/")


def test_rejects_unresolvable_host(resolve_to: Any) -> None:
    resolve_to({})
    with pytest.raises(UrlNotFetchableError, match="does not resolve"):
        check_fetchable("https://no-such-host.invalid/")
