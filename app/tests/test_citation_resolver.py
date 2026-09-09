"""Tests for the live evidence-identifier resolver (fidelity-audit G12).

``offline_resolver`` (app/citation_metadata.py) only ever reads back metadata a
source already claimed. These tests cover ``citation_resolver``'s
dereference logic in isolation, with the actual HTTP calls stubbed so the
suite stays hermetic (no network in CI). The PMID path specifically covers
why it goes through NCBI's ESummary API rather than a status-code check
against the human-facing PubMed page (see the module docstring): that page
returned 403 to a plain client during development regardless of headers,
which a status-code-only check would have silently misread as
"unresolvable" for every real, reachable article.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app import citation_resolver, retraction_set
from app.citation_metadata import (
    CitationMetadata,
    Resolvability,
    offline_resolver,
)


def _recording_reachable(calls: list[str], *, result: bool = True) -> object:
    """A ``_reachable`` stub that records the url it was called with."""

    def _stub(client: httpx.Client, url: str) -> bool:
        calls.append(url)
        return result

    return _stub


def _recording_pmid_found(calls: list[str], *, result: bool = True) -> object:
    """A ``_pmid_found`` stub that records the pmid it was called with."""

    def _stub(client: httpx.Client, pmid: str) -> bool:
        calls.append(pmid)
        return result

    return _stub


def test_retracted_short_circuits_without_a_network_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retracted article never reaches the network."""
    calls: list[str] = []
    monkeypatch.setattr(
        citation_resolver, "_reachable", _recording_reachable(calls)
    )
    monkeypatch.setattr(
        citation_resolver, "_pmid_found", _recording_pmid_found(calls)
    )

    verdict = citation_resolver.resolve_one(
        doi="10.1000/dead",
        pmid="999",
        url="https://example.org/dead",
        retracted=True,
    )

    assert verdict is Resolvability.RETRACTED
    assert calls == []


def test_no_identifier_is_unresolvable_without_a_network_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing to dereference means unresolvable, not a network call."""
    calls: list[str] = []
    monkeypatch.setattr(
        citation_resolver, "_reachable", _recording_reachable(calls)
    )

    verdict = citation_resolver.resolve_one(
        doi="", pmid="", url="", retracted=False
    )

    assert verdict is Resolvability.UNRESOLVABLE
    assert calls == []


def test_doi_is_preferred_over_pmid_and_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DOI resolves through doi.org even when a PMID/URL is also present."""
    seen: list[str] = []
    monkeypatch.setattr(
        citation_resolver, "_reachable", _recording_reachable(seen)
    )
    monkeypatch.setattr(
        citation_resolver, "_pmid_found", _recording_pmid_found(seen)
    )

    citation_resolver.resolve_one(
        doi="10.1000/xyz",
        pmid="12345",
        url="https://example.org/other",
        retracted=False,
    )

    assert seen == ["https://doi.org/10.1000/xyz"]


def test_pmid_is_preferred_over_a_bare_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A PMID (no DOI) is looked up rather than falling through to the URL."""
    pmid_calls: list[str] = []
    url_calls: list[str] = []
    monkeypatch.setattr(
        citation_resolver, "_pmid_found", _recording_pmid_found(pmid_calls)
    )
    monkeypatch.setattr(
        citation_resolver, "_reachable", _recording_reachable(url_calls)
    )

    verdict = citation_resolver.resolve_one(
        doi="", pmid="12345", url="https://example.org/other", retracted=False
    )

    assert verdict is Resolvability.RESOLVABLE
    assert pmid_calls == ["12345"]
    assert url_calls == []


def test_bare_url_is_checked_when_no_identifier_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With neither DOI nor PMID, the source-supplied URL is dereferenced."""
    seen: list[str] = []
    monkeypatch.setattr(
        citation_resolver, "_reachable", _recording_reachable(seen)
    )

    citation_resolver.resolve_one(
        doi="", pmid="", url="https://example.org/paper", retracted=False
    )

    assert seen == ["https://example.org/paper"]


def test_reachable_and_unreachable_land_differently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The verdict tracks the dereference outcome, not the string's shape."""
    monkeypatch.setattr(
        citation_resolver, "_reachable", lambda client, url: True
    )
    assert (
        citation_resolver.resolve_one(
            doi="10.1000/live", pmid="", url="", retracted=False
        )
        is Resolvability.RESOLVABLE
    )

    monkeypatch.setattr(
        citation_resolver, "_reachable", lambda client, url: False
    )
    assert (
        citation_resolver.resolve_one(
            doi="10.1000/dead-but-well-formed", pmid="", url="", retracted=False
        )
        is Resolvability.UNRESOLVABLE
    )


# --- _pmid_found (ESummary response parsing) --------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeEsummaryClient:
    """A fake ``httpx.Client`` returning a fixed ESummary-shaped payload."""

    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self._status_code = status_code
        self._payload = payload
        self.requested_params: dict[str, Any] | None = None

    def get(self, url: str, params: dict[str, Any]) -> _FakeResponse:
        self.requested_params = params
        return _FakeResponse(self._status_code, self._payload)


