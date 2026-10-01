"""Characterization of every fact the engine holds about a model.

A model's capabilities, routing and price are answered by several
functions that each reach a different table or family substring. This pins
what every one of them says for each route the engine names and for a set
of unknown and family-variant routes, so regrouping those tables cannot
change an answer without this file failing. The recorded answers are in
``tests/_model_profile_snapshot.py``: ``CAPABILITIES`` groups the models
that share one row, ``MONEY`` has one row per model.

Only functions expected to outlive such a regrouping are called. Models are
passed exactly as a caller spells them, mixed case included:
``estimate_cost_usd`` and the free-route check are exact-case, every other
fact lowercases.

A capability row holds:

* ``reasons`` -- ``model_reasons``.
* ``effort`` -- ``reasoning_effort_args`` enabled, then disabled.
* ``knobs`` -- the thinking/reasoning object ``deepseek_thinking_extra_body``
  sends when thinking is requested, when it is not, and when it is not but
  the retry loop is recovering from a mandatory-reasoning refusal
  (``scoped_minimal_reasoning``).
* ``routing`` -- the rest of that body: the gateway provider block (shown as
  ``"gateway provider"`` while it equals ``_gateway_provider``) and the
  fallback models. Identical in all three modes, which ``_split_body``
  asserts.
* ``thinks`` -- ``effective_thinking_enabled`` for a call that asked to
  disable reasoning, normally and while recovering.
* ``floor`` -- ``effective_max_tokens`` for a 4000-token ask, thinking
  requested then not.
* ``schema`` -- ``True``/``False`` when the answer to "does it take a
  json_schema response_format" is fixed, ``"registry"`` when it is whatever
  litellm's capability registry says (``True`` if that lookup raises).
* ``temperature`` -- ``_clamp_temperature`` for 0.0, 0.7 and 1.0.
* ``free`` -- ``_requires_free`` for a deployment key, then a caller's own.
* ``free_row`` -- ``verify_model`` for the gateway-relative id against a
  catalog row that lists only prompt and completion prices: "ok" for
  ``:free`` variants and admitted promotions, which may omit ancillary
  rates, else why it is refused.
* ``requests`` -- ``_build_completion_args`` for a schema'd call with
  thinking on, then a plain-JSON call with thinking off: the response
  format, whether the schema was restated in the prompt, ``max_tokens``,
  and whether ``extra_body`` and ``reasoning_effort`` are exactly what the
  functions above say for that mode.

A money row is ``MODEL_PRICING.get`` as (prompt, completion, cached), then
``estimate_cost_usd`` for 1M prompt tokens (half cached) plus 1M completion
tokens, then ``_gateway_provider`` for the lowercased name, written as what
differs from ``_BASE_PROVIDER`` (``None`` marks a key the provider omits).
"""

import contextlib
from collections.abc import Iterator
from typing import Any
from unittest import mock

import litellm
import pytest

from co_scientist.constants_pricing import MODEL_PRICING, estimate_cost_usd
from co_scientist.exceptions import FreeModelEligibilityError
from co_scientist.llm import (
    deepseek_thinking_extra_body,
    model_reasons,
    reasoning_effort_args,
)
from co_scientist.llm.admission.free_catalog import verify_model
from co_scientist.llm.admission.free_policy import _requires_free
from co_scientist.llm.request.completion import (
    CompletionShape,
    _build_completion_args,
    _clamp_temperature,
    _supports_json_schema_response_format,
)
from co_scientist.llm.request.gateway_body import (
    effective_thinking_enabled,
    scoped_minimal_reasoning,
)
from co_scientist.llm.request.gateway_routing import _gateway_provider
from co_scientist.llm.request.thinking import effective_max_tokens
from tests._model_profile_snapshot import CAPABILITIES, MONEY

_SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}}
_FREE_ROW = {
    "pricing": {"prompt": "0", "completion": "0"},
    "architecture": {
        "input_modalities": ["text"],
        "output_modalities": ["text"],
    },
}
_KNOB_KEYS = ("reasoning", "thinking")
_BASE_PROVIDER: dict[str, Any] = {
    "require_parameters": True,
    "allow_fallbacks": True,
    "preferred_min_throughput": 25,
    "order": ["z-ai", "deepinfra", "novita", "gmicloud"],
}


@contextlib.contextmanager
def _registry(answer: bool | type[Exception]) -> Iterator[None]:
    """Stands in for litellm's capability registry, cache cleared around it."""

    def stub(model: str) -> bool:
        if isinstance(answer, bool):
            return answer
        raise answer("no registry entry")

    patch = mock.patch.object(litellm, "supports_response_schema", stub)
    _supports_json_schema_response_format.cache_clear()
    try:
        with patch:
            yield
    finally:
        _supports_json_schema_response_format.cache_clear()


def _schema_route(model: str) -> bool | str:
    """True/False when fixed, ``"registry"`` when litellm decides."""
    answers = []
    for stub in (True, False, RuntimeError):
        with _registry(stub):
            answers.append(_supports_json_schema_response_format(model))
    if answers == [True, False, True]:
        return "registry"
    assert len(set(answers)) == 1, (model, answers)
    return answers[0]


def _free_row(model: str) -> str:
    route = model.removeprefix("openrouter/")
    try:
        verify_model(route, {route: _FREE_ROW})
    except FreeModelEligibilityError as exc:
        return str(exc)
    return "ok"


