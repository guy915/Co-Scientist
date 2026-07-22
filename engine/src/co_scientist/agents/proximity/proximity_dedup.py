"""Pure cluster-resolution and dedup helpers for the proximity node.

Everything here is deterministic list/dict work over already-fetched
similarity clusters: resolving cluster members back to hypotheses,
assigning cluster ids, and dropping high-similarity duplicates. The LLM
call and node orchestration stay in ``proximity.py``, which re-exports
these names for compatibility.
"""

import logging
from typing import Any

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
        by_prefix: First-occurrence map from 100-char text prefix.

    Returns:
        The matching hypothesis, or None when the entry resolves to none.
    """
    index = similar_hyp.get("index")
    if isinstance(index, int) and 0 <= index < len(hypotheses):
        return hypotheses[index]
    text = similar_hyp.get("text")
    if isinstance(text, str) and text:
        return by_prefix.get(text[:100])
    return None


def _assign_cluster_ids(
    hypotheses: list[Hypothesis], similarity_clusters: list[dict[str, Any]]
) -> None:
    """Assigns similarity-cluster ids and degrees back onto hypotheses.

    A cluster member is resolved by the positional ``index`` the prompt
    assigns each hypothesis, falling back to comparing the first 100 chars
    of echoed text. Text matching came first and is kept as the fallback --
    it is robust to the quoting drift a model introduces -- but it cannot be
    the contract: echoing every member's full text made the response scale
    with the pool, and a large pool's echo does not fit the token budget
    (46 hypotheses averaging 1250 chars need roughly 14k output tokens
    against 10k). The JSON then truncated, every retry truncated the same
    way, and the node fell through to "no clusters" -- five spent attempts
    and deduplication silently skipped. An index costs a couple of
    characters and carries the identical clustering judgement.

    Mutates the hypotheses in place.

    Args:
        hypotheses: All hypotheses being analyzed for proximity.
        similarity_clusters: Clusters as returned by the proximity LLM call.
    """
    # First-occurrence prefix index: if several hypotheses share the same
    # 100-char prefix, the earliest one wins (matching by list order).
    by_prefix: dict[str, Hypothesis] = {}
    for hyp in hypotheses:
        by_prefix.setdefault(hyp.text[:100], hyp)

    for cluster in similarity_clusters:
        cluster_id = cluster.get("cluster_id", "unknown")
        for similar_hyp in cluster.get("similar_hypotheses", []):
            matched = _match_cluster_member(similar_hyp, hypotheses, by_prefix)
            if matched is None:
                continue
            matched.similarity_cluster_id = cluster_id
            # Store similarity degree (only set if not already set)
            # First match wins: if the LLM's clusters overlap and a
            # hypothesis appears more than once, its degree is fixed by
            # whichever cluster is processed first rather than being
            # overwritten by later matches.
            if matched.similarity_degree is None:
                matched.similarity_degree = similar_hyp.get(
                    "similarity_degree", "low"
                )


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

    Feeds the removed_duplicates audit trail (state.py), which evolve.py
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


def _resolve_cluster_duplicates(
    cluster_id: str, cluster_hypotheses: list[Hypothesis]
) -> tuple[list[Hypothesis], list[dict[str, Any]]]:
    """Resolves high-similarity duplicates within a single cluster.

    Keeps every non-"high" similarity hypothesis plus only the single best
    "high" similarity hypothesis (ranked by Elo, then score, then text),
    recording the rest as removed duplicates.

    Args:
        cluster_id: Identifier of the cluster being resolved.
        cluster_hypotheses: Hypotheses assigned to this cluster.

    Returns:
        Tuple of (hypotheses_to_keep, removed_duplicates) for this cluster.
    """
    if len(cluster_hypotheses) == 1:
        # No duplicates possible
        return list(cluster_hypotheses), []

    high_similarity, others = _partition_by_similarity_degree(
        cluster_hypotheses
    )

    # Keep all non-high-similarity hypotheses
    hypotheses_to_keep: list[Hypothesis] = []
    hypotheses_to_keep.extend(others)

    if not high_similarity:
        return hypotheses_to_keep, []

    # For high-similarity duplicates, keep only the best. Rank by Elo
    # (primary), then score, then text as deterministic tiebreakers.
    high_similarity = rank_by_elo(high_similarity)

    # Keep the best
    best = high_similarity[0]
    hypotheses_to_keep.append(best)

    # Remove the rest
    # Every other high-similarity hypothesis in the cluster is dropped.
    removed_duplicates: list[dict[str, Any]] = []
    for duplicate in high_similarity[1:]:
        removed_duplicates.append(
            _build_removed_duplicate_record(duplicate, cluster_id, best)
        )
        logger.info(
            "Removed duplicate from cluster %s: %s... (Elo: %s)",
            cluster_id,
            duplicate.text[:100],
            duplicate.elo_rating,
        )

    return hypotheses_to_keep, removed_duplicates


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

    # Group by cluster
    # Rebuilt from each hypothesis's own similarity_cluster_id (rather
    # than reusing the LLM's similarity_clusters list directly), so every
    # hypothesis -- including any the LLM left unclustered -- is
    # accounted for exactly once below.
    clusters_dict: dict[str, list[Hypothesis]] = {}
    for hyp in hypotheses:
        cluster_id = hyp.similarity_cluster_id or "unclustered"
        if cluster_id not in clusters_dict:
            clusters_dict[cluster_id] = []
        clusters_dict[cluster_id].append(hyp)

    # For each cluster, handle high-similarity duplicates
    for cluster_id, cluster_hypotheses in clusters_dict.items():
        kept, removed = _resolve_cluster_duplicates(
            cluster_id, cluster_hypotheses
        )
        hypotheses_to_keep.extend(kept)
        removed_duplicates.extend(removed)

    return hypotheses_to_keep, removed_duplicates
