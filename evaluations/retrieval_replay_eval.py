"""Can a run's retrieval be reconstructed from its record alone?

This is the metric Stage B of the deep-research work bought and nothing
could measure before it: until a run persisted the *question* and the
*query* behind each search, "replay this run's retrieval" was not a
question the store could answer.

What it scores, per persisted run:

- **id reproduction** -- every ``retrieval_calls`` row's id re-derived
  from the fields the row itself carries, and compared with the stored
  id. A call's id is a content hash over ``(source, question, query)``,
  so a row whose id does not re-derive is a row whose defining fields
  were lost or rewritten somewhere between the search and the disk. This
  is the load-bearing one: content addressing is what makes a replay
  comparable to the original at all.
- **evidence resolution** -- the fraction of evidence rows carrying a
  ``retrieval_call_id`` that resolves to a call in the same run. An id
  pointing at nothing is worse than a null: it reads as provenance.
- **result-set completeness** -- every locator a call admitted or
  dropped appears in the hits it recorded. A record that shows what was
  read but not what was passed over cannot reproduce the budget's
  choices, only its outcome.

**Offline by default, and honest about what that proves.** With no
provider key and no MCP server a driven run does no research at all, so
scoring one would measure an empty set and report a perfect score. The
default instead persists a synthetic ledger through the real writer
(``app.research_provenance`` into ``store.add_retrieval_calls``), which
exercises the serialization and the schema but not any model or network.
``--run <id>`` scores a real run already in the store, which is the mode
that says anything about production. Every artifact records which mode
produced it.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import tempfile
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parent.parent
# The viewer backend is a plain package under app/, reached the way every
# other runner here reaches it; the engine is an installed dependency.
if str(_ROOT / "app") not in sys.path:
    sys.path.insert(0, str(_ROOT / "app"))

from evaluations._artifacts import write_dated_artifact  # noqa: E402

_SYNTHETIC_GOAL = "replay reproducibility fixture"


def score_run(run_id: str, db_path: str | None = None) -> dict[str, Any]:
    """Score one persisted run's retrieval record for replayability.

    Args:
        run_id: The run to score.
        db_path: Optional override for the SQLite database path.

    Returns:
        The metric block. ``calls`` of 0 means the run bought no
        research, which is reported rather than scored -- express and
        standard runs do not, and neither does a run whose sources were
        unreachable.
    """
    from app import store

    calls = store.list_retrieval_calls(run_id, db_path=db_path)
    evidence = store.list_evidence(run_id, db_path=db_path)
    known = {str(call["id"]) for call in calls}
    pointed = [
        row for row in evidence if row.get("retrieval_call_id") is not None
    ]
    return {
        "run_id": run_id,
        "calls": len(calls),
        "id_reproduction": _ratio(
            sum(1 for call in calls if _rederives(call)), len(calls)
        ),
        "result_set_completeness": _ratio(
            sum(1 for call in calls if _result_set_complete(call)), len(calls)
        ),
        "evidence_rows": len(evidence),
        "evidence_with_provenance": len(pointed),
        "evidence_resolution": _ratio(
            sum(1 for row in pointed if str(row["retrieval_call_id"]) in known),
            len(pointed),
        ),
    }


def _rederives(call: dict[str, Any]) -> bool:
    """Whether a stored call's id follows from the fields it carries."""
    from co_scientist.research import content_id

    derived = content_id(
        "call",
        str(call.get("source") or ""),
        str(call.get("question") or ""),
        str(call.get("query") or ""),
    )
    return derived == str(call.get("id") or "")


def _result_set_complete(call: dict[str, Any]) -> bool:
    """Whether everything the call acted on is in what it recorded seeing."""
    seen = {str(hit.get("locator")) for hit in call.get("hits") or []}
    acted = {str(x) for x in call.get("admitted") or []} | {
        str(x) for x in call.get("dropped") or []
    }
    return acted <= seen


def _ratio(hits: int, total: int) -> float | None:
    """A rate, or None when there was nothing to rate."""
    return round(hits / total, 4) if total else None


