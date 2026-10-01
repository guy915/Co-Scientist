"""The completion backend registry and the recording fake that rides it.

``test_llm_completion_routing.py`` pins what a completion does end to end;
these pin the registry's own contract: the default is litellm, an installed
backend answers (and records) every call and carries its capability answer,
and what was installed before comes back.
"""

from typing import Any

import pytest

from co_scientist.llm.request import backend, completion
from co_scientist.llm.request.schema import _apply_response_format
from tests._llm_backend_fake import FakeBackend, install_fake_backend

_MODEL = "openrouter/some/model"
_SCHEMA: dict[str, Any] = {
    "name": "backend_probe",
    "schema": {"type": "object", "properties": {}},
}


async def _answers_ok(**_kwargs: Any) -> str:
    return "ok"


def test_the_default_backend_is_litellm_until_one_is_installed() -> None:
    """Nothing installed means litellm, and the registry says so."""
    assert isinstance(backend.active_backend(), backend.LitellmBackend)


def test_install_returns_what_it_replaced_and_none_restores_the_default() -> (
    None
):
    """``install_backend`` hands back the previous override for restoring."""
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
    """A scoped install never outlives its ``with`` block."""
    fake = FakeBackend(_answers_ok)

    with pytest.raises(RuntimeError), backend.using_backend(fake):
        assert backend.active_backend() is fake
        raise RuntimeError("boom")

    assert isinstance(backend.active_backend(), backend.LitellmBackend)


async def test_an_installed_backend_answers_and_records_every_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The completion await goes to the backend, kwargs and all."""
    fake = install_fake_backend(monkeypatch, _answers_ok)
    args = {"model": _MODEL, "messages": [{"role": "user", "content": "hi"}]}

    answer = await completion._acompletion_within_timeout(args, _MODEL)

    assert answer == "ok"
    assert fake.requests == [args]


async def test_a_backend_that_raises_surfaces_through_the_completion_await(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A backend's failure is not swallowed by the await around it."""

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
    """A fake that says no steers the request onto the json_object shim."""
    install_fake_backend(
        monkeypatch, _answers_ok, supports_json_schema=lambda _model: False
    )
    args: dict[str, Any] = {"model": _MODEL, "messages": []}

    _apply_response_format(args, "probe", _MODEL, False, _SCHEMA)

    assert args["response_format"] == {"type": "json_object"}


def test_a_fake_without_a_capability_answer_uses_the_real_default() -> None:
    """The fake only overrides the capability when the test says to."""
    fake = FakeBackend(_answers_ok)

    assert fake.supports_json_schema(_MODEL) is (
        backend.litellm_supports_json_schema(_MODEL)
    )
