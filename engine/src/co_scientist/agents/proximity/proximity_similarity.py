"""Deterministic text similarity for the proximity graph.

Listing 06 quantifies over *every* pair of hypotheses, and the LLM clustering
call relates only the pairs it chose to put in a cluster. This module is what
answers the rest of the pairs without spending a single extra provider call.

The metric is the token *coverage* the rest of the codebase already uses
(``token_coverage`` below, which the evolution duplicate guard has always
measured with) rather than a new one: coverage divides by the measured text's
own tokens, never by the union, because a union denominator is dominated by
the longer side -- the failure that made both citation-verification bands
mathematically unreachable.

``pair_similarity`` is the symmetric form of it. Two hypotheses are peers of
comparable length, so neither side is privileged the way a claim is against
an abstract, and the two directional coverages are combined by their harmonic
mean. That is the Dice coefficient ``2|A & B| / (|A| + |B|)``, which is:

* equal to plain coverage when the two texts have the same token count, so
  the number means the same thing it means everywhere else in the codebase;
* never dominated by the longer side (Dice >= Jaccard for every input); and
* not satisfiable by containment alone -- the *maximum* of the two coverages
  scores a short generic hypothesis wholly contained in a long one at 1.0,
  which is exactly the false duplicate this graph must not assert.

``token_coverage`` lives here rather than in the evolution package that used
to own it so that both readers share one implementation: evolution consumes
the proximity graph, so evolution -> proximity is the import direction that
does not cycle. ``evolve_context`` re-exports it for existing importers.
"""

from __future__ import annotations

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
