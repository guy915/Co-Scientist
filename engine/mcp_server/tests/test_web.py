import socket
from typing import Any

import httpx
import pytest
from mcp_server.tests._httpx import stub_failure, stub_responses
from mcp_server.tools import web_providers as providers
from mcp_server.tools.web_fetch import (
    UrlNotFetchableError,
    check_fetchable,
    extract_text_from_html,
    read_url,
)
from mcp_server.tools.web_providers import (
    _brave_freshness,
    _clear_credential_error,
    _record_credential_error,
    clean_snippet,
    normalize_brave,
    normalize_tavily,
    resolve_provider,
    search_brave,
    search_tavily,
    web_search_credential_error,
)


def _fake_getaddrinfo(mapping: dict[str, str]) -> Any:

    def _resolve(host: str, *args: Any, **kwargs: Any) -> list[Any]:
        if host not in mapping:
            raise socket.gaierror(f"unknown host {host}")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (mapping[host], 0))]

    return _resolve


@pytest.fixture
def resolve_to(monkeypatch: pytest.MonkeyPatch) -> Any:

    def _apply(mapping: dict[str, str]) -> None:
        monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo(mapping))

    return _apply


def test_allows_public_https_url(resolve_to: Any) -> None:
    resolve_to({"example.com": "93.184.216.34"})
    check_fetchable("https://example.com/article")


def test_rejects_non_http_scheme(resolve_to: Any) -> None:
    resolve_to({})
    with pytest.raises(UrlNotFetchableError, match="scheme"):
        check_fetchable("file:///etc/passwd")


def test_rejects_url_without_host(resolve_to: Any) -> None:
    resolve_to({})
    with pytest.raises(UrlNotFetchableError, match="no host"):
        check_fetchable("http:///nowhere")


def test_rejects_loopback(resolve_to: Any) -> None:
    resolve_to({"localhost": "127.0.0.1"})
    with pytest.raises(UrlNotFetchableError, match="non-public"):
        check_fetchable("http://localhost:8008/api/runs")


def test_rejects_private_range(resolve_to: Any) -> None:
    resolve_to({"mcp.railway.internal": "10.0.1.5"})
    with pytest.raises(UrlNotFetchableError, match="non-public"):
        check_fetchable("http://mcp.railway.internal:8888/mcp")


def test_rejects_public_hostname_resolving_to_loopback(resolve_to: Any) -> None:
    """Hostname text alone cannot detect public names resolving to private
    addresses."""
    resolve_to({"127.0.0.1.nip.io": "127.0.0.1"})
    with pytest.raises(UrlNotFetchableError, match="non-public"):
        check_fetchable("http://127.0.0.1.nip.io/admin")


def test_rejects_decimal_encoded_loopback(resolve_to: Any) -> None:
    resolve_to({"2130706433": "127.0.0.1"})
    with pytest.raises(UrlNotFetchableError, match="non-public"):
        check_fetchable("http://2130706433/")


def test_rejects_cloud_metadata_host(resolve_to: Any) -> None:
    resolve_to({})
    with pytest.raises(UrlNotFetchableError, match="not allowed"):
        check_fetchable("http://169.254.169.254/latest/meta-data/")


def test_rejects_link_local(resolve_to: Any) -> None:
    resolve_to({"metadata.example": "169.254.169.254"})
    with pytest.raises(UrlNotFetchableError, match="non-public"):
        check_fetchable("http://metadata.example/")


def test_rejects_unresolvable_host(resolve_to: Any) -> None:
    resolve_to({})
    with pytest.raises(UrlNotFetchableError, match="does not resolve"):
        check_fetchable("https://no-such-host.invalid/")


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


def test_extract_keeps_headings_and_body() -> None:
    text = extract_text_from_html(_PAGE)
    assert "# Trial readout" in text
    assert "# Phase 2 results" in text
    assert "## Methods" in text
    assert "The primary endpoint was met." in text
    assert "- Randomized" in text


def test_extract_drops_page_furniture() -> None:
    text = extract_text_from_html(_PAGE)
    for noise in ("analytics()", "color:red", "About", "Copyright 2026"):
        assert noise not in text


