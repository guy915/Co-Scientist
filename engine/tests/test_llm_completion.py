from __future__ import annotations

import ast
import asyncio
import pathlib
from typing import Any
from unittest.mock import AsyncMock

import pytest

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
from tests._llm_fake import FakeBackend, install_fake_backend
from tests._mcp import isolate_offline_router
from tests._state import make_hypothesis, make_state

_MODEL = "openrouter/some/model"
_LLM_COMPLETION_BACKEND_SCHEMA: dict[str, Any] = {
    "name": "backend_probe",
    "schema": {"type": "object", "properties": {}},
}


async def _answers_ok(**_kwargs: Any) -> str:
    return "ok"


def test_the_default_backend_is_litellm_until_one_is_installed() -> None:
    assert isinstance(backend.active_backend(), backend.LitellmBackend)


def test_install_returns_what_it_replaced_and_none_restores_the_default() -> (
    None
):
    first = FakeBackend(_answers_ok)
    second = FakeBackend(_answers_ok)

    previous = backend.install_backend(first)
    try:
        assert previous is None
        assert backend.active_backend() is first
        assert backend.install_backend(second) is first
        assert backend.active_backend() is second
    finally:
        backend.install_backend(previous)

    assert isinstance(backend.active_backend(), backend.LitellmBackend)


def test_using_backend_restores_even_when_the_block_raises() -> None:
    fake = FakeBackend(_answers_ok)

    with pytest.raises(RuntimeError), backend.using_backend(fake):
        assert backend.active_backend() is fake
        raise RuntimeError("boom")

    assert isinstance(backend.active_backend(), backend.LitellmBackend)


async def test_an_installed_backend_answers_and_records_every_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = install_fake_backend(monkeypatch, _answers_ok)
    args = {"model": _MODEL, "messages": [{"role": "user", "content": "hi"}]}

    answer = await completion._acompletion_within_timeout(args, _MODEL)

    assert answer == "ok"
    assert fake.requests == [args]


