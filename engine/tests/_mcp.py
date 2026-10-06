from __future__ import annotations

import types
from typing import Any, ClassVar, cast

import pytest
from langchain_core.tools import StructuredTool

from co_scientist.config.schema import ToolConfig
from co_scientist.offline import llm as offline_llm
from tests._llm_fake import restore_backend_at_teardown


def string_tool(name: str, result: Any) -> StructuredTool:

    async def _impl(**_: Any) -> Any:
        return result

    return StructuredTool.from_function(
        coroutine=_impl,
        name=name,
        description=f"fake tool {name}",
    )


class FakeCallToolClient:
    def __init__(
        self, response: Any = None, error: Exception | None = None
    ) -> None:
        self._response = response
        self._error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        self.calls.append((tool_name, kwargs))
        if self._error is not None:
            raise self._error
        return self._response


class FakeToolResultsClient:
    def __init__(
        self,
        results: dict[str, Any] | None = None,
        available_tools: set[str] | None = None,
        error_tools: set[str] | None = None,
    ) -> None:
        self._results = results or {}
        self._available_tools = available_tools
        self._error_tools = error_tools or set()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, **kwargs: Any) -> Any:
        self.calls.append((tool_name, kwargs))
        if tool_name in self._error_tools:
            raise RuntimeError(f"tool failed: {tool_name}")
        return self._results.get(tool_name)

    def has_tool(self, tool_name: str) -> bool:
        if self._available_tools is None:
            return True
        return tool_name in self._available_tools


def make_tool_results_client(
    results: dict[str, Any] | None = None,
    available_tools: set[str] | None = None,
    error_tools: set[str] | None = None,
) -> Any:
    return cast(
        Any,
        FakeToolResultsClient(results, available_tools, error_tools),
    )


def stub_mcp_availability(
    monkeypatch: pytest.MonkeyPatch, *, available: bool
) -> None:
    from co_scientist import mcp_client

    async def fake(**_: Any) -> bool:
        return available

    monkeypatch.setattr(mcp_client, "check_mcp_available", fake)
    monkeypatch.setattr(mcp_client, "check_literature_source_available", fake)


class ToolLookupRegistry:
    def __init__(self, tools: dict[str, Any]) -> None:
        self._tools = tools

    def get_tool(self, tool_id: str) -> Any:
        return self._tools.get(tool_id)


def make_tool_lookup_registry(tools: dict[str, Any]) -> Any:
    return cast(Any, ToolLookupRegistry(tools))


class WorkflowToolRegistry:
    def __init__(
        self,
        tool_ids: list[str],
        mcp_names: list[str],
        raise_on_workflow: bool = False,
        source_type: str = "knowledge_graph",
        tool_mcp_names: dict[str, str] | None = None,
    ) -> None:
        self._tool_ids = tool_ids
        self._mcp_names = mcp_names
        self._raise_on_workflow = raise_on_workflow
        self._source_type = source_type
        self._tool_mcp_names = tool_mcp_names or {}

    def get_tool(self, tool_id: str) -> ToolConfig:
        return ToolConfig(
            server="default_pubmed",
            mcp_tool_name=self._tool_mcp_names.get(tool_id, tool_id),
            source_type=self._source_type,
        )

    def get_tools_for_workflow(self, workflow_name: str) -> list[str]:
        del workflow_name
        if self._raise_on_workflow:
            raise RuntimeError("boom")
        return self._tool_ids

    def get_mcp_tool_names(self, tool_ids: list[str]) -> list[str]:
        names = dict(zip(self._tool_ids, self._mcp_names, strict=False))
        return [names[tool_id] for tool_id in tool_ids if tool_id in names]


class FakeToolRegistry:
    def __init__(
        self,
        *,
        availability_check: str | None = "check_avail",
        availability_check_present: bool = True,
        check_mcp_tool_name: str = "check_pubmed_available",
        mcp_name_to_server: dict[str, str] | None = None,
    ) -> None:
        self._availability_check = availability_check
        self._availability_check_present = availability_check_present
        self._check_mcp_tool_name = check_mcp_tool_name
        self._mcp_name_to_server = mcp_name_to_server or {}

    def get_server_configs_for_langchain(self) -> dict[str, dict[str, str]]:
        return {
            "default": {
                "transport": "streamable_http",
                "url": "http://registry.test/mcp",
            }
        }

    def get_enabled_servers(self) -> dict[str, Any]:
        return {"default": object()}

    def get_workflow(self, name: str) -> Any:
        if name != "literature_review":
            return None
        return types.SimpleNamespace(
            availability_check=self._availability_check
        )

    def get_tool(self, tool_id: str) -> Any:
        if tool_id == self._availability_check and (
            self._availability_check_present
        ):
            return types.SimpleNamespace(
                mcp_tool_name=self._check_mcp_tool_name
            )
        return None

    def get_tool_by_mcp_name(self, mcp_tool_name: str) -> Any:
        server = self._mcp_name_to_server.get(mcp_tool_name)
        if server is None:
            return None
        return types.SimpleNamespace(server=server)


class FakeMultiServerMCPClient:
    instances_created = 0
    tools: ClassVar[list[StructuredTool]] = []
    error: Exception | None = None

    def __init__(self, connections: Any) -> None:
        type(self).instances_created += 1
        self.connections = connections

    async def get_tools(self) -> list[StructuredTool]:
        err = type(self).error
        if err is not None:
            raise err
        return list(type(self).tools)


def make_tool_call(name: str, arguments: str, call_id: str = "call-1") -> Any:
    return types.SimpleNamespace(
        id=call_id,
        function=types.SimpleNamespace(name=name, arguments=arguments),
    )


def make_registry(**kwargs: Any) -> Any:
    return cast(Any, FakeToolRegistry(**kwargs))


def isolate_offline_router(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore the process-wide backend and idempotency flag so later tests
    start fresh."""
    restore_backend_at_teardown(monkeypatch)
    monkeypatch.setattr(offline_llm, "_installed", False)
