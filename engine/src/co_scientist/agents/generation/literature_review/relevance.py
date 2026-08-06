"""Hybrid lexical + semantic relevance scoring for literature retrieval.

Local algorithm (fidelity-audit G5, documented local choice)
==============================================================

Retrieval ranking otherwise rests entirely on
``search_support._retrieval_score``: source quality, capped citation count,
and linear recency -- a hand-weighted lexical/heuristic sum with no
semantic judgment of whether a candidate actually bears on the research
goal. No embedding model is configured for this deployment (the provider is
DeepSeek, which serves no embeddings endpoint), so the semantic half of the
hybrid is a **model-judged relevance pass** rather than a vector similarity
-- the same "LLM judges qualitatively, the module turns that into a
numeric, persisted score" pattern ``agents/proximity/proximity_graph.py``
documents as its own first-class local algorithm (``llm-cluster`` v1).

This deployment's retrieval scorer is ``hybrid-lexical-semantic`` version 1:

1. The existing lexical heuristic runs unchanged and is normalized onto
   ``[0, 1]`` (:func:`normalize_lexical`).
2. A bounded slice of the best-ranked candidates (the over-fetched pool a
   run can actually afford to judge, see ``_semantic_pool_size``) each get
   one LLM call scoring 0.0-1.0 relevance plus a one-sentence rationale
   (:func:`apply_semantic_relevance`) -- one call per candidate, so the
   schema never lists a pool to identify a candidate by echoed text (the
   structured-output pitfall AGENTS.md records: echoing a schema back
   scales output with pool size and truncates identically on every retry).
3. :func:`combine_hybrid_score` averages the two into the persisted score.

Every candidate's ``retrieval_score`` is written on this same normalized
scale regardless of whether it was semantically judged (an out-of-pool
candidate simply carries a lexical-only score), and ``retriever_version``
names which of the two the score reflects, so a reader can always tell a
judged score from an unjudged one. :func:`combine_hybrid_score` is a pure
function of its two numeric inputs, so the combination -- and its
determinism on fixed inputs -- is testable without an LLM.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from co_scientist.constants import DEFAULT_MAX_TOKENS, HIGH_TEMPERATURE
from co_scientist.llm import CompletionSpec, call_llm_json
from co_scientist.prompts import get_literature_review_relevance_prompt
from co_scientist.schemas import LITERATURE_RELEVANCE_SCHEMA

logger = logging.getLogger(__name__)

# Identifies how a persisted retrieval_score was produced (see the module
# docstring). A future retrieval metric registers as a new method/version
# rather than redefining what "hybrid-lexical-semantic" version 1 means.
RETRIEVAL_METHOD = "hybrid-lexical-semantic"
RETRIEVAL_METHOD_VERSION = "1"
_LEXICAL_ONLY_VERSION = f"lexical-only/{RETRIEVAL_METHOD_VERSION}"
_HYBRID_VERSION = f"{RETRIEVAL_METHOD}/{RETRIEVAL_METHOD_VERSION}"

# search_support._retrieval_score's documented range: source_quality
# (1.5-3.0) + capped citations (0-1.0) + recency (0-1.0). A retracted
# candidate's -1_000_000 sentinel is excluded upstream (search_budget's
# _exclude_retracted) before this module ever sees it.
_LEXICAL_MIN = 1.5
_LEXICAL_MAX = 5.0
_LEXICAL_WEIGHT = 0.5
_SEMANTIC_WEIGHT = 0.5

# Bounds how many candidates get a semantic call: an over-fetch multiplier
# on the evidence budget, capped absolutely so a large candidate pool
# cannot turn one literature review into dozens of extra LLM calls.
_SEMANTIC_POOL_MULTIPLIER = 3
_SEMANTIC_POOL_CAP = 24


def normalize_lexical(raw_score: float) -> float:
    """Map the lexical heuristic's documented raw range onto [0, 1]."""
    normalized = (raw_score - _LEXICAL_MIN) / (_LEXICAL_MAX - _LEXICAL_MIN)
    return max(0.0, min(1.0, normalized))


