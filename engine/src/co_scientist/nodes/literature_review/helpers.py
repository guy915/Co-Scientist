"""Literature review helper functions.

Small, composable functions for the literature review node phases:
- Query generation
- Paper search and collection
- PDF discovery and content fetching
- Paper analysis
- Result building
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, cast, Optional, TYPE_CHECKING

from co_scientist.constants import LITERATURE_REVIEW_FAILED
from co_scientist.models import Article
from co_scientist.models import phase_message

if TYPE_CHECKING:
    from co_scientist.config import ToolConfig, WorkflowConfig, ToolRegistry

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration helpers
# =============================================================================


@dataclass
class SearchConfig:
    """Configuration for literature review search."""

    # Resolved once per node run by literature_review._get_search_config and
    # threaded through every phase, so call sites never re-derive config
    # from the raw ToolRegistry/WorkflowConfig repeatedly.
    tool_registry: Optional["ToolRegistry"]
    workflow: Optional["WorkflowConfig"]
    is_multi_source: bool
    search_tool_name: str
    search_tool_config: Optional["ToolConfig"]
    source_name: str
    papers_to_read_count: int
    is_dev_mode: bool


def extract_source_name(tool_config: Optional["ToolConfig"]) -> str:
    """Extract source name from tool config's response_format field_mapping.
    """
    if not tool_config:
        return "unknown"
    if (tool_config.response_format and
            tool_config.response_format.field_mapping):
        source_val = tool_config.response_format.field_mapping.get("source", "")
        # field_mapping["source"] holds a quoted string literal (e.g.
        # "'pubmed'"), not a field name to look up - it's how YAML tool
        # config encodes a static display label without a dedicated field.
        if source_val.startswith("'") and source_val.endswith("'"):
            return source_val[1:-1]
    # No literal source mapping configured; fall back to the tool's general
    # source_type (e.g. "academic") as a best-effort label.
    return tool_config.source_type or "unknown"


# =============================================================================
# Response normalization
# =============================================================================


def _rekey_list_response_by_id(
    papers: list[Any],
    tool_config: "ToolConfig",
) -> dict[str, Any]:
    """Re-key a list-shaped response (e.g. arXiv) by each paper's id field.

    Falls back through the configured id field -> arxiv_id -> generic id ->
    positional index, since sources disagree on which field holds the id.
    """
    source_id_field = tool_config.response_format.field_mapping.get(
        "source_id", "source_id")
    # "@..." expressions are the field_mapping transform syntax used
    # elsewhere; here it just signals "use the source's native id field"
    # rather than an actual key to look up on each paper.
    if source_id_field.startswith("@"):
        source_id_field = "arxiv_id"

    normalized: dict[str, Any] = {}
    for paper in papers:
        # Fall back through configured field -> arxiv_id -> generic id ->
        # positional index, since sources disagree on the id field.
        paper_id = (paper.get(source_id_field) or paper.get("arxiv_id") or
                    paper.get("id") or str(len(normalized)))
        normalized[paper_id] = paper
    return normalized


def normalize_search_response(
    result_data: Any,
    tool_config: Optional["ToolConfig"],
) -> dict[str, dict[str, Any]]:
    """Normalize search tool response to standard {paper_id: metadata} format.

    Handles both dict responses (PubMed-style) and list responses (arXiv-style).
    """
    if not isinstance(result_data, (dict, list)):
        return {}

    # No config to interpret the shape; only a dict response can be trusted
    # as already being in {paper_id: metadata} form.
    if not tool_config or not tool_config.response_format:
        return result_data if isinstance(result_data, dict) else {}

    results_path = tool_config.response_format.results_path
    is_dict = tool_config.response_format.is_dict

    # Extract results from nested path
    if results_path and results_path != ".":
        if isinstance(result_data, dict):
            result_data = result_data.get(results_path, result_data)

    # Dict-keyed responses (e.g. PubMed) are already {paper_id: metadata}.
    if is_dict and isinstance(result_data, dict):
        return result_data

    # List responses (e.g. arXiv) need to be re-keyed by an id field so
    # downstream phases can address papers by a stable paper_id.
    if isinstance(result_data, list):
        return _rekey_list_response_by_id(result_data, tool_config)

    return result_data if isinstance(result_data, dict) else {}


# =============================================================================
# Article building
# =============================================================================


def build_article_from_metadata(
    paper_id: str,
    metadata: dict[str, Any],
    source_name: str = "pubmed",
    used_in_analysis: bool = True,
) -> Article:
    """Build an Article object from MCP response metadata."""
    year = parse_year_from_metadata(metadata)
    url = _build_article_url(paper_id, metadata, source_name)

    # content/pdf_links are unused in PubMed-only mode (fulltext is read
    # directly from files by an external tool); they're still populated
    # here for sources/modes that do rely on them.
    return Article(
        title=metadata.get("title", "unknown"),
        url=url,
        authors=metadata.get("authors", []),
        year=year,
        venue=metadata.get("publication") or metadata.get("venue"),
        citations=0,
        abstract=metadata.get("abstract"),
        content=metadata.get("fulltext"),
        source_id=paper_id,
        source=source_name,
        pdf_links=[],
        used_in_analysis=used_in_analysis,
    )


def parse_year_from_metadata(metadata: dict[str, Any]) -> int | None:
    """Parse year from metadata, handling multiple formats."""
    # Preferred: a direct numeric/string "year" field.
    if "year" in metadata and metadata["year"]:
        try:
            return int(metadata["year"])
        except (ValueError, TypeError):
            pass

    # Fallback for sources (e.g. PubMed) that only expose a revision date
    # like "YYYY/MM/DD"; take the leading year component.
    if "date_revised" in metadata:
        try:
            year_str = metadata["date_revised"].split("/")[0]
            return int(year_str)
        except (ValueError, KeyError, IndexError, AttributeError):
            pass

    return None


def _build_article_url(paper_id: str, metadata: dict[str, Any],
                       source_name: str) -> str:
    """Build URL for article, using metadata URL or constructing default."""
    # Prefer a URL the tool already supplied.
    url = metadata.get("url")
    if url:
        return cast(str, url)

    # PubMed ids map directly to a canonical article URL.
    if source_name == "pubmed":
        return f"https://pubmed.ncbi.nlm.nih.gov/{paper_id}/"

    # Bare DOIs (e.g. "10.1234/...") resolve via doi.org.
    if paper_id.startswith("10."):
        return f"https://doi.org/{paper_id}"

    # Last resort: use the raw id as-is (may not be a valid URL).
    return paper_id


def build_articles_from_metadata(
    all_paper_metadata: dict[str, dict[str, Any]],
    default_source_name: str,
) -> list[Article]:
    """Build Article objects from collected paper metadata."""
    articles = []
    for paper_id, metadata in all_paper_metadata.items():
        if isinstance(metadata, dict):
            # "_source_name" is stamped onto each paper's metadata during
            # multi-source collection (see literature_review.py's
            # _search_single_source) so per-paper provenance survives the
            # merge into a single dict; single-source mode has no such tag
            # and every paper shares default_source_name.
            paper_source = metadata.get("_source_name", default_source_name)
        else:
            paper_source = default_source_name

        articles.append(
            build_article_from_metadata(paper_id,
                                        metadata,
                                        paper_source,
                                        used_in_analysis=True))
    return articles


# =============================================================================
# Fulltext availability
# =============================================================================


def count_papers_with_fulltext(
        all_paper_metadata: dict[str, dict[str, Any]]) -> tuple[int, int]:
    """Count papers with and without fulltext indicators.

    Returns:
        Tuple of (papers_with_fulltext, papers_without_fulltext)
    """
    with_fulltext = 0
    for _, meta in all_paper_metadata.items():
        if not isinstance(meta, dict):
            continue
        # A paper counts as having fulltext if ANY of these indicator
        # fields is set - different sources/tools populate different
        # fields, so this is a union check rather than one canonical field.
        if (meta.get("pmc_full_text_id") or meta.get("fulltext") or
                meta.get("has_fulltext") or meta.get("pdf_url")):
            with_fulltext += 1

    without_fulltext = len(all_paper_metadata) - with_fulltext
    return with_fulltext, without_fulltext


def get_papers_with_content(
    all_paper_metadata: dict[str, dict[str,
                                       Any]],) -> dict[str, dict[str, Any]]:
    """Get papers that have content available for analysis.

    Papers with fulltext are preferred. Papers with pdf_url and abstract
    can use abstract as fallback.
    """
    papers_with_content = {}
    for pid, metadata in all_paper_metadata.items():
        if not isinstance(metadata, dict):
            continue
        # Fulltext is always preferred when available.
        if metadata.get("fulltext"):
            papers_with_content[pid] = metadata
        # Otherwise, a paper with a discovered pdf_url but no downloaded
        # fulltext can still be analyzed using its abstract as a fallback
        # rather than being dropped from analysis entirely.
        elif metadata.get("pdf_url") and metadata.get("abstract"):
            papers_with_content[pid] = metadata
            logger.debug(
                "Paper %s: using abstract for analysis"
                " (fulltext not downloaded)", pid)
    return papers_with_content


# =============================================================================
# Result builders
# =============================================================================


def make_failure_result(
    reason: str,
    queries: list[str] | None = None,
    articles: list[Article] | None = None,
) -> dict[str, Any]:
    """Create a failure result dict for early returns."""
    # The LITERATURE_REVIEW_FAILED sentinel is what downstream generation
    # nodes check in articles_with_reasoning to decide whether literature
    # review usably succeeded (as opposed to inspecting queries/articles).
    return {
        "articles_with_reasoning":
            LITERATURE_REVIEW_FAILED,
        "literature_review_queries":
            queries or [],
        "articles":
            articles or [],
        "messages":
            phase_message("literature_review",
                          f"literature review failed - {reason}",
                          error=True),
    }


def make_success_result(
    synthesis: str,
    queries: list[str],
    articles: list[Article],
) -> dict[str, Any]:
    """Create a success result dict."""
    return {
        "articles_with_reasoning":
            synthesis,
        "literature_review_queries":
            queries,
        "articles":
            articles,
        "messages":
            phase_message(
                "literature_review",
                f"completed literature review with {len(queries)}"
                f" queries, {len(articles)} articles analyzed"),
    }


# =============================================================================
# Query generation helpers
# =============================================================================


def parse_mcp_query_result(result: Any) -> list[str]:
    """Parse MCP tool result into list of queries."""
    if isinstance(result, str):
        try:
            result_data = json.loads(result)
            # A bare JSON list is a list of queries directly; otherwise
            # expect an object with a "queries" key.
            if isinstance(result_data, list):
                return result_data
            return cast(list[str], result_data.get("queries", []))
        except json.JSONDecodeError:
            return []
    elif isinstance(result, list):
        return result
    return []


def determine_query_source_type(
    workflow: Optional["WorkflowConfig"],
    tool_registry: Optional["ToolRegistry"],
    search_tool_config: Optional["ToolConfig"],
    is_multi_source: bool,
) -> str:
    """Determine the source type for query generation prompt selection."""
    if is_multi_source and workflow and tool_registry:
        source_types = []
        for source in workflow.get_enabled_search_sources():
            tool_cfg = tool_registry.get_tool(source.tool)
            if tool_cfg:
                source_types.append(tool_cfg.source_type)

        # A single shared query set is generated for all sources in
        # multi-source mode, so a mix of knowledge_graph and other source
        # types can't be served by one specialized prompt - fall back to
        # generic academic queries rather than picking one source to favor.
        if "knowledge_graph" in source_types and len(source_types) > 1:
            logger.warning("Multi-source mode with knowledge_graph detected. "
                           "Using generic queries. For best results, use"
                           " per-source query generation.")
            return "academic"
        # Only knowledge_graph sources are configured, so it's safe to use
        # the specialized knowledge_graph query-generation prompt.
        elif "knowledge_graph" in source_types:
            return "knowledge_graph"
        return "academic"

    if search_tool_config:
        return search_tool_config.source_type or "academic"

    return "academic"


# =============================================================================
# Search helpers
# =============================================================================


def calculate_papers_per_query(
    total_papers: int,
    num_queries: int,
) -> tuple[int, int]:
    """Calculate papers per query with remainder distribution.

    Returns:
        Tuple of (papers_per_query, remainder)
    """
    papers_per_query = total_papers // num_queries
    remainder = total_papers % num_queries

    # Enforce a floor of 2 papers/query even if the requested total would
    # imply fewer per query; too few results per query risks a thin,
    # unrepresentative literature sample for that query.
    if papers_per_query < 2:
        papers_per_query = 2
        logger.warning(
            "Target %s papers with %s queries gives <2 per query,"
            " using 2 minimum", total_papers, num_queries)

    # remainder is returned so callers can give the first `remainder`
    # queries one extra paper each, evenly distributing the leftovers
    # instead of concentrating them on a single query.
    return papers_per_query, remainder


def merge_search_results(
    source_results: list[tuple[str, dict[str, dict[str, Any]]]],
    deduplicate: bool = True,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Merge results from multiple sources.

    Args:
        source_results: List of (source_tool_id, results_dict) tuples
        deduplicate: Whether to deduplicate by title

    Returns:
        Tuple of (merged_metadata, paper_source_map)
    """
    all_paper_metadata: dict[str, dict[str, Any]] = {}
    paper_source_map: dict[str, str] = {}
    # Case-insensitively dedupes by title across ALL sources' results, since
    # the same paper can be indexed under different ids by different
    # sources (e.g. PubMed id vs. DOI) and title is the only reliably
    # shared field.
    seen_titles: set[str] = set()

    for source_tool_id, results in source_results:
        for paper_id, metadata in results.items():
            if deduplicate and isinstance(metadata, dict):
                title = (metadata.get("title") or "").lower().strip()
                if title and title in seen_titles:
                    logger.debug("Skipping duplicate: %s...", title[:60])
                    continue
                if title:
                    seen_titles.add(title)

            all_paper_metadata[paper_id] = metadata
            # Always record which source-tool each surviving paper came
            # from; later phases (PDF discovery, content fetch) use this
            # map to pick the correct per-source tool config.
            paper_source_map[paper_id] = source_tool_id

    return all_paper_metadata, paper_source_map


