"""Structured-output parsing, repair, feedback, validation and reshaping."""

import copy
import json
import logging
import re
from collections.abc import Callable
from typing import Any, Literal, NoReturn, overload

import jsonschema
from jsonschema.exceptions import ValidationError

from co_scientist.exceptions import ResponseParseError
from co_scientist.progress import record_schema_degradation

logger = logging.getLogger(__name__)


ElementKind = Literal["any", "dict", "str"]


def _element_ok(item: Any, element: ElementKind) -> bool:
    """Whether one list element already matches the wanted element kind."""
    if element == "dict":
        return isinstance(item, dict)
    if element == "str":
        return isinstance(item, str)
    return True


def _clean_str_element(item: str) -> str:
    """Strip one string element; blank strings are dropped by the caller."""
    return item.strip()


def _filter_elements(
    items: list[Any], element: ElementKind
) -> tuple[list[Any], bool]:
    """Keep only well-typed, non-blank elements; report whether any dropped.

    Args:
        items: The raw list to filter.
        element: The element kind every entry must satisfy.

    Returns:
        The kept elements (strings stripped), and whether anything was
        dropped -- a wrong-typed entry, or (for ``"str"``) a blank one.
    """
    kept: list[Any] = []
    dropped = False
    for item in items:
        if not _element_ok(item, element):
            dropped = True
            continue
        if element == "str":
            cleaned = _clean_str_element(item)
            if not cleaned:
                dropped = True
                continue
            kept.append(cleaned)
        else:
            kept.append(item)
    return kept, dropped


def _list_from_dict(
    value: dict[str, Any], keys: tuple[str, ...], element: ElementKind
) -> list[Any] | None:
    """Recover a list from a dict: a known key, or the dict as one element.

    Args:
        value: The dict found where a list was expected.
        keys: Property names that might carry the list, tried in order.
        element: The element kind the caller wants.

    Returns:
        The list found under a key, ``[value]`` when ``value`` itself is
        the single element wanted (``element="dict"``), or ``None`` when
        nothing usable could be recovered.
    """
    for key in keys:
        found = value.get(key)
        if isinstance(found, list):
            return found
    if element == "dict":
        return [value]
    return None


def _coerce_from_list(
    value: list[Any], element: ElementKind, site: str
) -> list[Any]:
    """Filter an already-list value, warning only if something was dropped."""
    items, dropped = _filter_elements(value, element)
    if dropped:
        logger.warning("%s: dropped list element(s) of the wrong type", site)
    return items


def _coerce_from_dict(
    value: dict[str, Any],
    keys: tuple[str, ...],
    element: ElementKind,
    site: str,
) -> list[Any]:
    """Recover a list from a dict, warning either way -- a real coercion."""
    found = _list_from_dict(value, keys, element)
    if found is None:
        logger.warning(
            "%s: expected a list, got a dict with no usable list", site
        )
        return []
    items, _dropped = _filter_elements(found, element)
    logger.warning("%s: coerced a dict into a list", site)
    return items


def _coerce_from_scalar(
    value: Any, element: ElementKind, site: str
) -> list[Any]:
    """Wrap a bare non-list, non-dict scalar into a one-element list."""
    if element != "str" or not isinstance(value, str) or not value.strip():
        logger.warning(
            "%s: expected a list, got %s", site, type(value).__name__
        )
        return []
    logger.warning("%s: coerced a bare value into a one-item list", site)
    return [value.strip()]


@overload
def coerce_json_list(
    value: Any,
    *,
    keys: tuple[str, ...] = (),
    element: Literal["str"],
    site: str,
) -> list[str]: ...


@overload
def coerce_json_list(
    value: Any,
    *,
    keys: tuple[str, ...] = (),
    element: Literal["dict"],
    site: str,
) -> list[dict[str, Any]]: ...


@overload
def coerce_json_list(
    value: Any,
    *,
    keys: tuple[str, ...] = (),
    element: Literal["any"] = "any",
    site: str,
) -> list[Any]: ...


