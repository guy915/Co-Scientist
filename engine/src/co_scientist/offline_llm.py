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

``_fill_schema`` (in the sibling ``offline_schema_fill`` module, split out
once this one grew past the file-length budget) takes the leaf-value
generator as a plain callable rather than baking in either strategy, so
``tests/_llm_fake.py`` can share this exact traversal logic while keeping
its own process-global counter (fine for a monkeypatch that pytest
reverts after every test, and relied on by existing tests for uniqueness
across separate calls within one test, not just within one response).
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
from co_scientist.offline_schema_fill import _fill_schema, _FillHints

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


_CANDIDATE_MARKER_RE = re.compile(r"\*\*Candidate \d+:\*\*")


def _relevance_batch_length(prompt: str) -> dict[str, int]:
    """Counts the "**Candidate N:**" markers in a relevance-batch prompt.

    Args:
        prompt: The rendered literature-relevance-batch prompt text.

    Returns:
        ``{"judgments": count}`` sized to the number of candidates in the
        batch (at least one), matching the property name in
        ``LITERATURE_RELEVANCE_BATCH_SCHEMA``. Without this hint the
        generic filler defaults every array to one item, which would
        leave every candidate past the first unjudged on the offline
        backend even though a real batch call judges all of them.
    """
    count = len(_CANDIDATE_MARKER_RE.findall(prompt))
    return {"judgments": max(count, 1)}


# Unlike the batch-review count above, a research overview's directions
# have no 1:1 correspondence with anything the prompt declares -- the
# model freely decides how many major directions a hypothesis pool
# resolves into. This hook is therefore a fixed count, not a prompt
# reading: enough to clear the report's directions-preview gate
# (report_markdown_overview.py::_render_directions_preview renders
# nothing below two named directions), so an offline run reads as having
# found several directions worth pursuing rather than exactly one.
_RESEARCH_DIRECTIONS_COUNT = 3

# Task B: sized to the schema's own maxItems
# (RESEARCH_OVERVIEW_MAX_UNEXPECTED_DIRECTIONS) rather than the bare
# one-item default, so an offline run's demo reads as having found
# several unexpected directions -- matching MASH's own published
# exemplar, which carries exactly three.
_UNEXPECTED_DIRECTIONS_COUNT = 3


def _research_overview_directions_length(_prompt: str) -> dict[str, int]:
    """Sizes both research-overview direction arrays past their defaults.

    Args:
        _prompt: The rendered research-overview prompt (unused; both
            counts are fixed rather than derived from prompt content --
            see the module-level comments on ``_RESEARCH_DIRECTIONS_COUNT``
            and ``_UNEXPECTED_DIRECTIONS_COUNT``).

    Returns:
        ``{"research_directions": _RESEARCH_DIRECTIONS_COUNT,
        "unexpected_research_directions": _UNEXPECTED_DIRECTIONS_COUNT}``.
    """
    return {
        "research_directions": _RESEARCH_DIRECTIONS_COUNT,
        "unexpected_research_directions": _UNEXPECTED_DIRECTIONS_COUNT,
    }


# Per-schema-name hooks that compute a {property_name: item_count} map from
# the prompt text, for the few schemas whose array length must match a
# count baked into the prompt rather than the generic filler's default of
# one item per array.
_ARRAY_LENGTH_HINTS: dict[str, Callable[[str], dict[str, int]]] = {
    "hypothesis_batch_review": _batch_review_length,
    "research_overview": _research_overview_directions_length,
    "literature_relevance_batch": _relevance_batch_length,
}

# The review rubric's eight scored axes (schemas/review.py's private
# _SCORE_CRITERIA, mirrored here rather than imported across that privacy
# boundary) plus the descriptive overall_score. Every offline review's
# every score otherwise defaults through _SCALAR_DEFAULTS to exactly
# NEEDS_REVISION_SCORE (constants.py, currently 4), which the initial
# review gate reads with a <=, not a <: every offline-reviewed hypothesis
# therefore lands in "needs_revision", never "viable" --
# review_gate._disposition_for -- and only a "viable" hypothesis reaches
# Reflection's full/simulation/recurrent cascade
# (mature_reviews.reviews_needed), so that cascade never fires on the
# offline backend. This override lands every score comfortably inside the
# rubric's "good" band instead, clear of that boundary, without touching
# NEEDS_REVISION_SCORE itself or any other schema's integer fields --
# every other integer this filler fills is a pool index (a batch review's
# hypothesis_index, a proximity cluster member's index, ...), not a
# score, and stays at the generic default.
_REVIEW_SCORE_FIELDS: tuple[str, ...] = (
    "scientific_soundness",
    "plausibility",
    "novelty",
    "testability",
    "potential_impact",
    "relevance",
    "safety",
    "clarity",
    "overall_score",
)
_REVIEW_SCORE_VALUE = 7

# Per-schema-name {property_name: value} overrides for a scalar leaf,
# read ahead of _SCALAR_DEFAULTS. Both REVIEW_SCHEMA and
# REVIEW_BATCH_SCHEMA share the same scored-axis vocabulary (via
# schemas/review.py's _SCORES_SCHEMA), so both schema names get the same
# override table.
_SCALAR_VALUE_HINTS: dict[str, dict[str, Any]] = {
    "hypothesis_review": dict.fromkeys(
        _REVIEW_SCORE_FIELDS, _REVIEW_SCORE_VALUE
    ),
    "hypothesis_batch_review": dict.fromkeys(
        _REVIEW_SCORE_FIELDS, _REVIEW_SCORE_VALUE
    ),
}

# Per-schema-name optional properties the filler fills anyway, despite the
# schema marking them optional (see offline_schema_fill._FillHints.
# optional_fields). Deliberately scoped, not a global "fill every optional"
# switch: a real provider genuinely omits optional fields, so defaulting to
# filling them everywhere would change offline output broadly and stop
# representing that. Only a schema named here, for only the properties
# named here, is filled -- every other optional property across every
# other schema stays absent, as it did before this hint existed.
#
# Both entries below were found dark (docs/decisions/2026-09-02-offline-
# optional-field-reach.md): FULL_REVIEW_SCHEMA's go_no_go_recommendation/
# time_to_verdict feed drain_reviews._verdict_detail, which
# ideas_detail_review_findings.tsx's VerdictLines never renders without
# them; META_REVIEW_SCHEMA's strategic_recommendations[] time_estimate/
# phase_label/recommended_idea feed report_markdown_meta_review's
# _render_recommendation the same way. Both are plain free-text fields --
# no value needs to reference another part of the response -- so a name
# list alone is enough; see the ADR for the optional fields left out
# because they need more than that (a value with particular structure, or
# are blocked upstream by a required field).
_OPTIONAL_FIELD_HINTS: dict[str, tuple[str, ...]] = {
    "full_review": ("go_no_go_recommendation", "time_to_verdict"),
    "meta_review": ("time_estimate", "phase_label", "recommended_idea"),
}


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
    hints = _FillHints(
        array_lengths=length_hint(prompt) if length_hint else {},
        scalar_values=_SCALAR_VALUE_HINTS.get(schema_name, {}),
        optional_fields=frozenset(_OPTIONAL_FIELD_HINTS.get(schema_name, ())),
    )
    content = json.dumps(_fill_schema(schema, leaf_fn, hints))
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
