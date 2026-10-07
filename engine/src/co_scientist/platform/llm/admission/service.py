from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from co_scientist.core.exceptions import ProviderAdmissionError
from co_scientist.platform.db.admission import UNKNOWN_HOST, reserve_provider

_app: ContextVar[bool] = ContextVar("service_admission_app", default=False)


@contextmanager
def scoped_app_admission() -> Iterator[None]:
    token = _app.set(True)
    try:
        yield
    finally:
        _app.reset(token)


_client: ContextVar[str] = ContextVar("provider_usage_client", default="")
_host: ContextVar[str] = ContextVar("provider_usage_host", default=UNKNOWN_HOST)
_path: ContextVar[str | None] = ContextVar("provider_usage_path", default=None)


@contextmanager
def scoped_client(
    owner: str, *, host: str = UNKNOWN_HOST, db_path: str | None = None
) -> Iterator[None]:
    tokens = _client.set(owner), _host.set(host), _path.set(db_path)
    try:
        yield
    finally:
        _client.reset(tokens[0])
        _host.reset(tokens[1])
        _path.reset(tokens[2])


def _token_reservation(request: dict[str, Any], *, app: bool) -> int:
    from co_scientist.core.config import settings

    output = request.get("max_completion_tokens", request.get("max_tokens"))
    output_limit = (
        settings.app_llm_max_output_tokens if app else settings.provider_max_output_tokens
    )
    input_limit = settings.app_llm_max_input_bytes if app else settings.provider_max_input_bytes
    if (
        not isinstance(output, int)
        or isinstance(output, bool)
        or not 0 < output <= output_limit
        or request.get("n", 1) != 1
    ):
        raise ProviderAdmissionError("completion output budget exceeded")
    content = {key: request.get(key) for key in ("messages", "tools", "functions")}
    input_bytes = len(json.dumps(content, ensure_ascii=False).encode("utf-8"))
    if input_bytes > input_limit:
        raise ProviderAdmissionError("completion input budget exceeded")
    # Conservative byte-token bound plus the entire output cap. Failed requests
    # and interrupted streams retain the reservation, including after restart.
    return input_bytes + 1024 + output


def reserve_physical(request: dict[str, Any], *, app: bool | None = None) -> None:
    app = _app.get() if app is None else app
    tokens = _token_reservation(request, app=app)
    reserve_provider(_client.get(), _host.get(), tokens, app=app, db_path=_path.get())


def reserve_decision_physical(tokens: int, call_limit: int, token_limit: int) -> None:
    from co_scientist.platform.db.decision_usage import reserve_decision

    reserve_decision(tokens, call_limit, token_limit, _path.get())
    reserve_provider(_client.get(), _host.get(), tokens, app=_app.get(), db_path=_path.get())


def block_decision_provider(seconds: float) -> None:
    from co_scientist.platform.db.decision_usage import block_decisions

    block_decisions(seconds, _path.get())
