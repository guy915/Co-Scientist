"""Fakes for the ``litellm.acompletion`` boundary.

Used by the integration and system tests to run the *real* compiled
LangGraph workflow end-to-end with only the network boundary faked.
Patches ``litellm.acompletion`` directly -- the single external call every
``co_scientist.llm`` entry point (``call_llm``, ``call_llm_json``) funnels
through -- rather than patching individual node modules' imported
``call_llm``/``call_llm_json`` references (the idiom used by the
node-level unit tests). This keeps one patch point instead of one per node
module, and it exercises the real JSON extraction, schema validation, and
retry logic in ``co_scientist.llm`` rather than bypassing it.

For a schema'd call (``response_format={"type": "json_schema", ...}``),
``_fill_schema`` builds a minimal value that satisfies the schema: every
"required" property (or, absent a "required" list, every declared
property) is filled recursively, with enums resolved to their first
allowed value -- so closed-vocabulary fields like ranking's "winner" or
deep verification's "verdict" always get a valid, deterministic choice.
Every string leaf gets a unique, incrementing suffix so hypothesis text and
other identity-bearing fields never collide across calls; this matters
because ``co_scientist.state.deduplicate_hypotheses`` merges hypotheses
with equal normalized text, and evolution rejects a refinement that is
identical to (or a near-duplicate of) the original text. A call with no
schema (e.g. a debate's free-form intermediate turn) gets a unique
plain-text reply instead.

One schema needs an array filled to a specific length rather than the
generic filler's default of one item: the comparative batch-review
response's "reviews" array must have exactly one entry per hypothesis in
the batch, since ``review_node`` maps entries back to hypotheses by array
position and rejects a short response as invalid. ``_batch_review_length``
recovers that count from the prompt text (each hypothesis is rendered as
"**Hypothesis N:**" by ``_prepare_batch_review_call``), and
``_ARRAY_LENGTH_HINTS`` wires it to the "hypothesis_batch_review" schema
by name.
"""

import itertools
import json
import re
import types
from collections.abc import Callable
from typing import Any

import pytest

from co_scientist import cache

# Shared across every fake call in a test run so no two generated leaves
# (hypothesis text, free-form turns, etc.) ever collide.
_counter = itertools.count(1)

_HYPOTHESIS_MARKER_RE = re.compile(r"\*\*Hypothesis \d+:\*\*")


def _batch_review_length(prompt: str) -> dict[str, int]:
    """Counts the "**Hypothesis N:**" markers in a batch-review prompt.

    Args:
        prompt: The rendered batch-review prompt text.

    Returns:
        ``{"reviews": count}`` sized to the number of hypotheses in the
        batch (at least one), matching the property name in
        ``REVIEW_BATCH_SCHEMA``.
    """
    count = len(_HYPOTHESIS_MARKER_RE.findall(prompt))
    return {"reviews": max(count, 1)}


# Per-schema-name hooks that compute a {property_name: item_count} map from
# the prompt text, for the few schemas whose array length must match a
# count baked into the prompt rather than the generic filler's default of
# one item per array.
_ARRAY_LENGTH_HINTS: dict[str, Callable[[str], dict[str, int]]] = {
    "hypothesis_batch_review": _batch_review_length,
}


def _fill_schema(
    schema: dict[str, Any], array_lengths: dict[str, int] | None = None
) -> Any:
    """Builds a minimal value satisfying one JSON-schema node.

    Args:
        schema: A JSON Schema fragment (object, array, or scalar).
        array_lengths: Optional property-name -> item-count map (see
            ``_ARRAY_LENGTH_HINTS``); an array property whose name is a key
            here is filled to that length instead of the default one item.

    Returns:
        A value satisfying ``schema``: for objects, every required (or, if
        unspecified, every declared) property filled recursively; for
        arrays, a list with one filled item (or ``array_lengths`` many);
        for enums, the first allowed value; for scalars, a type-
        appropriate placeholder.
    """
    array_lengths = array_lengths or {}

    if "enum" in schema:
        return schema["enum"][0]

    schema_type = schema.get("type", "object")

    if schema_type == "object":
        properties = schema.get("properties", {})
        required = schema.get("required") or list(properties.keys())
        return {
            name: _fill_property(name, properties[name], array_lengths)
            for name in required
            if name in properties
        }

    if schema_type == "array":
        return _fill_array(schema, 1, array_lengths)

    if schema_type == "integer":
        return 4

    if schema_type == "number":
        return 4.0

    if schema_type == "boolean":
        return True

    # string, or any type this filler does not special-case.
    return f"stub-{next(_counter)}"


def _fill_property(
    name: str, schema: dict[str, Any], array_lengths: dict[str, int]
) -> Any:
    """Fills one object property, honoring an array-length hint by name.

    Args:
        name: The property name, checked against ``array_lengths``.
        schema: The property's own JSON Schema fragment.
        array_lengths: Property-name -> item-count map.

    Returns:
        The filled property value.
    """
    if schema.get("type") == "array" and name in array_lengths:
        return _fill_array(schema, array_lengths[name], array_lengths)
    return _fill_schema(schema, array_lengths)


