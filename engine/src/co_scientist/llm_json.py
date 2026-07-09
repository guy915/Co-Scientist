"""JSON handling utilities for LLM responses.

Provides extraction of JSON payloads from raw LLM output, repair of common
syntax errors, schema validation, and fallback responses for non-critical
nodes. These helpers are pure (no network access) and are shared by the LLM
call wrappers in ``co_scientist.llm`` and the tool-based generation phases.
"""
# pylint: disable=inconsistent-quotes

import copy
import json
import logging
import re
from typing import Any
from collections.abc import Callable

import jsonschema
from jsonschema.exceptions import ValidationError

logger = logging.getLogger(__name__)


def extract_response_json(raw: str) -> str:
    """Strip markdown code fences and whitespace from an LLM response.

    Handles ```json and plain ``` fences case-insensitively, including
    responses whose closing fence was truncated away.

    Args:
        raw: Raw LLM response text.

    Returns:
        The fenced payload (or the stripped text when no fence is present).
    """
    text = raw.strip()
    lower = text.lower()
    if "```json" in lower:
        start = lower.find("```json") + 7
        end = text.find("```", start)
        text = text[start:] if end == -1 else text[start:end]
    elif "```" in text:
        # Fallback: a plain ``` fence with no "json" language tag.
        start = text.find("```") + 3
        end = text.find("```", start)
        text = text[start:] if end == -1 else text[start:end]
    return text.strip()


def _close_truncated_json(s: str) -> str:
    """Try to close truncated JSON by adding missing braces/brackets."""
    # Count open vs closed braces and brackets
    open_braces = s.count("{") - s.count("}")
    open_brackets = s.count("[") - s.count("]")

    # Enhanced unterminated string detection
    # Check if the string ends mid-value (unterminated string)
    stripped = s.rstrip()

    # Nothing to close for empty/whitespace input.
    if not stripped:
        return s

    # Pattern 1: Ends with opening quote after colon/comma (e.g., ':"text)
    if re.search(r'[:,]\s*"[^"]*$', stripped):
        s = s + '"'
        logger.debug("repaired: unterminated string after colon/comma")

    # Pattern 2: Ends with partial field name (e.g., '"field_na)
    elif re.search(r'"\w+$', stripped):
        # Find if we're in a string literal or field name
        # Count quotes before this position to determine context
        before_partial = stripped[:-20] if len(stripped) > 20 else ""
        quote_count = before_partial.count('"')
        if quote_count % 2 == 1:  # Odd number = we're inside a string
            s = s + '"'
            logger.debug("repaired: unterminated field name/string")

    # Pattern 3: Ends mid-array without closing (e.g., '"item1", "item2)
    elif stripped.endswith(",") or (stripped[-1].isalnum() and "[" in stripped):
        # Likely truncated mid-array or mid-value
        # Try to close intelligently based on context
        last_open_bracket = stripped.rfind("[")
        last_close_bracket = stripped.rfind("]")
        if last_open_bracket > last_close_bracket:
            # We're inside an unclosed array
            # Check if we need to close a string first
            after_bracket = stripped[last_open_bracket:]
            quote_count = after_bracket.count('"')
            if quote_count % 2 == 1:
                s = s + '"'
                logger.debug("repaired: unterminated string in array")

    # Remove trailing comma if present
    s = re.sub(r",\s*$", "", s)

    # Add missing closing characters
    # Close arrays first, then objects (proper nesting)
    result = s + ("]" * open_brackets) + ("}" * open_braces)

    if open_braces > 0 or open_brackets > 0:
        logger.debug("repaired: added %s ']' and %s '}'", open_brackets,
                     open_braces)

    return result


def _fix_invalid_escapes(s: str) -> str:
    r"""Escape lone backslashes that are not valid JSON escapes.

    LLMs frequently emit LaTeX or math notation inside string values
    (e.g. ``GFP-Ub\(^{G76V}\)``). ``\(`` is not a valid JSON escape and
    breaks parsing. Double any backslash not followed by a valid JSON
    escape character (``" \ / b f n r t u``) so the literal backslash
    survives and the value parses.
    """
    return re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", s)


