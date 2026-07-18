"""Tests for page extraction and the read_url failure contract."""

from typing import Any

import httpx
import pytest
from mcp_server.tools.web.extract import extract_text_from_html
from mcp_server.tools.web.fetch import read_url

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
    """Chrome is the bulk of a typical page's tokens; it must not survive."""
    text = extract_text_from_html(_PAGE)
    for noise in ("analytics()", "color:red", "About", "Copyright 2026"):
        assert noise not in text


def test_extract_falls_back_for_div_only_markup() -> None:
    """Falls back to a flat text dump for div-only markup.

    Such pages expose no allowlisted blocks, but a flat dump still beats
    returning nothing.
    """
    html = "<html><body><div>Bare content here</div></body></html>"
    assert "Bare content here" in extract_text_from_html(html)


def test_extract_truncates() -> None:
    html = f"<html><body><p>{'x' * 5000}</p></body></html>"
    text = extract_text_from_html(html, max_chars=100)
    assert "truncated" in text
    assert len(text) < 400


def _client_returning(response: httpx.Response) -> Any:
    """Builds an httpx client stub that always returns one response."""

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, url: str, **kwargs: Any) -> httpx.Response:
            return response

    return _Client


async def test_read_url_blocks_internal_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blocks an internal address before any request is made.

    The reason reaches the agent so it learns not to retry.
    """
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
        "mcp_server.tools.web.fetch.check_fetchable", lambda url: None
    )
    monkeypatch.setattr(httpx, "AsyncClient", _client_returning(response))
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
        "mcp_server.tools.web.fetch.check_fetchable", lambda url: None
    )
    monkeypatch.setattr(httpx, "AsyncClient", _client_returning(response))
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
        "mcp_server.tools.web.fetch.check_fetchable", lambda url: None
    )
    monkeypatch.setattr(httpx, "AsyncClient", _client_returning(response))
    result = await read_url("https://example.com/i.png")
    assert result.startswith("[note: unsupported content type image/png")
