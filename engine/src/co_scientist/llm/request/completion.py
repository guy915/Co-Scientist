"""Request preparation and shaping for LiteLLM completion calls.

Builds the keyword arguments for ``litellm.acompletion`` calls made by the
wrappers in ``co_scientist.llm``: response-format selection (including the
json_object provider-capability shim), temperature clamping, prompt
debug-artifact saving, and extraction of the text content from completion
responses.

Two pieces live in sibling modules and are re-exported here so this
module's namespace stays the one every caller and test speaks to:
thinking/reasoning argument shaping (``co_scientist.llm.request.thinking``) and
response-content extraction (``co_scientist.llm.request.response``).
"""

import asyncio
import functools
import logging
import time
import warnings
from dataclasses import dataclass
from typing import Any

import litellm
from litellm.exceptions import Timeout as LiteLLMTimeout

from co_scientist import prompts
from co_scientist.config.env_vars import parse_timeout_env

# Re-exported: the thinking token floor moved out with _apply_thinking_args,
# but it was importable from this module before the split.
from co_scientist.constants import (
    THINKING_FLOOR_MAX_TOKENS as THINKING_FLOOR_MAX_TOKENS,
)
from co_scientist.exceptions import LLMTimeoutError
from co_scientist.llm.admission.call_budget import record_provider_request
from co_scientist.llm.admission.credentials import current_api_key
from co_scientist.llm.admission.free_policy import enforce_free_request
from co_scientist.llm.request.response import (
    _empty_content_diagnosis as _empty_content_diagnosis,
)
from co_scientist.llm.request.response import (
    _extract_completion_content as _extract_completion_content,
)
from co_scientist.llm.request.schema import (
    _ANSWER_DISCIPLINE as _ANSWER_DISCIPLINE,
)
from co_scientist.llm.request.schema import (
    _apply_response_format as _apply_response_format,
)
from co_scientist.llm.request.schema import (
    _apply_schema_response_format as _apply_schema_response_format,
)
from co_scientist.llm.request.schema import (
    _inject_schema_into_prompt as _inject_schema_into_prompt,
)
from co_scientist.llm.request.thinking import (
    _GATEWAY_MODELS as _GATEWAY_MODELS,
)
from co_scientist.llm.request.thinking import (
    _JSON_OBJECT_ONLY_MODEL_FAMILIES as _JSON_OBJECT_ONLY_MODEL_FAMILIES,
)
from co_scientist.llm.request.thinking import (
    _apply_thinking_args as _apply_thinking_args,
)
from co_scientist.llm.request.thinking import (
    annotate_failure_context as annotate_failure_context,
)
from co_scientist.llm.request.thinking import (
    deepseek_thinking_extra_body as deepseek_thinking_extra_body,
)
from co_scientist.llm.request.thinking import (
    effective_max_tokens as effective_max_tokens,
)
from co_scientist.llm.request.thinking import (
    failure_context_text as failure_context_text,
)
from co_scientist.llm.request.thinking import (
    model_reasons as model_reasons,
)
from co_scientist.llm.request.thinking import (
    reasoning_effort_args as reasoning_effort_args,
)
from co_scientist.llm.request.thinking import (
    scoped_minimal_reasoning as scoped_minimal_reasoning,
)
from co_scientist.llm.telemetry import (
    record_completion_failure as _record_completion_failure,
)
from co_scientist.llm.telemetry import (
    record_completion_response as _record_completion_response,
)

logger = logging.getLogger(__name__)

# Wall-clock ceiling for a single completion call. Without one, a provider
# that accepts a request and then stops responding parks the caller forever:
# a durable run holds its task, and with a single worker nothing else
# progresses. The default is deliberately generous rather than tight --
# reasoning models legitimately spend minutes on a large meta-review or
# ranking synthesis, and a ceiling that cuts those off would turn healthy
# long calls into failures. It exists to bound the pathological case, not to
# police normal latency. Set the env var to 0 (or a negative value) to
# disable the ceiling entirely.
LLM_TIMEOUT_ENV = "COSCIENTIST_LLM_TIMEOUT_SECONDS"
DEFAULT_LLM_TIMEOUT_SECONDS = 600.0


