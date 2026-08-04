"""Shared store-row builders for the app test suites.

Thin wrappers over the ``app.store`` writers, for suites whose subject is
something else entirely and that only need a persisted row to point their
assertions at. Used by ``test_hypothesis_screening.py`` and
``test_claim_grounding.py``.
"""

from __future__ import annotations

from app import store


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