# =============================================================================
# PDF discovery helpers
# =============================================================================


def build_pdf_discovery_config(
    workflow: Optional["WorkflowConfig"],
    tool_registry: Optional["ToolRegistry"],
    is_multi_source: bool,
) -> dict[str, tuple[str, str]]:
    """Build PDF discovery configuration mapping.

    Returns:
        Dict mapping source_tool_id -> (mcp_tool_name, url_field)
    """
    config: dict[str, tuple[str, str]] = {}

    if is_multi_source and workflow and tool_registry:
        # Per-source keys let get_papers_needing_pdf_discovery route each
        # paper to the tool/field for the source it came from (via
        # paper_source_map), since sources can have different landing-page
        # layouts.
        for source in workflow.get_enabled_search_sources():
            # A source-level override wins; otherwise fall back to the
            # workflow-level default discovery tool/field.
            discovery_tool = source.pdf_discovery_tool or (
                workflow.pdf_discovery_tool if workflow else None)
            discovery_url_field = source.pdf_discovery_url_field or (
                workflow.pdf_discovery_url_field if workflow else "url")
            if discovery_tool:
                tool_cfg = tool_registry.get_tool(discovery_tool)
                if tool_cfg:
                    config[source.tool] = (tool_cfg.mcp_tool_name,
                                           discovery_url_field)

    elif tool_registry and workflow and workflow.pdf_discovery_tool:
        # Single-source mode: one default entry under the "_default" key.
        tool_cfg = tool_registry.get_tool(workflow.pdf_discovery_tool)
        if tool_cfg:
            config["_default"] = (tool_cfg.mcp_tool_name,
                                  workflow.pdf_discovery_url_field)

    return config


