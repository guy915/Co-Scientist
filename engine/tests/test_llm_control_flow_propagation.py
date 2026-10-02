"""A durable task's two control-flow errors must escape every fallback.

Production run bc77950f (2026-09-07, extended tier): the free model chain
hit its per-day cap. The ranking node handled it exactly as designed --
``platform rate limit hit (message_per_day)``, the row back to ``queued``
with its attempt undone by ``task_worker.outcomes._park_rate_limited_task``
-- while eleven ``engine.fanout.reflection.item`` tasks died permanently at
attempt 3/3. The reviews inside them caught the park in a bare
``except Exception``, degraded to "no review", and the fan-out reported
that as an ordinary ``RuntimeError``: three doomed retries against a cap
that had not reset, then a dead item.

So the rule these tests pin: an agent may degrade over a provider or parse
failure, but never over ``LLMRateLimitParkError`` (only the worker can
park) or ``LLMCallBudgetExceededError`` (only the worker can terminate the
run). Both are re-raised; everything else keeps the fallback that stops
one bad call from costing the whole pass.
"""

import ast
import asyncio
import pathlib
from unittest.mock import AsyncMock

import pytest

from co_scientist.agents.reflection import comprehensive_reflection as cr
from co_scientist.agents.reflection import reflection as refl
from co_scientist.agents.reflection import review as rv
from co_scientist.agents.reflection import verification as dv
from co_scientist.agents.reflection.review_evidence import _ReviewEvidence
from co_scientist.agents.reflection.review_types import ReviewType
from co_scientist.exceptions import (
    LLMCallBudgetExceededError,
    LLMRateLimitParkError,
)
from tests._state import make_hypothesis, make_state

PARK = LLMRateLimitParkError(1788825600.0, "message_per_day")
OVER_BUDGET = LLMCallBudgetExceededError(2501, 2500)
ORDINARY = ValueError("provider returned unparseable JSON")


def _stub_review_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give ``_run_review`` inert evidence so only its LLM call can fail."""

    async def _evidence(*_: object, **__: object) -> _ReviewEvidence:
        return _ReviewEvidence([], [], [], None)

    async def _observations(*_: object, **__: object) -> str | None:
        return None

    monkeypatch.setattr(cr, "_review_evidence_for", _evidence)
    monkeypatch.setattr(cr, "_observations_for", _observations)


@pytest.mark.parametrize("error", [PARK, OVER_BUDGET])
async def test_a_control_flow_error_escapes_a_mature_review(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """The exact hole that killed eleven items in run bc77950f."""
    _stub_review_inputs(monkeypatch)
    monkeypatch.setattr(cr, "call_llm_json", AsyncMock(side_effect=error))
    hypothesis = make_hypothesis(text="a mechanism")

    with pytest.raises(type(error)):
        await cr._run_review(
            make_state(hypotheses=[hypothesis]), hypothesis, ReviewType.FULL
        )


async def test_an_ordinary_failure_still_degrades_a_mature_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One unparseable answer must not cost the pass its other reviews."""
    _stub_review_inputs(monkeypatch)
    monkeypatch.setattr(cr, "call_llm_json", AsyncMock(side_effect=ORDINARY))
    hypothesis = make_hypothesis(text="a mechanism")

    run = await cr._run_review(
        make_state(hypotheses=[hypothesis]), hypothesis, ReviewType.FULL
    )

    assert run.result is None