def score_synthetic(db_path: str) -> dict[str, Any]:
    """Persist a synthetic ledger through the real writer, then score it.

    The point is the path, not the numbers: the same mapping and the same
    insert the drain uses, so a change that breaks replayability breaks
    this without needing a provider key or a search service.
    """
    from app import research_provenance, store

    run = store.create_run(_SYNTHETIC_GOAL, "extended", "engine", {})
    result = _synthetic_result()
    store.add_retrieval_calls(
        research_provenance.retrieval_call_rows(run.id, result),
        db_path=db_path,
    )
    for finding in result.findings:
        call = next(c for c in result.calls if c.id == finding.call_id)
        store.add_evidence(
            store.NewEvidence(
                run_id=run.id,
                title=f"paper {finding.locator}",
                source=call.source,
                abstract=finding.span,
                retrieval_call_id=finding.call_id,
            ),
            db_path=db_path,
        )
    return score_run(run.id, db_path=db_path)


def _synthetic_result() -> Any:
    """One research request, in the shape the engine hands the drain.

    Two searches for one question so the ledger is not degenerate: one
    that found a document worth reading and one whose results the
    evidence budget refused, since telling those apart is most of what
    the record is for.
    """
    from co_scientist.research import (
        Finding,
        Question,
        ResearchResult,
        StopReason,
        ThreadRecord,
        ThreadStatus,
    )

    question = "What blocks fibrotic signalling in humans?"
    read, passed_over = _synthetic_calls(question)
    finding = Finding(
        text="Blockade reduced fibrosis in a human cohort",
        question=question,
        locator="1",
        span="Blockade reduced fibrosis in a human cohort.",
        call_id=read.id,
    )
    return ResearchResult(
        goal=_SYNTHETIC_GOAL,
        stances=(),
        threads=(
            ThreadRecord(
                question=Question(text=question, stance="seed"),
                depth=1,
                status=ThreadStatus.OK,
                call_ids=(read.id, passed_over.id),
                finding_ids=(finding.id,),
            ),
        ),
        calls=(read, passed_over),
        findings=(finding,),
        stop_reason=StopReason.NO_FOLLOW_UPS,
        levels_run=1,
    )


def _synthetic_calls(question: str) -> tuple[Any, Any]:
    """The two searches: one read from, one entirely passed over."""
    from co_scientist.research import CallStatus, SearchCall, SourceHit

    query = "fibrosis signalling blockade human"
    return (
        SearchCall(
            question=question,
            query=query,
            source="pubmed",
            status=CallStatus.OK,
            hits=(
                SourceHit(locator="1", title="Read", snippet="s", rank=0),
                SourceHit(locator="2", title="Refused", snippet="s", rank=1),
            ),
            admitted=("1",),
            dropped=("2",),
        ),
        SearchCall(
            question=question,
            query=query,
            source="openalex",
            status=CallStatus.OK,
            hits=(
                SourceHit(locator="3", title="Also seen", snippet="", rank=0),
            ),
            dropped=("3",),
        ),
    )


def run(run_id: str | None) -> dict[str, Any]:
    """Score a named run, or a synthetic ledger when none is named."""
    if run_id:
        return {"mode": "persisted_run", **score_run(run_id)}
    previous = os.environ.get("COSCIENTIST_DB_PATH")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(pathlib.Path(tmp) / "replay.db")
        # `store.create_run` is the one call here that takes no `db_path`;
        # it reads the env var directly in store/db.py. Restore it after,
        # or a caller in the same process is left pointing at this
        # directory once the temporary tree is gone.
        os.environ["COSCIENTIST_DB_PATH"] = db_path
        try:
            return {"mode": "synthetic", **score_synthetic(db_path)}
        finally:
            if previous is None:
                os.environ.pop("COSCIENTIST_DB_PATH", None)
            else:
                os.environ["COSCIENTIST_DB_PATH"] = previous


def main() -> int:
    """Score replay reproducibility, write an artifact, print a summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        default=None,
        help="Score this persisted run instead of a synthetic ledger.",
    )
    args = parser.parse_args()

    report = run(args.run)
    out = write_dated_artifact(report, f"retrieval-replay-{report['mode']}")
    print(
        f"retrieval replay [{report['mode']}]: calls={report['calls']} "
        f"id_reproduction={report['id_reproduction']} "
        f"result_set_completeness={report['result_set_completeness']} "
        f"evidence_resolution={report['evidence_resolution']}"
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
