"""Request preparation and shaping for LiteLLM completion calls.

Builds the keyword arguments for ``litellm.acompletion`` calls made by the
wrappers in ``co_scientist.llm``: response-format selection (including the
json_object provider-capability shim), temperature clamping, prompt
debug-artifact saving, and extraction of the text content from completion
responses.
"""

import asyncio
import functools
import json
import logging
import warnings
from typing import Any, cast

import litellm

from co_scientist import prompts

logger = logging.getLogger(__name__)


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


def _apply_response_format(
    completion_args: dict[str, Any],
    prompt: str,
    model_name: str,
    force_json: bool,
    json_schema: dict[str, Any] | None,
) -> None:
    """Sets the response_format for a completion call, in place.

    When a schema is given, prefers the model's native json_schema response
    format; models that reject it fall back to the json_object
    provider-capability shim, which also rewrites "messages" to restate the
    schema as prompt text. Without a schema, force_json requests plain
    json_object mode.

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
        if _supports_json_schema_response_format(model_name):
            completion_args["response_format"] = {
                "type": "json_schema",
                "json_schema": json_schema,
            }
        else:
            # Provider-capability shim: this model rejects the
            # json_schema response format, so downgrade this call to
            # json_object and restate the schema in the prompt. The
            # cache keys above stay on the original prompt.
            logger.debug(
                "model %s does not support json_schema response format;"
                " downgrading to json_object with schema in prompt",
                model_name,
            )
            completion_args["messages"] = [
                {
                    "role": "user",
                    "content": _inject_schema_into_prompt(prompt, json_schema),
                }
            ]
            completion_args["response_format"] = {"type": "json_object"}
    elif force_json:
        completion_args["response_format"] = {"type": "json_object"}


def _build_completion_args(
    prompt: str,
    model_name: str,
    max_tokens: int,
    temperature: float,
    force_json: bool,
    json_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    """Builds the keyword arguments for a ``litellm.acompletion`` call.

    Args:
        prompt: The prompt to send to the LLM.
        model_name: Model name in litellm format.
        max_tokens: Maximum tokens in response.
        temperature: Sampling temperature.
        force_json: If True, try to force JSON mode (model support varies).
        json_schema: Optional JSON schema to constrain the response format.

    Returns:
        Keyword arguments ready to pass to ``litellm.acompletion``.
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

    _apply_response_format(
        completion_args, prompt, model_name, force_json, json_schema
    )

    return completion_args


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
            "LLM returned None or empty content. Response: %s", response
        )
        raise ValueError(
            f"LLM returned None or empty content. Model: {model_name}"
        )

    return cast(str, content)
