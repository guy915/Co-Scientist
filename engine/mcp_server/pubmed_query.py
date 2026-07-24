"""Query relaxation for PubMed search (deterministic, offline).

PubMed's ``esearch`` ANDs every untagged term in a query, so a distilled
multi-term keyword query silently collapses toward zero hits as terms
accumulate -- and an empty result set leaves a hypothesis with no evidence to
ground against, so every one of its claims lands "insufficient". This module
produces a *relaxation ladder*: progressively broader variants of a query that
a caller issues in order until one returns enough results, so a search returns
something to ground against instead of nothing.

The module is pure and stdlib-only (no Biopython, no network) so the ladder and
the retry policy are unit-testable in isolation; the call sites supply the
actual ``esearch`` as a callable.
"""

from __future__ import annotations

from collections.abc import Callable

# A search returning at least this many ids is "enough"; below it the caller
# steps to the next, broader ladder rung. Clamped to the caller's retmax so a
# deliberately tiny retmax never forces relaxation it could not satisfy.
MIN_RESULTS_BEFORE_RELAX = 3

_BOOLEAN_OPERATORS = frozenset({"AND", "OR", "NOT"})

# An esearch runner: (query, retmax, recency_years) -> matching ids.
EsearchFn = Callable[[str, int, int], list[str]]


def _has_boolean_structure(query: str) -> bool:
    """Whether the query already carries an explicit AND/OR/NOT operator."""
    return any(t.upper() in _BOOLEAN_OPERATORS for t in query.split())


def or_relaxed_query(query: str) -> str | None:
    """Rewrite an implicitly-ANDed keyword query to OR its terms.

    Turns ``"kinase inhibition tumor growth"`` (every term required) into
    ``"kinase OR inhibition OR tumor OR growth"`` (any term), trading precision
    for recall so a starved query returns candidates the downstream grounding
    step can then re-filter by relevance.

    Returns:
        The OR-joined query, or None when it cannot be broadened this way --
        the query is a single term, or it already carries explicit boolean
        structure -- so the caller can skip a redundant retry.
    """
    if _has_boolean_structure(query):
        return None
    tokens = query.split()
    if len(tokens) < 2:
        return None
    return " OR ".join(tokens)


def relaxation_ladder(
    query: str, recency_years: int = 0
) -> list[tuple[str, int]]:
    """Ordered ``(query, recency_years)`` attempts, most precise to broadest.

    The ladder broadens along two axes in turn: first drop the recency window
    (same terms, all years), then OR the terms (broad recall, all years). A
    rung is included only when it differs from every rung before it, so the
    caller never issues a redundant network search.

    Args:
        query: The distilled keyword query.
        recency_years: The initial publication-date window (0 = none).

    Returns:
        The attempts to try in order.
    """
    ladder: list[tuple[str, int]] = [(query, recency_years)]
    if recency_years > 0:
        ladder.append((query, 0))
    broadened = or_relaxed_query(query)
    if broadened is not None:
        ladder.append((broadened, 0))
    return ladder


def search_with_relaxation(
    query: str,
    retmax: int,
    recency_years: int,
    esearch: EsearchFn,
) -> list[str]:
    """Run ``esearch`` down the relaxation ladder until results suffice.

    Issues each ladder rung in turn and returns the first whose id count meets
    the (retmax-clamped) minimum. If no rung clears the bar, the first
    non-empty rung's ids are returned -- some evidence beats none -- and only a
    query that matches nothing at any breadth yields an empty list. A query
    that returns enough on the first rung costs exactly one ``esearch`` call;
    the extra calls are paid only by the starved queries that need them.

    Args:
        query: The distilled keyword query.
        retmax: Maximum ids to request per attempt.
        recency_years: The initial publication-date window (0 = none).
        esearch: Runs one search: ``(query, retmax, recency_years) -> ids``.

    Returns:
        The chosen attempt's ids (possibly empty).
    """
    threshold = min(MIN_RESULTS_BEFORE_RELAX, retmax)
    best: list[str] = []
    for term, recency in relaxation_ladder(query, recency_years):
        ids = esearch(term, retmax, recency)
        if len(ids) >= threshold:
            return ids
        if ids and not best:
            best = ids
    return best
