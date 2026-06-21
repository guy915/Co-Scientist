"""Tests for the OpenAlex literature search tool.

``normalize_works`` is pure and tested directly; ``search_openalex`` is tested
with a fake httpx client (no network) via ``asyncio.run`` so no pytest-asyncio
configuration is required.
"""

import asyncio
from typing import Any

import httpx

from mcp_server.tools.lit_review.openalex_search import (
    normalize_works,
    search_openalex,
)

_SAMPLE: dict[str, Any] = {
    "results": [
        {
            "id": "https://openalex.org/W123",
            "title": "Ambient nitrogen fixation",
            "publication_year": 2023,
            "authorships": [
                {
                    "author": {
                        "display_name": "Ada Lovelace"
                    }
                },
                {
                    "author": {
                        "display_name": "Alan Turing"
                    }
                },
            ],
            "abstract_inverted_index": {
                "Nitrogen": [0],
                "fixation": [1],
                "matters": [2],
            },
            "primary_location": {
                "landing_page_url": "https://example/w123"
            },
            "doi": "https://doi.org/10.1/x",
        },
        {
            "id": "https://openalex.org/W456",
            "display_name": "Second work",
            "publication_year": 2020,
            "authorships": [],
            "abstract_inverted_index": None,
            "primary_location": {},
            "doi": "https://doi.org/10.2/y",
        },
    ]
}


def test_normalize_basic_fields() -> None:
    out = normalize_works(_SAMPLE, max_papers=10)
    assert set(out) == {"W123", "W456"}
    w = out["W123"]
    assert w["title"] == "Ambient nitrogen fixation"
    assert w["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert w["year"] == 2023
    assert w["abstract"] == "Nitrogen fixation matters"
    assert w["url"] == "https://example/w123"
    assert w["source"] == "openalex"


def test_normalize_falls_back_to_doi_url_and_display_name() -> None:
    out = normalize_works(_SAMPLE, max_papers=10)
    w = out["W456"]
    assert w["title"] == "Second work"
    assert w["abstract"] == ""  # no inverted index
    assert w["url"] == "https://doi.org/10.2/y"  # no landing page -> doi


def test_normalize_caps_results() -> None:
    out = normalize_works(_SAMPLE, max_papers=1)
    assert len(out) == 1


def test_normalize_handles_garbage() -> None:
    assert normalize_works({}, 10) == {}
    assert normalize_works({"results": "nope"}, 10) == {}
    assert normalize_works({"results": [None, 7]}, 10) == {}


class _FakeResp:

    def __init__(self, data: Any, raise_exc: Exception | None = None) -> None:
        self._data = data
        self._raise = raise_exc

    def raise_for_status(self) -> None:
        if self._raise is not None:
            raise self._raise

    def json(self) -> Any:
        return self._data


class _FakeClient:

    def __init__(self, resp: _FakeResp) -> None:
        self._resp = resp

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False

    async def get(self, _url: str, params: Any = None) -> _FakeResp:
        return self._resp


def test_search_openalex_returns_normalized(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_: _FakeClient(_FakeResp(_SAMPLE)),
    )
    out = asyncio.run(search_openalex("nitrogen fixation", max_papers=5))
    assert "W123" in out
    assert out["W123"]["source"] == "openalex"


def test_search_openalex_degrades_on_http_error(monkeypatch: Any) -> None:
    err = httpx.HTTPError("boom")
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_: _FakeClient(_FakeResp(None, raise_exc=err)),
    )
    # A transport error must degrade to an empty dict, not raise.
    assert asyncio.run(search_openalex("q")) == {}
