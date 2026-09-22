"""Request campaign policy reaches real FastMCP SDK tool execution."""

import asyncio
from typing import Any

import httpx
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from mcp_server.auth_middleware import (
    MCP_AUTH_HEADER,
    MCP_CAMPAIGN_HEADER,
    SharedSecretAuthMiddleware,
)
from mcp_server.campaign import campaign_free_mode
from mcp_server.tool_logging import with_call_logging
from starlette.applications import Starlette


def _client_factory(app: Any):  # type: ignore[no-untyped-def]
    def factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("follow_redirects", None)
        return httpx.AsyncClient(
            **kwargs,
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )

    return factory


async def test_concurrent_fastmcp_sessions_receive_request_policy() -> None:
    """The SDK's tool task inherits only its own authenticated request."""
    both_entered = asyncio.Event()
    entered = 0
    lock = asyncio.Lock()

    async def inspect_policy(label: str) -> dict[str, object]:
        nonlocal entered
        async with lock:
            entered += 1
            if entered == 2:
                both_entered.set()
        await asyncio.wait_for(both_entered.wait(), timeout=2)
        return {"label": label, "campaign": campaign_free_mode()}

    mcp = FastMCP("campaign-context-test")
    mcp.tool(
        with_call_logging(inspect_policy, "search_pubmed"),
        name="search_pubmed",
    )
    mcp_app = mcp.http_app()
    app = Starlette(lifespan=mcp_app.lifespan)
    app.mount("/", mcp_app)
    app.add_middleware(SharedSecretAuthMiddleware, secret="secret")
    factory = _client_factory(app)

    async def invoke(label: str, campaign: bool) -> Any:
        headers = {MCP_AUTH_HEADER: "secret"}
        if campaign:
            headers[MCP_CAMPAIGN_HEADER] = "1"
        transport = StreamableHttpTransport(
            "http://test/mcp",
            headers=headers,
            httpx_client_factory=factory,
        )
        async with Client(transport) as client:
            return await client.call_tool("search_pubmed", {"label": label})

    async with app.router.lifespan_context(app):
        campaign, ordinary = await asyncio.gather(
            invoke("campaign", True), invoke("ordinary", False)
        )
        ordinary_after = await invoke("ordinary-after", False)

    assert campaign.data == {"label": "campaign", "campaign": True}
    assert ordinary.data == {"label": "ordinary", "campaign": False}
    assert ordinary_after.data == {
        "label": "ordinary-after",
        "campaign": False,
    }
    assert campaign_free_mode() is False
