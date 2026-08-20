"""The drain closing the loop on retrieval provenance.

The store has held a ``retrieval_calls`` table and a
``evidence.retrieval_call_id`` column since the schema change that made
room for them, and until a run actually wrote both the column stayed
NULL. These tests pin the end of that path: a run whose literature review
went back for its open questions leaves searches on record, and every
piece of evidence it found names the search that found it.

The final states here are synthetic, in the shape the engine's literature
review produces -- a ``research_ledger`` of everything the research did,
and articles stamped with the call that surfaced them.
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
    result_to_dict,
)

from app import store
from tests._drain_helpers import _persist_and_finalize

_CALL = SearchCall(
    question="What blocks TGF-beta signalling in humans?",
    query="TGF-beta blockade human fibrosis",
    source="pubmed",
    status=CallStatus.OK,
    hits=(
        SourceHit(
            locator="12345678",
            title="A researched paper",
            snippet="TGF-beta blockade reduced fibrosis.",
            rank=0,
            score=0.8,
        ),
        SourceHit(locator="99999999", title="Also seen", snippet="", rank=1),
    ),
    admitted=("12345678",),
    dropped=("99999999",),
    duration_seconds=0.6,
)


def _ledger() -> dict[str, Any]:
    """One research request, as the engine carries it out on the state."""
    finding = Finding(
        text="TGF-beta blockade reduced fibrosis in a human cohort",
        question=_CALL.question,
        locator="12345678",
        span="TGF-beta blockade reduced fibrosis.",
        call_id=_CALL.id,
    )
    return result_to_dict(
        ResearchResult(
            goal="reverse fibrosis",
            stances=(),
            threads=(
                ThreadRecord(
                    question=Question(text=_CALL.question, stance="seed"),
                    depth=1,
                    status=ThreadStatus.OK,
                    call_ids=(_CALL.id,),
                    finding_ids=(finding.id,),
                    summary="Human evidence exists but is thin.",
                ),
            ),
            calls=(_CALL,),
            findings=(finding,),
            stop_reason=StopReason.NO_FOLLOW_UPS,
            levels_run=1,
        )
    )


def _final_state(*, researched: bool) -> dict[str, Any]:
    """A drained run, with or without a research phase behind it."""
    article: dict[str, Any] = {
        "title": "A researched paper",
        "source": "pubmed",
        "source_id": "12345678",
        "url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
        "abstract": "TGF-beta blockade reduced fibrosis.",
    }
    state: dict[str, Any] = {
        "hypotheses": [],
        "articles": [article],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }
    if researched:
        article["retrieval_call_id"] = _CALL.id
        state["research_ledger"] = _ledger()
    return state


def test_evidence_resolves_to_the_search_that_found_it(
    isolated_db: str,
) -> None:
    """The join the whole provenance change exists to make possible.

    Both halves have to land in the same drain: the search on record,
    and the evidence row naming it. Either alone is unusable -- a call
    nothing points at, or an id pointing at nothing.
    """
    run = store.create_run("provenance goal", "extended", "engine", {})

    _persist_and_finalize(run, _final_state(researched=True), isolated_db)

    evidence = store.list_evidence(run.id, db_path=isolated_db)
    calls = store.list_retrieval_calls(run.id, db_path=isolated_db)
    assert len(evidence) == 1
    assert len(calls) == 1
    by_id = {call["id"]: call for call in calls}
    found_by = by_id[evidence[0]["retrieval_call_id"]]
    assert found_by["query"] == "TGF-beta blockade human fibrosis"
    assert found_by["question"] == _CALL.question
    assert found_by["source"] == "pubmed"


def test_what_was_seen_and_not_read_stays_on_record(
    isolated_db: str,
) -> None:
    """A coverage report cannot tell "unseen" from "seen and skipped"."""
    run = store.create_run("coverage goal", "extended", "engine", {})

    _persist_and_finalize(run, _final_state(researched=True), isolated_db)

    call = store.list_retrieval_calls(run.id, db_path=isolated_db)[0]
    assert [hit["locator"] for hit in call["hits"]] == ["12345678", "99999999"]
    assert call["admitted"] == ["12345678"]
    assert call["dropped"] == ["99999999"]
    assert call["depth"] == 1


def test_a_run_that_did_no_research_writes_no_searches(
    isolated_db: str,
) -> None:
    """Express and standard runs do not buy the phase, and that is fine."""
    run = store.create_run("shallow goal", "standard", "engine", {})

    _persist_and_finalize(run, _final_state(researched=False), isolated_db)

    assert store.list_retrieval_calls(run.id, db_path=isolated_db) == []
    evidence = store.list_evidence(run.id, db_path=isolated_db)
    assert evidence[0]["retrieval_call_id"] is None


def test_the_run_tier_reaches_the_engine_verbatim(isolated_db: str) -> None:
    """Which tiers research is the engine's list, and only its list.

    The app passes the tier rather than a yes/no, so the two sides cannot
    drift into disagreeing about which runs buy the phase. A legacy tier
    name is normalized on the way, since the engine matches on the
    current vocabulary.
    """
    from app.engine_adapter import _build_engine_opts

    run = store.create_run("tier goal", "ultra", "engine", {})

    opts = _build_engine_opts({"tier": "advanced"}, run.id, isolated_db)

    assert opts["research_tier"] == "ultra"
