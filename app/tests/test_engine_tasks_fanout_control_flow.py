"""A parked or over-budget review must reach the worker, not the fan-out.

Production run bc77950f (extended tier): the free model chain hit its
per-day cap. The ranking node parked as designed, while eleven
``engine.fanout.reflection.item`` tasks failed permanently at attempt 3/3
-- the review swallowed the park, returned no review, and this executor
reported that as a plain ``RuntimeError``, which the worker treats as a
transient hiccup worth three attempts against a cap that had not reset.

``task_worker.outcomes`` is what decides both outcomes; these tests pin
that the exception types it dispatches on actually arrive there.
"""

from __future__ import annotations

from typing import Any

import pytest
from co_scientist.exceptions import (
    LLMCallBudgetExceededError,
    LLMRateLimitParkError,
)
from co_scientist.models import Hypothesis

from app import store
from app.engine_tasks import fanout_items as engine_tasks_fanout_items
from app.engine_tasks.support import MATURE_REFLECTION_ITEM_TASK
from tests._engine_tasks_helpers import (
    _Generator,
    _patch_generator,
    _seed_checkpoint,
    _task_state,
)

PARK = LLMRateLimitParkError(1788825600.0, "message_per_day")
OVER_BUDGET = LLMCallBudgetExceededError(2501, 2500)


def _seed_mature_review_item(
    run_id: str, monkeypatch: pytest.MonkeyPatch, db_path: str
) -> store.ScientificTask:
    """Enqueue and lease one full-review item over a one-hypothesis state."""
    state = _task_state(run_id)
    hypothesis = Hypothesis(text="a mechanism worth reviewing")
    hypothesis.review_disposition = "viable"
    state["hypotheses"] = [hypothesis]
    checkpoint_seq = _seed_checkpoint(run_id, state, db_path=db_path)
    store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=MATURE_REFLECTION_ITEM_TASK,
            inputs={
                "checkpoint_seq": checkpoint_seq,
                "hypothesis_id": hypothesis.id,
                "review_mode": "full",
            },
            idempotency_key="control-flow-item",
        ),
        db_path=db_path,
    )
    _patch_generator(monkeypatch, _Generator(state), restore=True)
    leased = store.claim_task("item", run_id=run_id, db_path=db_path)
    assert leased is not None
    return leased


def _install_failing_review(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """Fail the review's own provider call, inside the engine's handler.

    Injected at the LLM seam rather than at ``_run_review`` itself: the
    handler that swallowed the park in bc77950f is inside that function,
    so a stand-in for the whole function would prove nothing about it.
    Patched on the engine module because the executor imports the review
    inside its own body.
    """
    import co_scientist.agents.reflection.comprehensive_reflection as comp
    from co_scientist.agents.reflection.review_evidence import _ReviewEvidence

    async def _evidence(*_: Any, **__: Any) -> _ReviewEvidence:
        return _ReviewEvidence([], [], [], None)

    async def _observations(*_: Any, **__: Any) -> str | None:
        return None

    async def _call(*_: Any, **__: Any) -> dict[str, Any]:
        raise error

    monkeypatch.setattr(comp, "_review_evidence_for", _evidence)
    monkeypatch.setattr(comp, "_observations_for", _observations)
    monkeypatch.setattr(comp, "call_llm_json", _call)


@pytest.mark.parametrize("error", [PARK, OVER_BUDGET])
async def test_a_control_flow_error_leaves_the_item_unchanged(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """Its own type has to survive the executor, not become a RuntimeError.

    ``task_worker.outcomes`` dispatches on the type: a park returns the
    row to ``queued`` with its attempt undone, and the call-budget
    ceiling terminates the run. A ``RuntimeError`` gets neither.
    """
    run = store.create_run("Task-level science", "extended", "engine", {})
    leased = _seed_mature_review_item(run.id, monkeypatch, isolated_db)
    _install_failing_review(monkeypatch, error)

    with pytest.raises(type(error)):
        await engine_tasks_fanout_items.execute_mature_reflection_item(
            leased, db_path=isolated_db
        )


async def test_an_ordinary_provider_failure_is_still_a_retryable_failure(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A review that ran and answered nothing keeps its three attempts."""
    run = store.create_run("Task-level science", "extended", "engine", {})
    leased = _seed_mature_review_item(run.id, monkeypatch, isolated_db)
    _install_failing_review(monkeypatch, ValueError("unparseable answer"))

    with pytest.raises(RuntimeError):
        await engine_tasks_fanout_items.execute_mature_reflection_item(
            leased, db_path=isolated_db
        )


@pytest.mark.parametrize("error", [PARK, OVER_BUDGET])
def test_a_control_flow_error_escapes_the_ranking_wave(
    error: Exception,
) -> None:
    """The wave's gather collects exceptions, which swallows these too.

    Dropping a park here keeps judging the rest of the wave against a cap
    that has not reset, and commits a tournament round short of the
    matchups it was budgeted -- the same trade the reviews lost eleven
    items to.
    """
    from co_scientist.agents.ranking import RankingJudgement

    from app.engine_tasks.ranking_wave import _surviving_judgements

    verdict = RankingJudgement("a", {"decision_summary": "A is stronger"}, 2)

    with pytest.raises(type(error)):
        _surviving_judgements(["pair-0", "pair-1"], [verdict, error])


def test_an_ordinary_judge_failure_still_leaves_its_wave_siblings() -> None:
    """Per-matchup isolation is unchanged for an ordinary failure."""
    from co_scientist.agents.ranking import RankingJudgement

    from app.engine_tasks.ranking_wave import _surviving_judgements

    verdict = RankingJudgement("a", {"decision_summary": "A is stronger"}, 2)

    survived = _surviving_judgements(
        ["pair-0", "pair-1"], [verdict, RuntimeError("judge refused")]
    )

    assert survived.pairs == ["pair-0"]
    assert survived.judgements == [verdict]
