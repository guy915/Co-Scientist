"""Schema dataclasses for MCP servers, tools, and their parameters.

Each dataclass mirrors one entry shape in the ``servers`` or ``tools``
sections of tools.yaml and exposes a ``from_dict()`` classmethod that
turns a raw parsed-YAML dict into the dataclass, filling in defaults for
absent keys and silently dropping unrecognized ones.
"""

import datetime
from dataclasses import dataclass, field
from typing import Any

from co_scientist.config.schema_fields import _declared_field_kwargs


@dataclass
class ServerConfig:
    """Configuration for an MCP server connection."""

    url: str
    transport: str = "streamable_http"
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServerConfig":
        """Create ServerConfig from dictionary."""
        # url is required on the dataclass but tolerated as missing in YAML.
        return cls(
            url=data.get("url", ""),
            **_declared_field_kwargs(cls, data, exclude=("url",)),
        )


# Consumed by tools/response_parser.py's ResponseParser: type/results_path/
# is_dict locate the results in a raw MCP response, and field_mapping's
# expression language (see response_parser.py) builds Article objects.
@dataclass
class ResponseFormat:
    """Configuration for parsing tool responses.

    Attributes:
        type: Response type (json, boolean_string, etc.)
        results_path: JSONPath-like path to results (e.g., "." for root,
            "results" for nested)
        is_dict: Whether results are a dict (True) or list (False)
        field_mapping: Maps Article fields to response fields with optional
            transforms
    """

    type: str = "json"
    results_path: str = "."
    is_dict: bool = False
    field_mapping: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResponseFormat":
        """Create ResponseFormat from dictionary."""
        if not data:
            return cls()
        return cls(**_declared_field_kwargs(cls, data))


@dataclass
class ParameterConfig:
    """Configuration for a tool parameter."""

    # Per-parameter metadata attached to a ToolConfig.parameters entry.
    # type/required/description document the parameter's contract in YAML;
    # default is the value ToolConfig.from_dict() applies when a YAML
    # parameter entry is a bare scalar rather than a nested mapping.
    type: str = "string"
    default: Any | None = None
    required: bool = False
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ParameterConfig":
        """Create ParameterConfig from dictionary."""
        if not data:
            return cls()
        return cls(**_declared_field_kwargs(cls, data))


# Used only by ToolConfig.map_parameters below, for tools whose parameter
# schema expects an absolute starting year rather than a lookback window.
def _recency_years_to_starting_year(value: int) -> int | None:
    """Convert a recency_years lookback window to an absolute starting year.

    Args:
        value: Number of years to look back (e.g., 7).

    Returns:
        The starting year (e.g., 2019 for a 7-year lookback in 2026), or
        None when value is not a positive lookback window.
    """
    current_year = datetime.datetime.now().year
    return current_year - value if value > 0 else None


@dataclass
class ToolConfig:
    """Configuration for an MCP tool.

    Attributes:
        server: Server ID this tool belongs to
        mcp_tool_name: Actual tool name on the MCP server
        display_name: Human-readable name for prompts
        description: Tool description for prompts
        category: Tool category (search, search_with_content, read, utility)
        source_type: Source type for articles (academic, preprint, etc.)
        enabled: Whether this tool is enabled
        response_format: Configuration for parsing responses
        prompt_snippet: Prompt text to include when this tool is available
        parameters: Tool parameter configurations
        parameter_mapping: Maps canonical parameter names to tool-specific
            names
        applies_to: Which sources this tool applies to (for generic tools)
    """

    server: str
    mcp_tool_name: str
    display_name: str = ""
    description: str = ""
    category: str = "utility"
    source_type: str = "academic"
    enabled: bool = True
    response_format: ResponseFormat = field(default_factory=ResponseFormat)
    prompt_snippet: str = ""
    parameters: dict[str, ParameterConfig] = field(default_factory=dict)
    parameter_mapping: dict[str, str | None] = field(default_factory=dict)
    applies_to: str = "all"
    # Internal: yaml tool_id stashed for downstream citation building.
    _yaml_tool_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], tool_id: str = "") -> "ToolConfig":
        """Create ToolConfig from dictionary."""
        # Parse parameters
        params_data = data.get("parameters", {})
        parameters = {}
        for param_name, param_data in params_data.items():
            if isinstance(param_data, dict):
                parameters[param_name] = ParameterConfig.from_dict(param_data)
            else:
                # Simple value (just a default)
                parameters[param_name] = ParameterConfig(default=param_data)

        # Explicitly handled fields: server is required on the dataclass but
        # defaults to "default" in YAML; mcp_tool_name and display_name fall
        # back to the YAML tool id (not the dataclass default); parameters and
        # response_format are parsed into nested dataclasses; _yaml_tool_id is
        # internal and never read from YAML.
        kwargs = _declared_field_kwargs(
            cls,
            data,
            exclude=(
                "server",
                "mcp_tool_name",
                "display_name",
                "response_format",
                "parameters",
                "_yaml_tool_id",
            ),
        )
        return cls(
            server=data.get("server", "default"),
            mcp_tool_name=data.get("mcp_tool_name", tool_id),
            display_name=data.get("display_name", tool_id),
            response_format=ResponseFormat.from_dict(
                data.get("response_format", {})
            ),
            parameters=parameters,
            **kwargs,
        )

    # Called by literature_review.py and validate.py just before invoking an
    # MCP tool, so nodes can build requests in canonical terms while each
    # tool config supplies the translation to that server's actual
    # parameter names.
    def map_parameters(
        self, canonical_params: dict[str, Any]
    ) -> dict[str, Any]:
        """Map canonical parameter names to tool-specific parameter names.

        Args:
            canonical_params: Parameters using canonical names (e.g.,
                max_papers, recency_years)

        Returns:
            Parameters using tool-specific names (e.g., max_results,
            starting_year)
        """
        if not self.parameter_mapping:
            # No mapping configured, return as-is
            return canonical_params

        mapped = {}
        for canonical_name, value in canonical_params.items():
            tool_param_name, mapped_value = self._map_single_parameter(
                canonical_name, value
            )
            if tool_param_name is not None:
                mapped[tool_param_name] = mapped_value

        return mapped

    def _map_single_parameter(
        self, canonical_name: str, value: Any
    ) -> tuple[str | None, Any]:
        """Map one canonical parameter to its tool-specific name and value.

        Args:
            canonical_name: Canonical parameter name (e.g., recency_years).
            value: Value supplied under the canonical name.

        Returns:
            (tool_param_name, mapped_value), or (None, None) when the
            parameter is explicitly ignored (mapped to null in YAML).
        """
        if canonical_name not in self.parameter_mapping:
            # No mapping, use canonical name
            return canonical_name, value

        tool_param_name = self.parameter_mapping[canonical_name]
        if tool_param_name is None:
            # Explicitly ignore this parameter (null in YAML)
            return None, None

        if (
            canonical_name == "recency_years"
            and tool_param_name == "starting_year"
        ):
            return tool_param_name, _recency_years_to_starting_year(value)

        return tool_param_name, value
