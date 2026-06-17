"""Best-effort geo-IP locale detection.

Used to decide whether a first-time visitor should default to Hebrew because
they are browsing from Israel. Detection is intentionally defensive: it prefers
country headers injected by upstream proxies/CDNs (Cloudflare, Vercel, Railway)
and only falls back to an external IP-geolocation lookup when configured. Any
failure yields a null result so the frontend can fall back to browser language.
"""
# pylint: disable=inconsistent-quotes

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# Country (ISO 3166-1 alpha-2) -> default locale code.
_COUNTRY_LOCALE: dict[str, str] = {
    "IL": "he",
}

# Proxy/CDN headers that carry a two-letter country code, in priority order.
_COUNTRY_HEADERS = (
    "cf-ipcountry",
    "x-vercel-ip-country",
    "x-country-code",
    "x-geo-country",
    "x-appengine-country",
)

# External lookup endpoint; must contain "{ip}". Disabled unless set so we never
# make a surprise outbound call in restricted environments. Example:
#   GEOIP_LOOKUP_URL=https://ipapi.co/{ip}/country/
_LOOKUP_URL_ENV = "GEOIP_LOOKUP_URL"
_LOOKUP_TIMEOUT_SECONDS = 2.0


def _client_ip(headers: dict[str, str], client_host: str | None) -> str | None:
    """Extract the originating client IP from forwarding headers."""
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        # First hop is the original client.
        return forwarded.split(",")[0].strip() or None
    real_ip = headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip() or None
    return client_host


def _is_public_ip(ip: str) -> bool:
    """Return True for routable IPs worth geolocating (skips private ones)."""
    try:
        import ipaddress  # pylint: disable=import-outside-toplevel
        addr = ipaddress.ip_address(ip)
        return not (addr.is_private or addr.is_loopback or addr.is_link_local or
                    addr.is_reserved)
    except ValueError:
        return False


def _country_from_lookup(ip: str) -> str | None:
    """Query the configured external geo-IP service for a country code."""
    template = os.getenv(_LOOKUP_URL_ENV)
    if not template or "{ip}" not in template:
        return None
    url = template.format(ip=ip)
    try:
        req = urllib.request.Request(url,
                                     headers={"User-Agent": "co-scientist"})
        with urllib.request.urlopen(  # noqa: S310 - URL is operator-configured
                req,
                timeout=_LOOKUP_TIMEOUT_SECONDS) as resp:
            body: str = resp.read().decode("utf-8", "replace").strip()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("geo-ip lookup failed for %s: %s", ip, exc)
        return None

    # Accept either a bare country code or a JSON object with one.
    if len(body) == 2 and body.isalpha():
        return body.upper()
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None
    for key in ("country", "country_code", "countryCode"):
        val = data.get(key) if isinstance(data, dict) else None
        if isinstance(val, str) and len(val) == 2:
            return val.upper()
    return None


async def detect_locale(headers: dict[str, str],
                        client_host: str | None) -> dict[str, Any]:
    """Detect a suggested locale from the request origin.

    Args:
        headers: Request headers, lower-cased keys.
        client_host: The socket peer host, used when no forwarding header set.

    Returns:
        A dict with the detected ``country`` (or None) and the suggested
        ``locale`` code (or None when no localized default applies).
    """
    headers = {k.lower(): v for k, v in headers.items()}

    country: str | None = None
    for header in _COUNTRY_HEADERS:
        val = headers.get(header)
        if val and len(val.strip()) == 2 and val.strip().isalpha():
            country = val.strip().upper()
            break

    if country is None:
        ip = _client_ip(headers, client_host)
        if ip and _is_public_ip(ip):
            country = await asyncio.to_thread(_country_from_lookup, ip)

    locale = _COUNTRY_LOCALE.get(country) if country else None
    return {"country": country, "locale": locale}