def combine_hybrid_score(lexical_raw: float, semantic: float | None) -> float:
    """Combine the lexical heuristic and the semantic judgment into one score.

    Pure and deterministic: the same two inputs always yield the same
    output, so the combination step is testable without an LLM.

    Args:
        lexical_raw: The unbounded lexical heuristic score
            (``search_support._retrieval_score``).
        semantic: The model-judged relevance in [0, 1], or None when this
            candidate was not semantically scored (out-of-pool candidates
            still get a normalized, lexical-only score on the same scale).

    Returns:
        The combined score in [0, 1], rounded to 4 places.
    """
    lexical = normalize_lexical(lexical_raw)
    if semantic is None:
        return round(lexical, 4)
    bounded_semantic = max(0.0, min(1.0, semantic))
    combined = _LEXICAL_WEIGHT * lexical + _SEMANTIC_WEIGHT * bounded_semantic
    return round(combined, 4)


def _semantic_pool_size(candidate_count: int, budget: int) -> int:
    """Bound how many of the ranked candidates receive a semantic call."""
    if budget <= 0:
        return 0
    cap = min(budget * _SEMANTIC_POOL_MULTIPLIER, _SEMANTIC_POOL_CAP)
    return min(candidate_count, cap)


async def _judge_one_candidate(
    paper_id: str,
    metadata: dict[str, Any],
    research_goal: str,
    model_name: str,
) -> tuple[str, float, str]:
    """Score one candidate's semantic relevance, tolerant of a failed call.

    A single candidate's judged relevance never blocks the rest of the
    pool: a failed or malformed call degrades to 0.0 with a rationale
    naming the failure (mirroring how the engine's tool calls degrade to an
    empty result rather than raising), so a re-rank still runs on the
    survivors rather than aborting the whole search.
    """
    prompt = get_literature_review_relevance_prompt(
        research_goal=research_goal,
        title=str(metadata.get("title") or "Unknown"),
        abstract=str(metadata.get("abstract") or ""),
    )
    try:
        result = await call_llm_json(
            prompt=prompt,
            spec=CompletionSpec(
                model_name=model_name,
                max_tokens=DEFAULT_MAX_TOKENS,
                temperature=HIGH_TEMPERATURE,
                json_schema=LITERATURE_RELEVANCE_SCHEMA,
            ),
        )
        relevance = float(result.get("relevance", 0.0))
        rationale = str(result.get("rationale") or "")
    except Exception as exc:  # Never abort the pool over one bad call.
        logger.warning(
            "Semantic relevance scoring failed for %s: %s", paper_id, exc
        )
        relevance = 0.0
        rationale = "semantic relevance scoring failed"
    return paper_id, relevance, rationale


def _stamp_hybrid_score(
    metadata: dict[str, Any],
    lexical_raw: float,
    semantic: float | None,
    rationale: str,
) -> None:
    """Record the combined score and its provenance on one candidate.

    ``lexical_raw`` must be the candidate's original, un-normalized
    ``search_support._retrieval_score`` output -- never read back from
    ``metadata["retrieval_score"]``, which this function overwrites with
    the already-normalized [0, 1] result. Reading it back would feed an
    already-normalized value into :func:`combine_hybrid_score` a second
    time, which -- being far below ``_LEXICAL_MIN`` -- always clamps to
    0.0 regardless of the candidate's real lexical quality: every
    candidate's score collapsed to exactly the same
    ``_SEMANTIC_WEIGHT``-scaled value the one time this shipped that way.
    """
    metadata["retrieval_score"] = combine_hybrid_score(lexical_raw, semantic)
    metadata["retrieval_rationale"] = rationale
    metadata["retriever_version"] = (
        _HYBRID_VERSION if semantic is not None else _LEXICAL_ONLY_VERSION
    )


