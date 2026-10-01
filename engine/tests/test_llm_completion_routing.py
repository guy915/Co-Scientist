"""Where a completion goes, and which capability answer travels with it.

Every engine completion is awaited through
``completion._acompletion_within_timeout``. What answers it is chosen by
exactly two things, and these tests pin both from the outside, through that
await and through the response-format helpers, so they hold whatever
mechanism does the choosing:

* nothing installed: the live ``litellm.acompletion`` attribute, looked up
  at call time -- which is why the string path
  ``"co_scientist.llm.litellm.acompletion"`` patches a call that is already
  built;
* the offline router installed: an ``offline/`` model is answered locally,
  every other model goes to whatever answered before.

The model-capability answer ("does this model take a native json_schema
response format") travels with the router, but it is read in two places on
purpose. ``llm.request.schema`` asks at call time, so the router's answer
steers which response format a call is built with. ``llm.attempts.
json_attempt`` bound the default answer at import, so the validation shim that
repairs a downgraded response never sees the router: an offline model is sent
a native schema and, if its answer ever needed repair, validated as though the
provider had not enforced one. That split is observable behaviour; it is
pinned here so a later change has to choose it rather than stumble into it.
"""

from typing import Any

import pytest

from co_scientist import offline_llm
from co_scientist.llm.attempts import json_attempt
from co_scientist.llm.request import completion
from co_scientist.llm.request.completion import (
    _supports_json_schema_response_format,
)
from co_scientist.llm.request.schema import _apply_response_format
from tests._offline_helpers import isolate_offline_router

_SCHEMA: dict[str, Any] = {
    "name": "routing_probe",
    "schema": {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    },
}


def _echo_model(label: str) -> Any:
    """Builds a provider stub that answers with its own label and records."""
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
    """The attribute is read per call, so a later patch wins over an earlier."""
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
    """``offline/`` goes local; any other model reaches the prior answerer."""
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
    """A repeat install must not chain a second router over the first."""
    isolate_offline_router(monkeypatch)
    real = _echo_model("real provider")
    monkeypatch.setattr("co_scientist.llm.litellm.acompletion", real)

    offline_llm.install_offline_router()
    offline_llm.install_offline_router()
    await completion._acompletion_within_timeout(
        _args("openrouter/some/model"), "openrouter/some/model"
    )

    assert len(real.calls) == 1


# The default answer, bound at import before any router could replace the
# ``completion`` attribute; the only handle that still has ``cache_clear``.
_default_capability = _supports_json_schema_response_format


def _registry_says_no_native_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """Makes litellm's capability registry reject json_schema everywhere."""
    monkeypatch.setattr(
        "co_scientist.llm.litellm.supports_response_schema",
        lambda **_kwargs: False,
    )
    _default_capability.cache_clear()


def _response_format_for(model: str) -> str:
    args = _args(model)
    _apply_response_format(args, "probe", model, False, _SCHEMA)
    return str(args["response_format"]["type"])


def test_the_capability_answer_steers_the_format_a_call_is_built_with(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline models get native json_schema only once the router is in."""
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
    """An invented field is still pruned for an offline model after install.

    ``json_attempt`` bound the default capability answer at import, so the
    repair shim treats an offline model as one without native schema
    enforcement even while the call itself was built with one.
    """
    isolate_offline_router(monkeypatch)
    _registry_says_no_native_schema(monkeypatch)
    model = offline_llm.DEFAULT_OFFLINE_MODEL

    try:
        offline_llm.install_offline_router()
        result = {"answer": "x", "invented": 1}

        json_attempt._backfill_and_validate(result, _SCHEMA, model)

        assert result == {"answer": "x"}
    finally:
        _default_capability.cache_clear()