def _fill_array(
    schema: dict[str, Any], count: int, array_lengths: dict[str, int]
) -> list[Any]:
    """Fills an array schema with ``count`` (at least one) filled items.

    Args:
        schema: The array's JSON Schema fragment (reads "items").
        count: Desired item count; clamped up to one.
        array_lengths: Property-name -> item-count map, threaded into each
            item's fill so length hints apply at any nesting depth.

    Returns:
        A list of ``max(count, 1)`` filled items.
    """
    item_schema = schema.get("items", {"type": "string"})
    return [
        _fill_schema(item_schema, array_lengths) for _ in range(max(count, 1))
    ]


def _fake_response(content: str) -> Any:
    """Builds the nested object a litellm completion response exposes.

    Args:
        content: The text ``_extract_completion_content`` should return.

    Returns:
        An object shaped like ``litellm.acompletion``'s return value, as
        far as ``co_scientist.llm`` reads it
        (``response.choices[0].message.content``).
    """
    message = types.SimpleNamespace(content=content)
    choice = types.SimpleNamespace(message=message)
    return types.SimpleNamespace(choices=[choice])


def _prompt_text(kwargs: dict[str, Any]) -> str:
    """Extracts the outgoing prompt text from completion call kwargs.

    Args:
        kwargs: The completion arguments built by
            ``co_scientist.llm._build_completion_args``.

    Returns:
        The last message's content, or "" if there are no messages.
    """
    messages = kwargs.get("messages") or []
    if not messages:
        return ""
    return str(messages[-1].get("content", ""))


async def _fake_acompletion(**kwargs: Any) -> Any:
    """Stands in for ``litellm.acompletion``: schema-true JSON or free text.

    Args:
        **kwargs: The completion arguments built by
            ``co_scientist.llm._build_completion_args`` (model, messages,
            response_format, ...); only ``response_format`` and the
            outgoing prompt text are inspected.

    Returns:
        A fake completion response exposing
        ``.choices[0].message.content``.
    """
    response_format = kwargs.get("response_format")
    if response_format and response_format.get("type") == "json_schema":
        json_schema = response_format["json_schema"]
        schema = json_schema["schema"]
        if json_schema.get("name") == "supervisor_allocation":
            # Exercise model-directed scheduling with a stable adaptive
            # portfolio: improve leaders first, then explore new regions.
            prompt = _prompt_text(kwargs)
            needs_proximity = '"pool_grew_since_proximity": true' in prompt
            first_cycle = '"iteration": 0' in prompt
            next_task = (
                "proximity"
                if needs_proximity
                else ("evolve" if first_cycle else "generate")
            )
            content = json.dumps(
                {
                    "next_task": next_task,
                    "reason": (
                        "Refresh the scientific similarity landscape."
                        if needs_proximity
                        else (
                            "Improve reviewed leaders."
                            if first_cycle
                            else "Explore an underdeveloped direction."
                        )
                    ),
                }
            )
            return _fake_response(content)
        length_hint = _ARRAY_LENGTH_HINTS.get(json_schema.get("name", ""))
        array_lengths = (
            length_hint(_prompt_text(kwargs)) if length_hint else None
        )
        content = json.dumps(_fill_schema(schema, array_lengths))
    elif response_format and response_format.get("type") == "json_object":
        # No production call site reaches this branch (every call site
        # that requests JSON also supplies a schema), but it is kept as a
        # safe, schema-less fallback.
        content = "{}"
    else:
        content = f"free-form response {next(_counter)}"
    return _fake_response(content)


def install_fake_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patches the LLM and cache boundaries for a fast, deterministic run.

    Patches ``litellm.acompletion`` (see module docstring) and forces LLM
    caching off. The cache override resets the process-wide singleton in
    ``co_scientist.cache`` in addition to setting the env var: the
    singleton is memoized on first use and other test modules may have
    already initialized it as enabled earlier in the same pytest process,
    a state a plain env-var override cannot undo.

    Also forces every schema'd call onto the native "json_schema" response
    format, regardless of the (made-up) test model name: real litellm's
    provider registry does not recognize it and reports no json_schema
    support, which would otherwise route every call through the
    json_object provider-capability shim (schema restated as prompt text
    instead of structured ``response_format``) -- a real production path,
    but not the one this fake speaks, since it builds its response from
    the structured schema rather than parsing it back out of prompt text.

    Args:
        monkeypatch: The pytest monkeypatch fixture.
    """
    import litellm

    from co_scientist import llm_request

    monkeypatch.setattr(litellm, "acompletion", _fake_acompletion)
    monkeypatch.setattr(
        llm_request,
        "_supports_json_schema_response_format",
        lambda _model_name: True,
    )
    monkeypatch.setenv("COSCIENTIST_CACHE_ENABLED", "false")
    monkeypatch.setattr(cache, "_global_cache", None)
