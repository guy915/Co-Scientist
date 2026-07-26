"""Deterministic offline LLM backend for ``offline/``-prefixed models.

Productionizes the pattern proven out by the test fake in
``tests/_llm_fake.py``: every engine LLM call funnels through exactly two
``litellm.acompletion`` call sites (``co_scientist.llm`` and
``co_scientist.llm_tool_loop``), both of which read the live module
attribute, so ``setattr(litellm, "acompletion", wrapper)`` intercepts
everything. ``install_offline_router`` installs a conditional wrapper: a
call whose ``model`` starts with ``OFFLINE_MODEL_PREFIX`` is answered
locally by ``offline_acompletion``; every other call passes through to the
original callable untouched, so real-model traffic is unaffected.

Unlike the test fake's process-global counter (fine for a monkeypatch that
pytest reverts after every test), the runtime router must not depend on
cross-call mutable state to shape its content: two identical calls (same
model, prompt, and schema name) must always produce byte-identical output,
while different prompts must differ. This is done by seeding a
``random.Random`` from the SHA-256 digest of ``(model, prompt, schema
name)`` once per call and drawing every string leaf from it -- the
deterministic traversal order of ``_fill_schema`` means identical inputs
draw the same sequence of random values (so the response is
byte-identical), while each leaf is also tagged with its 1-based position
within the response (so string leaves stay unique within one response even
when a draw repeats, which matters because
``co_scientist.state.deduplicate_hypotheses`` collapses hypotheses with
equal normalized text).

What a leaf *says* is ``offline_content``'s job: it varies the sentence by
the property being filled and grounds it in the prompt's research goal, so
offline runs -- including the production site's demo runs -- read as the
kind of output the product makes rather than as interchangeable filler.
The property name is threaded down through ``_fill_schema`` for that
reason; before, every field from a title to a reviewer's critique received
the same shape of sentence.

``_fill_schema`` takes the leaf-value generator as a plain callable rather
than baking in either strategy, so ``tests/_llm_fake.py`` can share this
exact traversal logic while keeping its own process-global counter (fine
for a monkeypatch that pytest reverts after every test, and relied on by
existing tests for uniqueness across separate calls within one test, not
just within one response).
"""

import hashlib
import itertools
import json
import logging
import random
import re
import types
from collections.abc import Callable
from typing import Any

from co_scientist import llm_request
from co_scientist.offline_content import leaf_text, subject_terms

logger = logging.getLogger(__name__)

OFFLINE_MODEL_PREFIX = "offline/"
DEFAULT_OFFLINE_MODEL = f"{OFFLINE_MODEL_PREFIX}deterministic"


def is_offline_model(model_name: str) -> bool:
    """Checks whether a model name is routed to the offline responder.

    Args:
        model_name: Model name in litellm format.

    Returns:
        True if ``model_name`` starts with ``OFFLINE_MODEL_PREFIX``.
    """
    return model_name.startswith(OFFLINE_MODEL_PREFIX)


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

# Placeholder values for scalar schema types this filler special-cases.
_SCALAR_DEFAULTS: dict[str, Any] = {
    "integer": 4,
    "number": 4.0,
    "boolean": True,
}


def _fill_schema(
    schema: dict[str, Any],
    leaf_fn: Callable[[str], Any],
    array_lengths: dict[str, int] | None = None,
    field: str = "",
) -> Any:
    """Builds a minimal value satisfying one JSON-schema node.

    Args:
        schema: A JSON Schema fragment (object, array, or scalar).
        leaf_fn: Callable taking the property name being filled and
            returning the next string-leaf value; called once per string
            leaf encountered. Callers choose the uniqueness strategy (a
            seeded RNG for the runtime router, a process-global counter for
            the test fake).
        array_lengths: Optional property-name -> item-count map (see
            ``_ARRAY_LENGTH_HINTS``); an array property whose name is a key
            here is filled to that length instead of the default one item.
        field: Name of the property this node is filling, passed to
            ``leaf_fn`` so a leaf can read as the field it lands in.
            Empty at the schema root.

    Returns:
        A value satisfying ``schema``: object properties filled
        recursively, array items filled per ``array_lengths`` (default
        one), an enum's first allowed value, or a scalar placeholder.
    """
    array_lengths = array_lengths or {}

    if "enum" in schema:
        return schema["enum"][0]

    schema_type = schema.get("type", "object")

    if schema_type == "object":
        return _fill_object(schema, leaf_fn, array_lengths)

    if schema_type == "array":
        return _fill_array(schema, 1, leaf_fn, array_lengths, field)

    if schema_type in _SCALAR_DEFAULTS:
        return _SCALAR_DEFAULTS[schema_type]

    # string, or any type this filler does not special-case.
    return leaf_fn(field)


