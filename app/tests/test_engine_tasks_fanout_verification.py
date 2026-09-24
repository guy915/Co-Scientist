"""Deep-verification fan-out mechanics for the durable engine executor.

Who is fanned out (every idea still owed its one verification, and only
those), that the family commits through a single aggregate, and that a
pool with nothing left to verify still hands the run into the tournament.
Split from ``test_engine_tasks_fanout``, mirroring the source split
between ``engine_tasks_fanout_reflection`` and
``engine_tasks_fanout_verification``.
"""

import asyncio
from typing import Any

import pytest
from co_scientist.models import Article, Hypothesis

from app import engine_tasks, store
from app.config import settings
from tests._client import make_client
from tests._engine_tasks_helpers import (
    _Generator,
    _milestones,
    _patch_generator,
    _seed_checkpoint,
    _task_events,
    _task_state,
)


def _lease_verification_parent(run_id: str, db_path: str) -> Any:
    """Enqueue and lease a deep_verification node task to fan out from."""
    parent = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}deep_verification",
            inputs={"checkpoint_seq": 4},
            idempotency_key="verification-parent",
        ),
        db_path=db_path,
    )
    leased = store.claim_task("parent", run_id=run_id, db_path=db_path)
    assert leased is not None and leased.id == parent.id
    return leased


@pytest.mark.asyncio
async def test_verification_fanout_materializes_one_task_per_unverified_idea(
    isolated_db: str,
) -> None:
    """Every idea is verified before the tournament, not an Elo slice.

    The node now runs between the safety screen and ranking, so there is
    no tournament ordering to take a top-k from and nothing enters a
    match unprobed.
    """
    run = store.create_run("Task-level science", "standard", "engine", {})
    leased = _lease_verification_parent(run.id, isolated_db)
    state = _task_state(run.id)
    state["hypotheses"] = [
        Hypothesis(text=f"candidate-{index}", elo_rating=1000 + index)
        for index in range(5)
    ]

    result = engine_tasks._enqueue_verification_fanout(
        leased, state, 4, db_path=isolated_db
    )
    assert len(result["fanout_task_ids"]) == 5
    assert store.complete_task(leased.id, "parent", result, db_path=isolated_db)
    claimed = [
        store.claim_task(f"verify-{index}", run_id=run.id, db_path=isolated_db)
        for index in range(5)
    ]
    assert all(item is not None for item in claimed)
    assert {item.task_type for item in claimed if item is not None} == {
        engine_tasks.VERIFICATION_ITEM_TASK
    }


@pytest.mark.asyncio
async def test_a_resumed_run_fans_out_only_the_ideas_still_owed_one(
    isolated_db: str,
) -> None:
    """The once-ever marker survives the checkpoint and bounds the wave.

    Blanket verification is affordable only because it is incremental. A
    marker held anywhere but on the hypothesis would let every restart
    re-fund the whole pool.
    """
    run = store.create_run("Task-level science", "standard", "engine", {})
    leased = _lease_verification_parent(run.id, isolated_db)
    state = _task_state(run.id)
    verified = Hypothesis(text="already verified")
    verified.enrichments["deep_verification_issued"] = True
    fresh = Hypothesis(text="an evolution child")
    state["hypotheses"] = [
        Hypothesis.from_dict(verified.to_dict()),
        Hypothesis.from_dict(fresh.to_dict()),
    ]

    result = engine_tasks._enqueue_verification_fanout(
        leased, state, 4, db_path=isolated_db
    )

    assert len(result["fanout_task_ids"]) == 1
    assert store.complete_task(leased.id, "parent", result, db_path=isolated_db)
    item = store.claim_task("verify", run_id=run.id, db_path=isolated_db)
    assert item is not None
    assert item.inputs["hypothesis_id"] == state["hypotheses"][1].id