def llm_timeout_seconds() -> float | None:
    """Return the per-call wall-clock ceiling, or None when disabled.

    Read from the environment on every call rather than cached, so tests and
    operators can change the ceiling without restarting the process.

    Returns:
        The timeout in seconds, or None when it is disabled (a value of zero
        or less) or the configured value is not a number.
    """
    return parse_timeout_env(LLM_TIMEOUT_ENV, DEFAULT_LLM_TIMEOUT_SECONDS)


def _apply_timeout(completion_args: dict[str, Any]) -> None:
    """Asks the provider client to give up on its own, in place.

    This is only the first of the two ceilings every completion runs under,
    and it is the weaker one: the argument binds only if litellm plumbs it
    through to the transport for the provider in use. Both call sites
    (``call_llm`` via ``_base_completion_args`` and the tool loop) also await
    through ``_acompletion_within_timeout``, which cancels the coroutine
    regardless -- a hang that never reached the transport would otherwise be
    unbounded.

    Args:
        completion_args: The in-progress completion kwargs dict; mutated with
            "timeout" unless the ceiling is disabled.
    """
    timeout = llm_timeout_seconds()
    if timeout is not None:
        completion_args["timeout"] = timeout


# Extra head-room over the value handed to litellm, so that when the
# provider client honours its own deadline it is the one to fail -- with a
# provider-specific error naming the endpoint -- and this ceiling only fires
# for a hang that never reached the transport at all.
_TIMEOUT_GRACE_SECONDS = 30.0


async def _acompletion_within_timeout(
    completion_args: dict[str, Any], model_name: str
) -> Any:
    """Await one completion under a hard wall-clock ceiling.

    ``_build_completion_args`` already asks the provider client to time out,
    but that only binds if litellm passes the argument through to the
    transport for the provider in use. Wrapping the await guarantees the
    coroutine is cancelled either way, which is what keeps a wedged provider
    from parking a durable task indefinitely. Both ``litellm.acompletion``
    call sites -- ``call_llm`` and the tool loop -- await through this.

    This is also the single point that records per-call telemetry (tokens,
    latency, error kind) into ``co_scientist.llm.telemetry`` -- see that
    module's docstring for why an in-memory aggregate here rather than a
    per-call log line or database row. A cache hit never reaches this
    function, so every call recorded here is a genuine physical attempt.

    Args:
        completion_args: Keyword arguments for ``litellm.acompletion``.
        model_name: Model name, for the error message.

    Returns:
        The completion response.

    Raises:
        LLMTimeoutError: If the call exceeds the configured ceiling.
    """
    # `api_key` may be a deployment credential added by a caller. Only the
    # scoped credential seam records run-level BYOK provenance.
    byok = bool(current_api_key())
    zero_cost_admitted = (
        await enforce_free_request(completion_args, byok=byok) and not byok
    )
    record_provider_request()
    start = time.monotonic()
    try:
        response = await _run_completion(completion_args, model_name)
    except (LLMTimeoutError, LiteLLMTimeout) as exc:
        message = str(exc)
        if isinstance(exc, LiteLLMTimeout):
            message = (
                f"LLM call to {model_name} timed out without a response; "
                "provider outcome may be unknown"
            )
        timeout_error = LLMTimeoutError(
            message, zero_cost_admitted=zero_cost_admitted
        )
        _record_completion_failure(
            model_name, timeout_error, time.monotonic() - start
        )
        raise timeout_error from exc
    except Exception as exc:
        _record_completion_failure(model_name, exc, time.monotonic() - start)
        raise
    _record_completion_response(model_name, response, time.monotonic() - start)
    return response


