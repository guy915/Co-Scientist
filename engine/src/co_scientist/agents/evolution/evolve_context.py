"""Context sampling, partner selection, and similarity helpers for Evolve."""

import logging
import random
from collections.abc import Sequence
from typing import Any

from co_scientist.agents.evolution.evolution_operators import (
    EvolutionOperator,
)
from co_scientist.agents.proximity.proximity_graph import is_judged_edge
from co_scientist.agents.proximity.proximity_similarity import (
    token_coverage as token_coverage,
)
from co_scientist.models import Hypothesis, rank_by_elo

# ``token_coverage`` is re-exported above rather than defined here: the
# proximity graph measures its own pairs with the same metric, and evolution
# consumes that graph, so proximity is the end of the dependency that can own
# it without a cycle. Existing importers keep this path.

logger = logging.getLogger(__name__)


def _sample_up_to(
    pool: list[Hypothesis], count: int, rng: random.Random
) -> list[Hypothesis]:
    """Sample up to count items from pool (all of it if smaller).

    No-op (returns []) on an empty pool, matching the caller's original
    `... if pool else []` short-circuit so no random state is consumed when
    there is nothing to sample from. Draws from the caller's seeded RNG
    rather than the process-global one, so a run's sampling is reproducible
    and concurrent runs cannot perturb each other's draws.
    """
    if not pool:
        return []
    return rng.sample(pool, min(count, len(pool)))


def _sample_top_and_random(
    others_by_elo: list[Hypothesis],
    top_count: int,
    random_count: int,
    rng: random.Random,
) -> list[Hypothesis]:
    """Combine the top-Elo performers with a seeded random sample of the rest.

    Args:
        others_by_elo: Candidate hypotheses, already ranked by Elo.
        top_count: Number of top-Elo performers to keep unconditionally.
        random_count: Number of additional hypotheses to sample randomly
            from the remainder.
        rng: Seeded RNG the random draw uses.

    Returns:
        The top performers followed by the randomly sampled remainder.
    """
    top_performers = others_by_elo[:top_count]
    remaining = others_by_elo[top_count:]
    sampled_others = _sample_up_to(remaining, random_count, rng)

    logger.debug(
        "sampled %s context hypotheses (top %s + %s random) from %s total",
        len(top_performers) + len(sampled_others),
        top_count,
        len(sampled_others),
        len(others_by_elo),
    )

    return top_performers + sampled_others


def sample_context_hypotheses(
    all_hypotheses: list[Hypothesis],
    exclude_hypothesis: Hypothesis,
    max_context: int = 15,
    ranked_hypotheses: list[Hypothesis] | None = None,
    rng: random.Random | None = None,
) -> list[Hypothesis]:
    """Strategically sample the other hypotheses for evolution context.

    To prevent token explosion with large hypothesis pools, we sample:
    - Top 5 by Elo rating (avoid copying winners)
    - Up to 10 random samples from the rest (diversity check)

    Args:
        all_hypotheses: all hypotheses being evolved
        exclude_hypothesis: the hypothesis being evolved (exclude from context)
        max_context: maximum context hypotheses to include (default 15)
        ranked_hypotheses: all_hypotheses already ordered by rank_by_elo,
            when the caller has it. Dropping one member cannot reorder the
            rest, so a caller sampling context for every member of a pool
            ranks it once here rather than once per member. Ranked locally
            when omitted, and only consulted on the large-pool branch --
            the small-pool branch deliberately keeps the caller's order.
        rng: Seeded RNG for the random half of the sample. Callers thread a
            run-scoped seed so the diversity context is reproducible; an
            unseeded RNG is created only when none is supplied.

    Returns:
        The sampled hypotheses (objects, not texts) to use as context.
    """
    # Filter out the current hypothesis
    others = [h for h in all_hypotheses if h.text != exclude_hypothesis.text]

    if len(others) <= max_context:
        # Small pool, include all
        return others

    if ranked_hypotheses is None:
        others_by_elo = rank_by_elo(others)
    else:
        others_by_elo = [
            h for h in ranked_hypotheses if h.text != exclude_hypothesis.text
        ]

    # Top 5 by Elo (avoid copying winners) + up to 10 random (diversity).
    draw = rng if rng is not None else random.Random()
    return _sample_top_and_random(others_by_elo, 5, 10, draw)


def combination_partners(
    ranked_hypotheses: Sequence[Hypothesis],
    parent: Hypothesis,
    max_partners: int = 2,
) -> list[Hypothesis]:
    """Select the top-ranked peers a parent may combine with or borrow from.

    The paper's combination and inspiration strategies operate on the
    top-ranked hypotheses, so partners are simply the strongest peers other
    than the parent itself, in Elo order. Deterministic -- no sampling.

    Args:
        ranked_hypotheses: The whole pool, ordered by rank_by_elo.
        parent: The hypothesis being evolved; never its own partner.
        max_partners: Most partners to return (default 2).

    Returns:
        Up to ``max_partners`` peers; empty only for a one-idea pool.
    """
    partners = [h for h in ranked_hypotheses if h.text != parent.text]
    return partners[:max_partners]


