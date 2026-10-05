import socket
from typing import Any

import httpx
import pytest
from mcp_server.tests._httpx import stub_failure, stub_responses
from mcp_server.tools import web_providers as providers
from mcp_server.tools.web_fetch import (
    UrlNotFetchableError,
    check_fetchable,
    read_url,
)
from mcp_server.tools.web_providers import (
    _clear_credential_error,
    _record_credential_error,
    check_web_search_available,
    resolve_provider,
    search_brave,
    search_tavily,
    search_web,
    web_search_credential_error,
)

_PUBLIC = {"example.com": "93.184.216.34"}


@pytest.fixture
def resolve_to(monkeypatch: pytest.MonkeyPatch) -> Any:

    def _apply(mapping: dict[str, str]) -> None:
        def resolve(host: str, *args: Any, **kwargs: Any) -> list[Any]:
            if host not in mapping:
                raise socket.gaierror(f"unknown host {host}")
            address = (mapping[host], 0)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", address)]

        monkeypatch.setattr(socket, "getaddrinfo", resolve)

    return _apply


def test_allows_public_https_url(resolve_to: Any) -> None:
    resolve_to(_PUBLIC)
    check_fetchable("https://example.com/article")


@pytest.mark.parametrize(
    ("url", "resolves", "reason"),
    [
        ("file:///etc/passwd", {}, "scheme"),
        ("http:///nowhere", {}, "no host"),
        (
            "http://localhost:8008/api/runs",
            {"localhost": "127.0.0.1"},
            "non-public",
        ),
        (
            "http://mcp.railway.internal:8888/mcp",
            {"mcp.railway.internal": "10.0.1.5"},
            "non-public",
        ),
        # Hostname text alone cannot detect public names resolving to
        # private addresses.
        (
            "http://127.0.0.1.nip.io/admin",
            {"127.0.0.1.nip.io": "127.0.0.1"},
            "non-public",
        ),
        ("http://2130706433/", {"2130706433": "127.0.0.1"}, "non-public"),
        (
            "http://metadata.example/",
            {"metadata.example": "169.254.169.254"},
            "non-public",
        ),
        ("http://169.254.169.254/latest/meta-data/", {}, "not allowed"),
        ("https://no-such-host.invalid/", {}, "does not resolve"),
    ],
)
def test_unsafe_urls_are_rejected(
    resolve_to: Any, url: str, resolves: dict[str, str], reason: str
) -> None:
    resolve_to(resolves)
    with pytest.raises(UrlNotFetchableError, match=reason):
        check_fetchable(url)


_PAGE = """
<html>
  <head><title>Trial readout</title><style>body{color:red}</style></head>
  <body>
    <nav><a href="/">Home</a><a href="/about">About</a></nav>
    <script>analytics()</script>
    <article>
      <h1>Phase 2 results</h1>
      <p>The primary endpoint was met.</p>
      <h2>Methods</h2>
      <ul><li>Randomized</li><li>Double blind</li></ul>
    </article>
    <footer>Copyright 2026</footer>
  </body>
</html>
"""


def _page(status: int, content: bytes, content_type: str | None) -> Any:
    return httpx.Response(
        status,
        content=content,
        headers={"content-type": content_type} if content_type else {},
        request=httpx.Request("GET", "https://example.com/a"),
    )


def _redirect(location: str) -> httpx.Response:
    return httpx.Response(
        302,
        headers={"location": location},
        request=httpx.Request("GET", "https://example.com/a"),
    )


@pytest.mark.parametrize("url", ["http://localhost:8008/api/runs", "file:///x"])
async def test_read_url_reports_a_blocked_url_as_text(url: str) -> None:
    assert (await read_url(url)).startswith("[blocked:")


