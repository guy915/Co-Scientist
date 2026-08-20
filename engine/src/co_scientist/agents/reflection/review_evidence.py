"""Gathering the evidence a mature review is grounded in.

Two rounds, and the second is optional. The probe round is what the
full and simulation reviews always did: formulate keyword queries from
the hypothesis, search, read what comes back. Research (assigned in
``research_evidence``) is what the deep tiers buy for their best-ranked
claims -- it reads that result, notices what it does not answer, and
goes again.

Both reviews of one hypothesis share a single gathering, because the
queries are formulated from the hypothesis text and the research goal
and neither differs by review mode. That sharing is why this lives in
its own module rather than inside the review call: it is per hypothesis,
while a review is per (hypothesis, mode).
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import logging
import weakref
from typing import Any

from co_scientist.agents.reflection.deep_verification import (
    _retrieve_probe_evidence,
)
from co_scientist.agents.reflection.research_evidence import (
    ReviewResearch,
    research_for_review,
)
from co_scientist.agents.reflection.review_types import ReviewType
from co_scientist.constants import (
    DEFAULT_MAX_TOKENS,
    LITERATURE_REVIEW_MAX_QUERIES,
    LOW_TEMPERATURE,
)
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm_json,
)
from co_scientist.models import Article, Hypothesis
from co_scientist.prompts import (
    get_hypothesis_query_generation_prompt,
)
from co_scientist.schemas import LITERATURE_QUERY_SCHEMA
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


# Bounds the searches (and downstream paper fan-out) per reviewed hypothesis,
# sharing the literature-review node's own Phase 1 cap.
_MAX_HYPOTHESIS_QUERIES = LITERATURE_REVIEW_MAX_QUERIES


async def _hypothesis_search_queries(
    state: WorkflowState, hypothesis: Hypothesis
) -> list[str]:
    """Formulate keyword search queries targeting one hypothesis.

    The search back end is a keyword index that ANDs every term, so prose
    retrieves nothing: sending the goal and the hypothesis text as one string
    asks for a paper containing every word of both, down to the numbers. This
    asks the model for the few terms a relevant paper would actually carry,
    the same shape the literature-review node's own queries take.

    Args:
        state: The workflow state, for the research goal and worker model.
        hypothesis: The hypothesis whose mechanism the queries must target.

    Returns:
        Up to ``_MAX_HYPOTHESIS_QUERIES`` keyword queries; empty only when
        there is nothing to spend them on -- no live search back end *and*
        no run corpus to ground against -- or when the model call fails,
        which leaves the review ungrounded rather than sending a query that
        cannot match.
    """
    # Without MCP the queries feed the corpus-grounding fallback in
    # _retrieve_probe_evidence (audit E8), so they are still worth a call
    # whenever the run retrieved anything. Only a run with no search back
    # end *and* no corpus has nothing to ground against either way.
    if not state.get("mcp_available") and not state.get("articles"):
        return []
    result = await _call_hypothesis_query_llm(state, hypothesis)
    if result is None:
        return []
    queries = [
        " ".join(str(query).split())
        for query in result.get("queries") or []
        if str(query).strip()
    ]
    return queries[:_MAX_HYPOTHESIS_QUERIES]


async def _call_hypothesis_query_llm(
    state: WorkflowState, hypothesis: Hypothesis
) -> dict[str, Any] | None:
    """Calls the LLM to generate keyword queries for one hypothesis.

    Runs once per reviewed hypothesis, with thinking on as everywhere
    else. Returns None on failure.
    """
    try:
        return await call_llm_json(
            prompt=get_hypothesis_query_generation_prompt(
                research_goal=state["research_goal"],
                hypothesis=hypothesis.text,
            ),
            spec=CompletionSpec(
                model_name=state["model_name"],
                max_tokens=DEFAULT_MAX_TOKENS,
                temperature=LOW_TEMPERATURE,
                json_schema=LITERATURE_QUERY_SCHEMA,
            ),
            options=LLMCallOptions(
                run_id=state.get("run_id"),
                prompt_name=f"hypothesis_queries_{hypothesis.id}",
            ),
        )
    except Exception as exc:
        logger.warning("Query generation failed for %s: %s", hypothesis.id, exc)
        return None


# In-flight targeted retrievals, one map per event loop.
#
# The full and simulation reviews of a hypothesis ask the same question of
# the same literature: queries are formulated from the hypothesis text and
# the research goal, neither of which differs by review mode. Run
# independently they cost two query-generation calls and two rounds of
# searches for one hypothesis, all of it on the run's critical path.
#
# Keyed by loop because the durable worker runs each task on its own thread
# with its own loop, and the shared task below is an asyncio object bound to
# whichever loop created it. Weakly held so a finished cohort's loop does
# not keep its retrievals alive.
_review_evidence_flights: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[str, asyncio.Task[_ReviewEvidence]]
] = weakref.WeakKeyDictionary()


@dataclasses.dataclass(frozen=True)
class _ReviewEvidence:
    """One hypothesis's targeted literature evidence for its reviews.

    Attributes:
        queries: The keyword searches formulated for this hypothesis.
        articles: Sources the searches returned, bounded by the probe cap,
            plus whatever research read on top of them.
        errors: Per-source retrieval failures, kept so a review can tell
            "found nothing" from "search broke".
        ledger: What research did for this hypothesis, as plain data, or
            None when this hypothesis bought none. Carried beside the
            articles rather than stamped on the review, so a record kept
            for provenance does not ride into every checkpoint envelope
            through ``enrichments``.
    """

    queries: list[str]
    articles: list[Article]
    errors: list[str]
    ledger: dict[str, Any] | None = None


def _evidence_key(state: WorkflowState, hypothesis: Hypothesis) -> str:
    """Return the sharing key for one hypothesis's targeted retrieval.

    Includes the text, not just the id: evolution rewrites a hypothesis in
    place, and evidence retrieved for the claim it used to make does not
    answer the one it makes now.
    """
    text = " ".join((hypothesis.text or "").split())
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"{state.get('run_id')}:{hypothesis.id}:{digest}"


async def _shared_review_evidence(
    state: WorkflowState, hypothesis: Hypothesis
) -> _ReviewEvidence:
    """Retrieve this hypothesis's targeted evidence once, sharing the result.

    Concurrent callers await one shared task rather than each starting a
    retrieval: the full and simulation reviews of a hypothesis are gathered
    together, so a plain check-then-fill cache would let both find it empty
    and stampede, which is the case that costs the duplicate work.

    A failed retrieval is evicted rather than cached, so a retry gets a
    fresh attempt instead of inheriting the failure.
    """
    loop = asyncio.get_running_loop()
    flights = _review_evidence_flights.setdefault(loop, {})
    key = _evidence_key(state, hypothesis)
    flight = flights.get(key)
    if flight is None:
        flight = loop.create_task(_retrieve_review_evidence(state, hypothesis))
        flights[key] = flight
    try:
        return await flight
    except Exception:
        flights.pop(key, None)
        raise


async def _retrieve_review_evidence(
    state: WorkflowState, hypothesis: Hypothesis
) -> _ReviewEvidence:
    """Gather one hypothesis's evidence: one probe round, then research.

    The probe round is what this review always did -- queries from the
    hypothesis text, read what comes back. Research is the second half
    the deep tiers now buy for their best-ranked claims: it reads what
    came back, notices what it did not answer, and goes again. The two
    are additive on purpose. A funded hypothesis keeps its probe
    articles and gains the researched ones; an unfunded one is the
    review that was always here.
    """
    queries = await _hypothesis_search_queries(state, hypothesis)
    articles, errors = await _retrieve_probe_evidence(state, queries)
    research = await _research_for_review(state, hypothesis)
    if research is None:
        return _ReviewEvidence(queries, articles, errors)
    known = {article.source_id for article in articles}
    found = [
        article
        for article in research.articles
        if article.source_id not in known
    ]
    return _ReviewEvidence(queries, articles + found, errors, research.ledger)


async def _research_for_review(
    state: WorkflowState, hypothesis: Hypothesis
) -> ReviewResearch | None:
    """Research this hypothesis, reporting failure as no research.

    A review whose research broke is still a review: it has its probe
    evidence, and grounding it in what the first round found beats
    failing the whole item over the second round.
    """
    try:
        return await research_for_review(state, hypothesis)
    except Exception as exc:
        logger.warning("Review research failed for %s: %s", hypothesis.id, exc)
        return None


async def _review_evidence_for(
    state: WorkflowState, hypothesis: Hypothesis, review_type: ReviewType
) -> _ReviewEvidence:
    """Return targeted evidence for the review types that search.

    Recurrent reviews reuse the accumulated tournament context instead of
    re-searching, so they get nothing here.
    """
    if review_type not in {ReviewType.FULL, ReviewType.SIMULATION}:
        return _ReviewEvidence([], [], [])
    return await _shared_review_evidence(state, hypothesis)


def researched_articles_for(
    state: WorkflowState, hypothesis: Hypothesis
) -> list[Article]:
    """Return research already gathered for a hypothesis, never starting any.

    This is what makes deep verification a third owner of the research
    loop *for free*. It runs after comprehensive reflection, on the same
    run cohort's event loop, over largely the same leaders -- so the
    gathering it needs has usually already happened and is sitting in
    the flight cache. Reading it costs nothing.

    What this deliberately will not do is start one. A gathering begun
    here would be a third per-hypothesis retrieval, multiplying by pool
    size and iteration exactly like the relevance pass that turned an
    express run into 299 model calls. So a leader the reviews did not
    research is verified against its probes alone, as it always was --
    the assignment adds depth where depth was already bought and adds no
    spend anywhere.

    Note the seeding needs no new policy either: research is seeded from
    the assumptions a previous cycle marked uncertain or likely false,
    and those assumptions are deep verification's own output. The loop
    it now reads from was already being pointed by it.

    Args:
        state: Current workflow state.
        hypothesis: The hypothesis being verified.

    Returns:
        The articles research found for it, or an empty list when none
        was gathered, the gathering is still running, or it failed.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return []
    flight = _review_evidence_flights.get(loop, {}).get(
        _evidence_key(state, hypothesis)
    )
    if flight is None or not flight.done() or flight.cancelled():
        return []
    if flight.exception() is not None:
        return []
    evidence = flight.result()
    return list(evidence.articles) if evidence.ledger is not None else []
