"""Tests for the ``MCPToolClient`` wrapper in ``co_scientist.mcp_client``.

Covers client construction, ``initialize``, ``get_tools``, ``call_tool`` and
``execute_tool_call``. The availability-check helpers and the global-client
caching / registry path are covered in ``test_mcp_client_availability``.

The external ``MultiServerMCPClient`` transport is replaced by the
``_patch_mcp_seam`` fixture (in ``conftest``) with an in-memory fake whose
``get_tools`` returns real ``StructuredTool`` instances, so no server is ever
contacted while the wrapper's ``convert_to_openai_tool`` conversion and
``ainvoke`` dispatch run for real. Tool-call objects for ``execute_tool_call``
are built with ``types.SimpleNamespace`` to mimic the LiteLLM shape the code
reads (``.id``, ``.function.name``, ``.function.arguments``).
"""

import asyncio
import json
from typing import Any

import pytest

import co_scientist.mcp_client as mcp_client_module
from co_scientist.mcp_client import MCPToolClient
from tests._mcp import FakeMultiServerMCPClient, make_tool_call, string_tool

# --- MCPToolClient construction --------------------------------------------


def test_init_legacy_default_server_url_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no args and no env var, the URL defaults to localhost:8888."""
    monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    client = MCPToolClient()
    assert client.server_url == "http://localhost:8888/mcp"


def test_init_legacy_reads_mcp_server_url_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The legacy path reads MCP_SERVER_URL from the environment."""
    monkeypatch.setenv("MCP_SERVER_URL", "http://example.test:9999/mcp")
    client = MCPToolClient()
    assert client.server_url == "http://example.test:9999/mcp"


def test_init_explicit_server_url_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit server_url takes precedence over the environment."""
    monkeypatch.setenv("MCP_SERVER_URL", "http://ignored.test/mcp")
    client = MCPToolClient(server_url="http://explicit.test/mcp")
    assert client.server_url == "http://explicit.test/mcp"


def test_init_server_configs_used_directly() -> None:
    """Provided server_configs are used and surfaced via server_url."""
    configs = {
        "s1": {"transport": "streamable_http", "url": "http://s1.test/mcp"},
    }
    client = MCPToolClient(server_configs=configs)
    assert client.server_url == "http://s1.test/mcp"


def test_has_tool_false_before_initialize() -> None:
    """Before initialize, has_tool reports every tool as unavailable."""
    client = MCPToolClient(server_url="http://x.test/mcp")
    assert client.has_tool("anything") is False


# --- MCPToolClient.initialize ----------------------------------------------


async def test_initialize_populates_tools_and_openai_schemas(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """Initialize fetches tools, builds the lookup dict and OpenAI schemas."""
    _patch_mcp_seam.tools = [
        string_tool("pubmed_search", "{}"),
        string_tool("check_pubmed_available", "true"),
    ]
    client = MCPToolClient(server_url="http://x.test/mcp")
    await client.initialize()

    assert client.has_tool("pubmed_search") is True
    tools_dict, openai_tools = client.get_tools()
    assert set(tools_dict.keys()) == {"pubmed_search", "check_pubmed_available"}
    schema_names = {t["function"]["name"] for t in openai_tools}
    assert schema_names == {"pubmed_search", "check_pubmed_available"}


async def test_initialize_is_idempotent_single_construction(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A second initialize on the same client does not rebuild the transport."""
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]
    client = MCPToolClient(server_url="http://x.test/mcp")
    await client.initialize()
    await client.initialize()
    assert _patch_mcp_seam.instances_created == 1


async def test_concurrent_initialize_waits_for_complete_tool_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent callers share one fully initialized MCP transport."""
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0
    tools: list[Any] = [string_tool("t1", "ok")]

    class SlowMultiServerMCPClient:
        """Hold tool discovery open so the initialization race is observable."""

        def __init__(self, _connections: object) -> None:
            pass

        async def get_tools(self) -> list[object]:
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return tools

    monkeypatch.setattr(
        mcp_client_module,
        "MultiServerMCPClient",
        SlowMultiServerMCPClient,
    )
    client = MCPToolClient(server_url="http://x.test/mcp")
    first = asyncio.create_task(client.initialize())
    await started.wait()
    second = asyncio.create_task(client.initialize())
    await asyncio.sleep(0)

    assert not second.done()
    release.set()
    await asyncio.gather(first, second)
    assert calls == 1
    assert client.has_tool("t1")


def test_get_tools_before_initialize_raises() -> None:
    """get_tools before initialize raises RuntimeError (not a silent empty)."""
    client = MCPToolClient(server_url="http://x.test/mcp")
    with pytest.raises(RuntimeError):
        client.get_tools()


async def test_get_tools_whitelist_filters(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A whitelist restricts both the returned dict and the OpenAI schemas."""
    _patch_mcp_seam.tools = [
        string_tool("keep_me", "{}"),
        string_tool("drop_me", "{}"),
    ]
    client = MCPToolClient(server_url="http://x.test/mcp")
    await client.initialize()

    tools_dict, openai_tools = client.get_tools(whitelist=["keep_me"])
    assert set(tools_dict.keys()) == {"keep_me"}
    schema_names = {t["function"]["name"] for t in openai_tools}
    assert schema_names == {"keep_me"}


# --- MCPToolClient.call_tool -----------------------------------------------


async def test_call_tool_before_initialize_raises() -> None:
    """call_tool before initialize raises RuntimeError."""
    client = MCPToolClient(server_url="http://x.test/mcp")
    with pytest.raises(RuntimeError):
        await client.call_tool("anything")


async def test_call_tool_unknown_name_raises_value_error(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """Calling an unregistered tool name raises ValueError."""
    _patch_mcp_seam.tools = [string_tool("known", "ok")]
    client = MCPToolClient(server_url="http://x.test/mcp")
    await client.initialize()
    with pytest.raises(ValueError):
        await client.call_tool("missing")


async def test_call_tool_returns_string_result_verbatim(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A string-returning tool's result is returned unchanged."""
    _patch_mcp_seam.tools = [string_tool("echo", "plain-string-result")]
    client = MCPToolClient(server_url="http://x.test/mcp")
    await client.initialize()
    result = await client.call_tool("echo")
    assert result == "plain-string-result"


async def test_call_tool_unwraps_list_of_text_dicts(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A ``[{"text": ...}]`` result is unwrapped to the inner text string."""
    _patch_mcp_seam.tools = [
        string_tool("blocks", [{"text": "inner-text", "type": "text"}]),
    ]
    client = MCPToolClient(server_url="http://x.test/mcp")
    await client.initialize()
    result = await client.call_tool("blocks")
    assert result == "inner-text"


# --- MCPToolClient.execute_tool_call ---------------------------------------


async def test_execute_tool_call_before_initialize_raises() -> None:
    """execute_tool_call before initialize raises RuntimeError."""
    client = MCPToolClient(server_url="http://x.test/mcp")
    call = make_tool_call("t", "{}")
    with pytest.raises(RuntimeError):
        await client.execute_tool_call(call)


async def test_execute_tool_call_returns_tool_response_message(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A tool call is dispatched and wrapped as a role=tool response message."""
    _patch_mcp_seam.tools = [string_tool("pubmed_search", "search-result")]
    client = MCPToolClient(server_url="http://x.test/mcp")
    await client.initialize()

    call = make_tool_call(
        "pubmed_search", json.dumps({"query": "cancer"}), call_id="call-42"
    )
    result = await client.execute_tool_call(call)

    assert result["role"] == "tool"
    assert result["name"] == "pubmed_search"
    assert result["tool_call_id"] == "call-42"
    assert result["content"] == "search-result"
