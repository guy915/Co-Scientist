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
from app.safety import SafetyDecision
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


def _status_event(events: list[dict[str, Any]], status: str) -> dict[str, Any]:
    return next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == status
    )


def _statuses(events: list[dict[str, Any]]) -> list[Any]:
    return [
        event["payload"].get("status")
        for event in events
        if event["type"] == "status"
    ]


def _decisions(run_id: str, stage: str, db_path: str) -> list[dict[str, Any]]:
    return [
        item
        for item in records.list_safety_decisions(run_id, db_path=db_path)
        if item["stage"] == stage
    ]


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


@pytest.mark.parametrize(
    ("status", "per_idea", "blocked"),
    [
        ("rejected", "review", "review"),
        ("duplicate", "higher-ranked", "folded into a higher-ranked idea"),
    ],
)
def test_a_contradicted_idea_is_withheld_for_its_status_on_both_surfaces(
    status: str, per_idea: str, blocked: str
) -> None:
    # Status exclusions precede contradiction exclusions across shared report
    # surfaces.
    hyp = _hypothesis("h1", status)
    edges = [_contradicting_edge("h1")]

    contradicted = report_gates.contradicted_hypothesis_ids("run1", None, edges)
    assert "h1" in contradicted
    buckets = report_content._idea_buckets([], [hyp], edges)
    per_idea_reason = buckets["non_viable"][0]["reason"].lower()
    tally = report_gates._exclusion_tally([hyp], [], contradicted)
    blocked_reason = report_gates._empty_leaderboard_reason(1, tally).lower()

    assert per_idea in per_idea_reason
    assert blocked in blocked_reason
    assert "contradicted" not in per_idea_reason
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
    events = _owner_events(owner, headers, run_id)
    assert _statuses(events) == ["cancelled"]
    return events


def _owner_events(
    owner: Any, headers: dict[str, str], run_id: str
) -> list[dict[str, Any]]:
    response = owner.get(
        f"/api/runs/{run_id}/events?stream=false", headers=headers
    )
    assert response.status_code == 200, response.text
    return cast(list[dict[str, Any]], response.json()["events"])


