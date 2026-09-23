"""Campaign MCP calls must use a qualified reference server and tool."""

from typing import Any

import pytest

from co_scientist.mcp_client import MCPToolClient
from tests._mcp import make_tool_call, string_tool

URL = "http://localhost:8888/mcp"


@pytest.mark.parametrize("url", ["https://other.example/mcp", URL])
async def test_campaign_rejects_unqualified_server_before_discovery(
    monkeypatch: pytest.MonkeyPatch, _patch_mcp_seam: Any, url: str
) -> None:
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.delenv("COSCIENTIST_CAMPAIGN_MCP_URL", raising=False)
    _patch_mcp_seam.tools = [string_tool("search_pubmed", "{}")]
    with pytest.raises(RuntimeError, match="campaign"):
        await MCPToolClient(server_url=url).initialize()


@pytest.mark.parametrize("model_call", [False, True])
async def test_campaign_rejects_preexisting_unqualified_tool_binding(
    monkeypatch: pytest.MonkeyPatch, _patch_mcp_seam: Any, model_call: bool
) -> None:
    _patch_mcp_seam.tools = [string_tool("search_web", "paid result")]
    client = MCPToolClient(server_url=URL)
    await client.initialize()
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    with pytest.raises(RuntimeError, match="campaign"):
        if model_call:
            await client.execute_tool_call(make_tool_call("search_web", "{}"))
        else:
            await client.call_tool("search_web")


