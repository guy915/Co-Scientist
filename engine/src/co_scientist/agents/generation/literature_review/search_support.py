"""Search-phase support helpers for the literature review node.

Small, composable functions supporting query generation (Phase 1) and paper
search/collection (Phase 2): the resolved ``SearchConfig`` bundle, search
response normalization, query source-type selection, per-query paper budgets,
and multi-source result merging.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional, cast

if TYPE_CHECKING:
    from co_scientist.config import (
        ToolConfig,
        ToolRegistry,
        WorkflowConfig,
    )

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


def _quoted_field_mapping_source(tool_config: "ToolConfig") -> str | None:
    """Return the literal source name from field_mapping, if present.

    field_mapping["source"] holds a quoted string literal (e.g. "'pubmed'"),
    not a field name to look up - it's how YAML tool config encodes a
    static display label without a dedicated field.
    """
    if not (
        tool_config.response_format
        and tool_config.response_format.field_mapping
    ):
        return None
    source_val = tool_config.response_format.field_mapping.get("source", "")
    if not (source_val.startswith("'") and source_val.endswith("'")):
        return None
    return source_val[1:-1]


def extract_source_name(tool_config: Optional["ToolConfig"]) -> str:
    """Extract source name from tool config's response_format field_mapping."""
    if not tool_config:
        return "unknown"
    literal_source = _quoted_field_mapping_source(tool_config)
    if literal_source is not None:
        return literal_source
    # No literal source mapping configured; fall back to the tool's general
    # source_type (e.g. "academic") as a best-effort label.
    return tool_config.source_type or "unknown"


# =============================================================================
# Response normalization
# =============================================================================


def _resolve_source_id_field(tool_config: "ToolConfig") -> str:
    """Resolve the field to key each paper by.

    "@..." expressions are the field_mapping transform syntax used
    elsewhere; here it just signals "use the source's native id field"
    rather than an actual key to look up on each paper.
    """
    source_id_field = tool_config.response_format.field_mapping.get(
        "source_id", "source_id"
    )
    if source_id_field.startswith("@"):
        return "arxiv_id"
    return source_id_field


def _paper_id_for_rekey(
    paper: Any, source_id_field: str, fallback_index: int
) -> str:
    """Pick a paper's id for re-keying.

    Falls back through the configured field -> arxiv_id -> generic id ->
    positional index, since sources disagree on the id field.
    """
    return cast(
        str,
        paper.get(source_id_field)
        or paper.get("arxiv_id")
        or paper.get("id")
        or str(fallback_index),
    )


def _rekey_list_response_by_id(
    papers: list[Any],
    tool_config: "ToolConfig",
) -> dict[str, Any]:
    """Re-key a list-shaped response (e.g. arXiv) by each paper's id field.

    Falls back through the configured id field -> arxiv_id -> generic id ->
    positional index, since sources disagree on which field holds the id.
    """
    source_id_field = _resolve_source_id_field(tool_config)
    normalized: dict[str, Any] = {}
    for paper in papers:
        paper_id = _paper_id_for_rekey(paper, source_id_field, len(normalized))
        normalized[paper_id] = paper
    return normalized


def _extract_results_path(result_data: Any, results_path: str | None) -> Any:
    """Extract the results collection from a configured nested path.

    Only applies when result_data is still a dict; a results_path of "."
    (or unset) means the response is already the results collection.
    """
    if results_path and results_path != "." and isinstance(result_data, dict):
        return result_data.get(results_path, result_data)
    return result_data


def _normalize_with_response_format(
    result_data: Any,
    tool_config: "ToolConfig",
) -> dict[str, dict[str, Any]]:
    """Normalize a response once a response_format is known to be present."""
    response_format = tool_config.response_format
    result_data = _extract_results_path(
        result_data, response_format.results_path
    )

    # Dict-keyed responses (e.g. PubMed) are already {paper_id: metadata}.
    if response_format.is_dict and isinstance(result_data, dict):
        return result_data

    # List responses (e.g. arXiv) need to be re-keyed by an id field so
    # downstream phases can address papers by a stable paper_id.
    if isinstance(result_data, list):
        return _rekey_list_response_by_id(result_data, tool_config)

    return result_data if isinstance(result_data, dict) else {}


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

    return _normalize_with_response_format(result_data, tool_config)


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


def _collect_enabled_source_types(
    workflow: "WorkflowConfig",
    tool_registry: "ToolRegistry",
) -> list[str]:
    """Collect the source_type of every enabled, resolvable search source."""
    source_types = []
    for source in workflow.get_enabled_search_sources():
        tool_cfg = tool_registry.get_tool(source.tool)
        if tool_cfg:
            source_types.append(tool_cfg.source_type)
    return source_types