def test_extract_falls_back_for_div_only_markup() -> None:
    html = "<html><body><div>Bare content here</div></body></html>"
    assert "Bare content here" in extract_text_from_html(html)


def test_extract_truncates() -> None:
    html = f"<html><body><p>{'x' * 5000}</p></body></html>"
    text = extract_text_from_html(html, max_chars=100)
    assert "truncated" in text
    assert len(text) < 400


async def test_read_url_blocks_internal_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = await read_url("http://localhost:8008/api/runs")
    assert result.startswith("[blocked:")


async def test_read_url_rejects_non_http_scheme() -> None:
    assert (await read_url("file:///etc/passwd")).startswith("[blocked:")


async def test_read_url_extracts_html(monkeypatch: pytest.MonkeyPatch) -> None:
    response = httpx.Response(
        200,
        content=_PAGE.encode(),
        headers={"content-type": "text/html; charset=utf-8"},
        request=httpx.Request("GET", "https://example.com/a"),
    )
    monkeypatch.setattr(
        "mcp_server.tools.web_fetch.check_fetchable", lambda url: None
    )
    stub_responses(monkeypatch, response)
    text = await read_url("https://example.com/a")
    assert "# Phase 2 results" in text


async def test_read_url_reports_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = httpx.Response(
        404,
        content=b"nope",
        request=httpx.Request("GET", "https://example.com/missing"),
    )
    monkeypatch.setattr(
        "mcp_server.tools.web_fetch.check_fetchable", lambda url: None
    )
    stub_responses(monkeypatch, response)
    result = await read_url("https://example.com/missing")
    assert result.startswith("[error: HTTP 404")


async def test_read_url_notes_unsupported_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = httpx.Response(
        200,
        content=b"\x00\x01",
        headers={"content-type": "image/png"},
        request=httpx.Request("GET", "https://example.com/i.png"),
    )
    monkeypatch.setattr(
        "mcp_server.tools.web_fetch.check_fetchable", lambda url: None
    )
    stub_responses(monkeypatch, response)
    result = await read_url("https://example.com/i.png")
    assert result.startswith("[note: unsupported content type image/png")


_WEB_SEARCH_BRAVE_PAYLOAD: dict[str, Any] = {
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
    out = normalize_brave(_WEB_SEARCH_BRAVE_PAYLOAD, max_results=10)
    assert len(out) == 2
    first = out[next(iter(out))]
    assert first["title"] == "GLP-1 trial results"
    assert first["url"] == "https://example.com/a"
    assert first["abstract"] == "A phase 2 readout."
    assert first["source"] == "web"
    assert first["site"] == "Example News"


def test_normalize_brave_respects_max_results() -> None:
    assert len(normalize_brave(_WEB_SEARCH_BRAVE_PAYLOAD, max_results=1)) == 1


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("<strong>GLP-1</strong> agonists", "GLP-1 agonists"),
        ("Trials &amp; results", "Trials & results"),
        ("line one\n\n  line two", "line one line two"),
        ("<p>nested <em>tags</em> here</p>", "nested tags here"),
        # Strip markup before unescaping so encoded tags remain inert text.
        ("&lt;script&gt;alert(1)&lt;/script&gt;", "<script>alert(1)</script>"),
        (None, ""),
        ("", ""),
        (123, ""),
    ],
)
def test_clean_snippet(raw: Any, expected: str) -> None:
    assert clean_snippet(raw) == expected


def test_normalize_brave_strips_markup_from_snippets() -> None:
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
    """Lineage and dedup depend on stable URL-based source ids across runs."""
    first = normalize_brave(_WEB_SEARCH_BRAVE_PAYLOAD, max_results=10)
    second = normalize_brave(_WEB_SEARCH_BRAVE_PAYLOAD, max_results=10)
    assert list(first.keys()) == list(second.keys())
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
    from mcp_server.tools.web_providers import search_web

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
    import mcp_server.tools.web_providers as web_search_module

    captured: dict[str, int] = {}

    async def _fake_search(
        query: str, max_results: int, recency_days: int
    ) -> dict[str, Any]:
        captured["max_results"] = max_results
        captured["recency_days"] = recency_days
        return {}

    monkeypatch.setattr(
        web_search_module,
        "candidate_providers",
        lambda: [("brave", _fake_search)],
    )
    await web_search_module.search_web("q", max_results=requested)
    assert captured["max_results"] == expected


