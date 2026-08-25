"""Shared store-row builders for the app test suites.

Thin wrappers over the ``app.store`` writers, for suites whose subject is
something else entirely and that only need a persisted row to point their
assertions at. Used by ``test_hypothesis_screening.py`` and
``test_claim_grounding.py``.

Also holds the two narrowing readers below. ``store.get_run`` and
``store.get_latest_report`` return ``None`` for an absent row, which a test
that just created the run knows cannot happen -- asserting it once here
keeps that knowledge out of every call site.
"""

from __future__ import annotations

from typing import Any

from app import store


def _existing_run(run_id: str) -> store.RunRow:
    """The run row, asserted present."""
    run = store.get_run(run_id)
    assert run is not None, f"run {run_id} not found"
    return run


def _existing_report(run_id: str) -> dict[str, Any]:
    """The run's latest report row, asserted present."""
    report = store.get_latest_report(run_id)
    assert report is not None, f"no report for run {run_id}"
    return report


def _add(
    run_id: str,
    title: str,
    statement: str,
    db: str,
    mechanism: str = "",
) -> str:
    """Persist one hypothesis row and return its id.

    Args:
        run_id: Owning run.
        title: Hypothesis title.
        statement: The hypothesis text itself.
        db: Path to the per-test SQLite database.
        mechanism: Optional mechanism text; empty (the store's own default)
            unless a test is exercising the mechanism field.

    Returns:
        The new hypothesis's id.
    """
    return store.add_hypothesis(
        store.NewHypothesis(
            run_id=run_id, title=title, statement=statement, mechanism=mechanism
        ),
        db_path=db,
    )
