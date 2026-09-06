"""JSON handling utilities for LLM responses.

Provides schema validation, fallback responses for non-critical nodes, and
the json_object-only provider-capability shims (backfilling missing
required fields, pruning invented properties, truncating over-long
arrays), plus validation feedback for retry prompts. The extraction/repair
helpers live in ``co_scientist.llm_json_repair`` and are re-exported here
so historical import paths keep working; a fourth shim (string
truncation) lives in ``co_scientist.llm_json_truncate_strings`` instead,
since ``llm_json_attempt`` is its only caller. These helpers are pure (no
network access), shared by ``co_scientist.llm`` and the tool-based phases.
"""

import copy
import logging
from collections.abc import Callable
from typing import Any

import jsonschema
from jsonschema.exceptions import ValidationError

from co_scientist.exceptions import ResponseParseError
from co_scientist.llm_json_lists import (
    coerce_json_list as coerce_json_list,
)
from co_scientist.llm_json_repair import (
    _MAJOR_JSON_REPAIR_STRATEGIES as _MAJOR_JSON_REPAIR_STRATEGIES,
)
from co_scientist.llm_json_repair import (
    _MINOR_JSON_REPAIR_STRATEGIES as _MINOR_JSON_REPAIR_STRATEGIES,
)
from co_scientist.llm_json_repair import (
    _UNTERMINATED_STRING_REPAIRS as _UNTERMINATED_STRING_REPAIRS,
)
from co_scientist.llm_json_repair import (
    _close_truncated_json as _close_truncated_json,
)
from co_scientist.llm_json_repair import (
    _fix_invalid_escapes as _fix_invalid_escapes,
)
from co_scientist.llm_json_repair import (
    _looks_like_truncated_array_entry as _looks_like_truncated_array_entry,
)
from co_scientist.llm_json_repair import (
    _repair_string_after_colon_or_comma as _repair_string_after_colon_or_comma,
)
from co_scientist.llm_json_repair import (
    _repair_unterminated_array_string as _repair_unterminated_array_string,
)
from co_scientist.llm_json_repair import (
    _repair_unterminated_field_name as _repair_unterminated_field_name,
)
from co_scientist.llm_json_repair import (
    _repair_unterminated_string as _repair_unterminated_string,
)
from co_scientist.llm_json_repair import (
    _try_direct_parse as _try_direct_parse,
)
from co_scientist.llm_json_repair import (
    _try_major_repairs as _try_major_repairs,
)
from co_scientist.llm_json_repair import (
    _try_minor_repairs as _try_minor_repairs,
)
from co_scientist.llm_json_repair import (
    attempt_json_repair as attempt_json_repair,
)
from co_scientist.llm_json_repair import (
    extract_response_json as extract_response_json,
)
from co_scientist.progress import (
    record_schema_degradation as record_schema_degradation,
)

logger = logging.getLogger(__name__)


def parse_tool_loop_json(
    final_response: str, list_key: str, phase_label: str
) -> list[Any]:
    """Parse a tool-calling loop's final response into its named list.

    Shared by the tool-based generation phases (drafting and validation
    synthesis), which each end a tool-calling loop by asking for one JSON
    object holding a single list.

    allow_major_repairs=True: tool-calling loop final responses are more
    prone to truncated/malformed JSON than single-shot calls (llm.py).

    Args:
        final_response: The agent's final tool-call-loop response text.
        list_key: Key holding the phase's result list in the JSON object.
        phase_label: Names the phase in the logs and in the raised error, so
            a log reader can tell which phase produced bad JSON.

    Returns:
        The parsed ``list_key`` list, or an empty list when the key is
        absent from an otherwise-parseable response. No schema constrains
        this call (it is the tool-calling loop's freeform final turn), so
        the value at ``list_key`` is coerced through ``coerce_json_list``
        rather than trusted to already be a list.

    Raises:
        ResponseParseError: If the response cannot be parsed even after
            repair attempts. Hard failure rather than an empty list:
            returning nothing silently would make the phase consuming this
            output a silent no-op too.
    """
    response_text = extract_response_json(final_response)
    response_data, was_repaired = attempt_json_repair(
        response_text, allow_major_repairs=True
    )

    if response_data is None:
        # One record, not two: the response excerpt is the evidence for the
        # sentence above it, and splitting them meant a reader scanning by
        # level had to notice that the line after an error belonged to it.
        logger.error(
            "Failed to parse %s JSON response after all repair attempts. "
            "Response: %s...",
            phase_label,
            final_response[:500],
        )
        raise ResponseParseError(
            f"{phase_label} returned invalid JSON that could not be repaired"
        )

    if was_repaired:
        logger.warning(
            "%s JSON response required major repairs (possible truncation)",
            phase_label,
        )

    return coerce_json_list(
        response_data.get(list_key),
        keys=(list_key, "items"),
        element="dict",
        site=phase_label,
    )


