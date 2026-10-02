"""Parse and validate model JSON, with bounded fallback for enhancement nodes.

For json_object-only providers, reshape response fields before validation:
remove unknown closed-object keys, fill required fields, and cap oversized
arrays/strings. Content constraints (enums, patterns, minima) still validate
normally. This applies only to parsed output, never to prompt inputs.
"""

import copy
import logging
from typing import Any

import jsonschema
from jsonschema.exceptions import ValidationError

from co_scientist.exceptions import ResponseParseError
from co_scientist.llm.structured.lists import coerce_json_list
from co_scientist.llm.structured.repair import (
    attempt_json_repair,
    extract_response_json,
)
from co_scientist.progress import record_schema_degradation

logger = logging.getLogger(__name__)


def parse_tool_loop_json(
    final_response: str, list_key: str, phase_label: str
) -> list[Any]:
    """Parse a tool-calling loop's final response into its named list.

    Shared by the tool-based generation phases (drafting and validation
    synthesis), which each end a tool-calling loop by asking for one JSON
    object holding a single list.

    allow_major_repairs=True: tool-calling loop final responses are more
    prone to truncated/malformed JSON than single-shot calls (llm/call.py).

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
    # same unwrap pattern is used by the response reshaper and
    # in co_scientist.llm.request.completion._inject_schema_into_prompt.
    # Extract actual schema from nested structure if present
    actual_schema = json_schema.get("schema", json_schema)

    try:
        jsonschema.validate(instance=result, schema=actual_schema)
        logger.debug("JSON schema validation passed")
    except ValidationError as e:
        # Debug, not warning: the only caller is the call_llm_json retry loop,
        # which warns about this same failure with the attempt number attached
        # (llm.attempts.json_attempt._validation_failure). Warning here
        # too put two rows in the log for one event, the first strictly less
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


def _default_for_field_schema(schema: dict[str, Any]) -> Any:
    """Return a fresh neutral value for an omitted required field."""
    kind = schema.get("type")
    if kind == "string":
        return schema["enum"][0] if "enum" in schema else ""
    factories = {"object": dict, "array": list, "integer": int, "number": int}
    factory = factories.get(kind) if isinstance(kind, str) else None
    return factory() if factory is not None else ""


def reshape_json_output(obj: Any, schema: Any, _path: str = "") -> None:
    """Reshape a parsed response to a provider's unenforced object schema.

    Mutates declared fields in place, keeping unknown fields under open
    schemas and leaving incorrect value types for normal validation.
    Arrays and strings are capped only by maxItems/maxLength. String cuts
    prefer a word boundary within the last 20% of the allowed length.
    """
    if not isinstance(obj, dict) or not isinstance(schema, dict):
        return
    props = schema.get("properties", {})
    _reshape_object_fields(obj, schema, props)
    for key, value in obj.items():
        if key in props:
            field_path = f"{_path}.{key}" if _path else key
            obj[key] = _reshape_value(value, props[key], field_path)


def _reshape_object_fields(
    obj: dict[str, Any], schema: dict[str, Any], props: dict[str, Any]
) -> None:
    """Remove undeclared closed-object keys and fill required properties."""
    if schema.get("additionalProperties") is False:
        for key in obj.keys() - props.keys():
            del obj[key]
    for field in schema.get("required", []):
        if field not in obj and field in props:
            obj[field] = _default_for_field_schema(props[field])


def _reshape_value(value: Any, schema: Any, field_path: str) -> Any:
    """Reshape a declared property's value and its nested fields."""
    if not isinstance(schema, dict):
        return value
    if isinstance(value, str):
        return _truncate_string_value(
            value, schema.get("maxLength"), field_path
        )
    if isinstance(value, list):
        _reshape_array(value, schema, field_path)
        return value
    reshape_json_output(value, schema, field_path)
    return value


def _reshape_array(
    value: list[Any], schema: dict[str, Any], field_path: str
) -> None:
    """Cap an array and reshape its retained items against their schema."""
    limit = schema.get("maxItems")
    if isinstance(limit, int) and len(value) > limit:
        del value[limit:]
    item_schema = schema.get("items")
    for index, item in enumerate(value):
        value[index] = _reshape_value(
            item, item_schema, f"{field_path}[{index}]"
        )


def _truncate_string_value(value: str, max_length: Any, field_path: str) -> str:
    """Cap a string, preferring a word boundary near the limit.

    Leave strings within their cap untouched and record each truncation
    with the field path. Missing or non-integer caps leave values intact.
    """
    if not isinstance(max_length, int) or len(value) <= max_length:
        return value
    candidate = value[:max_length]
    boundary_window = max_length - max(1, round(max_length * 0.2))
    boundary = candidate.rfind(" ", max(0, boundary_window))
    truncated = candidate[:boundary].rstrip() if boundary != -1 else candidate
    logger.warning(
        "Truncated over-long string at '%s': %d chars -> %d chars"
        " (schema maxLength=%d)",
        field_path,
        len(value),
        len(truncated),
        max_length,
    )
    return truncated


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
