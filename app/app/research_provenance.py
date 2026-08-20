"""Turn a research run's ledger into durable retrieval provenance.

``co_scientist.research`` returns everything a research request did --
every question asked, every search made, every finding bound to its
source -- and persists none of it, deliberately: the capability is owned
by no agent and knows nothing about this store. This module is the seam
between the two, and it is the only place that knows both.

It is a pure mapping. No connection is opened here and no network call is
made; the caller writes the rows inside its own transaction, after the
searching has returned. That split is not stylistic -- there is one
SQLite writer and no fair queuing, so a transaction held open across
outbound I/O freezes every other writer for its duration.

What it deliberately does not do is decide anything. Which searches are
worth keeping, when to write them, and which evidence row each finding
becomes are the assigning agent's questions, answered in its adapter.
"""

from __future__ import annotations

from typing import NamedTuple

from co_scientist.research import ResearchResult

from app.store import NewRetrievalCall


class _Origin(NamedTuple):
    """Where one call came from: its level, and the question behind it.

    A call carries its question as *text*, since that is what its own
    identity is hashed over; the id has to come from the question object,
    which is what a later join against a question tree keys on. Depth is
    the thread's, for the same reason -- a call does not know which level
    it was issued at.

    ``_UNKNOWN`` is what a call with no thread gets. The loop records a
    thread for every question it ran, so that is unreachable in practice;
    depth 0 reads as "level unknown", matching the column's own default,
    rather than silently claiming the first level.
    """

    depth: int
    question_id: str


_UNKNOWN = _Origin(depth=0, question_id="")


def retrieval_call_rows(
    run_id: str, result: ResearchResult
) -> list[NewRetrievalCall]:
    """Map a research result's searches to insertable rows.

    Every call is carried over, including the ones that returned nothing
    and the ones that failed. An empty result and an unreachable source
    look identical in a coverage report unless the failure is on record,
    and telling them apart is most of what this table is for.

    Args:
        run_id: The run the searches belong to.
        result: What ``conduct_research`` returned.

    Returns:
        One row per search, in the order the calls completed.
    """
    origins = _origin_by_call(result)
    return [
        NewRetrievalCall(
            run_id=run_id,
            id=call.id,
            question=call.question,
            question_id=origins.get(call.id, _UNKNOWN).question_id,
            query=call.query,
            source=call.source,
            depth=origins.get(call.id, _UNKNOWN).depth,
            status=call.status.value,
            hits=[
                {
                    "locator": hit.locator,
                    "title": hit.title,
                    "snippet": hit.snippet,
                    "rank": hit.rank,
                    "score": hit.score,
                    "metadata": dict(hit.metadata),
                }
                for hit in call.hits
            ],
            admitted=list(call.admitted),
            dropped=list(call.dropped),
            error=call.error,
            duration_seconds=call.duration_seconds,
        )
        for call in result.calls
    ]


def _origin_by_call(result: ResearchResult) -> dict[str, _Origin]:
    """Index every call by the thread that made it."""
    return {
        call_id: _Origin(depth=thread.depth, question_id=thread.question.id)
        for thread in result.threads
        for call_id in thread.call_ids
    }
