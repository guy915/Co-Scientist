"""A run that reached no literature source says so in its report.

The engine records the fact; these tests pin that it survives the drain
and lands in the payload the workbench reads. It is the one degradation a
reader cannot infer from the output: the run still publishes ideas,
reviews and a tournament, and nothing in any of them reveals that none of
it was checked against a paper.
"""

from __future__ import annotations

from typing import Any

from app import store
from tests._drain_helpers import (
    _final_state_with_features,
    _persist_and_finalize,
)


def _final_state(degradation: dict[str, Any] | None) -> dict[str, Any]:
    """A drained run, with or without a retrieval outage behind it.

    An ordinary complete run otherwise: a degraded run publishes the same
    report a healthy one does, which is the whole problem.
    """
    return {
        **_final_state_with_features(),
        "retrieval_degradation": degradation,
    }


def test_the_report_carries_what_the_run_could_not_search(
    isolated_db: str,
) -> None:
    """Without this the run publishes as though it never needed sources."""
    run = store.create_run("degraded goal", "extended", "engine", {})

    _persist_and_finalize(
        run,
        _final_state(
            {
                "reason": "mcp_unreachable",
                "lost": ["literature_review", "deep_research"],
                "floor": "none",
            }
        ),
        isolated_db,
    )

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    degradation = report["payload"]["retrieval_degradation"]
    assert degradation["reason"] == "mcp_unreachable"
    assert degradation["floor"] == "none"
    assert "literature_review" in degradation["lost"]


def test_a_healthy_run_reports_no_degradation(isolated_db: str) -> None:
    """Absent rather than an empty shape, so the notice cannot misfire."""
    run = store.create_run("healthy goal", "extended", "engine", {})

    _persist_and_finalize(run, _final_state(None), isolated_db)

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["payload"]["retrieval_degradation"] is None
