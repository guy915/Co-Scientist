from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import pytest
from co_scientist.models import (
    ExecutionMetrics,
    Hypothesis,
    HypothesisReview,
)

from app import engine_tasks
from app.engine_tasks import ranking as engine_tasks_ranking
from app.engine_tasks import runtime as engine_tasks_runtime
from app.engine_tasks import support as engine_tasks_support
from app.engine_tasks.runtime import ProductionEngineTaskRuntime
from app.store import checkpoints, events, messages, runs, tasks
from app.store import tasks_lifecycle as lifecycle
from app.store.checkpoints import NewCheckpoint
from app.store.models import ScientificTask
from app.store.tasks import NewTask

from ._llm_fake_backend import load_engine_fake


def _task_state(run_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "research_goal": "Task-level science",
        "model_name": "fixture",
        "supervisor_model_name": "fixture",
        "hypotheses": [],
        "articles": [],
        "messages": [],
        "metrics": ExecutionMetrics(),
        "mcp_available": False,
        "current_iteration": 0,
        "start_time": time.time(),
    }


def _seed_checkpoint(
    run_id: str,
    state: dict[str, Any],
    *,
    stage: str = "fixture",
    db_path: str | None = None,
) -> int:
    from co_scientist.checkpoint import (
        CHECKPOINT_VERSION,
        serialize_workflow_state,
    )

    envelope = serialize_workflow_state(state, last_event_seq=0)
    return checkpoints.save_checkpoint(
        run_id,
        NewCheckpoint(
            stage=stage,
            schema_version=CHECKPOINT_VERSION,
            last_event_seq=0,
            state={"provider": "engine", **envelope},
        ),
        db_path=db_path,
    )


class _Generator:
    tool_registry = None

    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    async def prepare_task_state(self, *_: Any, **__: Any) -> dict[str, Any]:
        return self.state


async def _deterministic_screen(
    _run_id: str, subject: Any, *_: Any, **__: Any
) -> Any:
    return subject.deterministic


class FakeEngineTaskRuntime:
    # Start from production collaborators so each test replaces only the seams
    # it declares.

    def __init__(self) -> None:
        self.production = ProductionEngineTaskRuntime()
        self.generator_and_opts: Callable[..., tuple[Any, dict[str, Any]]] = (
            self.production.generator_and_opts
        )
        self.generator_for_restore: Callable[..., Any] = (
            self.production.generator_for_restore
        )
        self.screen: Callable[..., Awaitable[Any]] = self.production.screen
        self.drain_final_state: Callable[..., Awaitable[Any]] = (
            self.production.drain_final_state
        )


def _install_runtime(monkeypatch: pytest.MonkeyPatch) -> FakeEngineTaskRuntime:
    installed = engine_tasks_runtime._installed
    if isinstance(installed, FakeEngineTaskRuntime):
        return installed
    runtime = FakeEngineTaskRuntime()
    monkeypatch.setattr(engine_tasks_runtime, "_installed", runtime)
    return runtime


def _patch_restore_generator(
    monkeypatch: pytest.MonkeyPatch, generator: _Generator
) -> None:
    _install_runtime(monkeypatch).generator_for_restore = lambda *_: generator


def _patch_generator(
    monkeypatch: pytest.MonkeyPatch,
    generator: Any,
    *,
    restore: bool = False,
    screen: bool = False,
) -> None:
    runtime = _install_runtime(monkeypatch)
    runtime.generator_and_opts = lambda *_: (generator, {})
    if restore:
        _patch_restore_generator(monkeypatch, generator)
    if screen:
        runtime.screen = _deterministic_screen


def _patch_task_node(monkeypatch: pytest.MonkeyPatch, execute: Any) -> None:
    import co_scientist.task_runtime as runtime

    monkeypatch.setattr(runtime, "execute_task_node", execute)


def _milestones(run_id: str, *, db_path: str | None = None) -> list[str]:
    return [
        message.content
        for message in messages.list_messages(run_id, db_path=db_path)
        if message.kind == "milestone"
    ]


def _task_events(
    run_id: str, task: str, *, db_path: str | None = None
) -> list[dict[str, Any]]:
    return [
        event
        for event in events.list_events(run_id, db_path=db_path)
        if event["payload"].get("task") == task
    ]


def _add_fixture_review(hypothesis: Hypothesis) -> Hypothesis:
    # Tournament fixtures require peer review as well as rankability, just like
    # real admitted pools.
    hypothesis.reviews.append(
        HypothesisReview(
            review_summary="fixture review",
            scores={},
            safety_ethical_concerns="",
            detailed_feedback={},
            constructive_feedback="",
            overall_score=8.0,
        )
    )
    return hypothesis


def _viable_hypotheses(count: int, played: bool = False) -> list[Hypothesis]:
    # Budget-exhaustion fixtures must mark pools played because unmatched ideas
    # are still owed a first match.
    text = "Mechanism {i} accelerates ATP recovery."
    hypotheses = [
        Hypothesis(text=text.format(i=i), literature_grounding=text.format(i=i))
        for i in range(count)
    ]
    for hypothesis in hypotheses:
        hypothesis.review_disposition = "viable"
        _add_fixture_review(hypothesis)
        if played:
            hypothesis.win_count = 1
            hypothesis.loss_count = 1
    return hypotheses


