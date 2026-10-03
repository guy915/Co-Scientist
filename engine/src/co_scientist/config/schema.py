"""YAML schemas for MCP servers, tools, workflows, prompts and enrichments.

Unknown fields are ignored; absent fields use dataclass defaults. ToolsConfig
parses the registry overlay into one typed configuration tree.
"""

import datetime
import re
from dataclasses import dataclass, field, fields
from typing import Any


def _declared_field_kwargs(
    cls: type[Any],
    data: dict[str, Any] | None,
    *,
    exclude: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build constructor kwargs from keys in data that are declared fields.

    Keys absent from ``data`` are omitted so the dataclass declaration
    remains the single source of truth for defaults. Keys not matching a
    declared field are ignored (unknown YAML keys are tolerated). A key
    present with an explicit ``null`` value is forwarded as ``None``,
    matching the legacy ``data.get(key, default)`` semantics where presence
    wins over the default.

    ``data`` may also be None: a YAML section written with an empty body
    (``prompts:``) parses to None rather than to ``{}``, and every caller
    used to guard for that itself with an ``if not data: return cls()``
    line that meant exactly "all defaults" -- which is what an empty kwargs
    mapping already produces.

    Args:
        cls: Dataclass whose declared fields define the accepted keys.
        data: Raw configuration dictionary (typically parsed YAML), or None
            for an absent/empty section.
        exclude: Field names the caller handles explicitly (nested
            parsing, renamed keys, or defaults that differ from the
            dataclass declaration).

    Returns:
        Mapping of field name to raw value, suitable for ``cls(**kwargs)``.
    """
    # Field names declared on the dataclass, minus the ones the caller
    # handles itself; only keys matching this set are forwarded.
    names = {f.name for f in fields(cls)} - set(exclude)
    return {key: value for key, value in (data or {}).items() if key in names}


def _tolerant_field_kwargs(
    cls: type[Any],
    data: dict[str, Any],
    required: str,
) -> dict[str, Any]:
    """Build constructor kwargs, defaulting one dataclass-required field.

    Three config dataclasses declare a field with no default -- so it must
    be passed -- while tolerating its absence in YAML. Each stated the
    field name twice (once to ``data.get``, once to ``exclude``) plus the
    same explanatory comment; naming the pattern once keeps the two
    mentions from drifting apart.

    Args:
        cls: Dataclass whose declared fields define the accepted keys.
        data: Raw configuration dictionary (typically parsed YAML).
        required: The field to supply as "" when YAML omits it.

    Returns:
        Mapping of field name to raw value, suitable for ``cls(**kwargs)``.
    """
    return {
        required: data.get(required, ""),
        **_declared_field_kwargs(cls, data, exclude=(required,)),
    }


_PLACEHOLDER_PATTERN = re.compile(r"\{(\w+)\}")


def _substitute_placeholders(
    value: str, context: dict[str, Any], *, preserve_type: bool = True
) -> Any:
    """Resolve known placeholders, preserving whole values when requested."""
    exact = _PLACEHOLDER_PATTERN.fullmatch(value)
    if preserve_type and exact and exact[1] in context:
        return context[exact[1]]
    # Keep the original occurrence order: later replacements may also apply
    # to placeholder text introduced by an earlier context value.
    for name in _PLACEHOLDER_PATTERN.findall(value):
        if name in context:
            value = value.replace(f"{{{name}}}", str(context[name]))
    return value


def resolve_content_params(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Resolve ``{name}`` references in string parameters and list items.

    Args:
        params: Tool content parameters containing optional placeholders.
        context: Runtime values keyed by placeholder name.

    Returns:
        Resolved parameters. Unknown placeholders stay literal; a parameter
        consisting of exactly one known placeholder retains its value type.
    """
    if not params:
        return {}
    resolved: dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, str):
            resolved[key] = _substitute_placeholders(value, context)
        elif isinstance(value, list):
            resolved[key] = [
                _substitute_placeholders(item, context, preserve_type=False)
                if isinstance(item, str)
                else item
                for item in value
            ]
        else:
            resolved[key] = value
    return resolved


