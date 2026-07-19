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
from co_scientist.exceptions import MCPToolTimeoutError
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


async def test_execute_tool_call_unwraps_list_of_text_dicts(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """The LLM tool path unwraps ``[{"text": ...}]`` results like call_tool.

    langchain-mcp-adapters 0.3.0 returns every single-text tool result as a
    list of content blocks, so the tool-loop message content must be reduced
    to the inner string for the provider to read it.
    """
    _patch_mcp_seam.tools = [
        string_tool("blocks", [{"text": "inner-text", "type": "text"}]),
    ]
    client = MCPToolClient(server_url="http://x.test/mcp")
    await client.initialize()

    call = make_tool_call("blocks", "{}", call_id="call-7")
    result = await client.execute_tool_call(call)

    assert result["content"] == "inner-text"


# --- MCP tool-call timeout -------------------------------------------------
#
# Regression: MCP tool invocations were bare awaits. When a server's SSE
# stream broke mid-call the awaiting run parked forever -- in production one
# sat silent for 18 minutes after "Error parsing SSE message", with no error
# and nothing in the log after the request went out. The LLM timeout added
# earlier wraps litellm.acompletion only and never covered this path.


def test_mcp_tool_timeout_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset, blank, and garbage all fall back to the default ceiling."""
    for raw in (None, "", "   ", "not-a-number"):
        if raw is None:
            monkeypatch.delenv(
                mcp_client_module.MCP_TOOL_TIMEOUT_ENV, raising=False
            )
        else:
            monkeypatch.setenv(mcp_client_module.MCP_TOOL_TIMEOUT_ENV, raw)
        assert (
            mcp_client_module.mcp_tool_timeout_seconds()
            == mcp_client_module.DEFAULT_MCP_TOOL_TIMEOUT_SECONDS
        )


def test_mcp_tool_timeout_configurable_and_disablable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operators can retune the ceiling, or remove it with a non-positive."""
    monkeypatch.setenv(mcp_client_module.MCP_TOOL_TIMEOUT_ENV, "12.5")
    assert mcp_client_module.mcp_tool_timeout_seconds() == 12.5
    for disabled in ("0", "-1"):
        monkeypatch.setenv(mcp_client_module.MCP_TOOL_TIMEOUT_ENV, disabled)
        assert mcp_client_module.mcp_tool_timeout_seconds() is None


@pytest.mark.asyncio
async def test_call_tool_cancels_a_hung_tool_and_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tool that never answers is cancelled, not awaited forever.

    The assertion that matters is ``cancelled``: without the ceiling this test
    would hang for the lifetime of the suite, which is exactly what the run
    did in production.
    """
    monkeypatch.setenv(mcp_client_module.MCP_TOOL_TIMEOUT_ENV, "0.05")
    cancelled = asyncio.Event()

    class HungTool:
        async def ainvoke(self, _args: Any) -> str:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return "never"

    client = MCPToolClient()
    client._tools_dict = {"search_pubmed": HungTool()}

    with pytest.raises(MCPToolTimeoutError) as excinfo:
        await client.call_tool("search_pubmed", query="anything")

    assert "search_pubmed" in str(excinfo.value)
    await asyncio.wait_for(cancelled.wait(), timeout=1.0)


@pytest.mark.asyncio
async def test_execute_tool_call_reports_timeout_to_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tool loop survives a dead tool instead of failing the run.

    This path runs under asyncio.gather without return_exceptions, so raising
    here would take down every sibling tool call in the same turn. The model
    is told this one tool did not answer and proceeds on what it has.
    """
    monkeypatch.setenv(mcp_client_module.MCP_TOOL_TIMEOUT_ENV, "0.05")

    class HungTool:
        async def ainvoke(self, _args: Any) -> str:
            await asyncio.sleep(3600)
            return "never"

    client = MCPToolClient()
    client._tools_dict = {"search_web": HungTool()}

    message = await client.execute_tool_call(
        make_tool_call("search_web", json.dumps({"query": "anything"}))
    )

    assert message["role"] == "tool"
    assert message["name"] == "search_web"
    assert "search_web" in message["content"]
    assert "did not respond" in message["content"]


@pytest.mark.asyncio
async def test_a_responsive_tool_is_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ceiling costs a healthy call nothing."""
    monkeypatch.setenv(mcp_client_module.MCP_TOOL_TIMEOUT_ENV, "30")
    client = MCPToolClient()
    client._tools_dict = {
        "search_pubmed": string_tool("search_pubmed", "papers")
    }

    assert await client.call_tool("search_pubmed", query="x") == "papers"


@pytest.mark.asyncio
async def test_timeout_can_be_disabled_entirely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the ceiling off the call is awaited directly, as before."""
    monkeypatch.setenv(mcp_client_module.MCP_TOOL_TIMEOUT_ENV, "0")
    client = MCPToolClient()
    client._tools_dict = {
        "search_pubmed": string_tool("search_pubmed", "papers")
    }

    assert await client.call_tool("search_pubmed", query="x") == "papers"