async def test_read_url_extracts_readable_text_without_page_furniture(
    monkeypatch: pytest.MonkeyPatch, resolve_to: Any
) -> None:
    resolve_to(_PUBLIC)
    stub_responses(
        monkeypatch, _page(200, _PAGE.encode(), "text/html; charset=utf-8")
    )

    text = await read_url("https://example.com/a")

    for kept in (
        "# Trial readout",
        "# Phase 2 results",
        "## Methods",
        "The primary endpoint was met.",
        "- Randomized",
    ):
        assert kept in text
    for noise in ("analytics()", "color:red", "About", "Copyright 2026"):
        assert noise not in text


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("<html><body><div>Bare content here</div></body></html>", "Bare"),
        (f"<html><body><p>{'x' * 60_000}</p></body></html>", "xxxx"),
    ],
)
async def test_read_url_handles_div_only_and_oversized_pages(
    monkeypatch: pytest.MonkeyPatch, resolve_to: Any, body: str, expected: str
) -> None:
    resolve_to(_PUBLIC)
    stub_responses(monkeypatch, _page(200, body.encode(), "text/html"))

    text = await read_url("https://example.com/a")

    assert expected in text
    assert len(text) <= 50_000


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (_page(404, b"nope", None), "[error: HTTP 404"),
        (
            _page(200, b"\x00\x01", "image/png"),
            "[note: unsupported content type image/png",
        ),
    ],
)
async def test_read_url_reports_failures_and_unreadable_types_as_text(
    monkeypatch: pytest.MonkeyPatch,
    resolve_to: Any,
    response: httpx.Response,
    expected: str,
) -> None:
    resolve_to(_PUBLIC)
    stub_responses(monkeypatch, response)

    assert (await read_url("https://example.com/a")).startswith(expected)


async def test_read_url_screens_every_redirect_hop(
    monkeypatch: pytest.MonkeyPatch, resolve_to: Any
) -> None:
    resolve_to(_PUBLIC | {"internal.example": "10.0.0.5"})
    client = stub_responses(
        monkeypatch, _redirect("http://internal.example/admin")
    )

    result = await read_url("https://example.com/a")

    assert result.startswith("[blocked:")
    assert len(client.calls) == 1


async def test_read_url_follows_a_safe_redirect_and_cuts_off_loops(
    monkeypatch: pytest.MonkeyPatch, resolve_to: Any
) -> None:
    resolve_to(_PUBLIC)
    stub_responses(
        monkeypatch,
        _redirect("https://example.com/b"),
        _page(200, b"<p>Landed</p>", "text/html"),
    )
    assert "Landed" in await read_url("https://example.com/a")

    stub_responses(monkeypatch, *[_redirect("https://example.com/a")] * 5)
    result = await read_url("https://example.com/a")
    assert result.startswith("[blocked: too many redirects")


_BRAVE_PAYLOAD: dict[str, Any] = {
    "web": {
        "results": [
            {
                "title": "<strong>GLP-1</strong> trial results",
                "url": "https://example.com/a",
                "description": "<strong>GLP-1</strong> met &amp; passed.",
                "page_age": "2026-05-01",
                "profile": {"name": "Example News"},
            },
            {
                "title": "Follow-up",
                "url": "https://example.org/b",
                # Strip markup before unescaping so encoded tags stay inert.
                "description": "&lt;script&gt;alert(1)&lt;/script&gt;",
            },
            {"title": "no url"},
            "not a dict",
        ]
    }
}


async def test_brave_results_normalize_into_clean_stable_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_responses(monkeypatch, *[_BRAVE_PAYLOAD] * 3)

    out = await search_brave("glp-1", 10, 0)
    again = await search_brave("glp-1", 10, 0)
    capped = await search_brave("glp-1", 1, 0)

    first, second = out.values()
    assert first == {
        "title": "GLP-1 trial results",
        "url": "https://example.com/a",
        "abstract": "GLP-1 met & passed.",
        "published_date": "2026-05-01",
        "site": "Example News",
        "source": "web",
    }
    assert second["abstract"] == "<script>alert(1)</script>"
    # Lineage and dedup depend on stable URL-based ids across runs.
    assert list(out) == list(again)
    assert len(capped) == 1


