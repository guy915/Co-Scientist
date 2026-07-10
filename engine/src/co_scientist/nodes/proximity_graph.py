"""Weighted proximity graph construction.

The Proximity agent computes a graph over hypotheses (accounting for the
research goal) so similar ideas can be clustered, deduplicated, and — via the
tournament matchmaker — compared preferentially (SSR §4). PLAN.md M3.1 asks for
a *persisted weighted graph* rather than cluster labels alone: edges carry a
similarity score, the method/model/version that produced them, the goal
context, and an update time.

:func:`build_proximity_graph` is a pure function of the clustering output, so
the edge set and weights are testable without an LLM. Google does not publish
the embedding/similarity method, so the degree→score mapping here is a
documented clone choice.
"""

from __future__ import annotations

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


def _degree_weight(degree: str | None) -> float:
    """Map a similarity degree label to its numeric weight (default low)."""
    return _DEGREE_WEIGHT.get((degree or "low").lower(), _DEGREE_WEIGHT["low"])


def _cluster_member_ids(
    cluster: dict[str, Any], id_by_text: dict[str, str]
) -> list[tuple[str, str]]:
    """Return (hypothesis_id, degree) for each resolvable cluster member."""
    members: list[tuple[str, str]] = []
    for member in cluster.get("hypotheses", []):
        text = member.get("hypothesis_text") or member.get("text") or ""
        hyp_id = id_by_text.get(text.strip().lower())
        if hyp_id is not None:
            members.append((hyp_id, member.get("similarity_degree", "low")))
    return members


def build_proximity_graph(
    similarity_clusters: list[dict[str, Any]],
    hypotheses_by_text: dict[str, str],
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
        hypotheses_by_text: Map from normalized hypothesis text to its stable
            id, used to resolve cluster members to hypothesis ids.
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
        cluster_id = cluster.get("cluster_id", "unknown")
        members = _cluster_member_ids(cluster, hypotheses_by_text)
        for (id_a, deg_a), (id_b, deg_b) in itertools.combinations(members, 2):
            if id_a == id_b:
                continue
            key = frozenset({id_a, id_b})
            weight = max(_degree_weight(deg_a), _degree_weight(deg_b))
            existing = edges.get(key)
            if existing is None or weight > existing["similarity"]:
                edges[key] = {
                    "source": id_a,
                    "target": id_b,
                    "similarity": weight,
                    "degree": (
                        deg_a
                        if _degree_weight(deg_a) >= _degree_weight(deg_b)
                        else deg_b
                    ),
                    "cluster_id": cluster_id,
                }

    return {
        "edges": list(edges.values()),
        "meta": {
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
        },
    }
