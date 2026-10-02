"""Where a scientist's hypothesis joins a run that is already executing.

PARITY ``HITL-MANUAL-HYP-001``. A contributed hypothesis is persisted and
safety-screened at POST time; these tests pin the other half -- that it
becomes an engine ``Hypothesis`` on the durable path (the only path
production runs) at one safe boundary, the orchestrator's, and from there
takes the same review/proximity/tournament/evolution path a generated one
takes, carrying its authorship through the checkpoint.

The orchestrator is the boundary because it is the run's only scheduling
decision point: the pool cannot grow inside a ranking wave or between a
fan-out's items and its aggregate, the orchestrator's own commit puts the
newcomer in the checkpoint every later task restores, and an unreviewed
pool member forces the scheduler's review transition before the idea can
rank or be bred from.
"""

from typing import Any

import pytest
from co_scientist.models import SCIENTIST_REVIEWER

from app import store, task_worker
from app.config import settings
from app.engine_adapter.drain import hypotheses as drain_hypotheses
from app.engine_tasks import fanout as engine_tasks_fanout
from app.engine_tasks import inputs as engine_tasks_inputs
from app.engine_tasks import node as engine_tasks_restore
from app.engine_tasks.support import NODE_TASK_PREFIX
from tests._client import make_client as _client
from tests._engine_tasks_helpers import (
    _Generator,
    _seed_checkpoint,
    _task_state,
)


def _node_task(run_id: str, node: str, seq: int, db_path: str) -> Any:
    """Enqueue and claim one durable node task for ``node``."""
    store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=f"{NODE_TASK_PREFIX}{node}",
            inputs={"checkpoint_seq": seq},
            idempotency_key=f"engine:{node}:{seq}",
            priority=90,
        ),
        db_path=db_path,
    )
    task = store.claim_task("worker", run_id=run_id, db_path=db_path)
    assert task is not None
    return task


def _restored_at(run_id: str, node: str, db_path: str) -> dict[str, Any]:
    """Restore the state one durable ``node`` task starts from."""
    state = _task_state(run_id)
    seq = _seed_checkpoint(run_id, state, db_path=db_path)
    task = _node_task(run_id, node, seq, db_path)
    checkpoint = store.get_latest_checkpoint(run_id, db_path=db_path)
    assert checkpoint is not None
    return engine_tasks_restore._restore_node_task_state(
        task, checkpoint, _Generator(state), {}, db_path
    )


def _seed_hypothesis(run_id: str, db_path: str) -> str:
    """Persist a scientist hypothesis the way the endpoint does."""
    hypothesis_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run_id,
            title="Scientist idea",
            statement="A scientist-proposed mechanism for kinase X.",
            created_by_agent="scientist_manual",
            author="dr-who",
        ),
        db_path=db_path,
    )
    store.update_hypothesis_state(
        hypothesis_id,
        store.HypothesisStateChanges(safety_status="allow"),
        db_path=db_path,
    )
    return hypothesis_id


