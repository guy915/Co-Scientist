"""Weighted proximity graph construction.

The Proximity agent computes a graph over hypotheses (accounting for the
research goal) so similar ideas can be clustered, deduplicated, and — via the
tournament matchmaker — compared preferentially (SSR §4). The agent builds
a *persisted weighted graph* rather than cluster labels alone: edges carry a
similarity score, the method/model/version that produced them, the goal
context, and an update time.

Local algorithm (fidelity-audit H2, documented local choice)
============================================================

The paper's similarity step says "e.g. text embeddings" without specifying a
method, so the similarity metric is a permitted local choice. This
deployment's first-class algorithm is ``llm-cluster`` version 1:

1. An LLM judges pairwise similarity qualitatively, emitting clusters whose
   members carry a ``similarity_degree`` of ``high`` / ``medium`` / ``low``
   (``PROXIMITY_SCHEMA``).
2. :func:`build_proximity_graph` turns each cluster into pairwise edges,
   mapping the qualitative degree to a fixed numeric weight via
   ``_DEGREE_WEIGHT`` (high 1.0, medium 0.6, low 0.3) and keeping the
   strongest weight per unordered pair.

3. A surviving pair the clustering left unconnected gets a *floor* edge
   (``_FLOOR_SIMILARITY``, below the weakest judged degree), up to a
   per-node cap, so the listing's ``FOR EACH pair of hypotheses`` reaches
   across the whole pool rather than stopping at a cluster boundary. The
   cap is why it reaches every node rather than literally every pair; the
   second note below is the trade.

Two properties of that third step are load-bearing.

**The floor edges live under their own ``floor_edges`` key, not in
``edges``.** A floor weight is not a judgement, it is the absence of one,
and a consumer that prefers a graph edge over its own measurement must not
be handed a placeholder instead: ``evolution.evolve_context.find_nearest_peer``
reads a parent's edge weight in preference to token coverage, so folding
the two lists together would replace a real similarity measurement with
0.1 and let a near-duplicate child through the guard that exists to catch
it. ``tests/test_proximity_graph.py`` pins that separation through the
evolution helper itself.

**They are capped per node** (``PROXIMITY_FLOOR_NEIGHBOUR_CAP``, counting
judged and floor edges together). A total graph is O(n^2) edges in a
checkpoint that the single SQLite writer commits on every node boundary --
a 22-idea pool is 231 pairs -- so the pairs are taken in ring order over
sorted ids, nearest first, until each node reaches the cap. Clustered
nodes are already at or over it and gain nothing, which is the intended
priority: a judged edge always outranks a floor one.

Given a fixed clustering output the graph is fully deterministic: the same
input yields the same edges, weights, floor edges, and provenance metadata.
Every
persisted graph records its provenance — ``method``, ``version``, ``model``,
goal, and update time — so a reader can always tell which algorithm and
model produced it, and a future metric (embeddings included) can be
introduced as a new method/version without silently re-labeling old edges.

:func:`build_proximity_graph` is a pure function of the clustering output, so
the edge set, weights, and determinism are testable without an LLM.
"""

from __future__ import annotations

import dataclasses
import itertools
from typing import Any

# The documented local algorithm's fixed degree->weight mapping (see the
# module docstring): the LLM judges similarity qualitatively, and these
# weights are the numeric edge values the rest of the system consumes.
# Google leaves the proximity similarity metric unspecified (SSR §12), so
# these values are the documented local choice; tests pin them and the
# graph's determinism on fixed inputs.
_DEGREE_WEIGHT: dict[str, float] = {
    "high": 1.0,
    "medium": 0.6,
    "low": 0.3,
}

# Identifies how these edges were produced, versioned so a persisted graph
# records its provenance and can be recomputed/migrated later. A future
# similarity metric registers as a new method/version rather than redefining
# what "llm-cluster" version 1 means.
PROXIMITY_METHOD = "llm-cluster"
PROXIMITY_METHOD_VERSION = "1"

# The weight of an edge the clustering did not draw: strictly below the
# weakest judged degree, so a floor edge can never be mistaken for one the
# model related. Its degree label is its own word for the same reason.
_FLOOR_SIMILARITY = 0.1
_FLOOR_DEGREE = "none"

# Highest degree a node may reach once floor edges are added, counting its
# judged edges. Bounds the total graph at n * cap / 2 edges instead of the
# complete graph's n * (n - 1) / 2 -- 44 rather than 231 on a 22-idea pool --
# because the graph rides the run's SQLite checkpoint. Four keeps every node
# connected to its two nearest neighbours on each side of the ring.
PROXIMITY_FLOOR_NEIGHBOUR_CAP = 4

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