@pytest.fixture
def qualified(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    import httpx
    from mcp_server.campaign import campaign_policy

    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    monkeypatch.setenv("COSCIENTIST_CAMPAIGN_MCP_URL", URL)
    monkeypatch.setenv("COSCIENTIST_MCP_SHARED_SECRET", "secret")
    data = {
        "service": "coscientist-lit-review",
        "campaign_policy": campaign_policy(),
    }
    original = httpx.AsyncClient

    def reply(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://localhost:8888/"
        assert request.headers["X-CoScientist-Campaign"] == "1"
        assert request.headers["X-MCP-Shared-Secret"] == "secret"
        return httpx.Response(200, json=data)

    def client(**kwargs: Any) -> httpx.AsyncClient:
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return original(**kwargs, transport=httpx.MockTransport(reply))

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return data


@pytest.mark.parametrize("model_call", [False, True])
async def test_qualified_calls_recheck_policy_and_hide_unqualified_tools(
    qualified: dict[str, Any], _patch_mcp_seam: Any, model_call: bool
) -> None:
    _patch_mcp_seam.tools = [
        string_tool("search_pubmed", "public evidence"),
        string_tool("search_web", "paid"),
    ]
    client = MCPToolClient(server_url=URL)
    await client.initialize()
    tools, schemas = client.get_tools()
    assert set(tools) == {"search_pubmed"}
    assert [s["function"]["name"] for s in schemas] == ["search_pubmed"]

    async def invoke(name: str) -> Any:
        if model_call:
            return await client.execute_tool_call(make_tool_call(name, "{}"))
        return await client.call_tool(name)

    assert "public evidence" in str(await invoke("search_pubmed"))
    with pytest.raises(RuntimeError, match="campaign"):
        await invoke("search_web")
    qualified["campaign_policy"]["enabled"] = False
    with pytest.raises(RuntimeError, match="campaign"):
        await invoke("search_pubmed")


@pytest.mark.parametrize("include_new_tool", [False, True])
async def test_new_client_accepts_old_and_current_manifests_during_rollout(
    qualified: dict[str, Any], _patch_mcp_seam: Any, include_new_tool: bool
) -> None:
    manifest_tools = {
        tool
        for tool in qualified["campaign_policy"]["tools"]
        if tool != "get_opencitations_citation_edges"
    }
    if include_new_tool:
        manifest_tools.add("get_opencitations_citation_edges")
    qualified["campaign_policy"]["tools"] = sorted(manifest_tools)
    _patch_mcp_seam.tools = [string_tool("search_pubmed", "public evidence")]
    if include_new_tool:
        _patch_mcp_seam.tools.append(
            string_tool("get_opencitations_citation_edges", "citation edges")
        )

    client = MCPToolClient(server_url=URL)
    await client.initialize()
    tool_map, _ = client.get_tools()
    expected_tools = {"search_pubmed"}
    if include_new_tool:
        expected_tools.add("get_opencitations_citation_edges")
        assert "citation edges" in str(
            await client.call_tool("get_opencitations_citation_edges")
        )
    assert set(tool_map) == expected_tools

    if not include_new_tool:
        # The MCP deployment can advance while this client remains active.
        qualified["campaign_policy"]["tools"] = sorted(
            [
                *qualified["campaign_policy"]["tools"],
                "get_opencitations_citation_edges",
            ]
        )
        assert "public evidence" in str(await client.call_tool("search_pubmed"))

    qualified["campaign_policy"]["tools"].append("unqualified_paid_tool")
    with pytest.raises(RuntimeError, match="campaign"):
        await client.call_tool("search_pubmed")


@pytest.mark.parametrize(
    "change", ["url", "transport", "headers", "extra", "multi"]
)
async def test_custom_configuration_is_rejected_before_sdk_connection(
    qualified: dict[str, Any], _patch_mcp_seam: Any, change: str
) -> None:
    config: dict[str, Any] = {"transport": "streamable_http", "url": URL}
    changes: dict[str, dict[str, Any]] = {
        "url": {"url": "https://unqualified.example/mcp"},
        "transport": {"transport": "stdio"},
        "headers": {"headers": {"Authorization": "fake"}},
        "extra": {"httpx_client_factory": lambda: None},
        "multi": {},
    }
    config.update(changes[change])
    configs = {"one": config}
    if change == "multi":
        configs["two"] = dict(config)
    with pytest.raises(RuntimeError, match="campaign"):
        await MCPToolClient(server_configs=configs).initialize()
    assert _patch_mcp_seam.instances_created == 0


@pytest.mark.parametrize(
    "mutation", [None, {"version": "old"}, {"enabled": False}]
)
async def test_unqualified_serving_policy_prevents_tool_discovery(
    qualified: dict[str, Any], _patch_mcp_seam: Any, mutation: Any
) -> None:
    qualified["campaign_policy"] = mutation
    with pytest.raises(RuntimeError, match="campaign"):
        await MCPToolClient(server_url=URL).initialize()
    assert _patch_mcp_seam.instances_created == 0


async def test_mutated_binding_cannot_redirect_existing_tools(
    qualified: dict[str, Any], _patch_mcp_seam: Any
) -> None:
    _patch_mcp_seam.tools = [string_tool("search_pubmed", "public")]
    client = MCPToolClient(server_url=URL)
    await client.initialize()
    client._server_configs["default"]["url"] = "https://unqualified.example/mcp"
    with pytest.raises(RuntimeError, match="campaign"):
        await client.call_tool("search_pubmed")


async def test_global_client_created_outside_campaign_cannot_be_reused(
    monkeypatch: pytest.MonkeyPatch, _patch_mcp_seam: Any
) -> None:
    from co_scientist.mcp_client import get_mcp_client

    _patch_mcp_seam.tools = [string_tool("search_pubmed", "unqualified")]
    await get_mcp_client(server_url=URL)
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    with pytest.raises(RuntimeError, match="campaign"):
        await get_mcp_client()


async def test_qualified_sdk_transport_has_no_redirect_or_proxy_escape(
    qualified: dict[str, Any], _patch_mcp_seam: Any
) -> None:
    from co_scientist.mcp_campaign import campaign_http_client

    client = MCPToolClient(server_url=URL)
    await client.initialize()
    assert client._client is not None
    connection = client._client.connections["default"]
    assert connection["transport"] == "streamable_http"
    factory = connection["httpx_client_factory"]
    assert factory is campaign_http_client
    async with factory() as transport:
        assert transport.follow_redirects is False
        assert transport.trust_env is False


@pytest.mark.parametrize("surface", ["schemas", "availability"])
async def test_unqualified_cached_tools_are_not_advertised_in_campaign(
    monkeypatch: pytest.MonkeyPatch, _patch_mcp_seam: Any, surface: str
) -> None:
    _patch_mcp_seam.tools = [string_tool("search_web", "paid")]
    client = MCPToolClient(server_url=URL)
    await client.initialize()
    monkeypatch.setenv("COSCIENTIST_REQUIRE_FREE_MODELS", "1")
    with pytest.raises(RuntimeError, match="campaign"):
        if surface == "schemas":
            client.get_tools()
        else:
            client.has_tool("search_web")