# Minor repairs (safe, don't indicate truncation). Built once at import time
# since none of the lambdas capture anything beyond their own argument.
_MINOR_JSON_REPAIR_STRATEGIES: list[Callable[[str], Any]] = [
    # Remove trailing commas before closing braces/brackets
    lambda s: json.loads(re.sub(r",(\s*[}\]])", r"\1", s)),
    # Escape invalid backslash sequences (LaTeX/math notation from LLMs)
    lambda s: json.loads(_fix_invalid_escapes(s)),
    # Both: invalid escapes and trailing commas
    lambda s: json.loads(_fix_invalid_escapes(re.sub(r",(\s*[}\]])", r"\1", s))
                        ),
]

# Major repairs (indicate truncation/incomplete, only tried on the final
# retry attempt).
_MAJOR_JSON_REPAIR_STRATEGIES: list[Callable[[str], Any]] = [
    # Close unterminated strings and truncated JSON (most common Gemini
    # issue)
    lambda s: json.loads(_close_truncated_json(s)),
    # Remove trailing commas AND close truncated JSON
    lambda s: json.loads(_close_truncated_json(re.sub(r",(\s*[}\]])", r"\1", s))
                        ),
    # Aggressively remove incomplete trailing content and close JSON
    lambda s: json.loads(_close_truncated_json(re.sub(r',?\s*"[^"]*$', "", s))),
    # Remove incomplete field (key OR value) and close
    lambda s: json.loads(_close_truncated_json(re.sub(r'[:,]\s*"[^"]*$', "", s))
                        ),
    # Find last complete comma, truncate there, then close
    lambda s: json.loads(
        _close_truncated_json(s[:s.rfind(",") + 1] if "," in s else s)),
    # Extract first complete JSON object using regex
    lambda s: (json.loads(m.group(0))
               if (m := re.search(r"\{.*\}", s, re.DOTALL)) else None),
]


def attempt_json_repair(
        json_str: str,
        allow_major_repairs: bool = False
) -> tuple[dict[str, Any] | None, bool]:
    """Attempt to repair common JSON syntax errors from LLM outputs.

    With json_schema response formats, most responses should be valid JSON.
    This function first tries to parse as-is, and only attempts repairs if
    needed.

    Args:
        json_str: Potentially malformed JSON string
        allow_major_repairs: If True, attempt major repairs (indicate
                           truncation). If False, only attempt minor repairs
                           (safe syntax fixes).

    Returns:
        Tuple of (parsed JSON dict if successful, was_major_repair: bool)
        Returns (None, False) if all repair attempts failed
    """
    # First, try parsing as-is (should work for json_schema responses)
    try:
        result = json.loads(json_str)
        if isinstance(result, dict):
            return result, False
    except json.JSONDecodeError:
        # JSON is malformed, proceed with repair strategies
        pass

    # Try minor repairs first
    for i, repair_fn in enumerate(_MINOR_JSON_REPAIR_STRATEGIES):
        try:
            result = repair_fn(json_str)
            if result:
                logger.debug("JSON repaired using minor repair strategy %s", i)
                return result, False
        except (json.JSONDecodeError, AttributeError, TypeError) as e:
            logger.debug("minor repair strategy %s failed: %s", i, e)
            continue

    # If major repairs are allowed, try them
    if allow_major_repairs:
        for i, repair_fn in enumerate(_MAJOR_JSON_REPAIR_STRATEGIES):
            try:
                result = repair_fn(json_str)
                if result:
                    logger.warning(
                        "JSON repaired using major repair strategy %s "
                        "(indicates truncation/incomplete response)", i)
                    return result, True
            except (json.JSONDecodeError, AttributeError, TypeError) as e:
                if i < 2:  # Only log for first few strategies
                    logger.debug("major repair strategy %s failed: %s", i, e)
                continue

    return None, False


