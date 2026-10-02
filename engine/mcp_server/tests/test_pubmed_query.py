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

from typing import Any

import pytest
from mcp_server.pubmed_query import (
    MIN_RESULTS_BEFORE_RELAX,
    anchored_relaxed_query,
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
    assert field_tag_terms("kinase NOT tumor", " AND ") == "kinase NOT tumor"


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
    assert or_relaxed_query("kinase NOT tumor") is None


# =============================================================================
# relaxation_ladder
# =============================================================================


def test_ladder_broadens_recency_then_anchored_then_terms() -> None:
    """Recency, then all-but-the-subject, then every term, in that order.

    Only the two broadened rungs carry field tags. The exact and
    recency-dropped rungs are left exactly as PubMed's own automatic term
    mapping receives them -- see the module docstring for the live
    measurement showing a naive per-word tag on those rungs regresses
    queries ATM already handles well.
    """
    ladder = relaxation_ladder("kinase inhibition tumor", recency_years=7)
    anchored = (
        "(kinase[tiab] OR kinase[mesh])"
        " AND (inhibition[tiab] OR inhibition[mesh])"
        " AND ((tumor[tiab] OR tumor[mesh]))"
    )
    tagged_or = (
        "(kinase[tiab] OR kinase[mesh])"
        " OR (inhibition[tiab] OR inhibition[mesh])"
        " OR (tumor[tiab] OR tumor[mesh])"
    )
    assert ladder == [
        ("kinase inhibition tumor", 7),
        ("kinase inhibition tumor", 0),
        (anchored, 0),
        (tagged_or, 0),
    ]


def test_the_anchored_rung_keeps_the_leading_terms_required() -> None:
    """Broadening must answer the question it was given.

    ORing every term is a different question, not a wider one: measured
    live, "PHGDH knockdown osimertinib resistance EGFR adenocarcinoma"
    ANDs to 0 hits and ORs to 1,966,502, and the three documents a caller
    then read were a gastric cancer case report, a leiomyosarcoma series
    and a paper on antimicrobial resistance.
    """
    anchored = anchored_relaxed_query("PHGDH knockdown osimertinib resistance")

    assert anchored is not None
    # The leading pair stays ANDed; only the tail relaxes.
    assert anchored.startswith(
        "(PHGDH[tiab] OR PHGDH[mesh])"
        " AND (knockdown[tiab] OR knockdown[mesh]) AND ("
    )
    assert " AND (osimertinib" not in anchored
    assert "osimertinib[tiab] OR osimertinib[mesh]" in anchored
    assert "resistance[tiab] OR resistance[mesh]" in anchored


def test_a_query_with_nothing_past_its_anchors_is_not_anchored() -> None:
    """Anchoring every term would just restate the exact rung."""
    assert anchored_relaxed_query("kinase") is None
    assert anchored_relaxed_query("kinase tumor") is None
    assert anchored_relaxed_query("kinase AND tumor") is None


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
    for operator in ("AND", "OR", "NOT"):
        query = f"kinase {operator} tumor"
        assert relaxation_ladder(query, recency_years=0) == [(query, 0)]


# =============================================================================
# search_with_relaxation
# =============================================================================


def test_lowercase_prose_operators_do_not_suppress_relaxation() -> None:
    """Only PubMed's uppercase Boolean operators signal query structure."""
    calls: list[str] = []

    def _esearch(term: str, retmax: int, recency: int) -> list[str]:
        calls.append(term)
        return []

    query = "kinase and tumor or growth not drug"
    ids = search_with_relaxation(query, 10, 0, _esearch)

    assert ids == []
    assert calls[0] == query
    assert len(calls) == 3
    assert " AND (" in calls[1]
    assert calls[2].startswith("(kinase[tiab] OR kinase[mesh]) OR")


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
    """A starved query falls through every rung to the broadest one."""
    calls: list[tuple[str, int, int]] = []

    def _esearch(term: str, retmax: int, recency: int) -> list[str]:
        calls.append((term, retmax, recency))
        # Only the fully-ORed rung returns results.
        if term.startswith("(kinase[tiab] OR kinase[mesh]) OR"):
            return ["1", "2", "3", "4"]
        return []

    ids = search_with_relaxation("kinase inhibition tumor", 10, 7, _esearch)
    assert ids == ["1", "2", "3", "4"]
    assert [c[1:] for c in calls] == [(10, 7), (10, 0), (10, 0), (10, 0)]
    assert calls[0][0] == "kinase inhibition tumor"
    assert " AND (" in calls[2][0]  # the anchored rung was tried first


def test_the_anchored_rung_is_taken_before_the_fully_ored_one() -> None:
    """The point of the middle rung: it stops the descent short.

    Reaching the OR rung is what returned three off-topic documents on a
    real run, so a rung that keeps the subject and clears the bar has to
    end the descent rather than merely precede it.
    """
    calls: list[str] = []

    def _esearch(term: str, retmax: int, recency: int) -> list[str]:
        calls.append(term)
        return ["1", "2", "3"] if " AND (" in term else []

    ids = search_with_relaxation("kinase inhibition tumor", 10, 0, _esearch)

    assert ids == ["1", "2", "3"]
    assert len(calls) == 2
    assert not calls[-1].startswith("(kinase[tiab] OR kinase[mesh]) OR")


def test_first_rung_target_survives_when_anchored_rung_fills_buffer() -> None:
    """A later qualifying rung must not discard an exact-rung PMID.

    The inputs and IDs reproduce the retained B. fragilis diagnostic, not a
    holdout for the frozen scientific comparison. The stub keeps this test
    offline while preserving the actual observed rung boundary.
    """
    query = (
        "Symbiotic Bacteroides fragilis polysaccharide A signals through TLR2 "
        "on Foxp3+ regulatory T cells to promote mucosal tolerance and "
        "colonization."
    )
    precise_ids = ["21512004"]
    anchored_ids = [
        "42415234",
        "42679821",
        "42400638",
        "42346964",
        "42115921",
        "40233891",
        "40764272",
        "41196415",
        "41195911",
    ]
    calls: list[str] = []
    trace: dict[str, Any] = {"sort": "pub_date"}

    def _esearch(term: str, retmax: int, recency: int) -> list[str]:
        assert retmax == 9
        assert recency == 0
        calls.append(term)
        if term == query:
            return precise_ids
        if " AND (" in term:
            return anchored_ids
        pytest.fail("The qualifying anchored rung should stop the ladder")

    ids = search_with_relaxation(query, 9, 0, _esearch, trace)

    assert ids == [*precise_ids, *anchored_ids[:8]]
    assert calls == [query, anchored_relaxed_query(query)]
    assert trace["selected"]["rung_index"] == 2
    assert trace["selected"]["rung_type"] == "anchored"
    assert trace["selected"]["ids"] == ids


def test_merged_rung_ids_keep_first_occurrence_order_and_retmax_cap() -> None:
    query = "kinase inhibition tumor growth"
    anchored_ids = ["shared", "anchored"]
    broad_ids = ["anchored", "broad-1", "broad-2"]

    def _esearch(term: str, _retmax: int, _recency: int) -> list[str]:
        if term == query:
            return ["exact", "shared"]
        if " AND (" in term:
            return anchored_ids
        return broad_ids

    ids = search_with_relaxation(query, 4, 0, _esearch)

    assert ids == ["exact", "shared", "anchored", "broad-1"]


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