def coerce_json_list(
    value: Any,
    *,
    keys: tuple[str, ...] = (),
    element: ElementKind = "any",
    site: str,
) -> list[Any]:
    """Coerce a parsed LLM JSON value into the list a caller expects.

    Overloaded on ``element``: ``"str"`` and ``"dict"`` narrow the return
    type to what ``_filter_elements`` actually guarantees at runtime for
    those cases, so a caller declaring ``list[str]`` or ``list[dict[str,
    Any]]`` gets a checked return rather than an ``Any`` it has to trust.

    Args:
        value: The parsed value found where a list was expected.
        keys: Property names to look under when ``value`` is a dict
            carrying the list rather than being the list itself --
            typically the schema's own field name plus a generic
            fallback such as ``"items"``.
        element: The element type each list entry must satisfy --
            ``"dict"`` drops non-dict entries (and lets a bare dict
            stand for a one-element list), ``"str"`` coerces scalars to
            stripped, non-blank strings, ``"any"`` performs no
            per-element filtering.
        site: The call site, logged with any coercion warning so a run
            that degraded silently can be traced back to where.

    Returns:
        A list of well-typed elements; empty when nothing usable could
        be recovered from ``value``.
    """
    if isinstance(value, list):
        return _coerce_from_list(value, element, site)
    if value is None:
        return []
    if isinstance(value, dict):
        return _coerce_from_dict(value, keys, element, site)
    return _coerce_from_scalar(value, element, site)


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


def _repair_string_after_colon_or_comma(s: str, stripped: str) -> str | None:
    """Closes a string left open right after a colon or comma.

    E.g. ``':"text``.

    Args:
        s: The full truncated JSON string being repaired.
        stripped: ``s.rstrip()``.

    Returns:
        ``s`` with a closing quote appended when ``stripped`` matches this
        truncation shape, or ``None`` when it doesn't (so the next pattern
        in the chain gets a chance).
    """
    if re.search(r'[:,]\s*"[^"]*$', stripped):
        logger.debug("repaired: unterminated string after colon/comma")
        return s + '"'
    return None


def _repair_unterminated_field_name(s: str, stripped: str) -> str | None:
    """Closes a string left open mid partial field name/value.

    E.g. ``'"field_na``.

    Args:
        s: The full truncated JSON string being repaired.
        stripped: ``s.rstrip()``.

    Returns:
        ``s``, with a closing quote appended when the partial name/value
        sits inside an open string, when ``stripped`` matches this
        truncation shape; ``None`` when it doesn't. Matching this shape
        always "commits" -- even when no quote needs adding -- mirroring
        the original elif chain, where this branch never falls through to
        the array-truncation pattern below.
    """
    if not re.search(r'"\w+$', stripped):
        return None
    # Count quotes before this position to determine context.
    before_partial = stripped[:-20] if len(stripped) > 20 else ""
    if before_partial.count('"') % 2 == 1:  # Odd number = inside a string.
        logger.debug("repaired: unterminated field name/string")
        return s + '"'
    return s


def _looks_like_truncated_array_entry(stripped: str) -> bool:
    """Checks whether text ends mid an unclosed-array string entry.

    Args:
        stripped: Right-stripped truncated JSON text.

    Returns:
        True if the text ends with a trailing comma, or ends with an
        alphanumeric character while an array bracket is still open.
    """
    return stripped.endswith(",") or (
        stripped[-1].isalnum() and "[" in stripped
    )


def _repair_unterminated_array_string(s: str, stripped: str) -> str | None:
    """Closes a string left open mid truncated array entry.

    E.g. ``'"item1", "item2``.

    Args:
        s: The full truncated JSON string being repaired.
        stripped: ``s.rstrip()``.

    Returns:
        ``s``, with a closing quote appended when we're inside an unclosed
        array and mid-string, when ``stripped`` matches this truncation
        shape; ``None`` when it doesn't.
    """
    if not _looks_like_truncated_array_entry(stripped):
        return None
    last_open_bracket = stripped.rfind("[")
    last_close_bracket = stripped.rfind("]")
    if last_open_bracket <= last_close_bracket:
        return s
    after_bracket = stripped[last_open_bracket:]
    if after_bracket.count('"') % 2 == 1:
        logger.debug("repaired: unterminated string in array")
        return s + '"'
    return s


