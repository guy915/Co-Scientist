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
"""Hybrid tool provider for unified access to MCP and Python tools.

Provides composition pattern wrapping MCPToolClient and PythonToolRegistry.
"""
# pylint: disable=inconsistent-quotes

import json
import logging
from typing import Any

from co_scientist.exceptions import ConfigError, ToolError
from co_scientist.mcp_client import MCPToolClient
from co_scientist.tools.registry import PythonToolRegistry

logger = logging.getLogger(__name__)


class HybridToolProvider:
    """Unified interface for MCP and Python tools.

    Routes tool calls to appropriate executor based on tool source.

    example usage:
        provider = HybridToolProvider(
            mcp_client=mcp_client,
            python_registry=literature_tools
        )

        tools_dict, openai_tools = provider.get_tools(
            mcp_whitelist=["pubmed_search_with_fulltext"],
            python_whitelist=["rank_papers_by_quality"]
        )

        result = await provider.execute_tool_call(tool_call)
    """

    def __init__(
        self,
        mcp_client: MCPToolClient | None = None,
        python_registry: PythonToolRegistry | None = None,
    ):
        """Initialize hybrid tool provider.

        Args:
            mcp_client: optional MCP client for MCP tools
            python_registry: optional Python tool registry
        """
        self.mcp_client = mcp_client
        self.python_registry = python_registry

        # track tool sources for routing
        self._tool_sources: dict[str, str] = {}  # tool_name → "mcp" or "python"

    def get_tools(
        self,
        mcp_whitelist: list[str] | None = None,
        python_whitelist: list[str] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Get merged tools from MCP and Python sources.

        Args:
            mcp_whitelist: optional list of MCP tool names to include
            python_whitelist: optional list of Python tool names to include

        Returns:
            tuple of (tools_dict, openai_tools_list)
            tools_dict is combined {tool_name: tool_object} for both sources
            openai_tools_list is combined list of OpenAI-format tools
        """
        merged_tools_dict = {}
        merged_openai_tools = []

        # get MCP tools
        if self.mcp_client is not None and mcp_whitelist is not None:
            try:
                mcp_tools_dict, mcp_openai_tools = self.mcp_client.get_tools(
                    whitelist=mcp_whitelist)

                # track tool sources
                for tool_name in mcp_tools_dict.keys():
                    self._tool_sources[tool_name] = "mcp"

                merged_tools_dict.update(mcp_tools_dict)
                merged_openai_tools.extend(mcp_openai_tools)

                logger.debug("added %s MCP tools", len(mcp_tools_dict))
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Failed to get MCP tools: %s", e)

        # get Python tools
        if self.python_registry is not None and python_whitelist is not None:
            try:
                python_functions, python_openai_tools = (
                    self.python_registry.get_tools(whitelist=python_whitelist))

                # track tool sources
                for tool_name in python_functions.keys():
                    self._tool_sources[tool_name] = "python"

                # Python tools stored as functions, not tool objects
                # store them in merged dict for tracking
                merged_tools_dict.update(python_functions)
                merged_openai_tools.extend(python_openai_tools)

                logger.debug("added %s Python tools", len(python_functions))
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Failed to get Python tools: %s", e)

        logger.info(
            "hybrid provider ready: %s total tools (%s MCP, %s Python)",
            len(merged_tools_dict),
            len([s for s in self._tool_sources.values() if s == 'mcp']),
            len([s for s in self._tool_sources.values() if s == 'python']))

        return merged_tools_dict, merged_openai_tools

    async def execute_tool_call(self, tool_call: Any) -> dict[str, Any]:
        """Execute a tool call by routing to appropriate executor.

        Args:
            tool_call: LiteLLM tool call object with .id, .function.name,
                .function.arguments

        Returns:
            tool response message dict:
                {role: "tool", name: ..., tool_call_id: ..., content: ...}
        """
        tool_name = tool_call.function.name
        tool_call_id = tool_call.id

        # check tool source
        tool_source = self._tool_sources.get(tool_name)

        if tool_source is None:
            error_msg = f"unknown tool: {tool_name}"
            logger.error(error_msg)
            return self._create_error_response(tool_name, tool_call_id,
                                               error_msg)

        # route to appropriate executor
        try:
            if tool_source == "mcp":
                return await self._execute_mcp_tool(tool_call)
            elif tool_source == "python":
                return await self._execute_python_tool(tool_call)
            else:
                error_msg = f"invalid tool source: {tool_source}"
                logger.error(error_msg)
                return self._create_error_response(tool_name, tool_call_id,
                                                   error_msg)

        except Exception as e:  # pylint: disable=broad-exception-caught
            error_msg = f"tool execution failed: {str(e)}"
            logger.error("%s error: %s", tool_name, error_msg)
            return self._create_error_response(tool_name, tool_call_id,
                                               error_msg)

    async def _execute_mcp_tool(self, tool_call: Any) -> dict[str, Any]:
        """Execute MCP tool call.

        Args:
            tool_call: LiteLLM tool call object

        Returns:
            tool response message dict
        """
        if self.mcp_client is None:
            raise ConfigError("MCP client not configured")

        # delegate to MCP client
        return await self.mcp_client.execute_tool_call(tool_call)

    async def _execute_python_tool(self, tool_call: Any) -> dict[str, Any]:
        """Execute Python tool call.

        Args:
            tool_call: LiteLLM tool call object

        Returns:
            tool response message dict
        """
        if self.python_registry is None:
            raise ConfigError("Python registry not configured")

        tool_name = tool_call.function.name
        tool_call_id = tool_call.id

        # get function
        func = self.python_registry.get_function(tool_name)
        if func is None:
            raise ToolError(f"Python function not found: {tool_name}")

        # parse arguments
        try:
            args_dict = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as e:
            raise ToolError(f"invalid JSON arguments: {e}") from e

        logger.debug("calling Python tool: %s with args: %s", tool_name,
                     args_dict)

        # call function
        result = await func(**args_dict)

        # serialize result
        result_json = json.dumps(result)

        # return tool message
        return {
            "role": "tool",
            "name": tool_name,
            "tool_call_id": tool_call_id,
            "content": result_json,
        }

    def _create_error_response(self, tool_name: str, tool_call_id: str,
                               error_msg: str) -> dict[str, Any]:
        """Create error response message for failed tool call.

        Args:
            tool_name: name of tool that failed
            tool_call_id: tool call ID
            error_msg: error message

        Returns:
            tool response message dict with error
        """
        return {
            "role": "tool",
            "name": tool_name,
            "tool_call_id": tool_call_id,
            "content": json.dumps({"error": error_msg}),
        }