@pytest.mark.parametrize(
    ("gate", "monitor_halt", "stage", "event_type"),
    [
        (
            (report_finalize, "_block_for_empty_leaderboard"),
            False,
            "scientific_readiness",
            None,
        ),
        (
            (engine_tasks_node, "apply_safety_gate"),
            True,
            "research_direction",
            "safety.research_direction",
        ),
    ],
    ids=["readiness-block", "monitor-halt"],
)
@pytest.mark.asyncio
async def test_a_cancel_before_a_blocking_gate_leaves_no_gate_audit(
    gate: tuple[Any, str],
    monitor_halt: bool,
    stage: str,
    event_type: str | None,
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, headers, run_id, task = _seed_leased_finalize(
        isolated_db,
        monkeypatch,
        f"cancel-before-{stage}",
        monitor_halt=monitor_halt,
    )
    _install_report(monkeypatch)

    async def allow_final_screen(*_: Any, **__: Any) -> Any:
        return SafetyDecision(stage="final", decision="allow")

    _install_runtime(monkeypatch).screen = allow_final_screen
    module, name = gate
    real_gate = getattr(module, name)
    cancel_responses: list[dict[str, Any]] = []

    async def cancel_first(*args: Any, **kwargs: Any) -> Any:
        response = owner.post(f"/api/runs/{run_id}/cancel", headers=headers)
        assert response.status_code == 200, response.text
        cancel_responses.append(response.json())
        async for event in real_gate(*args, **kwargs):
            yield event

    monkeypatch.setattr(module, name, cancel_first)

    with pytest.raises(task_worker._LeaseLostError):
        await engine_tasks.execute_finalize(task, db_path=isolated_db)

    assert cancel_responses == [{"id": run_id, "status": "cancelled"}]
    events = _assert_cancelled_task(
        owner, headers, run_id, task.id, isolated_db
    )
    assert _decisions(run_id, stage, isolated_db) == []
    assert not any(event["type"] == event_type for event in events)


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
    readiness = _decisions(run_id, "scientific_readiness", isolated_db)
    assert len(readiness) == 1
    assert readiness[0]["decision"] == "block"

    events = _owner_events(owner, headers, run_id)
    final_event = next(
        event for event in events if event["type"] == "safety.final"
    )
    blocked_event = _status_event(events, "blocked")
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
    final_decisions = _decisions(run_id, "final", isolated_db)
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
    completed_event = _status_event(events, "completed")
    assert final_event["seq"] < report_event["seq"] < completed_event["seq"]
    assert "sensitive span" not in repr(report_event["payload"]).lower()


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
    monitor = _decisions(run_id, "research_direction", isolated_db)
    assert len(monitor) == 1
    assert monitor[0]["decision"] == "block"
    assert monitor[0]["matches"] == ["engineer smallpox for greater transmiss"]

    events = _owner_events(owner, headers, run_id)
    halt_event = next(
        event
        for event in events
        if event["type"] == "safety.research_direction"
    )
    blocked_event = _status_event(events, "blocked")
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
    final_decisions = _decisions(run_id, "final", isolated_db)
    assert final_decisions == []
    assert not any(event["type"] == "safety.final" for event in events)
    assert not any(event["type"] == "report" for event in events)
    assert reports.get_latest_report(run_id, db_path=isolated_db) is None


_DRAIN_STAGES = ("safety.hypothesis", "citation.grounding", "citation_audit")


def _install_final_drain(
    monkeypatch: pytest.MonkeyPatch,
    run_id: str,
    hypothesis_id: str,
    isolated_db: str,
    *,
    llm_calls: int,
    during: Any = None,
) -> None:
    _install_runtime(
        monkeypatch
    ).drain_final_state = engine_tasks_node._drain_and_persist_final_state

    async def persist_final_state(*_: Any, **kwargs: Any) -> Any:
        if during is not None:
            during()
        hypotheses.add_hypothesis(
            NewHypothesis(
                run_id=run_id,
                hypothesis_id=hypothesis_id,
                title="IL-6 feedback",
                statement="IL-6 increases inflammation via STAT3 signaling.",
            ),
            db_path=isolated_db,
        )
        kwargs["final_state"]["metrics"] = {"llm_calls": llm_calls}
        return SimpleNamespace(
            safety_counts={},
            grounding_counts={},
            report_inputs={"citation_summary": {}},
        )

    monkeypatch.setattr(
        engine_tasks_node, "persist_final_state", persist_final_state
    )


@pytest.mark.asyncio
async def test_cancel_during_final_drain_keeps_cancelled_state(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, run_id, _queued_task, hypothesis_id = _seed_owned_finalize(
        isolated_db, monkeypatch, claim=False
    )
    _install_report_stubs(hypothesis_id, monkeypatch)
    cancel_responses: list[dict[str, Any]] = []

    def cancel() -> None:
        response = owner.post(f"/api/runs/{run_id}/cancel", headers=_OWNER)
        assert response.status_code == 200, response.text
        cancel_responses.append(response.json())

    _install_final_drain(
        monkeypatch,
        run_id,
        hypothesis_id,
        isolated_db,
        llm_calls=1,
        during=cancel,
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
    events = _owner_events(owner, _OWNER, run_id)
    assert not any(
        event["type"] in {*_DRAIN_STAGES, "report"} for event in events
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
    owner, run_id, original_task, hypothesis_id = _seed_owned_finalize(
        isolated_db, monkeypatch, claim=False
    )
    _install_report_stubs(hypothesis_id, monkeypatch)
    pause_responses: list[dict[str, Any]] = []

    def pause_once() -> None:
        if not pause_responses:
            response = owner.post(f"/api/runs/{run_id}/pause", headers=_OWNER)
            assert response.status_code == 200, response.text
            pause_responses.append(response.json())

    _install_final_drain(
        monkeypatch,
        run_id,
        hypothesis_id,
        isolated_db,
        llm_calls=3,
        during=pause_once,
    )

    assert await task_worker.run_once(
        "pause-during-drain-worker", run_id=run_id, db_path=isolated_db
    )
    paused = runs.get_run(run_id, db_path=isolated_db)
    assert pause_responses == [{"id": run_id, "status": "paused"}]
    assert paused is not None and paused.status == RunStatus.PAUSED.value
    assert hypotheses.get_hypothesis(hypothesis_id, db_path=isolated_db) is None
    assert reports.get_latest_report(run_id, db_path=isolated_db) is None
    pre_resume_events = _owner_events(owner, _OWNER, run_id)
    assert not any(
        event["type"] in {*_DRAIN_STAGES, "report"}
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

    events = _owner_events(owner, _OWNER, run_id)
    pause_event = next(
        event
        for event in events
        if event["type"] == "lifecycle"
        and event["payload"].get("event") == "pause_requested"
    )
    resume_event = _status_event(events, "resuming")
    report_event = next(event for event in events if event["type"] == "report")
    completion_event = _status_event(events, "completed")
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
    owner, run_id, _queued_task, hypothesis_id = _seed_owned_finalize(
        isolated_db, monkeypatch, claim=False
    )
    _install_report_stubs(hypothesis_id, monkeypatch)
    _install_final_drain(
        monkeypatch, run_id, hypothesis_id, isolated_db, llm_calls=5
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
    events = _owner_events(owner, _OWNER, run_id)
    expected_stages = list(_DRAIN_STAGES)
    stage_events = [
        event for event in events if event["type"] in expected_stages
    ]
    cancelled = _status_event(events, "cancelled")
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

    def add_idea(title: str, statement: str, **state: str) -> str:
        hyp_id = hypotheses.add_hypothesis(
            NewHypothesis(run_id=run_id, title=title, statement=statement),
            db_path=isolated_db,
        )
        hypotheses.update_hypothesis_state(
            hyp_id,
            HypothesisStateChanges(**{"safety_status": "allow", **state}),
            db_path=isolated_db,
        )
        return hyp_id

    released_id = add_idea(
        "Released feedback idea",
        "Modulating the feedback loop improves throughput.",
    )
    add_idea(
        "Safety blocked idea",
        "A blocked proposal kept out by the safety screen.",
        safety_status="prohibited",
    )
    add_idea(
        "Review rejected idea",
        "A proposal set aside during review.",
        status="rejected",
    )
    add_idea(
        "Deduplicated idea",
        "A proposal folded into a higher-ranked idea.",
        status="duplicate",
    )
    contradicted_id = add_idea(
        "Contradicted idea",
        "A proposal whose claims the evidence contradicts.",
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
