from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app import engine_tasks, task_worker
from app.config import settings
from app.engine_tasks import finalize as engine_tasks_node
from app.engine_tasks import support as engine_tasks_support
from app.main import app
from app.report import build as report_build
from app.report import content as report_content
from app.report import finalize as report_finalize
from app.report import gates as report_gates
from app.safety import SafetyDecision, apply_safety_gate
from app.safety.types import REDACTED_PLACEHOLDER
from app.store import checkpoints, db, hypotheses, records, reports, runs, tasks
from app.store import events as store_events
from app.store import retrieval_calls as retrieval
from app.store import tasks_lifecycle as lifecycle
from app.store.hypotheses import HypothesisStateChanges, NewHypothesis
from app.store.models import RunStatus
from app.store.records import NewClaimEvidence, NewEvidence
from tests._client import create_run as _create_run
from tests._client import make_client
from tests._engine_tasks_helpers import (
    _Generator,
    _install_runtime,
    _patch_restore_generator,
    _seed_checkpoint,
    _task_state,
    fake_final_drain,
)
from tests._store_helpers import enqueue_task, seed_checkpoint, seed_run
from tests.test_report_cancel_publication import (
    _OWNER,
    _install_report_stubs,
    _seed_owned_finalize,
)


def _hypothesis(identifier: str, status: str) -> dict[str, object]:
    return {
        "id": identifier,
        "title": "An idea",
        "text": "An idea that is both rejected and contradicted.",
        "status": status,
        "safety_status": "allowed",
    }


def _contradicting_edge(hypothesis_id: str) -> dict[str, object]:
    return {
        "hypothesis_id": hypothesis_id,
        "claim": "The idea contradicts prior data.",
        "label": "contradicts",
        "claim_role": "categorical",
        "supporting": [],
        "contradicting": [],
        "assessor": "llm",
    }


def test_rejected_and_contradicted_idea_agrees_across_both_surfaces() -> None:
    # Status exclusions precede contradiction exclusions across shared report
    # surfaces.
    hyp = _hypothesis("h1", "rejected")
    edges = [_contradicting_edge("h1")]

    contradicted = report_gates.contradicted_hypothesis_ids("run1", None, edges)
    assert "h1" in contradicted

    buckets = report_content._idea_buckets([], [hyp], edges)
    per_idea_reason = buckets["non_viable"][0]["reason"].lower()

    tally = report_gates._exclusion_tally([hyp], [], contradicted)
    blocked_reason = report_gates._empty_leaderboard_reason(1, tally).lower()

    assert "review" in per_idea_reason
    assert "contradicted" not in per_idea_reason
    assert "review" in blocked_reason
    assert "contradicted" not in blocked_reason


def test_duplicate_and_contradicted_idea_agrees_across_both_surfaces() -> None:
    hyp = _hypothesis("h2", "duplicate")
    edges = [_contradicting_edge("h2")]

    contradicted = report_gates.contradicted_hypothesis_ids("run1", None, edges)
    assert "h2" in contradicted

    buckets = report_content._idea_buckets([], [hyp], edges)
    per_idea_reason = buckets["non_viable"][0]["reason"].lower()

    tally = report_gates._exclusion_tally([hyp], [], contradicted)
    blocked_reason = report_gates._empty_leaderboard_reason(1, tally).lower()

    assert "higher-ranked" in per_idea_reason
    assert "contradicted" not in per_idea_reason
    assert "folded into a higher-ranked idea" in blocked_reason
    assert "contradicted" not in blocked_reason


