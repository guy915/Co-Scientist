"""Pause and resume at durable ranking task boundaries."""

from typing import Any, cast

import pytest

from app import engine_tasks, store
from app.config import settings
from app.engine_tasks import ranking as engine_tasks_ranking
from app.engine_tasks import support as engine_tasks_support
from tests._client import make_client
from tests._engine_tasks_helpers import (
    _install_plain_fake_judge,
    _RankingSeed,
    _run_ranking_node,
    _seed_ranking_node,
)

_OWNER = {"X-Client-ID": "ranking-pause-owner"}


def _owned_running_run(db_path: str) -> tuple[Any, str]:
    client = make_client()
    created = client.post(
        "/api/runs",
        headers=_OWNER,
        json={
            "research_goal": "Pause during a durable ranking match",
            "tier": "standard",
        },
    )
    assert created.status_code == 200, created.text
    run_id = str(created.json()["id"])
    store.update_run_status(run_id, store.RunStatus.RUNNING, db_path=db_path)
    return client, run_id


@pytest.mark.asyncio
async def test_paused_ranking_match_resumes_its_exact_successor(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A leased match commits under pause; resume leases its exact successor."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client, run_id = _owned_running_run(isolated_db)
    _seed_ranking_node(
        run_id,
        monkeypatch,
        _RankingSeed(
            hypothesis_count=4,
            tournament_pairs=12,
            idempotency_key="pause-ranking-node",
        ),
        isolated_db,
    )
    scheduled = await _run_ranking_node(run_id, isolated_db)

    import co_scientist.agents.ranking.ranking as ranking_module

    paused = False

    async def pause_during_judging(
        *_: Any, **kwargs: Any
    ) -> tuple[str, dict[str, Any]]:
        nonlocal paused
        if not paused:
            unauthorized = client.post(
                f"/api/runs/{run_id}/pause",
                headers={"X-Client-ID": "ranking-pause-other-owner"},
            )
            assert unauthorized.status_code == 404
            still_running = store.get_run(run_id, db_path=isolated_db)
            assert still_running is not None
            assert still_running.status == store.RunStatus.RUNNING.value
            response = client.post(f"/api/runs/{run_id}/pause", headers=_OWNER)
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "paused"
            paused = True
        return "a", {
            "decision_summary": "A is stronger",
            "confidence_level": "high",
            "debate_turns": int(kwargs["debate_turns"]),
            "debate_transcript": [],
            "judge_model": "fixture",
        }

    monkeypatch.setattr(ranking_module, "judge_matchup", pause_during_judging)
    match = store.claim_task(
        "ranking-match", run_id=run_id, db_path=isolated_db
    )
    assert match is not None
    assert match.task_type == engine_tasks_support.RANKING_MATCH_TASK
    result = await engine_tasks_ranking.execute_ranking_match(
        match, db_path=isolated_db
    )
    assert paused
    assert store.complete_task(
        match.id, "ranking-match", result, db_path=isolated_db
    )

    checkpoint = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    assert checkpoint["seq"] == int(scheduled["checkpoint_seq"]) + 1
    assert checkpoint["stage"] == f"engine_task:{match.id}"
    from co_scientist.checkpoint import restore_workflow_state

    state = restore_workflow_state(checkpoint["state"])
    details = state["pending_ranking_matchups"]
    assert len(details) == result["matches_committed"] == 6
    assert (
        sum(hypothesis.total_matches for hypothesis in state["hypotheses"])
        == 12
    )
    assert any(
        hypothesis.elo_rating != 1200 for hypothesis in state["hypotheses"]
    )

    successor = store.get_task(result["successor_task_id"], db_path=isolated_db)
    assert successor is not None
    assert successor.task_type == engine_tasks_support.RANKING_MATCH_TASK
    assert successor.status == "queued"
    assert successor.inputs["checkpoint_seq"] == checkpoint["seq"]
    assert successor.dependencies == (match.id,)
    assert (
        successor.provenance["scheduled_by"]
        == engine_tasks_support.RANKING_MATCH_TASK
    )
    paused_run = store.get_run(run_id, db_path=isolated_db)
    assert paused_run is not None
    assert paused_run.status == store.RunStatus.PAUSED.value
    assert (
        store.claim_task("before-resume", run_id=run_id, db_path=isolated_db)
        is None
    )

    events = store.list_events(run_id, db_path=isolated_db)
    pause_event = next(
        event
        for event in events
        if event["type"] == "lifecycle"
        and event["payload"].get("event") == "pause_requested"
    )
    assert not any(
        event["type"] == "scientific_task"
        and event["payload"].get("task") == "ranking"
        and event["payload"].get("status") == "running"
        and event["seq"] > pause_event["seq"]
        for event in events
    )

    resumed = client.post(f"/api/runs/{run_id}/resume", headers=_OWNER)
    assert resumed.status_code == 200, resumed.text
    resumed_task = store.get_task(successor.id, db_path=isolated_db)
    assert resumed_task is not None and resumed_task.status == "queued"
    claim = store.claim_task("after-resume", run_id=run_id, db_path=isolated_db)
    assert claim is not None
    assert claim.id == successor.id
    assert claim.task_type == engine_tasks_support.RANKING_MATCH_TASK


@pytest.mark.asyncio
async def test_paused_ranking_finalize_keeps_elo_metrics_and_exact_resume(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finalize commits ranking once; resume claims its recorded successor."""
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client, run_id = _owned_running_run(isolated_db)
    _seed_ranking_node(
        run_id,
        monkeypatch,
        _RankingSeed(
            hypothesis_count=4,
            tournament_pairs=12,
            idempotency_key="pause-ranking-finalize-node",
        ),
        isolated_db,
    )
    await _run_ranking_node(run_id, isolated_db)
    _install_plain_fake_judge(monkeypatch)

    while True:
        match = store.claim_task(
            "ranking-match", run_id=run_id, db_path=isolated_db
        )
        assert match is not None
        if match.task_type == engine_tasks_support.RANKING_FINALIZE_TASK:
            finalizer = match
            break
        assert match.task_type == engine_tasks_support.RANKING_MATCH_TASK
        result = await engine_tasks_ranking.execute_ranking_match(
            match, db_path=isolated_db
        )
        assert store.complete_task(
            match.id, "ranking-match", result, db_path=isolated_db
        )

    import co_scientist.agents.ranking.ranking as ranking_module

    finalize_ranking = ranking_module._finalize_ranking_result

    async def pause_after_finalize(*args: Any, **kwargs: Any) -> dict[str, Any]:
        update = await finalize_ranking(*args, **kwargs)
        response = client.post(f"/api/runs/{run_id}/pause", headers=_OWNER)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "paused"
        return cast(dict[str, Any], update)

    monkeypatch.setattr(
        ranking_module, "_finalize_ranking_result", pause_after_finalize
    )
    result = await engine_tasks_ranking.execute_ranking_finalize(
        finalizer, db_path=isolated_db
    )
    assert store.complete_task(
        finalizer.id, "ranking-match", result, db_path=isolated_db
    )

    checkpoint = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    assert checkpoint["seq"] == int(finalizer.inputs["checkpoint_seq"]) + 1
    assert checkpoint["stage"] == f"engine_task:{finalizer.id}"
    from co_scientist.checkpoint import restore_workflow_state

    state = restore_workflow_state(checkpoint["state"])
    details = state["tournament_matchups"]
    assert len(details) == result["matches_committed"] == 6
    assert not state.get("pending_ranking_matchups")
    assert (
        sum(hypothesis.total_matches for hypothesis in state["hypotheses"])
        == 12
    )
    assert any(
        hypothesis.elo_rating != 1200 for hypothesis in state["hypotheses"]
    )
    metrics = store.get_run_metrics(run_id, db_path=isolated_db)
    assert metrics is not None
    assert metrics["tournaments_count"] == len(details)
    assert metrics["llm_calls"] == sum(
        int(detail["debate_turns"]) for detail in details
    )

    successor = store.get_task(result["successor_task_id"], db_path=isolated_db)
    assert successor is not None
    assert successor.task_type == f"{engine_tasks.NODE_TASK_PREFIX}orchestrator"
    assert successor.status == "queued"
    assert successor.dependencies == (finalizer.id,)
    assert (
        successor.provenance["scheduled_by"]
        == engine_tasks_support.RANKING_FINALIZE_TASK
    )
    assert checkpoint["state"]["resume_successor"] == successor.task_type
    paused_run = store.get_run(run_id, db_path=isolated_db)
    assert paused_run is not None
    assert paused_run.status == store.RunStatus.PAUSED.value
    assert (
        store.claim_task(
            "before-finalize-resume", run_id=run_id, db_path=isolated_db
        )
        is None
    )

    events = store.list_events(run_id, db_path=isolated_db)
    pause_event = next(
        event
        for event in events
        if event["type"] == "lifecycle"
        and event["payload"].get("event") == "pause_requested"
    )
    completion = next(
        event
        for event in events
        if event["type"] == "scientific_task"
        and event["payload"].get("task") == "ranking"
        and event["payload"].get("status") == "completed"
        and event["payload"].get("checkpoint_seq") == checkpoint["seq"]
    )
    assert completion["seq"] > pause_event["seq"]
    assert completion["payload"]["successor"] == "orchestrator"
    assert not any(
        event["type"] == "scientific_task"
        and event["payload"].get("task") == "ranking"
        and event["payload"].get("status") == "running"
        and event["seq"] > pause_event["seq"]
        for event in events
    )

    resumed = client.post(f"/api/runs/{run_id}/resume", headers=_OWNER)
    assert resumed.status_code == 200, resumed.text
    claim = store.claim_task(
        "after-finalize-resume", run_id=run_id, db_path=isolated_db
    )
    assert claim is not None
    assert claim.id == successor.id
    assert claim.task_type == successor.task_type
