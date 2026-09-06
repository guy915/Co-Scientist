"""The report payload carries every persisted review row to the reader (E1).

The mature Reflection cascade's full/simulation/recurrent reviews used to
stop at the engine's enrichments: the drain persisted only the initial
and deep-verification rows, and the report payload carried no reviews at
all. These tests pin the drain's distinctly labeled rows and the
payload's ``reviews`` field.
"""

from __future__ import annotations

from typing import Any

from app import store
from tests._drain_helpers import (
    _final_state_with_features,
    _final_state_with_lineage,
    _persist,
    _persist_and_finalize,
)


def _final_state_with_mature_enrichments() -> dict[str, Any]:
    """A features state whose first hypothesis also carries mature reviews."""
    state = _final_state_with_features()
    state["hypotheses"][0]["enrichments"] = {
        "full": {"verdict": "sound", "justification": "holds together"},
        "simulation": {"verdict": "holds", "decisive_step": "step two"},
    }
    return state


def test_report_payload_carries_every_persisted_review(
    isolated_db: str,
) -> None:
    """Deep and mature reviews all reach the persisted report payload."""
    run = store.create_run("review goal", "standard", "engine", {})

    _persist_and_finalize(
        run, _final_state_with_mature_enrichments(), isolated_db
    )

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    agents = sorted(
        row["reviewer_agent"] for row in report["payload"]["reviews"]
    )
    # The features fixture carries deep-verification probes; the
    # enrichments above add the mature cascade's distinctly labeled rows.
    assert "deep_verification" in agents
    assert "full_review" in agents
    assert "simulation_review" in agents


def test_report_payload_reviews_default_empty(isolated_db: str) -> None:
    """A run whose ideas carry no review rows still bears the field, empty.

    The lineage fixture has hypotheses (so the empty-leaderboard block
    does not fire) but no reviews and no probes, so no review rows exist.
    """
    run = store.create_run("no review goal", "standard", "engine", {})

    _persist_and_finalize(run, _final_state_with_lineage(), isolated_db)

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["payload"]["reviews"] == []


def test_mature_review_rows_are_distinctly_labeled(isolated_db: str) -> None:
    """Each mature review persists under its own reviewer_agent."""
    run = store.create_run("labeled goal", "standard", "engine", {})

    _persist(
        run_id=run.id,
        final_state=_final_state_with_mature_enrichments(),
        db_path=isolated_db,
    )

    reviews = store.list_reviews(run.id, db_path=isolated_db)
    summaries = {
        r["reviewer_agent"]: r["summary"]
        for r in reviews
        if r["reviewer_agent"] in ("full_review", "simulation_review")
    }
    assert summaries == {
        "full_review": "Full review verdict: sound",
        "simulation_review": "Simulation review verdict: holds",
    }
