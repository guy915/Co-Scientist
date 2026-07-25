"""Request preparation and shaping for LiteLLM completion calls.

Builds the keyword arguments for ``litellm.acompletion`` calls made by the
wrappers in ``co_scientist.llm``: response-format selection (including the
json_object provider-capability shim), temperature clamping, prompt
debug-artifact saving, and extraction of the text content from completion
responses.
"""

import asyncio
import contextlib
import functools
import json
import logging
import warnings
from dataclasses import dataclass
from typing import Any, cast

import litellm

from co_scientist import prompts
from co_scientist.config.env_vars import parse_timeout_env
from co_scientist.constants import THINKING_FLOOR_MAX_TOKENS
from co_scientist.exceptions import LLMTimeoutError

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


# Provider-capability shim: some providers reject
# response_format={"type": "json_schema", ...} outright (DeepSeek returns an
# invalid-request error). For those models every schema'd call is downgraded,
# per call, to {"type": "json_object"} with the schema restated as prompt
# text, and missing required fields are back-filled with empty defaults
# before schema validation (json_object mode has no server-side schema
# enforcement, so nested required fields are routinely omitted). Models that
# support json_schema are untouched.
#
# Families listed here are checked BEFORE litellm's capability registry:
# litellm's cost map marks deepseek/* as supporting response schema, but the
# DeepSeek API only accepts json_object, so the registry alone cannot be
# trusted for these providers.
_JSON_OBJECT_ONLY_MODEL_FAMILIES: tuple[str, ...] = ("deepseek",)


def _is_dashscope(model_name: str) -> bool:
    """Whether ``model_name`` routes through Alibaba Cloud DashScope."""
    return model_name.lower().startswith("dashscope/")


def deepseek_thinking_extra_body(
    model_name: str, *, enabled: bool = True
) -> dict[str, Any]:
    """Return an ``extra_body`` selecting DeepSeek V4 thinking mode.

    DeepSeek V4 (pro/flash) are reasoning models: the chain of thought is
    returned separately as ``reasoning_content`` and never mixed into
    ``content``, so structured/JSON parsing is unaffected as long as the
    ``max_tokens`` budget leaves room for the answer after the reasoning
    spend. Budgets are not sized for that per node -- most predate thinking
    being switched on everywhere -- so ``_apply_thinking_args`` raises any
    thinking call to ``THINKING_FLOOR_MAX_TOKENS``. Non-DeepSeek models get
    an empty dict.

    Thinking is on for every node. ``enabled=False`` remains the seam for
    opting a call site out; nothing uses it today. Any future opt-out is a
    latency decision, and the two call sites where it would pay are the
    ranking tournament's pairwise matchups, which run O(n^2) times per cycle
    (``agents/ranking/ranking_debate.py``), and supervisor allocation, which
    runs once per loop point on the run's serial spine where nothing else is
    executing (``agents/supervisor/supervisor_decision.py``).

    DashScope (Alibaba Cloud) serves the same DeepSeek models behind its
    OpenAI-compatible endpoint but controls thinking with a different knob:
    ``enable_thinking`` (bool), with thinking OFF by default. The explicit
    field below covers both providers' defaults.

    Args:
        model_name: Model name in litellm format.
        enabled: Whether to request thinking mode. False explicitly disables
            it, which is not the same as omitting the field -- the API's own
            default is enabled.

    Returns:
        ``{"thinking": {"type": "enabled"|"disabled"}}`` for DeepSeek models,
        ``{"enable_thinking": bool}`` for DeepSeek-on-DashScope, else ``{}``.
    """
    lowered = model_name.lower()
    if any(family in lowered for family in _JSON_OBJECT_ONLY_MODEL_FAMILIES):
        if _is_dashscope(model_name):
            return {"enable_thinking": enabled}
        return {"thinking": {"type": "enabled" if enabled else "disabled"}}
    return {}


