"""Shared httpx stand-ins for the tools that call a remote HTTP API.

Every tool in this package reaches its upstream through a fresh
``httpx.AsyncClient`` context manager, so the whole suite fakes the same
seam: patch ``httpx.AsyncClient`` with something that answers ``post``
(the INDRA CoGex endpoints) or ``get`` (the ChEMBL/UniProt lookups) from
canned data instead of opening a socket. Those stand-ins live here, in
one place, because six tool-family modules each carrying their own copy
is exactly how three mutually incompatible client shapes grew from one
original.

The convention is ``engine/tests``': an underscore-prefixed helper module
exporting names without the underscore. Only the import path differs, and
not by choice -- ``mcp_server`` is itself a package, so this directory's
dotted name is ``mcp_server.tests`` even without an ``__init__.py``, and
that is the name both pytest and mypy resolve. Importing it any shorter
way gives mypy two names for one file, which it rejects outright.
"""

from typing import Any

import httpx
import pytest


class StubResponse:
    """A canned httpx.Response standing in for a real upstream reply."""

    def __init__(self, payload: Any) -> None:
        """Store the payload ``json`` hands back."""
        self._payload = payload

    def raise_for_status(self) -> None:
        """Represent a 2xx response: never raises."""

    def json(self) -> Any:
        """Return the fixture payload."""
        return self._payload


class StubClient:
    """A canned httpx.AsyncClient serving queued payloads, or raising.

    Payloads are served in call order, which is what a tool issuing more
    than one request needs (the gene-disease network follows its genes
    call with a variants call); a single-request tool simply queues one.
    Every request is recorded as ``(url, payload)`` -- the JSON body for a
    POST, the query params for a GET -- so tests can assert on the
    request the tool built as well as on what it did with the answer.
    """

    def __init__(
        self,
        responses: list[Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        """Queue the payloads to serve, or the error to raise instead.

        Args:
            responses: Payloads returned in call order, one per request.
            error: Exception raised by every request instead of answering.
        """
        self._responses = list(responses) if responses else []
        self._error = error
        self.calls: list[tuple[str, Any]] = []

    async def __aenter__(self) -> "StubClient":
        """Enter the async context manager every tool opens."""
        return self

    async def __aexit__(self, *_: Any) -> bool:
        """Leave the context manager without suppressing exceptions."""
        return False

    async def get(self, url: str, **kwargs: Any) -> StubResponse:
        """Record the GET and serve the next queued payload."""
        return self._serve(url, kwargs.get("params"))

    async def post(self, url: str, json: Any = None, **_: Any) -> StubResponse:
        """Record the POST and serve the next queued payload.

        Keyword arguments beyond the body are accepted and ignored, the
        same way ``get`` ignores everything but ``params``: a caller that
        sends auth headers (Tavily) must not need a second stub.
        """
        return self._serve(url, json)

    def _serve(self, url: str, payload: Any) -> StubResponse:
        """Record one request, then raise the error or pop a response."""
        self.calls.append((url, payload))
        if self._error is not None:
            raise self._error
        if not self._responses:
            raise AssertionError(f"stub has no response queued for {url}")
        return StubResponse(self._responses.pop(0))


def _install(monkeypatch: pytest.MonkeyPatch, client: StubClient) -> StubClient:
    """Patch ``httpx.AsyncClient`` to hand out ``client``, and return it."""
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)
    return client


def stub_responses(
    monkeypatch: pytest.MonkeyPatch, *payloads: Any
) -> StubClient:
    """Patch httpx.AsyncClient to serve ``payloads`` in call order.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        *payloads: One payload per request the tool under test makes.

    Returns:
        The installed client, whose ``calls`` record those requests.
    """
    return _install(monkeypatch, StubClient(responses=list(payloads)))


def stub_failure(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> StubClient:
    """Patch httpx.AsyncClient to raise ``error`` instead of responding.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        error: The transport failure every request raises.

    Returns:
        The installed client, whose ``calls`` record those requests.
    """
    return _install(monkeypatch, StubClient(error=error))


def stub_unreachable(
    monkeypatch: pytest.MonkeyPatch,
    message: str = "must not reach the network",
) -> StubClient:
    """Patch httpx.AsyncClient so any request at all fails the test.

    For the branches a tool must reject before issuing a request. The
    RuntimeError is never asserted on; it exists so a leaked request
    surfaces as this message instead of as a quietly passing test.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
        message: The RuntimeError text a leaked request would carry.

    Returns:
        The installed client, whose ``calls`` stay empty when the tool
        short-circuits as intended.
    """
    return stub_failure(monkeypatch, RuntimeError(message))
