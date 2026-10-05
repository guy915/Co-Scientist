from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

import co_scientist.mcp_client as mcp_client_module
import co_scientist.mcp_client as mcp_client_session_module
from co_scientist.exceptions import MCPToolTimeoutError
from co_scientist.llm import scoped_campaign_mode
from co_scientist.mcp_client import (
    MCP_AUTH_HEADER,
    MCP_SHARED_SECRET_ENV,
    POLICY,
    PUBLIC_TOOLS,
    MCPToolClient,
    check_literature_source_available,
    check_mcp_available,
    check_web_search_available,
    get_mcp_client,
    reset_mcp_client,
)
from tests._mcp import (
    FakeMultiServerMCPClient,
    make_registry,
    make_tool_call,
    string_tool,
)

URL = "http://x.test/mcp"


@pytest.mark.parametrize(
    ("check", "tools", "error", "expected"),
    [
        (check_mcp_available, [("t1", "ok")], None, True),
        (check_mcp_available, [], None, False),
        (check_mcp_available, [], ConnectionError("boom"), False),
        (
            check_literature_source_available,
            [("check_pubmed_available", "true"), ("pubmed_search", "{}")],
            None,
            True,
        ),
        (
            check_literature_source_available,
            [("check_pubmed_available", True)],
            None,
            True,
        ),
        (
            check_literature_source_available,
            [("check_pubmed_available", "false")],
            None,
            False,
        ),
        (
            check_literature_source_available,
            [("some_other_tool", "{}")],
            None,
            False,
        ),
        # Tool presence proves key configuration, not provider acceptance or
        # available quota.
        (
            check_web_search_available,
            [("check_web_search_available", "false"), ("search_web", "{}")],
            None,
            False,
        ),
        (
            check_web_search_available,
            [("check_web_search_available", "true"), ("search_web", "{}")],
            None,
            True,
        ),
        (check_web_search_available, [("search_web", "{}")], None, True),
        (check_web_search_available, [("search_pubmed", "{}")], None, False),
    ],
    ids=[
        "mcp-tools-present",
        "mcp-no-tools",
        "mcp-connection-error",
        "literature-true-string",
        "literature-true-bool",
        "literature-false-string",
        "literature-check-tool-absent",
        "web-dead-key",
        "web-usable-key",
        "web-older-server-falls-back-to-tool-presence",
        "web-tool-absent",
    ],
)
async def test_availability_checks_report_what_the_server_offers(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
    check: Any,
    tools: list[tuple[str, Any]],
    error: Exception | None,
    expected: bool,
) -> None:
    _patch_mcp_seam.tools = [string_tool(name, value) for name, value in tools]
    _patch_mcp_seam.error = error

    assert await check(server_url=URL) is expected


@pytest.mark.parametrize(
    ("registry", "tools", "error", "expected"),
    [
        (
            {
                "availability_check": "check_avail",
                "check_mcp_tool_name": "check_pubmed_available",
            },
            [("check_pubmed_available", "true"), ("pubmed_search", "{}")],
            None,
            True,
        ),
        (
            {
                "availability_check": "check_avail",
                "check_mcp_tool_name": "check_pubmed_available",
            },
            [("pubmed_search", "{}")],
            None,
            False,
        ),
        ({"availability_check": None}, [("pubmed_search", "{}")], None, True),
        ({"availability_check": None}, [], ConnectionError("down"), False),
    ],
    ids=["explicit-check-true", "check-tool-missing", "null-check", "mcp-down"],
)
async def test_the_registry_decides_how_literature_availability_is_checked(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
    registry: dict[str, Any],
    tools: list[tuple[str, Any]],
    error: Exception | None,
    expected: bool,
) -> None:
    _patch_mcp_seam.tools = [string_tool(name, value) for name, value in tools]
    _patch_mcp_seam.error = error

    assert (
        await check_literature_source_available(
            tool_registry=make_registry(**registry)
        )
        is expected
    )
    assert await check_mcp_available(
        tool_registry=make_registry(**registry)
    ) is bool(tools)


async def test_the_session_is_reused_until_reset_or_forced_new(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]

    first = await get_mcp_client(server_url=URL)
    reused = await get_mcp_client(server_url=URL)
    forced = await get_mcp_client(server_url=URL, force_new=True)
    reset_mcp_client()
    after_reset = await get_mcp_client(server_url=URL)

    assert reused is first
    assert first.has_tool("t1")
    assert forced is not first
    assert after_reset is not forced
    assert _patch_mcp_seam.instances_created == 3


async def test_a_different_configuration_builds_a_new_session(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]

    first = await get_mcp_client(server_url="http://a.test/mcp")
    other_url = await get_mcp_client(server_url="http://b.test/mcp")
    registry = await get_mcp_client(tool_registry=make_registry())
    same_registry = await get_mcp_client(tool_registry=make_registry())

    assert other_url is not first
    assert other_url.server_url == "http://b.test/mcp"
    assert registry is not other_url
    assert registry.server_url == "http://registry.test/mcp"
    assert same_registry is registry
    assert _patch_mcp_seam.instances_created == 3


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


def test_same_configuration_never_reuses_client_across_event_loops(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]

    async def get_client() -> MCPToolClient:
        return await get_mcp_client(server_url="http://a.test/mcp")

    first = asyncio.run(get_client())
    second = asyncio.run(get_client())

    assert first is not second
    assert _patch_mcp_seam.instances_created == 2


