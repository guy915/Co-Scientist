from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import task_worker
from app.config import settings
from app.engine_tasks import support as engine_tasks_support
from app.report import build as report_build
from app.report import finalize as report_finalize
from app.runs import lifecycle as runs_lifecycle
from app.safety import SafetyDecision
from app.store import checkpoints, hypotheses, reports, runs
from app.store import events as store_events
from app.store import messages as store_messages
from app.store import records as store
from app.store import runs_views as views
from app.store import tasks as store_tasks
from app.store import tasks_lifecycle as lifecycle
from app.store.hypotheses import NewHypothesis
from app.store.models import MessageRow
from app.store.models import RunStatus as StoreRunStatus
from app.store.records import NewEvidence, NewReview
from tests._client import create_run as _create_run
from tests._client import fake_litellm as _fake_litellm
from tests._client import make_client
from tests._client import make_client as _client
from tests._engine_tasks_helpers import (
    _Generator,
    _install_runtime,
    _patch_restore_generator,
    _seed_checkpoint,
    _task_state,
    fake_final_drain,
)
from tests._llm_fake_backend import install_completion_backend
from tests._process_mode_helpers import FakeProcessMode
from tests._store_helpers import (
    enqueue_task,
    event_seqs,
    seed_checkpoint,
    seed_run,
)


def _new_run(client: Any, headers: dict[str, str] | None = None) -> str:
    res = _create_run(client, "Scientist-in-the-loop goal", headers=headers)
    return str(res.json()["id"])


def test_scientist_hypothesis_admitted_with_authorship(
    isolated_db: str,
) -> None:
    # Attribute contributions to caller identity, not a spoofable author field
    # in the request body.
    headers = {"X-Client-ID": "dr-smith"}
    client = _client()
    run_id = _new_run(client, headers)

    res = client.post(
        f"/api/runs/{run_id}/hypotheses",
        headers=headers,
        json={
            "statement": "Inhibiting kinase X reduces AML growth by apoptosis.",
            "author": "dr-smith",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["admitted"] is True
    assert body["author"] == "dr-smith"

    hyps = client.get(f"/api/runs/{run_id}/hypotheses", headers=headers).json()[
        "hypotheses"
    ]
    manual = next(h for h in hyps if h["id"] == body["id"])
    assert manual["created_by_agent"] == "scientist_manual"
    assert manual["author"] == "dr-smith"
    assert manual["safety_status"] == "allow"
    pending = client.get(
        f"/api/runs/{run_id}/messages", headers=headers
    ).json()["messages"]
    assert pending[-1]["kind"] == "steering"
    assert pending[-1]["meta"]["kind"] == "manual_hypothesis"


def test_scientist_unsafe_hypothesis_is_blocked_not_persisted(
    isolated_db: str,
) -> None:
    client = _client()
    run_id = _new_run(client)

    res = client.post(
        f"/api/runs/{run_id}/hypotheses",
        json={
            "statement": (
                "Weaponize the pathogen to enhance transmissibility in humans."
            ),
            "author": "bad-actor",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["admitted"] is False
    assert body["safety"]["outcome"] == "prohibited"

    hyps = client.get(f"/api/runs/{run_id}/hypotheses").json()["hypotheses"]
    assert all(h["created_by_agent"] != "scientist_manual" for h in hyps)


def test_scientist_review_lands_in_reviews_table(isolated_db: str) -> None:
    headers = {"X-Client-ID": "dr-lee"}
    client = _client()
    run_id = _new_run(client, headers)
    hyp = client.post(
        f"/api/runs/{run_id}/hypotheses",
        headers=headers,
        json={"statement": "A safe, testable hypothesis.", "author": "dr-lee"},
    ).json()

    res = client.post(
        f"/api/runs/{run_id}/reviews",
        headers=headers,
        json={
            "hypothesis_id": hyp["id"],
            "author": "dr-lee",
            "verdict": "support",
            "critique": "Well grounded; suggest a control arm.",
        },
    )
    assert res.status_code == 200
    assert res.json()["recorded"] is True

    reviews = client.get(f"/api/runs/{run_id}/reviews", headers=headers).json()[
        "reviews"
    ]
    scientist = [r for r in reviews if r["reviewer_agent"] == "scientist"]
    assert len(scientist) == 1
    assert "dr-lee" in scientist[0]["summary"]
    messages = client.get(
        f"/api/runs/{run_id}/messages", headers=headers
    ).json()["messages"]
    assert messages[-1]["meta"]["kind"] == "human_review"
    assert messages[-1]["applied"] is False


@pytest.mark.parametrize(
    ("verdict", "target", "status"),
    [
        ("maybe", "own", 422),
        ("support", "missing", 404),
        ("support", "other", 404),
    ],
)
def test_scientist_review_rejects_bad_verdict_and_foreign_hypotheses(
    isolated_db: str, verdict: str, target: str, status: int
) -> None:
    client = _client()
    run_a = _new_run(client)
    run_b = _new_run(client)
    statement = {"statement": "A safe, testable hypothesis.", "author": "x"}
    hosts = {"own": run_a, "other": run_b}
    hyp = "does-not-exist"
    if target in hosts:
        posted = client.post(
            f"/api/runs/{hosts[target]}/hypotheses", json=statement
        )
        hyp = posted.json()["id"]

    res = client.post(
        f"/api/runs/{run_a}/reviews",
        json={
            "hypothesis_id": hyp,
            "author": "dr-lee",
            "verdict": verdict,
            "critique": "",
        },
    )

    assert res.status_code == status
    assert client.get(f"/api/runs/{run_a}/reviews").json()["reviews"] == []


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"title": "Doc", "text": "Some text.", "consent": False}, 422),
        ({"title": "Big", "text": "x" * 200_001, "consent": True}, 422),
    ],
)
def test_attachment_needs_consent_and_a_bounded_size(
    isolated_db: str, body: dict[str, Any], status: int
) -> None:
    client = _client()
    run_id = _new_run(client)

    res = client.post(f"/api/runs/{run_id}/attachments", json=body)

    assert res.status_code == status


