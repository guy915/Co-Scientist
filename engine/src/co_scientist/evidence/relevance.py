"""Hybrid lexical + semantic relevance scoring for literature retrieval.

Local algorithm (fidelity-audit G5, documented local choice)
==============================================================

Retrieval ranking otherwise rests entirely on
``search_support.merge_search_results``: Reciprocal Rank Fusion over each
source's own result order, weighted per source -- a rank-based fusion with
no semantic judgment of whether a candidate actually bears on the research
goal. No embedding model is configured for this deployment (the provider is
DeepSeek, which serves no embeddings endpoint), so the semantic half of the
hybrid is a **model-judged relevance pass** rather than a vector similarity
-- the same "LLM judges qualitatively, the module turns that into a
numeric, persisted score" pattern ``agents/proximity/proximity_graph.py``
documents as its own first-class local algorithm (``llm-cluster`` v1).

This deployment's retrieval scorer is ``hybrid-lexical-semantic`` version 2
(version 1 was an additive source-quality/citation/recency heuristic, now
retired -- the version bumped rather than being redefined in place, so a
persisted ``retriever_version`` of "1" keeps meaning what it always meant):

1. The RRF-fused rank score runs unchanged out of ``merge_search_results``,
   already normalized onto ``[0, 1]`` there (min-max over the fused pool,
   see ``search_support._normalize_rrf_pool``); :func:`normalize_lexical`
   here is a defensive clamp only, not a rescale.
2. A bounded slice of the best-ranked candidates (the over-fetched pool a
   run can actually afford to judge, see ``_semantic_pool_size``) is
   judged in batches of ``_RELEVANCE_BATCH_SIZE`` (:func:`_judge_batch`,
   fanned out concurrently by :func:`apply_semantic_relevance`): each
   batch call scores every candidate in it 0.0-1.0 relevance plus a
   one-sentence rationale, identified by the positional index the prompt
   assigned it -- never by echoing the candidate's title or abstract back
   (the structured-output pitfall AGENTS.md records: echoing a pool back
   scales output with pool size and truncates identically on every
   retry). This mirrors ``review_helpers``' batch-review index contract.
3. :func:`combine_hybrid_score` averages the two into the persisted score.

Every candidate's ``retrieval_score`` is written on this same normalized
scale regardless of whether it was semantically judged (an out-of-pool
candidate simply carries a lexical-only score), and ``retriever_version``
names which of the two the score reflects, so a reader can always tell a
judged score from an unjudged one. :func:`combine_hybrid_score` is a pure
function of its two numeric inputs, so the combination -- and its
determinism on fixed inputs -- is testable without an LLM.

Cost measurement (production ultra run b82f9162, 2026-09-06, free gateway
models): a literature review with 16 collected papers spent 70 provider
calls before generation even started -- 16 per-paper analyses (one call
per paper, see ``analysis.py``; unaffected by this module, which judges
title/abstract metadata *before* any paper's fulltext is fetched), ~3
query-generation calls, 1 synthesis call, and the remainder this pass's
one-call-per-candidate relevance judgments (up to
``papers_to_read_count * 3``, capped at ``_SEMANTIC_POOL_CAP``). Production
now runs on free gateway models capped at roughly 100 requests/day per
model (see the root AGENTS.md's "Required environment" section), so this
one node could consume most of a day's budget by itself. Batching the
relevance pass into groups of ``_RELEVANCE_BATCH_SIZE`` candidates per
call turns that many-calls-per-candidate cost into a small, fixed number
of calls per literature review (25 candidates at batch size 10 is 3
calls, not 25) without changing the per-candidate scoring semantics or
thresholds.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from co_scientist.constants import DEFAULT_MAX_TOKENS, HIGH_TEMPERATURE
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS
from co_scientist.llm import CompletionSpec, call_llm_json
from co_scientist.prompts import get_literature_review_relevance_batch_prompt
from co_scientist.schemas import LITERATURE_RELEVANCE_BATCH_SCHEMA

logger = logging.getLogger(__name__)

# Identifies how a persisted retrieval_score was produced (see the module
# docstring). A future retrieval metric registers as a new method/version
# rather than redefining what "hybrid-lexical-semantic" version 1 meant.
RETRIEVAL_METHOD = "hybrid-lexical-semantic"
RETRIEVAL_METHOD_VERSION = "2"
_LEXICAL_ONLY_VERSION = f"lexical-only/{RETRIEVAL_METHOD_VERSION}"
_HYBRID_VERSION = f"{RETRIEVAL_METHOD}/{RETRIEVAL_METHOD_VERSION}"

_LEXICAL_WEIGHT = 0.5
_SEMANTIC_WEIGHT = 0.5

# Bounds how many candidates get a semantic call: an over-fetch multiplier
# on the evidence budget, capped absolutely so a large candidate pool
# cannot turn one literature review into dozens of extra LLM calls.
_SEMANTIC_POOL_MULTIPLIER = 3
_SEMANTIC_POOL_CAP = 24

# How many candidates one relevance call judges together. Tunable: larger
# batches mean fewer calls but a longer prompt and a bigger blast radius
# if one batch call fails outright (the whole batch degrades to 0.0, see
# _judge_batch); 8-12 keeps each call's prompt small while still cutting
# a full pool (_SEMANTIC_POOL_CAP) to a handful of calls.
_RELEVANCE_BATCH_SIZE = 10

# Per-candidate abstract truncation inside a batch prompt, so a batch's
# total prompt size scales with _RELEVANCE_BATCH_SIZE, not with however
# long any one candidate's abstract happens to be.
_ABSTRACT_CHAR_BUDGET = 1500


def normalize_lexical(raw_score: float) -> float:
    """Clamp the RRF-fused rank score onto [0, 1].

    ``search_support.merge_search_results`` already min-max normalizes the
    raw RRF score onto [0, 1] over its own fused pool before this module
    ever sees it (unlike the retired v1 heuristic, whose fixed [1.5, 5.0]
    raw range this function used to rescale) -- so this is a defensive
    clamp against floating-point noise, not a rescale.
    """
    return max(0.0, min(1.0, raw_score))


def combine_hybrid_score(lexical_raw: float, semantic: float | None) -> float:
    """Combine the lexical heuristic and the semantic judgment into one score.

    Pure and deterministic: the same two inputs always yield the same
    output, so the combination step is testable without an LLM.

    Args:
        lexical_raw: The candidate's RRF-fused rank score, already
            normalized onto [0, 1] by
            ``search_support.merge_search_results``.
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