_UNTERMINATED_STRING_REPAIRS: tuple[Callable[[str, str], str | None], ...] = (
    _repair_string_after_colon_or_comma,
    _repair_unterminated_field_name,
    _repair_unterminated_array_string,
)


def _repair_unterminated_string(s: str, stripped: str) -> str:
    """Applies the first matching unterminated-string repair pattern.

    Args:
        s: The full truncated JSON string being repaired.
        stripped: ``s.rstrip()``, used to detect the truncation shape.

    Returns:
        ``s``, possibly with a closing quote appended.
    """
    for repair in _UNTERMINATED_STRING_REPAIRS:
        result = repair(s, stripped)
        if result is not None:
            return result
    return s


def _close_truncated_json(s: str) -> str:
    """Try to close truncated JSON by adding missing braces/brackets."""
    # Count open vs closed braces and brackets
    open_braces = s.count("{") - s.count("}")
    open_brackets = s.count("[") - s.count("]")

    stripped = s.rstrip()

    # Nothing to close for empty/whitespace input.
    if not stripped:
        return s

    s = _repair_unterminated_string(s, stripped)

    # Remove trailing comma if present
    s = re.sub(r",\s*$", "", s)

    # Add missing closing characters
    # Close arrays first, then objects (proper nesting)
    result = s + ("]" * open_brackets) + ("}" * open_braces)

    if open_braces > 0 or open_brackets > 0:
        logger.debug(
            "repaired: added %s ']' and %s '}'", open_brackets, open_braces
        )

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
_MINOR_JSON_REPAIR_STRATEGIES: list[Callable[[str], dict[str, Any] | None]] = [
    # Remove trailing commas before closing braces/brackets
    lambda s: json.loads(re.sub(r",(\s*[}\]])", r"\1", s)),
    # Escape invalid backslash sequences (LaTeX/math notation from LLMs)
    lambda s: json.loads(_fix_invalid_escapes(s)),
    # Both: invalid escapes and trailing commas
    lambda s: json.loads(
        _fix_invalid_escapes(re.sub(r",(\s*[}\]])", r"\1", s))
    ),
    # Admit literal control characters inside strings. A model writing
    # prose into a string field presses return inside it, and strict JSON
    # forbids a raw newline between quotes -- so a complete, balanced
    # object is discarded over a blank line in one value. `strict=False`
    # is exactly and only this permission; it accepts nothing else the
    # parser would have rejected, so it cannot turn genuinely broken JSON
    # into a wrong answer. Measured on `openrouter/stealth/ox-alpha` in
    # json_object mode, where no server-side schema constrains the shape:
    # five ranking calls in one express run died this way, each losing a
    # tournament verdict the model had written correctly.
    lambda s: json.loads(s, strict=False),
    # And the same, once the two textual repairs above have run.
    lambda s: json.loads(
        _fix_invalid_escapes(re.sub(r",(\s*[}\]])", r"\1", s)), strict=False
    ),
]

# Major repairs (indicate truncation/incomplete, only tried on the final
# retry attempt).
_MAJOR_JSON_REPAIR_STRATEGIES: list[Callable[[str], dict[str, Any] | None]] = [
    # Close unterminated strings and truncated JSON (most common Gemini
    # issue)
    lambda s: json.loads(_close_truncated_json(s)),
    # Remove trailing commas AND close truncated JSON
    lambda s: json.loads(
        _close_truncated_json(re.sub(r",(\s*[}\]])", r"\1", s))
    ),
    # Aggressively remove incomplete trailing content and close JSON
    lambda s: json.loads(_close_truncated_json(re.sub(r',?\s*"[^"]*$', "", s))),
    # Remove incomplete field (key OR value) and close
    lambda s: json.loads(
        _close_truncated_json(re.sub(r'[:,]\s*"[^"]*$', "", s))
    ),
    # Find last complete comma, truncate there, then close
    lambda s: json.loads(
        _close_truncated_json(s[: s.rfind(",") + 1] if "," in s else s)
    ),
    # Extract first complete JSON object using regex
    lambda s: (
        json.loads(m.group(0))
        if (m := re.search(r"\{.*\}", s, re.DOTALL))
        else None
    ),
]


