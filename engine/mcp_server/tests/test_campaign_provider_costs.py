"""Campaign mode cannot consume host accounts' search credits."""

from typing import Any

import httpx
import pytest
from mcp_server.tools.lit_review.openalex_search import search_openalex
from mcp_server.tools.web import providers
from mcp_server.tools.web.web_search import (
    check_web_search_available,
    search_web,
)


@pytest.fixture
def campaign(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    for name in ("BRAVE_API_KEY", "TAVILY_API_KEY", "OPENALEX_API_KEY"):
        monkeypatch.setenv(name, "test-paid-account")


@pytest.mark.parametrize("provider", ["brave", "tavily"])
async def test_campaign_blocks_direct_metered_search(
    campaign: None, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    sent = []

    def client(**kwargs: Any) -> Any:
        sent.append(kwargs)
        raise AssertionError("metered transport opened")

    monkeypatch.setattr(httpx, "AsyncClient", client)
    with pytest.raises(RuntimeError, match="campaign"):
        await getattr(providers, f"search_{provider}")("research", 2, 0)
    assert sent == []


async def test_campaign_exposes_no_paid_search_or_fallback(
    campaign: None,
) -> None:
    assert providers.configured_providers() == []
    assert providers.candidate_providers() == []
    assert providers.resolve_provider() is None
    assert not await check_web_search_available()
    assert await search_web("public research") == {}


async def test_campaign_openalex_does_not_attach_host_account(
    campaign: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[httpx.Request] = []
    original = httpx.AsyncClient

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"results": []})

    def client(**kwargs: Any) -> httpx.AsyncClient:
        assert kwargs["trust_env"] is False
        return original(**kwargs, transport=httpx.MockTransport(respond))

    monkeypatch.setattr(httpx, "AsyncClient", client)
    assert await search_openalex("public research") == {}
    assert len(sent) == 1
    assert "api_key" not in sent[0].url.params
    assert "authorization" not in sent[0].headers


@pytest.mark.parametrize("setting", ["1", "true", " TRUE ", "invalid"])
@pytest.mark.parametrize("provider", ["brave", "tavily"])
async def test_enabled_or_invalid_mode_never_opens_web_transport(
    monkeypatch: pytest.MonkeyPatch, setting: str, provider: str
) -> None:
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", setting)

    def refuse(**kwargs: Any) -> Any:
        raise AssertionError("transport opened")

    monkeypatch.setattr(httpx, "AsyncClient", refuse)
    with pytest.raises(RuntimeError, match="campaign"):
        await getattr(providers, f"search_{provider}")("public", 1, 0)


@pytest.mark.parametrize("setting", ["0", "false", ""])
async def test_normal_openalex_preserves_explicit_host_key(
    monkeypatch: pytest.MonkeyPatch, setting: str
) -> None:
    from mcp_server.tests._httpx import stub_responses

    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", setting)
    monkeypatch.setenv("OPENALEX_API_KEY", "test-user-key")
    client = stub_responses(monkeypatch, {"results": []})
    await search_openalex("public")
    assert client.calls[0][1]["api_key"] == "test-user-key"


async def test_openalex_quota_refusal_does_not_retry_with_host_key(
    campaign: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mcp_server.tests._httpx import stub_failure
    from mcp_server.tools.lit_review.openalex_search import (
        OpenAlexUnavailableError,
    )

    response = httpx.Response(
        429, request=httpx.Request("GET", "https://api.openalex.org/works")
    )
    client = stub_failure(
        monkeypatch,
        httpx.HTTPStatusError(
            "quota", request=response.request, response=response
        ),
    )
    with pytest.raises(OpenAlexUnavailableError):
        await search_openalex("public")
    assert len(client.calls) == 1
    assert "api_key" not in client.calls[0][1]


def test_campaign_server_boot_omits_metered_web_tools() -> None:
    import os
    import subprocess
    import sys

    script = """
from mcp_server.server import _MCP_TOOLS
names = {name for _, name in _MCP_TOOLS}
assert 'search_web' not in names
assert 'check_web_search_available' not in names
assert 'search_pubmed' in names
from mcp_server.campaign import PUBLIC_TOOLS, campaign_policy
assert names == PUBLIC_TOOLS
assert campaign_policy()['enabled'] is True
from mcp_server.server import root
import asyncio, json
body = json.loads(asyncio.run(root()).body)
assert body['campaign_policy'] == campaign_policy()
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={
            "PATH": os.defpath,
            "PYTHON_DOTENV_DISABLED": "1",
            "COSCIENTIST_REQUIRE_FREE_MODELS": "1",
            "BRAVE_API_KEY": "fake",
            "TAVILY_API_KEY": "fake",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


async def test_invalid_mode_blocks_openalex_and_provider_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "yes")

    def refuse(**kwargs: Any) -> Any:
        raise AssertionError("transport opened")

    monkeypatch.setattr(httpx, "AsyncClient", refuse)
    with pytest.raises(RuntimeError, match="invalid"):
        await search_openalex("public")
    with pytest.raises(RuntimeError, match="invalid"):
        await check_web_search_available()
    with pytest.raises(RuntimeError, match="invalid"):
        await search_web("public")
