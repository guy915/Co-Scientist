from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

import co_scientist.mcp_client as mcp_client_module
from co_scientist.exceptions import MCPToolTimeoutError
from co_scientist.llm import scoped_campaign_mode
from co_scientist.mcp_client import (
    MCP_AUTH_HEADER,
    MCP_SHARED_SECRET_ENV,
    POLICY,
    PUBLIC_TOOLS,
    MCPToolClient,
    get_mcp_client,
)
from tests._mcp import (
    FakeMultiServerMCPClient,
    make_tool_call,
    string_tool,
)


async def test_same_configuration_keeps_standard_and_campaign_clients(
    monkeypatch: pytest.MonkeyPatch,
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
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


# MCP calls need their own timeout; the LLM timeout cannot cover a hung SSE tool
# call.


class _HungTool:
    def __init__(self) -> None:
        self.cancelled = asyncio.Event()

    async def ainvoke(self, _args: Any) -> str:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return "never"


async def test_a_hung_tool_is_cancelled_and_reported_to_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Raising under gather would cancel sibling tools; return this tool's
    timeout to the model."""
    monkeypatch.setenv(mcp_client_module.MCP_TOOL_TIMEOUT_ENV, "0.05")
    hung = _HungTool()
    client = MCPToolClient()
    client._tools_dict = {"search_pubmed": hung}

    with pytest.raises(MCPToolTimeoutError, match="search_pubmed"):
        await client.call_tool("search_pubmed", query="anything")
    await asyncio.wait_for(hung.cancelled.wait(), timeout=1.0)

    message = await client.execute_tool_call(
        make_tool_call("search_pubmed", json.dumps({"query": "anything"}))
    )
    assert message["role"] == "tool"
    assert message["name"] == "search_pubmed"
    assert "did not respond" in message["content"]


@pytest.mark.parametrize(
    ("secret", "explicit", "expected"),
    [
        (None, None, None),
        ("", None, None),
        ("topsecret", None, {MCP_AUTH_HEADER: "topsecret"}),
        (
            "topsecret",
            {"X-Other": "kept"},
            {"X-Other": "kept", MCP_AUTH_HEADER: "topsecret"},
        ),
    ],
    ids=["unset", "empty-is-unset", "attached", "merged-with-existing"],
)
async def test_the_shared_secret_reaches_the_connection_as_a_header(
    monkeypatch: pytest.MonkeyPatch,
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
    secret: str | None,
    explicit: dict[str, str] | None,
    expected: dict[str, str] | None,
) -> None:
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]
    if secret is None:
        monkeypatch.delenv(MCP_SHARED_SECRET_ENV, raising=False)
    else:
        monkeypatch.setenv(MCP_SHARED_SECRET_ENV, secret)
    config: dict[str, Any] = {
        "transport": "streamable_http",
        "url": "http://s1.test/mcp",
    }
    if explicit is not None:
        config["headers"] = explicit
    client = MCPToolClient(server_configs={"s1": config})

    await client.initialize()

    assert client._client is not None
    assert client._client.connections["s1"].get("headers") == expected
    assert config.get("headers") == explicit
