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
"""Tests for HybridToolProvider: tool merging, whitelisting, and routing.

The provider composes an ``MCPToolClient`` (an external dependency, here
replaced by a tiny in-memory fake that exposes only ``get_tools`` and
``execute_tool_call``) with a real ``PythonToolRegistry`` holding genuinely
registered async functions. These tests exercise the real merging,
source-tracking, whitelisting, and routing logic - only the MCP client is
faked. Tool-call objects are built with ``types.SimpleNamespace`` to mimic the
LiteLLM shape the provider reads (``.id``, ``.function.name``,
``.function.arguments``).
"""

import json
import types
from typing import Any, cast

from co_scientist.mcp_client import MCPToolClient
from co_scientist.tools.provider import HybridToolProvider
from co_scientist.tools.registry import PythonToolRegistry


class FakeMCPClient:
    """Minimal stand-in for ``MCPToolClient`` used by the provider.

    Records the whitelist passed to ``get_tools`` and the tool calls routed to
    ``execute_tool_call`` so tests can assert routing without a real MCP server.
    """

    def __init__(self, tools: dict[str, Any] | None = None) -> None:
        """Initialize the fake with an optional name -> tool-object mapping."""
        self._tools = tools or {}
        self.get_tools_calls: list[list[str] | None] = []
        self.executed: list[Any] = []

    def get_tools(
        self,
        whitelist: list[str] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Return filtered (tools_dict, openai_tools) like the real client."""
        self.get_tools_calls.append(whitelist)
        if whitelist is None:
            selected = dict(self._tools)
        else:
            selected = {
                name: obj
                for name, obj in self._tools.items()
                if name in whitelist
            }
        openai_tools = [{
            "type": "function",
            "function": {
                "name": name
            },
        } for name in selected]
        return selected, openai_tools

    async def execute_tool_call(self, tool_call: Any) -> dict[str, Any]:
        """Record the call and return a sentinel MCP tool-response message."""
        self.executed.append(tool_call)
        return {
            "role": "tool",
            "name": tool_call.function.name,
            "tool_call_id": tool_call.id,
            "content": "mcp-result",
        }


def fake_mcp(**kwargs: Any) -> MCPToolClient:
    """Build a FakeMCPClient typed as the MCPToolClient the provider expects."""
    return cast(MCPToolClient, FakeMCPClient(**kwargs))


def _make_registry() -> PythonToolRegistry:
    """Build a registry with two genuinely registered async tools."""
    registry = PythonToolRegistry()

    @registry.register(name="echo_tool", description="echo the text back")
    async def echo_tool(text: str) -> dict[str, Any]:  # pylint: disable=unused-variable
        return {"echoed": text}

    @registry.register(name="add_tool", description="add two integers")
    async def add_tool(a: int, b: int) -> dict[str, Any]:  # pylint: disable=unused-variable
        return {"sum": a + b}

    return registry


def _make_tool_call(name: str, arguments: str, call_id: str = "call-1") -> Any:
    """Build a LiteLLM-shaped tool call via SimpleNamespace."""
    return types.SimpleNamespace(
        id=call_id,
        function=types.SimpleNamespace(name=name, arguments=arguments),
    )


# --- get_tools: python whitelist -------------------------------------------


def test_get_tools_python_whitelist_filters_to_named_tool() -> None:
    """A python whitelist returns only the named tool in dict and schemas."""
    provider = HybridToolProvider(mcp_client=fake_mcp(),
                                  python_registry=_make_registry())
    tools_dict, openai_tools = provider.get_tools(python_whitelist=["echo_tool"])

    assert set(tools_dict.keys()) == {"echo_tool"}
    assert callable(tools_dict["echo_tool"])
    schema_names = {t["function"]["name"] for t in openai_tools}
    assert schema_names == {"echo_tool"}


def test_get_tools_python_whitelist_multiple_tools() -> None:
    """A whitelist of several tools includes exactly those tools."""
    provider = HybridToolProvider(mcp_client=fake_mcp(),
                                  python_registry=_make_registry())
    tools_dict, openai_tools = provider.get_tools(
        python_whitelist=["echo_tool", "add_tool"])

    assert set(tools_dict.keys()) == {"echo_tool", "add_tool"}
    schema_names = {t["function"]["name"] for t in openai_tools}
    assert schema_names == {"echo_tool", "add_tool"}


def test_get_tools_no_python_whitelist_yields_no_python_tools() -> None:
    """Omitting the python whitelist (None) excludes all python tools."""
    provider = HybridToolProvider(mcp_client=fake_mcp(),
                                  python_registry=_make_registry())
    tools_dict, openai_tools = provider.get_tools()

    assert tools_dict == {}
    assert openai_tools == []


def test_get_tools_empty_mcp_whitelist_adds_no_mcp_tools() -> None:
    """An empty mcp whitelist returns no MCP tools while python tools merge."""
    fake = FakeMCPClient(tools={"pubmed_search": object()})
    provider = HybridToolProvider(mcp_client=cast(MCPToolClient, fake),
                                  python_registry=_make_registry())
    tools_dict, _ = provider.get_tools(mcp_whitelist=[],
                                       python_whitelist=["echo_tool"])

    # Empty whitelist still calls the client, but filters everything out.
    assert fake.get_tools_calls == [[]]
    assert set(tools_dict.keys()) == {"echo_tool"}


def test_get_tools_merges_mcp_and_python_sources() -> None:
    """Both sources merge into one dict and source tracking is recorded."""
    fake = FakeMCPClient(tools={"pubmed_search": object()})
    provider = HybridToolProvider(mcp_client=cast(MCPToolClient, fake),
                                  python_registry=_make_registry())
    tools_dict, openai_tools = provider.get_tools(
        mcp_whitelist=["pubmed_search"], python_whitelist=["add_tool"])

    assert set(tools_dict.keys()) == {"pubmed_search", "add_tool"}
    schema_names = {t["function"]["name"] for t in openai_tools}
    assert schema_names == {"pubmed_search", "add_tool"}
    # pylint: disable=protected-access
    assert provider._tool_sources["pubmed_search"] == "mcp"
    assert provider._tool_sources["add_tool"] == "python"


def test_get_tools_mcp_whitelist_forwarded_to_client() -> None:
    """The mcp whitelist is forwarded verbatim to the MCP client."""
    fake = FakeMCPClient(tools={"pubmed_search": object(), "other": object()})
    provider = HybridToolProvider(mcp_client=cast(MCPToolClient, fake), python_registry=None)
    provider.get_tools(mcp_whitelist=["pubmed_search"])

    assert fake.get_tools_calls == [["pubmed_search"]]


# --- execute_tool_call: routing --------------------------------------------


async def test_execute_routes_python_tool_to_registry_function() -> None:
    """A python tool call runs the real registered function and serializes it."""
    provider = HybridToolProvider(mcp_client=fake_mcp(),
                                  python_registry=_make_registry())
    provider.get_tools(python_whitelist=["add_tool"])

    tool_call = _make_tool_call("add_tool",
                                json.dumps({"a": 2, "b": 3}),
                                call_id="call-add")
    result = await provider.execute_tool_call(tool_call)

    assert result["role"] == "tool"
    assert result["name"] == "add_tool"
    assert result["tool_call_id"] == "call-add"
    assert json.loads(result["content"]) == {"sum": 5}


async def test_execute_routes_mcp_tool_to_fake_client() -> None:
    """An MCP tool call is delegated to the fake MCP client's executor."""
    fake = FakeMCPClient(tools={"pubmed_search": object()})
    provider = HybridToolProvider(mcp_client=cast(MCPToolClient, fake),
                                  python_registry=_make_registry())
    provider.get_tools(mcp_whitelist=["pubmed_search"])

    tool_call = _make_tool_call("pubmed_search",
                                json.dumps({"query": "cancer"}),
                                call_id="call-mcp")
    result = await provider.execute_tool_call(tool_call)

    assert fake.executed == [tool_call]
    assert result["name"] == "pubmed_search"
    assert result["tool_call_id"] == "call-mcp"
    assert result["content"] == "mcp-result"


async def test_execute_python_tool_passes_arguments_through() -> None:
    """JSON arguments are decoded and passed as kwargs to the function."""
    provider = HybridToolProvider(mcp_client=fake_mcp(),
                                  python_registry=_make_registry())
    provider.get_tools(python_whitelist=["echo_tool"])

    tool_call = _make_tool_call("echo_tool", json.dumps({"text": "hello"}))
    result = await provider.execute_tool_call(tool_call)

    assert json.loads(result["content"]) == {"echoed": "hello"}


# --- execute_tool_call: error / edge cases ---------------------------------


async def test_execute_unknown_tool_returns_error_response() -> None:
    """An unregistered tool name yields an error tool-response, not a raise."""
    provider = HybridToolProvider(mcp_client=fake_mcp(),
                                  python_registry=_make_registry())
    # No get_tools call, so nothing is tracked as a known source.
    tool_call = _make_tool_call("nope_tool", "{}", call_id="call-x")
    result = await provider.execute_tool_call(tool_call)

    assert result["role"] == "tool"
    assert result["name"] == "nope_tool"
    assert result["tool_call_id"] == "call-x"
    payload = json.loads(result["content"])
    assert payload["error"] == "unknown tool: nope_tool"


async def test_execute_python_tool_invalid_json_returns_error_response() -> None:
    """Malformed JSON arguments surface as an error response (ToolError caught)."""
    provider = HybridToolProvider(mcp_client=fake_mcp(),
                                  python_registry=_make_registry())
    provider.get_tools(python_whitelist=["echo_tool"])

    tool_call = _make_tool_call("echo_tool", "{not valid json")
    result = await provider.execute_tool_call(tool_call)

    payload = json.loads(result["content"])
    assert "tool execution failed" in payload["error"]
    assert "invalid JSON arguments" in payload["error"]


async def test_execute_python_source_without_registry_errors() -> None:
    """A python-routed call with no registry surfaces a ConfigError response."""
    fake = FakeMCPClient()
    provider = HybridToolProvider(mcp_client=cast(MCPToolClient, fake),
                                  python_registry=_make_registry())
    provider.get_tools(python_whitelist=["echo_tool"])
    # Drop the registry after sources are tracked to force the None branch.
    provider.python_registry = None

    tool_call = _make_tool_call("echo_tool", json.dumps({"text": "x"}))
    result = await provider.execute_tool_call(tool_call)

    payload = json.loads(result["content"])
    assert "tool execution failed" in payload["error"]
    assert "Python registry not configured" in payload["error"]