async def test_tavily_results_carry_extracted_page_text_and_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_responses(
        monkeypatch,
        {
            "results": [
                {
                    "title": "GLP-1 trial results",
                    "url": "https://example.com/a",
                    "content": "Extracted page text.",
                    "published_date": "2026-05-01",
                    "score": 0.91,
                }
            ]
        },
    )

    (entry,) = (await search_tavily("glp-1", 5, 30)).values()

    assert entry["abstract"] == "Extracted page text."
    assert entry["score"] == 0.91
    assert entry["source"] == "web"


@pytest.mark.parametrize(
    "payload", [{}, {"web": None}, {"web": {"results": "nope"}}, None, []]
)
async def test_a_malformed_provider_answer_is_no_results(
    monkeypatch: pytest.MonkeyPatch, payload: Any
) -> None:
    stub_responses(monkeypatch, payload, payload)

    assert await search_brave("q", 10, 0) == {}
    assert await search_tavily("q", 10, 0) == {}


@pytest.mark.parametrize(
    ("days", "freshness"),
    [(0, None), (1, "pd"), (5, "pw"), (30, "pm"), (200, "py"), (5000, None)],
)
async def test_brave_buckets_recency_into_its_freshness_codes(
    monkeypatch: pytest.MonkeyPatch, days: int, freshness: str | None
) -> None:
    client = stub_responses(monkeypatch, {})

    await search_brave("q", 5, days)

    assert client.calls[0][1].get("freshness") == freshness


@pytest.mark.parametrize(
    ("requested", "recency", "max_results", "recency_days"),
    [(500, 5, 20, 5), (0, 0, 1, 0), (-3, -10, 1, 0), (8, 0, 8, 0)],
)
async def test_search_web_clamps_its_limits(
    monkeypatch: pytest.MonkeyPatch,
    requested: int,
    recency: int,
    max_results: int,
    recency_days: int,
) -> None:
    seen: list[tuple[int, int]] = []

    async def fake_search(query: str, limit: int, days: int) -> dict[str, Any]:
        seen.append((limit, days))
        return {}

    monkeypatch.setattr(
        providers, "candidate_providers", lambda: [("brave", fake_search)]
    )
    await search_web("q", max_results=requested, recency_days=recency)

    assert seen == [(max_results, recency_days)]


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> Any:
    def configure(
        brave: bool = False, tavily: bool = False, prefer: str | None = None
    ) -> None:
        for name, present in (
            ("BRAVE_API_KEY", brave),
            ("TAVILY_API_KEY", tavily),
        ):
            if present:
                monkeypatch.setenv(name, "k")
            else:
                monkeypatch.delenv(name, raising=False)
        if prefer:
            monkeypatch.setenv("WEB_SEARCH_PROVIDER", prefer)
        else:
            monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)

    return configure


@pytest.fixture
def _clear_credential_state() -> Any:
    """Provider refusal records are process-wide."""
    _clear_credential_error()
    yield
    _clear_credential_error()


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.invalid/search")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(
        f"{status}", request=request, response=response
    )


