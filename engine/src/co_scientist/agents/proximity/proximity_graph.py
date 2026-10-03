"""Construct the proximity graph from judged and deterministic similarities."""

from __future__ import annotations

import dataclasses
import itertools
from collections.abc import Mapping
from typing import Any

# Similarity is rounded to this many decimals before anything sees it, so the
# admission decision (``PROXIMITY_EDGE_FLOOR``) and the persisted number are
# the same number, and so an edge's JSON is a bounded ~5 characters rather
# than a full float repr on every one of a large pool's pairs.
_SIMILARITY_DECIMALS = 3


def _tokens(text: str) -> set[str]:
    """Return the lowercased word-token set of a text."""
    return set(text.lower().split())


def token_coverage(text: str, reference: str) -> float:
    """Fraction of ``text``'s unique tokens that also appear in ``reference``.

    Coverage, not Jaccard: a union denominator is dominated by the longer
    side, so a short text perfectly contained in a long one still scores
    near ``len(text) / len(reference)`` -- which is how both duplicate bands
    became unreachable and every real refinement read as distinct. Dividing
    by the derived text's own tokens measures how much of it the peer
    already says, whatever the peer's length.

    Args:
        text: The derived text whose coverage is measured (the refinement).
        reference: The peer text checked for containing it.

    Returns:
        Coverage score between 0 and 1; 0.0 for an empty ``text``.
    """
    words = _tokens(text)
    if not words:
        return 0.0
    return len(words & _tokens(reference)) / len(words)


def pair_similarity(text_a: str, text_b: str) -> float:
    """Symmetric similarity of two hypothesis texts, in [0, 1].

    The harmonic mean of the two directional ``token_coverage`` readings
    (equivalently the Dice coefficient); see the module docstring for why
    that symmetric form and not the minimum, the maximum, or Jaccard.
    Verbatim-identical texts score 1.0 and texts sharing no vocabulary
    score 0.0, whatever their lengths.

    Args:
        text_a: One hypothesis's text.
        text_b: The other hypothesis's text.

    Returns:
        Rounded similarity in [0, 1]; 0.0 when either text has no tokens.
    """
    coverage_a = token_coverage(text_a, text_b)
    coverage_b = token_coverage(text_b, text_a)
    total = coverage_a + coverage_b
    if total == 0.0:
        return 0.0
    return round(2 * coverage_a * coverage_b / total, _SIMILARITY_DECIMALS)


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


# Identifies an edge this module measured rather than the model judging it.
# Both kinds share the ``edges`` list, so each edge names its own method and
# ``is_judged_edge`` is what a reader needing a judgement asks. The degree
# label is its own word for the same reason: it can never be read as one of
# the qualitative bands ``_DEGREE_WEIGHT`` maps.
PROXIMITY_COMPUTED_METHOD = "token-dice"

PROXIMITY_COMPUTED_DEGREE = "computed"


# Similarity a measured pair must reach to be stored. Every pair is measured;
# this decides which measurements are worth a row.
#
# The arithmetic. Pairs are n * (n - 1) / 2 over a tier's idea ceiling
# (``run_modes.RUN_TIER_DEFAULTS``): express 12 -> 66, standard 32 -> 496,
# extended 60 -> 1770, ultra 96 -> 4560. An edge measures ~190 bytes of JSON
# in the run's checkpoint and about the same as a ``proximity_edges`` row, so
# a complete ultra graph is ~0.87 MB per checkpoint plus ~0.87 MB of rows
# that outlive the run -- against a 0.5 GB volume that has filled before, and
# one INSERT per edge inside the drain's transaction.
#
# Measured by building this graph over ten real runs in the repo's local
# stores (8-24 ideas, 28-276 pairs each): the pair distribution has a median
# of 0.19, and this floor retains 24-40% of pairs. That is ~1600 edges
# (~0.3 MB each side) on ultra and ~80 on a 22-idea pool -- denser than the
# 44 the previous capped placeholder scheme produced, and about a third of
# the complete graph. The worst case is still the complete graph, and that
# is the pool where every one of those edges is a real near-duplicate
# finding.
PROXIMITY_EDGE_FLOOR = 0.25


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
    """The surviving hypotheses, and the two ways a member resolves to one.

    Every table here covers the dedup survivors only, so a member the
    proximity node has just dropped resolves to nothing and never becomes a
    graph node. The two resolution tables are carried together because their
    order matters: index first, text as the fallback, exactly as
    ``proximity_dedup._match_cluster_member`` resolves the same members.
    ``texts`` rides with them because measuring the pairs the clustering
    left unjudged needs the same population those tables resolve into.

    Attributes:
        by_index: Prompt position -> hypothesis id. Positions are the ones
            ``proximity._prepare_hypotheses_for_analysis`` numbered, so a
            removed duplicate leaves its position absent rather than
            renumbering the survivors.
        by_text: ``member_match_key`` -> hypothesis id, for responses that
            echo a member's text instead of (or as well as) its index.
        texts: Hypothesis id -> its full text. A survivor missing from this
            table is measured against nothing, rather than measured as
            unrelated to everything -- which is why the field is required
            rather than defaulted: a call site that forgot it would produce
            a graph with no computed edges and no error to say so.
    """

    by_index: dict[int, str]
    by_text: dict[str, str]
    texts: Mapping[str, str]


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
                "method": PROXIMITY_METHOD,
            }


