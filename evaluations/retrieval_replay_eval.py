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
(``store.retrieval_call_rows`` into ``store.add_retrieval_calls``), which
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
if str(_ROOT / "app") not in sys.path:
    sys.path.insert(0, str(_ROOT / "app"))

from evaluations._artifacts import write_dated_artifact  # noqa: E402

_SYNTHETIC_GOAL = "replay reproducibility fixture"


def score_run(run_id: str, db_path: str | None = None) -> dict[str, Any]:
    """No research calls means unscored, not a replayability failure."""
    from app.store import records as store
    from app.store import retrieval_calls as retrieval

    calls = retrieval.list_retrieval_calls(run_id, db_path=db_path)
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
    from co_scientist.research import content_id

    derived = content_id(
        "call",
        str(call.get("source") or ""),
        str(call.get("question") or ""),
        str(call.get("query") or ""),
    )
    return derived == str(call.get("id") or "")


def _result_set_complete(call: dict[str, Any]) -> bool:
    seen = {str(hit.get("locator")) for hit in call.get("hits") or []}
    acted = {str(x) for x in call.get("admitted") or []} | {
        str(x) for x in call.get("dropped") or []
    }
    return acted <= seen


def _ratio(hits: int, total: int) -> float | None:
    return round(hits / total, 4) if total else None


def score_synthetic(db_path: str) -> dict[str, Any]:
    """Exercise the real drain writer so mapping regressions fail without a
    provider.
    """
    from app.store import records, runs
    from app.store import retrieval_calls as store
    from app.store.records import NewEvidence

    run = runs.create_run(_SYNTHETIC_GOAL, "extended", "engine", {})
    result = _synthetic_result()
    store.add_retrieval_calls(
        store.retrieval_call_rows(run.id, result),
        db_path=db_path,
    )
    for finding in result.findings:
        call = next(c for c in result.calls if c.id == finding.call_id)
        records.add_evidence(
            NewEvidence(
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
    """Include read and budget-refused results to distinguish retrieval from
    evidence admission.
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
    if run_id:
        return {"mode": "persisted_run", **score_run(run_id)}
    previous = os.environ.get("COSCIENTIST_DB_PATH")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(pathlib.Path(tmp) / "replay.db")
        # The writer reads the store path from environment; restore it before
        # deleting the temporary tree.
        os.environ["COSCIENTIST_DB_PATH"] = db_path
        try:
            return {"mode": "synthetic", **score_synthetic(db_path)}
        finally:
            if previous is None:
                os.environ.pop("COSCIENTIST_DB_PATH", None)
            else:
                os.environ["COSCIENTIST_DB_PATH"] = previous


def main() -> int:
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
