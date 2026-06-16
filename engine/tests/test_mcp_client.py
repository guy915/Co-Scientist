# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for the MCP client wrapper in ``co_scientist.mcp_client``.

The only external dependency is ``MultiServerMCPClient`` from
``langchain_mcp_adapters`` - a network client that talks to a live MCP server.
These tests patch that class (at its use-site in ``mcp_client``) with an
in-memory fake whose ``get_tools`` either returns a list of real
``StructuredTool`` instances or raises, so no server is ever contacted. Real
``StructuredTool`` objects are used (rather than mocks) so the wrapper's
``convert_to_openai_tool`` conversion and ``ainvoke`` dispatch run for real;
only the transport seam is faked.

Tool-call objects for ``execute_tool_call`` are built with
``types.SimpleNamespace`` to mimic the LiteLLM shape the code reads
(``.id``, ``.function.name``, ``.function.arguments``).
"""

import json
import types
from collections.abc import Iterator
from typing import Any, cast

from langchain_core.tools import StructuredTool
import pytest

from co_scientist import mcp_client as mcp_mod
from co_scientist.mcp_client import check_literature_source_available
from co_scientist.mcp_client import check_mcp_available
from co_scientist.mcp_client import check_pubmed_available_via_mcp
from co_scientist.mcp_client import get_mcp_client
from co_scientist.mcp_client import MCPToolClient
from co_scientist.mcp_client import reset_mcp_client

# --- Real tool builders -----------------------------------------------------


def _string_tool(name: str, result: Any) -> StructuredTool:
    """Build a real StructuredTool whose coroutine returns ``result``.

    Args:
        name: The tool name exposed on the MCP server.
        result: The value the tool's coroutine should return when invoked.

    Returns:
        A StructuredTool that ignores its arguments and yields ``result``.
    """

    async def _impl(**_: Any) -> Any:
        return result

    return StructuredTool.from_function(
        coroutine=_impl,
        name=name,
        description=f"fake tool {name}",
    )


# --- Fake ToolRegistry (config-driven multi-server path) --------------------


class FakeToolRegistry:
    """Minimal stand-in for ``ToolRegistry`` exercising the registry path.

    Only the methods/attributes ``mcp_client`` reads are implemented:
    ``get_server_configs_for_langchain``, ``get_workflow`` (with an
    ``availability_check`` attribute), ``get_tool`` (with ``mcp_tool_name``),
    ``get_tool_by_mcp_name`` (with ``server``), and ``get_enabled_servers``.
    """

    def __init__(
        self,
        *,
        availability_check: str | None = "check_avail",
        availability_check_present: bool = True,
        check_mcp_tool_name: str = "check_pubmed_available",
        mcp_name_to_server: dict[str, str] | None = None,
    ) -> None:
        """Configure the registry's literature_review workflow and tool map.

        Args:
            availability_check: The availability-check tool id the workflow
                points at, or None to model ``availability_check: null``.
            availability_check_present: If False, ``get_tool`` returns None for
                the availability-check id (models a dangling reference).
            check_mcp_tool_name: The MCP tool name the availability-check tool
                config resolves to.
            mcp_name_to_server: Optional map from MCP tool name to server id for
                ``get_tool_by_mcp_name`` (drives ``get_server_for_tool``).
        """
        self._availability_check = availability_check
        self._availability_check_present = availability_check_present
        self._check_mcp_tool_name = check_mcp_tool_name
        self._mcp_name_to_server = mcp_name_to_server or {}

    def get_server_configs_for_langchain(self) -> dict[str, dict[str, str]]:
        """Return a single-server langchain-style config dict."""
        return {
            "default": {
                "transport": "streamable_http",
                "url": "http://registry.test/mcp",
            }
        }

    def get_enabled_servers(self) -> dict[str, Any]:
        """Return a one-entry enabled-servers map (only ``len`` is read)."""
        return {"default": object()}

    def get_workflow(self, name: str) -> Any:
        """Return a workflow namespace exposing ``availability_check``."""
        if name != "literature_review":
            return None
        return types.SimpleNamespace(
            availability_check=self._availability_check)

    def get_tool(self, tool_id: str) -> Any:
        """Resolve a tool id to a config exposing ``mcp_tool_name``."""
        if tool_id == self._availability_check and (
                self._availability_check_present):
            return types.SimpleNamespace(
                mcp_tool_name=self._check_mcp_tool_name)
        return None

    def get_tool_by_mcp_name(self, mcp_tool_name: str) -> Any:
        """Resolve an MCP tool name to a config exposing ``server``."""
        server = self._mcp_name_to_server.get(mcp_tool_name)
        if server is None:
            return None
        return types.SimpleNamespace(server=server)


# --- Fake MultiServerMCPClient (the external seam) --------------------------


class FakeMultiServerMCPClient:
    """In-memory stand-in for ``MultiServerMCPClient``.

    Patched in over the real class so ``initialize`` never opens a network
    connection. ``get_tools`` returns the configured tool list or raises the
    configured error. A class-level counter records how many instances are
    constructed so caching behavior can be asserted.
    """

    instances_created = 0
    tools: list[StructuredTool] = []
    error: Exception | None = None

    def __init__(self, connections: Any) -> None:
        """Record the connections dict and bump the construction counter."""
        type(self).instances_created += 1
        self.connections = connections

    async def get_tools(self) -> list[StructuredTool]:
        """Return the configured tools or raise the configured error."""
        err = type(self).error
        if err is not None:
            raise err
        return list(type(self).tools)


@pytest.fixture(autouse=True)
def _patch_mcp_seam(
    monkeypatch: pytest.MonkeyPatch
) -> Iterator[type[FakeMultiServerMCPClient]]:
    """Patch the MCP transport class and reset per-test global state.

    Replaces ``MultiServerMCPClient`` at its use-site with a fresh fake class
    (so the construction counter and tool/error config never leak between
    tests) and resets the module-global ``_global_client`` before and after
    each test so caching tests are isolated.

    Args:
        monkeypatch: The pytest monkeypatch fixture.

    Returns:
        The per-test fake client class, for tests that configure it.
    """

    class _Fake(FakeMultiServerMCPClient):
        instances_created = 0
        tools: list[StructuredTool] = []
        error: Exception | None = None

    monkeypatch.setattr(mcp_mod, "MultiServerMCPClient", _Fake)
    reset_mcp_client()
    yield _Fake
    reset_mcp_client()


def _make_tool_call(name: str, arguments: str, call_id: str = "call-1") -> Any:
    """Build a LiteLLM-shaped tool call via SimpleNamespace.

    Args:
        name: The tool function name.
        arguments: The JSON-encoded argument string.
        call_id: The tool-call id echoed back in the response.

    Returns:
        A SimpleNamespace with ``.id`` and ``.function.{name,arguments}``.
    """
    return types.SimpleNamespace(
        id=call_id,
        function=types.SimpleNamespace(name=name, arguments=arguments),
    )


# --- MCPToolClient construction --------------------------------------------


def test_init_legacy_default_server_url_from_env(
    monkeypatch: pytest.MonkeyPatch) -> None:
    """With no args and no env var, the URL defaults to localhost:8888."""
    monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    client = MCPToolClient()
    assert client.server_url == "http://localhost:8888/mcp"


def test_init_legacy_reads_mcp_server_url_env(
    monkeypatch: pytest.MonkeyPatch) -> None:
    """The legacy path reads MCP_SERVER_URL from the environment."""
    monkeypatch.setenv("MCP_SERVER_URL", "http://example.test:9999/mcp")
    client = MCPToolClient()
    assert client.server_url == "http://example.test:9999/mcp"


def test_init_explicit_server_url_overrides_env(
    monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_available_tools_empty_before_initialize() -> None:
    """Before initialize, available_tools is empty and has_tool is False."""
    client = MCPToolClient(server_url="http://x.test/mcp")
    assert client.available_tools == []
    assert client.has_tool("anything") is False


# --- MCPToolClient.initialize ----------------------------------------------


async def test_initialize_populates_tools_and_openai_schemas(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """initialize fetches tools, builds the lookup dict and OpenAI schemas."""
    _patch_mcp_seam.tools = [
        _string_tool("pubmed_search", "{}"),
        _string_tool("check_pubmed_available", "true"),
    ]
    client = MCPToolClient(server_url="http://x.test/mcp")
    await client.initialize()

    assert set(client.available_tools) == {
        "pubmed_search", "check_pubmed_available"
    }
    assert client.has_tool("pubmed_search") is True
    tools_dict, openai_tools = client.get_tools()
    assert set(tools_dict.keys()) == {
        "pubmed_search", "check_pubmed_available"
    }
    schema_names = {t["function"]["name"] for t in openai_tools}
    assert schema_names == {"pubmed_search", "check_pubmed_available"}


async def test_initialize_is_idempotent_single_construction(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """A second initialize on the same client does not rebuild the transport."""
    _patch_mcp_seam.tools = [_string_tool("t1", "ok")]
    client = MCPToolClient(server_url="http://x.test/mcp")
    await client.initialize()
    await client.initialize()
    assert _patch_mcp_seam.instances_created == 1


def test_get_tools_before_initialize_raises() -> None:
    """get_tools before initialize raises RuntimeError (not a silent empty)."""
    client = MCPToolClient(server_url="http://x.test/mcp")
    with pytest.raises(RuntimeError):
        client.get_tools()


async def test_get_tools_whitelist_filters(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """A whitelist restricts both the returned dict and the OpenAI schemas."""
    _patch_mcp_seam.tools = [
        _string_tool("keep_me", "{}"),
        _string_tool("drop_me", "{}"),
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
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """Calling an unregistered tool name raises ValueError."""
    _patch_mcp_seam.tools = [_string_tool("known", "ok")]
    client = MCPToolClient(server_url="http://x.test/mcp")
    await client.initialize()
    with pytest.raises(ValueError):
        await client.call_tool("missing")


async def test_call_tool_returns_string_result_verbatim(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """A string-returning tool's result is returned unchanged."""
    _patch_mcp_seam.tools = [_string_tool("echo", "plain-string-result")]
    client = MCPToolClient(server_url="http://x.test/mcp")
    await client.initialize()
    result = await client.call_tool("echo")
    assert result == "plain-string-result"


