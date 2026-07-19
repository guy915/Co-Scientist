"""Schema dataclasses for workflows, enrichments, and prompt overrides.

Each dataclass mirrors one entry shape in the ``workflows``,
``enrichments``, or ``prompts`` sections of tools.yaml and exposes a
``from_dict()`` classmethod that turns a raw parsed-YAML dict into the
dataclass, filling in defaults for absent keys and silently dropping
unrecognized ones.
"""

from dataclasses import dataclass, field
from typing import Any

from co_scientist.config.schema_fields import _declared_field_kwargs


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
        # tool is required on the dataclass but tolerated as missing in YAML.
        return cls(
            tool=data.get("tool", ""),
            **_declared_field_kwargs(cls, data, exclude=("tool",)),
        )


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
        if not data:
            return cls()

        # Parse search_sources into nested SearchSourceConfig objects.
        search_sources = [
            SearchSourceConfig.from_dict(source_data)
            for source_data in data.get("search_sources", [])
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
        # tool is required on the dataclass but tolerated as missing in YAML.
        return cls(
            tool=data.get("tool", ""),
            **_declared_field_kwargs(cls, data, exclude=("tool",)),
        )


# Read by prompts.py's _get_domain_variables() via
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
        if not data:
            return cls()
        return cls(**_declared_field_kwargs(cls, data))
