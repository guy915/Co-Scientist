from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

import httpx


class UnsafeUrlError(ValueError):
    pass


def _public_ip(host: str) -> str:
    try:
        literal = ipaddress.ip_address(host)
        addresses = [literal]
    except ValueError:
        try:
            addresses = [
                ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, None)
            ]
        except (OSError, ValueError) as exc:
            raise UnsafeUrlError("hostname does not resolve") from exc
    if not addresses:
        raise UnsafeUrlError("hostname does not resolve")
    for address in addresses:
        if not address.is_global:
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
    ip = _public_ip(host)
    return host, ip


async def get_with_screened_redirects(
    client: httpx.AsyncClient, url: str, *, max_redirects: int = 5
) -> httpx.Response:
    current = url
    for _ in range(max_redirects):
        host, ip = validate_http_url(current)
        parsed = httpx.URL(current)
        authority = f"[{host}]" if ":" in host else host
        if parsed.port is not None:
            authority = f"{authority}:{parsed.port}"
        pinned_url = parsed.copy_with(host=ip)
        response = await client.get(
            pinned_url,
            headers={"Host": authority},
            extensions={"sni_hostname": host},
            follow_redirects=False,
        )
        if not response.is_redirect or not response.headers.get("location"):
            return response
        current = str(httpx.URL(current).join(response.headers["location"]))
    raise UnsafeUrlError("too many redirects")
