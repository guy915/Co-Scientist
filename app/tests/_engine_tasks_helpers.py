"""Shared fixtures and stand-ins for the durable engine-task test suite.

Leading underscore so pytest does not collect this module. The split
``test_engine_tasks*.py`` files import these builders, which were extracted
verbatim from the original single ``test_engine_tasks.py``.
"""

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

from app import engine_tasks, store
from app.engine_tasks import runtime as engine_tasks_runtime
from app.engine_tasks.runtime import ProductionEngineTaskRuntime


def _task_state(run_id: str) -> dict[str, Any]:
    """Build the minimal serializable state used by task-runtime fixtures."""
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
    """Serialize ``state`` and commit it as an engine checkpoint, return seq."""
    from co_scientist.checkpoint import (
        CHECKPOINT_VERSION,
        serialize_workflow_state,
    )

    envelope = serialize_workflow_state(state, last_event_seq=0)
    return store.save_checkpoint(
        run_id,
        store.NewCheckpoint(
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
    """Stand in for the escalation with its deterministic verdict.

    Matches ``screen_with_escalation``'s signature (run id, then the
    ``ScreenSubject``) and returns what that wrapper returns for any run
    these tests create: the deterministic decision, with no contextual
    model call.
    """
    return subject.deterministic


class FakeEngineTaskRuntime:
    """Test adapter for ``app.engine_tasks.runtime``.

    Every slot starts as the production adapter's own, so a test replaces
    only the collaborators it states. ``screen`` serves both the intake gate
    and the final-report gate; the stand-ins here key on ``subject.stage``
    when a test needs only one of them. ``production`` is kept for a test
    that wraps or restores the real collaborator.
    """

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
    """Install the test adapter for this test, or return the one installed.

    The one place a test states which collaborators a durable task runs
    against, in place of patching each module that looks one up. Undone with
    the test.
    """
    installed = engine_tasks_runtime._installed
    if isinstance(installed, FakeEngineTaskRuntime):
        return installed
    runtime = FakeEngineTaskRuntime()
    monkeypatch.setattr(engine_tasks_runtime, "_installed", runtime)
    return runtime


def _patch_restore_generator(
    monkeypatch: pytest.MonkeyPatch, generator: _Generator
) -> None:
    """Make every restore site rebuild state with ``generator``."""
    _install_runtime(monkeypatch).generator_for_restore = lambda *_: generator


def _patch_generator(
    monkeypatch: pytest.MonkeyPatch,
    generator: Any,
    *,
    restore: bool = False,
    screen: bool = False,
) -> None:
    """Route the executor's generator seams at ``generator``.

    Installs the generator for a new run always, and optionally the restore
    generator and the deterministic screen -- the slots the durable-executor
    tests otherwise patch module by module.
    """
    runtime = _install_runtime(monkeypatch)
    runtime.generator_and_opts = lambda *_: (generator, {})
    if restore:
        _patch_restore_generator(monkeypatch, generator)
    if screen:
        runtime.screen = _deterministic_screen


def _patch_task_node(monkeypatch: pytest.MonkeyPatch, execute: Any) -> None:
    """Replace ``task_runtime.execute_task_node`` with a fixture coroutine."""
    import co_scientist.task_runtime as runtime

    monkeypatch.setattr(runtime, "execute_task_node", execute)


def _milestones(run_id: str, *, db_path: str | None = None) -> list[str]:
    """Return the run's milestone chat-message contents in commit order."""
    return [
        message.content
        for message in store.list_messages(run_id, db_path=db_path)
        if message.kind == "milestone"
    ]


def _task_events(
    run_id: str, task: str, *, db_path: str | None = None
) -> list[dict[str, Any]]:
    """Return the run's ``scientific_task`` events for one task name."""
    return [
        event
        for event in store.list_events(run_id, db_path=db_path)
        if event["payload"].get("task") == task
    ]


def _add_fixture_review(hypothesis: Hypothesis) -> Hypothesis:
    """Attach one agent-authored review so the hypothesis has peer review.

    ``_ranking_eligible`` (app.engine_tasks.ranking) requires
    ``has_peer_review`` alongside ``is_rankable`` (HITL-MANUAL-HYP-001's
    RANK-retry closure), so any fixture pool calling itself "viable" and
    ready to rank needs one, matching every real pool: nothing reaches
    ranking on the durable path without a review first.
    """
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
    """Build ``count`` reviewed-viable hypotheses for a tournament fixture.

    Args:
        count: How many hypotheses to build.
        played: Give each one a match record. The tournament round count
            owes a first match to any rankable hypothesis that has never
            played, so a fixture exercising budget exhaustion has to say
            that its pool already has.
    """
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
    """The shape of one seeded ranking-node fixture.

    Attributes:
        hypothesis_count: Reviewed-viable hypotheses to seed.
        tournament_pairs: Tournament pair budget put into state.
        idempotency_key: Key the queued ranking node task is enqueued under.
        consumed_rounds: Matches the run has already charged against the
            budget, as the accumulated run metric records them.
        played: Seed the pool as having already been matched, so the
            coverage floor is satisfied and the budget alone decides.
    """

    hypothesis_count: int
    tournament_pairs: int
    idempotency_key: str
    consumed_rounds: int = 0
    played: bool = False


def _seed_ranking_node(
    run_id: str,
    monkeypatch: pytest.MonkeyPatch,
    seed: _RankingSeed,
    db_path: str,
) -> None:
    """Seed a checkpoint + queued ranking node task and route the generator."""
    state = _task_state(run_id)
    state.update(
        {
            "hypotheses": _viable_hypotheses(
                seed.hypothesis_count, played=seed.played
            ),
            "tournament_pairs": seed.tournament_pairs,
            "metrics": ExecutionMetrics(tournaments_count=seed.consumed_rounds),
        }
    )
    checkpoint_seq = _seed_checkpoint(run_id, state)
    store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}ranking",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=seed.idempotency_key,
        ),
        db_path=db_path,
    )
    _patch_generator(monkeypatch, _Generator(state), restore=True)


