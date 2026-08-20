"""A research result has to survive a checkpoint.

The artifacts are frozen dataclasses holding enums and tuples, and the
state they travel in carries JSON only. These tests pin the properties
that make the round trip worth having: ids re-derive from content rather
than being stored, the source's own ranking comes back intact, and a
payload written by an older build still loads.
"""

from __future__ import annotations

from typing import Any

from co_scientist.research import (
    CallStatus,
    Finding,
    Question,
    ResearchResult,
    SearchCall,
    SourceHit,
    StopReason,
    ThreadRecord,
    ThreadStatus,
    result_from_dict,
    result_to_dict,
)


def _result() -> ResearchResult:
    """A result carrying one of everything worth losing."""
    call = SearchCall(
        question="What drives fibrosis?",
        query="fibrosis mechanism",
        source="pubmed",
        status=CallStatus.OK,
        hits=(
            SourceHit(
                locator="doc-a",
                title="First",
                snippet="about a",
                rank=0,
                score=0.9,
                metadata={"doi": "10.1/a"},
            ),
            SourceHit(
                locator="doc-b", title="Second", snippet="about b", rank=1
            ),
        ),
        admitted=("doc-a",),
        dropped=("doc-b",),
        duration_seconds=0.4,
    )
    finding = Finding(
        text="TGF-beta drives it",
        question="What drives fibrosis?",
        locator="doc-a",
        span="TGF-beta signalling drives fibrosis",
        call_id=call.id,
    )
    return ResearchResult(
        goal="reverse fibrosis",
        stances=("mechanism", "counter-evidence"),
        threads=(
            ThreadRecord(
                question=Question(
                    text="What drives fibrosis?", stance="mechanism"
                ),
                depth=1,
                status=ThreadStatus.OK,
                call_ids=(call.id,),
                finding_ids=(finding.id,),
                follow_ups=("what blocks it?",),
                summary="TGF-beta is the consensus driver.",
            ),
            ThreadRecord(
                question=Question(text="what blocks it?", stance="mechanism"),
                depth=2,
                status=ThreadStatus.DECLINED,
                note="breadth exhausted",
                retry_breadth=4,
            ),
        ),
        calls=(call,),
        findings=(finding,),
        stop_reason=StopReason.NO_FOLLOW_UPS,
        levels_run=2,
    )


def test_a_result_survives_the_trip_through_plain_data() -> None:
    """Everything the caller reads back has to come back."""
    original = _result()

    restored = result_from_dict(result_to_dict(original))

    assert restored == original


def test_ids_are_re_derived_rather_than_stored() -> None:
    """A stored id could disagree with what its fields hash to."""
    original = _result()

    payload = result_to_dict(original)
    restored = result_from_dict(payload)

    assert "id" not in payload["calls"][0]
    assert "id" not in payload["findings"][0]
    assert restored.calls[0].id == original.calls[0].id
    assert restored.findings[0].call_id == original.calls[0].id


def test_the_source_ranking_comes_back_intact() -> None:
    """A replay reproduces what the source returned, not just the winners."""
    restored = result_from_dict(result_to_dict(_result()))

    hits = restored.calls[0].hits
    assert [hit.locator for hit in hits] == ["doc-a", "doc-b"]
    assert [hit.rank for hit in hits] == [0, 1]
    assert hits[0].score == 0.9
    assert hits[0].metadata["doi"] == "10.1/a"
    assert restored.calls[0].dropped == ("doc-b",)


def test_a_payload_from_an_older_build_still_loads() -> None:
    """Missing keys take their default; unknown ones are ignored."""
    payload: dict[str, Any] = {
        "goal": "reverse fibrosis",
        "calls": [
            {
                "question": "q",
                "query": "q terms",
                "source": "pubmed",
                "status": "ok",
                "something_new": 1,
            }
        ],
        "stop_reason": "invented_reason",
    }

    restored = result_from_dict(payload)

    assert restored.goal == "reverse fibrosis"
    assert restored.calls[0].hits == ()
    assert restored.stop_reason is StopReason.DEPTH_EXHAUSTED
    assert restored.threads == ()