def get_papers_needing_pdf_discovery(
    all_paper_metadata: dict[str, dict[str, Any]],
    paper_source_map: dict[str, str],
    pdf_discovery_config: dict[str, tuple[str, str]],
) -> list[tuple[str, dict[str, Any], str, str]]:
    """Identify papers that need PDF discovery.

    Returns:
        List of (paper_id, metadata, tool_name, url_field) tuples
    """
    papers = []
    for pid, meta in all_paper_metadata.items():
        # Skip papers that already have a pdf_url - nothing to discover.
        if not isinstance(meta, dict) or meta.get("pdf_url"):
            continue

        # Look up the discovery config for the paper's originating source
        # (recorded by merge_search_results), falling back to a single
        # default config in single-source mode.
        source_tool_id = paper_source_map.get(pid, "_default")
        config = pdf_discovery_config.get(
            source_tool_id) or pdf_discovery_config.get("_default")
        if not config:
            continue

        tool_name, url_field = config
        landing_url = meta.get(url_field)
        # Only queue papers that actually have a source URL to discover
        # PDF links from.
        if landing_url:
            papers.append((pid, meta, tool_name, url_field))

    return papers


def parse_pdf_discovery_result(result: Any) -> str | None:
    """Parse PDF discovery result to extract PDF URL."""
    # Defensive parsing: different MCP tools serialize their PDF-discovery
    # results differently (raw JSON string, parsed dict/list, or a bare
    # URL string), so every shape is handled explicitly.
    if isinstance(result, str):
        try:
            result_data = json.loads(result)
            if isinstance(result_data, list) and result_data:
                return cast(Optional[str], result_data[0])
            if isinstance(result_data, dict):
                links = result_data.get("pdf_links") or result_data.get(
                    "links") or []
                if links:
                    first_link = links[0]
                    return first_link if isinstance(
                        first_link, str) else first_link.get("url")
        except json.JSONDecodeError:
            # Not JSON at all; treat a bare URL string as the result.
            if result.startswith("http"):
                return result
    elif isinstance(result, list) and result:
        first = result[0]
        return first if isinstance(first, str) else first.get("url")
    return None