def _node_ids(survivors: SurvivorIndex) -> set[str]:
    """Every surviving hypothesis the graph may draw an edge between."""
    return set(survivors.by_index.values()) | set(survivors.by_text.values())


def _edge_degrees(
    edges: dict[frozenset[str], dict[str, Any]],
) -> dict[str, int]:
    """Counts how many edges each node already carries."""
    degrees: dict[str, int] = {}
    for edge in edges.values():
        for node in (edge["source"], edge["target"]):
            degrees[node] = degrees.get(node, 0) + 1
    return degrees


def _ring_pairs(ordered: list[str]) -> list[tuple[str, str]]:
    """Candidate floor pairs in ring order over sorted ids, nearest first.

    Sorted ids make the order deterministic, and taking every node's
    nearest ring neighbour before anyone's second spreads the cap evenly
    instead of forming cliques among whichever ids happen to sort first.
    """
    span = min(PROXIMITY_FLOOR_NEIGHBOUR_CAP // 2, len(ordered) - 1)
    return [
        (id_a, ordered[(position + step) % len(ordered)])
        for step in range(1, span + 1)
        for position, id_a in enumerate(ordered)
    ]


def _floor_edge_allowed(
    key: frozenset[str],
    edges: dict[frozenset[str], dict[str, Any]],
    floor: dict[frozenset[str], dict[str, Any]],
    degrees: dict[str, int],
) -> bool:
    """Whether this pair may take a floor edge (unconnected, under cap)."""
    if len(key) != 2 or key in edges or key in floor:
        return False
    return all(
        degrees.get(node, 0) < PROXIMITY_FLOOR_NEIGHBOUR_CAP for node in key
    )


def _accumulate_floor_edges(
    edges: dict[frozenset[str], dict[str, Any]], node_ids: set[str]
) -> dict[frozenset[str], dict[str, Any]]:
    """Connects the pairs the clustering left apart, up to the node cap.

    Args:
        edges: The judged edges already accumulated; read, never modified,
            so a judged pair is never given a floor weight.
        node_ids: The surviving hypotheses.

    Returns:
        Floor edges keyed by unordered pair.
    """
    floor: dict[frozenset[str], dict[str, Any]] = {}
    degrees = _edge_degrees(edges)
    for id_a, id_b in _ring_pairs(sorted(node_ids)):
        key = frozenset({id_a, id_b})
        if not _floor_edge_allowed(key, edges, floor, degrees):
            continue
        floor[key] = {
            "source": id_a,
            "target": id_b,
            "similarity": _FLOOR_SIMILARITY,
            "degree": _FLOOR_DEGREE,
            "cluster_id": None,
        }
        degrees[id_a] = degrees.get(id_a, 0) + 1
        degrees[id_b] = degrees.get(id_b, 0) + 1
    return floor


def _proximity_graph_meta(
    edges: dict[frozenset[str], dict[str, Any]],
    floor: dict[frozenset[str], dict[str, Any]],
    research_goal: str,
    model: str,
    updated_at: float,
) -> dict[str, Any]:
    """Builds the provenance metadata for a persisted proximity graph.

    ``node_count`` and ``edge_count`` keep counting the judged edges alone,
    which is what they have always meant; the floor edges are reported
    beside them with the cap that bounded them.
    """
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
        "floor_edge_count": len(floor),
        "floor_similarity": _FLOOR_SIMILARITY,
        "neighbour_cap": PROXIMITY_FLOOR_NEIGHBOUR_CAP,
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
        hypotheses in the same cluster), ``floor_edges`` (the capped
        low-weight connections for pairs no cluster related -- see the
        module docstring for why they are a separate key), and ``meta``
        (method/version/model/goal/update-time provenance). Edges are
        deduplicated per unordered pair, keeping the strongest similarity.
    """
    edges: dict[frozenset[str], dict[str, Any]] = {}
    for cluster in similarity_clusters:
        _accumulate_cluster_edges(edges, cluster, survivors)
    floor = _accumulate_floor_edges(edges, _node_ids(survivors))

    return {
        "edges": list(edges.values()),
        "floor_edges": list(floor.values()),
        "meta": _proximity_graph_meta(
            edges, floor, research_goal, model, updated_at
        ),
    }
