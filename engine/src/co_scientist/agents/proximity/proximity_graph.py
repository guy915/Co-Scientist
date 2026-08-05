"""Weighted proximity graph construction.

The Proximity agent computes a graph over hypotheses (accounting for the
research goal) so similar ideas can be clustered, deduplicated, and — via the
tournament matchmaker — compared preferentially (SSR §4). The agent builds
a *persisted weighted graph* rather than cluster labels alone: edges carry a
similarity score, the method/model/version that produced them, the goal
context, and an update time.

:func:`build_proximity_graph` is a pure function of the clustering output, so
the edge set and weights are testable without an LLM. Google does not publish
the embedding/similarity method, so the degree→score mapping here is a
documented clone choice.
"""

from __future__ import annotations

import dataclasses
import itertools
from typing import Any

# Clone-defined mapping from the LLM's qualitative similarity degree to a
# numeric edge weight in [0, 1]. Google leaves the proximity similarity metric
# unspecified (SSR §12); this is the documented choice.
_DEGREE_WEIGHT: dict[str, float] = {
    "high": 1.0,
    "medium": 0.6,
    "low": 0.3,
}

# Identifies how these edges were produced, versioned so a persisted graph
# records its provenance and can be recomputed/migrated later.
PROXIMITY_METHOD = "llm-cluster"
PROXIMITY_METHOD_VERSION = "1"

# A cluster member names its hypothesis by the positional index the prompt
# assigned (PROXIMITY_SCHEMA), and only older responses echo the text back.
# Where a member does carry text, matching is done on the first 100 chars, so a
# re-quote that drifts past char 100 still resolves.
# proximity_dedup.py::_assign_cluster_ids resolves the same echoed members by
# calling member_match_key below, so clustering and this graph cannot disagree
# about which hypothesis a member is.
_MATCH_PREFIX_CHARS = 100


def member_match_key(text: str) -> str:
    """Normalize hypothesis text to the key used to resolve cluster members.

    Both the id map (built by the proximity node from surviving hypotheses)
    and each cluster member's echoed text are reduced to this key, so a member
    resolves to its hypothesis id whenever the node would have clustered it.
    Matching is on the normalized first ``_MATCH_PREFIX_CHARS`` characters:
    the same window the node's own fallback uses -- which reaches this
    function rather than reimplementing it -- and robust to the LLM editing
    the tail, the case, or the padding of a re-quoted hypothesis.

    Args:
        text: Raw hypothesis text (from a Hypothesis or an echoed cluster
            member).

    Returns:
        The normalized match key.
    """
    return text[:_MATCH_PREFIX_CHARS].strip().lower()


@dataclasses.dataclass(frozen=True)
class SurvivorIndex:
    """The two ways a cluster member resolves to a surviving hypothesis.

    Both tables cover the dedup survivors only, so a member the proximity
    node has just dropped resolves to nothing and never becomes a graph
    node. They are carried together because the resolution order matters:
    index first, text as the fallback, exactly as
    ``proximity_dedup._match_cluster_member`` resolves the same members.

    Attributes:
        by_index: Prompt position -> hypothesis id. Positions are the ones
            ``proximity._prepare_hypotheses_for_analysis`` numbered, so a
            removed duplicate leaves its position absent rather than
            renumbering the survivors.
        by_text: ``member_match_key`` -> hypothesis id, for responses that
            echo a member's text instead of (or as well as) its index.
    """

    by_index: dict[int, str]
    by_text: dict[str, str]


def _degree_weight(degree: str | None) -> float:
    """Map a similarity degree label to its numeric weight (default low)."""
    return _DEGREE_WEIGHT.get((degree or "low").lower(), _DEGREE_WEIGHT["low"])


def _resolve_member_id(
    member: dict[str, Any], survivors: SurvivorIndex
) -> str | None:
    """Resolve one cluster member to a surviving hypothesis id, index first.

    ``PROXIMITY_SCHEMA`` identifies a member by the positional ``index`` the
    prompt assigned and forbids any other key, so the index is the contract
    and echoed ``text`` is only a fallback for a response that carries it
    anyway. Reading text alone emptied the persisted graph on every real run
    once the schema stopped echoing it: no member carried a ``text`` key, so
    every member resolved to None and no cluster ever produced a pair.

    Args:
        member: One entry of a cluster's ``similar_hypotheses``.
        survivors: Resolution tables over the dedup survivors.

    Returns:
        The surviving hypothesis's id, or None when the member resolves to
        none of them.
    """
    index = member.get("index")
    if isinstance(index, int):
        resolved = survivors.by_index.get(index)
        if resolved is not None:
            return resolved
    text = member.get("text")
    if isinstance(text, str) and text:
        return survivors.by_text.get(member_match_key(text))
    return None


