"""Search-phase support helpers for the literature review node.

Small, composable functions supporting query generation (Phase 1) and paper
search/collection (Phase 2): the resolved ``SearchConfig`` bundle, search
response normalization, query source-type selection, and multi-source result
merging and ranking. The evidence-budget selection that reduces the merged,
ranked results lives in the sibling ``search_budget`` module.

Merging ranks candidates by Reciprocal Rank Fusion over each source's own
result order (see ``_rrf_position_score``), not by a score computed from
each candidate's metadata -- a fixed-weight sum over source quality,
citation count, and recency put every axis on an unrelated scale (source
quality span 2.0 against two axes spanning 1.0 each) and had no query
relevance term at all. Metadata that only some sources carry (a citation
count only OpenAlex reports; web results carry neither citations nor a
year) is exactly what an additive scorer structurally rewards or
penalizes without comparison being meaningful; RRF fuses by rank instead,
so it never needs the axes to be on comparable scales.
"""

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, cast

from co_scientist.agents.generation.literature_review.article_support import (
    _metadata_is_retracted,
)

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
    # Threaded through for the hybrid relevance pass (relevance.py), which
    # needs the goal to judge against and the model to judge with.
    research_goal: str = ""
    model_name: str = ""
    # Whether the merged pool earns the model-judged relevance pass. The
    # pass costs one LLM call per candidate (up to
    # ``papers_to_read_count * 3``), which the run-level review spends
    # once to pick the evidence every later agent reads. Targeted probe
    # retrieval (deep verification, comprehensive reflection, evolution
    # grounding) runs *per hypothesis*, so paying it there multiplied the
    # same re-ranking by the pool size on every cycle -- ~18 calls per
    # idea, in three agents, on top of the one review that already ran.
    # A probe also has least use for it: the model already wrote the
    # query it wants answered, so lexical ranking over those hits is what
    # the probe asked for. Off means lexical-only, never fewer results.
    semantic_relevance_enabled: bool = True


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


def _normalize_title(metadata: dict[str, Any]) -> str:
    """Lowercase/strip a paper's title for case-insensitive dedup matching."""
    return str(metadata.get("title") or "").lower().strip()


# Reciprocal Rank Fusion (Cormack, Clarke & Buettcher 2009), following
# qdrant's implementation (Apache-2.0):
# reciprocal_rank_fusion.rs::position_score. Unlike the additive scorer
# this replaces, RRF ignores every source's raw score entirely -- only a
# candidate's rank position within its own source's result list matters,
# which is what lets sources on incomparable scales (a citation index vs.
# a web search with no citation count at all) fuse without one dominating
# the other by construction. k=2 matches qdrant's DEFAULT_RRF_K.
_RRF_K = 2

# The old additive scorer's source_quality intent, carried forward as a
# per-list RRF weight instead of an additive term on an unrelated scale:
# PubMed (peer-reviewed, curated) outweighs OpenAlex (broad index, has
# citation counts), which outweighs Europe PMC/literature-tier sources
# (mixed peer review), which outweighs preprints/arXiv/web (no editorial
# review, and web carries no citation metadata at all -- the defect this
# table exists to fix). An unrecognized source name earns no special
# trust, so it shares the floor weight.
_SOURCE_RRF_WEIGHTS = {
    "pubmed": 3.0,
    "openalex": 2.0,
    "europepmc": 1.5,
    "literature": 1.5,
    "preprints": 1.0,
    "arxiv": 1.0,
    "web": 1.0,
}
_DEFAULT_SOURCE_RRF_WEIGHT = 1.0


def _source_rrf_weight(metadata: dict[str, Any]) -> float:
    """Resolve a candidate's per-source RRF weight from its tagged source."""
    source = str(
        metadata.get("source") or metadata.get("_source_name") or ""
    ).lower()
    return _SOURCE_RRF_WEIGHTS.get(source, _DEFAULT_SOURCE_RRF_WEIGHT)


def _rrf_position_score(position: int, weight: float) -> float:
    """Score one candidate's rank position in one source's result list.

    ``1 / ((position + 1) / weight + k - 1)``: a higher weight
    "compresses" the position, so a lower-trust source's rank-1 result
    still contributes, just less than a higher-trust source's rank-1
    would.
    """
    if weight <= 0:
        return 0.0
    return 1.0 / ((position + 1) / weight + _RRF_K - 1)


