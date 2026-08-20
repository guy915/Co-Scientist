"""Retrieval provenance: which query found a piece of evidence.

The store never recorded what a search was asked to answer. These tests
pin the properties that make the new record worth having: a call's
identity carries no run, so two runs must not share or delete each
other's rows; a resumed run re-offering work it already paid for must not
duplicate it; and a failed or empty search must survive, since "the
source was unreachable" and "the source had nothing" are the two facts a
coverage report cannot distinguish without it.
"""

from __future__ import annotations

import os

import pytest
from co_scientist.research import (
    CallStatus,
    Question,
    ResearchResult,
    SearchCall,
    SourceHit,
    StopReason,
    ThreadRecord,
    ThreadStatus,
)

from app import research_provenance, store


@pytest.fixture
def db(isolated_db: str) -> str:
    return os.environ["COSCIENTIST_DB_PATH"]


def _hit(locator: str, rank: int = 0) -> SourceHit:
    """One result as a source would have returned it."""
    return SourceHit(
        locator=locator,
        title=f"Title {locator}",
        snippet=f"Snippet for {locator}",
        rank=rank,
        score=1.0 - rank / 10,
        metadata={"kind": "article"},
    )


def _result(
    *,
    question: str = "What drives fibrosis?",
    depth: int = 1,
    calls: list[SearchCall] | None = None,
) -> ResearchResult:
    """A research result carrying one thread and its calls."""
    asked = Question(text=question, stance="mechanism")
    made = calls or [
        SearchCall(
            question=question,
            query="fibrosis mechanism",
            source="pubmed",
            status=CallStatus.OK,
            hits=(_hit("doc-a"), _hit("doc-b", rank=1)),
            admitted=("doc-a",),
            dropped=("doc-b",),
            duration_seconds=0.4,
        )
    ]
    return ResearchResult(
        goal="fibrosis",
        stances=("mechanism",),
        threads=(
            ThreadRecord(
                question=asked,
                depth=depth,
                status=ThreadStatus.OK,
                call_ids=tuple(call.id for call in made),
            ),
        ),
        calls=tuple(made),
        findings=(),
        stop_reason=StopReason.DEPTH_EXHAUSTED,
        levels_run=depth,
    )


def test_a_search_round_trips_with_its_question_and_ranking(db: str) -> None:
    """The stored row answers what was asked and what came back."""
    run = store.create_run("provenance", "standard", "engine", {})
    result = _result()

    store.add_retrieval_calls(
        research_provenance.retrieval_call_rows(run.id, result)
    )

    rows = store.list_retrieval_calls(run.id)
    assert len(rows) == 1
    row = rows[0]
    assert row["question"] == "What drives fibrosis?"
    assert row["query"] == "fibrosis mechanism"
    assert row["source"] == "pubmed"
    assert row["status"] == "ok"
    assert row["depth"] == 1
    # The ranking is part of what a replay reproduces, not just the winners.
    assert [hit["locator"] for hit in row["hits"]] == ["doc-a", "doc-b"]
    assert [hit["rank"] for hit in row["hits"]] == [0, 1]
    # Seen-and-refused stays distinguishable from never-seen.
    assert row["admitted"] == ["doc-a"]
    assert row["dropped"] == ["doc-b"]
    assert row["question_id"] == result.threads[0].question.id


def test_the_same_search_persisted_twice_is_one_row(db: str) -> None:
    """A resumed run recognizes searches it already paid for.

    A call's id is a hash of what it is, so re-running the same question
    against the same source re-derives the same id. Writing it again must
    be a no-op rather than a duplicate, which is what makes replaying a
    partial ledger safe.
    """
    run = store.create_run("resume", "standard", "engine", {})
    rows = research_provenance.retrieval_call_rows(run.id, _result())

    assert store.add_retrieval_calls(rows) == 1
    assert store.add_retrieval_calls(rows) == 0

    assert len(store.list_retrieval_calls(run.id)) == 1


