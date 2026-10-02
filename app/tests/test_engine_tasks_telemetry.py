"""Per-call telemetry attribution for fan-out items and ranking matches.

``co_scientist.llm.telemetry.scoped_telemetry`` has a single call site on
the plain node path (``task_runtime.execute_task_node``), which the durable
fan-out item tasks and ranking match tasks never go through -- they call
engine functions directly from app-side handlers. These tests pin that the
fan-out/ranking paths scope telemetry the same way and fold it back into
the committed run metrics, rather than silently dropping it.
"""

from typing import Any

import pytest
from co_scientist.llm import ModelCallStats, record_call
from co_scientist.models import Hypothesis, HypothesisReview

from app import engine_tasks, store
from app.engine_tasks import fanout_aggregates as engine_tasks_fanout_aggregates
from app.engine_tasks import fanout_items as engine_tasks_fanout_items
from app.engine_tasks import ranking as engine_tasks_ranking
from app.engine_tasks import support as engine_tasks_support
from tests._engine_tasks_helpers import (
    _Generator,
    _install_plain_fake_judge,
    _patch_generator,
    _RankingSeed,
    _run_ranking_node,
    _seed_checkpoint,
    _seed_ranking_node,
    _task_state,
)


async def _fake_review_with_telemetry(**kwargs: Any) -> HypothesisReview:
    """Stand in for review, recording telemetry the way a real call would."""
    record_call(
        "fixture-model",
        ModelCallStats(calls=1, prompt_tokens=20, completion_tokens=10),
    )
    return HypothesisReview(
        review_summary=f"reviewed {kwargs['hypothesis_text']}",
        scores={"scientific_soundness": 8, "novelty": 8},
        safety_ethical_concerns="none",
        detailed_feedback={},
        constructive_feedback="continue",
        overall_score=8.0,
    )


async def _advance_review_node(
    run_id: str, monkeypatch: pytest.MonkeyPatch, db_path: str
) -> None:
    """Seed a two-hypothesis review node and fan it out."""
    state = _task_state(run_id)
    state["hypotheses"] = [Hypothesis(text="alpha"), Hypothesis(text="beta")]
    checkpoint_seq = _seed_checkpoint(run_id, state)
    node = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}review",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key="review-node",
        ),
        db_path=db_path,
    )
    _patch_generator(monkeypatch, _Generator(state), restore=True)
    leased = store.claim_task("node", run_id=run_id, db_path=db_path)
    assert leased is not None and leased.id == node.id
    result = await engine_tasks.execute_node_task(leased, db_path=db_path)
    assert store.complete_task(leased.id, "node", result, db_path=db_path)