def _fill_object(
    schema: dict[str, Any],
    leaf_fn: Callable[[str], Any],
    array_lengths: dict[str, int],
) -> dict[str, Any]:
    """Fills every required (or, if unspecified, every declared) property.

    Args:
        schema: The object's JSON Schema fragment.
        leaf_fn: Zero-argument callable returning the next string-leaf
            value (see ``_fill_schema``).
        array_lengths: Property-name -> item-count map, threaded into each
            property's fill.

    Returns:
        A dict mapping each filled property name to its value.
    """
    properties = schema.get("properties", {})
    required = schema.get("required") or list(properties.keys())
    return {
        name: _fill_property(name, properties[name], leaf_fn, array_lengths)
        for name in required
        if name in properties
    }


def _fill_property(
    name: str,
    schema: dict[str, Any],
    leaf_fn: Callable[[str], Any],
    array_lengths: dict[str, int],
) -> Any:
    """Fills one object property, honoring an array-length hint by name.

    Args:
        name: The property name, checked against ``array_lengths``.
        schema: The property's own JSON Schema fragment.
        leaf_fn: Zero-argument callable returning the next string-leaf
            value (see ``_fill_schema``).
        array_lengths: Property-name -> item-count map.

    Returns:
        The filled property value.
    """
    if schema.get("type") == "array" and name in array_lengths:
        return _fill_array(
            schema, array_lengths[name], leaf_fn, array_lengths, name
        )
    return _fill_schema(schema, leaf_fn, array_lengths, name)


def _fill_array(
    schema: dict[str, Any],
    count: int,
    leaf_fn: Callable[[str], Any],
    array_lengths: dict[str, int],
    field: str = "",
) -> list[Any]:
    """Fills an array schema with ``count`` (at least one) filled items.

    Args:
        schema: The array's JSON Schema fragment (reads "items").
        count: Desired item count; clamped up to one.
        leaf_fn: Zero-argument callable returning the next string-leaf
            value (see ``_fill_schema``).
        array_lengths: Property-name -> item-count map, threaded into each
            item's fill so length hints apply at any nesting depth.
        field: Name of the array property, passed down so an item reads as
            the field it belongs to.

    Returns:
        A list of ``max(count, 1)`` filled items.
    """
    item_schema = schema.get("items", {"type": "string"})
    return [
        _fill_schema(item_schema, leaf_fn, array_lengths, field)
        for _ in range(max(count, 1))
    ]


def _build_response(content: str) -> Any:
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


def _prompt_text(completion_args: dict[str, Any]) -> str:
    """Extracts the outgoing prompt text from completion call kwargs.

    Args:
        completion_args: The completion arguments built by
            ``co_scientist.llm_request._build_completion_args``.

    Returns:
        The last message's content, or "" if there are no messages.
    """
    messages = completion_args.get("messages") or []
    if not messages:
        return ""
    return str(messages[-1].get("content", ""))


def _seed_for(model: str, prompt: str, schema_name: str) -> int:
    """Derives a deterministic RNG seed from a call's identity.

    Args:
        model: The requested model name.
        prompt: The outgoing prompt text.
        schema_name: The response schema's "name" field, or "" when the
            call is schema-less.

    Returns:
        An integer seed: identical for identical (model, prompt,
        schema_name) triples, and (with overwhelming probability)
        different otherwise.
    """
    digest = hashlib.sha256(
        "\x00".join((model, prompt, schema_name)).encode("utf-8")
    ).digest()
    return int.from_bytes(digest, byteorder="big")


def _supervisor_allocation_response(prompt: str) -> str:
    """Builds a deterministic ``supervisor_allocation`` decision.

    Exercises model-directed scheduling with a stable adaptive portfolio:
    improve leaders first, then explore new regions. Reads flags baked into
    the planning prompt by ``_planning_prompt`` rather than drawing from the
    schema filler, since the scheduling decision must react to run state
    rather than being an arbitrary valid value.

    Args:
        prompt: The rendered supervisor-allocation planning prompt.

    Returns:
        JSON text satisfying the ``supervisor_allocation`` schema.
    """
    needs_proximity = '"pool_grew_since_proximity": true' in prompt
    first_cycle = '"iteration": 0' in prompt
    next_task = (
        "proximity"
        if needs_proximity
        else ("evolve" if first_cycle else "generate")
    )
    reason = (
        "Refresh the scientific similarity landscape."
        if needs_proximity
        else (
            "Improve reviewed leaders."
            if first_cycle
            else "Explore an underdeveloped direction."
        )
    )
    return json.dumps({"next_task": next_task, "reason": reason})