@pytest.mark.parametrize(
    ("paused", "held", "resolved", "awaiting"),
    [
        (True, True, False, 1),
        (True, False, False, 0),
        (False, True, False, 0),
        (True, True, True, 0),
    ],
)
def test_only_a_paused_run_with_an_unresolved_review_awaits_a_decision(
    isolated_db: str, paused: bool, held: bool, resolved: bool, awaiting: int
) -> None:
    client = _client()
    headers = {"X-Client-ID": "awaiting"}
    if held:
        run_id, decision_id = _run_with_held_decision(client, headers)
    else:
        run_id = _create_run(
            client, "A mundane pathway", headers=headers
        ).json()["id"]
    if resolved:
        client.post(
            f"/api/runs/{run_id}/safety/{decision_id}/adjudicate",
            headers=headers,
            json={"resolution": "approved"},
        )
    if paused:
        runs.update_run_status(run_id, StoreRunStatus.PAUSED)

    detail = client.get(f"/api/runs/{run_id}", headers=headers).json()

    assert detail["awaiting_decision_count"] == awaiting


def test_resume_and_pause_need_a_checkpoint_or_an_active_run(
    isolated_db: str,
) -> None:
    client = _client()
    run_id = _create_run(client, "No checkpoint yet").json()["id"]

    assert client.post(f"/api/runs/{run_id}/resume").status_code == 409
    assert client.post(f"/api/runs/{run_id}/pause").status_code == 404


def test_offline_announcement_is_stored_streamed_and_marked_fallback() -> None:
    rid = _started_run_id()

    body = _announce(rid).text

    rows = _start_rows(rid)
    assert [row.sender for row in rows] == ["user", "system"]
    assert rows[0].content == "Start research"
    assert rows[1].content.strip()
    assert rows[1].meta == {"fallback": True}
    assert body.index('"type": "chunk"') < body.index('"type": "done"')
    assert '"fallback": true' in body
    assert '"type": "error"' not in body


def test_attachment_indexed_and_searchable(isolated_db: str) -> None:
    client = _client()
    run_id = _new_run(client)

    res = client.post(
        f"/api/runs/{run_id}/attachments",
        json={
            "title": "Persister cell review",
            "text": (
                "Drug-tolerant persister cells survive EGFR inhibition via "
                "a reversible transcriptional program and mitochondrial "
                "priming."
            ),
            "consent": True,
        },
    )
    assert res.status_code == 200
    assert res.json()["indexed"] is True

    hits = client.get(
        f"/api/runs/{run_id}/attachments/search",
        params={"q": "persister mitochondrial priming"},
    ).json()["results"]
    assert hits
    assert hits[0]["title"] == "Persister cell review"