# =============================================================================
# Content fetching helpers
# =============================================================================


@dataclass
class ContentToolConfig:
    """Configuration for a content retrieval tool."""

    # Bundles the resolved tool name, which metadata field holds the URL to
    # fetch, and any extra call params, so Phase 2.5 call sites don't
    # re-derive this from the raw WorkflowConfig/SearchSourceConfig per
    # paper.
    mcp_tool_name: str
    url_field: str
    content_params: dict[str, Any]


def build_content_config(
    workflow: Optional["WorkflowConfig"],
    tool_registry: Optional["ToolRegistry"],
    is_multi_source: bool,
) -> dict[str, ContentToolConfig]:
    """Build content retrieval configuration mapping.

    Returns:
        Dict mapping source_tool_id -> ContentToolConfig
    """
    config: dict[str, ContentToolConfig] = {}

    if is_multi_source and workflow and tool_registry:
        workflow_content_tool = workflow.content_tool
        workflow_url_field = workflow.content_url_field
        workflow_content_params = workflow.content_params

        # Same per-source-override-falls-back-to-workflow-default pattern as
        # build_pdf_discovery_config, keyed by source.tool this time so
        # get_papers_needing_content can look it up via paper_source_map.
        for source in workflow.get_enabled_search_sources():
            src_content_tool = source.content_tool or workflow_content_tool
            src_url_field = source.content_url_field or workflow_url_field
            # Merge workflow params with source-specific params (source takes
            # priority)
            src_params = {**workflow_content_params, **source.content_params}

            if src_content_tool:
                tool_cfg = tool_registry.get_tool(src_content_tool)
                if tool_cfg:
                    config[source.tool] = ContentToolConfig(
                        mcp_tool_name=tool_cfg.mcp_tool_name,
                        url_field=src_url_field,
                        content_params=src_params,
                    )

    elif tool_registry and workflow and workflow.content_tool:
        # Single-source mode: one default entry under the "_default" key.
        content_tool_cfg = tool_registry.get_tool(workflow.content_tool)
        if content_tool_cfg:
            config["_default"] = ContentToolConfig(
                mcp_tool_name=content_tool_cfg.mcp_tool_name,
                url_field=workflow.content_url_field,
                content_params=workflow.content_params,
            )

    return config


