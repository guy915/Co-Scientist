from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from co_scientist.core.exceptions import ProviderAdmissionError
from co_scientist.platform.db.admission import UNKNOWN_HOST, reserve_provider, settle_provider

logger = logging.getLogger(__name__)

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


def current_db_path() -> str:
    from co_scientist.platform.db import default_db_path

    return _path.get() or default_db_path() or "./coscientist.db"


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


@dataclass(frozen=True)
class Reservation:
    owner: str
    host: str
    day: int
    tokens: int
    app: bool
    db_path: str | None


def reserve_physical(request: dict[str, Any], *, app: bool | None = None) -> Reservation:
    app = _app.get() if app is None else app
    tokens = _token_reservation(request, app=app)
    owner, host, db_path = _client.get(), _host.get(), _path.get()
    day = reserve_provider(owner, host, tokens, app=app, db_path=db_path)
    return Reservation(owner, host, day, tokens, app, db_path)


def _reported_tokens(response: Any) -> int | None:
    usage = getattr(response, "usage", None)
    prompt = getattr(usage, "prompt_tokens", None)
    completion = getattr(usage, "completion_tokens", None)
    if type(prompt) is not int or type(completion) is not int or min(prompt, completion) < 0:
        return None
    details = getattr(usage, "completion_tokens_details", None)
    reasoning = getattr(details, "reasoning_tokens", None)
    # Completion normally includes reasoning; a provider reporting more
    # reasoning than completion counted it separately.
    if type(reasoning) is int and reasoning > completion:
        completion += reasoning
    return prompt + completion


def settle_physical(reservation: Reservation, response: Any) -> None:
    """Without reported usage the call keeps its whole reservation, as failed
    and interrupted calls do."""
    used = _reported_tokens(response)
    if used is None:
        return
    # W4: the EUR ledger records the settled call here.
    try:
        settle_provider(
            reservation.owner,
            reservation.host,
            reservation.day,
            reservation.tokens - min(used, reservation.tokens),
            app=reservation.app,
            db_path=reservation.db_path,
        )
    except Exception:
        # The provider has already answered; failing here would only retry it.
        logger.warning("Provider reservation not settled; keeping it", exc_info=True)


def reserve_decision_physical(tokens: int, call_limit: int, token_limit: int) -> None:
    from co_scientist.platform.db.decision_usage import reserve_decision

    db_path = current_db_path()
    reserve_decision(tokens, call_limit, token_limit, db_path)
    reserve_provider(_client.get(), _host.get(), tokens, app=_app.get(), db_path=db_path)


def block_decision_provider(seconds: float) -> None:
    from co_scientist.platform.db.decision_usage import block_decisions

    block_decisions(seconds, current_db_path())
