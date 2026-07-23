"""Safety checks for URLs the agent asks the server to fetch.

``read_url`` fetches a URL chosen by an LLM, and that choice is influenced by
search results the LLM did not write. In production this server runs on a
private network alongside the API service, so an unguarded fetcher would be a
read primitive against internal hosts. Every URL is screened here first, and
each redirect hop is screened again, since validating only the initial URL
lets a redirect walk straight past the check.
"""

import ipaddress
import logging
import socket
from urllib.parse import ParseResult, urlparse

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = ("http", "https")

# Cloud instance-metadata service. Blocked by the link-local check below as
# well, but named explicitly because it is the single highest-value target
# for an SSRF and the intent should be obvious to a future reader.
_METADATA_HOSTS = frozenset({"169.254.169.254", "metadata.google.internal"})


class UrlNotFetchableError(Exception):
    """Raised when a URL fails the safety screen."""


def _resolved_addresses(
    hostname: str,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolves a hostname to every IP address it maps to.

    Resolution happens before the range checks so that hostnames pointing at
    internal addresses (``localtest.me``, ``127.0.0.1.nip.io``, decimal or
    hex-encoded IPs) are caught. A string comparison against "localhost"
    would miss all of them.

    Args:
        hostname: Host portion of the URL under test.

    Returns:
        Every address the host resolves to.

    Raises:
        UrlNotFetchableError: If the hostname does not resolve.
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise UrlNotFetchableError(
            f"hostname does not resolve: {hostname}"
        ) from exc
    addresses = []
    for info in infos:
        raw = info[4][0]
        try:
            addresses.append(ipaddress.ip_address(raw))
        except ValueError:
            continue
    if not addresses:
        raise UrlNotFetchableError(f"hostname does not resolve: {hostname}")
    return addresses


def _is_blocked_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Reports whether an address belongs to a range we refuse to fetch.

    Args:
        address: A resolved IP address.

    Returns:
        True if the address is loopback, private, link-local, reserved,
        multicast, or unspecified.
    """
    return (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def _check_scheme(parsed: ParseResult) -> None:
    """Rejects any scheme other than http(s).

    Args:
        parsed: The parsed URL.

    Raises:
        UrlNotFetchableError: If the scheme is not http or https.
    """
    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise UrlNotFetchableError(
            f"scheme not allowed: {parsed.scheme or 'none'}"
        )


def _check_host_present(parsed: ParseResult) -> str:
    """Rejects a URL with no host, otherwise returns the host.

    Args:
        parsed: The parsed URL.

    Returns:
        The URL's hostname.

    Raises:
        UrlNotFetchableError: If the URL has no host.
    """
    hostname = parsed.hostname
    if not hostname:
        raise UrlNotFetchableError("URL has no host")
    return hostname


def _check_not_metadata_host(hostname: str) -> None:
    """Rejects a known cloud instance-metadata hostname.

    Args:
        hostname: Host portion of the URL under test.

    Raises:
        UrlNotFetchableError: If the host is a known metadata endpoint.
    """
    if hostname.lower() in _METADATA_HOSTS:
        raise UrlNotFetchableError(f"host not allowed: {hostname}")


def _check_resolved_addresses(hostname: str) -> None:
    """Rejects a host that resolves to any non-public address.

    Args:
        hostname: Host portion of the URL under test.

    Raises:
        UrlNotFetchableError: If the hostname does not resolve, or any
            resolved address is loopback, private, link-local, reserved,
            multicast, or unspecified.
    """
    for address in _resolved_addresses(hostname):
        if _is_blocked_address(address):
            raise UrlNotFetchableError(
                f"host resolves to a non-public address: {hostname}"
            )


def check_fetchable(url: str) -> None:
    """Screens a URL, raising if it must not be fetched.

    Args:
        url: Absolute URL to screen.

    Raises:
        UrlNotFetchableError: If the scheme is not http(s), the host is missing,
            the host is a known metadata endpoint, or the host resolves to a
            non-public address.
    """
    parsed = urlparse(url)
    _check_scheme(parsed)
    hostname = _check_host_present(parsed)
    _check_not_metadata_host(hostname)
    _check_resolved_addresses(hostname)