@dataclass
class ServerConfig:
    """Configuration for an MCP server connection."""

    url: str
    transport: str = "streamable_http"
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServerConfig":
        """Create ServerConfig from dictionary."""
        return cls(**_tolerant_field_kwargs(cls, data, "url"))


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
        effects: What the tool does to the world, as tool_effects tokens;
            governs whether it may run concurrently with sibling calls.
            Defaults to the barrier value when absent -- see below.
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
    # What this tool does to the world, as tokens from tool_effects's
    # vocabulary (read/write/append/network/process). Drives whether the
    # tool may run concurrently with its siblings in one model turn. The
    # default is deliberately the most restrictive value rather than the
    # common one: a tool added to YAML without an effects key serializes,
    # which costs latency, instead of running in parallel with a process
    # spawn, which costs correctness. See tool_effects.py.
    effects: list[str] = field(default_factory=lambda: ["write"])
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


@dataclass
class SearchSourceConfig:
    """Configuration for a single search source in multi-source lit review.

    Attributes:
        tool: Tool ID for this search source (e.g., "pubmed_fulltext",
            "arxiv_search")
        papers_per_query: Number of papers to fetch per query from this source
        enabled: Whether this source is enabled
        content_tool: Optional tool to fetch content (overrides workflow-level
            setting)
        content_url_field: Field containing content URL (overrides
            workflow-level setting)
        content_params: Extra parameters to pass to content tool (supports
            {research_goal} substitution)
        pdf_discovery_tool: Optional tool to discover PDF links from landing
            page URL
        pdf_discovery_url_field: Field containing the URL to pass to
            pdf_discovery_tool
        reserved_slots: How many of the evidence budget's slots this source is
            guaranteed, before the rest are filled by retrieval score. Zero
            (the default) leaves selection entirely to score, which is what
            every source wants unless its papers are scored on axes they
            cannot compete on -- a local corpus has no citation count and no
            publication year, so it loses to any indexed paper regardless of
            how well it matches the question.
    """

    tool: str
    papers_per_query: int = 3
    enabled: bool = True
    reserved_slots: int = 0
    content_tool: str | None = None
    content_url_field: str | None = None
    content_params: dict[str, Any] = field(default_factory=dict)
    # Two-step content retrieval: first discover PDF links, then fetch content
    pdf_discovery_tool: str | None = None  # e.g., "find_pdf_links"
    pdf_discovery_url_field: str | None = None  # e.g., "url" (landing page)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | str) -> "SearchSourceConfig":
        """Create SearchSourceConfig from a dictionary or bare tool name."""
        if isinstance(data, str):
            # Simple format: just tool name
            return cls(tool=data)
        return cls(**_tolerant_field_kwargs(cls, data, "tool"))


def _search_source_tool_ids(sources: list["SearchSourceConfig"]) -> list[str]:
    """Collect the search and content tool IDs referenced by sources.

    Args:
        sources: A workflow's configured multi-source search_sources.

    Returns:
        Each source's tool id, followed by its content_tool id when set.
    """
    tool_ids = []
    for source in sources:
        tool_ids.append(source.tool)
        if source.content_tool:
            tool_ids.append(source.content_tool)
    return tool_ids


