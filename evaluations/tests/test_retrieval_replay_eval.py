"""Replay reproducibility over a run's own retrieval record.

The synthetic mode goes through the real writer, so these are checks on
the mapping and the schema rather than on a fixture: a change that stops
a persisted call re-deriving its own id, or that drops what the budget
passed over, fails here without a provider key or a search service.
"""

from __future__ import annotations

from evaluations.retrieval_replay_eval import (
    _rederives,
    _result_set_complete,
    run,
)


def test_a_persisted_ledger_replays_exactly() -> None:
    """Everything the record needs to be reconstructable, end to end."""
    report = run(None)

    assert report["mode"] == "synthetic"
    assert report["calls"] == 2
    assert report["id_reproduction"] == 1.0
    assert report["result_set_completeness"] == 1.0
    # The evidence row written from a finding names the search that
    # surfaced it, and that id resolves against the same run's calls.
    assert report["evidence_with_provenance"] == 1
    assert report["evidence_resolution"] == 1.0


def test_a_rewritten_question_stops_the_id_reproducing() -> None:
    """The id is a hash over the fields, so this is the whole guarantee.

    A row whose question was edited after the fact keeps a stored id that
    no longer follows from its own contents -- which is exactly the state
    a replay cannot detect any other way.
    """
    call = {
        "id": "0" * 32,
        "source": "pubmed",
        "question": "what was actually asked",
        "query": "a query",
    }

    assert not _rederives(call)


def test_a_result_set_missing_what_was_read_is_incomplete() -> None:
    """Admitting a locator the record never saw is an unreplayable gap."""
    assert not _result_set_complete(
        {"hits": [{"locator": "1"}], "admitted": ["2"], "dropped": []}
    )
    assert _result_set_complete(
        {"hits": [{"locator": "1"}], "admitted": ["1"], "dropped": []}
    )