@pytest.mark.asyncio
async def test_review_fanout_folds_item_telemetry_into_committed_metrics(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Telemetry captured inside a review item survives to the aggregate.

    Every completed review item records one call via
    ``llm.telemetry.record_call``; the aggregate must fold both items'
    usage into the checkpoint's ``metrics.model_usage`` rather than
    dropping it, the way the plain node path already does for
    ``task_runtime.execute_task_node``.
    """
    run = store.create_run("Task-level science", "standard", "engine", {})
    await _advance_review_node(run.id, monkeypatch, isolated_db)

    import co_scientist.agents.reflection.review as review_module

    monkeypatch.setattr(
        review_module, "review_single_hypothesis", _fake_review_with_telemetry
    )
    first = store.claim_task("child-a", run_id=run.id, db_path=isolated_db)
    second = store.claim_task("child-b", run_id=run.id, db_path=isolated_db)
    assert first is not None and second is not None
    first_result = await engine_tasks_fanout_items.execute_review_item(
        first, db_path=isolated_db
    )
    second_result = await engine_tasks_fanout_items.execute_review_item(
        second, db_path=isolated_db
    )
    assert first_result["model_usage"] == {
        "review::fixture-model": ModelCallStats(
            calls=1, prompt_tokens=20, completion_tokens=10
        ).as_dict()
    }
    assert store.complete_task(
        first.id, "child-a", first_result, db_path=isolated_db
    )
    assert store.complete_task(
        second.id, "child-b", second_result, db_path=isolated_db
    )

    aggregate = store.claim_task(
        "aggregate", run_id=run.id, db_path=isolated_db
    )
    assert aggregate is not None
    aggregate_result = (
        await engine_tasks_fanout_aggregates.execute_review_aggregate(
            aggregate, db_path=isolated_db
        )
    )
    assert store.complete_task(
        aggregate.id, "aggregate", aggregate_result, db_path=isolated_db
    )

    from co_scientist.checkpoint import restore_workflow_state

    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    restored = restore_workflow_state(checkpoint["state"])
    usage = restored["metrics"].model_usage["review::fixture-model"]
    assert usage["calls"] == 2
    assert usage["prompt_tokens"] == 40
    assert usage["completion_tokens"] == 20


async def _fake_judge_with_telemetry(
    *_: Any, **kwargs: Any
) -> tuple[str, dict[str, Any]]:
    """Stand in for the ranking judge, recording telemetry per matchup."""
    record_call("fixture-model", ModelCallStats(calls=1, prompt_tokens=5))
    return "a", {
        "decision_summary": "A is stronger",
        "confidence_level": "high",
        "debate_turns": int(kwargs["debate_turns"]),
        "debate_transcript": [],
        "judge_model": "fixture-model",
    }


async def _drain_and_finalize_ranking(run_id: str, db_path: str) -> int:
    """Run every match task, then the finalizer; return matches judged."""
    matches = 0
    while True:
        task = store.claim_task(
            f"match-{matches}", run_id=run_id, db_path=db_path
        )
        assert task is not None
        if task.task_type != engine_tasks_support.RANKING_MATCH_TASK:
            break
        result = await engine_tasks_ranking.execute_ranking_match(
            task, db_path=db_path
        )
        assert store.complete_task(
            task.id, f"match-{matches}", result, db_path=db_path
        )
        matches += 1
    assert task.task_type == engine_tasks_support.RANKING_FINALIZE_TASK
    result = await engine_tasks_ranking.execute_ranking_finalize(
        task, db_path=db_path
    )
    assert store.complete_task(
        task.id, f"match-{matches}", result, db_path=db_path
    )
    return matches


@pytest.mark.asyncio
async def test_ranking_matches_fold_telemetry_into_finalized_metrics(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Telemetry from every sequential match survives to the tournament's end.

    No intervening match commit persists a metrics snapshot (each uses
    ``_save_state_and_enqueue_exact``, finding L14's exception) -- the
    running usage has to ride the successor task's inputs the same way
    ``total_llm_calls`` already does, and land in the checkpoint only at
    ``execute_ranking_finalize``.
    """
    run = store.create_run("Task-level science", "standard", "engine", {})
    _seed_ranking_node(
        run.id,
        monkeypatch,
        _RankingSeed(
            hypothesis_count=4,
            tournament_pairs=8,
            idempotency_key="telemetry-ranking-node",
        ),
        isolated_db,
    )
    import co_scientist.agents.ranking.operations as ranking_module

    monkeypatch.setattr(
        ranking_module, "judge_matchup", _fake_judge_with_telemetry
    )

    # A wave judges several matchups per durable match task, and a small
    # pool exhausts its distinct pairings before the round budget (the same
    # dedup as the "one pair" fix), so neither the requested round budget
    # nor the number of drained match tasks is the matchup count -- only
    # the committed tournament_matchups tally is.
    await _run_ranking_node(run.id, isolated_db)
    await _drain_and_finalize_ranking(run.id, isolated_db)

    from co_scientist.checkpoint import restore_workflow_state

    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    restored = restore_workflow_state(checkpoint["state"])
    played = len(restored["tournament_matchups"])
    assert played > 1, "fixture must judge more than one matchup"
    usage = restored["metrics"].model_usage["ranking::fixture-model"]
    assert usage["calls"] == played
    assert usage["prompt_tokens"] == played * 5


@pytest.mark.asyncio
async def test_baseline_fake_judge_leaves_no_telemetry(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sanity check: a judge that never calls ``record_call`` leaves none.

    Pins that the ``ranking::`` usage key only appears when a call is
    actually recorded, so the prior test's presence assertion is
    meaningful rather than an artifact of some other node's usage.
    """
    run = store.create_run("Task-level science", "standard", "engine", {})
    _seed_ranking_node(
        run.id,
        monkeypatch,
        _RankingSeed(
            hypothesis_count=4,
            tournament_pairs=8,
            idempotency_key="baseline-ranking-node",
        ),
        isolated_db,
    )
    _install_plain_fake_judge(monkeypatch)

    await _run_ranking_node(run.id, isolated_db)
    await _drain_and_finalize_ranking(run.id, isolated_db)

    from co_scientist.checkpoint import restore_workflow_state

    checkpoint = store.get_latest_checkpoint(run.id, db_path=isolated_db)
    assert checkpoint is not None
    restored = restore_workflow_state(checkpoint["state"])
    assert not any(
        key.startswith("ranking::") for key in restored["metrics"].model_usage
    )
