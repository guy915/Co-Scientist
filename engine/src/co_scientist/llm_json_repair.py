"""JSON extraction and repair helpers for LLM responses.

Provides extraction of JSON payloads from raw LLM output (markdown fence
stripping) and repair of common syntax errors, from safe minor fixes to
truncation-oriented major repairs. These helpers are pure (no network
access); they are re-exported by ``co_scientist.llm_json`` alongside the
schema-validation utilities that consume them.
"""

import json
import logging
import re
from collections.abc import Callable
from typing import Any

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
                logger.warning(
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