def validate_json_schema(result: dict[str, Any],
                         json_schema: dict[str, Any] | None) -> None:
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
    # in co_scientist.llm._inject_schema_into_prompt.
    # Extract actual schema from nested structure if present
    actual_schema = json_schema.get("schema", json_schema)

    try:
        jsonschema.validate(instance=result, schema=actual_schema)
        logger.debug("JSON schema validation passed")
    except ValidationError as e:
        logger.warning("JSON schema validation failed: %s", e.message)
        logger.debug("validation error path: %s",
                     '.'.join(str(p) for p in e.path))
        logger.debug("first 500 chars of result: %s", str(result)[:500])
        raise


# Post-generation "enhancement" nodes degrade gracefully when their LLM output
# cannot be parsed or validated after all retries: the run keeps the hypotheses
# it has and skips the enhancement rather than aborting. Foundational nodes
# (hypothesis generation, supervisor planning) are intentionally absent -- with
# no hypotheses there is no run, so they fail loud. Each fallback is shaped so
# the consuming node's ``.get(field, default)`` logic yields a sensible empty or
# neutral result (e.g. evolution returns ``{}`` -> the node keeps the original
# hypothesis; batch review returns no rows -> "Review unavailable" stubs).
_ENHANCEMENT_NODE_FALLBACKS: dict[str, dict[str, Any]] = {
    "proximity_analysis": {
        "similarity_clusters": [],
        "diversity_assessment": "Analysis failed - skipping deduplication",
        "redundancy_assessment": "Analysis failed - skipping deduplication",
    },
    "hypothesis_evolution": {},
    "hypothesis_review": {},
    "hypothesis_batch_review": {
        "reviews": []
    },
    "reflection_observations": {},
    "meta_review": {},
    "deep_verification": {},
    "research_overview": {},
}


def get_fallback_response(
        json_schema: dict[str, Any] | None) -> dict[str, Any] | None:
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
            schema_name)
        # Deep-copy so a caller mutating nested lists/dicts cannot corrupt the
        # shared template.
        return copy.deepcopy(fallback)

    # Foundational/critical nodes - no fallback, propagate the error.
    return None


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
    elif field_type == "object":
        return {}
    elif field_type == "array":
        return []
    elif field_type in ("integer", "number"):
        return 0
    else:
        return ""


def _backfill_required_fields(obj: Any, schema: Any) -> None:
    """Recursively fills missing required fields with empty defaults.

    Provider-capability shim for json_object-only models (see
    ``co_scientist.llm._supports_json_schema_response_format``): without
    server-side schema enforcement those models routinely omit nested required
    fields (e.g.
    ``performance_assessment.agent_performance.reflection_agent``), which
    would otherwise abort the run in schema validation. Missing required
    fields are filled in place with neutral empty values (empty string or
    first enum value, ``{}``, ``[]``, ``0``); fields that are present are
    never modified.

    Args:
        obj: Parsed JSON value to back-fill (non-dicts are ignored).
        schema: JSON schema node describing ``obj``.
    """
    if not isinstance(obj, dict) or not isinstance(schema, dict):
        return
    props = schema.get("properties", {})
    # Step 1: fill any required field missing from obj with a type-neutral
    # default so the schema's "required" check passes on validation.
    for field in schema.get("required", []):
        if field not in obj and field in props:
            obj[field] = _default_for_field_schema(props[field])
    # Step 2: recurse into every property present in obj -- both fields that
    # were already there and ones just backfilled above -- so nested
    # required fields at any depth get the same treatment.
    for key, value in obj.items():
        if key in props:
            _backfill_required_fields(value, props[key])


def _validation_feedback(error: ValidationError) -> str:
    """Builds the retry-prompt suffix describing a schema validation error.

    Args:
        error: The validation error from the previous attempt.

    Returns:
        Feedback text to append to the original prompt for the retry.
    """
    error_path = ".".join(str(p) for p in error.path) if error.path else "root"
    return ("\n\n--- VALIDATION ERROR FROM PREVIOUS"
            " ATTEMPT ---\n"
            f"Error: {error.message}\n"
            f"Location: {error_path}\n"
            "Please ensure your JSON output strictly"
            " matches the required schema structure.\n"
            "---")
