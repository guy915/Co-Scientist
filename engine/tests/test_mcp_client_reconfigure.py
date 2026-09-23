"""The shared MCP client must not outlive the configuration it was built for.

``get_mcp_client`` keeps one client per process so the nodes of a run share a
single MCP session instead of each opening its own. The cache was keyed on
nothing at all, though, so the *first* caller's servers were handed to every
later caller: a second run pointed at a different MCP deployment silently
talked to the first one's, and the divergence is invisible from the outside
because the client answers normally -- from the wrong servers.

Reuse still has to be the common case: in a deployment where every run
resolves the same servers, nothing here should build a second transport.
"""

import asyncio
from typing import Any

import httpx
import pytest

from co_scientist.llm_free_policy import scoped_campaign_mode
from co_scientist.mcp_campaign import POLICY, PUBLIC_TOOLS
from co_scientist.mcp_client import MCPToolClient, get_mcp_client
from tests._mcp import FakeMultiServerMCPClient, make_registry, string_tool


async def test_a_different_server_url_builds_a_new_client(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A caller asking for other servers must not get the cached ones."""
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]
    first = await get_mcp_client(server_url="http://a.test/mcp")
    second = await get_mcp_client(server_url="http://b.test/mcp")

    assert first is not second
    assert second.server_url == "http://b.test/mcp"


async def test_switching_to_a_registry_builds_a_new_client(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A registry resolving different servers is a configuration change."""
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]
    first = await get_mcp_client(server_url="http://a.test/mcp")
    second = await get_mcp_client(tool_registry=make_registry())

    assert first is not second
    assert second.server_url == "http://registry.test/mcp"


async def test_matching_configuration_still_reuses_one_session(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """Sharing one session across a run's nodes is the point of the cache."""
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]
    first = await get_mcp_client(tool_registry=make_registry())
    second = await get_mcp_client(tool_registry=make_registry())

    assert first is second
    assert _patch_mcp_seam.instances_created == 1


async def test_same_configuration_keeps_standard_and_campaign_clients(
    monkeypatch: pytest.MonkeyPatch,
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """Policy-specific cached tools cannot cross concurrent run scopes."""
    monkeypatch.setenv("COSCIENTIST_CAMPAIGN_MCP_URL", "http://a.test/mcp")
    monkeypatch.setenv("COSCIENTIST_MCP_SHARED_SECRET", "secret")
    _patch_mcp_seam.tools = [string_tool("search_pubmed", "ok")]

    original = httpx.AsyncClient

    def reply(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-CoScientist-Campaign"] == "1"
        assert request.headers["X-MCP-Shared-Secret"] == "secret"
        return httpx.Response(
            200,
            json={
                "service": "coscientist-lit-review",
                "campaign_policy": {
                    "version": POLICY,
                    "enabled": True,
                    "anonymous_openalex": True,
                    "tools": sorted(PUBLIC_TOOLS),
                },
            },
        )

    def client(**kwargs: Any) -> httpx.AsyncClient:
        return original(**kwargs, transport=httpx.MockTransport(reply))

    monkeypatch.setattr(httpx, "AsyncClient", client)

    standard = await get_mcp_client(server_url="http://a.test/mcp")
    with scoped_campaign_mode(True):
        campaign = await get_mcp_client(server_url="http://a.test/mcp")
    standard_again = await get_mcp_client(server_url="http://a.test/mcp")

    assert campaign is not standard
    assert standard_again is standard
    assert _patch_mcp_seam.instances_created == 2


def test_same_configuration_never_reuses_client_across_event_loops(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """Durable worker loops must not share SDK sessions or asyncio locks."""
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]

    async def get_client() -> MCPToolClient:
        return await get_mcp_client(server_url="http://a.test/mcp")

    first = asyncio.run(get_client())
    second = asyncio.run(get_client())

    assert first is not second
    assert _patch_mcp_seam.instances_created == 2