def get_papers_needing_content(
    all_paper_metadata: dict[str, dict[str, Any]],
    paper_source_map: dict[str, str],
    content_config: dict[str, ContentToolConfig],
) -> list[tuple[str, dict[str, Any], ContentToolConfig]]:
    """Identify papers that need content retrieval.

    Returns:
        List of (paper_id, metadata, content_tool_config) tuples
    """
    papers = []
    for pid, meta in all_paper_metadata.items():
        # Skip papers that already have fulltext - nothing to fetch.
        if not isinstance(meta, dict) or meta.get("fulltext"):
            continue

        source_tool_id = paper_source_map.get(pid, "_default")
        cfg = content_config.get(source_tool_id) or content_config.get(
            "_default")
        if not cfg:
            continue

        content_url = meta.get(cfg.url_field)
        # Only queue papers that have a resolvable URL to fetch content
        # from (typically the pdf_url discovered in Phase 2.4).
        if content_url:
            papers.append((pid, meta, cfg))

    return papers


def parse_content_result(result: Any) -> str | None:
    """Parse content fetch result to extract text content."""
    # As with parse_pdf_discovery_result, different content-fetch tools
    # serialize differently, so each shape is handled explicitly.
    if isinstance(result, str):
        try:
            result_data = json.loads(result)
            return result_data.get("content") or result_data.get(
                "text") or result
        except json.JSONDecodeError:
            # Not JSON; treat the raw string itself as the content.
            return result
    elif isinstance(result, dict):
        return result.get("content") or result.get("text") or str(result)
    return str(result) if result else None


# =============================================================================
# Paper analysis helpers
# =============================================================================


def get_paper_content_for_analysis(metadata: dict[str, Any],
                                   max_chars: int = 200_000) -> str:
    """Get paper content for analysis, with truncation if needed."""
    # Fulltext is preferred; abstract is the fallback when fulltext wasn't
    # fetched (mirrors the policy in get_papers_with_content).
    content = str(metadata.get("fulltext") or metadata.get("abstract") or "")
    # Bound the input size to the paper-analysis LLM call regardless of how
    # long the source fulltext is.
    if len(content) > max_chars:
        logger.debug("Truncating paper content to %s chars", max_chars)
        content = content[:max_chars] + "\n\n[... truncated for length ...]"
    return content