def validate_json_schema(
    result: dict[str, Any], json_schema: dict[str, Any] | None
) -> None:
    """Validate parsed JSON against the provided schema.

    Args:
        result: Parsed JSON dictionary to validate
        json_schema: Optional JSON schema dict (may have nested "schema" key)

    Raises:
        ValidationError: If the result doesn't match the schema
    """
    if json_schema is None:
        # No schema provided, skip validation
        return

    # Schema dicts may be either a bare JSON Schema or the LiteLLM
    # json_schema response-format wrapper ({"name": ..., "schema": {...}}
    # from call_llm); this normalizes to the bare schema either way. The
    # same unwrap pattern is repeated in _backfill_required_fields below and
    # in co_scientist.llm_request._inject_schema_into_prompt.
    # Extract actual schema from nested structure if present
    actual_schema = json_schema.get("schema", json_schema)

    try:
        jsonschema.validate(instance=result, schema=actual_schema)
        logger.debug("JSON schema validation passed")
    except ValidationError as e:
        # Debug, not warning: the only caller is the call_llm_json retry loop,
        # which warns about this same failure with the attempt number attached
        # (llm_json_retry._json_validation_failure_outcome). Warning here too
        # put two rows in the log for one event, the first strictly less
        # informative than the second.
        logger.debug("JSON schema validation failed: %s", e.message)
        logger.debug(
            "validation error path: %s", ".".join(str(p) for p in e.path)
        )
        logger.debug("first 500 chars of result: %s", str(result)[:500])
        raise


# Post-generation "enhancement" nodes degrade gracefully when their LLM output
# cannot be parsed or validated after all retries: the run keeps the hypotheses
# it has and skips the enhancement rather than aborting. Foundational nodes
# (hypothesis generation, supervisor planning) are intentionally absent -- with
# no hypotheses there is no run, so they fail loud. Each fallback is shaped so
# the consuming node's ``.get(field, default)`` logic yields a sensible empty or
# neutral result (e.g. evolution returns ``{}`` -> the node keeps the original
# hypothesis; batch review returns no rows -> every review is counted as failed
# and its hypothesis stays unreviewed for the next pass).
_ENHANCEMENT_NODE_FALLBACKS: dict[str, dict[str, Any]] = {
    "proximity_analysis": {
        "similarity_clusters": [],
        "diversity_assessment": "Analysis failed - skipping deduplication",
        "redundancy_assessment": "Analysis failed - skipping deduplication",
    },
    "hypothesis_evolution": {},
    "hypothesis_review": {},
    "hypothesis_batch_review": {"reviews": []},
    "reflection_observations": {},
    "meta_review": {},
    "deep_verification": {},
    "research_overview": {},
}