def _normalize_rrf_pool(
    raw_scores: dict[str, float], retracted_ids: set[str]
) -> dict[str, float]:
    """Min-max normalize raw RRF fusion scores onto [0, 1].

    Normalized over the non-retracted candidates only, since a retracted
    candidate's score is set to 0.0 directly and would otherwise skew the
    range for every legitimate candidate. Unlike the old scorer's fixed
    documented range, RRF's raw scale depends on pool size and source
    weights, so there is no fixed range to normalize against -- min/max
    over the pool that was actually fused is the only range available. A
    pool with no spread (one live candidate, or a tie across all of them)
    normalizes to 1.0 rather than dividing by zero.
    """
    live = {
        pid: score
        for pid, score in raw_scores.items()
        if pid not in retracted_ids
    }
    if not live:
        return dict.fromkeys(raw_scores, 0.0)
    lo, hi = min(live.values()), max(live.values())
    span = hi - lo
    normalized: dict[str, float] = {}
    for paper_id, score in raw_scores.items():
        if paper_id in retracted_ids:
            normalized[paper_id] = 0.0
        elif span > 0:
            normalized[paper_id] = round((score - lo) / span, 4)
        else:
            normalized[paper_id] = 1.0
    return normalized


def _rank_search_results(
    metadata: dict[str, dict[str, Any]],
    raw_scores: dict[str, float],
) -> dict[str, dict[str, Any]]:
    """Return deterministic best-first metadata with disclosed scores.

    A retracted candidate always sorts after every non-retracted one,
    regardless of its fused score -- score alone cannot exclude it (a
    thin pool would still admit it), so retraction is a primary sort key
    here, not a score penalty.
    """
    retracted_ids = {
        paper_id
        for paper_id, item in metadata.items()
        if _metadata_is_retracted(item)
    }
    normalized = _normalize_rrf_pool(raw_scores, retracted_ids)
    for paper_id, item in metadata.items():
        item["retrieval_score"] = normalized[paper_id]
        item["correction_status"] = (
            "retracted" if paper_id in retracted_ids else "current"
        )
    return dict(
        sorted(
            metadata.items(),
            key=lambda pair: (
                pair[0] in retracted_ids,
                -float(pair[1]["retrieval_score"]),
                _normalize_title(pair[1]),
                pair[0],
            ),
        )
    )


def _duplicate_owner_id(
    paper_id: str,
    metadata: Any,
    deduplicate: bool,
    seen_titles: dict[str, str],
) -> str | None:
    """Return the earlier paper id this metadata's title duplicates.

    Case-insensitively dedupes by title across ALL sources' results, since
    the same paper can be indexed under different ids by different sources
    (e.g. PubMed id vs. DOI) and title is the only reliably shared field.
    Returns None -- and registers ``paper_id`` as the title's owner -- the
    first time a title is seen, so the caller can still fold a later
    duplicate's own rank into the owner's fused score without letting the
    duplicate's metadata or source provenance overwrite the owner's.
    """
    if not deduplicate or not isinstance(metadata, dict):
        return None
    title = _normalize_title(metadata)
    if not title:
        return None
    owner_id = seen_titles.get(title)
    if owner_id is not None:
        logger.debug(
            "Duplicate title, folding into %s: %s...", owner_id, title[:60]
        )
        return owner_id
    seen_titles[title] = paper_id
    return None


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
    seen_titles: dict[str, str] = {}
    # Each source's own dict is already in that source's rank order (its
    # own relevance ranking); enumerate positions is the whole input RRF
    # needs. A paper found by several sources accumulates one
    # contribution per list, same as qdrant's rrf_scoring -- including a
    # duplicate folded away by title: its rank still counts toward the
    # id it duplicates, which is what lets cross-source agreement (the
    # signal RRF is built to reward) outrank a paper only one source saw.
    raw_rrf_scores: dict[str, float] = {}

    for source_tool_id, results in source_results:
        for position, (paper_id, metadata) in enumerate(results.items()):
            owner_id = _duplicate_owner_id(
                paper_id, metadata, deduplicate, seen_titles
            )
            if owner_id is None:
                all_paper_metadata[paper_id] = metadata
                # Always record which source-tool each surviving paper
                # came from; later phases (PDF discovery, content fetch)
                # use this map to pick the correct per-source tool
                # config. Never overwritten by a later duplicate.
                paper_source_map[paper_id] = source_tool_id
            weight = _source_rrf_weight(metadata)
            target_id = owner_id or paper_id
            raw_rrf_scores[target_id] = raw_rrf_scores.get(
                target_id, 0.0
            ) + _rrf_position_score(position, weight)

    ranked = _rank_search_results(all_paper_metadata, raw_rrf_scores)
    ranked_source_map = {
        paper_id: paper_source_map[paper_id] for paper_id in ranked
    }
    return ranked, ranked_source_map
