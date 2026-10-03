"""Request preparation and shaping for LiteLLM completion calls.

Builds the keyword arguments for ``litellm.acompletion`` calls made by the
wrappers in ``co_scientist.llm``, and owns the one await every completion goes
through (``_acompletion_within_timeout``: admission, call budget, timeout
ceiling, telemetry): temperature clamping, prompt debug-artifact saving and
the per-call credential.

Response-format selection and the json_object capability shim live here.
Sibling modules own thinking/reasoning arguments (``llm.request.thinking``),
response extraction (``llm.request.response``) and the completion backend
(``llm.request.backend``).
"""

import asyncio
import json
import logging
import warnings
from dataclasses import dataclass
from typing import Any, Final

from co_scientist import prompts
from co_scientist.config.env_vars import parse_timeout_env
from co_scientist.llm.admission.free_policy import current_api_key
from co_scientist.llm.profile import model_profile
from co_scientist.llm.request.backend import (
    active_backend,
    litellm_supports_json_schema,
)
from co_scientist.llm.request.thinking import _apply_thinking_args
from co_scientist.llm.request.transport import complete_request

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


# Goes ahead of the restated schema, never after it -- see reason 3 in
# _inject_schema_into_prompt's docstring for the measurement, and note that
# the position is the effect.
_ANSWER_DISCIPLINE: Final = (
    "\n\n## Answer Discipline\n\n"
    "Your reasoning is not your answer. When you have finished reasoning, "
    "you must write the JSON object described below as the content of your "
    "reply. A reply whose content is empty is discarded in full, however "
    "good the reasoning behind it was, so never end your turn without "
    "emitting the JSON."
)


def _inject_schema_into_prompt(prompt: str, json_schema: dict[str, Any]) -> str:
    """Appends the JSON schema to the prompt for json_object-only models.

    Downgrading to the json_object response format loses the server-side
    schema constraint, so the schema is restated as prompt text to keep the
    model aware of the required structure. With no server-side enforcement
    the wording is the only constraint there is, so it spells out the two
    ways models actually break this contract in production, both of which
    surface as ``additionalProperties`` validation failures and cost a full
    retry each:

    1. Returning the schema itself -- an object carrying ``type`` and
       ``properties`` -- because "match this schema" reads as "echo this"
       once a schema is the last thing in the context.
    2. Adding a plausible-sounding field the schema does not declare
       (``cross_agent_feedback_used`` and friends), because nothing in the
       instruction said the property list was closed.
    3. Reasoning the answer out and then writing nothing, because on a
       thinking model a restated schema is something the chain of thought
       can satisfy and then treat as done. That is the answerless
       completion behind ``LLMThinkingOnlyError``, and it is this block
       that creates it: measured against the real ranking-matchup prompt,
       thinking alone produced none in 20 calls and the schema alone
       produced none in 20 calls, while the two together produced 12 in
       65. Naming the reply as the deliverable took that to 2 in 65 with
       thinking left on -- which is why the sentence is here rather than
       in any one node's template, and why the remedy is not to stop
       restating the schema.

    Note where that sentence sits: **before** the schema, not after it.
    The same sentence appended after the schema did nothing at all (3 in 40
    against a control's 3 in 40) while the identical text ahead of it took
    a 4-in-40 control to 0 in 40. Whatever the model reads last is what it
    orients to, which is the same effect reason 1 above is about -- so a
    later edit that tidies these instructions into one trailing block
    silently reverts the fix.

    Args:
        prompt: The original user prompt.
        json_schema: JSON schema dict (may have a nested "schema" key).

    Returns:
        The prompt with the schema instruction block appended.
    """
    actual_schema = json_schema.get("schema", json_schema)
    schema_str = json.dumps(actual_schema, indent=2)
    return (
        prompt + _ANSWER_DISCIPLINE + "\n\n---\nRESPOND WITH VALID JSON ONLY. "
        "Your output MUST strictly match this JSON schema "
        "(all required fields must be present):\n" + schema_str + "\n\n"
        "Output a JSON object that CONFORMS TO the schema above -- the "
        "actual data. Do NOT output the schema itself: your response must "
        'not contain "type", "properties", or "required" keys unless the '
        "schema declares them as data fields. Use only the property names "
        "the schema lists; any field it does not declare will be rejected."
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
    # Asked of the installed backend on every call, not bound at import: the
    # answer travels with whatever answers the call (the offline router says
    # yes to its own models), and a from-import of it would freeze the
    # default's answer.
    if active_backend().supports_json_schema(model_name):
        completion_args["response_format"] = {
            "type": "json_schema",
            # Callers use both bare schemas and provider envelopes.
            "json_schema": (
                {"name": "response", **json_schema}
                if "schema" in json_schema
                else {"name": "response", "schema": json_schema}
            ),
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
    return await complete_request(
        completion_args,
        model_name,
        byok=bool(current_api_key()),
        timeout_seconds=llm_timeout_seconds(),
        timeout_grace_seconds=_TIMEOUT_GRACE_SECONDS,
    )


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
    """Clamps temperature to the model's minimum, when it has one.

    Gemini 3 models require temperature >= 1.0 to avoid degraded
    performance (``ModelProfile.min_temperature``).

    Args:
        model_name: LLM model identifier.
        temperature: Requested sampling temperature.

    Returns:
        The temperature to actually use for the call.
    """
    floor = model_profile(model_name).min_temperature
    if floor is not None and temperature < floor:
        logger.debug(
            "clamping temperature %s -> %s for %s (it requires temp >= %s "
            "to avoid degraded performance)",
            temperature,
            floor,
            model_name,
            floor,
        )
        return floor
    return temperature


# The default backend's capability answer under its old name. ``json_attempt``
# binds it at import (deliberately not the installed backend's answer; see
# ``llm.request.backend``) and tests clear its cache.
_supports_json_schema_response_format = litellm_supports_json_schema


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
