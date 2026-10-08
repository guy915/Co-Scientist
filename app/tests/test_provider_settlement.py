from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

import pytest
from co_scientist.core.config import settings
from co_scientist.core.exceptions import LLMCallBudgetExceededError
from co_scientist.platform import db
from co_scientist.platform.llm import provider_usage
from co_scientist.platform.llm.llm_scope import app_call_scope
from co_scientist.platform.llm.request.transport import complete_request

from tests._llm_fake_backend import install_completion_backend

MAX_TOKENS = 10_000
REQUEST = {"model": "gpt-4o-mini", "max_tokens": MAX_TOKENS}


def _response(prompt: int, completion: int, reasoning: int | None = None) -> Any:
    details = SimpleNamespace(reasoning_tokens=reasoning) if reasoning is not None else None
    usage = SimpleNamespace(
        prompt_tokens=prompt, completion_tokens=completion, completion_tokens_details=details
    )
    return SimpleNamespace(choices=[], model="gpt-4o-mini", usage=usage)


def _reservation() -> int:
    from co_scientist.platform.llm.admission.service import _token_reservation

    return _token_reservation(dict(REQUEST), app=False)


async def _call(owner: str = "owner", host: str = "peer") -> Any:
    with provider_usage.scoped_client(owner, host=host):
        return await complete_request(dict(REQUEST), "gpt-4o-mini", byok=False, timeout_seconds=1)


def _tokens() -> dict[str, int]:
    with db.connect() as conn:
        rows = conn.execute("SELECT scope, calls, tokens FROM provider_admissions").fetchall()
    return {f"{scope}.tokens": tokens for scope, _, tokens in rows} | {
        f"{scope}.calls": calls for scope, calls, _ in rows
    }


async def test_a_run_whose_real_usage_fits_is_not_stopped_by_its_reservations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 20
    # Twenty reservations need about 225k tokens; twenty calls use 8k.
    monkeypatch.setattr(settings, "provider_client_tokens_per_day", 60_000)

    async def respond(**kwargs: Any) -> Any:
        return _response(prompt=100, completion=300)

    fake = install_completion_backend(monkeypatch, respond)
    for _ in range(calls):
        await _call()

    assert len(fake.requests) == calls
    assert _tokens()["client.tokens"] == calls * 400
    assert _tokens()["client.calls"] == calls


async def test_settlement_lowers_every_booked_row_to_reported_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def respond(**kwargs: Any) -> Any:
        return _response(prompt=1_000, completion=2_000)

    install_completion_backend(monkeypatch, respond)
    await _call()

    assert _tokens() == {
        "global.tokens": 3_000,
        "client.tokens": 3_000,
        "host.tokens": 3_000,
        "global.calls": 1,
        "client.calls": 1,
        "host.calls": 1,
    }


async def test_reasoning_reported_outside_completion_is_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def respond(**kwargs: Any) -> Any:
        return _response(prompt=100, completion=200, reasoning=900)

    install_completion_backend(monkeypatch, respond)
    await _call()

    assert _tokens()["client.tokens"] == 1_200


async def test_reasoning_inside_completion_is_not_counted_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def respond(**kwargs: Any) -> Any:
        return _response(prompt=100, completion=900, reasoning=700)

    install_completion_backend(monkeypatch, respond)
    await _call()

    assert _tokens()["client.tokens"] == 1_000


async def test_usage_above_the_reservation_never_raises_the_booking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def respond(**kwargs: Any) -> Any:
        return _response(prompt=500_000, completion=MAX_TOKENS)

    install_completion_backend(monkeypatch, respond)
    await _call()

    assert _tokens()["client.tokens"] == _reservation()


@pytest.mark.parametrize(
    "usage",
    [
        None,
        SimpleNamespace(prompt_tokens=None, completion_tokens=12),
        SimpleNamespace(prompt_tokens=10, completion_tokens=-1),
        SimpleNamespace(prompt_tokens=10, completion_tokens=True),
    ],
)
async def test_missing_or_malformed_usage_keeps_the_reservation(
    monkeypatch: pytest.MonkeyPatch, usage: Any
) -> None:
    async def respond(**kwargs: Any) -> Any:
        return SimpleNamespace(choices=[], model="gpt-4o-mini", usage=usage)

    install_completion_backend(monkeypatch, respond)
    await _call()

    assert _tokens()["client.tokens"] == _reservation()


async def test_a_failed_call_keeps_the_reservation(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(**kwargs: Any) -> Any:
        raise RuntimeError("provider outcome unknown")

    install_completion_backend(monkeypatch, fail)
    with pytest.raises(RuntimeError):
        await _call()

    assert _tokens()["client.tokens"] == _reservation()


async def test_a_restart_before_the_response_keeps_the_reservation(
    monkeypatch: pytest.MonkeyPatch, isolated_db: str
) -> None:
    async def die(**kwargs: Any) -> Any:
        # The process dies after dispatch: nothing after this point runs.
        db._initialized.discard(isolated_db)
        raise SystemExit

    install_completion_backend(monkeypatch, die)
    with pytest.raises(SystemExit):
        await _call()

    assert _tokens()["client.tokens"] == _reservation()


class _Stream:
    def __init__(self, chunks: list[Any], error: BaseException | None = None) -> None:
        self._chunks = iter(chunks)
        self._error = error

    def __aiter__(self) -> _Stream:
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._chunks)
        except StopIteration:
            if self._error is not None:
                raise self._error from None
            raise StopAsyncIteration from None


async def _stream_call(monkeypatch: pytest.MonkeyPatch, stream: _Stream) -> None:
    async def respond(**kwargs: Any) -> Any:
        return stream

    install_completion_backend(monkeypatch, respond)
    with provider_usage.scoped_client("owner", host="peer"):
        response = await complete_request(
            dict(REQUEST, stream=True), "gpt-4o-mini", byok=False, timeout_seconds=1
        )
    async for _ in response:
        pass


async def test_a_finished_stream_settles_to_its_final_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final = _response(prompt=40, completion=60)
    await _stream_call(monkeypatch, _Stream([SimpleNamespace(usage=None), final]))

    assert _tokens()["client.tokens"] == 100


async def test_an_interrupted_stream_keeps_the_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partial = _response(prompt=40, completion=60)
    with pytest.raises(ConnectionError):
        await _stream_call(monkeypatch, _Stream([partial], ConnectionError("reset")))

    assert _tokens()["client.tokens"] == _reservation()


async def test_app_calls_also_settle_the_app_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    async def respond(**kwargs: Any) -> Any:
        return _response(prompt=100, completion=150)

    install_completion_backend(monkeypatch, respond)
    with app_call_scope("test"):
        await _call()

    with db.connect() as conn:
        app_tokens = conn.execute("SELECT tokens FROM app_llm_usage").fetchone()[0]
    assert app_tokens == 250
    assert _tokens()["global.tokens"] == 250


def test_concurrent_calls_stay_within_the_token_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    ceiling = 3 * _reservation()
    monkeypatch.setattr(settings, "provider_client_tokens_per_day", ceiling)
    observed: list[int] = []

    async def respond(**kwargs: Any) -> Any:
        observed.append(_tokens()["client.tokens"])
        await asyncio.sleep(0.01)
        return _response(prompt=100, completion=100)

    install_completion_backend(monkeypatch, respond)

    def call(_: int) -> bool:
        try:
            asyncio.run(_call())
            return True
        except LLMCallBudgetExceededError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        admitted = sum(pool.map(call, range(40)))

    assert observed and max(observed) <= ceiling
    assert admitted >= 3
    assert _tokens()["client.tokens"] == admitted * 200