def _try_minor_repairs(json_str: str) -> dict[str, Any] | None:
    """Tries each safe (non-truncation-indicating) repair strategy in order.

    Args:
        json_str: Potentially malformed JSON string.

    Returns:
        The first successfully repaired dict, or ``None`` if all strategies
        failed.
    """
    for i, repair_fn in enumerate(_MINOR_JSON_REPAIR_STRATEGIES):
        try:
            result = repair_fn(json_str)
            if result:
                logger.debug("JSON repaired using minor repair strategy %s", i)
                return result
        except (json.JSONDecodeError, AttributeError, TypeError) as e:
            logger.debug("minor repair strategy %s failed: %s", i, e)
    return None


def _try_major_repairs(json_str: str) -> dict[str, Any] | None:
    """Tries each truncation-oriented repair strategy in order.

    Args:
        json_str: Potentially malformed (likely truncated) JSON string.

    Returns:
        The first successfully repaired dict, or ``None`` if all strategies
        failed.
    """
    for i, repair_fn in enumerate(_MAJOR_JSON_REPAIR_STRATEGIES):
        try:
            result = repair_fn(json_str)
            if result:
                # Debug, not warning: which of the strategies worked is a
                # detail for someone debugging the strategies. Both callers
                # already report the repair with the thing a reader needs
                # -- the phase whose response was truncated -- so warning
                # here only made every truncation cost two records.
                logger.debug(
                    "JSON repaired using major repair strategy %s "
                    "(indicates truncation/incomplete response)",
                    i,
                )
                return result
        except (json.JSONDecodeError, AttributeError, TypeError) as e:
            if i < 2:  # Only log for first few strategies
                logger.debug("major repair strategy %s failed: %s", i, e)
    return None


def _try_direct_parse(json_str: str) -> dict[str, Any] | None:
    """Tries parsing json_str as-is, should it already be valid JSON.

    Args:
        json_str: Potentially malformed JSON string.

    Returns:
        The parsed dict, or None if parsing failed or produced a value that
        isn't a dict (e.g. a bare list or string).
    """
    try:
        result = json.loads(json_str)
    except json.JSONDecodeError:
        # JSON is malformed, let the caller proceed with repair strategies.
        return None
    return result if isinstance(result, dict) else None


