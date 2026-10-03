"""Offline contracts for mcp client."""

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
    _resolve_server_configs,
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

# --- check_mcp_available: three outcomes ------------------------------------


async def test_check_mcp_available_true_when_tools_present(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A server that returns at least one tool is reported available."""
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]
    assert await check_mcp_available(server_url="http://x.test/mcp") is True


async def test_check_mcp_available_false_when_no_tools(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A server responding with an empty tool list is reported unavailable."""
    _patch_mcp_seam.tools = []
    assert await check_mcp_available(server_url="http://x.test/mcp") is False


async def test_check_mcp_available_false_on_connection_error(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A transport error degrades gracefully to False, no exception escapes."""
    _patch_mcp_seam.error = ConnectionError("boom")
    assert await check_mcp_available(server_url="http://x.test/mcp") is False


# --- check_literature_source_available --------------------------------------


async def test_literature_source_true_when_check_tool_returns_true_string(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """The default check tool returning the string "true" yields True."""
    _patch_mcp_seam.tools = [
        string_tool("check_pubmed_available", "true"),
        string_tool("pubmed_search", "{}"),
    ]
    assert (
        await check_literature_source_available(server_url="http://x.test/mcp")
        is True
    )


async def test_literature_source_true_when_check_tool_returns_bool(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A check tool returning a real bool True yields True."""
    _patch_mcp_seam.tools = [
        string_tool("check_pubmed_available", True),
    ]
    assert (
        await check_literature_source_available(server_url="http://x.test/mcp")
        is True
    )


async def test_literature_source_false_when_check_tool_returns_false_string(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A check tool returning "false" yields False."""
    _patch_mcp_seam.tools = [
        string_tool("check_pubmed_available", "false"),
    ]
    assert (
        await check_literature_source_available(server_url="http://x.test/mcp")
        is False
    )


async def test_literature_source_false_when_check_tool_absent(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """If the default check tool is missing from the server, returns False."""
    _patch_mcp_seam.tools = [string_tool("some_other_tool", "{}")]
    assert (
        await check_literature_source_available(server_url="http://x.test/mcp")
        is False
    )


async def test_literature_source_false_when_server_has_no_tools(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """If the MCP server reports no tools, the source is unavailable."""
    _patch_mcp_seam.tools = []
    assert (
        await check_literature_source_available(server_url="http://x.test/mcp")
        is False
    )


async def test_literature_source_false_on_connection_error(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A transport error degrades gracefully to False."""
    _patch_mcp_seam.error = RuntimeError("down")
    assert (
        await check_literature_source_available(server_url="http://x.test/mcp")
        is False
    )


# --- get_mcp_client / global caching ----------------------------------------


async def test_get_mcp_client_caches_single_instance(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """Repeated get_mcp_client calls return the same cached client."""
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]
    first = await get_mcp_client(server_url="http://x.test/mcp")
    second = await get_mcp_client(server_url="http://x.test/mcp")

    assert first is second
    # The transport is constructed once: the second call reuses the cached
    # client and initialize() short-circuits.
    assert _patch_mcp_seam.instances_created == 1
    assert first.has_tool("t1")


async def test_get_mcp_client_force_new_rebuilds(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """force_new builds a fresh client and a fresh transport connection."""
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]
    first = await get_mcp_client(server_url="http://x.test/mcp")
    second = await get_mcp_client(
        server_url="http://x.test/mcp", force_new=True
    )

    assert first is not second
    assert _patch_mcp_seam.instances_created == 2


async def test_reset_mcp_client_clears_global(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """After reset, the next get_mcp_client builds a brand-new client."""
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]
    first = await get_mcp_client(server_url="http://x.test/mcp")
    reset_mcp_client()
    second = await get_mcp_client(server_url="http://x.test/mcp")

    assert first is not second
    assert _patch_mcp_seam.instances_created == 2


# --- Registry / config-driven multi-server path -----------------------------


def test_init_with_registry_uses_registry_server_configs() -> None:
    """A tool_registry drives the server configs and surfaced server_url."""
    client = MCPToolClient(tool_registry=make_registry())
    assert client.server_url == "http://registry.test/mcp"


async def test_initialize_with_registry_tracks_tool_to_server(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """Registry-driven initialize records the server that provides each tool."""
    _patch_mcp_seam.tools = [
        string_tool("pubmed_search", "{}"),
        string_tool("orphan_tool", "{}"),
    ]
    registry = make_registry(
        mcp_name_to_server={"pubmed_search": "pubmed_server"}
    )
    client = MCPToolClient(tool_registry=registry)
    await client.initialize()

    # initialize records the providing server for each tool in the map that
    # backed the (now-removed) get_server_for_tool accessor.
    assert client._tool_to_server.get("pubmed_search") == "pubmed_server"
    # A tool the registry doesn't know about maps to no server.
    assert client._tool_to_server.get("orphan_tool") is None


async def test_check_mcp_available_with_registry_true(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """check_mcp_available works through the registry multi-server path."""
    _patch_mcp_seam.tools = [string_tool("t1", "ok")]
    assert await check_mcp_available(tool_registry=make_registry()) is True


async def test_literature_source_registry_explicit_check_tool_true(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """An explicit availability_check tool that returns "true" yields True."""
    _patch_mcp_seam.tools = [
        string_tool("check_pubmed_available", "true"),
        string_tool("pubmed_search", "{}"),
    ]
    registry = make_registry(
        availability_check="check_avail",
        check_mcp_tool_name="check_pubmed_available",
    )
    assert (
        await check_literature_source_available(tool_registry=registry) is True
    )


async def test_literature_source_registry_check_tool_missing_returns_false(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A configured check tool absent from the live server yields False."""
    _patch_mcp_seam.tools = [string_tool("pubmed_search", "{}")]
    registry = make_registry(
        availability_check="check_avail",
        check_mcp_tool_name="check_pubmed_available",
    )
    assert (
        await check_literature_source_available(tool_registry=registry) is False
    )


async def test_literature_source_registry_null_check_assumes_available(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """``availability_check: null`` returns True without calling any check tool.

    The only requirement is that the MCP server is up (returns tools); no
    source-specific availability tool is invoked.
    """
    _patch_mcp_seam.tools = [string_tool("pubmed_search", "{}")]
    registry = make_registry(availability_check=None)
    assert (
        await check_literature_source_available(tool_registry=registry) is True
    )


async def test_literature_source_registry_false_when_mcp_down(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """With a registry but no live MCP server, the source is unavailable."""
    _patch_mcp_seam.error = ConnectionError("down")
    registry = make_registry(availability_check=None)
    assert (
        await check_literature_source_available(tool_registry=registry) is False
    )


# --- check_web_search_available ---------------------------------------------
#
# The connector's health used to be read off the presence of ``search_web``,
# which only says a key was set when the server booted. A key the provider
# has since refused leaves the tool listed and every search empty, so the
# status card read "up" while the runs saw nothing.


async def test_web_search_false_when_the_server_reports_a_dead_key(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """A listed search_web does not override the server's own verdict."""
    _patch_mcp_seam.tools = [
        string_tool("check_web_search_available", "false"),
        string_tool("search_web", "{}"),
    ]
    assert (
        await check_web_search_available(server_url="http://x.test/mcp")
        is False
    )


async def test_web_search_true_when_the_server_reports_a_usable_key(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """The check tool's affirmative answer is the whole answer."""
    _patch_mcp_seam.tools = [
        string_tool("check_web_search_available", "true"),
        string_tool("search_web", "{}"),
    ]
    assert (
        await check_web_search_available(server_url="http://x.test/mcp") is True
    )


async def test_web_search_falls_back_to_tool_presence_on_older_servers(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """App and MCP server deploy separately; an old image must still pass."""
    _patch_mcp_seam.tools = [string_tool("search_web", "{}")]
    assert (
        await check_web_search_available(server_url="http://x.test/mcp") is True
    )


async def test_web_search_false_when_the_tool_is_absent_entirely(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """No key at boot means no search_web, which is still "not usable"."""
    _patch_mcp_seam.tools = [string_tool("search_pubmed", "{}")]
    assert (
        await check_web_search_available(server_url="http://x.test/mcp")
        is False
    )


async def test_web_search_false_on_connection_error(
    _patch_mcp_seam: type[FakeMultiServerMCPClient],
) -> None:
    """An unreachable server degrades to unavailable, like the other probes."""
    _patch_mcp_seam.error = ConnectionError("boom")
    assert (
        await check_web_search_available(server_url="http://x.test/mcp")
        is False
    )


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
        mcp_client_session_module,
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


def test_unset_secret_sends_no_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the env var unset, resolved configs carry no headers at all.

    This is the "unset variable keeps the current behaviour" requirement:
    a deployment that has not adopted the secret must send exactly the
    request shape it always has.
    """
    monkeypatch.delenv(MCP_SHARED_SECRET_ENV, raising=False)

    configs = _resolve_server_configs(None, None, "http://x.test/mcp")

    assert "headers" not in configs["default"]


def test_configured_secret_is_attached_to_legacy_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(MCP_SHARED_SECRET_ENV, "topsecret")

    configs = _resolve_server_configs(None, None, "http://x.test/mcp")

    assert configs["default"]["headers"] == {MCP_AUTH_HEADER: "topsecret"}


def test_configured_secret_is_attached_to_explicit_configs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(MCP_SHARED_SECRET_ENV, "topsecret")
    explicit = {
        "s1": {"transport": "streamable_http", "url": "http://s1.test/mcp"},
    }

    configs = _resolve_server_configs(None, explicit, None)

    assert configs["s1"]["headers"] == {MCP_AUTH_HEADER: "topsecret"}
    # The input dict is not mutated in place.
    assert "headers" not in explicit["s1"]


def test_configured_secret_merges_with_existing_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller-supplied header on the config survives alongside the secret."""
    monkeypatch.setenv(MCP_SHARED_SECRET_ENV, "topsecret")
    explicit = {
        "s1": {
            "transport": "streamable_http",
            "url": "http://s1.test/mcp",
            "headers": {"X-Other": "kept"},
        },
    }

    configs = _resolve_server_configs(None, explicit, None)

    assert configs["s1"]["headers"] == {
        "X-Other": "kept",
        MCP_AUTH_HEADER: "topsecret",
    }


def test_empty_secret_is_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(MCP_SHARED_SECRET_ENV, "")

    configs = _resolve_server_configs(None, None, "http://x.test/mcp")

    assert "headers" not in configs["default"]


def test_mcp_tool_client_carries_the_header_through_server_configs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The header reaches MCPToolClient's own resolved server config."""
    monkeypatch.setenv(MCP_SHARED_SECRET_ENV, "topsecret")

    client = MCPToolClient(server_url="http://x.test/mcp")

    assert client._server_configs["default"]["headers"] == {
        MCP_AUTH_HEADER: "topsecret"
    }