def test_pmid_found_true_for_a_record_without_an_error_field() -> None:
    """A PMID ESummary recognizes reads as found."""
    client = _FakeEsummaryClient(
        200,
        {"result": {"uids": ["23851394"], "23851394": {"uid": "23851394"}}},
    )

    assert citation_resolver._pmid_found(client, "23851394") is True  # type: ignore[arg-type]
    assert client.requested_params == {
        "db": "pubmed",
        "id": "23851394",
        "retmode": "json",
    }


def test_pmid_found_false_for_an_error_record() -> None:
    """ESummary answers 200 even for an unknown id, with an error field."""
    client = _FakeEsummaryClient(
        200,
        {
            "result": {
                "uids": ["999999999999"],
                "999999999999": {
                    "uid": "999999999999",
                    "error": "cannot get document summary",
                },
            }
        },
    )

    assert citation_resolver._pmid_found(client, "999999999999") is False  # type: ignore[arg-type]


def test_pmid_found_false_on_http_error() -> None:
    class _RaisingClient:
        def get(self, url: str, params: dict[str, Any]) -> _FakeResponse:
            raise httpx.ConnectError("no route")

    assert citation_resolver._pmid_found(_RaisingClient(), "1") is False  # type: ignore[arg-type]


def test_pmid_found_false_on_malformed_json() -> None:
    class _BadJsonResponse:
        status_code = 200

        def json(self) -> dict[str, Any]:
            raise json.JSONDecodeError("bad", "doc", 0)

    class _BadJsonClient:
        def get(self, url: str, params: dict[str, Any]) -> _BadJsonResponse:
            return _BadJsonResponse()

    assert citation_resolver._pmid_found(_BadJsonClient(), "1") is False  # type: ignore[arg-type]


# --- resolve_many -------------------------------------------------------


def test_resolve_many_preserves_input_order() -> None:
    """Concurrent resolution returns verdicts in the same order as input."""
    results = citation_resolver.resolve_many(
        [
            CitationMetadata(url="https://a"),
            CitationMetadata(url="https://b", retracted=True),
            CitationMetadata(url="https://c"),
        ],
        resolver=offline_resolver,
    )

    assert results == [
        Resolvability.RESOLVABLE,
        Resolvability.RETRACTED,
        Resolvability.RESOLVABLE,
    ]


def test_resolve_many_routes_every_verdict_through_the_seam() -> None:
    """The fan-out adds concurrency, never a second verdict implementation.

    ``resolve_many`` used to call ``resolve_one`` directly, leaving
    ``assess_resolvability`` and its ``Resolver`` protocol reachable only
    from their own unit tests while production ran the parallel path.
    """
    seen: list[CitationMetadata] = []

    def recording_resolver(meta: CitationMetadata) -> Resolvability:
        seen.append(meta)
        return Resolvability.UNRESOLVABLE

    metas = [CitationMetadata(doi="10.1/a"), CitationMetadata(pmid="7")]
    results = citation_resolver.resolve_many(metas, resolver=recording_resolver)

    assert results == [Resolvability.UNRESOLVABLE] * 2
    assert sorted(m.doi + m.pmid for m in seen) == ["10.1/a", "7"]


def test_live_resolver_is_the_production_resolver_implementation() -> None:
    """``live_resolver`` satisfies the protocol by dereferencing."""
    meta = CitationMetadata(url="https://x", doi="", pmid="", retracted=True)
    assert citation_resolver.live_resolver(meta) is Resolvability.RETRACTED


def test_resolve_many_empty_input_makes_no_calls() -> None:
    assert citation_resolver.resolve_many([], resolver=offline_resolver) == []


# --- offline retraction-set check (second, independent check) -----------


def test_offline_retracted_doi_short_circuits_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DOI in the offline set resolves RETRACTED without a network call."""
    calls: list[str] = []
    monkeypatch.setattr(
        retraction_set,
        "is_known_retracted",
        lambda doi: doi == "10.1000/offline-flagged",
    )
    monkeypatch.setattr(
        citation_resolver, "_reachable", _recording_reachable(calls)
    )

    verdict = citation_resolver.resolve_one(
        doi="10.1000/offline-flagged", pmid="", url="", retracted=False
    )

    assert verdict is Resolvability.RETRACTED
    assert calls == []


def test_doi_absent_from_offline_set_still_resolves_normally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DOI absent from the offline set still resolves normally.

    It falls through to the live dereference check.
    """
    monkeypatch.setattr(
        retraction_set,
        "is_known_retracted",
        lambda doi: False,
    )
    monkeypatch.setattr(
        citation_resolver, "_reachable", lambda client, url: True
    )

    verdict = citation_resolver.resolve_one(
        doi="10.1000/clean", pmid="", url="", retracted=False
    )

    assert verdict is Resolvability.RESOLVABLE


def test_source_flagged_retraction_never_consults_the_offline_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The source-flag fast path stays first.

    The offline set is only ever a fallback for what the source did not
    already catch.
    """

    def _fail_if_called(doi: str) -> bool:
        raise AssertionError("offline retraction set consulted needlessly")

    monkeypatch.setattr(retraction_set, "is_known_retracted", _fail_if_called)

    verdict = citation_resolver.resolve_one(
        doi="10.1000/already-flagged", pmid="", url="", retracted=True
    )

    assert verdict is Resolvability.RETRACTED
