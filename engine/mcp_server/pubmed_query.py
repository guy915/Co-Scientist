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

**Broadening has to keep the subject, which is why there is a rung between
the two.** ORing every term is not a broader version of the question, it is
a different question: measured live, the six-term query "PHGDH knockdown
osimertinib resistance EGFR adenocarcinoma" ANDs to 0 hits and ORs to
1,966,502 -- and a caller reading the first three of those got a gastric
cancer case report, a uterine leiomyosarcoma series and a paper on
antimicrobial resistance, which matched "adenocarcinoma" and "resistance"
and nothing else. There is no downstream relevance filter to save it when
the read budget is three documents, so those three *are* the evidence, and
the reading model spends its call explaining that none of them are on
topic. ``anchored_relaxed_query`` is the middle rung: the leading terms
stay required, the rest relax to an OR. On the same query it returns 18
hits rather than 0 or two million.

The module is pure and stdlib-only (no Biopython, no network) so the ladder and
the retry policy are unit-testable in isolation; the call sites supply the
actual ``esearch`` as a callable.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_MAX_TRACE_IDS = 9

# A search returning at least this many ids is "enough"; below it the caller
# steps to the next, broader ladder rung. Clamped to the caller's retmax so a
# deliberately tiny retmax never forces relaxation it could not satisfy.
MIN_RESULTS_BEFORE_RELAX = 3

_BOOLEAN_OPERATORS = frozenset({"AND", "OR", "NOT"})

# An esearch runner: (query, retmax, recency_years) -> matching ids.
EsearchFn = Callable[[str, int, int], list[str]]


def _has_boolean_structure(query: str) -> bool:
    """Whether the query carries an explicit uppercase Boolean operator.

    PubMed reserves uppercase AND, OR, and NOT for Boolean operators; their
    lowercase forms are ordinary search terms (NCBI PubMed Help:
    https://pubmed.ncbi.nlm.nih.gov/help/).
    """
    return any(token in _BOOLEAN_OPERATORS for token in query.split())


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


# Leading terms an anchored rung keeps required. Two, because one is not
# enough to hold a topic (anchoring the same query on "PHGDH" alone
# returns 170 hits against 18 for the leading pair) and three is the
# arity at which these queries already AND to zero, which is the state
# the rung exists to leave.
_ANCHOR_TERMS = 2


