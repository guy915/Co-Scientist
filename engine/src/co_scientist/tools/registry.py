"""Python tool registry for registering Python functions as LLM-callable tools.

Provides decorator-based registration with automatic JSON schema generation
from type hints.
"""

import inspect
import logging
from typing import Any, Optional, get_type_hints, get_origin, get_args
from collections.abc import Callable

logger = logging.getLogger(__name__)


class PythonToolRegistry:
    """Registry for Python functions exposed as LLM-callable tools.

    Example usage:
        registry = PythonToolRegistry()

        @registry.register(
            name="my_tool",
            description="does something useful"
        )
        async def my_tool(arg1: str, arg2: int = 0) -> Dict[str, Any]:
            return {"result": f"{arg1} {arg2}"}
    """

    def __init__(self) -> None:
        self._functions: dict[str, Callable[..., Any]] = {}
        self._schemas: dict[str, dict[str, Any]] = {}
        self._openai_tools: list[dict[str, Any]] = []

    def register(
        self,
        name: str | None = None,
        description: str | None = None
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorate and register a Python function as a tool.

        Args:
            name: tool name (defaults to function name)
            description: tool description (defaults to function docstring)

        Returns:
            decorator function
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = name or func.__name__
            tool_description = (description or func.__doc__ or
                                f"call {tool_name}")

            # Generate JSON schema from type hints
            schema = self._generate_schema(func, tool_name, tool_description)

            # Store function and schema
            self._functions[tool_name] = func
            self._schemas[tool_name] = schema

            # Convert to OpenAI format
            openai_tool = {"type": "function", "function": schema}
            self._openai_tools.append(openai_tool)

            logger.debug("registered Python tool: %s", tool_name)

            return func

        return decorator

    def _generate_schema(self, func: Callable[..., Any], name: str,
                         description: str) -> dict[str, Any]:
        """Generate JSON schema from function signature and type hints.

        Args:
            func: function to generate schema for
            name: tool name
            description: tool description

        Returns:
            JSON schema dict
        """
        sig = inspect.signature(func)
        type_hints = get_type_hints(func)

        parameters: dict[str, Any] = {
            "type": "object",
            "properties": {},
            "required": []
        }

        for param_name, param in sig.parameters.items():
            # Get type hint
            param_type = type_hints.get(param_name, Any)

            # Convert to JSON schema type
            param_schema = self._type_to_schema(param_type, param_name)

            # Add to parameters
            parameters["properties"][param_name] = param_schema

            # Add to required if no default
            if param.default == inspect.Parameter.empty:
                parameters["required"].append(param_name)

        schema = {
            "name": name,
            "description": description,
            "parameters": parameters
        }

        return schema

    def _type_to_schema(self, python_type: Any,
                        param_name: str) -> dict[str, Any]:
        """Convert Python type hint to JSON schema.

        supports: str, int, float, bool, List, Dict, Optional

        Args:
            python_type: Python type annotation
            param_name: parameter name (for logging)

        Returns:
            JSON schema dict for the type
        """
        origin = get_origin(python_type)

        # Handle Optional[T] (Union[T, None])
        if origin is type(Optional[str]):  # Union type
            args = get_args(python_type)
            # Filter out None type
            non_none_types = [arg for arg in args if arg is not type(None)]
            if len(non_none_types) == 1:
                # Optional[T] case - recurse on T
                return self._type_to_schema(non_none_types[0], param_name)
            else:
                logger.warning("complex Union type for %s, using string",
                               param_name)
                return {"type": "string"}

        # Handle List[T]
        if origin is list:
            args = get_args(python_type)
            if args:
                item_schema = self._type_to_schema(args[0],
                                                   f"{param_name}_item")
                return {"type": "array", "items": item_schema}
            else:
                return {"type": "array", "items": {"type": "string"}}

        # Handle Dict[K, V]
        if origin is dict:
            return {"type": "object", "additionalProperties": True}

        # Handle basic types
        if python_type == str:
            return {"type": "string"}
        elif python_type == int:
            return {"type": "integer"}
        elif python_type == float:
            return {"type": "number"}
        elif python_type == bool:
            return {"type": "boolean"}
        elif python_type == Any:
            return {"type": "string"}
        else:
            # Default to string for unknown types
            logger.debug("unknown type %s for %s, using string", python_type,
                         param_name)
            return {"type": "string"}

    def get_function(self, name: str) -> Callable[..., Any] | None:
        """Get registered function by name."""
        return self._functions.get(name)

    def get_schema(self, name: str) -> dict[str, Any] | None:
        """Get JSON schema for registered tool by name."""
        return self._schemas.get(name)

    def get_all_functions(self) -> dict[str, Callable[..., Any]]:
        """Get all registered functions."""
        return self._functions.copy()

    def get_all_schemas(self) -> dict[str, dict[str, Any]]:
        """Get all JSON schemas."""
        return self._schemas.copy()

    def get_openai_tools(self) -> list[dict[str, Any]]:
        """Get tools in OpenAI format for LiteLLM."""
        return self._openai_tools.copy()

    def get_tools(
        self,
        whitelist: list[str] | None = None
    ) -> tuple[dict[str, Callable[..., Any]], list[dict[str, Any]]]:
        """Get tools filtered by whitelist.

        Args:
            whitelist: optional list of tool names to include

        Returns:
            tuple of (functions_dict, openai_tools_list)
        """
        if whitelist is None:
            return self.get_all_functions(), self.get_openai_tools()

        # Filter functions
        filtered_functions = {
            name: func
            for name, func in self._functions.items()
            if name in whitelist
        }

        # Filter openai tools
        filtered_openai_tools = [
            tool for tool in self._openai_tools
            if tool["function"]["name"] in whitelist
        ]

        return filtered_functions, filtered_openai_tools
