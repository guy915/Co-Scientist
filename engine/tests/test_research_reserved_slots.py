"""What a reserved slot guarantees, and what it deliberately does not.

The research loop reads a fixed number of documents per question and
draws its sources in configured order, which makes order a proxy for
quality. A source that cannot compete on that proxy -- no citation count,
no recency -- can still be guaranteed a place via ``reserved_slots``, a
general capability of :class:`ResearchBudget` and ``admit_within_budget``
that no shipped source currently uses.

These pin the mechanism itself -- a reservation guarantees a place, and
cannot take more than it was given.
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
from tests._research_fakes import _hits

_NETWORK = "pubmed"
_RESERVED = "reserved_source"


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
    """A three-document budget over the network source and the reserved one."""
    return ResearchBudget(
        hits_per_question=3,
        sources=(_NETWORK, _RESERVED),
        reserved_slots=reserved,
    )


def test_without_a_reservation_the_first_source_takes_everything() -> None:
    """The behaviour a reservation exists to change."""
    calls = [
        _call(_NETWORK, "n1", "n2", "n3", "n4"),
        _call(_RESERVED, "c1"),
    ]

    admitted, _ = admit_within_budget(calls, _budget(()))

    assert [hit.locator for hit in admitted] == ["n1", "n2", "n3"]


def test_a_reservation_seats_the_reserved_source_ahead_of_the_network() -> None:
    calls = [
        _call(_NETWORK, "n1", "n2", "n3", "n4"),
        _call(_RESERVED, "c1", "c2"),
    ]

    admitted, recorded = admit_within_budget(calls, _budget(((_RESERVED, 1),)))

    # One place, and one only: the reservation is so the source is always
    # consulted, not so it displaces the rest of the read.
    assert [hit.locator for hit in admitted] == ["c1", "n1", "n2"]
    assert recorded[1].admitted == ("c1",)
    assert recorded[1].dropped == ("c2",)


def test_a_reservation_is_never_padded_when_the_source_is_empty() -> None:
    """An unfilled reservation returns its place, it does not hold it."""
    calls = [
        _call(_NETWORK, "n1", "n2", "n3", "n4"),
        _call(_RESERVED),
    ]

    admitted, _ = admit_within_budget(calls, _budget(((_RESERVED, 1),)))

    assert [hit.locator for hit in admitted] == ["n1", "n2", "n3"]


def test_a_paper_both_sources_returned_is_seated_once() -> None:
    """A locator two sources returned is seated once, not twice.

    Deduplication runs before either fill, so a shared paper cannot be
    seated by the reservation and again by rank.
    """
    calls = [
        _call(_NETWORK, "shared", "n1", "n2"),
        _call(_RESERVED, "shared", "c1"),
    ]

    admitted, _ = admit_within_budget(calls, _budget(((_RESERVED, 1),)))

    assert [hit.locator for hit in admitted] == ["c1", "shared", "n1"]


def test_a_reservation_cannot_claim_every_document() -> None:
    """Reserving the whole read leaves source order deciding nothing."""
    with pytest.raises(ValueError, match="claim all"):
        ResearchBudget(
            hits_per_question=2,
            sources=(_NETWORK, _RESERVED),
            reserved_slots=((_RESERVED, 2),),
        )


def test_a_reservation_for_an_unsearched_source_is_refused() -> None:
    """Otherwise the typo is silent: it simply never seats anything."""
    with pytest.raises(ValueError, match="unsearched"):
        ResearchBudget(sources=(_NETWORK,), reserved_slots=(("nope", 1),))


@pytest.mark.parametrize("tier", ["extended", "ultra"])
@pytest.mark.parametrize(
    "resolve", [budget_for_tier, review_budget_for_tier], ids=["run", "review"]
)
def test_every_researching_budget_reserves_nothing_by_default(
    tier: str, resolve: object
) -> None:
    """No shipped source reserves a place, so the ceiling reserves none."""
    budget = resolve(tier, (_NETWORK, _RESERVED))  # type: ignore[operator]

    assert budget is not None
    assert budget.reserved_slots == ()


def test_the_descent_carries_a_reservation_down() -> None:
    """A level that lost the reservation would drop the source again."""
    budget = ResearchBudget(
        depth=3,
        hits_per_question=3,
        sources=(_NETWORK, _RESERVED),
        reserved_slots=((_RESERVED, 1),),
    )

    second = budget.descend()

    assert second is not None
    assert second.reserved_slots == ((_RESERVED, 1),)