def test_pasted_and_uploaded_attachments_emit_same_audit_event(
    isolated_db: str,
) -> None:
    client = _client()
    run_id = _new_run(client)

    pasted = client.post(
        f"/api/runs/{run_id}/attachments",
        json={
            "title": "Pasted note",
            "text": "Persister cells tolerate EGFR inhibition reversibly.",
            "consent": True,
        },
    ).json()
    uploaded = client.post(
        f"/api/runs/{run_id}/attachments/upload",
        files={
            "file": ("assay.md", b"Kinase X reduced growth.", "text/markdown")
        },
        data={"consent": "true"},
    ).json()

    events = client.get(f"/api/runs/{run_id}/events?stream=false").json()
    attachment_events = [
        e for e in events["events"] if e["type"] == "scientist.attachment"
    ]
    assert [e["payload"]["evidence_id"] for e in attachment_events] == [
        pasted["id"],
        uploaded["id"],
    ]
    assert attachment_events[0]["payload"]["title"] == "Pasted note"
    assert attachment_events[1]["payload"]["title"] == "assay.md"


def _seed_agent_artifacts(run_id: str) -> str:
    agent_id = hypotheses.add_hypothesis(
        NewHypothesis(
            run_id=run_id,
            title="Agent idea",
            statement="An agent-generated hypothesis.",
            created_by_agent="generation",
        )
    )
    store.add_review(
        NewReview(
            run_id=run_id,
            hypothesis_id=agent_id,
            reviewer_agent="reflection",
            summary="agent review",
            critique="agent critique",
        )
    )
    store.add_evidence(
        NewEvidence(
            run_id=run_id,
            title="Retrieved paper",
            source="pubmed",
            abstract="x",
        )
    )
    return agent_id


def _seed_scientist_artifacts(run_id: str) -> str:
    manual_id = hypotheses.add_hypothesis(
        NewHypothesis(
            run_id=run_id,
            title="Human idea",
            statement="A scientist-authored hypothesis.",
            created_by_agent="scientist_manual",
            author="dr-who",
        )
    )
    store.add_review(
        NewReview(
            run_id=run_id,
            hypothesis_id=manual_id,
            reviewer_agent="scientist",
            summary="human review",
            critique="looks promising",
        )
    )
    store.add_evidence(
        NewEvidence(
            run_id=run_id,
            title="Attached doc",
            source="attachment",
            abstract="notes",
        )
    )
    return manual_id


def test_resume_preserves_scientist_contributions(isolated_db: str) -> None:
    run = seed_run("Human input survives resume", profile="express")
    _seed_agent_artifacts(run.id)
    manual_id = _seed_scientist_artifacts(run.id)

    views.clear_run_derived_data(run.id)

    hyps = hypotheses.list_hypotheses(run.id)
    assert [h["id"] for h in hyps] == [manual_id]
    reviews = store.list_reviews(run.id)
    assert len(reviews) == 1 and reviews[0]["reviewer_agent"] == "scientist"
    evidence = store.list_evidence(run.id)
    assert [e["source"] for e in evidence] == ["attachment"]