@dataclass
class WorkflowConfig:
    """Configuration for a workflow phase.

    Defines which tools are available in each phase of hypothesis generation.

    For literature review, supports both single-source (primary_search) and
    multi-source (search_sources) configurations.
    """

    # is_multi_source() below is the branch point literature_review.py uses
    # to pick which of the two field groups (this one or search_sources) to
    # read; only one mode is active per workflow, chosen by whether
    # search_sources is non-empty.
    # Single-source mode (legacy/simple)
    primary_search: str | None = None
    fallback_search: str | None = None
    availability_check: str | None = None

    # Multi-source mode
    search_sources: list[SearchSourceConfig] = field(default_factory=list)
    deduplicate_across_sources: bool = True

    # General tool lists
    search_tools: list[str] = field(default_factory=list)
    read_tools: list[str] = field(default_factory=list)
    utility_tools: list[str] = field(default_factory=list)

    # Knowledge-graph / external context tools called once per workflow phase.
    # Results are injected as background context into the phase's synthesis
    # prompt. Domain-agnostic: any workflow can list tools here; the node checks
    # this field and skips enrichment when the list is empty.
    context_enrichment_tools: list[str] = field(default_factory=list)

    # Query generation via MCP tool (replaces hardcoded prompts)
    query_generation_tool: str | None = None
    # "boolean" for PubMed, "natural_language" for arXiv/Scholar
    query_format: str = "boolean"

    # Content retrieval for sources that don't return fulltext (e.g., arXiv)
    # Can be overridden per-source in search_sources
    content_tool: str | None = None
    content_url_field: str = "pdf_url"
    content_params: dict[str, Any] = field(default_factory=dict)

    # Two-step content retrieval: first discover PDF links from landing page
    # Used for sources like Google Scholar that return landing page URLs, not
    # direct PDFs
    pdf_discovery_tool: str | None = None  # e.g., "find_pdf_links"
    pdf_discovery_url_field: str = "url"  # field containing landing page URL

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowConfig":
        """Create WorkflowConfig from dictionary."""
        # Parse search_sources into nested SearchSourceConfig objects.
        search_sources = [
            SearchSourceConfig.from_dict(source_data)
            for source_data in (data or {}).get("search_sources", [])
        ]

        return cls(
            search_sources=search_sources,
            **_declared_field_kwargs(cls, data, exclude=("search_sources",)),
        )

    def get_enabled_search_sources(self) -> list[SearchSourceConfig]:
        """Get list of enabled search sources."""
        return [s for s in self.search_sources if s.enabled]

    def is_multi_source(self) -> bool:
        """Check if this workflow uses multi-source configuration."""
        return len(self.search_sources) > 0

    def get_all_tools(self) -> list[str]:
        """Get all tool IDs referenced in this workflow."""
        single_tool_fields = (
            self.primary_search,
            self.fallback_search,
            self.availability_check,
            self.query_generation_tool,
            self.content_tool,
        )
        tools = [tool_id for tool_id in single_tool_fields if tool_id]
        tools.extend(_search_source_tool_ids(self.search_sources))
        tools.extend(self.search_tools)
        tools.extend(self.read_tools)
        tools.extend(self.utility_tools)
        tools.extend(self.context_enrichment_tools)
        return tools


@dataclass
class EnrichmentConfig:
    """Configuration for a post-generation enrichment step.

    Each enrichment maps a tool to a hypothesis field, running the tool
    with the hypothesis field value as input and storing results in
    hypothesis.enrichments[output_key].

    Attributes:
        tool: Tool ID from tools section (e.g., "nvd_cve_search")
        input_field: Hypothesis field to use as input (text, explanation,
            etc.)
        output_key: Key in hypothesis.enrichments dict (e.g., "related_cves")
        enabled: Whether this enrichment is enabled
        max_results: Max results to request from the tool
        results_path: Dot-path to extract from response (e.g., "results" to
            unwrap a response wrapper). Empty string means use the full
            response as-is.
        workflow: Which pipeline phase runs this enrichment.
            "generation" (default) = called by the generation coordinator per
            hypothesis. "reflection" = called by the reflection node using
            entity-level lookups; these are skipped by the coordinator's
            general enrichment loop.
    """

    tool: str
    input_field: str = "text"
    output_key: str = ""
    enabled: bool = True
    max_results: int = 10
    results_path: str = ""
    workflow: str = "generation"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EnrichmentConfig":
        """Create EnrichmentConfig from dictionary."""
        return cls(**_tolerant_field_kwargs(cls, data, "tool"))


# Read by prompts/loading.py's _get_domain_variables() via
# ToolRegistry.get_prompts_config() and merged into most node prompt
# variables as the domain_* placeholders referenced below.
@dataclass
class PromptsConfig:
    """Domain-specific prompt customizations via {{domain_*}} placeholders.

    All fields are optional. When absent, placeholders resolve to empty strings
    and prompts behave identically to the defaults.

    Attributes:
        domain_context: Injected at the top of all prompts. Use for role
            framing, terminology mappings, and domain description.
        generation_guidance: Injected into generation prompts. Use for
            domain-specific categories, hypothesis format requirements, and
            output expectations.
        review_guidance: Injected into review and ranking prompts. Use for
            domain-specific evaluation criteria.
        evolution_guidance: Injected into evolution and meta-review prompts.
            Use for domain-specific refinement priorities.
    """

    domain_context: str = ""
    generation_guidance: str = ""
    review_guidance: str = ""
    evolution_guidance: str = ""
    reflection_guidance: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PromptsConfig":
        """Create PromptsConfig from dictionary."""
        return cls(**_declared_field_kwargs(cls, data))