def _cluster_member_ids(
    cluster: dict[str, Any], survivors: SurvivorIndex
) -> list[tuple[str, str]]:
    """Return (hypothesis_id, degree) for each resolvable cluster member.

    Members that resolve to nothing are dropped: an out-of-range index, an
    unrecognized text, or a hypothesis pruned by dedup before the graph was
    built.
    """
    members: list[tuple[str, str]] = []
    for member in cluster.get("similar_hypotheses", []):
        hyp_id = _resolve_member_id(member, survivors)
        if hyp_id is not None:
            members.append((hyp_id, member.get("similarity_degree", "low")))
    return members


def _accumulate_cluster_edges(
    edges: dict[frozenset[str], dict[str, Any]],
    cluster: dict[str, Any],
    survivors: SurvivorIndex,
) -> None:
    """Merges one cluster's pairwise edges into the accumulating edge map.

    Keeps the strongest similarity per unordered pair when the same pair
    appears in more than one cluster.
    """
    cluster_id = cluster.get("cluster_id", "unknown")
    members = _cluster_member_ids(cluster, survivors)
    for (id_a, deg_a), (id_b, deg_b) in itertools.combinations(members, 2):
        if id_a == id_b:
            continue
        key = frozenset({id_a, id_b})
        # The edge's weight and its label are the same decision -- the
        # stronger of the two members' degrees -- so each degree is scored
        # once and both are read off that one comparison.
        weight_a, weight_b = _degree_weight(deg_a), _degree_weight(deg_b)
        stronger = deg_a if weight_a >= weight_b else deg_b
        weight = max(weight_a, weight_b)
        existing = edges.get(key)
        if existing is None or weight > existing["similarity"]:
            edges[key] = {
                "source": id_a,
                "target": id_b,
                "similarity": weight,
                "degree": stronger,
                "cluster_id": cluster_id,
            }


def _proximity_graph_meta(
    edges: dict[frozenset[str], dict[str, Any]],
    research_goal: str,
    model: str,
    updated_at: float,
) -> dict[str, Any]:
    """Builds the provenance metadata for a persisted proximity graph."""
    return {
        "method": PROXIMITY_METHOD,
        "version": PROXIMITY_METHOD_VERSION,
        "model": model,
        "research_goal": research_goal,
        "updated_at": updated_at,
        "node_count": len(
            {v["source"] for v in edges.values()}
            | {v["target"] for v in edges.values()}
        ),
        "edge_count": len(edges),
    }


def build_proximity_graph(
    similarity_clusters: list[dict[str, Any]],
    survivors: SurvivorIndex,
    *,
    research_goal: str,
    model: str,
    updated_at: float,
) -> dict[str, Any]:
    """Build a persisted weighted proximity graph from clustering output.

    Args:
        similarity_clusters: Clusters as returned by the proximity LLM call;
            each has a ``cluster_id`` and member hypotheses with a
            ``similarity_degree``.
        survivors: Index/text resolution tables over the dedup survivors,
            used to resolve cluster members to hypothesis ids.
        research_goal: The goal context the graph was computed under.
        model: The model that produced the clustering (provenance).
        updated_at: Unix timestamp when the graph was computed.

    Returns:
        A graph dict with ``edges`` (undirected weighted edges between
        hypotheses in the same cluster) and ``meta`` (method/version/model/
        goal/update-time provenance). Edges are deduplicated per unordered
        pair, keeping the strongest similarity.
    """
    edges: dict[frozenset[str], dict[str, Any]] = {}
    for cluster in similarity_clusters:
        _accumulate_cluster_edges(edges, cluster, survivors)

    return {
        "edges": list(edges.values()),
        "meta": _proximity_graph_meta(edges, research_goal, model, updated_at),
    }