async def test_search_web_floors_negative_recency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_server.tools.web_providers as web_search_module

    captured: dict[str, int] = {}

    async def _fake_search(
        query: str, max_results: int, recency_days: int
    ) -> dict[str, Any]:
        captured["recency_days"] = recency_days
        return {}

    monkeypatch.setattr(
        web_search_module,
        "candidate_providers",
        lambda: [("brave", _fake_search)],
    )
    await web_search_module.search_web("q", recency_days=-10)
    assert captured["recency_days"] == 0


_WEB_SEARCH_CREDENTIALS_BRAVE_PAYLOAD: dict[str, Any] = {
    "web": {
        "results": [
            {
                "title": "GLP-1 trial results",
                "url": "https://example.com/a",
                "description": "A phase 2 readout.",
            }
        ]
    }
}


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.invalid/search")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(
        f"{status}", request=request, response=response
    )


@pytest.fixture
def _clear_credential_state() -> Any:
    """Provider refusal records are process-wide."""
    _clear_credential_error()
    yield
    _clear_credential_error()


@pytest.mark.usefixtures("_clear_credential_state")
class TestWebSearchCredentials:
    @pytest.mark.parametrize("status", [401, 402, 403])
    async def test_rejected_key_is_recorded_not_swallowed(
        self, monkeypatch: pytest.MonkeyPatch, status: int
    ) -> None:
        monkeypatch.setenv("BRAVE_API_KEY", "k")
        stub_failure(monkeypatch, _status_error(status))

        assert await search_brave("anything", 5, 0) == {}

        recorded = web_search_credential_error()
        assert recorded is not None
        assert recorded["provider"] == "brave"
        assert recorded["status"] == status

    async def test_rate_limit_is_not_a_credential_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Throttling self-heals and says nothing about whether a credential
        is valid."""
        monkeypatch.setenv("BRAVE_API_KEY", "k")
        stub_failure(monkeypatch, _status_error(429))

        assert await search_brave("anything", 5, 0) == {}
        assert web_search_credential_error() is None

    async def test_transport_failure_is_not_a_credential_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("BRAVE_API_KEY", "k")
        stub_failure(monkeypatch, httpx.ConnectError("no route"))

        assert await search_brave("anything", 5, 0) == {}
        assert web_search_credential_error() is None

    async def test_tavily_rejection_is_recorded_under_its_own_name(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("TAVILY_API_KEY", "k")
        stub_failure(monkeypatch, _status_error(401))

        assert await search_tavily("anything", 5, 0) == {}

        recorded = web_search_credential_error()
        assert recorded is not None and recorded["provider"] == "tavily"

    async def test_a_successful_search_clears_the_record(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("BRAVE_API_KEY", "k")
        stub_failure(monkeypatch, _status_error(402))
        await search_brave("anything", 5, 0)
        assert web_search_credential_error() is not None

        stub_responses(monkeypatch, _WEB_SEARCH_CREDENTIALS_BRAVE_PAYLOAD)
        assert await search_brave("anything", 5, 0) != {}
        assert web_search_credential_error() is None

    async def test_availability_check_follows_the_record(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from mcp_server.tools.web_providers import check_web_search_available

        monkeypatch.setenv("BRAVE_API_KEY", "k")
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
        assert await check_web_search_available() is True

        stub_failure(monkeypatch, _status_error(402))
        await search_brave("anything", 5, 0)
        assert await check_web_search_available() is False

    async def test_availability_check_is_false_without_a_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from mcp_server.tools.web_providers import check_web_search_available

        monkeypatch.delenv("BRAVE_API_KEY", raising=False)
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
        assert await check_web_search_available() is False

    @pytest.mark.parametrize("status", [432, 433])
    async def test_exhausted_credits_count_as_a_rejection(
        self, monkeypatch: pytest.MonkeyPatch, status: int
    ) -> None:
        monkeypatch.setenv("TAVILY_API_KEY", "k")
        stub_failure(monkeypatch, _status_error(status))

        assert await search_tavily("anything", 5, 0) == {}

        recorded = web_search_credential_error()
        assert recorded is not None and recorded["status"] == status

    def test_resolve_provider_skips_a_refused_one(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
        monkeypatch.setenv("BRAVE_API_KEY", "k")
        monkeypatch.setenv("TAVILY_API_KEY", "k")
        assert (resolved := resolve_provider()) is not None
        assert resolved[0] == "brave"

        _record_credential_error("brave", 402, "quota gone")

        assert (resolved := resolve_provider()) is not None
        assert resolved[0] == "tavily"

    def test_an_explicit_provider_is_skipped_once_refused(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("WEB_SEARCH_PROVIDER", "tavily")
        monkeypatch.setenv("BRAVE_API_KEY", "k")
        monkeypatch.setenv("TAVILY_API_KEY", "k")
        _record_credential_error("tavily", 432, "out of credits")

        assert (resolved := resolve_provider()) is not None
        assert resolved[0] == "brave"

    def test_the_preferred_provider_is_retried_when_all_are_refused(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Only success clears refusal records; trying a provider keeps
        monthly resets discoverable."""
        monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
        monkeypatch.setenv("BRAVE_API_KEY", "k")
        monkeypatch.setenv("TAVILY_API_KEY", "k")
        _record_credential_error("brave", 402, "quota gone")
        _record_credential_error("tavily", 432, "out of credits")

        assert (resolved := resolve_provider()) is not None
        assert resolved[0] == "brave"

    async def test_search_web_falls_through_to_the_second_provider(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from mcp_server.tools.web_providers import search_web

        monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
        monkeypatch.setenv("BRAVE_API_KEY", "k")
        monkeypatch.setenv("TAVILY_API_KEY", "k")

        calls: list[str] = []

        async def _brave(*_: Any) -> dict[str, Any]:
            calls.append("brave")
            _record_credential_error("brave", 402, "quota gone")
            return {}

        async def _tavily(*_: Any) -> dict[str, Any]:
            calls.append("tavily")
            return {"t1": {"title": "found"}}

        monkeypatch.setattr(providers, "search_brave", _brave)
        monkeypatch.setattr(providers, "search_tavily", _tavily)
        monkeypatch.setattr(
            providers,
            "_PROVIDERS",
            {
                "brave": (_brave, "BRAVE_API_KEY"),
                "tavily": (_tavily, "TAVILY_API_KEY"),
            },
        )

        assert await search_web("anything") == {"t1": {"title": "found"}}
        assert calls == ["brave", "tavily"]

    async def test_an_empty_result_does_not_spend_the_other_quota(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Finding nothing is an answer; only refusal justifies spending
        another provider's quota."""
        from mcp_server.tools.web_providers import search_web

        monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
        monkeypatch.setenv("BRAVE_API_KEY", "k")
        monkeypatch.setenv("TAVILY_API_KEY", "k")

        calls: list[str] = []

        async def _brave(*_: Any) -> dict[str, Any]:
            calls.append("brave")
            return {}

        async def _tavily(*_: Any) -> dict[str, Any]:
            calls.append("tavily")
            return {"t1": {"title": "found"}}

        monkeypatch.setattr(
            providers,
            "_PROVIDERS",
            {
                "brave": (_brave, "BRAVE_API_KEY"),
                "tavily": (_tavily, "TAVILY_API_KEY"),
            },
        )

        assert await search_web("anything") == {}
        assert calls == ["brave"]

    async def test_availability_is_true_while_any_provider_is_healthy(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from mcp_server.tools.web_providers import check_web_search_available

        monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
        monkeypatch.setenv("BRAVE_API_KEY", "k")
        monkeypatch.setenv("TAVILY_API_KEY", "k")
        _record_credential_error("brave", 402, "quota gone")

        assert await check_web_search_available() is True

        _record_credential_error("tavily", 432, "out of credits")
        assert await check_web_search_available() is False