def _seed_review(
    run_id: str, hypothesis_id: str, verdict: str, db_path: str
) -> None:
    """Persist a scientist review the way the endpoint does."""
    store.add_review(
        store.NewReview(
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


def test_admission_happens_at_the_orchestrator_boundary(
    isolated_db: str,
) -> None:
    """The Supervisor's decision point is where the pool may grow."""
    run = store.create_run("Admission", "express", "engine", {})
    hypothesis_id = _seed_hypothesis(run.id, isolated_db)

    state = _restored_at(run.id, "orchestrator", isolated_db)

    assert [h.id for h in state["hypotheses"]] == [hypothesis_id]
    assert state["hypotheses"][0].origin.value == "scientist_manual"


def test_a_ranking_wave_cannot_gain_a_competitor(isolated_db: str) -> None:
    """No idea enters mid-tournament, where its Elo would mean nothing."""
    run = store.create_run("Mid-tournament", "express", "engine", {})
    _seed_hypothesis(run.id, isolated_db)

    state = _restored_at(run.id, "ranking", isolated_db)

    assert state["hypotheses"] == []


def test_an_admitted_idea_still_owes_the_run_a_peer_review(
    isolated_db: str,
) -> None:
    """It arrives unreviewed, so the scheduler must review before ranking."""
    from co_scientist.models import has_peer_review

    run = store.create_run("Owes review", "express", "engine", {})
    hypothesis_id = _seed_hypothesis(run.id, isolated_db)
    _seed_review(run.id, hypothesis_id, "support", isolated_db)

    state = _restored_at(run.id, "orchestrator", isolated_db)
    merged = state["hypotheses"][0]

    assert [r.reviewer for r in merged.reviews] == [SCIENTIST_REVIEWER]
    assert not has_peer_review(merged)


def test_the_admitted_idea_enters_the_durable_review_fanout(
    isolated_db: str,
) -> None:
    """One leasable review-item task per unreviewed idea, including this one."""
    run = store.create_run("Review fanout", "express", "engine", {})
    hypothesis_id = _seed_hypothesis(run.id, isolated_db)
    _seed_review(run.id, hypothesis_id, "support", isolated_db)
    state = _restored_at(run.id, "orchestrator", isolated_db)
    seq = int(
        (store.get_latest_checkpoint(run.id, db_path=isolated_db) or {})["seq"]
    )
    task = _node_task(run.id, "review", seq, isolated_db)

    result = engine_tasks_fanout._enqueue_review_fanout(
        task, state, seq, db_path=isolated_db
    )

    items = [
        store.get_task(task_id, db_path=isolated_db)
        for task_id in result["fanout_task_ids"]
    ]
    assert [item.inputs["hypothesis_id"] for item in items if item] == [
        hypothesis_id
    ]


def test_an_opposing_verdict_withholds_the_idea_from_the_tournament(
    isolated_db: str,
) -> None:
    """The merge re-derives the disposition, at no LLM cost."""
    run = store.create_run("Oppose", "express", "engine", {})
    hypothesis_id = _seed_hypothesis(run.id, isolated_db)
    _seed_review(run.id, hypothesis_id, "oppose", isolated_db)

    state = _restored_at(run.id, "orchestrator", isolated_db)

    merged = state["hypotheses"][0]
    assert merged.review_disposition == "inaccurate"
    assert not merged.is_rankable()


def test_authorship_and_screen_survive_a_checkpoint_round_trip(
    isolated_db: str,
) -> None:
    """Provenance rides the checkpoint, not the store row alone."""
    from co_scientist.checkpoint import (
        restore_workflow_state,
        serialize_workflow_state,
    )

    run = store.create_run("Provenance", "express", "engine", {})
    _seed_hypothesis(run.id, isolated_db)
    state = {**_task_state(run.id)}
    engine_tasks_inputs._merge_scientist_inputs(state, run.id, isolated_db)

    envelope = serialize_workflow_state(state, last_event_seq=0)
    restored = restore_workflow_state(envelope, tool_registry=None)

    hypothesis = restored["hypotheses"][0]
    assert hypothesis.origin.value == "scientist_manual"
    assert hypothesis.enrichments["scientist_author"] == "dr-who"
    assert hypothesis.safety_status == "allow"
    # The drain reads the mark back under the same key it was written.
    assert (
        drain_hypotheses._payload_author(hypothesis.to_dict())
        == hypothesis.enrichments[engine_tasks_inputs.SCIENTIST_AUTHOR_MARK]
    )


def test_an_unscreened_row_does_not_suppress_the_engine_safety_screen(
    isolated_db: str,
) -> None:
    """The column's 'pending' default is not a completed screen.

    A non-None ``safety_status`` tells the engine's screen the hypothesis
    is already decided, so the placeholder must not travel as one.
    """
    from co_scientist.agents.safety.safety_screen import (
        _screen_one_hypothesis,
    )

    run = store.create_run("Unscreened", "express", "engine", {})
    store.add_hypothesis(
        store.NewHypothesis(
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


def test_the_admitted_idea_reaches_the_tournament_and_the_gene_pool(
    isolated_db: str,
) -> None:
    """It ranks, and evolution's near-duplicate guard can see it.

    Both read ``state["hypotheses"]`` -- the tournament through
    ``is_rankable``, the guard through ``sample_context_hypotheses`` over
    the whole pool -- so being in the admitted pool is what puts a
    contributed idea in front of them.
    """
    from co_scientist.agents.evolution.evolve_context import (
        sample_context_hypotheses,
    )
    from co_scientist.models import Hypothesis

    run = store.create_run("Gene pool", "express", "engine", {})
    hypothesis_id = _seed_hypothesis(run.id, isolated_db)
    _seed_review(run.id, hypothesis_id, "support", isolated_db)
    state = _restored_at(run.id, "orchestrator", isolated_db)
    generated = Hypothesis(text="A generated mechanism for kinase Y.")
    state["hypotheses"].append(generated)

    peers = sample_context_hypotheses(
        all_hypotheses=state["hypotheses"], exclude_hypothesis=generated
    )

    assert state["hypotheses"][0].is_rankable()
    assert [peer.id for peer in peers] == [hypothesis_id]


def test_the_drain_reattributes_an_idea_whose_row_is_gone(
    isolated_db: str,
) -> None:
    """The author rides the payload, so an insert is not an anonymous one."""
    from tests._drain_helpers import _persist

    run = store.create_run("Reattribute", "express", "engine", {})
    _seed_hypothesis(run.id, isolated_db)
    state: dict[str, Any] = {"hypotheses": []}
    engine_tasks_inputs._merge_scientist_inputs(state, run.id, isolated_db)
    payload = [h.to_dict() for h in state["hypotheses"]]
    payload[0]["id"] = "unseen-engine-id"
    other = store.create_run("Fresh store", "express", "engine", {})

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

    rows = store.list_hypotheses(other.id, isolated_db)
    assert [row["author"] for row in rows] == ["dr-who"]
    assert rows[0]["created_by_agent"] == "scientist_manual"


def test_admitting_the_same_idea_twice_creates_one_pool_member(
    isolated_db: str,
) -> None:
    """A second boundary re-merges the same rows, not a second competitor."""
    run = store.create_run("Idempotent", "express", "engine", {})
    hypothesis_id = _seed_hypothesis(run.id, isolated_db)
    _seed_review(run.id, hypothesis_id, "revise", isolated_db)
    state = {**_task_state(run.id)}

    engine_tasks_inputs._merge_scientist_inputs(state, run.id, isolated_db)
    engine_tasks_inputs._merge_scientist_inputs(state, run.id, isolated_db)

    assert [h.id for h in state["hypotheses"]] == [hypothesis_id]
    assert len(state["hypotheses"][0].reviews) == 1


_LATE_CONTRIB_WORKER = "late-contrib-test"


async def _drain_until_finalize_enqueued(run_id: str, isolated_db: str) -> None:
    """Run tasks one at a time up to (not including) finalize.

    Generous cap: each fan-out (review/verification/generation/reflection
    items) and every ranking match is its own durable task.
    """
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
    """A contribution past the last orchestrator boundary self-heals.

    Residual window recorded on HITL-STEERING-001/HITL-MANUAL-HYP-001: a
    contribution POSTed while a run executes its final nodes has no
    remaining orchestrator boundary and gets no continuation task at POST
    time (``enqueue_scientist_continuation`` only reopens an already-
    ``completed`` run). Closed by
    ``engine_tasks_inputs.reopen_for_pending_scientist_input``, called
    from ``execute_finalize`` once the report settles -- this drives the
    real durable queue one task at a time to land a message exactly in
    that window, rather than asserting the fix in isolation.
    """
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client = _client()
    created = client.post(
        "/api/runs",
        json={"research_goal": "Late contribution reopen", "tier": "express"},
    )
    run_id = created.json()["id"]
    started = client.post(f"/api/runs/{run_id}/start", json={})
    assert started.status_code == 200

    await _drain_until_finalize_enqueued(run_id, isolated_db)
    pre_status = store.get_run(run_id, db_path=isolated_db)
    assert pre_status is not None and pre_status.status != "completed"

    posted = client.post(
        f"/api/runs/{run_id}/messages",
        json={"content": "also consider off-target kinase effects"},
    )
    assert posted.status_code == 200
    # No boundary left for it to land on yet.
    assert posted.json()["continuation_task_id"] is None
    assert store.get_pending_steering(run_id, db_path=isolated_db)

    # run_run_until_idle drains everything -- both the original completion
    # and the reopened continuation cycle it triggers -- so the run lands
    # completed again either way; the evidence of reopening is the
    # continuation task and lifecycle event left behind along the way,
    # and the message finally being acknowledged.
    await task_worker.run_run_until_idle(
        run_id, _LATE_CONTRIB_WORKER, db_path=isolated_db
    )

    reopened = store.get_run(run_id, db_path=isolated_db)
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
        for event in store.list_events(run_id, db_path=isolated_db)
        if event["payload"].get("event") == "reopened_for_scientist_input"
    ]
    assert lifecycle_events
    assert not store.get_pending_steering(run_id, db_path=isolated_db)