def _bodies(model: str) -> list[dict[str, Any]]:
    """The thinking body when requested, when not, and when recovering."""
    with scoped_minimal_reasoning():
        recovering = deepseek_thinking_extra_body(model, enabled=False)
    return [
        deepseek_thinking_extra_body(model),
        deepseek_thinking_extra_body(model, enabled=False),
        recovering,
    ]


def _routing(model: str, body: dict[str, Any]) -> dict[str, Any]:
    """A body without its knob, its provider block named when standard."""
    routing = {k: v for k, v in body.items() if k not in _KNOB_KEYS}
    if routing.get("provider") == _gateway_provider(model.lower()):
        routing["provider"] = "gateway provider"
    return routing


def _split_body(model: str) -> tuple[list[Any], dict[str, Any]]:
    """The three modes' knob objects, and the routing they share."""
    bodies = _bodies(model)
    routings = [_routing(model, body) for body in bodies]
    assert routings[0] == routings[1] == routings[2], model
    knobs = [
        next((body[key] for key in _KNOB_KEYS if key in body), None)
        for body in bodies
    ]
    return knobs, routings[0]


def _request(model: str, shape: CompletionShape) -> list[Any]:
    args = _build_completion_args("prompt", model, 4000, 0.5, shape)
    wired = args.get("extra_body", {}) == deepseek_thinking_extra_body(
        model, enabled=shape.enable_thinking
    ) and args.get("reasoning_effort") == reasoning_effort_args(
        model, enabled=shape.enable_thinking
    ).get("reasoning_effort")
    return [
        args.get("response_format", {}).get("type"),
        args["messages"] != [{"role": "user", "content": "prompt"}],
        args["max_tokens"],
        wired,
    ]


def _requests(model: str) -> list[list[Any]]:
    with _registry(True):
        schema = _request(model, CompletionShape(json_schema=_SCHEMA))
        plain = _request(
            model, CompletionShape(force_json=True, enable_thinking=False)
        )
    return [schema, plain]


def _thinks(model: str) -> list[bool]:
    with scoped_minimal_reasoning():
        recovering = effective_thinking_enabled(model, False)
    return [effective_thinking_enabled(model, False), recovering]


def _capabilities(model: str) -> dict[str, Any]:
    """Every capability the engine would act on for ``model`` today."""
    knobs, routing = _split_body(model)
    return {
        "reasons": model_reasons(model),
        "effort": [
            reasoning_effort_args(model),
            reasoning_effort_args(model, enabled=False),
        ],
        "knobs": knobs,
        "routing": routing,
        "thinks": _thinks(model),
        "floor": [
            effective_max_tokens(model, 4000, True),
            effective_max_tokens(model, 4000, False),
        ],
        "schema": _schema_route(model),
        "temperature": [_clamp_temperature(model, t) for t in (0.0, 0.7, 1.0)],
        "free": [
            _requires_free({"model": model}, byok=False),
            _requires_free({"model": model}, byok=True),
        ],
        "free_row": _free_row(model),
        "requests": _requests(model),
    }


def _provider_delta(provider: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(provider.keys() | _BASE_PROVIDER.keys())
    return {
        key: provider.get(key)
        for key in keys
        if provider.get(key) != _BASE_PROVIDER.get(key)
    }


def _money(model: str) -> list[Any]:
    """What ``model`` costs and what a gateway call to it may be charged."""
    price = MODEL_PRICING.get(model)
    return [
        None
        if price is None
        else [
            price.prompt_usd_per_million,
            price.completion_usd_per_million,
            price.cached_prompt_usd_per_million,
        ],
        estimate_cost_usd(model, 1_000_000, 1_000_000, 500_000),
        _provider_delta(_gateway_provider(model.lower())),
    ]


_CAPABILITY_ROWS = [
    (model, row) for models, row in CAPABILITIES for model in models
]


@pytest.fixture(autouse=True)
def _hermetic_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The environment variables that reshape these answers."""
    monkeypatch.delenv("COSCIENTIST_GATEWAY_PROVIDER_ORDER", raising=False)
    monkeypatch.delenv("COSCIENTIST_REQUIRE_FREE_MODELS", raising=False)
    monkeypatch.setenv("COSCIENTIST_LLM_TIMEOUT_SECONDS", "0")


@pytest.mark.parametrize(("model", "row"), _CAPABILITY_ROWS)
def test_every_capability_of_the_model_is_unchanged(
    model: str, row: dict[str, Any]
) -> None:
    """The engine answers each capability question as it was recorded."""
    observed = _capabilities(model)
    for fact, expected in row.items():
        assert observed[fact] == expected, (model, fact)
    assert observed.keys() == row.keys(), model


@pytest.mark.parametrize(("model", "row"), sorted(MONEY.items()))
def test_the_price_and_routing_cap_of_the_model_are_unchanged(
    model: str, row: list[Any]
) -> None:
    """The engine charges and caps each model as it was recorded."""
    assert _money(model) == row


def test_every_model_has_both_rows() -> None:
    """A capability row and a money row for each route, none for a stranger."""
    capability_models = {model for model, _ in _CAPABILITY_ROWS}
    assert capability_models == set(MONEY)
    assert set(MODEL_PRICING) <= capability_models
