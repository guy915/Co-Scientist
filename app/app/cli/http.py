"""HTTP client wrapper for the ``cosci`` CLI.

Centralizes base-URL and client-id resolution and turns transport and HTTP
errors into a :class:`CliError` with a clear, single-line message. Every
command goes through this so error handling and header injection live in one
place. Synchronous throughout: the CLI is a short-lived process, so there is no
benefit to an async client, and ``httpx.Client`` streams SSE responses fine.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import sys
import time
from collections.abc import Generator, Iterator
from typing import Any

import httpx

DEFAULT_API_URL = "http://localhost:8008"

# Gateway statuses worth one more try: the API process is restarting or a
# proxy briefly lost it. 4xx and 500 are not listed; those reproduce.
RETRYABLE_STATUSES = frozenset({502, 503, 504})

# Extra attempts after the first, applied to GET requests only. POSTs are
# lifecycle actions and must not be replayed on an ambiguous failure.
GET_RETRIES = 2


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


class ApiUnreachableError(CliError):
    """A transport-level failure: the API could not be reached at all.

    Distinct from an HTTP-status :class:`CliError` so callers that retry
    (``runs watch`` reconnecting a dropped stream) can tell a transient
    network failure from a definitive API answer such as a 404.
    """


def expect_object(body: Any, context: str) -> dict[str, Any]:
    """Return ``body`` when it is a JSON object, else raise :class:`CliError`.

    Guards the text-rendering paths against a non-object payload (say, from a
    misconfigured proxy) surfacing as an ``AttributeError`` traceback.
    """
    if not isinstance(body, dict):
        raise CliError(f"unexpected non-object response from {context}")
    return body


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


@dataclasses.dataclass(frozen=True)
class ApiClientOptions:
    """Transport and diagnostics knobs for one :class:`ApiClient`.

    Attributes:
        timeout: Per-request timeout in seconds (streams read without one).
        retry_wait: Seconds to sleep between GET retry attempts.
        verbose: When true, log every request's method, path, status, and
            elapsed time to stderr (stdout stays parseable output only).
        transport: Optional httpx transport, used by tests to route requests
            at a stub (e.g. ``httpx.MockTransport``) instead of the network;
            production leaves it unset.
    """

    timeout: float = 30.0
    retry_wait: float = 0.5
    verbose: bool = False
    transport: httpx.BaseTransport | None = None


def _build_headers(
    client_id: str | None, logs_token: str | None
) -> dict[str, str]:
    """Build the header dict carrying the optional client/logs identity."""
    headers: dict[str, str] = {}
    if client_id:
        headers["X-Client-ID"] = client_id
    if logs_token:
        headers["X-Logs-Token"] = logs_token
    return headers


class ApiClient:
    """Synchronous httpx wrapper bound to one API base URL and client id.

    The optional client id is sent as the ``X-Client-ID`` header, which
    scopes run listings to the caller (see ``app.auth.client_id``); a
    caller-supplied ``client_id`` of ``None``/empty sends no header at all,
    which the API refuses for any creating call (see
    ``app.auth.require_client_scope``) -- ``app.cli.main.main`` never
    passes that through unresolved, always falling back to
    ``app.cli.identity.default_client_id`` first.
    """

    def __init__(
        self,
        base_url: str,
        client_id: str | None = None,
        logs_token: str | None = None,
        *,
        options: ApiClientOptions | None = None,
    ) -> None:
        """Bind the client to ``base_url`` with an optional ``client_id``.

        Args:
            base_url: Base URL of the Co-Scientist API. A bare host:port
                without a scheme is treated as ``http://``.
            client_id: Optional ``X-Client-ID`` header value.
            logs_token: Optional ``X-Logs-Token`` value, granting the
                app-wide log view when the API is not reached over
                loopback (Docker, or a remote deployment).
            options: Transport and diagnostics knobs; the defaults of
                :class:`ApiClientOptions` when omitted.
        """
        options = options or ApiClientOptions()
        if "://" not in base_url:
            base_url = f"http://{base_url}"
        self.base_url = base_url.rstrip("/")
        self._headers = _build_headers(client_id, logs_token)
        self._timeout = options.timeout
        self._retry_wait = options.retry_wait
        self._verbose = options.verbose
        self._transport = options.transport
        self._http_client: httpx.Client | None = None

    def _log(self, message: str) -> None:
        """Write one diagnostic line to stderr when verbose mode is on."""
        if self._verbose:
            print(f"cosci: {message}", file=sys.stderr)

    @property
    def _http(self) -> httpx.Client:
        """The shared httpx client, created on first use.

        One client for the ApiClient's lifetime, so polling loops (``runs
        wait``, ``logs --follow``) reuse a kept-alive connection instead of
        paying a TCP/TLS handshake per poll. Per-call timeout variations
        (the SSE stream's unbounded read) ride the request, not the client.
        """
        if self._http_client is None:
            self._http_client = httpx.Client(
                timeout=self._timeout, transport=self._transport
            )
        return self._http_client

    def close(self) -> None:
        """Close the shared httpx client, if one was ever created."""
        if self._http_client is not None:
            self._http_client.close()
            self._http_client = None

    def _url(self, path: str) -> str:
        """Join the base URL with an API path beginning with ``/``."""
        return f"{self.base_url}{path}"

    def _do_request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None,
    ) -> httpx.Response:
        """Send one HTTP request and log its status and elapsed time."""
        started = time.monotonic()
        response = self._http.request(
            method,
            self._url(path),
            json=json_body,
            headers=self._headers,
        )
        elapsed_ms = (time.monotonic() - started) * 1000
        self._log(
            f"{method} {path} -> {response.status_code} ({elapsed_ms:.0f} ms)"
        )
        return response

    def _send_attempt(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None,
        attempt: int,
        retries: int,
    ) -> httpx.Response | None:
        """Try one request attempt; return the response, or None to retry.

        Raises:
            ApiUnreachableError: On a transport error during the final
                attempt.
        """
        last = attempt == retries
        try:
            response = self._do_request(method, path, json_body)
        except httpx.HTTPError as exc:
            if last:
                raise ApiUnreachableError(
                    f"could not reach API at {self.base_url}: {exc}"
                ) from exc
            self._log(
                f"{method} {path} failed ({type(exc).__name__}); "
                f"retrying ({attempt + 2}/{retries + 1})"
            )
            return None
        if last or response.status_code not in RETRYABLE_STATUSES:
            return response
        self._log(
            f"{method} {path} got {response.status_code}; "
            f"retrying ({attempt + 2}/{retries + 1})"
        )
        return None

    def _send(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Send one request, retrying transient failures on GETs.

        GETs are retried up to :data:`GET_RETRIES` extra times on transport
        errors and :data:`RETRYABLE_STATUSES`; other methods get exactly one
        attempt because replaying a lifecycle POST on an ambiguous failure
        could apply it twice.

        Raises:
            CliError: When the API stays unreachable across all attempts.
        """
        retries = GET_RETRIES if method.upper() == "GET" else 0
        for attempt in range(retries + 1):
            response = self._send_attempt(
                method, path, json_body, attempt, retries
            )
            if response is not None:
                return response
            time.sleep(self._retry_wait)
        raise AssertionError("unreachable: retry loop always returns/raises")

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
        response = self._send(method, path, json_body=json_body)
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
        response = self._send(method, path)
        _raise_for_status(response)
        return response.text

    def _validate_stream_response(
        self, response: httpx.Response, method: str, path: str
    ) -> None:
        """Raise for a non-2xx streaming response, else log its status."""
        if not response.is_success:
            response.read()
            _raise_for_status(response)
        self._log(f"{method} {path} -> {response.status_code} (streaming)")

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
            with self._http.stream(
                method,
                self._url(path),
                json=json_body,
                headers=self._headers,
                timeout=timeout,
            ) as response:
                self._validate_stream_response(response, method, path)
                yield response.iter_lines()
        except httpx.HTTPError as exc:
            raise ApiUnreachableError(
                f"could not reach API at {self.base_url}: {exc}"
            ) from exc