@pytest.mark.parametrize("error", [PARK, OVER_BUDGET])
async def test_a_control_flow_error_escapes_an_observation_reflection(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """The observation mode reaches the same fan-out item executor."""
    monkeypatch.setattr(
        refl, "_call_reflection_llm", AsyncMock(side_effect=error)
    )
    context = refl._ReflectionContext(
        articles_with_reasoning="retrieved observations",
        model_name="fixture",
    )

    with pytest.raises(type(error)):
        await refl.analyze_single_hypothesis(
            hypothesis=make_hypothesis(text="a mechanism"),
            hypothesis_index=1,
            total_count=1,
            context=context,
        )


async def test_an_ordinary_failure_still_degrades_an_observation_reflection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-hypothesis failure stays isolated to that hypothesis."""
    monkeypatch.setattr(
        refl, "_call_reflection_llm", AsyncMock(side_effect=ORDINARY)
    )
    context = refl._ReflectionContext(
        articles_with_reasoning="retrieved observations",
        model_name="fixture",
    )

    assert (
        await refl.analyze_single_hypothesis(
            hypothesis=make_hypothesis(text="a mechanism"),
            hypothesis_index=1,
            total_count=1,
            context=context,
        )
        is None
    )


@pytest.mark.parametrize("error", [PARK, OVER_BUDGET])
async def test_a_control_flow_error_escapes_deep_verification(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """Verification's per-hypothesis isolation is not a park's business."""
    monkeypatch.setattr(dv, "_verify_with_probes", AsyncMock(side_effect=error))
    context = dv._VerificationContext(
        research_goal="g",
        model_name="fixture",
        tool_registry=None,
        state=make_state(),
    )

    with pytest.raises(type(error)):
        await dv._verify_within_semaphore(
            asyncio.Semaphore(1),
            make_hypothesis(text="a mechanism"),
            context,
            "",
        )


async def test_an_ordinary_failure_still_degrades_deep_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken verification stays an explicit ``unverified`` verdict."""
    monkeypatch.setattr(
        dv, "_verify_with_probes", AsyncMock(side_effect=ORDINARY)
    )
    context = dv._VerificationContext(
        research_goal="g",
        model_name="fixture",
        tool_registry=None,
        state=make_state(),
    )

    assert (
        await dv._verify_within_semaphore(
            asyncio.Semaphore(1),
            make_hypothesis(text="a mechanism"),
            context,
            "",
        )
        is None
    )


@pytest.mark.parametrize("error", [PARK, OVER_BUDGET])
async def test_a_control_flow_error_escapes_the_initial_review_gather(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """``gather(return_exceptions=True)`` swallows a park like a handler."""
    monkeypatch.setattr(
        rv, "review_single_hypothesis", AsyncMock(side_effect=error)
    )
    context = rv.ReviewContext.from_state(make_state())

    with pytest.raises(type(error)):
        await rv.review_parallel_individual(
            [make_hypothesis(text="a"), make_hypothesis(text="b")], context
        )


async def test_an_ordinary_failure_still_degrades_one_initial_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit E15's per-hypothesis isolation is unchanged."""
    monkeypatch.setattr(
        rv, "review_single_hypothesis", AsyncMock(side_effect=ORDINARY)
    )
    context = rv.ReviewContext.from_state(make_state())

    assert await rv.review_parallel_individual(
        [make_hypothesis(text="a"), make_hypothesis(text="b")], context
    ) == [None, None]


# --- The sweep, pinned structurally -----------------------------------
#
# The behavioural tests above cover the reflection cascade. The same shape
# recurs wherever an agent wraps an LLM call in a fallback, so the guard
# below fails the build for any *new* one rather than waiting for the next
# run to lose its items to it. Syntactic by design: it reads the source,
# so it sees a handler that no test happens to drive.

_AGENTS_DIR = (
    pathlib.Path(__file__).resolve().parents[1] / "src/co_scientist/agents"
)
_LLM_CALLS = {"call_llm", "call_llm_json", "call_llm_with_tools"}
_GUARD = "TASK_CONTROL_FLOW_ERRORS"


def _calls_an_llm(node: ast.AST) -> bool:
    """True when this subtree invokes one of the engine's LLM seams."""
    return any(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id in _LLM_CALLS
        for child in ast.walk(node)
    )


def _catches_bare_exception(handler: ast.ExceptHandler) -> bool:
    """True when this handler catches ``Exception`` itself."""
    return isinstance(handler.type, ast.Name) and handler.type.id == "Exception"


def _unguarded_handlers(node: ast.Try) -> list[int]:
    """Bare handlers on this ``try`` that no guard clause precedes.

    Order matters, not presence: a re-raise written *below* the broad
    handler never runs, so the guard has to have been seen already.
    """
    offenders = []
    guarded = False
    for handler in node.handlers:
        if _GUARD in ast.dump(handler.type or ast.Pass()):
            guarded = True
        elif _catches_bare_exception(handler) and not guarded:
            offenders.append(handler.lineno)
    return offenders


def _unguarded_llm_fallbacks(tree: ast.AST) -> list[int]:
    """Line numbers of bare handlers over an LLM call with no guard first."""
    return [
        line
        for node in ast.walk(tree)
        if isinstance(node, ast.Try) and _calls_an_llm(node)
        for line in _unguarded_handlers(node)
    ]


def test_no_agent_degrades_an_llm_call_over_a_control_flow_error() -> None:
    """Every bare fallback around an LLM call re-raises the two first."""
    unguarded: dict[str, list[int]] = {}
    for path in sorted(_AGENTS_DIR.rglob("*.py")):
        offenders = _unguarded_llm_fallbacks(
            ast.parse(path.read_text(encoding="utf-8"))
        )
        if offenders:
            unguarded[str(path.relative_to(_AGENTS_DIR))] = offenders

    assert not unguarded, (
        "these handlers swallow a rate-limit park or the run's call-budget "
        f"ceiling: {unguarded}"
    )


def test_the_guard_would_notice_an_unprotected_fallback() -> None:
    """The structural check fails on the shape it exists to catch."""
    source = "try:\n    await call_llm_json(p)\nexcept Exception:\n    pass\n"
    assert _unguarded_llm_fallbacks(ast.parse(source)) == [3]


def test_the_guard_accepts_a_re_raise_placed_first() -> None:
    """A narrow re-raise before the fallback is what the rule asks for."""
    source = (
        "try:\n"
        "    await call_llm_json(p)\n"
        "except TASK_CONTROL_FLOW_ERRORS:\n"
        "    raise\n"
        "except Exception:\n"
        "    pass\n"
    )
    assert _unguarded_llm_fallbacks(ast.parse(source)) == []


@pytest.mark.parametrize("error", [PARK, OVER_BUDGET])
def test_a_control_flow_error_escapes_the_synthesis_batch_gather(
    error: Exception,
) -> None:
    """The one gather whose fallback is *more* calls, not fewer.

    A batch routed into ``failed_batches`` is answered by retrying its
    hypotheses one at a time -- against the very cap that refused the
    batch, so degrading here multiplies the doomed requests.
    """
    from co_scientist.agents.generation.literature_tools import (
        validate_synthesis as vs,
    )

    with pytest.raises(type(error)):
        vs._partition_synthesis_results([[{"a": 1}], [{"b": 2}]], [[], error])


def test_an_ordinary_batch_failure_is_still_retried_individually() -> None:
    """Per-batch isolation is unchanged for an ordinary failure."""
    from co_scientist.agents.generation.literature_tools import (
        validate_synthesis as vs,
    )

    batches = [[{"a": 1}], [{"b": 2}]]
    validated, failed = vs._partition_synthesis_results(
        batches, [[{"ok": True}], RuntimeError("batch refused")]
    )

    assert validated == [{"ok": True}]
    assert failed == [(1, batches[1])]
