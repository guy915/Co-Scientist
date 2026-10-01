"""Cancellation races with final safety and the empty-leaderboard block."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from app import engine_tasks, engine_tasks_node, store, task_worker
from app.config import settings
from app.report import build as report_build
from app.report import finalize as report_finalize
from app.safety import SafetyDecision, apply_safety_gate
from app.safety_redaction import REDACTED_PLACEHOLDER
from tests._client import make_client
from tests._engine_tasks_helpers import (
    _Generator,
    _patch_restore_generator,
    _seed_checkpoint,
    _task_state,
)


def _seed_leased_finalize(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    client_id: str,
    *,
    monitor_halt: bool = False,
) -> tuple[Any, dict[str, str], str, Any]:
    """Create an owner-scoped run with a real claimed finalize task."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    headers = {"X-Client-ID": client_id}
    created = owner.post(
        "/api/runs",
        headers=headers,
        json={
            "research_goal": "Study final safety cancellation",
            "tier": "express",
        },
    )
    assert created.status_code == 200, created.text
    run_id = str(created.json()["id"])
    store.update_run_status(
        run_id, store.RunStatus.RUNNING, db_path=isolated_db
    )

    state = _task_state(run_id)
    if monitor_halt:
        state["safety_blocked"] = True
        state["safety_decisions"] = [
            {
                "stage": "research_direction",
                "outcome": "prohibited",
                "reason": "Content matches a prohibited policy rule.",
                "matches": ["engineer smallpox for greater transmiss"],
            }
        ]
    checkpoint_seq = _seed_checkpoint(run_id, state, db_path=isolated_db)
    queued = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=engine_tasks.FINALIZE_TASK,
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key="final-safety-cancel-readiness",
        ),
        db_path=isolated_db,
    )
    task = store.claim_task(
        "final-safety-cancel-worker", run_id=run_id, db_path=isolated_db
    )
    assert task is not None and task.id == queued.id
    assert task.status == "leased"
    _patch_restore_generator(monkeypatch, _Generator(state))

    async def fake_drain(
        *_: Any, **__: Any
    ) -> tuple[Any, float, dict[str, Any]]:
        drained = SimpleNamespace(
            safety_counts={},
            grounding_counts={},
            report_inputs={"citation_summary": {}},
        )
        return drained, 1.0, {}

    monkeypatch.setattr(
        engine_tasks_node, "_drain_and_persist_final_state", fake_drain
    )
    return owner, headers, run_id, task


def _install_report(
    monkeypatch: pytest.MonkeyPatch, *, empty: bool = True
) -> None:
    """Stub a deterministic empty or publishable report."""
    leaderboard = (
        []
        if empty
        else [
            {
                "title": "Hypothesis with sensitive span",
                "statement": "The report contains sensitive span.",
            }
        ]
    )
    built = report_build._BuiltReport(
        payload={"idea_count": 1, "leaderboard": leaderboard},
        markdown="# Goal Report with sensitive span",
        facts=[],
        exclusion_tally={"rejected": 1},
    )

    async def fake_build_report(*_: Any, **__: Any) -> Any:
        return built

    monkeypatch.setattr(
        report_finalize, "build_report_content", fake_build_report
    )


def _assert_cancelled_task(
    owner: Any,
    headers: dict[str, str],
    run_id: str,
    task_id: str,
    db_path: str,
) -> list[dict[str, Any]]:
    """Return events after confirming the owner cancellation stayed terminal."""
    persisted = store.get_run(run_id, db_path=db_path)
    assert persisted is not None
    assert persisted.status == store.RunStatus.CANCELLED.value
    task = store.get_task(task_id, db_path=db_path)
    assert task is not None and task.status == "cancelled"
    return _owner_events(owner, headers, run_id)


def _owner_events(
    owner: Any, headers: dict[str, str], run_id: str
) -> list[dict[str, Any]]:
    response = owner.get(
        f"/api/runs/{run_id}/events?stream=false", headers=headers
    )
    assert response.status_code == 200, response.text
    return cast(list[dict[str, Any]], response.json()["events"])