__all__ = [
    "EnrichmentConfig",
    "ParameterConfig",
    "PromptsConfig",
    "ResponseFormat",
    "SearchSourceConfig",
    "ServerConfig",
    "ToolConfig",
    "ToolsConfig",
    "WorkflowConfig",
    "resolve_content_params",
]


# Each parses one top-level tools.yaml section into its nested dataclasses;
# split out of ToolsConfig.from_dict() below so that function reads as a
# sequence of named phases rather than a run of inline loops.
def _parse_servers(data: dict[str, Any]) -> dict[str, ServerConfig]:
    """Parse the top-level ``servers`` section into ServerConfig objects."""
    servers = {}
    for server_id, server_data in data.get("servers", {}).items():
        servers[server_id] = ServerConfig.from_dict(server_data)
    return servers


def _parse_workflows(data: dict[str, Any]) -> dict[str, WorkflowConfig]:
    """Parse the top-level ``workflows`` section into WorkflowConfig objects."""
    workflows = {}
    for workflow_id, workflow_data in data.get("workflows", {}).items():
        workflows[workflow_id] = WorkflowConfig.from_dict(workflow_data)
    return workflows


def _parse_tools_by_category(
    data: dict[str, Any],
) -> dict[str, dict[str, ToolConfig]]:
    """Parse the top-level ``tools`` section, keyed by category then id."""
    tools: dict[str, dict[str, ToolConfig]] = {}
    tools_data = data.get("tools", {})
    for category, category_tools in tools_data.items():
        tools[category] = {}
        for tool_id, tool_data in category_tools.items():
            tools[category][tool_id] = ToolConfig.from_dict(tool_data, tool_id)
    return tools


@dataclass
class ToolsConfig:
    """Root configuration object containing all tool definitions.

    This is the top-level structure parsed from tools.yaml.
    """

    # tools is keyed first by category (e.g. search_tools, read_tools,
    # utility_tools, matching the top-level grouping in tools.yaml) and then
    # by tool id, so a tool id must be unique across categories for
    # get_tool()/get_all_tools() below to resolve it unambiguously.
    version: str = "1.0"
    servers: dict[str, ServerConfig] = field(default_factory=dict)
    tools: dict[str, dict[str, ToolConfig]] = field(default_factory=dict)
    workflows: dict[str, WorkflowConfig] = field(default_factory=dict)
    prompts: PromptsConfig = field(default_factory=PromptsConfig)
    enrichments: list[EnrichmentConfig] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolsConfig":
        """Create ToolsConfig from dictionary (parsed YAML)."""
        servers = _parse_servers(data)
        tools = _parse_tools_by_category(data)
        workflows = _parse_workflows(data)
        prompts = PromptsConfig.from_dict(data.get("prompts", {}))
        enrichments = [
            EnrichmentConfig.from_dict(e) for e in data.get("enrichments", [])
        ]

        # Every section above is parsed into nested dataclasses; only plain
        # scalar fields (currently just version) go through the generic path.
        # The YAML settings section is read from the raw dict by the registry
        # (merge_strategy), so it has no parsed counterpart here.
        kwargs = _declared_field_kwargs(
            cls,
            data,
            exclude=(
                "servers",
                "tools",
                "workflows",
                "settings",
                "prompts",
                "enrichments",
            ),
        )
        return cls(
            servers=servers,
            tools=tools,
            workflows=workflows,
            prompts=prompts,
            enrichments=enrichments,
            **kwargs,
        )

    def get_tool(self, tool_id: str) -> ToolConfig | None:
        """Get a tool config by ID, searching all categories."""
        for category_tools in self.tools.values():
            if tool_id in category_tools:
                return category_tools[tool_id]
        return None

    def get_all_tools(self) -> dict[str, ToolConfig]:
        """Get all tools as a flat dict."""
        all_tools = {}
        for category_tools in self.tools.values():
            all_tools.update(category_tools)
        return all_tools

    def get_enabled_tools(self) -> dict[str, ToolConfig]:
        """Get all enabled tools as a flat dict."""
        return {
            tool_id: tool
            for tool_id, tool in self.get_all_tools().items()
            if tool.enabled
        }