def get_fallback_response(
    json_schema: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Get fallback placeholder data for non-critical nodes that failed.

    Args:
        json_schema: Optional JSON schema dict (may have "name" field to
            identify node)

    Returns:
        Placeholder data for a post-generation enhancement node so the run can
        continue, or None for foundational nodes where failing loud is correct.
    """
    if json_schema is None:
        return None

    schema_name = json_schema.get("name")
    if not isinstance(schema_name, str):
        return None
    fallback = _ENHANCEMENT_NODE_FALLBACKS.get(schema_name)
    if fallback is not None:
        logger.warning(
            "Node '%s' failed JSON parsing after all retries; returning a "
            "fallback so the run degrades gracefully instead of aborting.",
            schema_name,
        )
        # The run continues on the fallback below; this only makes the
        # degradation durable (state key) and visible (progress event) so a
        # blank report section can explain itself.
        record_schema_degradation(schema_name)
        # Deep-copy so a caller mutating nested lists/dicts cannot corrupt the
        # shared template.
        return copy.deepcopy(fallback)

    # Foundational/critical nodes - no fallback, propagate the error.
    return None


# Type-neutral placeholder factories for schema types with no special
# handling. Callables (not bare values) so "object"/"array" each return a
# fresh dict/list per call instead of one shared mutable instance -- "string"
# and "integer"/"number" are handled separately below since "string" needs
# the schema's enum (if any) and int 0 is immutable so aliasing is moot.
_FIELD_TYPE_DEFAULT_FACTORIES: dict[str, Callable[[], Any]] = {
    "object": dict,
    "array": list,
    "integer": lambda: 0,
    "number": lambda: 0,
}


def _default_for_field_schema(field_schema: dict[str, Any]) -> Any:
    """Returns a type-neutral placeholder value for a schema field.

    Args:
        field_schema: JSON schema node describing the missing field.

    Returns:
        The first enum value (or empty string) for a "string" type, ``{}``
        for "object", ``[]`` for "array", ``0`` for "integer"/"number", and
        an empty string for any other (or missing) declared type.
    """
    field_type = field_schema.get("type")
    if field_type == "string":
        return field_schema["enum"][0] if "enum" in field_schema else ""
    if not isinstance(field_type, str):
        return ""
    factory = _FIELD_TYPE_DEFAULT_FACTORIES.get(field_type)
    return factory() if factory is not None else ""


def _is_backfillable(obj: Any, schema: Any) -> bool:
    """Checks whether both obj and schema are dicts worth backfilling.

    Args:
        obj: Parsed JSON value to check.
        schema: JSON schema node to check.

    Returns:
        True if both are dicts (any other shape is left untouched).
    """
    return isinstance(obj, dict) and isinstance(schema, dict)


def _fill_missing_required_fields(
    obj: dict[str, Any], schema: dict[str, Any], props: dict[str, Any]
) -> None:
    """Fills required-but-absent fields on obj with type-neutral defaults.

    Args:
        obj: Dict to backfill in place.
        schema: JSON schema node describing ``obj``.
        props: ``schema["properties"]``, pre-extracted by the caller.
    """
    for field in schema.get("required", []):
        if field not in obj and field in props:
            obj[field] = _default_for_field_schema(props[field])


def _recurse_into_properties(
    obj: dict[str, Any], props: dict[str, Any]
) -> None:
    """Recurses backfilling into every property schema present in obj.

    Args:
        obj: Dict whose values may themselves need backfilling.
        props: ``schema["properties"]`` describing ``obj``'s fields.
    """
    for key, value in obj.items():
        if key in props:
            _backfill_child(value, props[key])


def _backfill_child(value: Any, property_schema: Any) -> None:
    """Backfills one property's value, descending into arrays element-wise.

    Mirrors ``_prune_child``: ``_backfill_required_fields`` itself only
    accepts a dict, so without this an array-of-objects property (e.g. a
    schema's ``research_directions``) was handed straight to it and
    silently skipped -- a required field missing from one *item* inside
    the array never got backfilled, and the response failed schema
    validation instead of degrading.

    Args:
        value: The property's value, of any shape.
        property_schema: The schema node describing that property.
    """
    if isinstance(value, list) and isinstance(property_schema, dict):
        item_schema = property_schema.get("items")
        for item in value:
            _backfill_required_fields(item, item_schema)
        return
    _backfill_required_fields(value, property_schema)


def _backfill_required_fields(obj: Any, schema: Any) -> None:
    """Recursively fills missing required fields with empty defaults.

    Provider-capability shim for json_object-only models (see
    ``co_scientist.llm_request._supports_json_schema_response_format``):
    without server-side schema enforcement those models routinely omit nested
    required fields (e.g.
    ``performance_assessment.agent_performance.reflection_agent``), which
    would otherwise abort the run in schema validation. Missing required
    fields are filled in place with neutral empty values (empty string or
    first enum value, ``{}``, ``[]``, ``0``); fields that are present are
    never modified. Recurses into array-of-object properties element-wise
    (``_backfill_child``), so a field missing from one item of a list
    schema (e.g. one entry of ``research_directions``) is backfilled the
    same as a field missing from a plain nested object.

    Args:
        obj: Parsed JSON value to back-fill (non-dicts are ignored).
        schema: JSON schema node describing ``obj``.
    """
    if not _is_backfillable(obj, schema):
        return
    props = schema.get("properties", {})
    # Step 1: fill any required field missing from obj with a type-neutral
    # default so the schema's "required" check passes on validation.
    _fill_missing_required_fields(obj, schema, props)
    # Step 2: recurse into every property present in obj -- both fields that
    # were already there and ones just backfilled above -- so nested
    # required fields at any depth get the same treatment.
    _recurse_into_properties(obj, props)


def _prune_unknown_properties(obj: Any, schema: Any) -> None:
    """Recursively drops properties a closed schema node does not declare.

    Provider-capability shim for json_object-only models (see
    ``co_scientist.llm_request._supports_json_schema_response_format``), and
    the mirror image of ``_backfill_required_fields``: without server-side
    enforcement a model both omits required fields and invents extra ones,
    and every object node in this engine's schemas is closed
    (``schemas/builders.obj``), so a single invented key fails the whole
    response. Feeding that error back is no cure -- a production
    research_overview call answered with the same three invented sections on
    all five attempts before falling back to nothing.

    Only names are touched: an unknown key under a closed node is removed in
    place, everything the schema declares is left exactly as it arrived, and
    a node that allows extras keeps them.

    Args:
        obj: Parsed JSON value to prune (non-dicts are ignored).
        schema: JSON schema node describing ``obj``.
    """
    if not _is_backfillable(obj, schema):
        return
    props = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        _drop_undeclared_keys(obj, props)
    for key, value in obj.items():
        if key in props:
            _prune_child(value, props[key])


def _drop_undeclared_keys(obj: dict[str, Any], props: dict[str, Any]) -> None:
    """Removes, in place, every key of obj that props does not declare."""
    for key in [key for key in obj if key not in props]:
        del obj[key]


def _prune_child(value: Any, property_schema: Any) -> None:
    """Prunes one property's value, descending into arrays element-wise.

    Args:
        value: The property's value, of any shape.
        property_schema: The schema node describing that property.
    """
    if isinstance(value, list) and isinstance(property_schema, dict):
        item_schema = property_schema.get("items")
        for item in value:
            _prune_unknown_properties(item, item_schema)
        return
    _prune_unknown_properties(value, property_schema)


def _truncate_oversized_arrays(obj: Any, schema: Any) -> None:
    """Recursively truncates arrays that exceed their schema's ``maxItems``.

    Provider-capability shim for json_object-only models (see
    ``_supports_json_schema_response_format``), alongside
    ``_prune_unknown_properties`` and ``_backfill_required_fields``: without
    server-side enforcement ``maxItems`` is advisory only, so an otherwise
    valid answer one item over the limit fails the whole response.
    Production returned six good experiment-plan steps against a
    ``maxItems: 5`` schema and paid for a doomed retry, even though the
    consuming node already truncates to the same cap defensively
    (``MAX_EXPERIMENT_STEPS``) -- the sixth step was never surviving anyway.

    Reshapes the OUTPUT only. It runs on a parsed response and must never
    be pointed at a prompt -- trimming an LLM's input this way is exactly
    what the "Trim the schema, never the input" gotcha (root ``AGENTS.md``)
    forbids.

    Args:
        obj: Parsed JSON value to truncate in place (non-dicts are ignored).
        schema: JSON schema node describing ``obj``.
    """
    if not _is_backfillable(obj, schema):
        return
    props = schema.get("properties", {})
    for key, value in obj.items():
        if key in props:
            _truncate_child(value, props[key])


def _truncate_child(value: Any, property_schema: Any) -> None:
    """Truncates one property's array value, then recurses into its items.

    Mirrors ``_prune_child``/``_backfill_child``: cuts an over-long array to
    its ``maxItems`` in place, then walks each remaining item with the
    array's own item schema -- covering an array nested inside an object
    nested inside another array in one recursive call.

    Args:
        value: The property's value, of any shape.
        property_schema: The schema node describing that property.
    """
    if not isinstance(property_schema, dict):
        return
    if isinstance(value, list):
        max_items = property_schema.get("maxItems")
        if isinstance(max_items, int) and len(value) > max_items:
            del value[max_items:]
        item_schema = property_schema.get("items")
        for item in value:
            _truncate_oversized_arrays(item, item_schema)
        return
    _truncate_oversized_arrays(value, property_schema)


def _validation_feedback(error: ValidationError) -> str:
    """Builds the retry-prompt suffix describing a schema validation error.

    Args:
        error: The validation error from the previous attempt.

    Returns:
        Feedback text to append to the original prompt for the retry.
    """
    error_path = ".".join(str(p) for p in error.path) if error.path else "root"
    return (
        "\n\n--- VALIDATION ERROR FROM PREVIOUS"
        " ATTEMPT ---\n"
        f"Error: {error.message}\n"
        f"Location: {error_path}\n"
        "Please ensure your JSON output strictly"
        " matches the required schema structure.\n"
        "---"
    )
