from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from fastapi import HTTPException

from co_scientist.core.config import settings
from co_scientist.platform import db

_client: ContextVar[str] = ContextVar("provider_usage_client", default="")


@contextmanager
def scoped_client(owner: str) -> Iterator[None]:
    token = _client.set(owner)
    try:
        yield
    finally:
        _client.reset(token)


def reserve(request: dict[str, Any]) -> None:
    output = request.get("max_completion_tokens", request.get("max_tokens"))
    if (
        not isinstance(output, int)
        or isinstance(output, bool)
        or not 0 < output <= settings.app_llm_max_output_tokens
        or request.get("n", 1) != 1
    ):
        raise HTTPException(status_code=429, detail="completion output budget exceeded")
    content = {key: request.get(key) for key in ("messages", "tools", "functions")}
    input_bytes = len(json.dumps(content, ensure_ascii=False).encode("utf-8"))
    if input_bytes > settings.app_llm_max_input_bytes:
        raise HTTPException(status_code=429, detail="completion input budget exceeded")
    # Reserve a conservative byte-token upper bound and the entire output cap;
    # failures and interrupted streams never refund potentially billed usage.
    tokens = input_bytes + 1024 + output
    owner = _client.get()
    day = int(db.current_time() // 86400)
    with db.transaction() as conn:
        conn.execute("DELETE FROM app_llm_usage WHERE day<?", (day,))
        global_calls, global_tokens = conn.execute(
            "SELECT COALESCE(SUM(calls),0),COALESCE(SUM(tokens),0) FROM app_llm_usage WHERE day=?",
            (day,),
        ).fetchone()
        row = conn.execute(
            "SELECT calls,tokens FROM app_llm_usage WHERE day=? AND client_id=?",
            (day, owner),
        ).fetchone()
        calls, used = (row["calls"], row["tokens"]) if row else (0, 0)
        if (
            calls + 1 > settings.app_llm_client_calls_per_day
            or used + tokens > settings.app_llm_client_tokens_per_day
            or global_calls + 1 > settings.app_llm_global_calls_per_day
            or global_tokens + tokens > settings.app_llm_global_tokens_per_day
        ):
            raise HTTPException(status_code=429, detail="daily completion budget exceeded")
        conn.execute(
            "INSERT INTO app_llm_usage VALUES (?,?,1,?) "
            "ON CONFLICT(day,client_id) DO UPDATE "
            "SET calls=calls+1,tokens=tokens+excluded.tokens",
            (day, owner, tokens),
        )
