"""Context sampling and text-similarity helpers for the Evolve node."""

import logging
import random

from co_scientist.models import Hypothesis, rank_by_elo

logger = logging.getLogger(__name__)


def _hypothesis_texts(hypotheses: list[Hypothesis]) -> list[str]:
    """Extract the .text field from a list of hypotheses."""
    return [h.text for h in hypotheses]


def _sample_up_to(pool: list[Hypothesis], count: int) -> list[Hypothesis]:
    """Randomly sample up to count items from pool (all of it if smaller).

    No-op (returns []) on an empty pool, matching the caller's original
    `... if pool else []` short-circuit so no random state is consumed when
    there is nothing to sample from.
    """
    if not pool:
        return []
    return random.sample(pool, min(count, len(pool)))


def _sample_top_and_random(
    others_by_elo: list[Hypothesis], top_count: int, random_count: int
) -> list[Hypothesis]:
    """Combine the top-Elo performers with a random sample of the rest.

    Args:
        others_by_elo: Candidate hypotheses, already ranked by Elo.
        top_count: Number of top-Elo performers to keep unconditionally.
        random_count: Number of additional hypotheses to sample randomly
            from the remainder.

    Returns:
        The top performers followed by the randomly sampled remainder.
    """
    top_performers = others_by_elo[:top_count]
    remaining = others_by_elo[top_count:]
    sampled_others = _sample_up_to(remaining, random_count)

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
) -> list[str]:
    """Strategically sample a subset of other hypotheses for evolution context.

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

    Returns:
        List of hypothesis texts to use as context
    """
    # Filter out the current hypothesis
    others = [h for h in all_hypotheses if h.text != exclude_hypothesis.text]

    if len(others) <= max_context:
        # Small pool, include all
        return _hypothesis_texts(others)

    if ranked_hypotheses is None:
        others_by_elo = rank_by_elo(others)
    else:
        others_by_elo = [
            h for h in ranked_hypotheses if h.text != exclude_hypothesis.text
        ]

    # Top 5 by Elo (avoid copying winners) + up to 10 random (diversity).
    context_hypotheses = _sample_top_and_random(others_by_elo, 5, 10)

    return _hypothesis_texts(context_hypotheses)


def calculate_text_similarity(text1: str, text2: str) -> float:
    """Calculates simple similarity between two texts.

    This is a basic implementation using word overlap; embeddings or a more
    sophisticated similarity metric would be a production-grade upgrade.

    Args:
        text1: First text
        text2: Second text

    Returns:
        Similarity score between 0 and 1
    """
    words1 = set(text1.lower().split())
    words2 = set(text2.lower().split())

    # Degenerate case: an empty text has no words to overlap with, so
    # treat it as maximally dissimilar rather than dividing by zero below.
    if not words1 or not words2:
        return 0.0

    # Jaccard similarity: size of the word-set intersection over the
    # word-set union. Cheap and order-insensitive, but purely lexical (no
    # synonym/paraphrase awareness) -- see the docstring note about
    # upgrading to embeddings.
    intersection = words1.intersection(words2)
    union = words1.union(words2)

    return len(intersection) / len(union) if union else 0.0


def _find_most_similar(
    refined_text: str, other_hypotheses_texts: list[str]
) -> tuple[float, str | None]:
    """Finds the other hypothesis text most similar to the refined text.

    Guards against evolution converging this hypothesis toward one of the
    peers it was shown as diversity context, using the same word-overlap
    metric as calculate_text_similarity.

    Args:
        refined_text: The newly evolved hypothesis text.
        other_hypotheses_texts: Strategically sampled subset of other
            hypotheses (max 15).

    Returns:
        Tuple of (max_similarity, most_similar_text); most_similar_text is
        None if other_hypotheses_texts is empty.
    """
    max_similarity = 0.0
    most_similar_text = None
    for other_text in other_hypotheses_texts:
        similarity = calculate_text_similarity(refined_text, other_text)
        if similarity > max_similarity:
            max_similarity = similarity
            most_similar_text = other_text
    return max_similarity, most_similar_text