def is_judged_edge(edge: Mapping[str, Any]) -> bool:
    """Whether this edge carries the model's own similarity judgement.

    A missing ``method`` reads as judged on purpose: an edge under ``edges``
    in a graph checkpointed before computed edges existed came from the
    clustering call, and demoting it on resume would silently withdraw a
    real judgement from every reader that asks for one.

    Args:
        edge: One entry of a persisted graph's ``edges``.

    Returns:
        True for a clustering edge, False for a computed one.
    """
    return bool(edge.get("method", PROXIMITY_METHOD) == PROXIMITY_METHOD)


def _node_ids(survivors: SurvivorIndex) -> set[str]:
    """Every surviving hypothesis the graph may draw an edge between."""
    return set(survivors.by_index.values()) | set(survivors.by_text.values())


def _computed_edges(
    judged: dict[frozenset[str], dict[str, Any]],
    node_ids: set[str],
    texts: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Measures every pair the clustering left unjudged, above the floor.

    Pairs are walked in sorted-id order so the result is deterministic, and
    a hypothesis with no text contributes no pair rather than a zero-weight
    one -- there is nothing to have measured.

    Args:
        judged: The clustering's edges; read only, so a judged pair is never
            given a computed weight.
        node_ids: The surviving hypotheses.
        texts: Hypothesis id -> its text.

    Returns:
        The computed edges, in sorted pair order.
    """
    edges: list[dict[str, Any]] = []
    for id_a, id_b in itertools.combinations(sorted(node_ids), 2):
        if frozenset({id_a, id_b}) in judged:
            continue
        similarity = pair_similarity(texts.get(id_a, ""), texts.get(id_b, ""))
        if similarity < PROXIMITY_EDGE_FLOOR:
            continue
        edges.append(
            {
                "source": id_a,
                "target": id_b,
                "similarity": similarity,
                "degree": PROXIMITY_COMPUTED_DEGREE,
                "cluster_id": None,
                "method": PROXIMITY_COMPUTED_METHOD,
            }
        )
    return edges


def _proximity_graph_meta(
    edges: dict[frozenset[str], dict[str, Any]],
    computed: list[dict[str, Any]],
    research_goal: str,
    model: str,
    updated_at: float,
) -> dict[str, Any]:
    """Builds the provenance metadata for a persisted proximity graph.

    ``node_count`` and ``edge_count`` keep counting the judged edges alone,
    which is what they have always meant; the computed edges are reported
    beside them with the floor that admitted them.
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
        "computed_edge_count": len(computed),
        "computed_method": PROXIMITY_COMPUTED_METHOD,
        "edge_floor": PROXIMITY_EDGE_FLOOR,
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
        survivors: The dedup survivors: the resolution tables that map a
            cluster member to a hypothesis id, and their texts.
        research_goal: The goal context the graph was computed under.
        model: The model that produced the clustering (provenance).
        updated_at: Unix timestamp when the graph was computed.

    Returns:
        A graph dict with ``edges`` (undirected weighted edges, judged ones
        first, each naming the ``method`` that produced it -- see the module
        docstring) and ``meta`` (method/version/model/goal/update-time
        provenance). Edges are deduplicated per unordered pair, keeping the
        strongest similarity, and a judged pair is never also computed.
    """
    judged: dict[frozenset[str], dict[str, Any]] = {}
    for cluster in similarity_clusters:
        _accumulate_cluster_edges(judged, cluster, survivors)
    computed = _computed_edges(judged, _node_ids(survivors), survivors.texts)

    return {
        "edges": list(judged.values()) + computed,
        "meta": _proximity_graph_meta(
            judged, computed, research_goal, model, updated_at
        ),
    }
