from __future__ import annotations

import ast
import asyncio
import pathlib
from typing import Any
from unittest.mock import AsyncMock

import pytest

import co_scientist.agents.generation.literature_tools.validate as vs
import co_scientist.agents.reflection.deep_verification as dv
from co_scientist.agents.reflection import comprehensive_reflection as cr
from co_scientist.agents.reflection import reflection as refl
from co_scientist.agents.reflection import review as rv
from co_scientist.agents.reflection.review_evidence import _ReviewEvidence
from co_scientist.agents.reflection.review_gate import ReviewType
from co_scientist.exceptions import (
    LLMCallBudgetExceededError,
    LLMRateLimitParkError,
)
from co_scientist.llm.attempts import json_attempt
from co_scientist.llm.request import backend, completion
from co_scientist.llm.request.completion import (
    _apply_response_format,
    _supports_json_schema_response_format,
)
from co_scientist.offline import llm as offline_llm
from tests._llm_fake import FakeBackend
from tests._mcp import isolate_offline_router
from tests._state import make_hypothesis, make_state

_ROUTING_SCHEMA: dict[str, Any] = {
    "name": "routing_probe",
    "schema": {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    },
}


async def _answers_ok(**_kwargs: Any) -> str:
    return "ok"


def test_a_backend_scope_restores_what_it_replaced_even_when_it_raises() -> (
    None
):
    assert isinstance(backend.active_backend(), backend.LitellmBackend)
    first, second = FakeBackend(_answers_ok), FakeBackend(_answers_ok)

    previous = backend.install_backend(first)
    try:
        assert previous is None
        assert backend.install_backend(second) is first
    finally:
        backend.install_backend(previous)
    assert isinstance(backend.active_backend(), backend.LitellmBackend)

    with pytest.raises(RuntimeError), backend.using_backend(first):
        assert backend.active_backend() is first
        raise RuntimeError("boom")
    assert isinstance(backend.active_backend(), backend.LitellmBackend)


def _echo_model(label: str) -> Any:
    calls: list[dict[str, Any]] = []

    async def stub(**kwargs: Any) -> str:
        calls.append(kwargs)
        return label

    stub.calls = calls  # type: ignore[attr-defined]
    return stub


def _args(model: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": "probe"}],
    }


async def test_with_nothing_installed_the_live_litellm_attribute_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = _echo_model("first"), _echo_model("second")
    model = "openrouter/some/model"

    monkeypatch.setattr("co_scientist.llm.litellm.acompletion", first)
    one = await completion._acompletion_within_timeout(_args(model), model)
    monkeypatch.setattr("co_scientist.llm.litellm.acompletion", second)
    two = await completion._acompletion_within_timeout(_args(model), model)

    assert (one, two) == ("first", "second")
    assert first.calls == second.calls == [_args(model)]


async def test_the_offline_router_answers_offline_models_and_passes_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_offline_router(monkeypatch)
    real = _echo_model("real provider")
    monkeypatch.setattr("co_scientist.llm.litellm.acompletion", real)
    offline_llm.install_offline_router()
    offline_model = offline_llm.DEFAULT_OFFLINE_MODEL

    local = await completion._acompletion_within_timeout(
        _args(offline_model), offline_model
    )
    remote = await completion._acompletion_within_timeout(
        _args("openrouter/some/model"), "openrouter/some/model"
    )

    assert local.choices[0].message.content
    assert real.calls == [_args("openrouter/some/model")]
    assert remote == "real provider"


# Validation holds the default capability answer bound before router
# installation.
_default_capability = _supports_json_schema_response_format


def _registry_says_no_native_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "co_scientist.llm.litellm.supports_response_schema",
        lambda **_kwargs: False,
    )
    _default_capability.cache_clear()


def _response_format_for(model: str) -> str:
    args = _args(model)
    _apply_response_format(args, "probe", model, False, _ROUTING_SCHEMA)
    return str(args["response_format"]["type"])