_FAILED_JUDGMENT_RATIONALE = "semantic relevance scoring failed"


def _chunked(items: list[str], size: int) -> list[list[str]]:
    """Split ``items`` into consecutive chunks of at most ``size``."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def _build_candidates_block(
    pool_ids: list[str], ranked: dict[str, dict[str, Any]]
) -> str:
    """Format one batch's candidates as a 1-based numbered list.

    The numbering is load-bearing: each judgment in the response names
    its candidate by this number (``index``), and ``_match_batch_judgments``
    maps entries back by it -- same convention as
    ``review_helpers._build_hypotheses_list_text``. Titles and abstracts
    are included so the model can judge them; the abstract is truncated
    to ``_ABSTRACT_CHAR_BUDGET`` so a batch's prompt size scales with the
    batch size, not with any one candidate's abstract length.
    """
    lines = []
    for number, paper_id in enumerate(pool_ids, start=1):
        metadata = ranked[paper_id]
        title = str(metadata.get("title") or "Unknown")
        abstract = str(metadata.get("abstract") or "")[:_ABSTRACT_CHAR_BUDGET]
        lines.append(
            f"**Candidate {number}:**\nTitle: {title}\nAbstract: {abstract}"
        )
    return "\n\n".join(lines)


def _match_batch_judgments(
    judgments: list[Any], pool_ids: list[str]
) -> list[Any]:
    """Associates batch judgment entries with candidates by their index.

    Same contract as ``review_helpers._match_batch_entries_to_hypotheses``:
    each entry's ``index`` is the number the prompt assigned (1-based).
    Entries with a valid, not-yet-claimed number land on that candidate
    regardless of list order; entries whose number is absent, non-integer,
    out of range, or duplicated fall back to filling the still-empty slots
    in list order. Surplus entries are dropped. A missing slot returns
    None there, degrading that candidate the same way a failed call does
    (see ``_judge_batch``) -- this is also what keeps the offline backend
    safe when its filler under-populates the array (see the "offline
    backend under-populates" note): a short response still fills the
    earliest candidates first rather than raising an index error.

    Args:
        judgments: The "judgments" list pulled from the batch response.
        pool_ids: Candidate ids in this batch, in prompt order.

    Returns:
        One entry (raw dict or None) per candidate, in ``pool_ids`` order.
    """
    count = len(pool_ids)
    slots: list[Any] = [None] * count
    unplaced: list[Any] = []
    claimed: set[int] = set()
    for entry in judgments:
        number = entry.get("index") if isinstance(entry, dict) else None
        if (
            isinstance(number, int)
            and not isinstance(number, bool)
            and 1 <= number <= count
            and number not in claimed
        ):
            slots[number - 1] = entry
            claimed.add(number)
        else:
            unplaced.append(entry)

    remaining = iter(unplaced)
    for index in range(count):
        if slots[index] is None:
            slots[index] = next(remaining, None)
    return slots


def _score_matched_judgments(
    pool_ids: list[str], judgments: list[Any]
) -> list[tuple[str, float, str]]:
    """Pairs each candidate with its matched judgment, or a failed default.

    A candidate the response never named (index missing, malformed, or the
    array simply short -- see the offline backend's own filler) degrades
    to 0.0 the same way a raised exception does.
    """
    matched = _match_batch_judgments(judgments, pool_ids)
    scored = []
    for paper_id, entry in zip(pool_ids, matched, strict=True):
        scored.append((paper_id, *_one_judgment(entry)))
    return scored


def _one_judgment(entry: Any) -> tuple[float, str]:
    """Reads one matched entry's relevance/rationale, tolerant of bad types.

    Under the json_object downgrade (no server-side schema enforcement) a
    field can hold the wrong type entirely -- a non-numeric ``relevance``
    must degrade only this one candidate, not raise out of the whole
    batch (which would abort every sibling batch through
    ``asyncio.gather``, the exact abort this function exists to avoid).
    """
    if not isinstance(entry, dict):
        return 0.0, _FAILED_JUDGMENT_RATIONALE
    try:
        relevance = float(entry.get("relevance", 0.0))
    except (TypeError, ValueError):
        return 0.0, _FAILED_JUDGMENT_RATIONALE
    return relevance, str(entry.get("rationale") or "")


async def _judge_batch(
    pool_ids: list[str],
    ranked: dict[str, dict[str, Any]],
    research_goal: str,
    model_name: str,
) -> list[tuple[str, float, str]]:
    """Score one batch of candidates' semantic relevance in a single call.

    A failed or malformed call degrades every candidate in the batch to
    0.0 with a rationale naming the failure (mirroring how the engine's
    tool calls degrade to an empty result rather than raising), so a
    re-rank still runs on the survivors rather than aborting the whole
    search.
    """
    prompt = get_literature_review_relevance_batch_prompt(
        research_goal=research_goal,
        candidates_block=_build_candidates_block(pool_ids, ranked),
    )
    try:
        result = await call_llm_json(
            prompt=prompt,
            spec=CompletionSpec(
                model_name=model_name,
                max_tokens=DEFAULT_MAX_TOKENS,
                temperature=HIGH_TEMPERATURE,
                json_schema=LITERATURE_RELEVANCE_BATCH_SCHEMA,
            ),
        )
    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception as exc:  # Never abort the pool over one bad call.
        logger.warning(
            "Semantic relevance batch scoring failed for %s candidates: %s",
            len(pool_ids),
            exc,
        )
        return [
            (paper_id, 0.0, _FAILED_JUDGMENT_RATIONALE) for paper_id in pool_ids
        ]

    return _score_matched_judgments(pool_ids, result.get("judgments") or [])


def _stamp_hybrid_score(
    metadata: dict[str, Any],
    lexical_raw: float,
    semantic: float | None,
    rationale: str,
) -> None:
    """Record the combined score and its provenance on one candidate.

    ``lexical_raw`` must be the candidate's original
    ``search_support.merge_search_results`` RRF score -- never read back
    from ``metadata["retrieval_score"]``, which this function overwrites
    with the *combined* [0, 1] result. Reading it back would feed an
    already-combined score into :func:`combine_hybrid_score` a second
    time, silently double-weighting the semantic term for every
    candidate stamped this way: every candidate's score collapsed to
    exactly the same ``_SEMANTIC_WEIGHT``-scaled value the one time this
    shipped that way.
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
    ``_SEMANTIC_POOL_CAP``) candidates by lexical score are judged, split
    into batches of ``_RELEVANCE_BATCH_SIZE`` and judged one call per
    batch (run concurrently, the same way the calls this replaced ran one
    per candidate), so a large candidate pool costs a small, bounded
    number of calls rather than one per candidate.

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

    batches = await asyncio.gather(
        *(
            _judge_batch(batch_ids, ranked, research_goal, model_name)
            for batch_ids in _chunked(pool_ids, _RELEVANCE_BATCH_SIZE)
        )
    )
    for batch in batches:
        for paper_id, relevance, rationale in batch:
            _stamp_hybrid_score(
                ranked[paper_id], lexical_raw[paper_id], relevance, rationale
            )

    return _resort_by_hybrid_score(ranked, set(pool_ids))
