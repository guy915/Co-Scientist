"""Evidence-budget selection for the literature review (Phase 2 reduction).

Chooses which of a run's ranked, merged search results fit the evidence
budget: pure score order, except that a source configured with
``reserved_slots`` is guaranteed that many places (see ``select_within_budget``
for why), and a retracted candidate is never admissible regardless of score or
reservation.
"""

import logging
from typing import TYPE_CHECKING, Any

from co_scientist.evidence.article_support import (
    _metadata_is_retracted,
)

if TYPE_CHECKING:
    from co_scientist.config import SearchSourceConfig

logger = logging.getLogger(__name__)


def _fill_reserved_slots(
    ranked: dict[str, dict[str, Any]],
    source_map: dict[str, str],
    sources: list["SearchSourceConfig"],
    budget: int,
) -> list[str]:
    """Fills each source's reserved slots best-first, capped at the budget."""
    reserved: list[str] = []
    for source in sources:
        if source.reserved_slots <= 0:
            continue
        remaining = budget - len(reserved)
        if remaining <= 0:
            break
        from_source = [
            paper_id
            for paper_id in ranked
            if source_map.get(paper_id) == source.tool
        ]
        reserved.extend(from_source[: min(source.reserved_slots, remaining)])
    return reserved


def _fill_remaining_by_score(
    ranked: dict[str, dict[str, Any]],
    reserved: list[str],
    budget: int,
) -> list[str]:
    """Appends the best-ranked remaining papers up to the budget."""
    selected = list(reserved)
    reserved_ids = set(reserved)
    for paper_id in ranked:
        if len(selected) >= budget:
            break
        if paper_id not in reserved_ids:
            selected.append(paper_id)
    return selected


def _exclude_retracted(
    ranked: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Drop retracted candidates before either fill path can see them.

    Score alone cannot exclude a retracted paper: its penalized score only
    sorts it last, which still admits it once the ranked pool underfills the
    budget, or once a reserved source's own top candidates happen to be
    retracted. Filtering here, upstream of both fill paths, is what keeps a
    retraction a hard exclusion rather than a demotion.

    Args:
        ranked: Papers best-first, as returned by ``merge_search_results``.

    Returns:
        The same mapping with every retracted entry removed, order
        preserved.
    """
    return {
        paper_id: metadata
        for paper_id, metadata in ranked.items()
        if not _metadata_is_retracted(metadata)
    }


# Why reserved_slots exists: retrieval score rewards citation count and
# recency, which a source can lack entirely rather than score poorly on. A
# local corpus of the group's own papers carries neither, so it sorts below
# every indexed paper and is truncated away no matter how well it answers
# the question. Reserving places is the narrow fix -- raising such a
# source's base score enough to survive would also let it displace
# everything else.
def select_within_budget(
    ranked: dict[str, dict[str, Any]],
    source_map: dict[str, str],
    sources: list["SearchSourceConfig"],
    budget: int,
) -> list[str]:
    """Choose which ranked papers fit the evidence budget.

    Score alone decides among admissible papers, except that a source
    configured with ``reserved_slots`` is guaranteed that many places first.
    Reserved places are filled best-first from within the source, are never
    padded when the source returned fewer papers, and cannot push the
    selection past the budget. A retracted paper is never admissible: it is
    excluded before either fill path runs, so it can neither seat a
    reservation nor pad an underfilled budget, and its slot is not
    backfilled from another source.

    Args:
        ranked: Papers best-first, as returned by ``merge_search_results``.
        source_map: Paper id to the source tool id that produced it.
        sources: The workflow's enabled search sources, in config order.
        budget: Total papers to select.

    Returns:
        The selected paper ids: reserved papers first, then the best of the
        rest by score.
    """
    if budget <= 0:
        return []

    admissible = _exclude_retracted(ranked)
    reserved = _fill_reserved_slots(admissible, source_map, sources, budget)
    selected = _fill_remaining_by_score(admissible, reserved, budget)

    if reserved:
        logger.info(
            "Evidence budget %s: %s reserved, %s by score",
            budget,
            len(reserved),
            len(selected) - len(reserved),
        )
    return selected
