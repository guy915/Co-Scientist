"""Response-format selection and the json_object provider-capability shim.

Split out of ``co_scientist.llm_request`` on size; every name here is
re-exported there, so callers and tests keep speaking to that module's
namespace. The cluster belongs together because it is one thing: what to
send when a model cannot be handed a JSON schema server-side.

``_supports_json_schema_response_format`` deliberately stayed behind in
``llm_request``. It is a monkeypatch seam -- ``offline_llm`` and three
test helpers rebind it on that module -- and moving a patched name is
silent: the re-export alias keeps every *reader* working while every
*patcher* rebinds an alias nothing consults.
"""

import json
import logging
from typing import Any, Final

# Named for the module this split out of, for the same reason as
# llm_failure: the logger name is an operator-facing filter, and an
# internal split must not move it.
logger = logging.getLogger("co_scientist.llm_request")


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
    # Read through the module object, not a from-import: the predicate is
    # a monkeypatch seam that offline_llm and three test helpers rebind on
    # ``llm_request`` to force one branch. A from-import would bind the
    # original at import time and silently ignore every one of them.
    from co_scientist import llm_request

    if llm_request._supports_json_schema_response_format(model_name):
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