async def test_a_backend_that_raises_surfaces_through_the_completion_await(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    async def refuses(**_kwargs: Any) -> Any:
        raise ConnectionError("provider down")

    install_fake_backend(monkeypatch, refuses)

    with pytest.raises(ConnectionError):
        await completion._acompletion_within_timeout(
            {"model": _MODEL, "messages": []}, _MODEL
        )


def test_the_capability_answer_comes_from_the_installed_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_backend(
        monkeypatch, _answers_ok, supports_json_schema=lambda _model: False
    )
    args: dict[str, Any] = {"model": _MODEL, "messages": []}

    _apply_response_format(
        args, "probe", _MODEL, False, _LLM_COMPLETION_BACKEND_SCHEMA
    )

    assert args["response_format"] == {"type": "json_object"}


def test_a_fake_without_a_capability_answer_uses_the_real_default() -> None:
    fake = FakeBackend(_answers_ok)

    assert fake.supports_json_schema(_MODEL) is (
        backend.litellm_supports_json_schema(_MODEL)
    )


_LLM_COMPLETION_ROUTING_SCHEMA: dict[str, Any] = {
    "name": "routing_probe",
    "schema": {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    },
}


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
    first = _echo_model("first")
    second = _echo_model("second")

    monkeypatch.setattr("co_scientist.llm.litellm.acompletion", first)
    one = await completion._acompletion_within_timeout(
        _args("openrouter/some/model"), "openrouter/some/model"
    )
    monkeypatch.setattr("co_scientist.llm.litellm.acompletion", second)
    two = await completion._acompletion_within_timeout(
        _args("openrouter/some/model"), "openrouter/some/model"
    )

    assert (one, two) == ("first", "second")
    assert first.calls == [_args("openrouter/some/model")]
    assert second.calls == [_args("openrouter/some/model")]


async def test_the_offline_router_answers_offline_models_and_passes_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_offline_router(monkeypatch)
    real = _echo_model("real provider")
    monkeypatch.setattr("co_scientist.llm.litellm.acompletion", real)
    offline_llm.install_offline_router()

    local = await completion._acompletion_within_timeout(
        _args(offline_llm.DEFAULT_OFFLINE_MODEL),
        offline_llm.DEFAULT_OFFLINE_MODEL,
    )
    remote = await completion._acompletion_within_timeout(
        _args("openrouter/some/model"), "openrouter/some/model"
    )

    assert local.choices[0].message.content
    assert real.calls == [_args("openrouter/some/model")]
    assert remote == "real provider"


async def test_installing_the_router_twice_still_passes_through_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_offline_router(monkeypatch)
    real = _echo_model("real provider")
    monkeypatch.setattr("co_scientist.llm.litellm.acompletion", real)

    offline_llm.install_offline_router()
    offline_llm.install_offline_router()
    await completion._acompletion_within_timeout(
        _args("openrouter/some/model"), "openrouter/some/model"
    )

    assert len(real.calls) == 1


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
    _apply_response_format(
        args, "probe", model, False, _LLM_COMPLETION_ROUTING_SCHEMA
    )
    return str(args["response_format"]["type"])


def test_the_capability_answer_steers_the_format_a_call_is_built_with(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_offline_router(monkeypatch)
    _registry_says_no_native_schema(monkeypatch)
    model = offline_llm.DEFAULT_OFFLINE_MODEL

    try:
        assert _response_format_for(model) == "json_object"
        offline_llm.install_offline_router()
        assert _response_format_for(model) == "json_schema"
        assert _response_format_for("openrouter/some/model") == "json_object"
    finally:
        _default_capability.cache_clear()


def test_the_validation_shim_keeps_the_default_answer_not_the_routers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validation binds the default capability answer before router
    installation; request shaping stays live."""
    isolate_offline_router(monkeypatch)
    _registry_says_no_native_schema(monkeypatch)
    model = offline_llm.DEFAULT_OFFLINE_MODEL

    try:
        offline_llm.install_offline_router()
        result = {"answer": "x", "invented": 1}

        json_attempt._backfill_and_validate(
            result, _LLM_COMPLETION_ROUTING_SCHEMA, model
        )

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


@pytest.mark.parametrize("error", [PARK, OVER_BUDGET])
async def test_a_control_flow_error_escapes_a_mature_review(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """Batch fallback buys per-item retries; swallowing a spent cap
    multiplies doomed requests."""
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
    """Batch fallback buys per-item retries; swallowing a spent cap
    multiplies doomed requests."""
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
    """Batch fallback buys per-item retries; swallowing a spent cap
    multiplies doomed requests."""
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
    """Batch fallback buys per-item retries; swallowing a spent cap
    multiplies doomed requests."""
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
    monkeypatch.setattr(
        rv, "review_single_hypothesis", AsyncMock(side_effect=ORDINARY)
    )
    context = rv.ReviewContext.from_state(make_state())

    assert await rv.review_parallel_individual(
        [make_hypothesis(text="a"), make_hypothesis(text="b")], context
    ) == [None, None]


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


def test_the_guard_would_notice_an_unprotected_fallback() -> None:
    source = "try:\n    await call_llm_json(p)\nexcept Exception:\n    pass\n"
    assert _unguarded_llm_fallbacks(ast.parse(source)) == [3]


def test_the_guard_accepts_a_re_raise_placed_first() -> None:
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
    """Batch fallback buys per-item retries; swallowing a spent cap
    multiplies doomed requests."""
    import co_scientist.agents.generation.literature_tools.validate as vs

    with pytest.raises(type(error)):
        vs._partition_synthesis_results([[{"a": 1}], [{"b": 2}]], [[], error])


def test_an_ordinary_batch_failure_is_still_retried_individually() -> None:
    import co_scientist.agents.generation.literature_tools.validate as vs

    batches = [[{"a": 1}], [{"b": 2}]]
    validated, failed = vs._partition_synthesis_results(
        batches, [[{"ok": True}], RuntimeError("batch refused")]
    )

    assert validated == [{"ok": True}]
    assert failed == [(1, batches[1])]
