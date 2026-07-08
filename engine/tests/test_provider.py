"""Tests for MCPToolProvider: tool listing, whitelisting, and execution.

The provider wraps an ``MCPToolClient`` (an external dependency, here replaced
by a tiny in-memory fake that exposes only ``get_tools`` and
``execute_tool_call``). These tests exercise the real name-tracking,
whitelisting, and error-wrapping logic - only the MCP client is faked.
Tool-call objects are built with ``types.SimpleNamespace`` to mimic the
LiteLLM shape the provider reads (``.id``, ``.function.name``,
``.function.arguments``).
"""

import json
import types
from typing import Any, cast

from co_scientist.mcp_client import MCPToolClient
from co_scientist.tools.provider import MCPToolProvider


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


class FailingMCPClient(FakeMCPClient):
    """Fake MCP client whose executor always raises."""

    async def execute_tool_call(self, tool_call: Any) -> dict[str, Any]:
        """Raise to simulate a tool execution failure."""
        raise RuntimeError(f"server unavailable for {tool_call.function.name}")


def _make_tool_call(name: str, arguments: str, call_id: str = "call-1") -> Any:
    """Build a LiteLLM-shaped tool call via SimpleNamespace."""
    return types.SimpleNamespace(
        id=call_id,
        function=types.SimpleNamespace(name=name, arguments=arguments),
    )


def _make_provider(fake: FakeMCPClient) -> MCPToolProvider:
    """Build a provider around a fake client typed as MCPToolClient."""
    return MCPToolProvider(mcp_client=cast(MCPToolClient, fake))


# --- get_tools: whitelisting ------------------------------------------------


def test_get_tools_whitelist_filters_to_named_tool() -> None:
    """A whitelist returns only the named tool in dict and schemas."""
    fake = FakeMCPClient(tools={"pubmed_search": object(), "other": object()})
    provider = _make_provider(fake)
    tools_dict, openai_tools = provider.get_tools(
        mcp_whitelist=["pubmed_search"])

    assert set(tools_dict.keys()) == {"pubmed_search"}
    schema_names = {t["function"]["name"] for t in openai_tools}
    assert schema_names == {"pubmed_search"}


def test_get_tools_no_whitelist_yields_all_tools() -> None:
    """Omitting the whitelist (None) exposes every tool the client offers."""
    fake = FakeMCPClient(tools={"pubmed_search": object(), "other": object()})
    provider = _make_provider(fake)
    tools_dict, openai_tools = provider.get_tools()

    assert set(tools_dict.keys()) == {"pubmed_search", "other"}
    schema_names = {t["function"]["name"] for t in openai_tools}
    assert schema_names == {"pubmed_search", "other"}
    assert fake.get_tools_calls == [None]


def test_get_tools_empty_whitelist_adds_no_tools() -> None:
    """An empty whitelist still calls the client but filters everything out."""
    fake = FakeMCPClient(tools={"pubmed_search": object()})
    provider = _make_provider(fake)
    tools_dict, _ = provider.get_tools(mcp_whitelist=[])

    assert fake.get_tools_calls == [[]]
    assert tools_dict == {}


def test_get_tools_whitelist_forwarded_to_client() -> None:
    """The whitelist is forwarded verbatim to the MCP client."""
    fake = FakeMCPClient(tools={"pubmed_search": object(), "other": object()})
    provider = _make_provider(fake)
    provider.get_tools(mcp_whitelist=["pubmed_search"])

    assert fake.get_tools_calls == [["pubmed_search"]]


# --- execute_tool_call ------------------------------------------------------


async def test_execute_delegates_known_tool_to_client() -> None:
    """A known tool call is delegated to the MCP client's executor."""
    fake = FakeMCPClient(tools={"pubmed_search": object()})
    provider = _make_provider(fake)
    provider.get_tools(mcp_whitelist=["pubmed_search"])

    tool_call = _make_tool_call("pubmed_search",
                                json.dumps({"query": "cancer"}),
                                call_id="call-mcp")
    result = await provider.execute_tool_call(tool_call)

    assert fake.executed == [tool_call]
    assert result["name"] == "pubmed_search"
    assert result["tool_call_id"] == "call-mcp"
    assert result["content"] == "mcp-result"


async def test_execute_unknown_tool_returns_error_response() -> None:
    """An unlisted tool name yields an error tool-response, not a raise."""
    provider = _make_provider(FakeMCPClient())
    # No get_tools call, so no tool names are tracked.
    tool_call = _make_tool_call("nope_tool", "{}", call_id="call-x")
    result = await provider.execute_tool_call(tool_call)

    assert result["role"] == "tool"
    assert result["name"] == "nope_tool"
    assert result["tool_call_id"] == "call-x"
    payload = json.loads(result["content"])
    assert payload["error"] == "unknown tool: nope_tool"


async def test_execute_client_failure_returns_error_response() -> None:
    """An exception from the MCP client surfaces as an error response."""
    fake = FailingMCPClient(tools={"pubmed_search": object()})
    provider = _make_provider(fake)
    provider.get_tools(mcp_whitelist=["pubmed_search"])

    tool_call = _make_tool_call("pubmed_search", "{}")
    result = await provider.execute_tool_call(tool_call)

    payload = json.loads(result["content"])
    assert "tool execution failed" in payload["error"]
    assert "server unavailable" in payload["error"]


async def test_execute_known_tool_without_client_errors() -> None:
    """A tracked tool with no client surfaces a ConfigError response."""
    fake = FakeMCPClient(tools={"pubmed_search": object()})
    provider = _make_provider(fake)
    provider.get_tools(mcp_whitelist=["pubmed_search"])
    # Drop the client after names are tracked to force the None branch.
    provider.mcp_client = None

    tool_call = _make_tool_call("pubmed_search", "{}")
    result = await provider.execute_tool_call(tool_call)

    payload = json.loads(result["content"])
    assert "tool execution failed" in payload["error"]
    assert "MCP client not configured" in payload["error"]


# --- tracked_executor -------------------------------------------------------


async def test_tracked_executor_counts_calls_per_tool() -> None:
    """The tracked executor counts calls per tool name as it delegates."""
    fake = FakeMCPClient(tools={"pubmed_search": object()})
    provider = _make_provider(fake)
    provider.get_tools(mcp_whitelist=["pubmed_search"])
    executor, counts = provider.tracked_executor("Draft")

    await executor(_make_tool_call("pubmed_search", "{}"))
    await executor(_make_tool_call("pubmed_search", "{}"))

    assert counts == {"pubmed_search": 2}
    assert len(fake.executed) == 2