@pytest.mark.asyncio
async def test_cancel_race_does_not_block_run(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale finalize cannot overwrite cancellation with a readiness block."""
    owner, headers, run_id, task = _seed_leased_finalize(
        isolated_db, monkeypatch, "readiness-cancel-owner"
    )
    _install_report(monkeypatch)

    async def allow_final_screen(*_: Any, **__: Any) -> Any:
        return SafetyDecision(stage="final", decision="allow")

    monkeypatch.setattr(
        report_finalize, "screen_with_escalation", allow_final_screen
    )
    cancel_responses: list[dict[str, Any]] = []
    block_for_empty_leaderboard = report_finalize._block_for_empty_leaderboard

    async def cancel_before_readiness_write(*args: Any, **kwargs: Any) -> Any:
        response = owner.post(f"/api/runs/{run_id}/cancel", headers=headers)
        assert response.status_code == 200, response.text
        cancel_responses.append(response.json())
        async for event in block_for_empty_leaderboard(*args, **kwargs):
            yield event

    monkeypatch.setattr(
        report_finalize,
        "_block_for_empty_leaderboard",
        cancel_before_readiness_write,
    )

    # The finalize task passed its status check; cancel before readiness writes.
    with pytest.raises(task_worker._LeaseLostError):
        await engine_tasks.execute_finalize(task, db_path=isolated_db)

    assert cancel_responses == [{"id": run_id, "status": "cancelled"}]
    events = _assert_cancelled_task(
        owner, headers, run_id, task.id, isolated_db
    )
    readiness = [
        item
        for item in store.list_safety_decisions(run_id, db_path=isolated_db)
        if item["stage"] == "scientific_readiness"
    ]
    statuses = [
        event["payload"].get("status")
        for event in events
        if event["type"] == "status"
    ]
    assert readiness == []
    assert statuses == ["cancelled"]


@pytest.mark.asyncio
async def test_empty_leaderboard_block_remains_auditable(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valid empty-board block remains ordered and auditable."""
    owner, headers, run_id, task = _seed_leased_finalize(
        isolated_db, monkeypatch, "readiness-block-owner"
    )
    _install_report(monkeypatch)

    async def allow_final_screen(*_: Any, **__: Any) -> Any:
        return SafetyDecision(stage="final", decision="allow")

    monkeypatch.setattr(
        report_finalize, "screen_with_escalation", allow_final_screen
    )

    result = await engine_tasks.execute_finalize(task, db_path=isolated_db)

    persisted = store.get_run(run_id, db_path=isolated_db)
    assert result["status"] == store.RunStatus.BLOCKED.value
    assert persisted is not None
    assert persisted.status == store.RunStatus.BLOCKED.value
    readiness = [
        item
        for item in store.list_safety_decisions(run_id, db_path=isolated_db)
        if item["stage"] == "scientific_readiness"
    ]
    assert len(readiness) == 1
    assert readiness[0]["decision"] == "block"

    events = _owner_events(owner, headers, run_id)
    final_event = next(
        event for event in events if event["type"] == "safety.final"
    )
    blocked_event = next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "blocked"
    )
    assert final_event["seq"] < blocked_event["seq"]
    assert not any(event["type"] == "report" for event in events)
    assert store.get_latest_report(run_id, db_path=isolated_db) is None


