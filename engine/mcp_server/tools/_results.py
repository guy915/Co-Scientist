"""One result contract for every tool, so a failed lookup never reads as no match.

A tool that cannot answer returns its ordinary empty result plus an ``error``
object -- ``kind``, ``detail`` and, for HTTP refusals, ``status_code`` -- rather
than raising or returning a bare empty result. The engine reads that field.
Exception text is kept out of ``detail`` where it can carry a request URL,
because some providers authenticate with a query parameter.
"""

import socket
import urllib.error
from typing import Any
from xml.etree.ElementTree import ParseError

import httpx

# Malformed or unexpected upstream payloads surface as these while parsing.
_RESPONSE_ERRORS = (ValueError, TypeError, AttributeError, KeyError, IndexError, ParseError)


def failure(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, (httpx.TimeoutException, TimeoutError, socket.timeout)):
        return {"kind": "timeout", "detail": type(exc).__name__}
    if isinstance(exc, httpx.HTTPStatusError):
        return _http_status(exc.response.status_code, exc.response.headers.get("retry-after"))
    if isinstance(exc, urllib.error.HTTPError):
        return _http_status(exc.code, exc.headers.get("retry-after") if exc.headers else None)
    if isinstance(exc, (httpx.HTTPError, OSError)):
        return {"kind": "network_error", "detail": type(exc).__name__}
    if isinstance(exc, _RESPONSE_ERRORS):
        return {"kind": "invalid_response", "detail": f"{type(exc).__name__}: {exc}"}
    return {"kind": "unavailable", "detail": f"{type(exc).__name__}: {exc}"}


def _http_status(status_code: int, retry_after: str | None) -> dict[str, Any]:
    detail = f"HTTP {status_code}" + (f"; retry after {retry_after}s" if retry_after else "")
    return {"kind": "http_status", "status_code": status_code, "detail": detail}


def invalid_request(detail: str) -> dict[str, Any]:
    return {"kind": "invalid_request", "detail": detail}


def blocked(detail: str) -> dict[str, Any]:
    return {"kind": "blocked", "detail": detail}


def unavailable(detail: str) -> dict[str, Any]:
    return {"kind": "unavailable", "detail": detail}


def unreadable(detail: str) -> dict[str, Any]:
    return {"kind": "invalid_response", "detail": detail}


def records(source: str, query: Any, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"source": source, "query": query, "records": items}


def failed_records(source: str, query: Any, error: dict[str, Any]) -> dict[str, Any]:
    return {"source": source, "query": query, "records": [], "error": error}


def failed(error: dict[str, Any], **context: Any) -> dict[str, Any]:
    """For tools whose success shape is keyed by result id rather than enveloped."""
    return {**context, "error": error}
