from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import replace
from typing import Any

import httpx

from co_scientist.platform.llm.admission.call_budget import record_provider_request
from co_scientist.platform.llm.admission.service import (
    block_decision_provider,
    reserve_decision_physical,
)
from co_scientist.platform.llm.decisions.settings import DecisionSettings, DecisionUnavailableError
from co_scientist.platform.llm.decisions.types import DecisionResult, Question, parse_result
from co_scientist.platform.llm.telemetry import ModelCallStats, record_call


def _body_and_tokens(
    state: str | dict[str, Any], questions: dict[str, Question], settings: DecisionSettings
) -> tuple[dict[str, Any], int]:
    if not questions or len(questions) > settings.max_questions or not all(questions):
        raise DecisionUnavailableError("decision question limit exceeded")
    rendered = {name: question.body() for name, question in questions.items()}
    body = {"model": settings.model, "state": state, "questions": rendered}
    serialized = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(serialized) > settings.max_input_bytes:
        raise DecisionUnavailableError("decision input is too large")
    # A byte bound avoids silently truncating state with an unrelated tokenizer.
    state_bytes = len(json.dumps(state, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    tokens = 0
    for question in rendered.values():
        bound = state_bytes + len(json.dumps(question, ensure_ascii=False).encode("utf-8")) + 1024
        if bound > settings.context_tokens:
            raise DecisionUnavailableError("decision context limit exceeded")
        tokens += bound
    return body, tokens


class SystemOneClient:
    def __init__(
        self, settings: DecisionSettings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.settings = settings
        self._transport = transport

    async def decide(
        self, state: str | dict[str, Any], questions: dict[str, Question]
    ) -> DecisionResult:
        settings = self.settings
        settings.validate()
        if not settings.configured:
            raise DecisionUnavailableError("decision provider is not configured")
        if self._transport is None and os.getenv("COSCIENTIST_FORCE_OFFLINE") == "1":
            raise DecisionUnavailableError("offline execution cannot contact decision providers")
        body, tokens = _body_and_tokens(state, questions, settings)
        reserve_decision_physical(tokens, settings.max_calls_per_day, settings.max_tokens_per_day)
        record_provider_request()
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(self._send(body, questions), settings.timeout_seconds)
        except BaseException as error:
            record_call(
                "liquid/d1:free",
                ModelCallStats(
                    calls=1,
                    decision_calls=1,
                    requested_models={"liquid/d1:free": 1},
                    errors={type(error).__name__: 1},
                    latency_seconds=time.monotonic() - start,
                ),
            )
            raise
        record_call(
            "liquid/d1:free",
            ModelCallStats(
                calls=1,
                decision_calls=1,
                observed_model_calls=1,
                reported_usage_calls=int(result.input_tokens is not None),
                priced_usage_calls=int(result.input_tokens is not None),
                requested_models={"liquid/d1:free": 1},
                prompt_tokens=result.input_tokens or 0,
                latency_seconds=time.monotonic() - start,
            ),
        )
        return result

    async def _send(self, body: dict[str, Any], questions: dict[str, Question]) -> DecisionResult:
        settings = self.settings
        async with (
            httpx.AsyncClient(
                transport=self._transport,
                timeout=settings.timeout_seconds,
                trust_env=False,
                follow_redirects=False,
                headers={"Authorization": f"Bearer {settings.api_key}"},
            ) as client,
            client.stream(
                "POST", f"{settings.base_url.rstrip('/')}/systemone", json=body
            ) as response,
        ):
            if response.status_code == 429:
                try:
                    delay = float(response.headers.get("Retry-After", "60"))
                except ValueError:
                    delay = 60
                block_decision_provider(max(1, min(delay, 86400)))
                raise DecisionUnavailableError("decision provider rate limited")
            if response.status_code != 200:
                raise DecisionUnavailableError("decision provider request failed")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 262_144:
                    raise DecisionUnavailableError("decision response is too large")
            result = parse_result(json.loads(content), questions)
            rate_limits = {
                key: response.headers[key][:128]
                for key in (
                    "x-ratelimit-limit",
                    "x-ratelimit-remaining",
                    "x-ratelimit-reset",
                    "x-ratelimit-limit-requests",
                    "x-ratelimit-limit-tokens",
                    "ratelimit",
                    "ratelimit-policy",
                    "retry-after",
                )
                if key in response.headers
            }
            return replace(result, rate_limits=rate_limits)