def proximity_weights_for(
    proximity_graph: dict[str, Any] | None, hypothesis_id: str
) -> dict[str, float]:
    """Map one hypothesis's judged proximity-graph neighbors to their weights.

    The persisted graph is undirected, so both edge orientations resolve.

    Only the clustering's own edges are read. The graph also carries the
    similarity it *computed* for the pairs the clustering left unjudged, with
    the same token-coverage metric ``find_nearest_peer`` falls back to -- but
    computed against the parent, not against the child being guarded, so
    reading one would answer a question about the parent's neighbourhood
    where the caller asked about the child's. The fallback measures the child
    directly, which is strictly better information for that decision.
    """
    weights: dict[str, float] = {}
    for edge in (proximity_graph or {}).get("edges", []):
        if not is_judged_edge(edge):
            continue
        source = edge.get("source")
        target = edge.get("target")
        similarity = edge.get("similarity")
        if source == hypothesis_id and target is not None:
            weights[target] = float(similarity or 0.0)
        elif target == hypothesis_id and source is not None:
            weights[source] = float(similarity or 0.0)
    return weights


def find_nearest_peer(
    refined_text: str,
    parent_id: str,
    peers: list[Hypothesis],
    proximity_graph: dict[str, Any] | None = None,
) -> tuple[float, Hypothesis | None]:
    """The peer a refinement is most similar to, and how similar.

    Per peer the similarity prefers the persisted proximity graph's
    weighted, LLM-judged edge between the parent and that neighbor when one
    exists (a judged edge only -- see ``proximity_weights_for``): the child
    of a refinement stays in its parent's semantic neighborhood, and the
    graph's judgement is what proximity dedup itself
    trusts. Peers without one fall back to token coverage of the
    refined text by the peer's text (never union-based Jaccard, which the
    longer side dominates).

    Args:
        refined_text: The newly evolved hypothesis text.
        parent_id: Id of the hypothesis the refinement was evolved from.
        peers: Candidate peers to compare against.
        proximity_graph: The run's persisted proximity graph, when built.

    Returns:
        Tuple of (max_similarity, nearest peer); the peer is None when
        ``peers`` is empty.
    """
    weights = proximity_weights_for(proximity_graph, parent_id)
    max_similarity = 0.0
    nearest: Hypothesis | None = None
    for peer in peers:
        weight = weights.get(peer.id)
        similarity = (
            weight
            if weight is not None
            else token_coverage(refined_text, peer.text)
        )
        if similarity > max_similarity:
            max_similarity = similarity
            nearest = peer
    return max_similarity, nearest


_PARTNER_SECTION_HEADERS = {
    EvolutionOperator.COMBINATION: (
        "## Combination Partners\n"
        "These top-ranked hypotheses are designated to be merged with the "
        "parent. Their full fields follow, untruncated. Identify any partner "
        "you merge by its positional index in your response; never echo a "
        "partner's text back."
    ),
    EvolutionOperator.INSPIRATION: (
        "## Inspiration Sources\n"
        "These top-ranked hypotheses are existing approaches you may borrow "
        "mechanism or structure from. Their full fields follow, untruncated."
    ),
    # Out-of-box renders published A.7, whose own sentence already
    # introduces these as the concepts to draw analogy from, so the header
    # only labels the block; the empty-pool note below still applies.
    EvolutionOperator.OUT_OF_BOX: "## Provided Concepts",
}


def _format_partner_context(
    partners: tuple[Hypothesis, ...], operator: EvolutionOperator
) -> str:
    """Render the full-field reference block for this task's partners.

    Whole fields, never truncated: combination and inspiration operate on
    the partners' actual mechanisms and experiments, and a snippet view was
    one of the ways multi-parent combination stayed structurally crippled.

    Returns:
        The partner section, or a placeholder when the task has no partners.
    """
    header = _PARTNER_SECTION_HEADERS.get(operator)
    if header is None:
        return "(No partners are assigned to this operator.)"
    if not partners:
        return (
            f"{header}\n\n"
            "(No partners are available in this pool; work from the parent "
            "and the context already provided.)"
        )
    sections = [header]
    for index, partner in enumerate(partners, start=1):
        sections.append(
            f"### Partner {index}\n"
            f"**Hypothesis:** {partner.text}\n"
            f"**Explanation:** {partner.explanation or 'Not provided.'}\n"
            f"**Mechanism grounding:** "
            f"{partner.literature_grounding or 'Not provided.'}\n"
            f"**Experiment:** {partner.experiment or 'Not provided.'}"
        )
    return "\n\n".join(sections)
