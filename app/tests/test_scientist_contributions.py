from __future__ import annotations

from typing import Any

import pytest
from co_scientist.constants import NOT_VIABLE_SCORE
from co_scientist.models import (
    SCIENTIST_REVIEWER,
)

from app import engine_tasks, task_worker
from app.config import settings
from app.engine_adapter.drain import hypotheses as drain_hypotheses
from app.engine_tasks import inputs as engine_tasks_inputs
from app.engine_tasks import node as engine_tasks_restore
from app.engine_tasks.support import (
    NODE_TASK_PREFIX,
)
from app.store import checkpoints, hypotheses, messages, records, runs
from app.store import events as store_events
from app.store import hypotheses as store_hypotheses
from app.store import tasks as store
from app.store.hypotheses import HypothesisStateChanges, NewHypothesis
from app.store.models import RunStatus as StoreRunStatus
from app.store.records import NewReview
from tests._client import create_run as _create_run
from tests._client import make_client as _client
from tests._engine_tasks_helpers import (
    _Generator,
    _seed_checkpoint,
    _task_state,
)
from tests._store_helpers import (
    enqueue_task,
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


def _node_task(run_id: str, node: str, seq: int, db_path: str) -> Any:
    enqueue_task(
        run_id,
        f"{NODE_TASK_PREFIX}{node}",
        f"engine:{node}:{seq}",
        inputs={"checkpoint_seq": seq},
        priority=90,
        db_path=db_path,
    )
    task = store.claim_task("worker", run_id=run_id, db_path=db_path)
    assert task is not None
    return task


def _restored_at(run_id: str, node: str, db_path: str) -> dict[str, Any]:
    state = _task_state(run_id)
    seq = _seed_checkpoint(run_id, state, db_path=db_path)
    task = _node_task(run_id, node, seq, db_path)
    checkpoint = checkpoints.get_latest_checkpoint(run_id, db_path=db_path)
    assert checkpoint is not None
    return engine_tasks_restore._restore_node_task_state(
        task, checkpoint, _Generator(state), {}, db_path
    )


def _seed_hypothesis(run_id: str, db_path: str) -> str:
    hypothesis_id = hypotheses.add_hypothesis(
        NewHypothesis(
            run_id=run_id,
            title="Scientist idea",
            statement="A scientist-proposed mechanism for kinase X.",
            created_by_agent="scientist_manual",
            author="dr-who",
        ),
        db_path=db_path,
    )
    hypotheses.update_hypothesis_state(
        hypothesis_id,
        HypothesisStateChanges(safety_status="allow"),
        db_path=db_path,
    )
    return hypothesis_id


def _seed_review(
    run_id: str, hypothesis_id: str, verdict: str, db_path: str
) -> None:
    records.add_review(
        NewReview(
            run_id=run_id,
            hypothesis_id=hypothesis_id,
            reviewer_agent="scientist",
            summary=f"Scientist verdict: {verdict} (by dr-who)",
            critique="The proposed control cannot distinguish the mechanism.",
            author="dr-who",
            verdict=verdict,
        ),
        db_path=db_path,
    )


@pytest.mark.parametrize(
    ("node", "verdict", "admitted", "rankable"),
    [
        ("orchestrator", None, True, True),
        ("orchestrator", "support", True, True),
        ("orchestrator", "oppose", True, False),
        ("ranking", None, False, False),
    ],
)
def test_scientist_idea_is_admitted_only_at_the_orchestrator_boundary(
    isolated_db: str,
    node: str,
    verdict: str | None,
    admitted: bool,
    rankable: bool,
) -> None:
    from co_scientist.models import has_peer_review

    run = seed_run("Admission", profile="express")
    hypothesis_id = _seed_hypothesis(run.id, isolated_db)
    if verdict:
        _seed_review(run.id, hypothesis_id, verdict, isolated_db)

    state = _restored_at(run.id, node, isolated_db)

    assert [h.id for h in state["hypotheses"]] == (
        [hypothesis_id] if admitted else []
    )
    if admitted:
        merged = state["hypotheses"][0]
        assert merged.origin.value == "scientist_manual"
        # A scientist verdict never stands in for the run's own peer review.
        assert not has_peer_review(merged)
        assert (merged.review_disposition == "inaccurate") is (not rankable)
        assert [r.reviewer for r in merged.reviews] == (
            [SCIENTIST_REVIEWER] if verdict else []
        )


def test_authorship_and_screen_survive_a_checkpoint_round_trip(
    isolated_db: str,
) -> None:
    from co_scientist.checkpoint import (
        restore_workflow_state,
        serialize_workflow_state,
    )

    run = seed_run("Provenance", profile="express")
    _seed_hypothesis(run.id, isolated_db)
    state = {**_task_state(run.id)}
    engine_tasks_inputs._merge_scientist_inputs(state, run.id, isolated_db)

    envelope = serialize_workflow_state(state, last_event_seq=0)
    restored = restore_workflow_state(envelope, tool_registry=None)

    hypothesis = restored["hypotheses"][0]
    assert hypothesis.origin.value == "scientist_manual"
    assert hypothesis.enrichments["scientist_author"] == "dr-who"
    assert hypothesis.safety_status == "allow"
    assert (
        drain_hypotheses._payload_author(hypothesis.to_dict())
        == hypothesis.enrichments[engine_tasks_inputs.SCIENTIST_AUTHOR_MARK]
    )


def test_an_unscreened_row_does_not_suppress_the_engine_safety_screen(
    isolated_db: str,
) -> None:
    # Pending is a placeholder, not a finished screen; sending it suppresses the
    # real safety decision.
    from co_scientist.agents.safety import (
        _screen_one_hypothesis,
    )

    run = seed_run("Unscreened", profile="express")
    hypotheses.add_hypothesis(
        NewHypothesis(
            run_id=run.id,
            title="Unscreened idea",
            statement="A scientist-proposed mechanism for kinase X.",
            created_by_agent="scientist_manual",
            author="dr-who",
        ),
        db_path=isolated_db,
    )

    state = _restored_at(run.id, "orchestrator", isolated_db)

    merged = state["hypotheses"][0]
    assert merged.safety_status is None
    _screen_one_hypothesis(merged)
    assert merged.safety_status == "allow"


def test_the_drain_reattributes_an_idea_whose_row_is_gone(
    isolated_db: str,
) -> None:
    from tests._drain_helpers import _persist

    run = seed_run("Reattribute", profile="express")
    _seed_hypothesis(run.id, isolated_db)
    state: dict[str, Any] = {"hypotheses": []}
    engine_tasks_inputs._merge_scientist_inputs(state, run.id, isolated_db)
    payload = [h.to_dict() for h in state["hypotheses"]]
    payload[0]["id"] = "unseen-engine-id"
    other = seed_run("Fresh store", profile="express")

    _persist(
        run_id=other.id,
        final_state={
            "hypotheses": payload,
            "articles": [],
            "tournament_matchups": [],
            "proximity_graph": {},
            "meta_review": {},
            "research_overview": {},
        },
        db_path=isolated_db,
    )

    rows = hypotheses.list_hypotheses(other.id, isolated_db)
    assert [row["author"] for row in rows] == ["dr-who"]
    assert rows[0]["created_by_agent"] == "scientist_manual"


def test_admitting_the_same_idea_twice_creates_one_pool_member(
    isolated_db: str,
) -> None:
    run = seed_run("Idempotent", profile="express")
    hypothesis_id = _seed_hypothesis(run.id, isolated_db)
    _seed_review(run.id, hypothesis_id, "revise", isolated_db)
    state = {**_task_state(run.id)}

    engine_tasks_inputs._merge_scientist_inputs(state, run.id, isolated_db)
    engine_tasks_inputs._merge_scientist_inputs(state, run.id, isolated_db)

    assert [h.id for h in state["hypotheses"]] == [hypothesis_id]
    assert len(state["hypotheses"][0].reviews) == 1


_LATE_CONTRIB_WORKER = "late-contrib-test"


async def _drain_until_finalize_enqueued(run_id: str, isolated_db: str) -> None:
    for _ in range(500):
        tasks = store.list_tasks(run_id, db_path=isolated_db)
        if any(t.task_type == "engine.finalize" for t in tasks):
            return
        worked = await task_worker.run_once(
            _LATE_CONTRIB_WORKER, run_id=run_id, db_path=isolated_db
        )
        assert worked, "run finished before finalize was ever enqueued"
    raise AssertionError("finalize never appeared inside the task cap")


@pytest.mark.asyncio
async def test_late_contribution_reopens_the_run_once_it_completes(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Contributions arriving after the last orchestrator need a continuation
    # once finalization settles.
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    created = _create_run(client, "Late contribution reopen", tier="express")
    run_id = created.json()["id"]
    started = client.post(f"/api/runs/{run_id}/start", json={})
    assert started.status_code == 200

    await _drain_until_finalize_enqueued(run_id, isolated_db)
    pre_status = runs.get_run(run_id, db_path=isolated_db)
    assert pre_status is not None and pre_status.status != "completed"

    posted = client.post(
        f"/api/runs/{run_id}/messages",
        json={"content": "also consider off-target kinase effects"},
    )
    assert posted.status_code == 200
    assert posted.json()["continuation_task_id"] is None
    assert messages.get_pending_steering(run_id, db_path=isolated_db)

    await task_worker.run_run_until_idle(
        run_id, _LATE_CONTRIB_WORKER, db_path=isolated_db
    )

    reopened = runs.get_run(run_id, db_path=isolated_db)
    assert reopened is not None and reopened.status == "completed", (
        reopened.error if reopened else None
    )
    tasks_after = store.list_tasks(run_id, db_path=isolated_db)
    assert any(
        task.task_type == "engine.node.orchestrator"
        and task.provenance.get("behavior") == "scientist-directed-continuation"
        for task in tasks_after
    )
    lifecycle_events = [
        event["payload"]
        for event in store_events.list_events(run_id, db_path=isolated_db)
        if event["payload"].get("event") == "reopened_for_scientist_input"
    ]
    assert lifecycle_events
    assert not messages.get_pending_steering(run_id, db_path=isolated_db)


def test_scientist_inputs_merge_into_engine_state_once(
    isolated_db: str,
) -> None:
    run = seed_run("Scientist loop")
    hypothesis_id = store_hypotheses.add_hypothesis(
        NewHypothesis(
            run_id=run.id,
            title="Scientist idea",
            statement="A scientist-proposed mechanism",
            created_by_agent="scientist_manual",
            author="researcher",
        ),
        db_path=isolated_db,
    )
    records.add_review(
        NewReview(
            run_id=run.id,
            hypothesis_id=hypothesis_id,
            reviewer_agent="scientist",
            summary="Scientist verdict: oppose (by researcher)",
            critique="The proposed control cannot distinguish the mechanism.",
        ),
        db_path=isolated_db,
    )
    state = _task_state(run.id)

    engine_tasks_inputs._merge_scientist_inputs(state, run.id, isolated_db)
    engine_tasks_inputs._merge_scientist_inputs(state, run.id, isolated_db)

    merged = state["hypotheses"]
    assert [hypothesis.id for hypothesis in merged] == [hypothesis_id]
    assert merged[0].origin.value == "scientist_manual"
    assert len(merged[0].reviews) == 1
    assert merged[0].reviews[0].overall_score == NOT_VIABLE_SCORE
    assert "cannot distinguish" in merged[0].reviews[0].constructive_feedback


def test_scientist_input_reopens_completed_engine_run(isolated_db: str) -> None:
    run = seed_run("Continuation")
    checkpoint_seq = _seed_checkpoint(
        run.id,
        _task_state(run.id),
        stage="engine_task:final",
        db_path=isolated_db,
    )
    runs.update_run_status(
        run.id, StoreRunStatus.COMPLETED, db_path=isolated_db
    )

    task = engine_tasks.enqueue_scientist_continuation(
        run.id, 42, db_path=isolated_db
    )

    assert task is not None
    assert task.task_type == "engine.node.orchestrator"
    assert task.inputs["checkpoint_seq"] == checkpoint_seq
    assert task.priority == 100
    reopened = runs.get_run(run.id, db_path=isolated_db)
    assert reopened is not None and reopened.status == "queued"