@pytest.mark.usefixtures("_clear_credential_state")
class TestWebSearchProviders:
    @pytest.mark.parametrize(
        ("keyed", "prefer", "refused", "chosen"),
        [
            ({}, None, [], None),
            ({"brave", "tavily"}, None, [], "brave"),
            ({"brave", "tavily"}, "tavily", [], "tavily"),
            ({"brave"}, "tavily", [], "brave"),
            ({"brave"}, "bing", [], "brave"),
            ({"brave", "tavily"}, None, ["brave"], "tavily"),
            ({"brave", "tavily"}, "tavily", ["tavily"], "brave"),
            # Only success clears refusal records; trying a provider keeps
            # monthly resets discoverable.
            ({"brave", "tavily"}, None, ["brave", "tavily"], "brave"),
        ],
    )
    def test_the_provider_is_chosen_by_preference_keys_and_refusals(
        self,
        keys: Any,
        keyed: set[str],
        prefer: str | None,
        refused: list[str],
        chosen: str | None,
    ) -> None:
        keys("brave" in keyed, "tavily" in keyed, prefer)
        for provider in refused:
            _record_credential_error(provider, 402, "quota gone")

        resolved = resolve_provider()

        assert (resolved[0] if resolved else None) == chosen

    @pytest.mark.parametrize(
        ("search", "key", "status", "provider"),
        [
            (search_brave, "BRAVE_API_KEY", 401, "brave"),
            (search_brave, "BRAVE_API_KEY", 402, "brave"),
            (search_brave, "BRAVE_API_KEY", 403, "brave"),
            (search_tavily, "TAVILY_API_KEY", 401, "tavily"),
            (search_tavily, "TAVILY_API_KEY", 432, "tavily"),
            (search_tavily, "TAVILY_API_KEY", 433, "tavily"),
        ],
    )
    async def test_a_rejected_key_is_recorded_not_swallowed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        search: Any,
        key: str,
        status: int,
        provider: str,
    ) -> None:
        monkeypatch.setenv(key, "k")
        stub_failure(monkeypatch, _status_error(status))

        assert await search("anything", 5, 0) == {}

        recorded = web_search_credential_error()
        assert recorded is not None
        assert (recorded["provider"], recorded["status"]) == (provider, status)

    @pytest.mark.parametrize(
        "failure", [_status_error(429), httpx.ConnectError("no route")]
    )
    async def test_throttling_and_outages_say_nothing_about_the_credential(
        self, monkeypatch: pytest.MonkeyPatch, failure: Exception
    ) -> None:
        monkeypatch.setenv("BRAVE_API_KEY", "k")
        stub_failure(monkeypatch, failure)

        assert await search_brave("anything", 5, 0) == {}
        assert web_search_credential_error() is None

    async def test_availability_follows_refusals_and_a_success_clears_them(
        self, monkeypatch: pytest.MonkeyPatch, keys: Any
    ) -> None:
        keys()
        assert await check_web_search_available() is False

        keys(brave=True)
        assert await check_web_search_available() is True
        stub_failure(monkeypatch, _status_error(402))
        await search_brave("anything", 5, 0)
        assert await check_web_search_available() is False

        stub_responses(
            monkeypatch,
            {"web": {"results": [{"title": "t", "url": "https://e.com"}]}},
        )
        assert await search_brave("anything", 5, 0) != {}
        assert web_search_credential_error() is None
        assert await check_web_search_available() is True

        keys(brave=True, tavily=True)
        _record_credential_error("brave", 402, "quota gone")
        assert await check_web_search_available() is True
        _record_credential_error("tavily", 432, "out of credits")
        assert await check_web_search_available() is False

    @pytest.mark.parametrize(
        ("brave_refuses", "expected", "calls"),
        [
            # An empty answer is an answer; only refusal justifies spending
            # another provider's quota.
            (False, {}, ["brave"]),
            (True, {"t1": {"title": "found"}}, ["brave", "tavily"]),
        ],
    )
    async def test_search_web_falls_through_only_when_a_provider_refuses(
        self,
        monkeypatch: pytest.MonkeyPatch,
        keys: Any,
        brave_refuses: bool,
        expected: dict[str, Any],
        calls: list[str],
    ) -> None:
        keys(brave=True, tavily=True)
        seen: list[str] = []

        async def brave(*_: Any) -> dict[str, Any]:
            seen.append("brave")
            if brave_refuses:
                _record_credential_error("brave", 402, "quota gone")
            return {}

        async def tavily(*_: Any) -> dict[str, Any]:
            seen.append("tavily")
            return {"t1": {"title": "found"}}

        monkeypatch.setattr(
            providers,
            "_PROVIDERS",
            {
                "brave": (brave, "BRAVE_API_KEY"),
                "tavily": (tavily, "TAVILY_API_KEY"),
            },
        )

        assert await search_web("anything") == expected
        assert seen == calls