def _install_plain_fake_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch ``judge_matchup`` with a deterministic 'A wins' verdict."""
    import co_scientist.agents.ranking.ranking as ranking_module

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
    """Patch ``judge_matchup`` to record peak concurrent judging.

    Returns a shared box whose ``peak`` key holds the greatest number of
    matchups judged simultaneously.
    """
    import co_scientist.agents.ranking.ranking as ranking_module

    box = {"in_flight": 0, "peak": 0}

    async def fake_judge(*_: Any, **kwargs: Any) -> tuple[str, dict[str, Any]]:
        box["in_flight"] += 1
        box["peak"] = max(box["peak"], box["in_flight"])
        await asyncio.sleep(0)  # Yield so siblings can overlap.
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
    """Lease, execute, and commit the queued ranking node; return its result."""
    leased = store.claim_task("ranking", run_id=run_id, db_path=db_path)
    assert leased is not None
    scheduled = await engine_tasks.execute_node_task(leased, db_path=db_path)
    assert store.complete_task(leased.id, "ranking", scheduled, db_path=db_path)
    return scheduled


async def _drain_ranking_matches(run_id: str, db_path: str) -> int:
    """Lease + execute every queued match task; return the number run."""
    matches = 0
    while True:
        match = store.claim_task(
            f"match-{matches}", run_id=run_id, db_path=db_path
        )
        assert match is not None
        if match.task_type != engine_tasks.RANKING_MATCH_TASK:
            break
        result = await engine_tasks.execute_ranking_match(
            match, db_path=db_path
        )
        assert store.complete_task(
            match.id, f"match-{matches}", result, db_path=db_path
        )
        matches += 1
    return matches


def _running_ranking_events(run_id: str, db_path: str) -> list[dict[str, Any]]:
    """Return the run's 'running'-status ranking progress events."""
    return [
        e
        for e in store.list_events(run_id, db_path=db_path)
        if e["payload"].get("task") == "ranking"
        and e["payload"].get("status") == "running"
    ]
