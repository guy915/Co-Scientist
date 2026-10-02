"""Contracts for scientific Reflection operations used by both paths."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.reflection import (
    ReviewRun,
    ReviewType,
    apply_initial_review_gate,
    has_valid_verification,
    observe_hypothesis,
    review_hypothesis,
    select_hypotheses_to_verify,
    verify_hypothesis,
)
from co_scientist.agents.reflection import comprehensive_reflection as cr
from co_scientist.agents.reflection import deep_verification as dv
from co_scientist.agents.reflection import reflection as observation
from co_scientist.agents.reflection import verification as leaf
from co_scientist.agents.reflection.review_evidence import _ReviewEvidence
from co_scientist.agents.reflection.verification_freshness import (
    mark_verification_issued,
    verification_fingerprint,
)
from co_scientist.exceptions import (
    LLMCallBudgetExceededError,
    LLMRateLimitParkError,
)
from tests._state import make_article, make_hypothesis, make_review, make_state


def test_gate_honors_scientist_criteria_and_safety() -> None:
    ideas = [make_hypothesis(), make_hypothesis()]
    reviews = [
        make_review(scores={"novelty": 1, "testability": 8, "safety": 8}),
        make_review(scores={"testability": 8, "safety": 1}),
    ]
    apply_initial_review_gate(ideas, reviews, ["Experimental feasibility"])
    assert [idea.review_disposition for idea in ideas] == ["viable", "unsafe"]


def test_selection_preserves_pool_order_and_once_ever_markers() -> None:
    pending = make_hypothesis()
    blocked = make_hypothesis(review_disposition="unsafe")
    issued = make_hypothesis()
    mark_verification_issued(issued)
    current = make_hypothesis()
    current.deep_verification_fingerprint = verification_fingerprint(
        current, "m"
    )
    next_pending = make_hypothesis()
    assert select_hypotheses_to_verify(
        [pending, blocked, issued, current, next_pending], "m"
    ) == [pending, next_pending]
    assert not pending.enrichments


@pytest.mark.parametrize(
    "result",
    [
        None,
        {},
        {"verdict": None},
        {"verdict": "unverified"},
        {"verdict": "unknown"},
        {"verdict": []},
        {"verdict": {}},
    ],
)
def test_invalid_verification(result: dict[str, Any] | None) -> None:
    assert not has_valid_verification(result)


@pytest.mark.parametrize("verdict", ["holds", "weakened", "undermined"])
def test_valid_verification(verdict: str) -> None:
    assert has_valid_verification({"verdict": verdict})


@pytest.mark.asyncio
async def test_single_verification_assembles_bounded_context_and_local_limiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    semaphores: list[asyncio.Semaphore] = []
    contexts: list[str] = []

    async def capture(
        semaphore: asyncio.Semaphore,
        hypothesis: Any,
        context: Any,
        evidence: str,
    ) -> dict[str, Any]:
        assert context.state is state
        semaphores.append(semaphore)
        contexts.append(evidence)
        return {"verdict": "holds"}

    state = make_state(
        articles=[
            make_article(
                "Long evidence", abstract="x" * 100000, used_in_analysis=True
            )
        ],
        context_enrichment_sources=[{"display": "y" * 100000}],
        meta_review={"common_weaknesses": ["Recurring assumption error"]},
    )
    monkeypatch.setattr(leaf, "_verify_within_semaphore", capture)
    for _ in range(2):
        assert await verify_hypothesis(state, make_hypothesis()) == {
            "verdict": "holds"
        }
    assert semaphores[0] is not semaphores[1]
    assert all(semaphore._value == 1 for semaphore in semaphores)
    assert all(len(context) < 20000 for context in contexts)
    assert "Long evidence" in contexts[0]
    assert "Recurring assumption error" in contexts[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,owner",
    [
        (verify_hypothesis, leaf),
        (observe_hypothesis, observation),
        (review_hypothesis, cr),
    ],
)
@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("ordinary"),
        LLMRateLimitParkError(9999, "cap"),
        LLMCallBudgetExceededError(2, 1),
    ],
)
async def test_failures_degrade_but_task_control_propagates(
    monkeypatch: pytest.MonkeyPatch,
    operation: Any,
    owner: Any,
    error: Exception,
) -> None:
    monkeypatch.setattr(owner, "call_llm_json", AsyncMock(side_effect=error))
    state = make_state(articles_with_reasoning="Retrieved literature")
    args = (
        (state, make_hypothesis(), ReviewType.FULL)
        if operation is review_hypothesis
        else (state, make_hypothesis())
    )
    if isinstance(error, RuntimeError):
        result = await operation(*args)
        assert (
            result.result if isinstance(result, ReviewRun) else result
        ) is None
    else:
        with pytest.raises(type(error)) as caught:
            await operation(*args)
        assert caught.value is error


@pytest.mark.asyncio
async def test_observation_indices_default_to_one_and_support_graph_indices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = AsyncMock(return_value={"classification": "supports"})
    monkeypatch.setattr(observation, "call_llm_json", calls)
    state = make_state(articles_with_reasoning="Literature")
    default = await observe_hypothesis(state, make_hypothesis())
    indexed = await observe_hypothesis(
        state, make_hypothesis(), hypothesis_index=3, total_count=7
    )
    assert default is not None and indexed is not None
    assert (
        calls.await_args_list[0].kwargs["options"].prompt_name == "reflection_1"
    )
    assert (
        calls.await_args_list[1].kwargs["options"].prompt_name == "reflection_3"
    )


@pytest.mark.asyncio
async def test_mature_review_keeps_ledger_separate_even_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = {"funded_threads": 4}
    monkeypatch.setattr(
        cr,
        "_review_evidence_for",
        AsyncMock(return_value=_ReviewEvidence([], [], [], ledger)),
    )
    monkeypatch.setattr(
        cr, "call_llm_json", AsyncMock(return_value={"verdict": "sound"})
    )
    run = await review_hypothesis(
        make_state(), make_hypothesis(), ReviewType.FULL
    )
    assert isinstance(run, ReviewRun)
    assert tuple(run) == (ReviewType.FULL, run.result, ledger)
    assert run.result is not None and "research_ledger" not in run.result
    monkeypatch.setattr(
        cr, "call_llm_json", AsyncMock(side_effect=RuntimeError("bad"))
    )
    failed = await review_hypothesis(
        make_state(), make_hypothesis(), ReviewType.FULL
    )
    assert failed == ReviewRun(ReviewType.FULL, None, ledger)


@pytest.mark.asyncio
async def test_graph_batch_limiter_and_issued_markers_are_retained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = peak = 0
    semaphores: list[asyncio.Semaphore] = []

    async def verify(
        hypothesis: Any, context: Any, evidence: str
    ) -> dict[str, Any]:
        nonlocal active, peak
        assert hypothesis.enrichments["deep_verification_issued"] is True
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return {}

    original = dv._verify_one

    async def capture_leaf(
        hypothesis: Any,
        context: Any,
        semaphore: asyncio.Semaphore,
        evidence: str,
    ) -> dict[str, Any] | None:
        semaphores.append(semaphore)
        return await original(hypothesis, context, semaphore, evidence)

    monkeypatch.setattr(dv, "MAX_CONCURRENT_LLM_CALLS", 2)
    monkeypatch.setattr(leaf, "_verify_with_probes", verify)
    monkeypatch.setattr(dv, "_verify_one", capture_leaf)
    ideas = [make_hypothesis() for _ in range(5)]
    counts = await dv._run_verification_batch(
        make_state(hypotheses=ideas), ideas
    )
    assert counts == (0, 5, 5)
    assert peak == 2
    assert len({id(semaphore) for semaphore in semaphores}) == 1
    assert all(idea.deep_verification_verdict == "unverified" for idea in ideas)


@pytest.mark.asyncio
async def test_public_verification_reuses_funded_review_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from co_scientist.agents.reflection import review_evidence

    idea = make_hypothesis()
    state = make_state()
    funded = make_article("Already funded research", source_id="funded")
    evidence = _ReviewEvidence([], [funded], [], {"threads": 4})
    loop = asyncio.get_running_loop()
    completed = loop.create_task(AsyncMock(return_value=evidence)())
    await completed
    review_evidence._review_evidence_flights.setdefault(loop, {})[
        review_evidence._evidence_key(state, idea)
    ] = completed
    calls = AsyncMock(return_value={"verdict": "holds"})
    monkeypatch.setattr(leaf, "call_llm_json", calls)
    monkeypatch.setattr(
        leaf, "_retrieve_probe_evidence", AsyncMock(return_value=([], []))
    )
    result = await verify_hypothesis(state, idea)
    assert result is not None
    assert result["verification_llm_calls"] == 2
    assert [item["source_id"] for item in result["retrieved_articles"]] == [
        "funded"
    ]
    assert (
        "Already funded research" in calls.await_args_list[1].kwargs["prompt"]
    )
    assert "deep_verification_issued" not in idea.enrichments


def test_public_verification_does_not_import_graph_orchestration() -> None:
    import ast
    import inspect

    from co_scientist.agents.reflection import operations

    imports = [
        node.module
        for node in ast.walk(ast.parse(inspect.getsource(operations)))
        if isinstance(node, ast.ImportFrom)
    ]
    assert "co_scientist.agents.reflection.deep_verification" not in imports
