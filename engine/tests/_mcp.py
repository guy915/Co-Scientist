"""Shared fakes and builders for the MCP client tests.

The MCP client wrapper's only external dependency is ``MultiServerMCPClient``
from ``langchain_mcp_adapters`` - a network client that talks to a live MCP
server. These helpers provide an in-memory ``FakeMultiServerMCPClient`` (patched
in over the real class by the ``_patch_mcp_seam`` fixture in ``conftest``), a
``FakeToolRegistry`` for the config-driven multi-server path, and small builders
for real ``StructuredTool`` instances and LiteLLM-shaped tool-call objects.
"""

import types
from typing import Any, ClassVar, cast

from langchain_core.tools import StructuredTool

# --- Real tool builders -----------------------------------------------------


def string_tool(name: str, result: Any) -> StructuredTool:
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


# --- Fake MCPToolClient (call_tool duck) ------------------------------------


class FakeCallToolClient:
    """Minimal ``call_tool``-only stand-in for ``MCPToolClient``.

    Records every call and either returns a fixed response or raises a
    configured error, so success and failure paths can be driven without a
    live MCP server.
    """

    def __init__(
        self, response: Any = None, error: Exception | None = None
    ) -> None:
        """Store the response (or error) every ``call_tool`` invocation uses.

        Args:
            response: Value returned by ``call_tool`` when no error is set.
            error: Exception raised by ``call_tool`` instead of returning.
        """
        self._response = response
        self._error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """Record the call and return the response or raise the error."""
        self.calls.append((tool_name, kwargs))
        if self._error is not None:
            raise self._error
        return self._response


# --- Minimal get_tool-only ToolRegistry stub --------------------------------


class ToolLookupRegistry:
    """Minimal ``ToolRegistry`` stand-in exposing only ``get_tool``.

    Resolves a tool id to its configured value via a dict lookup, returning
    None for an unknown id. Used by the literature-review phase/helper tests
    that need nothing more than tool-config resolution.
    """

    def __init__(self, tools: dict[str, Any]) -> None:
        """Store the tool-id -> config map ``get_tool`` resolves."""
        self._tools = tools

    def get_tool(self, tool_id: str) -> Any:
        """Resolve a tool id to its configured value, or None."""
        return self._tools.get(tool_id)


def make_tool_lookup_registry(tools: dict[str, Any]) -> Any:
    """Build a ToolLookupRegistry typed as the ToolRegistry code expects."""
    return cast(Any, ToolLookupRegistry(tools))


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
            availability_check=self._availability_check
        )

    def get_tool(self, tool_id: str) -> Any:
        """Resolve a tool id to a config exposing ``mcp_tool_name``."""
        if tool_id == self._availability_check and (
            self._availability_check_present
        ):
            return types.SimpleNamespace(
                mcp_tool_name=self._check_mcp_tool_name
            )
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
    tools: ClassVar[list[StructuredTool]] = []
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


def make_tool_call(name: str, arguments: str, call_id: str = "call-1") -> Any:
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


def make_registry(**kwargs: Any) -> Any:
    """Build a FakeToolRegistry typed as the ToolRegistry the code expects."""
    return cast(Any, FakeToolRegistry(**kwargs))
