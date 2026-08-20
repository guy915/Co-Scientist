"""Deep verification as the third owner of the research loop, at no cost."""

from __future__ import annotations

import asyncio
from typing import cast

import pytest

from co_scientist.agents.reflection import review_evidence
from co_scientist.agents.reflection.deep_verification_evidence import (
    with_researched,
)
from co_scientist.agents.reflection.review_evidence import (
    _evidence_key,
    _ReviewEvidence,
    researched_articles_for,
)
from co_scientist.models import Article, Hypothesis
from co_scientist.state import WorkflowState


def _hypothesis() -> Hypothesis:
    """One leader, as deep verification would see it."""
    return Hypothesis(id="h1", text="Blocking X reverses fibrosis in humans.")


def _article(source_id: str) -> Article:
    """One paper, identified the way the merge deduplicates on."""
    return Article(title=f"paper {source_id}", source_id=source_id)


def _state() -> WorkflowState:
    """The state fields the sharing key is built from."""
    return cast(WorkflowState, {"run_id": "run-1"})


async def _plant(
    state: WorkflowState,
    hypothesis: Hypothesis,
    evidence: _ReviewEvidence,
) -> None:
    """Put a completed gathering in the flight cache for this loop."""
    loop = asyncio.get_running_loop()
    flights = review_evidence._review_evidence_flights.setdefault(loop, {})
    task = loop.create_task(_resolved(evidence))
    await task
    flights[_evidence_key(state, hypothesis)] = task


async def _resolved(evidence: _ReviewEvidence) -> _ReviewEvidence:
    """A finished gathering."""
    return evidence


@pytest.mark.asyncio
async def test_verification_reads_research_the_reviews_already_bought() -> None:
    """The assignment: depth where depth was already paid for.

    Deep verification runs after comprehensive reflection on the same
    cohort's loop, over largely the same leaders, so the gathering it
    needs is usually already sitting in the flight cache.
    """
    state, hypothesis = _state(), _hypothesis()
    await _plant(
        state,
        hypothesis,
        _ReviewEvidence(["q"], [_article("a"), _article("b")], [], {"t": 1}),
    )

    found = researched_articles_for(state, hypothesis)

    assert [article.source_id for article in found] == ["a", "b"]


@pytest.mark.asyncio
async def test_a_hypothesis_that_bought_no_research_adds_nothing() -> None:
    """A gathering with no ledger did a probe round and no research.

    Its articles are the probe articles this verification is about to
    retrieve for itself, so returning them would double every paper in
    the prompt while claiming depth that was never bought.
    """
    state, hypothesis = _state(), _hypothesis()
    await _plant(
        state, hypothesis, _ReviewEvidence(["q"], [_article("a")], [], None)
    )

    assert researched_articles_for(state, hypothesis) == []


@pytest.mark.asyncio
async def test_an_unresearched_leader_starts_nothing() -> None:
    """The cost ceiling, and the whole reason this is a read.

    A leader outside the reviews' funded set has no gathering. Starting
    one here would be a third per-hypothesis retrieval, multiplying by
    pool size and by iteration -- the exact shape that turned an express
    run into 299 model calls.
    """
    state, hypothesis = _state(), _hypothesis()

    assert researched_articles_for(state, hypothesis) == []


@pytest.mark.asyncio
async def test_a_failed_gathering_is_not_an_error_here() -> None:
    """Verification still has its probes; it does not inherit the failure."""
    state, hypothesis = _state(), _hypothesis()
    loop = asyncio.get_running_loop()

    async def _boom() -> _ReviewEvidence:
        raise RuntimeError("search broke")

    task = loop.create_task(_boom())
    with pytest.raises(RuntimeError):
        await task
    review_evidence._review_evidence_flights.setdefault(loop, {})[
        _evidence_key(state, hypothesis)
    ] = task

    assert researched_articles_for(state, hypothesis) == []


@pytest.mark.asyncio
async def test_a_paper_found_twice_is_carried_once() -> None:
    """A probe query and a research question can surface the same paper.

    Repeated in the prompt it spends the evidence budget twice to say one
    thing, and reads to the model as corroboration by two sources.
    """
    state, hypothesis = _state(), _hypothesis()
    await _plant(
        state,
        hypothesis,
        _ReviewEvidence(["q"], [_article("a"), _article("c")], [], {"t": 1}),
    )

    merged = with_researched(state, hypothesis, [_article("a")])

    assert [article.source_id for article in merged] == ["a", "c"]
