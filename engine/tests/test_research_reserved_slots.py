"""What a reserved slot guarantees, and what it deliberately does not.

The research loop reads a fixed number of documents per question and
draws its sources in configured order, which makes order a proxy for
quality. One source cannot compete on that proxy: the group's own papers
are appended last and carry neither citation count nor recency, so on a
healthy run the indexed literature fills every place before the corpus is
reached and a corpus that answers the question well is never read.

These pin the narrow fix -- the corpus is guaranteed a place, and cannot
take more than one.
"""

from __future__ import annotations

import pytest

from co_scientist.research import ResearchBudget
from co_scientist.research.admission import admit_within_budget
from co_scientist.research.artifacts import CallStatus, SearchCall
from co_scientist.research_adapter.budget import (
    budget_for_tier,
    review_budget_for_tier,
)
from co_scientist.research_adapter.local_corpus import GROUP_CORPUS_SOURCE
from tests._research_fakes import _hits

_NETWORK = "pubmed"


def _call(source: str, *locators: str) -> SearchCall:
    """One completed call returning the given locators, best first."""
    return SearchCall(
        question="what is known?",
        query="known",
        source=source,
        status=CallStatus.OK,
        hits=tuple(_hits(*locators)),
    )


def _budget(reserved: tuple[tuple[str, int], ...]) -> ResearchBudget:
    """A three-document budget over the network source and the corpus."""
    return ResearchBudget(
        hits_per_question=3,
        sources=(_NETWORK, GROUP_CORPUS_SOURCE),
        reserved_slots=reserved,
    )


def test_without_a_reservation_the_first_source_takes_everything() -> None:
    """The behaviour a reservation exists to change."""
    calls = [
        _call(_NETWORK, "n1", "n2", "n3", "n4"),
        _call(GROUP_CORPUS_SOURCE, "c1"),
    ]

    admitted, _ = admit_within_budget(calls, _budget(()))

    assert [hit.locator for hit in admitted] == ["n1", "n2", "n3"]


def test_a_reservation_seats_the_corpus_ahead_of_the_network() -> None:
    calls = [
        _call(_NETWORK, "n1", "n2", "n3", "n4"),
        _call(GROUP_CORPUS_SOURCE, "c1", "c2"),
    ]

    admitted, recorded = admit_within_budget(
        calls, _budget(((GROUP_CORPUS_SOURCE, 1),))
    )

    # One place, and one only: the reservation is so the group's own work
    # is always consulted, not so it displaces the published literature.
    assert [hit.locator for hit in admitted] == ["c1", "n1", "n2"]
    assert recorded[1].admitted == ("c1",)
    assert recorded[1].dropped == ("c2",)


def test_a_reservation_is_never_padded_when_the_source_is_empty() -> None:
    """An unfilled reservation returns its place, it does not hold it."""
    calls = [
        _call(_NETWORK, "n1", "n2", "n3", "n4"),
        _call(GROUP_CORPUS_SOURCE),
    ]

    admitted, _ = admit_within_budget(
        calls, _budget(((GROUP_CORPUS_SOURCE, 1),))
    )

    assert [hit.locator for hit in admitted] == ["n1", "n2", "n3"]


def test_a_paper_both_sources_returned_is_seated_once() -> None:
    """A locator two sources returned is seated once, not twice.

    Deduplication runs before either fill, so a shared paper cannot be
    seated by the reservation and again by rank.
    """
    calls = [
        _call(_NETWORK, "shared", "n1", "n2"),
        _call(GROUP_CORPUS_SOURCE, "shared", "c1"),
    ]

    admitted, _ = admit_within_budget(
        calls, _budget(((GROUP_CORPUS_SOURCE, 1),))
    )

    assert [hit.locator for hit in admitted] == ["c1", "shared", "n1"]


def test_a_reservation_cannot_claim_every_document() -> None:
    """Reserving the whole read leaves source order deciding nothing."""
    with pytest.raises(ValueError, match="claim all"):
        ResearchBudget(
            hits_per_question=2,
            sources=(_NETWORK, GROUP_CORPUS_SOURCE),
            reserved_slots=((GROUP_CORPUS_SOURCE, 2),),
        )


def test_a_reservation_for_an_unsearched_source_is_refused() -> None:
    """Otherwise the typo is silent: it simply never seats anything."""
    with pytest.raises(ValueError, match="unsearched"):
        ResearchBudget(sources=(_NETWORK,), reserved_slots=(("corpuss", 1),))


@pytest.mark.parametrize("tier", ["extended", "ultra"])
@pytest.mark.parametrize(
    "resolve", [budget_for_tier, review_budget_for_tier], ids=["run", "review"]
)
def test_every_researching_budget_reserves_the_corpus_a_place(
    tier: str, resolve: object
) -> None:
    budget = resolve(tier, (_NETWORK, GROUP_CORPUS_SOURCE))  # type: ignore[operator]

    assert budget is not None
    assert budget.reserved_slots == ((GROUP_CORPUS_SOURCE, 1),)


@pytest.mark.parametrize("tier", ["extended", "ultra"])
def test_a_run_without_a_corpus_reserves_nothing(tier: str) -> None:
    """The reservation is not a default; it names a source or is absent."""
    budget = budget_for_tier(tier, (_NETWORK,))

    assert budget is not None
    assert budget.reserved_slots == ()


def test_the_descent_carries_the_reservation_down() -> None:
    """A level that lost the reservation would drop the corpus again."""
    budget = ResearchBudget(
        depth=3,
        hits_per_question=3,
        sources=(_NETWORK, GROUP_CORPUS_SOURCE),
        reserved_slots=((GROUP_CORPUS_SOURCE, 1),),
    )

    second = budget.descend()

    assert second is not None
    assert second.reserved_slots == ((GROUP_CORPUS_SOURCE, 1),)