async def _run_completion(
    completion_args: dict[str, Any], model_name: str
) -> Any:
    """Awaits the completion call, translating a hung provider's timeout.

    Split out of ``_acompletion_within_timeout`` so that function can wrap
    exactly one try/except around this call for telemetry, regardless of
    which branch below is taken.

    Args:
        completion_args: Keyword arguments for ``litellm.acompletion``.
        model_name: Model name, for the error message.

    Returns:
        The completion response.

    Raises:
        LLMTimeoutError: If the call exceeds the configured ceiling.
    """
    timeout = llm_timeout_seconds()
    if timeout is None:
        return await litellm.acompletion(**completion_args)
    try:
        return await asyncio.wait_for(
            litellm.acompletion(**completion_args),
            timeout=timeout + _TIMEOUT_GRACE_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise LLMTimeoutError(
            f"LLM call to {model_name} exceeded {timeout}s without a "
            f"response; set {LLM_TIMEOUT_ENV} to change or "
            "disable this ceiling"
        ) from exc


async def _save_prompt_if_named(
    prompt: str,
    run_id: str | None,
    prompt_name: str | None,
    prompt_metadata: dict[str, Any] | None,
) -> None:
    """Saves the filled-in prompt to disk when a prompt name is given.

    Unified save policy for every LLM call site: the prompt is saved
    whenever ``prompt_name`` is provided, under ``run_id or "unknown"``.
    Every write is still globally gated by the ``COSCIENTIST_SAVE_PROMPTS``
    env check inside ``prompts.save_prompt_to_disk`` (which also emits the
    canonical debug log for each saved prompt). The blocking file write runs
    in a worker thread so gathered LLM calls don't stall the event loop.

    ``save_prompt_to_disk`` is resolved through the ``prompts`` module at
    call time so tests can monkeypatch it there.

    Args:
        prompt: The filled-in prompt content to save.
        run_id: Optional run identifier; ``None`` falls back to "unknown".
        prompt_name: Optional debug-artifact name; ``None`` disables saving.
        prompt_metadata: Optional metadata appended to the saved file.
    """
    if prompt_name is None:
        return
    await asyncio.to_thread(
        prompts.save_prompt_to_disk,
        run_id=run_id or "unknown",
        prompt_name=prompt_name,
        content=prompt,
        metadata=prompt_metadata,
    )


# Suppress Pydantic serialization warnings from LiteLLM globally
# these occur when LiteLLM response objects (Pydantic models) are serialized
# and have mismatched field counts between streaming/non-streaming responses
warnings.filterwarnings(
    "ignore", message=r".*Pydantic serializer warnings.*", category=UserWarning
)


def _clamp_temperature(model_name: str, temperature: float) -> float:
    """Clamps temperature to model-specific minimums.

    Gemini 3 models require temperature >= 1.0 to avoid degraded performance.

    Args:
        model_name: LLM model identifier.
        temperature: Requested sampling temperature.

    Returns:
        The temperature to actually use for the call.
    """
    if "gemini-3" in model_name.lower() and temperature < 1.0:
        logger.debug(
            "clamping temperature %s -> 1.0 for gemini 3 model "
            "(gemini 3 requires temp >= 1.0 to avoid degraded performance)",
            temperature,
        )
        return 1.0
    return temperature


# Exact endpoint evidence, ahead of the generic gateway downgrade. Gemma's
# endpoint has JSON object mode only; pinned Qwen has native structured output
# but no JSON object mode (a JSON object request hard-404ed on 2026-09-25).
_SCHEMA_ROUTE_OVERRIDES = {
    "openrouter/google/gemma-4-26b-a4b-it:free": False,
    "openrouter/qwen/qwen3.8-27b:free": True,
}


@functools.cache
def _supports_json_schema_response_format(model_name: str) -> bool:
    """Checks whether a model accepts the json_schema response format.

    The result is a process-static property of the model, so it is cached to
    avoid re-running litellm's registry lookup on every LLM call and retry.

    Args:
        model_name: Model name in litellm format.

    Returns:
        False when the model belongs to a known json_object-only family,
        when it is an exact route with a known provider capability mismatch,
        when it is one of the declared OpenRouter gateway models without a
        proven native-schema endpoint, or when
        litellm's capability registry reports no json_schema support. True
        otherwise, including when the registry lookup itself raises, so the
        default json_schema path is preserved for unknown models.
    """
    lowered = model_name.lower()
    if any(family in lowered for family in _JSON_OBJECT_ONLY_MODEL_FAMILIES):
        return False
    if lowered in _SCHEMA_ROUTE_OVERRIDES:
        return _SCHEMA_ROUTE_OVERRIDES[lowered]
    if lowered in _GATEWAY_MODELS:
        # Declared rather than left to the registry lookup below: every
        # rung in a gateway chain is paired with ``require_parameters``
        # (see ``llm.request.gateway_routing._GATEWAY_PROVIDER``), which turns
        # an unsupported ``response_format`` into a hard 404 instead of a soft
        # degradation, and litellm's own answer for a free variant has been
        # observed to flip between True and False across runs on the same day --
        # these are volatile stealth/free listings, not stable capability data.
        # At least one declared fallback
        # (``nvidia/nemotron-3.5-lightning:free``) lists no ``response_format``
        # support at all in its own OpenRouter listing, so json_object is the
        # only format proven safe across every rung a chain might actually land
        # on.
        return False
    try:
        return bool(litellm.supports_response_schema(model=model_name))
    except Exception:
        return True


def _base_completion_args(
    prompt: str, model_name: str, max_tokens: int, temperature: float
) -> dict[str, Any]:
    """Builds the model/messages/token/timeout base of a completion call.

    Args:
        prompt: The prompt to send to the LLM.
        model_name: Model name in litellm format.
        max_tokens: Maximum tokens in response.
        temperature: Sampling temperature.

    Returns:
        The starting keyword arguments, before response-format and thinking
        options are applied.
    """
    completion_args: dict[str, Any] = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        # Silently drop params a provider doesn't accept instead of
        # raising, since not every model/provider supports every arg.
        "drop_params": True,
    }

    _apply_timeout(completion_args)

    return completion_args