def test_resuming_a_pre_engine_checkpoint_restarts_from_a_fresh_bootstrap(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    run_id = _new_run(client)
    _seed_agent_artifacts(run_id)
    manual_id = _seed_scientist_artifacts(run_id)
    seed_checkpoint(
        run_id,
        {"provider": "mock", "legacy": True},
        stage="iteration_1",
        last_event_seq=store_events.latest_event_seq(run_id),
    )
    runs.update_run_status(run_id, StoreRunStatus.PAUSED)

    resumed = client.post(f"/api/runs/{run_id}/resume")

    assert resumed.status_code == 200, resumed.text
    assert [h["id"] for h in hypotheses.list_hypotheses(run_id)] == [manual_id]
    assert checkpoints.get_latest_checkpoint(run_id) is None
    assert event_seqs(run_id, "lifecycle", event="legacy_resume_cleanup")
    [task] = store_tasks.list_tasks(run_id)
    assert (task.task_type, task.status) == ("engine.bootstrap", "queued")


def test_resume_reassigns_event_seqs_above_last_checkpoint(
    isolated_db: str,
) -> None:
    # Clients retain after=N cursors; resumed event sequences must exceed
    # checkpoint high-water marks.
    run = seed_run("Seq continuity", profile="express")
    for i in range(5):
        store_events.append_event(run.id, "log", {"i": i})
    high_water = store_events.latest_event_seq(run.id)
    assert high_water == 5

    seed_checkpoint(run.id, {}, stage="pause", last_event_seq=high_water)
    views.clear_run_derived_data(run.id)
    assert store_events.list_events(run.id) == []

    seq = store_events.append_event(run.id, "status", {"status": "resuming"})
    assert seq == high_water + 1
    assert (
        store_events.list_events(run.id, after_seq=high_water)[0]["seq"] == seq
    )


_WORKER = "double-resume-test"


async def _advance(run_id: str, count: int, db_path: str) -> None:
    for _ in range(count):
        worked = await task_worker.run_once(
            _WORKER, run_id=run_id, db_path=db_path
        )
        assert worked, "run finished (or stalled) earlier than the test expects"


async def _advance_until_pool_nonempty(
    run_id: str, db_path: str, *, cap: int = 30
) -> set[str]:
    # Wait for a populated checkpoint rather than a task count tied to
    # generation fan-out topology.
    for _ in range(cap):
        worked = await task_worker.run_once(
            _WORKER, run_id=run_id, db_path=db_path
        )
        assert worked, "run finished before its pool ever grew"
        pool = _checkpoint_hypothesis_ids(run_id, db_path)
        if pool:
            return pool
    raise AssertionError(f"pool still empty after {cap} tasks")


def _pause_and_resume(client: Any, run_id: str) -> None:
    paused = client.post(f"/api/runs/{run_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    resumed = client.post(f"/api/runs/{run_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "queued"


def _checkpoint_hypothesis_ids(run_id: str, db_path: str) -> set[str]:
    checkpoint = checkpoints.get_latest_checkpoint(run_id, db_path=db_path)
    assert checkpoint is not None
    payload = checkpoint["state"]["state"]
    return {str(h["id"]) for h in payload.get("hypotheses") or []}


@pytest.mark.asyncio
async def test_two_resume_cycles_still_complete_with_pool_intact(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Disable the embedded worker so two interruption boundaries cannot race
    # detached execution.
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    created = _create_run(client, "Double resume coverage", tier="express")
    assert created.status_code == 200
    run_id = created.json()["id"]
    started = client.post(f"/api/runs/{run_id}/start", json={})
    assert started.status_code == 200

    await _advance(run_id, 1, isolated_db)
    _pause_and_resume(client, run_id)

    pool_before = await _advance_until_pool_nonempty(run_id, isolated_db)
    _pause_and_resume(client, run_id)

    await task_worker.run_run_until_idle(run_id, _WORKER, db_path=isolated_db)

    final_run = runs.get_run(run_id, db_path=isolated_db)
    assert final_run is not None
    assert final_run.status == "completed", final_run.error
    report = reports.get_latest_report(run_id, db_path=isolated_db)
    assert report is not None
    final_ids = {
        str(row["id"])
        for row in hypotheses.list_hypotheses(run_id, db_path=isolated_db)
    }
    assert pool_before <= final_ids


def _enqueue_paused_blocking_task(run_id: str, db_path: str) -> None:
    enqueue_task(run_id, "engine.test.blocking", "blocking:0", db_path=db_path)
    lifecycle.pause_run_tasks(run_id, db_path=db_path)
    runs.update_run_status(run_id, StoreRunStatus.PAUSED)


def _install_blocking_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    import time as _time

    from app import engine_tasks

    async def _execute(
        _task: Any, *, db_path: str | None = None
    ) -> dict[str, bool]:
        _time.sleep(1.0)
        return {"completed": True}

    monkeypatch.setattr(engine_tasks, "execute_engine_task", _execute)


async def _worst_loop_stall(stop: asyncio.Event) -> float:
    import time as _time

    worst = 0.0
    while not stop.is_set():
        started = _time.monotonic()
        await asyncio.sleep(0.01)
        worst = max(worst, _time.monotonic() - started - 0.01)
    return worst


async def test_resume_does_not_execute_run_work_on_the_event_loop(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Resume cohorts must run off the API loop; synchronous state/SQLite work
    # otherwise starves health checks.
    run = seed_run("loop freedom")
    _enqueue_paused_blocking_task(run.id, isolated_db)
    _install_blocking_execute(monkeypatch)

    stop = asyncio.Event()
    probe = asyncio.create_task(_worst_loop_stall(stop))
    await runs_lifecycle._launch_resume(run.id)
    await asyncio.gather(*list(runs_lifecycle._resume_tasks))
    stop.set()
    worst_stall = await probe

    assert worst_stall < 0.5, (
        f"event loop stalled {worst_stall:.2f}s while a resumed run executed"
    )


@pytest.mark.asyncio
async def test_resume_rejects_final_safety_block_after_finalize_succeeded(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    owner = make_client()
    owner_headers = {"X-Client-ID": "final-safety-block-owner"}
    created = _create_run(
        owner,
        "Study a final-stage safety block",
        headers=owner_headers,
        tier="express",
    )
    assert created.status_code == 200, created.text
    run_id = str(created.json()["id"])
    runs.update_run_status(run_id, StoreRunStatus.RUNNING, db_path=isolated_db)

    predecessor = enqueue_task(
        run_id,
        "engine.node.overview",
        "completed-overview",
        db_path=isolated_db,
    )
    previous_claim = store_tasks.claim_task(
        "resume-safety-fixture", run_id=run_id, db_path=isolated_db
    )
    assert previous_claim is not None and previous_claim.id == predecessor.id
    assert lifecycle.complete_task(
        predecessor.id,
        "resume-safety-fixture",
        {},
        db_path=isolated_db,
    )

    state = _task_state(run_id)
    checkpoint_seq = _seed_checkpoint(
        run_id,
        state,
        stage=f"engine_task:{predecessor.id}",
        db_path=isolated_db,
    )
    checkpoint = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    checkpoint_seq = seed_checkpoint(
        run_id,
        {
            **checkpoint["state"],
            "resume_successor": engine_tasks_support.FINALIZE_TASK,
        },
        stage=f"engine_task:{predecessor.id}",
        schema_version=checkpoint["schema_version"],
        last_event_seq=checkpoint["last_event_seq"],
        db_path=isolated_db,
    )
    finalizer = enqueue_task(
        run_id,
        engine_tasks_support.FINALIZE_TASK,
        f"{engine_tasks_support.FINALIZE_TASK}:after:{predecessor.id}",
        inputs={"checkpoint_seq": checkpoint_seq},
        dependencies=(predecessor.id,),
        db_path=isolated_db,
    )
    _patch_restore_generator(monkeypatch, _Generator(state))

    async def block_final_report(*_: Any, **__: Any) -> SafetyDecision:
        return SafetyDecision(
            stage="final",
            decision="block",
            reason="Final-stage policy blocked this report.",
        )

    built = report_build._BuiltReport(
        payload={
            "idea_count": 1,
            "leaderboard": [
                {"title": "Safe fixture", "statement": "A report."}
            ],
        },
        markdown="# Final safety fixture",
        facts=[],
        exclusion_tally={},
    )

    async def fake_build_report(*_: Any, **__: Any) -> Any:
        return built

    _install_runtime(monkeypatch).drain_final_state = fake_final_drain
    monkeypatch.setattr(
        report_finalize, "build_report_content", fake_build_report
    )
    _install_runtime(monkeypatch).screen = block_final_report

    assert await task_worker.run_once(
        "final-safety-worker", run_id=run_id, db_path=isolated_db
    )
    blocked = runs.get_run(run_id, db_path=isolated_db)
    completed_finalize = store_tasks.get_task(finalizer.id, db_path=isolated_db)
    assert (
        blocked is not None and blocked.status == StoreRunStatus.BLOCKED.value
    )
    assert completed_finalize is not None
    assert completed_finalize.status == "completed"
    final_decision = [
        item
        for item in store.list_safety_decisions(run_id, db_path=isolated_db)
        if item["stage"] == "final"
    ]
    assert len(final_decision) == 1 and final_decision[0]["decision"] == "block"
    assert reports.get_latest_report(run_id, db_path=isolated_db) is None

    outsider = owner.post(
        f"/api/runs/{run_id}/resume",
        headers={"X-Client-ID": "different-owner"},
    )
    assert outsider.status_code == 404

    response = owner.post(f"/api/runs/{run_id}/resume", headers=owner_headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "run was blocked; create a new run"
    saved = runs.get_run(run_id, db_path=isolated_db)
    assert saved is not None and saved.status == StoreRunStatus.BLOCKED.value
    tasks = store_tasks.list_tasks(run_id, db_path=isolated_db)
    assert [(task.task_type, task.status) for task in tasks] == [
        ("engine.node.overview", "completed"),
        (engine_tasks_support.FINALIZE_TASK, "completed"),
    ]
    events_response = owner.get(
        f"/api/runs/{run_id}/events?stream=false", headers=owner_headers
    )
    assert events_response.status_code == 200
    events = events_response.json()["events"]
    safety_event = next(
        event for event in events if event["type"] == "safety.final"
    )
    blocked_event = next(
        event
        for event in events
        if event["type"] == "status"
        and event["payload"].get("status") == "blocked"
    )
    assert safety_event["seq"] < blocked_event["seq"]
    status_events = [event for event in events if event["type"] == "status"]
    assert status_events[-1]["payload"]["status"] == "blocked"
    assert not any(
        event["payload"].get("status") == "resuming" for event in events
    )


def _run_with_held_decision(
    client: TestClient, headers: dict[str, str]
) -> tuple[str, str]:
    from app.store import records as store
    from app.store.records import NewSafetyDecision as StoreNewSafetyDecision

    created = _create_run(
        client, "Review a sensitive research protocol", headers=headers
    ).json()
    store.add_safety_decision(
        StoreNewSafetyDecision(
            run_id=created["id"],
            stage="intake",
            decision="hold",
            reason="Context requires review.",
            matches=[],
            category="uncertain",
            policy_version="coscientist-safety-v2",
            requires_review=True,
        )
    )
    decision_id = store.list_safety_decisions(created["id"])[0]["id"]
    return created["id"], decision_id


def test_safety_adjudication_is_identified_and_single_use(
    isolated_db: str,
) -> None:
    from app.store import records as store

    client = _client()
    headers = {"X-Client-ID": "reviewer-1"}
    run_id, decision_id = _run_with_held_decision(client, headers)

    anonymous = client.post(
        f"/api/runs/{run_id}/safety/{decision_id}/adjudicate",
        json={"resolution": "approved"},
    )
    assert anonymous.status_code == 404

    approved = client.post(
        f"/api/runs/{run_id}/safety/{decision_id}/adjudicate",
        headers=headers,
        json={"resolution": "approved"},
    )
    assert approved.status_code == 200
    assert store.safety_stage_is_approved(
        run_id, "intake", "coscientist-safety-v2"
    )

    repeated = client.post(
        f"/api/runs/{run_id}/safety/{decision_id}/adjudicate",
        headers=headers,
        json={"resolution": "rejected"},
    )
    assert repeated.status_code == 409


def test_held_hypothesis_adjudication_records_without_blocking(
    isolated_db: str,
) -> None:
    # Hypothesis-stage holds resolve one excluded idea without restarting or
    # stopping the whole run.
    from tests._drain_helpers import _held_final_state, _persist

    client = _client()
    headers = {"X-Client-ID": "held-reviewer"}
    created = _create_run(
        client, "Adjudicate hypotheses held for review", headers=headers
    ).json()
    run_id = created["id"]
    _persist(
        run_id=run_id, final_state=_held_final_state(), db_path=isolated_db
    )

    listed = client.get(f"/api/runs/{run_id}/safety", headers=headers)
    assert listed.status_code == 200
    holds = [d for d in listed.json()["safety"] if d["decision"] == "hold"]
    assert len(holds) == 2

    approved = client.post(
        f"/api/runs/{run_id}/safety/{holds[0]['id']}/adjudicate",
        headers=headers,
        json={"resolution": "approved"},
    )
    assert approved.status_code == 200

    rejected = client.post(
        f"/api/runs/{run_id}/safety/{holds[1]['id']}/adjudicate",
        headers=headers,
        json={"resolution": "rejected"},
    )
    assert rejected.status_code == 200

    by_id = {
        d["id"]: d
        for d in client.get(
            f"/api/runs/{run_id}/safety", headers=headers
        ).json()["safety"]
    }
    assert by_id[holds[0]["id"]]["resolution"] == "approved"
    assert by_id[holds[1]["id"]]["resolution"] == "rejected"
    repeated = client.post(
        f"/api/runs/{run_id}/safety/{holds[0]['id']}/adjudicate",
        headers=headers,
        json={"resolution": "rejected"},
    )
    assert repeated.status_code == 409
    assert (
        client.get(f"/api/runs/{run_id}", headers=headers).json()["status"]
        == "draft"
    )


def _started_run_id() -> str:
    c = _client()
    return str(
        _create_run(
            c, "Investigate ferroptosis in cancer", tier="express"
        ).json()["id"]
    )


def _announce(run_id: str, prompt: str = "Start research") -> Any:
    # TestClient vendors a distinct httpx Response type, so this boundary
    # deliberately returns Any.
    return _client().post(
        f"/api/runs/{run_id}/messages/started", json={"prompt": prompt}
    )


def _start_rows(run_id: str) -> list[MessageRow]:
    return [
        m for m in store_messages.list_messages(run_id) if m.kind == "start"
    ]


def test_live_model_writes_the_announcement(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    rid = _started_run_id()
    fake_process_mode.online()
    install_completion_backend(
        monkeypatch,
        (_fake_litellm(["Your session is ", "under way."])).acompletion,
    )

    body = _announce(rid).text

    assert "under way." in body
    assert '"fallback": true' not in body
    reply = _start_rows(rid)[1]
    assert reply.content == "Your session is under way."
    assert reply.meta is None


def test_provider_failure_falls_back_without_an_error_frame(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    rid = _started_run_id()
    fake_process_mode.online()
    install_completion_backend(
        monkeypatch,
        (
            _fake_litellm([], raise_exc=RuntimeError("provider down"))
        ).acompletion,
    )

    body = _announce(rid).text

    assert '"type": "error"' not in body
    assert '"fallback": true' in body
    assert _start_rows(rid)[1].content.strip()


def test_announcement_404s_for_an_unknown_run() -> None:
    assert _announce("no-such-run").status_code == 404


def test_reasoning_is_relayed_and_kept_with_the_reply(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    rid = _started_run_id()
    fake_process_mode.online()
    install_completion_backend(
        monkeypatch,
        (
            _fake_litellm(
                [
                    {
                        "content": None,
                        "reasoning_content": (
                            "The run exists, so this confirms it."
                        ),
                    },
                    {"content": "Under way.", "reasoning_content": None},
                ]
            )
        ).acompletion,
    )

    body = _announce(rid).text

    assert '"type": "reasoning"' in body
    assert body.index('"type": "reasoning"') < body.index('"type": "chunk"')
    reply = _start_rows(rid)[1]
    assert reply.meta == {"reasoning": "The run exists, so this confirms it."}


def test_thinking_only_announcement_retries_before_the_fallback(
    monkeypatch: pytest.MonkeyPatch, fake_process_mode: FakeProcessMode
) -> None:
    # Fixed announcement fallback is reserved for retries that also fail, not
    # the first thinking-only reply.
    rid = _started_run_id()
    fake_process_mode.online()
    monkeypatch.setattr(settings, "chat_model_name", "deepseek/deepseek-v4-pro")
    calls: list[dict[str, Any]] = []
    install_completion_backend(
        monkeypatch,
        (
            _fake_litellm(
                [
                    {
                        "content": None,
                        "reasoning_content": (
                            "brainstorming candidates at length..."
                        ),
                    }
                ],
                retry_chunks=[
                    {
                        "content": "Research is under way.",
                        "reasoning_content": None,
                    }
                ],
                calls=calls,
            )
        ).acompletion,
    )

    body = _announce(rid).text

    assert len(calls) == 2
    assert calls[1]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert '"fallback": true' not in body
    reply = _start_rows(rid)[1]
    assert reply.content == "Research is under way."