def reasoning_effort_args(
    model_name: str, *, enabled: bool = True
) -> dict[str, Any]:
    """Kwargs selecting the reasoning tier, when supported.

    ``high`` is the floor, not a high setting. DeepSeek implements exactly
    two tiers, ``high`` and ``max``, and accepts OpenAI's lower names
    (``low``, ``medium``) as aliases onto ``high`` -- the parameter and its
    vocabulary are OpenAI's, and DeepSeek only supports the top of that
    ladder. There is no cheaper way to think than this; the rung below is
    ``enabled=False``. ``high`` is also DeepSeek's default once thinking is
    on, so this field is belt-and-braces: litellm 1.80.x strips
    ``reasoning_effort`` from the body outright (BerriAI/litellm#27439), and
    since the value equals the default, that bug is inert. Sending it keeps
    the intent explicit and the call correct once the fix lands.

    Empty for models without a thinking mode, when thinking is disabled for
    the call, and on DashScope -- Model Studio does accept the parameter
    (``high``/``max``, default ``high``), but the only value wanted there is
    that default.

    Args:
        model_name: Model name in litellm format.
        enabled: Whether thinking mode is requested for this call.

    Returns:
        ``{"reasoning_effort": "high"}`` when the tier applies, else ``{}``.
    """
    if (
        enabled
        and deepseek_thinking_extra_body(model_name)
        and not _is_dashscope(model_name)
    ):
        return {"reasoning_effort": "high"}
    return {}


@functools.cache
def _supports_json_schema_response_format(model_name: str) -> bool:
    """Checks whether a model accepts the json_schema response format.

    The result is a process-static property of the model, so it is cached to
    avoid re-running litellm's registry lookup on every LLM call and retry.

    Args:
        model_name: Model name in litellm format.

    Returns:
        False when the model belongs to a known json_object-only family or
        when litellm's capability registry reports no json_schema support.
        True otherwise, including when the registry lookup itself raises, so
        the default json_schema path is preserved for unknown models.
    """
    lowered = model_name.lower()
    if any(family in lowered for family in _JSON_OBJECT_ONLY_MODEL_FAMILIES):
        return False
    try:
        return bool(litellm.supports_response_schema(model=model_name))
    except Exception:
        return True


def _inject_schema_into_prompt(prompt: str, json_schema: dict[str, Any]) -> str:
    """Appends the JSON schema to the prompt for json_object-only models.

    Downgrading to the json_object response format loses the server-side
    schema constraint, so the schema is restated as prompt text to keep the
    model aware of the required structure.

    Args:
        prompt: The original user prompt.
        json_schema: JSON schema dict (may have a nested "schema" key).

    Returns:
        The prompt with the schema instruction block appended.
    """
    actual_schema = json_schema.get("schema", json_schema)
    schema_str = json.dumps(actual_schema, indent=2)
    return (
        prompt + "\n\n---\nRESPOND WITH VALID JSON ONLY. "
        "Your output MUST strictly match this JSON schema "
        "(all required fields must be present):\n" + schema_str
    )


def _apply_schema_response_format(
    completion_args: dict[str, Any],
    prompt: str,
    model_name: str,
    json_schema: dict[str, Any],
) -> None:
    """Sets the response_format for a call with a JSON schema, in place.

    Prefers the model's native json_schema format; models that reject it
    fall back to the json_object shim, restating the schema as prompt text.

    Args:
        completion_args: The in-progress completion kwargs dict; mutated.
        prompt: The original prompt, rebuilt into "messages" for the shim.
        model_name: Model name in litellm format.
        json_schema: JSON schema to constrain the response format.
    """
    if _supports_json_schema_response_format(model_name):
        completion_args["response_format"] = {
            "type": "json_schema",
            "json_schema": json_schema,
        }
        return

    # Provider-capability shim: this model rejects json_schema, so downgrade
    # to json_object and restate the schema in the prompt. The cache keys
    # above stay on the original prompt.
    logger.debug(
        "model %s does not support json_schema response format;"
        " downgrading to json_object with schema in prompt",
        model_name,
    )
    shimmed_content = _inject_schema_into_prompt(prompt, json_schema)
    completion_args["messages"] = [{"role": "user", "content": shimmed_content}]
    completion_args["response_format"] = {"type": "json_object"}