def _apply_api_key(
    completion_args: dict[str, Any], api_key: str | None
) -> None:
    """Sets a per-call provider credential, in place, when one is given.

    litellm accepts ``api_key`` on the completion call and prefers it
    over the provider credential read from the environment, which is
    exactly the bring-your-own-key contract: the run's key overrides
    the deployment's for this call only, without mutating any shared
    state. Absent a key the argument is omitted entirely so the call
    keeps litellm's normal environment resolution.

    Args:
        completion_args: The in-progress completion kwargs dict; mutated.
        api_key: Provider key for this call, or None to leave env
            resolution untouched.
    """
    if api_key:
        completion_args["api_key"] = api_key


@dataclass(frozen=True)
class CompletionShape:
    """How one completion's response is shaped and reasoned about.

    Attributes:
        force_json: Try to force JSON mode (model support varies).
        json_schema: Schema constraining the response format, if any.
        enable_thinking: Whether DeepSeek thinking mode is requested; False
            opts a high-frequency call site out of the reasoning spend.
    """

    force_json: bool = False
    json_schema: dict[str, Any] | None = None
    enable_thinking: bool = True


def _build_completion_args(
    prompt: str,
    model_name: str,
    max_tokens: int,
    temperature: float,
    shape: CompletionShape,
) -> dict[str, Any]:
    """Builds the keyword arguments for a ``litellm.acompletion`` call.

    The bring-your-own-key credential is applied afterwards by the call
    site (see ``_apply_api_key``): it rides the task-scoped context from
    ``llm.admission.credentials`` rather than this argument list.

    Args:
        prompt: The prompt to send to the LLM.
        model_name: Model name in litellm format.
        max_tokens: Maximum tokens in response.
        temperature: Sampling temperature.
        shape: Response-format and thinking-mode selection for this call.

    Returns:
        Keyword arguments ready to pass to ``litellm.acompletion``.
    """
    completion_args = _base_completion_args(
        prompt, model_name, max_tokens, temperature
    )

    _apply_response_format(
        completion_args, prompt, model_name, shape.force_json, shape.json_schema
    )

    _apply_thinking_args(completion_args, model_name, shape.enable_thinking)

    return completion_args
