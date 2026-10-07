from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

import httpx


class UnsafeUrlError(ValueError):
    pass


def _public_ip(host: str) -> str:
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [
                ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, None)
            ]
        except (OSError, ValueError) as exc:
            raise UnsafeUrlError("hostname does not resolve") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise UnsafeUrlError("host resolves to a non-public address")
    return str(addresses[0])


def validate_http_url(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    try:
        valid_port = parsed.port is None or 1 <= parsed.port <= 65535
    except ValueError:
        valid_port = False
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or not valid_port
    ):
        raise UnsafeUrlError("only absolute public http(s) URLs are allowed")
    host = httpx.URL(url).host
    if host.lower() in {"169.254.169.254", "metadata.google.internal"}:
        raise UnsafeUrlError("metadata hosts are blocked")
    return host, _public_ip(host)


def request_with_screened_redirects(
    client: httpx.Client, method: str, url: str, *, max_redirects: int = 5
) -> httpx.Response:
    current = url
    for _ in range(max_redirects):
        host, ip = validate_http_url(current)
        parsed = httpx.URL(current)
        authority = f"[{host}]" if ":" in host else host
        if parsed.port is not None:
            authority = f"{authority}:{parsed.port}"
        pinned_url = parsed.copy_with(host=ip)
        headers = {"Host": authority}
        extensions = {"sni_hostname": host}
        response = client.request(
            method,
            pinned_url,
            headers=headers,
            extensions=extensions,
            follow_redirects=False,
        )
        if response.status_code in {403, 405} and method == "HEAD":
            response = client.request(
                "GET",
                pinned_url,
                headers=headers,
                extensions=extensions,
                follow_redirects=False,
            )
        location = response.headers.get("location")
        if response.is_redirect and location:
            current = str(httpx.URL(current).join(location))
            continue
        return response
    raise UnsafeUrlError("too many redirects")
