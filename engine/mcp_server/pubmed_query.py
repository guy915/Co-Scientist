"""Query relaxation for PubMed search (deterministic, offline).

PubMed's ``esearch`` ANDs every untagged term in a query, so a distilled
multi-term keyword query silently collapses toward zero hits as terms
accumulate -- and an empty result set leaves a hypothesis with no evidence to
ground against, so every one of its claims lands "insufficient". This module
produces a *relaxation ladder*: progressively broader variants of a query that
a caller issues in order until one returns enough results, so a search returns
something to ground against instead of nothing.

The exact rung is left as PubMed's own automatic term mapping (ATM) receives
it, deliberately untagged: ATM already resolves an untagged phrase against a
MeSH heading before falling back to per-word ANDing, and that phrase-level
translation beats a naive per-word ``[tiab]``/``[mesh]`` split -- measured
live against three realistic literature-review queries, tagging the exact
rung word-by-word cut an already-working query's hits from 257 to 20 and from
92 to 75, while the untouched, untagged rung already returns 0-1 hits on the
genuinely starved query the ladder exists to broaden. Once broadening is
already trading precision for recall -- the OR rung, once ANDing has failed
-- there is no phrase left to lose, so ``or_relaxed_query`` field-tags each
term there (``[tiab]`` OR ``[mesh]``, see ``field_tag_terms``): it does not
raise the raw hit count over an untagged OR (both already return the
retmax-capped maximum on a starved query), but it anchors every match to the
paper's own title/abstract text or its indexed MeSH heading rather than
whatever field ATM's own broader expansion happens to touch.

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


def _field_tagged_term(term: str) -> str:
    """Tag one term to match either PubMed's text words or its MeSH heading.

    ``[tiab]`` matches the term against the title/abstract text directly;
    ``[mesh]`` matches it against PubMed's own indexed MeSH heading for the
    concept. ORing the two lets the term hit either without going through
    PubMed's automatic term mapping, whose silent fallback -- break an
    unmatched multi-word phrase into single words, then AND them -- is the
    root cause this module works around (see the module docstring).

    Args:
        term: A single query token (no internal whitespace).

    Returns:
        The parenthesized, field-tagged alternation for this term.
    """
    return f"({term}[tiab] OR {term}[mesh])"


def field_tag_terms(query: str, joiner: str) -> str:
    """Field-tag every term of a keyword query and rejoin with ``joiner``.

    Args:
        query: The keyword query, terms separated by spaces.
        joiner: How to recombine the tagged terms (e.g. ``" AND "`` or
            ``" OR "``).

    Returns:
        The field-tagged query, or ``query`` unchanged when it already
        carries explicit boolean structure (AND/OR/NOT) -- re-tokenizing and
        re-tagging it would fight the caller's own boolean intent rather
        than extend it -- or has no terms to tag.
    """
    if _has_boolean_structure(query):
        return query
    terms = query.split()
    if not terms:
        return query
    return joiner.join(_field_tagged_term(term) for term in terms)


def or_relaxed_query(query: str) -> str | None:
    """Rewrite an implicitly-ANDed keyword query to a field-tagged OR.

    Turns ``"kinase inhibition tumor growth"`` (every term required) into an
    OR of each term's own tagged alternation, trading precision for recall
    so a starved query returns candidates the downstream grounding step can
    then re-filter by relevance.

    Returns:
        The OR-joined, field-tagged query, or None when it cannot be
        broadened this way -- the query is a single term, or it already
        carries explicit boolean structure -- so the caller can skip a
        redundant retry.
    """
    if _has_boolean_structure(query):
        return None
    tokens = query.split()
    if len(tokens) < 2:
        return None
    return field_tag_terms(query, " OR ")


def relaxation_ladder(
    query: str, recency_years: int = 0
) -> list[tuple[str, int]]:
    """Ordered ``(query, recency_years)`` attempts, most precise to broadest.

    The ladder broadens along two axes in turn: first drop the recency window
    (same terms, all years, still exactly as PubMed's own automatic term
    mapping receives it -- see the module docstring for why this rung is
    deliberately left untagged), then field-tag and OR the terms (broad
    recall, all years). A rung is included only when it differs from every
    rung before it, so the caller never issues a redundant network search.

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