def _schema_response(
    model: str, prompt: str, json_schema: dict[str, Any]
) -> Any:
    """Builds a fake completion response for a schema'd offline call.

    Args:
        model: The requested model name.
        prompt: The outgoing prompt text.
        json_schema: The ``response_format["json_schema"]`` payload (name
            and schema).

    Returns:
        A fake completion response exposing
        ``.choices[0].message.content``.
    """
    schema_name = json_schema.get("name", "")

    if schema_name == "supervisor_allocation":
        return _build_response(_supervisor_allocation_response(prompt))

    rng = random.Random(_seed_for(model, prompt, schema_name))
    ordinals = itertools.count(1)
    terms = subject_terms(prompt)

    def leaf_fn(field: str) -> str:
        return leaf_text(rng, next(ordinals), field, terms)

    schema = json_schema["schema"]
    length_hint = _ARRAY_LENGTH_HINTS.get(schema_name)
    array_lengths = length_hint(prompt) if length_hint else None
    content = json.dumps(_fill_schema(schema, leaf_fn, array_lengths))
    return _build_response(content)


async def offline_acompletion(**completion_args: Any) -> Any:
    """Stands in for ``litellm.acompletion`` for ``offline/`` models.

    Builds schema-true JSON for a schema'd call, or deterministic free text
    otherwise. See the module docstring for the determinism contract.

    Args:
        **completion_args: The completion arguments built by
            ``co_scientist.llm_request._build_completion_args`` (model,
            messages, response_format, ...); only "model", "response_format",
            and the outgoing prompt text are inspected.

    Returns:
        A fake completion response exposing
        ``.choices[0].message.content``.
    """
    model = str(completion_args.get("model") or DEFAULT_OFFLINE_MODEL)
    prompt = _prompt_text(completion_args)
    response_format = completion_args.get("response_format")

    if response_format and response_format.get("type") == "json_schema":
        return _schema_response(model, prompt, response_format["json_schema"])

    if response_format and response_format.get("type") == "json_object":
        # No production call site reaches this branch (every call site
        # that requests JSON also supplies a schema), but it is kept as a
        # safe, schema-less fallback.
        return _build_response("{}")

    rng = random.Random(_seed_for(model, prompt, ""))
    return _build_response(leaf_text(rng, 1, "", subject_terms(prompt)))


_installed = False
_original_acompletion: Callable[..., Any] | None = None
_original_supports_json_schema: Callable[[str], bool] | None = None


def _make_routed_acompletion(
    original_acompletion: Callable[..., Any],
) -> Callable[..., Any]:
    """Builds an acompletion wrapper that answers offline models locally."""

    async def _routed_acompletion(**kwargs: Any) -> Any:
        model_name = str(kwargs.get("model") or "")
        if is_offline_model(model_name):
            return await offline_acompletion(**kwargs)
        return await original_acompletion(**kwargs)

    return _routed_acompletion


def _make_routed_supports_json_schema(
    original_supports_json_schema: Callable[[str], bool],
) -> Callable[[str], bool]:
    """Builds a supports-json-schema wrapper that treats offline as True."""

    def _routed_supports_json_schema(model_name: str) -> bool:
        if is_offline_model(model_name):
            return True
        return original_supports_json_schema(model_name)

    return _routed_supports_json_schema


def install_offline_router() -> None:
    """Installs a conditional router over ``litellm.acompletion``.

    Idempotent: a second call is a no-op, so callers (app startup, test
    fixtures) can call it unconditionally without risking a nested chain of
    routers. ``offline/``-prefixed models are answered by
    ``offline_acompletion``; every other model's call passes through
    untouched to the callable that was live at install time. Also wraps
    ``llm_request._supports_json_schema_response_format`` so schema'd
    offline calls take the native json_schema branch in
    ``co_scientist.llm_request._apply_response_format`` rather than the
    json_object provider-capability shim.
    """
    global _installed, _original_acompletion, _original_supports_json_schema

    if _installed:
        return

    import litellm

    original_acompletion = litellm.acompletion
    original_supports_json_schema = (
        llm_request._supports_json_schema_response_format
    )

    litellm.acompletion = _make_routed_acompletion(original_acompletion)
    # The original is a functools.cache-wrapped function; setattr (rather
    # than a direct assignment, which mypy would reject as a callable-type
    # mismatch) installs the plain-function replacement. noqa: intentional
    # dynamic patch, the same pattern the test fake uses via monkeypatch.
    setattr(  # noqa: B010
        llm_request,
        "_supports_json_schema_response_format",
        _make_routed_supports_json_schema(original_supports_json_schema),
    )

    _original_acompletion = original_acompletion
    _original_supports_json_schema = original_supports_json_schema
    _installed = True
    logger.debug("offline llm router installed")