def test_the_capability_answer_steers_the_format_but_not_the_validation_shim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Request shaping asks the installed backend on every call; validation
    binds the default answer before router installation."""
    isolate_offline_router(monkeypatch)
    _registry_says_no_native_schema(monkeypatch)
    model = offline_llm.DEFAULT_OFFLINE_MODEL

    try:
        assert _response_format_for(model) == "json_object"
        offline_llm.install_offline_router()
        assert _response_format_for(model) == "json_schema"
        assert _response_format_for("openrouter/some/model") == "json_object"

        result = {"answer": "x", "invented": 1}
        json_attempt._backfill_and_validate(result, _ROUTING_SCHEMA, model)
        assert result == {"answer": "x"}
    finally:
        _default_capability.cache_clear()


PARK = LLMRateLimitParkError(1788825600.0, "message_per_day")
OVER_BUDGET = LLMCallBudgetExceededError(2501, 2500)
ORDINARY = ValueError("provider returned unparseable JSON")


def _stub_review_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _evidence(*_: object, **__: object) -> _ReviewEvidence:
        return _ReviewEvidence([], [], [], None)

    async def _observations(*_: object, **__: object) -> str | None:
        return None

    monkeypatch.setattr(cr, "_review_evidence_for", _evidence)
    monkeypatch.setattr(cr, "_observations_for", _observations)


async def _mature_review(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> Any:
    _stub_review_inputs(monkeypatch)
    monkeypatch.setattr(cr, "call_llm_json", AsyncMock(side_effect=error))
    hypothesis = make_hypothesis(text="a mechanism")
    run = await cr._run_review(
        make_state(hypotheses=[hypothesis]), hypothesis, ReviewType.FULL
    )
    return run.result


async def _observation_reflection(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> Any:
    monkeypatch.setattr(
        refl, "_call_reflection_llm", AsyncMock(side_effect=error)
    )
    return await refl.analyze_single_hypothesis(
        hypothesis=make_hypothesis(text="a mechanism"),
        hypothesis_index=1,
        total_count=1,
        context=refl._ReflectionContext(
            articles_with_reasoning="retrieved observations",
            model_name="fixture",
        ),
    )


async def _deep_verification(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> Any:
    monkeypatch.setattr(dv, "_verify_with_probes", AsyncMock(side_effect=error))
    context = dv._VerificationContext(
        research_goal="g",
        model_name="fixture",
        tool_registry=None,
        state=make_state(),
    )
    return await dv._verify_within_semaphore(
        asyncio.Semaphore(1),
        make_hypothesis(text="a mechanism"),
        context,
        "",
    )


async def _initial_reviews(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> Any:
    monkeypatch.setattr(
        rv, "review_single_hypothesis", AsyncMock(side_effect=error)
    )
    return await rv.review_parallel_individual(
        [make_hypothesis(text="a"), make_hypothesis(text="b")],
        rv.ReviewContext.from_state(make_state()),
    )


_FALLBACK_SITES = [
    (_mature_review, None),
    (_observation_reflection, None),
    (_deep_verification, None),
    (_initial_reviews, [None, None]),
]


@pytest.mark.parametrize(
    ("site", "degraded"),
    _FALLBACK_SITES,
    ids=[
        "mature-review",
        "observation",
        "deep-verification",
        "initial-reviews",
    ],
)
async def test_a_batch_fallback_degrades_ordinary_failures_but_not_spent_caps(
    monkeypatch: pytest.MonkeyPatch, site: Any, degraded: Any
) -> None:
    """Batch fallback buys per-item retries; swallowing a spent cap
    multiplies doomed requests."""
    assert await site(monkeypatch, ORDINARY) == degraded
    for error in (PARK, OVER_BUDGET):
        with pytest.raises(type(error)):
            await site(monkeypatch, error)


def test_a_synthesis_batch_is_retried_individually_unless_a_cap_is_spent() -> (
    None
):
    batches = [[{"a": 1}], [{"b": 2}]]
    validated, failed = vs._partition_synthesis_results(
        batches, [[{"ok": True}], RuntimeError("batch refused")]
    )
    assert (validated, failed) == ([{"ok": True}], [(1, batches[1])])

    for error in (PARK, OVER_BUDGET):
        with pytest.raises(type(error)):
            vs._partition_synthesis_results(batches, [[], error])


# Structural guards cover new fallback handlers that behavior tests may not
# drive.

_AGENTS_DIR = (
    pathlib.Path(__file__).resolve().parents[1] / "src/co_scientist/agents"
)
_LLM_CALLS = {"call_llm", "call_llm_json", "call_llm_with_tools"}
_GUARD = "TASK_CONTROL_FLOW_ERRORS"


def _calls_an_llm(node: ast.AST) -> bool:
    return any(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id in _LLM_CALLS
        for child in ast.walk(node)
    )


def _catches_bare_exception(handler: ast.ExceptHandler) -> bool:
    return isinstance(handler.type, ast.Name) and handler.type.id == "Exception"


def _unguarded_handlers(node: ast.Try) -> list[int]:
    """A re-raise after a broad handler cannot run; guard order matters."""
    offenders = []
    guarded = False
    for handler in node.handlers:
        if _GUARD in ast.dump(handler.type or ast.Pass()):
            guarded = True
        elif _catches_bare_exception(handler) and not guarded:
            offenders.append(handler.lineno)
    return offenders


def _unguarded_llm_fallbacks(tree: ast.AST) -> list[int]:
    return [
        line
        for node in ast.walk(tree)
        if isinstance(node, ast.Try) and _calls_an_llm(node)
        for line in _unguarded_handlers(node)
    ]


def test_no_agent_degrades_an_llm_call_over_a_control_flow_error() -> None:
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

    bare = "try:\n    await call_llm_json(p)\nexcept Exception:\n    pass\n"
    guarded = (
        "try:\n    await call_llm_json(p)\n"
        "except TASK_CONTROL_FLOW_ERRORS:\n    raise\n"
        "except Exception:\n    pass\n"
    )
    assert _unguarded_llm_fallbacks(ast.parse(bare)) == [3]
    assert _unguarded_llm_fallbacks(ast.parse(guarded)) == []
