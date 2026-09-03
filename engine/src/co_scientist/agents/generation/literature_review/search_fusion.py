"""Multi-source result merging and Reciprocal Rank Fusion.

Split out of ``search_support`` to keep that module within the size cap.
Holds the RRF fusion mechanics -- per-source weighting, the rank-position
score, pool normalization, retraction-aware ordering -- and the
title-deduplicating merge that ties them together. Every name is
re-exported from ``search_support``, so callers (and
``search_support.merge_search_results``'s own docstring references) are
unaffected.

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

import logging
from typing import Any

from co_scientist.agents.generation.literature_review.article_support import (
    _metadata_is_retracted,
)

logger = logging.getLogger(__name__)


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
# (mixed peer review), which outweighs preprints/arXiv/bioRxiv/web (no
# editorial review, and web carries no citation metadata at all -- the
# defect this table exists to fix). An unrecognized source name earns no
# special trust, so it shares the floor weight -- which is exactly the
# floor weight below, spelled out for every no-editorial-review source
# rather than left implicit for the ones this table happens to omit.
_SOURCE_RRF_WEIGHTS = {
    "pubmed": 3.0,
    "openalex": 2.0,
    "europepmc": 1.5,
    "literature": 1.5,
    "preprints": 1.0,
    "arxiv": 1.0,
    "biorxiv": 1.0,
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