def anchored_relaxed_query(query: str) -> str | None:
    """Relax a keyword query while keeping its leading terms required.

    The query-writing prompt asks for the question's subject first, so the
    leading terms are the ones a relaxation cannot drop without answering
    a different question. They stay ANDed; everything after them becomes a
    single OR group, which is where the recall comes from.

    Args:
        query: The distilled keyword query.

    Returns:
        The anchored query, or None when there is nothing to relax this
        way -- the query already carries explicit boolean structure, or
        has no terms past the anchors to loosen -- so the caller can skip
        a redundant search.
    """
    if _has_boolean_structure(query):
        return None
    tokens = query.split()
    if len(tokens) <= _ANCHOR_TERMS:
        return None
    anchors = " AND ".join(
        _field_tagged_term(term) for term in tokens[:_ANCHOR_TERMS]
    )
    loosened = " OR ".join(
        _field_tagged_term(term) for term in tokens[_ANCHOR_TERMS:]
    )
    return f"{anchors} AND ({loosened})"


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

    The ladder broadens along three axes in turn: first drop the recency
    window (same terms, all years, still exactly as PubMed's own automatic
    term mapping receives it -- see the module docstring for why this rung is
    deliberately left untagged), then relax everything except the leading
    terms, then field-tag and OR every term (broadest recall, all years). A
    rung is included only when it differs from every rung before it, so the
    caller never issues a redundant network search.

    The anchored rung sits in the middle because the two rungs around it are
    further apart than they look: the queries this ladder receives AND to
    zero and OR to millions, with nothing in between (module docstring). It
    is where a broadened search still answers the question it was given.

    Args:
        query: The distilled keyword query.
        recency_years: The initial publication-date window (0 = none).

    Returns:
        The attempts to try in order.
    """
    ladder: list[tuple[str, int]] = [(query, recency_years)]
    if recency_years > 0:
        ladder.append((query, 0))
    for rung in (anchored_relaxed_query(query), or_relaxed_query(query)):
        if rung is not None and rung not in {term for term, _ in ladder}:
            ladder.append((rung, 0))
    return ladder


def _relaxation_rung_type(
    rung_index: int, query: str, term: str, recency_years: int
) -> str:
    if rung_index == 1:
        return "exact"
    if term == query and recency_years == 0:
        return "recency_dropped"
    return "anchored" if " AND (" in term else "or"


def _record_attempt(
    trace: dict[str, Any] | None, attempt: dict[str, Any] | None
) -> None:
    """Records one application-level ESearch rung without query text.

    Bio.Entrez's internal transport retries are below this seam and are not
    visible as separate attempts here.
    """
    if trace is not None and attempt is not None:
        trace.setdefault("attempts", []).append(attempt)


def _new_attempt(
    trace: dict[str, Any] | None,
    rung_index: int,
    rung_type: str,
    recency_years: int,
    retmax: int,
) -> dict[str, Any]:
    return {
        "rung_index": rung_index,
        "rung_type": rung_type,
        "operation": "esearch",
        "recency_years": recency_years,
        "retmax": retmax,
        "sort": trace["sort"] if trace is not None else None,
    }


def _record_failed_attempt(
    trace: dict[str, Any] | None,
    attempt: dict[str, Any],
    exc: Exception,
) -> None:
    attempt.update(
        {"count": 0, "first_ids": [], "error_type": type(exc).__name__}
    )
    _record_attempt(trace, attempt)
    if trace is None:
        return
    trace["selected"] = None
    trace["threshold_met"] = False
    trace["error"] = {"stage": "esearch", "type": type(exc).__name__}


def _record_selected_rung(
    trace: dict[str, Any] | None,
    selected: tuple[int, str, str, list[str]] | None,
    threshold_met: bool,
) -> None:
    """Records which relaxation rung supplied the returned identifiers."""
    if trace is None:
        return
    trace["selected"] = (
        {
            "rung_index": selected[0],
            "rung_type": selected[1],
            "count": len(selected[3]),
            "ids": selected[3][:_MAX_TRACE_IDS],
            "sort": trace["sort"],
        }
        if selected
        else None
    )
    trace["threshold_met"] = threshold_met


def search_with_relaxation(
    query: str,
    retmax: int,
    recency_years: int,
    esearch: EsearchFn,
    trace: dict[str, Any] | None = None,
) -> list[str]:
    """Run ``esearch`` down the relaxation ladder until results suffice.

    Issues each ladder rung in turn and stops at the first whose id count meets
    the (retmax-clamped) minimum. The ids of every rung tried are merged in
    rung order, deduplicated and capped at ``retmax``, so a precise rung's few
    on-target hits survive a broader rung that clears the bar. If no rung
    clears it the merged ids are still returned -- some evidence beats none --
    and only a query that matches nothing at any breadth yields an empty
    list. A query
    that returns enough on the first rung costs exactly one ``esearch`` call;
    the extra calls are paid only by the starved queries that need them.

    Args:
        query: The distilled keyword query.
        retmax: Maximum ids to request per attempt.
        recency_years: The initial publication-date window (0 = none).
        esearch: Runs one search: ``(query, retmax, recency_years) -> ids``.
        trace: Optional bounded record of each application-level search rung.

    Returns:
        The merged ids of the rungs tried (possibly empty).
    """
    threshold = min(MIN_RESULTS_BEFORE_RELAX, retmax)
    merged: list[str] = []
    fallback: tuple[int, str, str] | None = None
    for rung_index, (term, recency) in enumerate(
        relaxation_ladder(query, recency_years), start=1
    ):
        rung_type = _relaxation_rung_type(rung_index, query, term, recency)
        attempt = _new_attempt(trace, rung_index, rung_type, recency, retmax)
        try:
            ids = esearch(term, retmax, recency)
        except Exception as exc:
            _record_failed_attempt(trace, attempt, exc)
            raise
        attempt.update({"count": len(ids), "first_ids": ids[:_MAX_TRACE_IDS]})
        _record_attempt(trace, attempt)
        merged.extend(i for i in dict.fromkeys(ids) if i not in merged)
        del merged[retmax:]
        if len(ids) >= threshold:
            _record_selected_rung(
                trace,
                (rung_index, rung_type, term, merged),
                threshold_met=True,
            )
            return merged
        if ids and fallback is None:
            fallback = (rung_index, rung_type, term)
    _record_selected_rung(
        trace, (*fallback, merged) if fallback else None, threshold_met=False
    )
    return merged
