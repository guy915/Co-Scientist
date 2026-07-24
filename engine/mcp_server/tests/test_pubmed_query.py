"""Tests for the PubMed query-relaxation ladder (mcp_server/pubmed_query.py).

PubMed ANDs every untagged term, so a distilled multi-term query collapses
toward zero hits. These prove the relaxation policy that keeps a starved query
returning candidates to ground against: OR-broadening a single-term-required
query, the precise-to-broad ladder, and the runner that stops at the first rung
returning enough while paying only one search when the first rung suffices.
"""

from __future__ import annotations

from mcp_server.pubmed_query import (
    MIN_RESULTS_BEFORE_RELAX,
    or_relaxed_query,
    relaxation_ladder,
    search_with_relaxation,
)


def test_or_relaxes_a_multi_term_query() -> None:
    """A space-separated (implicitly ANDed) query becomes an OR of its terms."""
    assert (
        or_relaxed_query("kinase inhibition tumor growth")
        == "kinase OR inhibition OR tumor OR growth"
    )


def test_single_term_and_boolean_queries_are_not_relaxed() -> None:
    """Nothing to broaden: one term, or an already-boolean query."""
    assert or_relaxed_query("kinase") is None
    assert or_relaxed_query("kinase OR tumor") is None
    assert or_relaxed_query("kinase AND tumor") is None


def test_ladder_broadens_recency_then_terms() -> None:
    """The ladder drops the recency window, then ORs the terms, in order."""
    ladder = relaxation_ladder("kinase inhibition tumor", recency_years=7)
    assert ladder == [
        ("kinase inhibition tumor", 7),
        ("kinase inhibition tumor", 0),
        ("kinase OR inhibition OR tumor", 0),
    ]


def test_ladder_omits_redundant_rungs() -> None:
    """With no recency window and one term, only the exact query remains."""
    assert relaxation_ladder("kinase", recency_years=0) == [("kinase", 0)]
    # No recency to drop; the OR rung still differs, so it is included.
    assert relaxation_ladder("kinase tumor", recency_years=0) == [
        ("kinase tumor", 0),
        ("kinase OR tumor", 0),
    ]


def test_runner_returns_first_rung_when_it_has_enough() -> None:
    """A first rung that meets the threshold costs exactly one search."""
    calls: list[tuple[str, int, int]] = []

    def _esearch(term: str, retmax: int, recency: int) -> list[str]:
        calls.append((term, retmax, recency))
        return [str(i) for i in range(MIN_RESULTS_BEFORE_RELAX)]

    ids = search_with_relaxation("kinase tumor", 10, 7, _esearch)
    assert len(ids) == MIN_RESULTS_BEFORE_RELAX
    assert calls == [("kinase tumor", 10, 7)]  # no relaxation issued


def test_runner_relaxes_until_a_rung_returns_enough() -> None:
    """A starved first rung falls through to the broader OR rung."""
    calls: list[tuple[str, int, int]] = []

    def _esearch(term: str, retmax: int, recency: int) -> list[str]:
        calls.append((term, retmax, recency))
        # Only the OR-broadened rung returns results.
        if "OR" in term:
            return ["1", "2", "3", "4"]
        return []

    ids = search_with_relaxation("kinase inhibition tumor", 10, 7, _esearch)
    assert ids == ["1", "2", "3", "4"]
    assert calls == [
        ("kinase inhibition tumor", 10, 7),
        ("kinase inhibition tumor", 10, 0),
        ("kinase OR inhibition OR tumor", 10, 0),
    ]


def test_runner_keeps_a_thin_result_when_no_rung_clears_the_bar() -> None:
    """Some evidence beats none: the first non-empty rung is returned."""

    def _esearch(term: str, retmax: int, recency: int) -> list[str]:
        return ["only-one"] if recency > 0 else []

    ids = search_with_relaxation("kinase inhibition tumor", 10, 7, _esearch)
    assert ids == ["only-one"]


def test_runner_returns_empty_when_nothing_matches_at_any_breadth() -> None:
    """A query matching nothing even when broadened yields an empty list."""
    ids = search_with_relaxation(
        "kinase inhibition tumor", 10, 7, lambda *_: []
    )
    assert ids == []


def test_threshold_is_clamped_to_retmax() -> None:
    """A retmax below the minimum never forces relaxation it cannot satisfy."""
    calls: list[str] = []

    def _esearch(term: str, retmax: int, recency: int) -> list[str]:
        calls.append(term)
        return ["1"]  # one result, and retmax is 1

    ids = search_with_relaxation("kinase tumor", 1, 0, _esearch)
    assert ids == ["1"]
    assert calls == ["kinase tumor"]  # one hit satisfies retmax=1, no relax
