"""Pure cluster-resolution and dedup helpers for the proximity node.

Everything here is deterministic list/dict work over already-fetched
similarity clusters: resolving cluster members back to hypotheses,
assigning cluster ids, and dropping high-similarity duplicates. The LLM
call and node orchestration stay in ``proximity.py``, which re-exports
these names for compatibility.

The dropping is ours, not Google's: the published Proximity agent scores
pairs and updates a graph, and no listing deletes a hypothesis. See
``_resolve_cluster_duplicates`` for the decision point and what a false
"high" costs.
"""

import logging
from typing import Any

from co_scientist.agents.proximity.proximity_graph import member_match_key
from co_scientist.models import Hypothesis, rank_by_elo

logger = logging.getLogger(__name__)


def _match_cluster_member(
    similar_hyp: dict[str, Any],
    hypotheses: list[Hypothesis],
    by_prefix: dict[str, Hypothesis],
) -> Hypothesis | None:
    """Resolve one cluster member to its hypothesis, index first.

    Args:
        similar_hyp: One entry of a cluster's ``similar_hypotheses``.
        hypotheses: The pool, in the order the prompt numbered it.
        by_prefix: First-occurrence map keyed by ``member_match_key``.

    Returns:
        The matching hypothesis, or None when the entry resolves to none.
    """
    index = similar_hyp.get("index")
    if isinstance(index, int) and 0 <= index < len(hypotheses):
        return hypotheses[index]
    text = similar_hyp.get("text")
    if isinstance(text, str) and text:
        return by_prefix.get(member_match_key(text))
    return None


def _apply_cluster_membership(
    matched: Hypothesis, cluster_id: str, similar_hyp: dict[str, Any]
) -> None:
    """Assigns one cluster id and (first-write-wins) similarity degree.

    First match wins: if the LLM's clusters overlap and a hypothesis
    appears more than once, its degree is fixed by whichever cluster is
    processed first rather than being overwritten by later matches.
    """
    matched.similarity_cluster_id = cluster_id
    if matched.similarity_degree is None:
        matched.similarity_degree = similar_hyp.get("similarity_degree", "low")


def _assign_cluster_ids(
    hypotheses: list[Hypothesis], similarity_clusters: list[dict[str, Any]]
) -> None:
    """Assigns similarity-cluster ids and degrees back onto hypotheses.

    A cluster member is resolved by the positional ``index`` the prompt
    assigns each hypothesis, falling back to comparing echoed text through
    ``member_match_key``. Text matching came first and is kept as the
    fallback -- it is robust to the quoting drift a model introduces -- but
    it cannot be the contract: echoing every member's full text made the
    response scale with the pool, and a large pool's echo does not fit the
    token budget (46 hypotheses averaging 1250 chars need roughly 14k
    output tokens against 10k). The JSON then truncated, every retry
    truncated the same way, and the node fell through to "no clusters" --
    five spent attempts and deduplication silently skipped. An index costs
    a couple of characters and carries the identical clustering judgement.

    The fallback goes through ``member_match_key`` because the persisted
    proximity graph resolves the same echoed members with that key. Raw
    prefixes here meant a re-quote that only changed case or padding was a
    stranger to clustering and a member to the graph -- one model response
    producing two different answers to "which hypothesis is this".

    Mutates the hypotheses in place.

    Args:
        hypotheses: All hypotheses being analyzed for proximity.
        similarity_clusters: Clusters as returned by the proximity LLM call.
    """
    # First-occurrence index: if several hypotheses share a match key, the
    # earliest one wins (matching by list order).
    by_prefix: dict[str, Hypothesis] = {}
    for hyp in hypotheses:
        by_prefix.setdefault(member_match_key(hyp.text), hyp)

    for cluster in similarity_clusters:
        cluster_id = cluster.get("cluster_id", "unknown")
        for similar_hyp in cluster.get("similar_hypotheses", []):
            matched = _match_cluster_member(similar_hyp, hypotheses, by_prefix)
            if matched is None:
                continue
            _apply_cluster_membership(matched, cluster_id, similar_hyp)


def _partition_by_similarity_degree(
    cluster_hypotheses: list[Hypothesis],
) -> tuple[list[Hypothesis], list[Hypothesis]]:
    """Splits cluster hypotheses into "high" and non-"high" similarity groups.

    Only hypotheses tagged "high" are candidates for removal; "medium"/"low"
    degree hypotheses in the same cluster are related but distinct enough to
    keep both.

    Args:
        cluster_hypotheses: Hypotheses assigned to one cluster.

    Returns:
        Tuple of (high_similarity, others).
    """
    high_similarity = [
        h for h in cluster_hypotheses if h.similarity_degree == "high"
    ]
    others = [h for h in cluster_hypotheses if h.similarity_degree != "high"]
    return high_similarity, others


def _build_removed_duplicate_record(
    duplicate: Hypothesis, cluster_id: str, kept: Hypothesis
) -> dict[str, Any]:
    """Builds one removed-duplicate audit entry for a dropped hypothesis.

    Feeds the removed_duplicates audit trail (state package), which evolve.py
    later reads to avoid recreating them and the UI surfaces for
    transparency.

    Args:
        duplicate: The high-similarity hypothesis being dropped.
        cluster_id: Identifier of the cluster it was resolved from.
        kept: Hypothesis retained instead of this duplicate.

    Returns:
        Removed-duplicate audit dict.
    """
    return {
        "text": duplicate.text,
        "cluster_id": cluster_id,
        "reason": "high_similarity_duplicate",
        "kept_hypothesis_id": kept.id,
        "kept_instead": kept.text[:200],
        "elo_rating": duplicate.elo_rating,
        "score": duplicate.score,
        # Preserve the complete immutable idea for lineage, tournament history,
        # and the Goal Report's Non-Viable archive without returning it to the
        # active hypothesis pool.
        "hypothesis": duplicate.to_dict(),
    }


