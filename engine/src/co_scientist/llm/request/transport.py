"""Shared physical provider dispatch, admission, deadlines and telemetry.

Streaming consumers own their silence and total deadlines. This layer bounds
only establishment and records the physical call when consumption finishes.
"""

import asyncio
import time
from contextvars import copy_context
from typing import Any

from litellm.exceptions import Timeout as LiteLLMTimeout

from co_scientist.exceptions import LLMTimeoutError
from co_scientist.llm.admission.call_budget import record_provider_request
from co_scientist.llm.admission.free_policy import enforce_free_request
from co_scientist.llm.request.backend import active_backend
from co_scientist.llm.telemetry import (
    record_completion_failure,
    record_completion_response,
)


class _CompletionStream:
    """Observe usage without buffering, replaying or owning stream clocks."""

    def __init__(self, response: Any, model: str, start: float) -> None:
        self._response = response
        self._iterator = response.__aiter__()
        self._model = model
        self._start = start
        self._context = copy_context()
        self._last = response
        self._done = False

    def __aiter__(self) -> "_CompletionStream":
        return self

    async def __anext__(self) -> Any:
        try:
            chunk = await self._iterator.__anext__()
        except StopAsyncIteration:
            self._finish()
            raise
        except BaseException as error:
            self._finish(error)
            raise
        if getattr(chunk, "usage", None) is not None:
            self._last = chunk
        return chunk

    def _finish(self, error: BaseException | None = None) -> None:
        if self._done:
            return
        self._done = True
        latency = time.monotonic() - self._start
        if error is None:
            self._context.run(
                record_completion_response, self._model, self._last, latency
            )
        else:
            self._context.run(
                record_completion_failure, self._model, error, latency
            )

    async def aclose(self) -> None:
        """Close the upstream on cancellation or a consumer deadline."""
        self._finish(asyncio.CancelledError())
        close = getattr(self._response, "aclose", None)
        if close is not None:
            await close()


async def _await_provider(
    args: dict[str, Any], model: str, timeout: float | None, grace: float
) -> Any:
    backend = active_backend()
    if timeout is None:
        return await backend.complete(**args)
    try:
        return await asyncio.wait_for(
            backend.complete(**args), timeout=timeout + grace
        )
    except asyncio.TimeoutError as exc:
        raise LLMTimeoutError(
            f"LLM call to {model} exceeded {timeout}s without a response"
        ) from exc


async def complete_request(
    completion_args: dict[str, Any],
    model_name: str,
    *,
    byok: bool,
    timeout_seconds: float | None,
    timeout_grace_seconds: float = 0.0,
) -> Any:
    """Admit, reserve and observe exactly one provider request.

    No retries occur here. Stream establishment uses the supplied deadline;
    chunk consumption remains under the caller's silence/total policy.
    """
    zero_cost = await enforce_free_request(completion_args, byok=byok)
    record_provider_request()
    start = time.monotonic()
    try:
        response = await _await_provider(
            completion_args, model_name, timeout_seconds, timeout_grace_seconds
        )
    except (LLMTimeoutError, LiteLLMTimeout) as exc:
        error = LLMTimeoutError(
            f"LLM call to {model_name} timed out without a response; "
            "provider outcome may be unknown",
            zero_cost_admitted=zero_cost and not byok,
        )
        record_completion_failure(model_name, error, time.monotonic() - start)
        raise error from exc
    except BaseException as exc:
        record_completion_failure(model_name, exc, time.monotonic() - start)
        raise
    if completion_args.get("stream"):
        return _CompletionStream(response, model_name, start)
    record_completion_response(model_name, response, time.monotonic() - start)
    return response
