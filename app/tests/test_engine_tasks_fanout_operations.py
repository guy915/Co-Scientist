"""Durable adaptations of the public Reflection item operations."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from co_scientist.agents import reflection
from co_scientist.exceptions import (
    LLMCallBudgetExceededError,
    LLMRateLimitParkError,
)
from co_scientist.models import Hypothesis

from app.engine_tasks import fanout_items as items


def _restore_item(monkeypatch: pytest.MonkeyPatch, mode: str = "full") -> Any:
    idea = Hypothesis(id="idea", text="Scientific claim")
    state = {"hypotheses": [idea], "articles_with_reasoning": "Literature"}
    monkeypatch.setattr(
        items, "_restore_item_checkpoint", lambda *args, **kwargs: (state, 7)
    )
    return SimpleNamespace(
        inputs={"hypothesis_id": idea.id, "review_mode": mode}
    )


@pytest.mark.asyncio
async def test_verification_keeps_raw_payload_and_defers_issuance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _restore_item(monkeypatch)
    raw = {"verdict": "holds", "sub_assumptions": list(range(30))}
    operation = AsyncMock(return_value=raw)
    monkeypatch.setattr(reflection, "verify_hypothesis", operation)
    result = await items.execute_verification_item(task)
    assert result["verification"] is raw
    assert result["checkpoint_seq"] == 7
    assert operation.await_args is not None
    assert not operation.await_args.args[1].enrichments


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "executor,operation",
    [
        (items.execute_verification_item, "verify_hypothesis"),
        (items.execute_mature_reflection_item, "review_hypothesis"),
    ],
)
@pytest.mark.parametrize(
    "error",
    [LLMRateLimitParkError(9999, "cap"), LLMCallBudgetExceededError(2, 1)],
)
async def test_public_item_task_control_errors_reach_worker(
    monkeypatch: pytest.MonkeyPatch,
    executor: Any,
    operation: str,
    error: Exception,
) -> None:
    task = _restore_item(monkeypatch)
    monkeypatch.setattr(reflection, operation, AsyncMock(side_effect=error))
    with pytest.raises(type(error)) as caught:
        await executor(task)
    assert caught.value is error


@pytest.mark.asyncio
async def test_verification_none_becomes_durable_item_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _restore_item(monkeypatch)
    monkeypatch.setattr(
        reflection, "verify_hypothesis", AsyncMock(return_value=None)
    )
    with pytest.raises(RuntimeError, match="deep verification failed for idea"):
        await items.execute_verification_item(task)


@pytest.mark.asyncio
async def test_observation_rejects_missing_literature_before_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operation = AsyncMock()
    monkeypatch.setattr(reflection, "observe_hypothesis", operation)
    with pytest.raises(RuntimeError, match="no literature context"):
        await items._run_observation_reflection({}, Hypothesis(text="claim"))
    operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_durable_observation_uses_single_item_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    indices: list[tuple[int, int]] = []

    async def observe(
        state: Any,
        hypothesis: Any,
        *,
        hypothesis_index: int = 1,
        total_count: int = 1,
    ) -> dict[str, Any]:
        indices.append((hypothesis_index, total_count))
        return {"classification": "neutral"}

    task = _restore_item(monkeypatch, "observation")
    monkeypatch.setattr(reflection, "observe_hypothesis", observe)
    result = await items.execute_mature_reflection_item(task)
    assert result["review"] == {"classification": "neutral"}
    assert result["research_ledger"] is None
    assert indices == [(1, 1)]


@pytest.mark.asyncio
async def test_durable_mature_review_keeps_ledger_beside_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _restore_item(monkeypatch)
    review, ledger = {"verdict": "sound"}, {"threads": 4}
    monkeypatch.setattr(
        reflection,
        "review_hypothesis",
        AsyncMock(
            return_value=reflection.ReviewRun(
                reflection.ReviewType.FULL, review, ledger
            )
        ),
    )
    result = await items.execute_mature_reflection_item(task)
    assert result["review"] is review
    assert result["research_ledger"] is ledger
    assert "research_ledger" not in result["review"]
