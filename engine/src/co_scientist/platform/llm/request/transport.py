"""Streaming consumers own silence and total deadlines; this layer bounds
establishment.
"""

import asyncio
import time
from collections.abc import Callable
from contextvars import copy_context
from typing import Any

from litellm.exceptions import Timeout as LiteLLMTimeout
from opentelemetry.trace import Span

from co_scientist.core.exceptions import LLMTimeoutError, ProviderAdmissionError
from co_scientist.platform.db.admission import ProviderReservation
from co_scientist.platform.llm.admission.call_budget import record_provider_request
from co_scientist.platform.llm.admission.free_policy import enforce_free_request
from co_scientist.platform.llm.admission.service import reserve_physical, settle_physical
from co_scientist.platform.llm.admission.spend import paid_dispatch_config, require_enabled
from co_scientist.platform.llm.request.azure import LUNA, NANO
from co_scientist.platform.llm.request.backend import active_backend
from co_scientist.platform.llm.request.thinking import apply_provider_constraints
from co_scientist.platform.llm.telemetry import (
    end_request_span,
    record_completion_failure,
    record_completion_response,
    start_request_span,
)


class _CompletionStream:
    """Consumption may finish in another context; usage belongs to the
    initiating task.
    """

    def __init__(
        self,
        response: Any,
        model: str,
        start: float,
        span: Span,
        receipt: ProviderReservation | None,
    ) -> None:
        self._response = response
        self._iterator = response.__aiter__()
        self._model = model
        self._start = start
        self._span = span
        self._context = copy_context()
        self._last = response
        self._done = False
        self._receipt = receipt

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
            try:
                settle_physical(self._receipt, self._last)
            except BaseException as settlement_error:
                self._context.run(record_completion_failure, self._model, settlement_error, latency)
                end_request_span(self._span, self._last, settlement_error)
                raise
            self._context.run(record_completion_response, self._model, self._last, latency)
        else:
            self._context.run(record_completion_failure, self._model, error, latency)
        end_request_span(self._span, self._last, error)

    async def aclose(self) -> None:
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
        return await asyncio.wait_for(backend.complete(**args), timeout=timeout + grace)
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
    before_dispatch: Callable[[], None] | None = None,
) -> Any:
    """No retry occurs at this physical-call seam; stream clocks remain
    caller-owned.
    """
    from co_scientist.core.config import settings

    require_enabled()
    native_model = str(completion_args.get("model", "")).replace("azure/responses/", "azure/")
    if byok and native_model in (LUNA, NANO):
        # The native deployment client owns its key; a caller key cannot
        # establish caller funding for this route.
        raise ProviderAdmissionError("No model is available right now")
    apply_provider_constraints(completion_args, model_name)
    zero_cost = await enforce_free_request(completion_args, byok=byok)
    record_provider_request()
    receipt = None
    if not byok:
        # Bound requests that previously delegated an unbounded output default
        # to the SDK. Admission covers every scientific and app retry here.
        if "max_completion_tokens" not in completion_args:
            completion_args.setdefault("max_tokens", settings.app_llm_max_output_tokens)
        receipt = reserve_physical(completion_args)
    if before_dispatch is not None:
        before_dispatch()
    require_enabled()
    if receipt is not None and receipt.paid:
        paid_dispatch_config(receipt.db_path)
    span = start_request_span(model_name, completion_args)
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
        end_request_span(span, None, error)
        raise error from exc
    except BaseException as exc:
        record_completion_failure(model_name, exc, time.monotonic() - start)
        end_request_span(span, None, exc)
        raise
    if completion_args.get("stream"):
        return _CompletionStream(response, model_name, start, span, receipt)
    try:
        settle_physical(receipt, response)
    except BaseException as settlement_error:
        record_completion_failure(model_name, settlement_error, time.monotonic() - start)
        end_request_span(span, response, settlement_error)
        raise
    record_completion_response(model_name, response, time.monotonic() - start)
    end_request_span(span, response, None)
    return response
