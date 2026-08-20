"""Two pure decisions the loop makes about what it retrieved.

Split from ``loop.py``, which sequences the ports; these two take no
ports and hold no state, which is what makes them the easiest part of a
run to reason about and to test directly.

**What gets read** is a budget question answered across sources rather
than within one, so a source that returns everything cannot crowd out a
source that returns one good thing.

**What a finding is bound to** is the provenance question: the claim,
the span behind it, the question that went looking, and the call that
surfaced the document.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from co_scientist.research.artifacts import Finding, SearchCall, SourceHit
from co_scientist.research.budget import ResearchBudget
from co_scientist.research.ports import ExtractedFinding


def bind_findings(
    extracted: Sequence[ExtractedFinding],
    question: str,
    calls: Sequence[SearchCall],
) -> tuple[Finding, ...]:
    """Bind each extracted claim to the question and call behind it.

    A finding that cannot be traced to the call that surfaced its
    document keeps an empty ``call_id`` rather than being dropped: the
    claim and its span are the evidence, and the call is provenance.

    Args:
        extracted: What the model drew from the documents.
        question: The question the thread was answering.
        calls: The thread's calls, for locating each document's origin.

    Returns:
        Findings carrying their question, span and originating call.
    """
    call_by_locator = {
        hit.locator: call.id for call in calls for hit in call.hits
    }
    return tuple(
        Finding(
            text=item.text,
            question=question,
            locator=item.locator,
            span=item.span,
            call_id=call_by_locator.get(item.locator, ""),
        )
        for item in extracted
    )


def admit_within_budget(
    calls: Sequence[SearchCall], budget: ResearchBudget
) -> tuple[list[SourceHit], list[SearchCall]]:
    """Choose which results get read, and record which did not.

    Sources are drawn in configured order and results in their own
    ranking, so the ordering a replay has to reproduce is the ordering
    the sources gave. A locator returned by two sources collapses onto
    the first one that returned it.

    Args:
        calls: This question's calls, one per source.
        budget: The level's ceilings.

    Returns:
        The admitted hits, and the calls updated with what each of them
        contributed and what was refused.
    """
    admitted: list[SourceHit] = []
    admitted_locators: set[str] = set()
    seen: set[str] = set()

    for call in calls:
        for hit in call.hits:
            if hit.locator in seen:
                continue
            seen.add(hit.locator)
            if len(admitted) < budget.hits_per_question:
                admitted.append(hit)
                admitted_locators.add(hit.locator)

    recorded = [
        replace(
            call,
            admitted=tuple(
                hit.locator
                for hit in call.hits
                if hit.locator in admitted_locators
            ),
            dropped=tuple(
                hit.locator
                for hit in call.hits
                if hit.locator not in admitted_locators
            ),
        )
        for call in calls
    ]
    return admitted, recorded