def _apply_response_format(
    completion_args: dict[str, Any],
    prompt: str,
    model_name: str,
    force_json: bool,
    json_schema: dict[str, Any] | None,
) -> None:
    """Sets the response_format for a completion call, in place.

    With a schema, defers to ``_apply_schema_response_format`` (native
    json_schema, or the json_object shim). Without one, force_json requests
    plain json_object mode.

    Args:
        completion_args: The in-progress completion kwargs dict; mutated in
            place with "response_format" and, for the shim, "messages".
        prompt: The original user prompt, used to rebuild "messages" when the
            json_object shim applies.
        model_name: Model name in litellm format.
        force_json: If True, try to force JSON mode when no schema is given.
        json_schema: Optional JSON schema to constrain the response format.
    """
    if json_schema:
        _apply_schema_response_format(
            completion_args, prompt, model_name, json_schema
        )
    elif force_json:
        completion_args["response_format"] = {"type": "json_object"}


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

    # Ask the provider client to give up on its own. call_llm additionally
    # wraps the await in a hard asyncio ceiling, because this argument only
    # binds if litellm plumbs it through to the transport for the provider in
    # use, and a hang that never reaches the transport would otherwise be
    # unbounded.
    timeout = llm_timeout_seconds()
    if timeout is not None:
        completion_args["timeout"] = timeout

    return completion_args


def _apply_thinking_args(
    completion_args: dict[str, Any], model_name: str, enable_thinking: bool
) -> None:
    """Sets the DeepSeek thinking-mode kwargs on a completion call, in place.

    Also lifts ``max_tokens`` to ``THINKING_FLOOR_MAX_TOKENS`` when the call
    will actually think, because the budget has to cover the chain of thought
    as well as the answer -- see that constant for why an answer-sized budget
    silently turns into an empty response. Applied here rather than at the
    call sites so a node cannot be added later with a budget that predates
    thinking; the floor only ever raises, so a node that sized itself above
    it keeps its own number.

    Args:
        completion_args: The in-progress completion kwargs dict; mutated in
            place with "extra_body", reasoning-effort args, and a raised
            "max_tokens" when thinking applies to this model.
        model_name: Model name in litellm format.
        enable_thinking: Whether DeepSeek thinking mode is requested.
    """
    thinking = deepseek_thinking_extra_body(model_name, enabled=enable_thinking)
    if not thinking:
        return

    completion_args["extra_body"] = thinking
    completion_args.update(
        reasoning_effort_args(model_name, enabled=enable_thinking)
    )

    if enable_thinking:
        completion_args["max_tokens"] = max(
            completion_args["max_tokens"], THINKING_FLOOR_MAX_TOKENS
        )


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


def _empty_content_diagnosis(response: Any) -> str:
    """Summarizes, in one short line, why a completion carried no content.

    The response object itself is deliberately never logged. On a reasoning
    model it embeds the entire chain of thought twice -- once as
    ``message.reasoning_content`` and again under
    ``provider_specific_fields`` -- so a single record runs to tens of
    kilobytes, floods the persisted log, and pushes the run's own narrative
    out of the fixed newest-N window the Logs panel shows. None of that text
    diagnoses anything the fields below do not: ``finish_reason="length"``
    with ``reasoning_tokens`` sitting at the call's ``max_tokens`` says the
    chain of thought spent the whole budget and left nothing for the answer.

    Every field is read defensively -- this runs on an already-failing
    response, and a diagnostic that raises would replace a useful error with
    an ``AttributeError`` from the logging path.

    Args:
        response: The raw response returned by ``litellm.acompletion``.

    Returns:
        A compact ``key=value`` summary of the finish reason and token spend.
    """
    parts: list[str] = []

    with contextlib.suppress(Exception):
        parts.append(f"finish_reason={response.choices[0].finish_reason}")

    usage = getattr(response, "usage", None)
    for field in ("prompt_tokens", "completion_tokens"):
        value = getattr(usage, field, None)
        if value is not None:
            parts.append(f"{field}={value}")

    details = getattr(usage, "completion_tokens_details", None)
    reasoning = getattr(details, "reasoning_tokens", None)
    if reasoning is not None:
        parts.append(f"reasoning_tokens={reasoning}")

    return ", ".join(parts) if parts else "no usage reported"


def _extract_completion_content(response: Any, model_name: str) -> str:
    """Extracts and validates the text content of a completion response.

    Args:
        response: The raw response returned by ``litellm.acompletion``.
        model_name: Model name in litellm format, included in the error
            message when the response has no content.

    Returns:
        The non-empty response content.

    Raises:
        ValueError: If the response has no non-whitespace content.
    """
    content = response.choices[0].message.content

    if content is None or not content.strip():
        logger.error(
            "LLM returned None or empty content. Model: %s (%s)",
            model_name,
            _empty_content_diagnosis(response),
        )
        raise ValueError(
            f"LLM returned None or empty content. Model: {model_name}"
        )

    return cast(str, content)