def _seed_leased_finalize(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    client_id: str,
    *,
    monitor_halt: bool = False,
) -> tuple[Any, dict[str, str], str, Any]:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    headers = {"X-Client-ID": client_id}
    created = _create_run(
        owner,
        "Study final safety cancellation",
        headers=headers,
        tier="express",
    )
    assert created.status_code == 200, created.text
    run_id = str(created.json()["id"])
    runs.update_run_status(run_id, RunStatus.RUNNING, db_path=isolated_db)

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
    queued = enqueue_task(
        run_id,
        engine_tasks_support.FINALIZE_TASK,
        "final-safety-cancel-readiness",
        inputs={"checkpoint_seq": checkpoint_seq},
        db_path=isolated_db,
    )
    task = tasks.claim_task(
        "final-safety-cancel-worker", run_id=run_id, db_path=isolated_db
    )
    assert task is not None and task.id == queued.id
    assert task.status == "leased"
    _patch_restore_generator(monkeypatch, _Generator(state))

    _install_runtime(monkeypatch).drain_final_state = fake_final_drain
    return owner, headers, run_id, task


def _install_report(
    monkeypatch: pytest.MonkeyPatch, *, empty: bool = True
) -> None:
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
    persisted = runs.get_run(run_id, db_path=db_path)
    assert persisted is not None
    assert persisted.status == RunStatus.CANCELLED.value
    task = tasks.get_task(task_id, db_path=db_path)
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
    owner, headers, run_id, task = _seed_leased_finalize(
        isolated_db, monkeypatch, "readiness-cancel-owner"
    )
    _install_report(monkeypatch)

    async def allow_final_screen(*_: Any, **__: Any) -> Any:
        return SafetyDecision(stage="final", decision="allow")

    _install_runtime(monkeypatch).screen = allow_final_screen
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

    with pytest.raises(task_worker._LeaseLostError):
        await engine_tasks.execute_finalize(task, db_path=isolated_db)

    assert cancel_responses == [{"id": run_id, "status": "cancelled"}]
    events = _assert_cancelled_task(
        owner, headers, run_id, task.id, isolated_db
    )
    readiness = [
        item
        for item in records.list_safety_decisions(run_id, db_path=isolated_db)
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
    owner, headers, run_id, task = _seed_leased_finalize(
        isolated_db, monkeypatch, "readiness-block-owner"
    )
    _install_report(monkeypatch)

    async def allow_final_screen(*_: Any, **__: Any) -> Any:
        return SafetyDecision(stage="final", decision="allow")

    _install_runtime(monkeypatch).screen = allow_final_screen

    result = await engine_tasks.execute_finalize(task, db_path=isolated_db)

    persisted = runs.get_run(run_id, db_path=isolated_db)
    assert result["status"] == RunStatus.BLOCKED.value
    assert persisted is not None
    assert persisted.status == RunStatus.BLOCKED.value
    readiness = [
        item
        for item in records.list_safety_decisions(run_id, db_path=isolated_db)
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
    assert reports.get_latest_report(run_id, db_path=isolated_db) is None


@pytest.mark.asyncio
async def test_leased_finalize_redaction_audits_and_scrubs_report(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    _install_runtime(monkeypatch).screen = redact_final_screen

    result = await engine_tasks.execute_finalize(task, db_path=isolated_db)

    assert result["status"] == RunStatus.COMPLETED.value
    final_decisions = [
        item
        for item in records.list_safety_decisions(run_id, db_path=isolated_db)
        if item["stage"] == "final"
    ]
    assert len(final_decisions) == 1
    assert final_decisions[0]["decision"] == "redact"
    assert final_decisions[0]["matches"] == ["sensitive span"]

    saved = reports.get_latest_report(run_id, db_path=isolated_db)
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
        for item in records.list_safety_decisions(run_id, db_path=isolated_db)
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
    owner, headers, run_id, task = _seed_leased_finalize(
        isolated_db,
        monkeypatch,
        "monitor-halt-audit-owner",
        monitor_halt=True,
    )

    result = await engine_tasks.execute_finalize(task, db_path=isolated_db)

    persisted = runs.get_run(run_id, db_path=isolated_db)
    assert result["status"] == RunStatus.BLOCKED.value
    assert persisted is not None
    assert persisted.status == RunStatus.BLOCKED.value
    monitor = [
        item
        for item in records.list_safety_decisions(run_id, db_path=isolated_db)
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

    _install_runtime(monkeypatch).screen = cancel_then_decide

    with pytest.raises(task_worker._LeaseLostError):
        await engine_tasks.execute_finalize(task, db_path=isolated_db)

    assert cancel_responses == [{"id": run_id, "status": "cancelled"}]
    events = _assert_cancelled_task(
        owner, headers, run_id, task.id, isolated_db
    )
    final_decisions = [
        item
        for item in records.list_safety_decisions(run_id, db_path=isolated_db)
        if item["stage"] == "final"
    ]
    assert final_decisions == []
    assert not any(event["type"] == "safety.final" for event in events)
    assert not any(event["type"] == "report" for event in events)
    assert reports.get_latest_report(run_id, db_path=isolated_db) is None


@pytest.mark.asyncio
async def test_early_finalize_pause_skips_final_drain(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, run_id, task, _hypothesis_id = _seed_owned_finalize(
        isolated_db, monkeypatch
    )
    paused = owner.post(f"/api/runs/{run_id}/pause", headers=_OWNER)
    assert paused.status_code == 200, paused.text
    drain_calls: list[bool] = []

    async def unexpected_drain(*_: Any, **__: Any) -> Any:
        drain_calls.append(True)
        raise AssertionError("paused finalize called the final drain")

    _install_runtime(monkeypatch).drain_final_state = unexpected_drain
    result = await engine_tasks.execute_finalize(task, db_path=isolated_db)

    assert result["status"] == "paused"
    assert drain_calls == []
    checkpoint = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    assert checkpoint["stage"] == f"engine_task_paused:{task.id}"
    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == RunStatus.PAUSED.value


@pytest.mark.asyncio
async def test_cancel_during_final_drain_keeps_cancelled_state(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_drain = engine_tasks_node._drain_and_persist_final_state
    owner, run_id, _queued_task, hypothesis_id = _seed_owned_finalize(
        isolated_db, monkeypatch, claim=False
    )
    _install_report_stubs(hypothesis_id, monkeypatch)
    _install_runtime(monkeypatch).drain_final_state = real_drain
    cancel_responses: list[dict[str, Any]] = []

    async def cancel_inside_drain(*_: Any, **__: Any) -> Any:
        response = owner.post(f"/api/runs/{run_id}/cancel", headers=_OWNER)
        assert response.status_code == 200, response.text
        cancel_responses.append(response.json())
        return SimpleNamespace(
            safety_counts={},
            grounding_counts={},
            report_inputs={"citation_summary": {}},
        )

    monkeypatch.setattr(
        engine_tasks_node, "persist_final_state", cancel_inside_drain
    )
    task = tasks.claim_task(
        "cancel-during-drain-worker", run_id=run_id, db_path=isolated_db
    )
    assert task is not None
    with pytest.raises(task_worker._LeaseLostError):
        await engine_tasks.execute_finalize(task, db_path=isolated_db)

    run = runs.get_run(run_id, db_path=isolated_db)
    assert run is not None and run.status == RunStatus.CANCELLED.value
    assert cancel_responses == [{"id": run_id, "status": "cancelled"}]
    assert reports.get_latest_report(run_id, db_path=isolated_db) is None
    checkpoint = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None and checkpoint["stage"] == "fixture"
    events = owner.get(
        f"/api/runs/{run_id}/events?stream=false", headers=_OWNER
    ).json()["events"]
    assert not any(
        event["type"]
        in {
            "safety.hypothesis",
            "citation.grounding",
            "citation_audit",
            "report",
        }
        for event in events
    )


@pytest.mark.asyncio
async def test_resume_after_finalize_pause_read_does_not_write_stale_checkpoint(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, run_id, task, hypothesis_id = _seed_owned_finalize(
        isolated_db, monkeypatch
    )
    _install_report_stubs(hypothesis_id, monkeypatch)
    previous = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert previous is not None
    resume_state = {
        **previous["state"],
        "resume_successor": engine_tasks_support.FINALIZE_TASK,
    }
    seed_checkpoint(
        run_id,
        resume_state,
        stage=f"engine_task:{task.id}",
        schema_version=previous["schema_version"],
        last_event_seq=store_events.latest_event_seq(
            run_id, db_path=isolated_db
        ),
        db_path=isolated_db,
    )
    paused = owner.post(f"/api/runs/{run_id}/pause", headers=_OWNER)
    assert paused.status_code == 200, paused.text
    get_run = runs.get_run
    paused_reads = 0
    resume_responses: list[dict[str, Any]] = []

    def resume_after_pause_snapshot(
        requested: str,
        db_path: str | None = None,
        conn: Any | None = None,
    ) -> Any:
        nonlocal paused_reads
        run = get_run(requested, db_path=db_path, conn=conn)
        if requested == run_id and run is not None and run.status == "paused":
            paused_reads += 1
            if paused_reads == 2:
                response = owner.post(
                    f"/api/runs/{run_id}/resume", headers=_OWNER
                )
                assert response.status_code == 200, response.text
                resume_responses.append(response.json())
        return run

    monkeypatch.setattr(runs, "get_run", resume_after_pause_snapshot)
    result = await engine_tasks.execute_finalize(task, db_path=isolated_db)

    assert paused_reads >= 2
    assert resume_responses == [{"id": run_id, "status": "queued"}]
    assert result["status"] == RunStatus.COMPLETED.value
    completed = runs.get_run(run_id, db_path=isolated_db)
    assert completed is not None
    assert completed.status == RunStatus.COMPLETED.value
    checkpoint = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    assert checkpoint["stage"] == f"engine_task:{task.id}"
    assert reports.get_latest_report(run_id, db_path=isolated_db) is not None
    assert lifecycle.complete_task(
        task.id,
        str(task.lease_owner),
        result,
        db_path=isolated_db,
    )


@pytest.mark.asyncio
async def test_pause_during_final_drain_waits_for_explicit_resume(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_drain = engine_tasks_node._drain_and_persist_final_state
    owner, run_id, original_task, hypothesis_id = _seed_owned_finalize(
        isolated_db, monkeypatch, claim=False
    )
    _install_report_stubs(hypothesis_id, monkeypatch)
    _install_runtime(monkeypatch).drain_final_state = real_drain
    pause_responses: list[dict[str, Any]] = []

    async def pause_inside_drain(*_: Any, **kwargs: Any) -> Any:
        if not pause_responses:
            response = owner.post(f"/api/runs/{run_id}/pause", headers=_OWNER)
            assert response.status_code == 200, response.text
            pause_responses.append(response.json())
        hypotheses.add_hypothesis(
            NewHypothesis(
                run_id=run_id,
                hypothesis_id=hypothesis_id,
                title="IL-6 feedback",
                statement="IL-6 increases inflammation via STAT3 signaling.",
            ),
            db_path=isolated_db,
        )
        kwargs["final_state"]["metrics"] = {"llm_calls": 3}
        return SimpleNamespace(
            safety_counts={},
            grounding_counts={},
            report_inputs={"citation_summary": {}},
        )

    monkeypatch.setattr(
        engine_tasks_node, "persist_final_state", pause_inside_drain
    )

    assert await task_worker.run_once(
        "pause-during-drain-worker", run_id=run_id, db_path=isolated_db
    )
    paused = runs.get_run(run_id, db_path=isolated_db)
    assert pause_responses == [{"id": run_id, "status": "paused"}]
    assert paused is not None and paused.status == RunStatus.PAUSED.value
    assert hypotheses.get_hypothesis(hypothesis_id, db_path=isolated_db) is None
    assert reports.get_latest_report(run_id, db_path=isolated_db) is None
    pre_resume_events = owner.get(
        f"/api/runs/{run_id}/events?stream=false", headers=_OWNER
    ).json()["events"]
    assert not any(
        event["type"]
        in {
            "safety.hypothesis",
            "citation.grounding",
            "citation_audit",
            "report",
        }
        for event in pre_resume_events
    )
    assert (
        owner.get(f"/api/runs/{run_id}/report", headers=_OWNER).status_code
        == 404
    )
    checkpoint = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    assert checkpoint["stage"] == f"engine_task_paused:{original_task.id}"
    assert (
        checkpoint["state"]["resume_successor"]
        == engine_tasks_support.FINALIZE_TASK
    )
    assert retrieval.get_run_metrics(run_id, db_path=isolated_db) == {
        "llm_calls": 3
    }
    assert (
        tasks.claim_task(
            "before-finalize-resume", run_id=run_id, db_path=isolated_db
        )
        is None
    )

    from app import main

    recovered = main._reconcile_and_log_interrupted_runs()
    assert run_id not in recovered["failed"]
    assert run_id not in recovered["resumable"]
    assert run_id not in tasks.list_active_engine_task_run_ids(
        db_path=isolated_db
    )
    assert reports.get_latest_report(run_id, db_path=isolated_db) is None

    resumed = owner.post(f"/api/runs/{run_id}/resume", headers=_OWNER)
    assert resumed.status_code == 200, resumed.text
    assert await task_worker.run_once(
        "resumed-finalize-worker", run_id=run_id, db_path=isolated_db
    )
    completed = runs.get_run(run_id, db_path=isolated_db)
    assert completed is not None
    assert completed.status == RunStatus.COMPLETED.value
    assert reports.get_latest_report(run_id, db_path=isolated_db) is not None

    events = owner.get(
        f"/api/runs/{run_id}/events?stream=false", headers=_OWNER
    ).json()["events"]
    pause_event = next(
        event
        for event in events
        if event["type"] == "lifecycle"
        and event["payload"].get("event") == "pause_requested"
    )
    resume_event = next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "resuming"
    )
    report_event = next(event for event in events if event["type"] == "report")
    completion_event = next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "completed"
    )
    assert pause_event["seq"] < resume_event["seq"]
    stages = [
        event
        for event in events
        if event["type"]
        in {"safety.hypothesis", "citation.grounding", "citation_audit"}
    ]
    assert [event["type"] for event in stages] == [
        "safety.hypothesis",
        "citation.grounding",
        "citation_audit",
    ]
    assert resume_event["seq"] < stages[0]["seq"]
    assert stages[-1]["seq"] < report_event["seq"] < completion_event["seq"]


@pytest.mark.asyncio
async def test_cancel_after_drain_commit_orders_stages_before_cancel(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_drain = engine_tasks_node._drain_and_persist_final_state
    owner, run_id, _queued_task, hypothesis_id = _seed_owned_finalize(
        isolated_db, monkeypatch, claim=False
    )
    _install_report_stubs(hypothesis_id, monkeypatch)
    _install_runtime(monkeypatch).drain_final_state = real_drain

    async def fake_persist_final_state(*_: Any, **kwargs: Any) -> Any:
        hypotheses.add_hypothesis(
            NewHypothesis(
                run_id=run_id,
                hypothesis_id=hypothesis_id,
                title="IL-6 feedback",
                statement="IL-6 increases inflammation via STAT3 signaling.",
            ),
            db_path=isolated_db,
        )
        kwargs["final_state"]["metrics"] = {"llm_calls": 5}
        return SimpleNamespace(
            safety_counts={},
            grounding_counts={},
            report_inputs={"citation_summary": {}},
        )

    monkeypatch.setattr(
        engine_tasks_node, "persist_final_state", fake_persist_final_state
    )
    task = tasks.claim_task(
        "cancel-after-drain-worker", run_id=run_id, db_path=isolated_db
    )
    assert task is not None
    commit_drain = engine_tasks_node._commit_finalize_drain
    cancel_responses: list[dict[str, Any]] = []

    def commit_then_cancel(*args: Any, **kwargs: Any) -> Any:
        outcome = commit_drain(*args, **kwargs)
        if len(args) > 2 and args[2] is not None:
            response = owner.post(f"/api/runs/{run_id}/cancel", headers=_OWNER)
            assert response.status_code == 200, response.text
            cancel_responses.append(response.json())
        return outcome

    monkeypatch.setattr(
        engine_tasks_node, "_commit_finalize_drain", commit_then_cancel
    )
    with pytest.raises(task_worker._LeaseLostError):
        await engine_tasks.execute_finalize(task, db_path=isolated_db)

    persisted = runs.get_run(run_id, db_path=isolated_db)
    assert persisted is not None
    assert persisted.status == RunStatus.CANCELLED.value
    assert cancel_responses == [{"id": run_id, "status": "cancelled"}]
    assert reports.get_latest_report(run_id, db_path=isolated_db) is None
    events = owner.get(
        f"/api/runs/{run_id}/events?stream=false", headers=_OWNER
    ).json()["events"]
    expected_stages = [
        "safety.hypothesis",
        "citation.grounding",
        "citation_audit",
    ]
    stage_events = [
        event for event in events if event["type"] in expected_stages
    ]
    cancelled = next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "cancelled"
    )
    assert [event["type"] for event in stage_events] == expected_stages
    assert all(event["seq"] < cancelled["seq"] for event in stage_events)
    assert not any(
        event["type"] == "report"
        or event["payload"].get("status") == "completed"
        for event in events
    )


def _run_with_report(isolated_db: str) -> str:
    run = seed_run(
        "Study a causal pathway",
        provider="mock",
        client_id="owner-a",
        db_path=isolated_db,
    )
    reports.save_report(
        run.id,
        {"research_goal": run.research_goal, "leaderboard": []},
        "# Goal Report",
        db_path=isolated_db,
    )
    return run.id


def test_share_link_is_unique_hashed_and_revocable(isolated_db: str) -> None:
    run_id = _run_with_report(isolated_db)
    with TestClient(app) as client:
        denied = client.post(
            f"/api/runs/{run_id}/shares",
            headers={"X-Client-ID": "other"},
        )
        assert denied.status_code == 404

        created = client.post(
            f"/api/runs/{run_id}/shares",
            headers={"X-Client-ID": "owner-a"},
        )
        assert created.status_code == 200
        share = created.json()
        assert len(share["token"]) >= 32

        with db.connect(isolated_db) as conn:
            stored = conn.execute(
                "SELECT token_hash FROM report_shares WHERE id=?",
                (share["id"],),
            ).fetchone()[0]
        assert stored != share["token"]

        public = client.get(f"/api/shared/{share['token']}")
        assert public.status_code == 200
        assert public.json()["report"]["payload"]["research_goal"] == (
            "Study a causal pathway"
        )

        revoked = client.delete(
            f"/api/runs/{run_id}/shares/{share['id']}",
            headers={"X-Client-ID": "owner-a"},
        )
        assert revoked.status_code == 204
        assert client.get(f"/api/shared/{share['token']}").status_code == 404


def _run_with_blocked_and_released_content(
    isolated_db: str,
) -> tuple[str, str, str]:
    run = seed_run(
        "Map a signaling pathway",
        config={"private_setting": "config-secret-value"},
        client_id="owner-b",
        db_path=isolated_db,
    )
    run_id = run.id

    released_id = hypotheses.add_hypothesis(
        NewHypothesis(
            run_id=run_id,
            title="Released feedback idea",
            statement="Modulating the feedback loop improves throughput.",
        ),
        db_path=isolated_db,
    )
    hypotheses.update_hypothesis_state(
        released_id,
        HypothesisStateChanges(safety_status="allow"),
        db_path=isolated_db,
    )

    blocked_id = hypotheses.add_hypothesis(
        NewHypothesis(
            run_id=run_id,
            title="Safety blocked idea",
            statement="A blocked proposal kept out by the safety screen.",
        ),
        db_path=isolated_db,
    )
    hypotheses.update_hypothesis_state(
        blocked_id,
        HypothesisStateChanges(safety_status="prohibited"),
        db_path=isolated_db,
    )

    rejected_id = hypotheses.add_hypothesis(
        NewHypothesis(
            run_id=run_id,
            title="Review rejected idea",
            statement="A proposal set aside during review.",
        ),
        db_path=isolated_db,
    )
    hypotheses.update_hypothesis_state(
        rejected_id,
        HypothesisStateChanges(status="rejected", safety_status="allow"),
        db_path=isolated_db,
    )

    duplicate_id = hypotheses.add_hypothesis(
        NewHypothesis(
            run_id=run_id,
            title="Deduplicated idea",
            statement="A proposal folded into a higher-ranked idea.",
        ),
        db_path=isolated_db,
    )
    hypotheses.update_hypothesis_state(
        duplicate_id,
        HypothesisStateChanges(status="duplicate", safety_status="allow"),
        db_path=isolated_db,
    )

    contradicted_id = hypotheses.add_hypothesis(
        NewHypothesis(
            run_id=run_id,
            title="Contradicted idea",
            statement="A proposal whose claims the evidence contradicts.",
        ),
        db_path=isolated_db,
    )
    hypotheses.update_hypothesis_state(
        contradicted_id,
        HypothesisStateChanges(safety_status="allow"),
        db_path=isolated_db,
    )

    cited_id = records.add_evidence(
        NewEvidence(
            run_id=run_id,
            title="A public pathway paper",
            source="pubmed",
            abstract="Published abstract text.",
        ),
        db_path=isolated_db,
    )
    records.add_evidence(
        NewEvidence(
            run_id=run_id,
            title="Private lab memo",
            source="attachment",
            abstract="private-document-secret-text",
        ),
        db_path=isolated_db,
    )

    records.add_claim_evidence(
        NewClaimEvidence(
            run_id=run_id,
            hypothesis_id=released_id,
            claim="The feedback loop is causal",
            label="supports",
            supporting=[{"evidence_id": cited_id, "quote": "feedback loop"}],
            contradicting=[],
            assessor="deterministic",
        ),
        db_path=isolated_db,
    )
    records.add_claim_evidence(
        NewClaimEvidence(
            run_id=run_id,
            hypothesis_id=contradicted_id,
            claim="The loop runs backwards",
            label="contradicts",
            supporting=[],
            contradicting=[{"evidence_id": cited_id, "quote": "no such thing"}],
            assessor="deterministic",
        ),
        db_path=isolated_db,
    )

    reports.save_report(
        run_id,
        {"research_goal": run.research_goal},
        "# Goal Report",
        db_path=isolated_db,
    )
    return run_id, released_id, cited_id


def test_shared_payload_is_filtered_to_release_artifact(
    isolated_db: str,
) -> None:
    run_id, released_id, cited_id = _run_with_blocked_and_released_content(
        isolated_db
    )
    with TestClient(app) as client:
        created = client.post(
            f"/api/runs/{run_id}/shares",
            headers={"X-Client-ID": "owner-b"},
        )
        assert created.status_code == 200
        public = client.get(f"/api/shared/{created.json()['token']}")
        assert public.status_code == 200
        payload = public.json()

    assert {h["id"] for h in payload["hypotheses"]} == {released_id}
    assert [e["id"] for e in payload["evidence"]] == [cited_id]

    serialized = json.dumps(payload)
    for secret in (
        "Safety blocked idea",
        "A blocked proposal kept out by the safety screen.",
        "Review rejected idea",
        "A proposal set aside during review.",
        "Deduplicated idea",
        "A proposal folded into a higher-ranked idea.",
        "Contradicted idea",
        "A proposal whose claims the evidence contradicts.",
        "Private lab memo",
        "private-document-secret-text",
        "config-secret-value",
    ):
        assert secret not in serialized

    assert payload["run"] == {
        "title": None,
        "research_goal": "Map a signaling pathway",
        "run_mode": "standard",
    }

    shared = payload["hypotheses"][0]
    assert shared["title"] == "Released feedback idea"
    assert shared["statement"] == (
        "Modulating the feedback loop improves throughput."
    )
    assert "abstract" not in payload["evidence"][0]
    assert payload["evidence"][0]["title"] == "A public pathway paper"
    assert payload["evidence"][0]["retracted"] is False