def _determine_multi_source_query_type(
    workflow: "WorkflowConfig",
    tool_registry: "ToolRegistry",
) -> str:
    """Determine the query source type across multiple enabled sources."""
    source_types = _collect_enabled_source_types(workflow, tool_registry)

    # A single shared query set is generated for all sources in
    # multi-source mode, so a mix of knowledge_graph and other source
    # types can't be served by one specialized prompt - fall back to
    # generic academic queries rather than picking one source to favor.
    if "knowledge_graph" in source_types and len(source_types) > 1:
        logger.warning(
            "Multi-source mode with knowledge_graph detected. "
            "Using generic queries. For best results, use"
            " per-source query generation."
        )
        return "academic"
    # Only knowledge_graph sources are configured, so it's safe to use
    # the specialized knowledge_graph query-generation prompt.
    if "knowledge_graph" in source_types:
        return "knowledge_graph"
    return "academic"


def _multi_source_type_if_applicable(
    is_multi_source: bool,
    workflow: Optional["WorkflowConfig"],
    tool_registry: Optional["ToolRegistry"],
) -> str | None:
    """Return the multi-source query type, or None if not applicable."""
    if not is_multi_source or not workflow or not tool_registry:
        return None
    return _determine_multi_source_query_type(workflow, tool_registry)


def determine_query_source_type(
    workflow: Optional["WorkflowConfig"],
    tool_registry: Optional["ToolRegistry"],
    search_tool_config: Optional["ToolConfig"],
    is_multi_source: bool,
) -> str:
    """Determine the source type for query generation prompt selection."""
    multi_source_type = _multi_source_type_if_applicable(
        is_multi_source, workflow, tool_registry
    )
    if multi_source_type is not None:
        return multi_source_type

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
            " using 2 minimum",
            total_papers,
            num_queries,
        )

    # remainder is returned so callers can give the first `remainder`
    # queries one extra paper each, evenly distributing the leftovers
    # instead of concentrating them on a single query.
    return papers_per_query, remainder


def _normalize_title(metadata: dict[str, Any]) -> str:
    """Lowercase/strip a paper's title for case-insensitive dedup matching."""
    return str(metadata.get("title") or "").lower().strip()


def _retrieval_score(metadata: dict[str, Any]) -> float:
    """Score source quality, impact, recency, and correction risk."""
    if metadata.get("is_retracted"):
        return -1_000_000.0
    source = str(
        metadata.get("source") or metadata.get("_source_name") or ""
    ).lower()
    source_quality = {
        "pubmed": 3.0,
        "openalex": 2.0,
        "arxiv": 1.0,
    }.get(source, 1.5)
    try:
        citations = max(0, int(metadata.get("cited_by_count") or 0))
    except (TypeError, ValueError):
        citations = 0
    try:
        year = int(metadata.get("year") or 0)
    except (TypeError, ValueError):
        year = 0
    current_year = datetime.now(timezone.utc).year
    recency = max(0.0, 1.0 - max(0, current_year - year) / 20) if year else 0
    return source_quality + min(citations, 1000) / 1000 + recency


def _rank_search_results(
    metadata: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return deterministic best-first metadata with disclosed scores."""
    for item in metadata.values():
        item["retrieval_score"] = round(_retrieval_score(item), 4)
        item["correction_status"] = (
            "retracted" if item.get("is_retracted") else "current"
        )
    return dict(
        sorted(
            metadata.items(),
            key=lambda pair: (
                -float(pair[1]["retrieval_score"]),
                _normalize_title(pair[1]),
                pair[0],
            ),
        )
    )


def _is_duplicate_title(
    metadata: Any,
    deduplicate: bool,
    seen_titles: set[str],
) -> bool:
    """Check and record a paper's title against titles seen so far.

    Case-insensitively dedupes by title across ALL sources' results, since
    the same paper can be indexed under different ids by different sources
    (e.g. PubMed id vs. DOI) and title is the only reliably shared field.
    """
    if not deduplicate or not isinstance(metadata, dict):
        return False
    title = _normalize_title(metadata)
    if not title:
        return False
    if title in seen_titles:
        logger.debug("Skipping duplicate: %s...", title[:60])
        return True
    seen_titles.add(title)
    return False


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
    seen_titles: set[str] = set()

    for source_tool_id, results in source_results:
        for paper_id, metadata in results.items():
            if _is_duplicate_title(metadata, deduplicate, seen_titles):
                continue
            all_paper_metadata[paper_id] = metadata
            # Always record which source-tool each surviving paper came
            # from; later phases (PDF discovery, content fetch) use this
            # map to pick the correct per-source tool config.
            paper_source_map[paper_id] = source_tool_id

    ranked = _rank_search_results(all_paper_metadata)
    ranked_source_map = {
        paper_id: paper_source_map[paper_id] for paper_id in ranked
    }
    return ranked, ranked_source_map
