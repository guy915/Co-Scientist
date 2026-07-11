"""HTTP client wrapper for the ``cosci`` CLI.

Centralizes base-URL and client-id resolution and turns transport and HTTP
errors into a :class:`CliError` with a clear, single-line message. Every
command goes through this so error handling and header injection live in one
place. Synchronous throughout: the CLI is a short-lived process, so there is no
benefit to an async client, and ``httpx.Client`` streams SSE responses fine.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Generator, Iterator
from typing import Any

import httpx

DEFAULT_API_URL = "http://localhost:8008"


class CliError(Exception):
    """A user-facing CLI failure carrying an exit code and a message.

    Raised for anything the caller should see as an error line on stderr: a
    connection failure, a non-2xx HTTP status, or an unusable response body.
    ``main`` catches it, prints ``message`` to stderr, and returns the code.
    """

    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        """Store the human-readable message and the process exit code."""
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


def _error_detail(response: httpx.Response) -> str:
    """Extract the most useful error text from a non-2xx response.

    FastAPI error bodies are ``{"detail": ...}``; fall back to the raw body or
    the HTTP reason phrase when the body is not the expected shape.
    """
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        return response.text.strip() or response.reason_phrase
    if isinstance(body, dict) and "detail" in body:
        detail = body["detail"]
        return detail if isinstance(detail, str) else json.dumps(detail)
    return json.dumps(body)


def _raise_for_status(response: httpx.Response) -> None:
    """Raise :class:`CliError` for a non-2xx response, else return."""
    if response.is_success:
        return
    method = response.request.method
    path = response.request.url.path
    raise CliError(
        f"HTTP {response.status_code} on {method} {path}: "
        f"{_error_detail(response)}"
    )


class ApiClient:
    """Synchronous httpx wrapper bound to one API base URL and client id.

    The optional client id is sent as the ``X-Client-ID`` header, which scopes
    run listings to the caller (see ``app.runs._client_id``); a missing id
    shares the header-less pool, matching the API's own default.
    """

    def __init__(
        self,
        base_url: str,
        client_id: str | None = None,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Bind the client to ``base_url`` with an optional ``client_id``.

        Args:
            base_url: Base URL of the Co-Scientist API.
            client_id: Optional ``X-Client-ID`` header value.
            timeout: Per-request timeout in seconds (streams read without one).
            transport: Optional httpx transport, used by tests to route
                requests at a stub (e.g. ``httpx.MockTransport``) instead of
                the network; production leaves it unset.
        """
        self.base_url = base_url.rstrip("/")
        self._headers: dict[str, str] = {}
        if client_id:
            self._headers["X-Client-ID"] = client_id
        self._timeout = timeout
        self._transport = transport

    def _client(self, timeout: httpx.Timeout | float) -> httpx.Client:
        """Build an httpx client honoring the injected transport, if any."""
        return httpx.Client(timeout=timeout, transport=self._transport)

    def _url(self, path: str) -> str:
        """Join the base URL with an API path beginning with ``/``."""
        return f"{self.base_url}{path}"

    def request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        """Send a request and return the decoded JSON body.

        Args:
            method: HTTP method, e.g. ``"GET"`` or ``"POST"``.
            path: API path beginning with ``/``.
            json_body: Optional request body serialized as JSON.

        Returns:
            The decoded JSON body (typically a dict).

        Raises:
            CliError: On a connection failure, a non-2xx status, or a body
                that is not valid JSON.
        """
        try:
            with self._client(self._timeout) as client:
                response = client.request(
                    method,
                    self._url(path),
                    json=json_body,
                    headers=self._headers,
                )
        except httpx.HTTPError as exc:
            raise CliError(
                f"could not reach API at {self.base_url}: {exc}"
            ) from exc
        _raise_for_status(response)
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise CliError(f"invalid JSON from {path}: {exc}") from exc

    def request_text(self, method: str, path: str) -> str:
        """Send a request and return the response body as text.

        Raises:
            CliError: On a connection failure or a non-2xx status.
        """
        try:
            with self._client(self._timeout) as client:
                response = client.request(
                    method, self._url(path), headers=self._headers
                )
        except httpx.HTTPError as exc:
            raise CliError(
                f"could not reach API at {self.base_url}: {exc}"
            ) from exc
        _raise_for_status(response)
        return response.text

    @contextlib.contextmanager
    def stream_lines(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> Generator[Iterator[str], None, None]:
        """Open a streaming response and yield its lines as they arrive.

        Used for the Server-Sent-Events endpoints (``/events`` and
        ``/messages/ask``). The stream has no read timeout because a live run
        can idle between events. A non-2xx status is surfaced as a
        :class:`CliError` before any line is yielded.

        Args:
            method: HTTP method for the streaming request.
            path: API path beginning with ``/``.
            json_body: Optional request body serialized as JSON.

        Yields:
            An iterator over decoded response lines (without trailing newlines).

        Raises:
            CliError: On a connection failure or a non-2xx status.
        """
        timeout = httpx.Timeout(self._timeout, read=None)
        try:
            with (
                self._client(timeout) as client,
                client.stream(
                    method,
                    self._url(path),
                    json=json_body,
                    headers=self._headers,
                ) as response,
            ):
                if not response.is_success:
                    response.read()
                    _raise_for_status(response)
                yield response.iter_lines()
        except httpx.HTTPError as exc:
            raise CliError(
                f"could not reach API at {self.base_url}: {exc}"
            ) from exc