@pytest.mark.parametrize(
    ("env", "kwargs", "expected"),
    [
        (None, {}, "http://localhost:8888/mcp"),
        ("http://example.test:9999/mcp", {}, "http://example.test:9999/mcp"),
        (
            "http://ignored.test/mcp",
            {"server_url": "http://explicit.test/mcp"},
            "http://explicit.test/mcp",
        ),
        (
            None,
            {
                "server_configs": {
                    "s1": {
                        "transport": "streamable_http",
                        "url": "http://s1.test/mcp",
                    }
                }
            },
            "http://s1.test/mcp",
        ),
        (None, {"tool_registry": make_registry()}, "http://registry.test/mcp"),
    ],
    ids=["default", "env", "explicit-url", "server-configs", "registry"],
)
def test_the_server_url_comes_from_the_most_specific_configuration(
    monkeypatch: pytest.MonkeyPatch,
    env: str | None,
    kwargs: dict[str, Any],
    expected: str,
) -> None:
    if env is None:
        monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    else:
        monkeypatch.setenv("MCP_SERVER_URL", env)

    assert MCPToolClient(**kwargs).server_url == expected


async def test_initialize_indexes_tools_once_and_serves_filtered_schemas(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    _patch_mcp_seam.tools = [
        string_tool("pubmed_search", "{}"),
        string_tool("check_pubmed_available", "true"),
    ]
    client = MCPToolClient(server_url=URL)
    assert client.has_tool("pubmed_search") is False

    await client.initialize()
    await client.initialize()

    assert _patch_mcp_seam.instances_created == 1
    assert client.has_tool("pubmed_search") is True
    tools_dict, openai_tools = client.get_tools()
    assert set(tools_dict) == {"pubmed_search", "check_pubmed_available"}
    assert {t["function"]["name"] for t in openai_tools} == set(tools_dict)
    filtered, filtered_schemas = client.get_tools(whitelist=["pubmed_search"])
    assert set(filtered) == {"pubmed_search"}
    assert [t["function"]["name"] for t in filtered_schemas] == [
        "pubmed_search"
    ]


async def test_concurrent_initialize_waits_for_complete_tool_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0
    tools: list[Any] = [string_tool("t1", "ok")]

    class SlowMultiServerMCPClient:
        def __init__(self, _connections: object) -> None:
            pass

        async def get_tools(self) -> list[object]:
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return tools

    monkeypatch.setattr(
        mcp_client_session_module,
        "MultiServerMCPClient",
        SlowMultiServerMCPClient,
    )
    client = MCPToolClient(server_url=URL)
    first = asyncio.create_task(client.initialize())
    await started.wait()
    second = asyncio.create_task(client.initialize())
    await asyncio.sleep(0)

    assert not second.done()
    release.set()
    await asyncio.gather(first, second)
    assert calls == 1
    assert client.has_tool("t1")


async def test_nothing_is_served_before_initialize() -> None:
    client = MCPToolClient(server_url=URL)

    with pytest.raises(RuntimeError):
        client.get_tools()
    with pytest.raises(RuntimeError):
        await client.call_tool("anything")
    with pytest.raises(RuntimeError):
        await client.execute_tool_call(make_tool_call("t", "{}"))


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ("plain-string-result", "plain-string-result"),
        ([{"text": "inner-text", "type": "text"}], "inner-text"),
    ],
    ids=["string", "content-blocks"],
)
async def test_tool_results_reach_the_caller_and_the_model_as_text(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
    result: Any,
    expected: str,
) -> None:
    """The adapter returns text in content-block lists; providers need the
    inner string."""
    _patch_mcp_seam.tools = [string_tool("echo", result)]
    client = MCPToolClient(server_url=URL)
    await client.initialize()

    message = await client.execute_tool_call(
        make_tool_call("echo", json.dumps({"query": "x"}), call_id="call-42")
    )

    assert await client.call_tool("echo") == expected
    assert message["role"] == "tool"
    assert message["name"] == "echo"
    assert message["tool_call_id"] == "call-42"
    assert message["content"] == expected
    with pytest.raises(ValueError):
        await client.call_tool("missing")


# MCP calls need their own timeout; the LLM timeout cannot cover a hung SSE tool
# call.


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, mcp_client_module.DEFAULT_MCP_TOOL_TIMEOUT_SECONDS),
        ("", mcp_client_module.DEFAULT_MCP_TOOL_TIMEOUT_SECONDS),
        ("not-a-number", mcp_client_module.DEFAULT_MCP_TOOL_TIMEOUT_SECONDS),
        ("12.5", 12.5),
        ("0", None),
        ("-1", None),
    ],
)
def test_mcp_tool_timeout_is_configurable_and_disablable(
    monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: float | None
) -> None:
    if raw is None:
        monkeypatch.delenv(
            mcp_client_module.MCP_TOOL_TIMEOUT_ENV, raising=False
        )
    else:
        monkeypatch.setenv(mcp_client_module.MCP_TOOL_TIMEOUT_ENV, raw)

    assert mcp_client_module.mcp_tool_timeout_seconds() == expected


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


@pytest.mark.parametrize("timeout", ["30", "0"])
async def test_a_responsive_tool_is_untouched_by_the_timeout(
    monkeypatch: pytest.MonkeyPatch, timeout: str
) -> None:
    monkeypatch.setenv(mcp_client_module.MCP_TOOL_TIMEOUT_ENV, timeout)
    client = MCPToolClient()
    client._tools_dict = {
        "search_pubmed": string_tool("search_pubmed", "papers")
    }

    assert await client.call_tool("search_pubmed", query="x") == "papers"


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