@pytest.mark.asyncio
async def test_leased_finalize_redaction_audits_and_scrubs_report(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A leased final screen keeps its audit span and scrubs report copies."""
    owner, headers, run_id, task = _seed_leased_finalize(
        isolated_db, monkeypatch, "final-redaction-owner"
    )
    _install_report(monkeypatch, empty=False)

    async def redact_final_screen(*_: Any, **__: Any) -> Any:
        return SafetyDecision(
            stage="final",
            decision="redact",
            matches=["sensitive span"],
        )

    monkeypatch.setattr(
        report_finalize, "screen_with_escalation", redact_final_screen
    )

    result = await engine_tasks.execute_finalize(task, db_path=isolated_db)

    assert result["status"] == store.RunStatus.COMPLETED.value
    final_decisions = [
        item
        for item in store.list_safety_decisions(run_id, db_path=isolated_db)
        if item["stage"] == "final"
    ]
    assert len(final_decisions) == 1
    assert final_decisions[0]["decision"] == "redact"
    assert final_decisions[0]["matches"] == ["sensitive span"]

    saved = store.get_latest_report(run_id, db_path=isolated_db)
    assert saved is not None
    assert "sensitive span" not in repr(saved["payload"]).lower()
    assert REDACTED_PLACEHOLDER in repr(saved["payload"])
    assert "sensitive span" not in saved["markdown_text"].lower()
    assert REDACTED_PLACEHOLDER in saved["markdown_text"]

    events = _owner_events(owner, headers, run_id)
    final_event = next(
        event for event in events if event["type"] == "safety.final"
    )
    report_event = next(event for event in events if event["type"] == "report")
    completed_event = next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "completed"
    )
    assert final_event["seq"] < report_event["seq"] < completed_event["seq"]
    assert "sensitive span" not in repr(report_event["payload"]).lower()


@pytest.mark.asyncio
async def test_cancel_before_monitor_halt_gate_leaves_no_halt_audit(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A monitor verdict cannot write after owner cancellation."""
    owner, headers, run_id, task = _seed_leased_finalize(
        isolated_db,
        monkeypatch,
        "monitor-halt-cancel-owner",
        monitor_halt=True,
    )
    cancel_responses: list[dict[str, Any]] = []

    async def cancel_before_monitor_gate(
        gated_run_id: str, decision: SafetyDecision, emit: Any, **kwargs: Any
    ) -> Any:
        response = owner.post(f"/api/runs/{run_id}/cancel", headers=headers)
        assert response.status_code == 200, response.text
        cancel_responses.append(response.json())
        async for event in apply_safety_gate(
            gated_run_id, decision, emit, **kwargs
        ):
            yield event

    monkeypatch.setattr(
        engine_tasks_node, "apply_safety_gate", cancel_before_monitor_gate
    )

    with pytest.raises(task_worker._LeaseLostError):
        await engine_tasks.execute_finalize(task, db_path=isolated_db)

    assert cancel_responses == [{"id": run_id, "status": "cancelled"}]
    events = _assert_cancelled_task(
        owner, headers, run_id, task.id, isolated_db
    )
    monitor = [
        item
        for item in store.list_safety_decisions(run_id, db_path=isolated_db)
        if item["stage"] == "research_direction"
    ]
    assert monitor == []
    assert not any(
        event["type"] == "safety.research_direction" for event in events
    )
    assert [
        event["payload"].get("status")
        for event in events
        if event["type"] == "status"
    ] == ["cancelled"]


@pytest.mark.asyncio
async def test_leased_monitor_halt_remains_auditable(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valid leased monitor halt remains visible in owner event replay."""
    owner, headers, run_id, task = _seed_leased_finalize(
        isolated_db,
        monkeypatch,
        "monitor-halt-audit-owner",
        monitor_halt=True,
    )

    result = await engine_tasks.execute_finalize(task, db_path=isolated_db)

    persisted = store.get_run(run_id, db_path=isolated_db)
    assert result["status"] == store.RunStatus.BLOCKED.value
    assert persisted is not None
    assert persisted.status == store.RunStatus.BLOCKED.value
    monitor = [
        item
        for item in store.list_safety_decisions(run_id, db_path=isolated_db)
        if item["stage"] == "research_direction"
    ]
    assert len(monitor) == 1
    assert monitor[0]["decision"] == "block"
    assert monitor[0]["matches"] == ["engineer smallpox for greater transmiss"]

    events = _owner_events(owner, headers, run_id)
    halt_event = next(
        event
        for event in events
        if event["type"] == "safety.research_direction"
    )
    blocked_event = next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "blocked"
    )
    assert halt_event["seq"] < blocked_event["seq"]
    assert not any(event["type"] == "report" for event in events)


@pytest.mark.parametrize("decision", ["allow", "redact"])
@pytest.mark.asyncio
async def test_cancel_during_final_screen_has_no_final_safety_audit(
    decision: str,
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation during screening fences final decision and event writes."""
    owner, headers, run_id, task = _seed_leased_finalize(
        isolated_db, monkeypatch, f"final-screen-cancel-{decision}"
    )
    _install_report(monkeypatch)
    cancel_responses: list[dict[str, Any]] = []

    async def cancel_then_decide(*_: Any, **__: Any) -> Any:
        response = owner.post(f"/api/runs/{run_id}/cancel", headers=headers)
        assert response.status_code == 200, response.text
        cancel_responses.append(response.json())
        matches = ["sensitive span"] if decision == "redact" else []
        return SafetyDecision(stage="final", decision=decision, matches=matches)

    monkeypatch.setattr(
        report_finalize, "screen_with_escalation", cancel_then_decide
    )

    with pytest.raises(task_worker._LeaseLostError):
        await engine_tasks.execute_finalize(task, db_path=isolated_db)

    assert cancel_responses == [{"id": run_id, "status": "cancelled"}]
    events = _assert_cancelled_task(
        owner, headers, run_id, task.id, isolated_db
    )
    final_decisions = [
        item
        for item in store.list_safety_decisions(run_id, db_path=isolated_db)
        if item["stage"] == "final"
    ]
    assert final_decisions == []
    assert not any(event["type"] == "safety.final" for event in events)
    assert not any(event["type"] == "report" for event in events)
    assert store.get_latest_report(run_id, db_path=isolated_db) is None