def attempt_json_repair(
    json_str: str, allow_major_repairs: bool = False
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
    direct_result = _try_direct_parse(json_str)
    if direct_result is not None:
        return direct_result, False

    minor_result = _try_minor_repairs(json_str)
    if minor_result is not None:
        return minor_result, False

    if allow_major_repairs:
        major_result = _try_major_repairs(json_str)
        if major_result is not None:
            return major_result, True

    return None, False


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


def _log_first_json_error_position(text: str) -> None:
    """Logs the position of the first JSON parse error near the tail of text.

    Scans growing prefixes of ``text`` and reports the first parse error
    found once the prefix reaches within 200 chars of the end, since that is
    typically where LLM truncation breaks the JSON.

    Args:
        text: The raw response text to scan.
    """
    for i in range(0, len(text), 100):
        chunk = text[: i + 100]
        try:
            json.loads(chunk)
        except json.JSONDecodeError as e:
            if i > len(text) - 200:  # Near the end
                logger.error("JSON error near position %s: %s", e.pos, e.msg)
                logger.error(
                    "Context around error: ...%s...",
                    text[max(0, e.pos - 100) : e.pos + 100],
                )
                break


def _log_json_parse_failure_diagnostics(last_response_text: str) -> None:
    """Logs diagnostic detail about an unparseable LLM JSON response.

    Args:
        last_response_text: The last raw response text that failed to parse
            (after fence-stripping and repair attempts).
    """
    # Log the full response for debugging
    logger.error("Failed to parse JSON response after all repair attempts.")
    logger.error("Response length: %s chars", len(last_response_text))
    logger.error("First 500 chars: %s", last_response_text[:500])
    logger.error("Last 500 chars: %s", last_response_text[-500:])

    # Log middle section too (where errors often are)
    if len(last_response_text) > 1000:
        mid_point = len(last_response_text) // 2
        logger.error(
            "Middle 500 chars (around char %s): %s",
            mid_point,
            last_response_text[mid_point - 250 : mid_point + 250],
        )

    # Try to find where JSON is broken
    try:
        # Count braces
        open_braces = last_response_text.count("{")
        close_braces = last_response_text.count("}")
        logger.error("Brace count: { = %s, } = %s", open_braces, close_braces)
        _log_first_json_error_position(last_response_text)
    except Exception as debug_err:
        logger.error("Error during debugging: %s", debug_err)


def _raise_validation_error(
    last_error: ValidationError, max_attempts: int
) -> NoReturn:
    """Re-raises a schema validation failure with an attempt-count message.

    Args:
        last_error: The schema validation failure to re-raise.
        max_attempts: Total number of attempts made.

    Raises:
        ValidationError: Always.
    """
    raise ValidationError(
        f"Schema validation failed after {max_attempts} attempts: "
        f"{last_error.message}",
        instance=last_error.instance,
        schema=last_error.schema,
        schema_path=last_error.schema_path,
        path=last_error.path,
    )


def _json_decode_error_pos(last_error: Exception | None) -> int:
    """Extracts a JSONDecodeError's character position, defaulting to 0.

    Args:
        last_error: The parse error to inspect, if any.

    Returns:
        ``last_error.pos`` when it is a ``json.JSONDecodeError``, else 0.
    """
    if isinstance(last_error, json.JSONDecodeError):
        return last_error.pos
    return 0


def _raise_json_decode_error(
    last_error: Exception | None,
    last_response_text: str | None,
    max_attempts: int,
) -> NoReturn:
    """Re-raises a parse failure with an attempt-count message.

    Args:
        last_error: The parse error to derive a position from, if any.
        last_response_text: The last raw response text, if any was received.
        max_attempts: Total number of attempts made.

    Raises:
        json.JSONDecodeError: Always.
    """
    raise json.JSONDecodeError(
        f"Could not parse LLM response as JSON after {max_attempts} attempts",
        last_response_text or "",
        _json_decode_error_pos(last_error),
    )


def _raise_json_parse_error(
    last_error: Exception | None,
    last_response_text: str | None,
    max_attempts: int,
) -> NoReturn:
    """Raises the final error after all JSON parse/repair retries fail.

    Args:
        last_error: The most recent validation or parse error, if any.
        last_response_text: The last raw response text, if any was received.
        max_attempts: Total number of attempts made.

    Raises:
        ValidationError: If ``last_error`` was a schema validation failure.
        json.JSONDecodeError: Otherwise (parse failure, or no error captured).
    """
    if isinstance(last_error, ValidationError):
        _raise_validation_error(last_error, max_attempts)
    _raise_json_decode_error(last_error, last_response_text, max_attempts)


def _handle_json_retries_exhausted(
    json_schema: dict[str, Any] | None,
    last_error: Exception | None,
    last_response_text: str | None,
    max_attempts: int,
) -> dict[str, Any]:
    """Resolves a call_llm_json run whose retries are all exhausted.

    Non-critical nodes (those with a registered fallback for their schema)
    degrade to fallback data; critical nodes get failure diagnostics logged
    and the most appropriate error raised.

    Args:
        json_schema: Optional JSON schema the failed call was constrained by.
        last_error: The most recent validation or parse error, if any.
        last_response_text: The last raw response text, if any was received.
        max_attempts: Total number of attempts made.

    Returns:
        The fallback response, when one is registered for the schema.

    Raises:
        Exception: The parse/validation error via _raise_json_parse_error
            when no fallback exists.
    """
    # Check for fallback for non-critical nodes
    fallback = get_fallback_response(json_schema)
    if fallback is not None:
        logger.warning(
            "Returning fallback data for non-critical node "
            "after all retries exhausted"
        )
        return fallback

    # No fallback available - raise appropriate error
    if last_response_text:
        _log_json_parse_failure_diagnostics(last_response_text)

    _raise_json_parse_error(last_error, last_response_text, max_attempts)
