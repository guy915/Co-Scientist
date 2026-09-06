"""Tests for the OpenAlex literature search tool.

``normalize_works`` is pure and tested directly; ``search_openalex`` is tested
with a fake httpx client (no network) via ``asyncio.run`` so no pytest-asyncio
configuration is required.
"""

import asyncio
from typing import Any

import httpx
import pytest
from mcp_server.tools.lit_review.openalex_search import (
    OpenAlexUnavailableError,
    _build_search_params,
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
                {"author": {"display_name": "Ada Lovelace"}},
                {"author": {"display_name": "Alan Turing"}},
            ],
            "abstract_inverted_index": {
                "Nitrogen": [0],
                "fixation": [1],
                "matters": [2],
            },
            "primary_location": {"landing_page_url": "https://example/w123"},
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
    assert w["is_retracted"] is False


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


class _PagedClient:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self._pages = iter(pages)
        self.cursors: list[str] = []

    async def __aenter__(self) -> "_PagedClient":
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False

    async def get(self, _url: str, params: Any = None) -> _FakeResp:
        self.cursors.append(str(params["cursor"]))
        return _FakeResp(next(self._pages))


def test_search_openalex_returns_normalized(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_: _FakeClient(_FakeResp(_SAMPLE)),
    )
    out = asyncio.run(search_openalex("nitrogen fixation", max_papers=5))
    assert "W123" in out
    assert out["W123"]["source"] == "openalex"


def test_search_openalex_raises_when_it_cannot_be_asked(
    monkeypatch: Any,
) -> None:
    """A source that refused is not a source with nothing to say.

    Collapsing the two hid a dead source for a whole credentialed run:
    26 searches, every one refused, every one recorded as an empty
    result set.
    """
    err = httpx.HTTPError("boom")
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_: _FakeClient(_FakeResp(None, raise_exc=err)),
    )

    with pytest.raises(OpenAlexUnavailableError, match="could not be"):
        asyncio.run(search_openalex("q"))


def test_a_rate_limit_says_how_long_and_why(monkeypatch: Any) -> None:
    """A 429 says how long the caller is locked out, and why.

    OpenAlex meters its free tier, so this is the failure this source
    actually has, and its body carries the only part worth reading.
    """
    response = httpx.Response(
        429,
        headers={"retry-after": "6810"},
        json={"error": "Rate limit exceeded", "message": "Insufficient budget"},
        request=httpx.Request("GET", "https://api.openalex.org/works"),
    )
    err = httpx.HTTPStatusError(
        "429", request=response.request, response=response
    )
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_: _FakeClient(_FakeResp(None, raise_exc=err)),
    )

    with pytest.raises(OpenAlexUnavailableError) as raised:
        asyncio.run(search_openalex("q"))

    message = str(raised.value)
    assert "HTTP 429" in message
    assert "Insufficient budget" in message
    assert "retry after 6810s" in message


def test_no_match_is_still_an_empty_result(monkeypatch: Any) -> None:
    """The other half of the distinction: asked, answered, nothing there."""
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **_: _FakeClient(_FakeResp({"results": [], "meta": {}})),
    )

    assert asyncio.run(search_openalex("q")) == {}


def test_search_openalex_uses_cursor_pagination(monkeypatch: Any) -> None:
    second = {
        "results": [
            {
                "id": "https://openalex.org/W789",
                "title": "Third work",
            }
        ],
        "meta": {"next_cursor": None},
    }
    first = {**_SAMPLE, "meta": {"next_cursor": "cursor-2"}}
    client = _PagedClient([first, second])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)

    out = asyncio.run(search_openalex("nitrogen fixation", max_papers=3))

    assert set(out) == {"W123", "W456", "W789"}
    assert client.cursors == ["*", "cursor-2"]


def test_search_params_exclude_retractions_and_support_api_key(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("OPENALEX_API_KEY", "key")
    params, per_page = _build_search_params("q", 250, 5)

    assert per_page == 100
    assert params["cursor"] == "*"
    assert params["api_key"] == "key"
    assert "is_retracted:false" in params["filter"]


def test_wildcards_are_stripped_before_reaching_openalex() -> None:
    """Wildcards must never reach OpenAlex's default `search` param.

    A live check confirms it 400s there ("Wildcards (* or ?) require
    exact (no-stem) search... Use the search.exact= parameter instead"),
    so a model-written query using them must reach the API without them
    rather than fail the whole call.
    """
    params, _ = _build_search_params(
        "glioblastoma repurpos* drug?", max_papers=10, recency_years=0
    )

    assert "*" not in params["search"]
    assert "?" not in params["search"]
    assert params["search"] == "glioblastoma repurpos drug"


def test_wildcard_stripping_collapses_the_resulting_whitespace() -> None:
    params, _ = _build_search_params("a* * b", max_papers=10, recency_years=0)

    assert params["search"] == "a b"


def test_a_clean_query_is_untouched() -> None:
    params, _ = _build_search_params(
        '"exact phrase" AND glioblastoma', max_papers=10, recency_years=0
    )

    assert params["search"] == '"exact phrase" AND glioblastoma'