@pytest.mark.asyncio
async def test_a_pool_with_nothing_left_to_verify_advances_into_ranking(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The steady state from cycle two on must not stall the run.

    Every idea already carries its marker, so the fan-out enqueues no item
    tasks at all. The aggregate then has no dependencies, is claimable
    immediately, and has to commit the checkpoint and hand on to the
    tournament exactly as a populated one does.
    """
    run = store.create_run("Task-level science", "standard", "engine", {})
    state = _task_state(run.id)
    hypotheses = [Hypothesis(text=f"verified-{index}") for index in range(3)]
    for hypothesis in hypotheses:
        hypothesis.enrichments["deep_verification_issued"] = True
    state["hypotheses"] = hypotheses
    checkpoint_seq = _seed_checkpoint(run.id, state)
    node = store.enqueue_task(
        store.NewTask(
            run_id=run.id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}deep_verification",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key="verification-node",
        ),
        db_path=isolated_db,
    )
    _patch_generator(monkeypatch, _Generator(state), restore=True)
    leased_node = store.claim_task("node", run_id=run.id, db_path=isolated_db)
    assert leased_node is not None and leased_node.id == node.id
    scheduled = await engine_tasks.execute_node_task(
        leased_node, db_path=isolated_db
    )
    assert scheduled["fanout_task_ids"] == []
    assert store.complete_task(
        leased_node.id, "node", scheduled, db_path=isolated_db
    )

    aggregate = store.claim_task(
        "aggregate", run_id=run.id, db_path=isolated_db
    )
    assert aggregate is not None
    result = await engine_tasks.execute_verification_aggregate(
        aggregate, db_path=isolated_db
    )

    assert result["successful_verifications"] == 0
    assert result["failed_verifications"] == 0
    assert store.complete_task(
        aggregate.id, "aggregate", result, db_path=isolated_db
    )
    successor = store.get_task(result["successor_task_id"], db_path=isolated_db)
    assert successor is not None
    assert successor.task_type == (f"{engine_tasks.NODE_TASK_PREFIX}ranking")


async def _fake_verify(*_: Any, **__: Any) -> dict[str, Any]:
    # "holds" is a real DEEP_VERIFICATION_SCHEMA verdict: the aggregate
    # fails closed on anything outside the schema enum (audit E9).
    return {
        "probes": [{"question": "q"}],
        "verdict": "holds",
        "retrieval_queries": ["probe query"],
        "retrieved_articles": [
            Article(
                title="Probe evidence",
                source_id="probe-1",
                abstract="Direct targeted support.",
                used_in_analysis=True,
            ).to_dict()
        ],
        "verification_llm_calls": 2,
    }


async def _advance_verification_node(
    run_id: str, monkeypatch: pytest.MonkeyPatch, db_path: str
) -> None:
    """Seed a 3-candidate deep_verification node and fan it out."""
    state = _task_state(run_id)
    state["hypotheses"] = [
        Hypothesis(text=f"candidate-{index}", elo_rating=1200 + index)
        for index in range(3)
    ]
    checkpoint_seq = _seed_checkpoint(run_id, state)
    node = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}deep_verification",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key="verification-node",
        ),
        db_path=db_path,
    )
    _patch_generator(monkeypatch, _Generator(state), restore=True)
    leased_node = store.claim_task("node", run_id=run_id, db_path=db_path)
    assert leased_node is not None and leased_node.id == node.id
    scheduled = await engine_tasks.execute_node_task(
        leased_node, db_path=db_path
    )
    assert store.complete_task(
        leased_node.id, "node", scheduled, db_path=db_path
    )


async def _run_verification_children_and_aggregate(
    run_id: str, db_path: str, before_aggregate: Any | None = None
) -> None:
    """Lease the three verification children and commit one aggregate."""
    children = [
        store.claim_task(f"child-{index}", run_id=run_id, db_path=db_path)
        for index in range(3)
    ]
    assert all(child is not None for child in children)
    child_results = await asyncio.gather(
        *[
            engine_tasks.execute_verification_item(child, db_path=db_path)
            for child in children
            if child is not None
        ]
    )
    for index, (child, result) in enumerate(
        zip(children, child_results, strict=True)
    ):
        assert child is not None
        assert store.complete_task(
            child.id, f"child-{index}", result, db_path=db_path
        )
    aggregate = store.claim_task("aggregate", run_id=run_id, db_path=db_path)
    assert aggregate is not None
    if before_aggregate is not None:
        before_aggregate()
    result = await engine_tasks.execute_verification_aggregate(
        aggregate, db_path=db_path
    )
    assert result["successful_verifications"] == 3
    assert store.complete_task(
        aggregate.id, "aggregate", result, db_path=db_path
    )


def _assert_verifications_are_marked_once_ever(
    run_id: str, db_path: str
) -> None:
    """Every item marks its hypothesis, so no later cycle re-offers it.

    Written at the aggregate boundary rather than by the items, because
    that is the only place that sees the whole family -- and read back
    through the checkpoint, since a marker that does not survive the
    round trip bounds nothing on a resume.
    """
    latest = store.get_latest_checkpoint(run_id, db_path=db_path)
    assert latest is not None
    restored = latest["state"]["state"]["hypotheses"]
    assert all(
        item["enrichments"]["deep_verification_issued"] for item in restored
    )


def _assert_verification_committed(run_id: str, db_path: str) -> None:
    """Pin the aggregate-boundary commit: verdicts, evidence, milestone."""
    latest = store.get_latest_checkpoint(run_id, db_path=db_path)
    assert latest is not None
    restored = latest["state"]["state"]["hypotheses"]
    assert all(
        item["deep_verification_verdict"] == "holds" for item in restored
    )
    assert latest["state"]["state"]["articles"][-1]["source_id"] == "probe-1"
    assert restored[0]["enrichments"]["deep_verification"][
        "retrieval_queries"
    ] == ["probe query"]
    assert _milestones(run_id, db_path=db_path) == ["3 hypotheses verified"]
    verification_events = _task_events(
        run_id, "deep_verification", db_path=db_path
    )
    assert len(verification_events) == 1
    # Verification precedes tournament entry (``03-reflection.md``), so it
    # hands the run into ranking rather than back to the loop point.
    assert verification_events[0]["payload"]["successor"] == "ranking"


def _assert_fingerprints_survive_the_checkpoint(
    run_id: str, db_path: str
) -> None:
    """Every committed verification records what it was produced from.

    The durable path is the only one production takes, so a fingerprint
    missing here means no leader is ever recognized as current and deep
    verification re-runs on every cycle for the life of the run. It has to
    survive the checkpoint round-trip to be worth anything on resume.
    """
    from co_scientist.agents.reflection.deep_verification import (
        verification_fingerprint,
    )
    from co_scientist.models import Hypothesis

    latest = store.get_latest_checkpoint(run_id, db_path=db_path)
    assert latest is not None
    state = latest["state"]["state"]
    for payload in state["hypotheses"]:
        # Round-tripped through the checkpoint, not the in-memory object.
        hypothesis = Hypothesis.from_dict(payload)
        assert hypothesis.deep_verification_fingerprint == (
            verification_fingerprint(hypothesis, state["model_name"])
        )


@pytest.mark.asyncio
async def test_verification_children_commit_through_single_aggregator(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verification results update state only at the aggregate boundary."""
    run = store.create_run("Task-level science", "standard", "engine", {})
    await _advance_verification_node(run.id, monkeypatch, isolated_db)

    import co_scientist.agents.reflection.deep_verification as verification

    monkeypatch.setattr(verification, "_verify_one", _fake_verify)
    await _run_verification_children_and_aggregate(run.id, isolated_db)

    _assert_verification_committed(run.id, isolated_db)
    _assert_fingerprints_survive_the_checkpoint(run.id, isolated_db)
    _assert_verifications_are_marked_once_ever(run.id, isolated_db)


@pytest.mark.asyncio
async def test_verification_aggregate_pauses_and_resumes_to_ranking(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Leased verifier aggregate retains evidence and the ranking successor."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)

    with make_client() as client:
        created = client.post(
            "/api/runs", json={"research_goal": "Paused verification aggregate"}
        )
        assert created.status_code == 200, created.text
        run_id = str(created.json()["id"])
        store.update_run_status(
            run_id, store.RunStatus.RUNNING, db_path=isolated_db
        )
        await _advance_verification_node(run_id, monkeypatch, isolated_db)
        checkpoint_before = store.get_latest_checkpoint(
            run_id, db_path=isolated_db
        )
        assert checkpoint_before is not None
        import co_scientist.agents.reflection.deep_verification as verification

        monkeypatch.setattr(verification, "_verify_one", _fake_verify)

        def pause() -> None:
            response = client.post(f"/api/runs/{run_id}/pause")
            assert response.status_code == 200, response.text

        await _run_verification_children_and_aggregate(
            run_id, isolated_db, before_aggregate=pause
        )

        checkpoint = store.get_latest_checkpoint(run_id, db_path=isolated_db)
        assert checkpoint is not None
        assert checkpoint["seq"] == checkpoint_before["seq"] + 1
        saved_run = store.get_run(run_id, db_path=isolated_db)
        assert saved_run is not None and saved_run.status == "paused"
        state = checkpoint["state"]["state"]
        assert all(
            hypothesis["deep_verification_verdict"] == "holds"
            for hypothesis in state["hypotheses"]
        )
        assert state["articles"][-1]["source_id"] == "probe-1"
        metrics = store.get_run_metrics(run_id, db_path=isolated_db)
        assert metrics is not None and metrics["llm_calls"] == 6
        verification_items = [
            task
            for task in store.list_tasks(run_id, db_path=isolated_db)
            if task.task_type == engine_tasks.VERIFICATION_ITEM_TASK
        ]
        assert len(verification_items) == 3
        assert all(
            task.status == "completed" and task.result
            for task in verification_items
        )
        [event] = _task_events(run_id, "deep_verification", db_path=isolated_db)
        assert event["payload"]["successor"] == "ranking"
        ranking_tasks = [
            task
            for task in store.list_tasks(run_id, db_path=isolated_db)
            if task.task_type == f"{engine_tasks.NODE_TASK_PREFIX}ranking"
        ]
        assert len(ranking_tasks) == 1
        assert (
            store.claim_task(
                "before-resume", run_id=run_id, db_path=isolated_db
            )
            is None
        )

        resumed = client.post(f"/api/runs/{run_id}/resume")
        assert resumed.status_code == 200, resumed.text
        successor = store.claim_task(
            "after-resume", run_id=run_id, db_path=isolated_db
        )
        assert successor is not None
        assert successor.task_type == f"{engine_tasks.NODE_TASK_PREFIX}ranking"


@pytest.mark.asyncio
async def test_failed_verification_items_record_explicit_unverified(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider failure fails closed at the aggregate boundary (audit E9).

    Errored verification items must not leave their ideas merely untouched
    -- that read as an implicit pass. The aggregate stamps the explicit
    ``unverified`` verdict, keeps the fingerprints stale so nothing reads
    a failure as a stored verdict, and the ideas remain rankable. The
    attempt is still spent: the once-ever marker is written for a failed
    item too, so the next cycle does not re-fund the whole population the
    verifier just failed on.
    """
    run = store.create_run("Task-level science", "standard", "engine", {})
    await _advance_verification_node(run.id, monkeypatch, isolated_db)

    for index in range(3):
        item = store.claim_task(
            f"child-{index}", run_id=run.id, db_path=isolated_db
        )
        assert item is not None
        assert store.fail_task(
            item.id,
            f"child-{index}",
            "provider failed",
            retryable=False,
            db_path=isolated_db,
        )

    aggregate = store.claim_task(
        "aggregate", run_id=run.id, db_path=isolated_db
    )
    assert aggregate is not None
    result = await engine_tasks.execute_verification_aggregate(
        aggregate, db_path=isolated_db
    )
    assert result["successful_verifications"] == 0
    assert result["failed_verifications"] == 3
    assert store.complete_task(
        aggregate.id, "aggregate", result, db_path=isolated_db
    )

    latest = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert latest is not None
    restored = latest["state"]["state"]["hypotheses"]
    assert all(
        item["deep_verification_verdict"] == "unverified" for item in restored
    )
    assert all(item["deep_verification_probes"] == [] for item in restored)
    # Stale fingerprints: nothing reads a failure as a stored verdict.
    assert all(
        item["deep_verification_fingerprint"] is None for item in restored
    )
    # But the attempt was spent, so the wave does not re-fire next cycle.
    assert all(
        item["enrichments"]["deep_verification_issued"] for item in restored
    )
