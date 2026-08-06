"""Tests for the PubMed query-relaxation ladder (mcp_server/pubmed_query.py).

PubMed ANDs every untagged term, so a distilled multi-term query collapses
toward zero hits. These prove the relaxation policy that keeps a starved query
returning candidates to ground against: OR-broadening a single-term-required
query with each term field-tagged against its own MeSH heading and
title/abstract text (the exact rung is deliberately left untagged -- see the
module docstring), the precise-to-broad ladder, and the runner that stops at
the first rung returning enough while paying only one search when the first
rung suffices.
"""

from __future__ import annotations

from mcp_server.pubmed_query import (
    MIN_RESULTS_BEFORE_RELAX,
    field_tag_terms,
    or_relaxed_query,
    relaxation_ladder,
    search_with_relaxation,
)

# =============================================================================
# field_tag_terms
# =============================================================================


def test_field_tag_terms_wraps_each_term_in_mesh_and_tiab() -> None:
    """Every term is OR'd against its own MeSH heading and text-word match.

    This is what keeps an over-specific multi-term query from collapsing to
    zero hits under PubMed's automatic term mapping: tagging bypasses the
    ATM fallback that silently ANDs every bare word once a phrase fails to
    match a controlled-vocabulary heading.
    """
    assert field_tag_terms("kinase tumor", " AND ") == (
        "(kinase[tiab] OR kinase[mesh]) AND (tumor[tiab] OR tumor[mesh])"
    )


def test_field_tag_terms_honors_the_given_joiner() -> None:
    """The same tagging is reusable for an OR-joined broadened rung."""
    assert field_tag_terms("kinase tumor growth", " OR ") == (
        "(kinase[tiab] OR kinase[mesh]) OR (tumor[tiab] OR tumor[mesh])"
        " OR (growth[tiab] OR growth[mesh])"
    )


def test_field_tag_terms_tags_a_single_term() -> None:
    """A single term still gains the MeSH/text-word OR, just with no join."""
    assert field_tag_terms("kinase", " AND ") == (
        "(kinase[tiab] OR kinase[mesh])"
    )


def test_field_tag_terms_leaves_explicit_boolean_queries_untouched() -> None:
    """A query the caller already wrote as boolean is not re-tokenized.

    Re-tagging term-by-term would fight the caller's own AND/OR/NOT
    structure rather than extend it.
    """
    assert field_tag_terms("kinase AND tumor", " AND ") == "kinase AND tumor"
    assert field_tag_terms("kinase OR tumor", " OR ") == "kinase OR tumor"


# =============================================================================
# or_relaxed_query
# =============================================================================


def test_or_relaxes_a_multi_term_query_with_field_tags() -> None:
    """A space-separated (implicitly ANDed) query becomes a tagged OR."""
    assert or_relaxed_query("kinase inhibition tumor growth") == (
        "(kinase[tiab] OR kinase[mesh])"
        " OR (inhibition[tiab] OR inhibition[mesh])"
        " OR (tumor[tiab] OR tumor[mesh])"
        " OR (growth[tiab] OR growth[mesh])"
    )


def test_single_term_and_boolean_queries_are_not_relaxed() -> None:
    """Nothing to broaden: one term, or an already-boolean query."""
    assert or_relaxed_query("kinase") is None
    assert or_relaxed_query("kinase OR tumor") is None
    assert or_relaxed_query("kinase AND tumor") is None


# =============================================================================
# relaxation_ladder
# =============================================================================


def test_ladder_broadens_recency_then_terms() -> None:
    """The ladder drops the recency window, then ORs the terms, in order.

    Only the final OR rung carries field tags. The exact and recency-dropped
    rungs are left exactly as PubMed's own automatic term mapping receives
    them -- see the module docstring for the live measurement showing a
    naive per-word tag on those rungs regresses queries ATM already handles
    well.
    """
    ladder = relaxation_ladder("kinase inhibition tumor", recency_years=7)
    tagged_or = (
        "(kinase[tiab] OR kinase[mesh])"
        " OR (inhibition[tiab] OR inhibition[mesh])"
        " OR (tumor[tiab] OR tumor[mesh])"
    )
    assert ladder == [
        ("kinase inhibition tumor", 7),
        ("kinase inhibition tumor", 0),
        (tagged_or, 0),
    ]


def test_ladder_omits_redundant_rungs() -> None:
    """With no recency window and one term, only the exact query remains."""
    assert relaxation_ladder("kinase", recency_years=0) == [("kinase", 0)]
    # No recency to drop; the OR rung still differs, so it is included.
    assert relaxation_ladder("kinase tumor", recency_years=0) == [
        ("kinase tumor", 0),
        (
            "(kinase[tiab] OR kinase[mesh]) OR (tumor[tiab] OR tumor[mesh])",
            0,
        ),
    ]


def test_ladder_leaves_an_explicit_boolean_query_untagged() -> None:
    """A caller-supplied boolean query passes through every rung as-is."""
    assert relaxation_ladder("kinase AND tumor", recency_years=0) == [
        ("kinase AND tumor", 0)
    ]


# =============================================================================
# search_with_relaxation
# =============================================================================


def test_runner_returns_first_rung_when_it_has_enough() -> None:
    """A first rung that meets the threshold costs exactly one search."""
    calls: list[tuple[str, int, int]] = []

    def _esearch(term: str, retmax: int, recency: int) -> list[str]:
        calls.append((term, retmax, recency))
        return [str(i) for i in range(MIN_RESULTS_BEFORE_RELAX)]

    ids = search_with_relaxation("kinase tumor", 10, 7, _esearch)
    assert len(ids) == MIN_RESULTS_BEFORE_RELAX
    assert len(calls) == 1  # no relaxation issued
    assert calls[0][1:] == (10, 7)


def test_runner_relaxes_until_a_rung_returns_enough() -> None:
    """A starved first rung falls through to the broader OR rung."""
    calls: list[tuple[str, int, int]] = []

    def _esearch(term: str, retmax: int, recency: int) -> list[str]:
        calls.append((term, retmax, recency))
        # Only the OR-broadened rung returns results.
        if " OR (" in term:
            return ["1", "2", "3", "4"]
        return []

    ids = search_with_relaxation("kinase inhibition tumor", 10, 7, _esearch)
    assert ids == ["1", "2", "3", "4"]
    assert [c[1:] for c in calls] == [(10, 7), (10, 0), (10, 0)]
    assert calls[0][0] == "kinase inhibition tumor"
    assert " OR (" in calls[2][0]


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
    assert len(calls) == 1  # one hit satisfies retmax=1, no relax