def test_two_runs_asking_the_same_thing_keep_separate_rows(db: str) -> None:
    """The call id carries no run, so the key has to.

    Two runs researching the same goal derive identical call ids. Under a
    bare primary key the second run's write would be silently ignored and
    its provenance would point at the first run's row -- or worse, the
    first run's deletion would take the second run's record with it.
    """
    first = store.create_run("goal", "standard", "engine", {})
    second = store.create_run("goal", "standard", "engine", {})
    result = _result()

    store.add_retrieval_calls(
        research_provenance.retrieval_call_rows(first.id, result)
    )
    store.add_retrieval_calls(
        research_provenance.retrieval_call_rows(second.id, result)
    )

    assert len(store.list_retrieval_calls(first.id)) == 1
    assert len(store.list_retrieval_calls(second.id)) == 1
    assert (
        store.list_retrieval_calls(first.id)[0]["id"]
        == store.list_retrieval_calls(second.id)[0]["id"]
    )

    store.delete_run(first.id)
    assert len(store.list_retrieval_calls(second.id)) == 1


def test_a_failed_search_is_recorded_not_dropped(db: str) -> None:
    """An unreachable source and an empty result must not look alike."""
    run = store.create_run("degraded", "standard", "engine", {})
    result = _result(
        calls=[
            SearchCall(
                question="What drives fibrosis?",
                query="fibrosis mechanism",
                source="pubmed",
                status=CallStatus.FAILED,
                error="connection refused",
                duration_seconds=0.1,
            ),
            SearchCall(
                question="What drives fibrosis?",
                query="fibrosis mechanism",
                source="corpus",
                status=CallStatus.EMPTY,
                duration_seconds=0.2,
            ),
        ]
    )

    store.add_retrieval_calls(
        research_provenance.retrieval_call_rows(run.id, result)
    )

    by_source = {
        row["source"]: row for row in store.list_retrieval_calls(run.id)
    }
    assert by_source["pubmed"]["status"] == "failed"
    assert by_source["pubmed"]["error"] == "connection refused"
    assert by_source["corpus"]["status"] == "empty"
    assert by_source["corpus"]["error"] is None
    assert by_source["corpus"]["hits"] == []


def test_a_deeper_search_records_the_level_it_ran_at(db: str) -> None:
    """A follow-up search and the search that provoked it differ."""
    run = store.create_run("descent", "standard", "engine", {})

    store.add_retrieval_calls(
        research_provenance.retrieval_call_rows(run.id, _result(depth=3))
    )

    assert store.list_retrieval_calls(run.id)[0]["depth"] == 3


def test_evidence_can_name_the_search_that_found_it(db: str) -> None:
    """The link exists in both directions of the join."""
    run = store.create_run("link", "standard", "engine", {})
    result = _result()
    rows = research_provenance.retrieval_call_rows(run.id, result)
    store.add_retrieval_calls(rows)

    ev_id = store.add_evidence(
        store.NewEvidence(
            run_id=run.id,
            title="Title doc-a",
            source="pubmed",
            retrieval_call_id=rows[0].id,
        )
    )

    stored = {row["id"]: row for row in store.list_evidence(run.id)}
    assert stored[ev_id]["retrieval_call_id"] == rows[0].id


def test_evidence_without_a_search_behind_it_stays_null(db: str) -> None:
    """An uploaded document has no query, and that is not a gap."""
    run = store.create_run("upload", "standard", "engine", {})

    ev_id = store.add_evidence(
        store.NewEvidence(run_id=run.id, title="Attached report")
    )

    stored = {row["id"]: row for row in store.list_evidence(run.id)}
    assert stored[ev_id]["retrieval_call_id"] is None


def test_a_result_with_no_searches_writes_nothing(db: str) -> None:
    """An empty batch is a no-op, not an empty INSERT."""
    run = store.create_run("empty", "standard", "engine", {})

    assert store.add_retrieval_calls([]) == 0
    assert store.list_retrieval_calls(run.id) == []
