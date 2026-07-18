"""Tests for web-search response normalization and provider selection.

Normalization is pure, so it is tested directly with no network, matching
test_openalex.py.
"""

from typing import Any

import pytest
from mcp_server.tools.web.providers import (
    _brave_freshness,
    clean_snippet,
    normalize_brave,
    normalize_tavily,
    resolve_provider,
)

_BRAVE_PAYLOAD: dict[str, Any] = {
    "web": {
        "results": [
            {
                "title": "GLP-1 trial results",
                "url": "https://example.com/a",
                "description": "A phase 2 readout.",
                "page_age": "2026-05-01",
                "profile": {"name": "Example News"},
            },
            {
                "title": "Follow-up analysis",
                "url": "https://example.org/b",
                "description": "Secondary endpoints.",
            },
        ]
    }
}

_TAVILY_PAYLOAD: dict[str, Any] = {
    "results": [
        {
            "title": "GLP-1 trial results",
            "url": "https://example.com/a",
            "content": "Extracted page text.",
            "published_date": "2026-05-01",
            "score": 0.91,
        }
    ]
}


def test_normalize_brave_maps_fields() -> None:
    out = normalize_brave(_BRAVE_PAYLOAD, max_results=10)
    assert len(out) == 2
    first = out[next(iter(out))]
    assert first["title"] == "GLP-1 trial results"
    assert first["url"] == "https://example.com/a"
    # The snippet lands in abstract because that is the field the engine's
    # article pipeline reads for summary text.
    assert first["abstract"] == "A phase 2 readout."
    assert first["source"] == "web"
    assert first["site"] == "Example News"


def test_normalize_brave_respects_max_results() -> None:
    assert len(normalize_brave(_BRAVE_PAYLOAD, max_results=1)) == 1


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("<strong>GLP-1</strong> agonists", "GLP-1 agonists"),
        ("Trials &amp; results", "Trials & results"),
        ("line one\n\n  line two", "line one line two"),
        ("<p>nested <em>tags</em> here</p>", "nested tags here"),
        # Encoded markup must not survive as a live tag: strip first, then
        # unescape, so this stays inert text.
        ("&lt;script&gt;alert(1)&lt;/script&gt;", "<script>alert(1)</script>"),
        (None, ""),
        ("", ""),
        (123, ""),
    ],
)
def test_clean_snippet(raw: Any, expected: str) -> None:
    assert clean_snippet(raw) == expected


def test_normalize_brave_strips_markup_from_snippets() -> None:
    """Brave wraps query terms in <strong>; the agent must never see tags."""
    payload = {
        "web": {
            "results": [
                {
                    "title": "<strong>GLP-1</strong> readout",
                    "url": "https://example.com/a",
                    "description": "<strong>GLP-1</strong> met the endpoint.",
                }
            ]
        }
    }
    entry = normalize_brave(payload, max_results=1)
    first = entry[next(iter(entry))]
    assert first["title"] == "GLP-1 readout"
    assert first["abstract"] == "GLP-1 met the endpoint."
    assert "<" not in first["abstract"]


def test_normalize_brave_skips_results_without_url() -> None:
    payload = {"web": {"results": [{"title": "no url"}, "not a dict"]}}
    assert normalize_brave(payload, max_results=10) == {}


def test_result_ids_are_stable_across_calls() -> None:
    """Keeps a stable id for the same page across calls.

    source_id keys off the URL digest, and lineage and dedup depend on it
    staying constant across runs.
    """
    first = normalize_brave(_BRAVE_PAYLOAD, max_results=10)
    second = normalize_brave(_BRAVE_PAYLOAD, max_results=10)
    assert list(first.keys()) == list(second.keys())
    # Not the randomized built-in hash.
    assert all("-" in key for key in first)


@pytest.mark.parametrize(
    "payload", [{}, {"web": None}, {"web": {"results": "nope"}}, None, []]
)
def test_normalize_brave_tolerates_malformed_payloads(payload: Any) -> None:
    assert normalize_brave(payload, max_results=10) == {}


def test_normalize_tavily_maps_extracted_content() -> None:
    out = normalize_tavily(_TAVILY_PAYLOAD, max_results=10)
    entry = out[next(iter(out))]
    assert entry["abstract"] == "Extracted page text."
    assert entry["score"] == 0.91
    assert entry["source"] == "web"


@pytest.mark.parametrize("payload", [{}, {"results": None}, None])
def test_normalize_tavily_tolerates_malformed_payloads(payload: Any) -> None:
    assert normalize_tavily(payload, max_results=10) == {}


@pytest.mark.parametrize(
    "days,expected",
    [(0, None), (1, "pd"), (5, "pw"), (30, "pm"), (200, "py"), (5000, None)],
)
def test_brave_freshness_buckets(days: int, expected: str | None) -> None:
    assert _brave_freshness(days) == expected


def test_resolve_provider_returns_none_without_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    assert resolve_provider() is None


def test_resolve_provider_autodetects_brave_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    monkeypatch.setenv("BRAVE_API_KEY", "k")
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    resolved = resolve_provider()
    assert resolved is not None and resolved[0] == "brave"


def test_explicit_provider_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("BRAVE_API_KEY", "k")
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    resolved = resolve_provider()
    assert resolved is not None and resolved[0] == "tavily"


def test_explicit_provider_without_key_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "tavily")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("BRAVE_API_KEY", "k")
    resolved = resolve_provider()
    assert resolved is not None and resolved[0] == "brave"


def test_unknown_provider_falls_back_to_autodetect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "bing")
    monkeypatch.setenv("BRAVE_API_KEY", "k")
    resolved = resolve_provider()
    assert resolved is not None and resolved[0] == "brave"


async def test_search_web_returns_empty_without_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_server.tools.web.web_search import search_web

    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    assert await search_web("anything") == {}


@pytest.mark.parametrize(
    "requested,expected", [(500, 20), (0, 1), (-3, 1), (8, 8)]
)
async def test_search_web_clamps_max_results(
    monkeypatch: pytest.MonkeyPatch, requested: int, expected: int
) -> None:
    """A model can ask for any number; the provider must see a sane one."""
    from mcp_server.tools.web import web_search as web_search_module

    captured: dict[str, int] = {}

    async def _fake_search(
        query: str, max_results: int, recency_days: int
    ) -> dict[str, Any]:
        captured["max_results"] = max_results
        captured["recency_days"] = recency_days
        return {}

    monkeypatch.setattr(
        web_search_module, "resolve_provider", lambda: ("brave", _fake_search)
    )
    await web_search_module.search_web("q", max_results=requested)
    assert captured["max_results"] == expected


async def test_search_web_floors_negative_recency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_server.tools.web import web_search as web_search_module

    captured: dict[str, int] = {}

    async def _fake_search(
        query: str, max_results: int, recency_days: int
    ) -> dict[str, Any]:
        captured["recency_days"] = recency_days
        return {}

    monkeypatch.setattr(
        web_search_module, "resolve_provider", lambda: ("brave", _fake_search)
    )
    await web_search_module.search_web("q", recency_days=-10)
    assert captured["recency_days"] == 0