@dataclass(frozen=True)
class _RankingSeed:
    hypothesis_count: int
    tournament_pairs: int
    idempotency_key: str
    consumed_rounds: int = 0
    played: bool = False
    criteria: list[str] | None = None
    preferences: str | None = None


def _seed_ranking_node(
    run_id: str,
    monkeypatch: pytest.MonkeyPatch,
    seed: _RankingSeed,
    db_path: str,
) -> None:
    state = _task_state(run_id)
    state.update(
        {
            "hypotheses": _viable_hypotheses(
                seed.hypothesis_count, played=seed.played
            ),
            "tournament_pairs": seed.tournament_pairs,
            "metrics": ExecutionMetrics(tournaments_count=seed.consumed_rounds),
            "criteria": seed.criteria,
            "preferences": seed.preferences,
        }
    )
    checkpoint_seq = _seed_checkpoint(run_id, state)
    tasks.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}ranking",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=seed.idempotency_key,
        ),
        db_path=db_path,
    )
    _patch_generator(monkeypatch, _Generator(state), restore=True)


def _install_plain_fake_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    import co_scientist.agents.ranking.operations as ranking_module

    async def fake_judge(*_: Any, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        return "a", {
            "decision_summary": "A is stronger",
            "confidence_level": "high",
            "debate_turns": int(kwargs["debate_turns"]),
            "debate_transcript": [],
            "judge_model": "fixture",
        }

    monkeypatch.setattr(ranking_module, "judge_matchup", fake_judge)


def _install_concurrency_tracking_judge(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, int]:
    import co_scientist.agents.ranking.operations as ranking_module

    box = {"in_flight": 0, "peak": 0}

    async def fake_judge(*_: Any, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        box["in_flight"] += 1
        box["peak"] = max(box["peak"], box["in_flight"])
        await asyncio.sleep(0)
        box["in_flight"] -= 1
        return "a", {
            "decision_summary": "A is stronger",
            "confidence_level": "high",
            "debate_turns": int(kwargs["debate_turns"]),
            "debate_transcript": [],
            "judge_model": "fixture",
        }

    monkeypatch.setattr(ranking_module, "judge_matchup", fake_judge)
    return box


async def _run_ranking_node(run_id: str, db_path: str) -> dict[str, Any]:
    leased = tasks.claim_task("ranking", run_id=run_id, db_path=db_path)
    assert leased is not None
    scheduled = await engine_tasks.execute_node_task(leased, db_path=db_path)
    assert lifecycle.complete_task(
        leased.id, "ranking", scheduled, db_path=db_path
    )
    return scheduled


async def _drain_ranking_matches(run_id: str, db_path: str) -> int:
    matches = 0
    while True:
        match = tasks.claim_task(
            f"match-{matches}", run_id=run_id, db_path=db_path
        )
        assert match is not None
        if match.task_type != engine_tasks_support.RANKING_MATCH_TASK:
            break
        result = await engine_tasks_ranking.execute_ranking_match(
            match, db_path=db_path
        )
        assert lifecycle.complete_task(
            match.id, f"match-{matches}", result, db_path=db_path
        )
        matches += 1
    return matches


def _running_ranking_events(run_id: str, db_path: str) -> list[dict[str, Any]]:
    return [
        e
        for e in events.list_events(run_id, db_path=db_path)
        if e["payload"].get("task") == "ranking"
        and e["payload"].get("status") == "running"
    ]


def _run() -> str:
    return runs.create_run("queue goal", "standard", "engine", {}).id


def _enqueue(
    run_id: str, task_type: str, key: str, db: str, **kwargs: Any
) -> Any:
    return tasks.enqueue_task(
        NewTask(
            run_id=run_id,
            task_type=task_type,
            inputs={},
            idempotency_key=key,
            **kwargs,
        ),
        db_path=db,
    )


def _three_control_tasks(run_id: str, db: str) -> tuple[str, str, str]:
    promoted = _enqueue(
        run_id, "reflection.full", "control:promote", db, priority=1
    )
    cancelled = _enqueue(
        run_id, "generation.assumptions", "control:cancel", db, priority=2
    )
    failed = _enqueue(
        run_id,
        "verification.deep",
        "control:retry",
        db,
        priority=100,
        max_attempts=1,
    )
    leased = tasks.claim_task("failed-worker", run_id=run_id, db_path=db)
    assert leased is not None and leased.id == failed.id
    assert tasks.fail_task(
        failed.id,
        "failed-worker",
        "transient provider error",
        retryable=False,
        db_path=db,
    )
    return promoted.id, cancelled.id, failed.id


def make_cancellable_executor(
    started: asyncio.Event, interrupted: asyncio.Event
) -> Callable[..., Awaitable[dict[str, bool]]]:

    async def _execute(
        _task: ScientificTask, *, db_path: str | None = None
    ) -> dict[str, bool]:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            interrupted.set()
            raise
        return {"completed": True}

    return _execute


def _install_fake_engine_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    load_engine_fake().install_fake_llm(monkeypatch)
    monkeypatch.setenv("FORCE_LITERATURE_REVIEW", "0")
    from app.config import settings

    monkeypatch.setattr(settings, "semantic_safety_enabled", False)
