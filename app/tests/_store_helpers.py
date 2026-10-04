# Narrow optional results only after creating their rows.

from __future__ import annotations

from typing import Any

from app.store import hypotheses as store
from app.store import reports, runs
from app.store.hypotheses import NewHypothesis
from app.store.models import RunRow


def _existing_run(run_id: str) -> RunRow:
    run = runs.get_run(run_id)
    assert run is not None, f"run {run_id} not found"
    return run


def _existing_report(run_id: str) -> dict[str, Any]:
    report = reports.get_latest_report(run_id)
    assert report is not None, f"no report for run {run_id}"
    return report


def _add(
    run_id: str,
    title: str,
    statement: str,
    db: str,
    mechanism: str = "",
) -> str:
    return store.add_hypothesis(
        NewHypothesis(
            run_id=run_id, title=title, statement=statement, mechanism=mechanism
        ),
        db_path=db,
    )
