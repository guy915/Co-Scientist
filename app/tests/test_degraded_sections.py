"""Reader-facing visibility of engine schema degradations (L7).

The engine records every enhancement node served a placeholder fallback
instead of parseable LLM output (``degraded_nodes`` in workflow state).
These tests pin the app half: the drain hands the list to the report
path, the persisted report payload carries it as ``degraded_sections``,
and canonical node events surface it once a commit holds it -- so a blank
report section can explain itself instead of showing silence.
"""

from __future__ import annotations

from typing import Any

from app import report_render, store
from app.engine_adapter.events import (
    _canonical_engine_payload,
    _canonical_event_type,
)
from tests._drain_helpers import _final_state_with_features, _persist


def test_drain_result_carries_degraded_sections(isolated_db: str) -> None:
    """The drain hands the engine's degraded nodes to the report path."""
    run = store.create_run("degraded goal", "standard", "engine", {})
    state = _final_state_with_features()
    state["degraded_nodes"] = ["meta_review", "research_overview"]

    drained = _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    assert drained.report_inputs["degraded_sections"] == [
        "meta_review",
        "research_overview",
    ]


def test_drain_result_defaults_to_no_degraded_sections(
    isolated_db: str,
) -> None:
    """A run without degradations reports an empty list, not an absent key."""
    run = store.create_run("clean goal", "standard", "engine", {})

    drained = _persist(
        run_id=run.id,
        final_state=_final_state_with_features(),
        db_path=isolated_db,
    )

    assert drained.report_inputs["degraded_sections"] == []


def test_report_payload_carries_degraded_sections(isolated_db: str) -> None:
    """The persisted report payload names the sections that degraded."""
    run = store.create_run("degraded goal", "standard", "engine", {})
    state = _final_state_with_features()
    state["degraded_nodes"] = ["meta_review"]

    drained = _persist(run_id=run.id, final_state=state, db_path=isolated_db)

    async def _emit(type_: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"type": type_, "payload": payload}

    from tests._client import drain as _drain

    _drain(
        report_render.finalize_report(
            run.id,
            report_render.ReportRequest(
                research_goal=run.research_goal,
                run_mode="standard",
                provider="engine",
                execution_time=1.0,
                db_path=isolated_db,
                **drained.report_inputs,
            ),
            _emit,
        )
    )

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["payload"]["degraded_sections"] == ["meta_review"]


def test_report_payload_degraded_sections_default_empty(
    isolated_db: str,
) -> None:
    """Reports for clean runs still carry the field, empty."""
    run = store.create_run("clean goal", "standard", "engine", {})

    drained = _persist(
        run_id=run.id,
        final_state=_final_state_with_features(),
        db_path=isolated_db,
    )

    async def _emit(type_: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {"type": type_, "payload": payload}

    from tests._client import drain as _drain

    _drain(
        report_render.finalize_report(
            run.id,
            report_render.ReportRequest(
                research_goal=run.research_goal,
                run_mode="standard",
                provider="engine",
                execution_time=1.0,
                db_path=isolated_db,
                **drained.report_inputs,
            ),
            _emit,
        )
    )

    report = store.get_latest_report(run.id, db_path=isolated_db)
    assert report is not None
    assert report["payload"]["degraded_sections"] == []


def test_node_event_payload_surfaces_degraded_nodes() -> None:
    """A node commit holding degradations carries them on its event."""
    state: dict[str, Any] = {
        "current_iteration": 1,
        "degraded_nodes": ["deep_verification"],
    }

    payload = _canonical_engine_payload(
        "ranking", _canonical_event_type("ranking"), state
    )

    assert payload["degraded"] == ["deep_verification"]


def test_node_event_payload_omits_degraded_when_clean() -> None:
    """Clean runs emit no degraded key on their node events."""
    state: dict[str, Any] = {"current_iteration": 0, "degraded_nodes": []}

    payload = _canonical_engine_payload(
        "generate", _canonical_event_type("generate"), state
    )

    assert "degraded" not in payload