async def test_call_tool_unwraps_list_of_text_dicts(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """A ``[{"text": ...}]`` result is unwrapped to the inner text string."""
    _patch_mcp_seam.tools = [
        _string_tool("blocks", [{"text": "inner-text", "type": "text"}]),
    ]
    client = MCPToolClient(server_url="http://x.test/mcp")
    await client.initialize()
    result = await client.call_tool("blocks")
    assert result == "inner-text"


# --- MCPToolClient.execute_tool_call ---------------------------------------


async def test_execute_tool_call_before_initialize_raises() -> None:
    """execute_tool_call before initialize raises RuntimeError."""
    client = MCPToolClient(server_url="http://x.test/mcp")
    call = _make_tool_call("t", "{}")
    with pytest.raises(RuntimeError):
        await client.execute_tool_call(call)


async def test_execute_tool_call_returns_tool_response_message(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """A tool call is dispatched and wrapped as a role=tool response message."""
    _patch_mcp_seam.tools = [_string_tool("pubmed_search", "search-result")]
    client = MCPToolClient(server_url="http://x.test/mcp")
    await client.initialize()

    call = _make_tool_call(
        "pubmed_search", json.dumps({"query": "cancer"}), call_id="call-42")
    result = await client.execute_tool_call(call)

    assert result["role"] == "tool"
    assert result["name"] == "pubmed_search"
    assert result["tool_call_id"] == "call-42"
    assert result["content"] == "search-result"


# --- check_mcp_available: three outcomes ------------------------------------


async def test_check_mcp_available_true_when_tools_present(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """A server that returns at least one tool is reported available."""
    _patch_mcp_seam.tools = [_string_tool("t1", "ok")]
    assert await check_mcp_available(server_url="http://x.test/mcp") is True


async def test_check_mcp_available_false_when_no_tools(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """A server that responds with an empty tool list is reported unavailable."""
    _patch_mcp_seam.tools = []
    assert await check_mcp_available(server_url="http://x.test/mcp") is False


async def test_check_mcp_available_false_on_connection_error(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """A transport error degrades gracefully to False, no exception escapes."""
    _patch_mcp_seam.error = ConnectionError("boom")
    assert await check_mcp_available(server_url="http://x.test/mcp") is False


# --- check_literature_source_available --------------------------------------


async def test_literature_source_true_when_check_tool_returns_true_string(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """The default check tool returning the string "true" yields True."""
    _patch_mcp_seam.tools = [
        _string_tool("check_pubmed_available", "true"),
        _string_tool("pubmed_search", "{}"),
    ]
    assert await check_literature_source_available(
        server_url="http://x.test/mcp") is True


async def test_literature_source_true_when_check_tool_returns_bool(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """A check tool returning a real bool True yields True."""
    _patch_mcp_seam.tools = [
        _string_tool("check_pubmed_available", True),
    ]
    assert await check_literature_source_available(
        server_url="http://x.test/mcp") is True


async def test_literature_source_false_when_check_tool_returns_false_string(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """A check tool returning "false" yields False."""
    _patch_mcp_seam.tools = [
        _string_tool("check_pubmed_available", "false"),
    ]
    assert await check_literature_source_available(
        server_url="http://x.test/mcp") is False


async def test_literature_source_false_when_check_tool_absent(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """If the default check tool is missing from the server, returns False."""
    _patch_mcp_seam.tools = [_string_tool("some_other_tool", "{}")]
    assert await check_literature_source_available(
        server_url="http://x.test/mcp") is False


async def test_literature_source_false_when_server_has_no_tools(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """If the MCP server reports no tools, the source is unavailable."""
    _patch_mcp_seam.tools = []
    assert await check_literature_source_available(
        server_url="http://x.test/mcp") is False


async def test_literature_source_false_on_connection_error(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """A transport error degrades gracefully to False."""
    _patch_mcp_seam.error = RuntimeError("down")
    assert await check_literature_source_available(
        server_url="http://x.test/mcp") is False


# --- check_pubmed_available_via_mcp (thin alias) ----------------------------


async def test_pubmed_alias_delegates_true(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """The deprecated alias returns True when the source is available."""
    _patch_mcp_seam.tools = [_string_tool("check_pubmed_available", "true")]
    assert await check_pubmed_available_via_mcp(
        server_url="http://x.test/mcp") is True


async def test_pubmed_alias_delegates_false(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """The deprecated alias returns False when the source is unavailable."""
    _patch_mcp_seam.error = ConnectionError("boom")
    assert await check_pubmed_available_via_mcp(
        server_url="http://x.test/mcp") is False


# --- get_mcp_client / global caching ----------------------------------------


async def test_get_mcp_client_caches_single_instance(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """Repeated get_mcp_client calls return the same cached, initialized client."""
    _patch_mcp_seam.tools = [_string_tool("t1", "ok")]
    first = await get_mcp_client(server_url="http://x.test/mcp")
    second = await get_mcp_client(server_url="http://x.test/mcp")

    assert first is second
    # The transport is constructed once: the second call reuses the cached
    # client and initialize() short-circuits.
    assert _patch_mcp_seam.instances_created == 1
    assert first.available_tools == ["t1"]


async def test_get_mcp_client_force_new_rebuilds(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """force_new builds a fresh client and a fresh transport connection."""
    _patch_mcp_seam.tools = [_string_tool("t1", "ok")]
    first = await get_mcp_client(server_url="http://x.test/mcp")
    second = await get_mcp_client(server_url="http://x.test/mcp", force_new=True)

    assert first is not second
    assert _patch_mcp_seam.instances_created == 2


async def test_reset_mcp_client_clears_global(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """After reset, the next get_mcp_client builds a brand-new client."""
    _patch_mcp_seam.tools = [_string_tool("t1", "ok")]
    first = await get_mcp_client(server_url="http://x.test/mcp")
    reset_mcp_client()
    second = await get_mcp_client(server_url="http://x.test/mcp")

    assert first is not second
    assert _patch_mcp_seam.instances_created == 2


# --- Registry / config-driven multi-server path -----------------------------


def _registry(**kwargs: Any) -> Any:
    """Build a FakeToolRegistry typed as the ToolRegistry the code expects."""
    return cast(Any, FakeToolRegistry(**kwargs))


def test_init_with_registry_uses_registry_server_configs() -> None:
    """A tool_registry drives the server configs and surfaced server_url."""
    client = MCPToolClient(tool_registry=_registry())
    assert client.server_url == "http://registry.test/mcp"


async def test_initialize_with_registry_tracks_tool_to_server(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """Registry-driven initialize records the server that provides each tool."""
    _patch_mcp_seam.tools = [
        _string_tool("pubmed_search", "{}"),
        _string_tool("orphan_tool", "{}"),
    ]
    registry = _registry(mcp_name_to_server={"pubmed_search": "pubmed_server"})
    client = MCPToolClient(tool_registry=registry)
    await client.initialize()

    assert client.get_server_for_tool("pubmed_search") == "pubmed_server"
    # A tool the registry doesn't know about maps to no server.
    assert client.get_server_for_tool("orphan_tool") is None


async def test_check_mcp_available_with_registry_true(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """check_mcp_available works through the registry multi-server path."""
    _patch_mcp_seam.tools = [_string_tool("t1", "ok")]
    assert await check_mcp_available(tool_registry=_registry()) is True


async def test_literature_source_registry_explicit_check_tool_true(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """An explicit availability_check tool that returns "true" yields True."""
    _patch_mcp_seam.tools = [
        _string_tool("check_pubmed_available", "true"),
        _string_tool("pubmed_search", "{}"),
    ]
    registry = _registry(availability_check="check_avail",
                         check_mcp_tool_name="check_pubmed_available")
    assert await check_literature_source_available(
        tool_registry=registry) is True


async def test_literature_source_registry_check_tool_missing_returns_false(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """A configured check tool absent from the live server yields False."""
    _patch_mcp_seam.tools = [_string_tool("pubmed_search", "{}")]
    registry = _registry(availability_check="check_avail",
                         check_mcp_tool_name="check_pubmed_available")
    assert await check_literature_source_available(
        tool_registry=registry) is False


async def test_literature_source_registry_null_check_assumes_available(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """``availability_check: null`` returns True without calling any check tool.

    The only requirement is that the MCP server is up (returns tools); no
    source-specific availability tool is invoked.
    """
    _patch_mcp_seam.tools = [_string_tool("pubmed_search", "{}")]
    registry = _registry(availability_check=None)
    assert await check_literature_source_available(
        tool_registry=registry) is True


async def test_literature_source_registry_false_when_mcp_down(
    _patch_mcp_seam: type[FakeMultiServerMCPClient]) -> None:
    """With a registry but no live MCP server, the source is unavailable."""
    _patch_mcp_seam.error = ConnectionError("down")
    registry = _registry(availability_check=None)
    assert await check_literature_source_available(
        tool_registry=registry) is False