def _lexical_raw_scores(
    ranked: dict[str, dict[str, Any]],
) -> dict[str, float]:
    """Capture every candidate's original lexical score before any stamping.

    Must run before ``_stamp_hybrid_score`` touches ``ranked`` at all: that
    function overwrites ``retrieval_score`` in place, so reading it after
    even the lexical-only baseline pass would already return a normalized
    value (see ``_stamp_hybrid_score``'s docstring).
    """
    return {
        pid: float(metadata.get("retrieval_score") or 0.0)
        for pid, metadata in ranked.items()
    }


def _stamp_lexical_baseline(
    ranked: dict[str, dict[str, Any]], lexical_raw: dict[str, float]
) -> None:
    """Normalize every candidate's score before any semantic judgment runs."""
    for paper_id, metadata in ranked.items():
        _stamp_hybrid_score(metadata, lexical_raw[paper_id], None, "")


def _semantic_pool_ids(
    ranked: dict[str, dict[str, Any]], research_goal: str, budget: int
) -> list[str]:
    """Return the candidate ids to semantically score, best lexical first."""
    if not research_goal:
        return []
    pool_size = _semantic_pool_size(len(ranked), budget)
    return list(ranked)[:pool_size] if pool_size > 0 else []


def _resort_by_hybrid_score(
    ranked: dict[str, dict[str, Any]], scored_ids: set[str]
) -> dict[str, dict[str, Any]]:
    """Re-sort the semantically-scored subset, keeping the rest in place.

    The unscored tail (outside the semantic pool) keeps its original
    lexical order and stays after every scored candidate, since it was
    already ranked below the pool this function scored.
    """
    scored = sorted(
        (pid for pid in ranked if pid in scored_ids),
        key=lambda pid: -float(ranked[pid]["retrieval_score"]),
    )
    rest = [pid for pid in ranked if pid not in scored_ids]
    return {pid: ranked[pid] for pid in (*scored, *rest)}


async def apply_semantic_relevance(
    ranked: dict[str, dict[str, Any]],
    research_goal: str,
    model_name: str,
    budget: int,
) -> dict[str, dict[str, Any]]:
    """Re-rank merged search results with a bounded semantic relevance pass.

    Every candidate's ``retrieval_score`` is normalized onto [0, 1] first
    (lexical-only baseline); the best-ranked slice of the pool then gets a
    model-judged relevance call, whose result is combined in via
    :func:`combine_hybrid_score`. Only the top
    ``budget * _SEMANTIC_POOL_MULTIPLIER`` (capped at
    ``_SEMANTIC_POOL_CAP``) candidates by lexical score are judged, so a
    large candidate pool costs a bounded number of calls.

    Args:
        ranked: Merged search results, best-first by lexical score (as
            returned by ``search_support.merge_search_results``).
        research_goal: The goal to judge relevance against; an empty goal
            (should not occur in a real run) skips the semantic pass.
        model_name: Model for the semantic judgment calls.
        budget: The run's evidence budget, used only to size the pool.

    Returns:
        The same candidates, re-sorted by combined score where judged and
        otherwise left in their original lexical position.
    """
    if not ranked:
        return ranked
    lexical_raw = _lexical_raw_scores(ranked)
    _stamp_lexical_baseline(ranked, lexical_raw)

    pool_ids = _semantic_pool_ids(ranked, research_goal, budget)
    if not pool_ids:
        return ranked

    judgments = await asyncio.gather(
        *(
            _judge_one_candidate(pid, ranked[pid], research_goal, model_name)
            for pid in pool_ids
        )
    )
    for paper_id, relevance, rationale in judgments:
        _stamp_hybrid_score(
            ranked[paper_id], lexical_raw[paper_id], relevance, rationale
        )

    return _resort_by_hybrid_score(ranked, set(pool_ids))