def _build_removed_duplicates_for_cluster(
    high_similarity: list[Hypothesis], cluster_id: str, best: Hypothesis
) -> list[dict[str, Any]]:
    """Builds removed-duplicate records for the non-kept high-similarity set.

    Every high-similarity hypothesis in the cluster other than ``best`` is
    dropped. This is the one place a drop is traced, and it traces at debug:
    deduplication working is the node doing its job, the count already
    reaches the reader in the pass summary
    (``proximity._log_dedup_summary``), and every drop is persisted as an
    archived hypothesis. At info it wrote a row per drop into a log whose
    readable window is the newest hundred records -- the same crowding that
    summary line was itself fixed to stop.
    """
    removed_duplicates: list[dict[str, Any]] = []
    for duplicate in high_similarity[1:]:
        removed_duplicates.append(
            _build_removed_duplicate_record(duplicate, cluster_id, best)
        )
        logger.debug(
            "removed duplicate from cluster %s: %s... (elo %s)",
            cluster_id,
            duplicate.text[:100],
            duplicate.elo_rating,
        )
    return removed_duplicates


def _resolve_cluster_duplicates(
    cluster_id: str, cluster_hypotheses: list[Hypothesis]
) -> tuple[list[Hypothesis], list[dict[str, Any]]]:
    """Resolves high-similarity duplicates within a single cluster.

    Keeps every non-"high" similarity hypothesis plus only the single best
    "high" similarity hypothesis (ranked by Elo, then score, then text),
    recording the rest as removed duplicates.

    **This deletion is a local addition with no counterpart in the
    published proximity listing.** Google's Proximity agent computes a
    similarity per pair and updates a graph; nothing in it removes a
    hypothesis from the pool, and no other listing authorises a deletion
    either. Dropping near-duplicates is defensible in practice -- a pool of
    restatements wastes the tournament, evolution's parents and the
    reader's attention -- but the cost of being wrong is asymmetric and
    silent: a *false* "high" from a single clustering call deletes a
    distinct idea from the run outright. It never reaches the tournament,
    never breeds, and never appears in the report as an idea; it survives
    only as a ``removed_duplicates`` archive row explained as a duplicate
    of something it is not. There is no second opinion and no later pass
    that revisits the verdict, which is why the "high" band alone deletes
    and "medium"/"low" merely relate (``_partition_by_similarity_degree``).
    Anything that widens what deletes -- a lower band, a text metric, a
    second caller -- widens that silent loss with it.

    A single-member cluster needs no special case: it either falls in
    ``others`` and is kept, or is the sole "high" member and is kept as the
    best of one, with nothing after it to remove.

    Args:
        cluster_id: Identifier of the cluster being resolved.
        cluster_hypotheses: Hypotheses assigned to this cluster.

    Returns:
        Tuple of (hypotheses_to_keep, removed_duplicates) for this cluster.
    """
    high_similarity, others = _partition_by_similarity_degree(
        cluster_hypotheses
    )
    # Keep all non-high-similarity hypotheses.
    hypotheses_to_keep: list[Hypothesis] = list(others)
    if not high_similarity:
        return hypotheses_to_keep, []

    # For high-similarity duplicates, keep only the best. Rank by Elo
    # (primary), then score, then text as deterministic tiebreakers.
    high_similarity = rank_by_elo(high_similarity)
    best = high_similarity[0]
    hypotheses_to_keep.append(best)

    removed_duplicates = _build_removed_duplicates_for_cluster(
        high_similarity, cluster_id, best
    )

    return hypotheses_to_keep, removed_duplicates


def _group_by_cluster(
    hypotheses: list[Hypothesis],
) -> dict[str, list[Hypothesis]]:
    """Groups hypotheses by their assigned similarity_cluster_id.

    Rebuilt from each hypothesis's own similarity_cluster_id (rather than
    reusing the LLM's similarity_clusters list directly), so every
    hypothesis -- including any the LLM left unclustered -- is accounted
    for exactly once.
    """
    clusters_dict: dict[str, list[Hypothesis]] = {}
    for hyp in hypotheses:
        cluster_id = hyp.similarity_cluster_id or "unclustered"
        clusters_dict.setdefault(cluster_id, []).append(hyp)
    return clusters_dict


def _dedupe_by_cluster(
    hypotheses: list[Hypothesis],
) -> tuple[list[Hypothesis], list[dict[str, Any]]]:
    """Removes high-similarity duplicates within each similarity cluster.

    Groups hypotheses by their (already-assigned) similarity_cluster_id,
    then for each cluster keeps every non-"high" similarity hypothesis plus
    only the single best "high" similarity hypothesis (ranked by Elo, then
    score, then text), recording the rest as removed duplicates.

    Args:
        hypotheses: All hypotheses being analyzed for proximity, with
            similarity_cluster_id/similarity_degree already assigned.

    Returns:
        Tuple of (hypotheses_to_keep, removed_duplicates), where
        removed_duplicates entries feed the audit trail that evolve.py
        later reads to avoid recreating them and the UI surfaces for
        transparency.
    """
    removed_duplicates: list[dict[str, Any]] = []
    hypotheses_to_keep: list[Hypothesis] = []

    clusters_dict = _group_by_cluster(hypotheses)

    for cluster_id, cluster_hypotheses in clusters_dict.items():
        kept, removed = _resolve_cluster_duplicates(
            cluster_id, cluster_hypotheses
        )
        hypotheses_to_keep.extend(kept)
        removed_duplicates.extend(removed)

    return hypotheses_to_keep, removed_duplicates
