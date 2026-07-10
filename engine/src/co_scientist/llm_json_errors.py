"""Failure diagnostics and terminal errors for ``call_llm_json``.

Resolves a ``call_llm_json`` run whose parse/validation retries are all
exhausted: non-critical nodes (those with a registered fallback for their
schema) degrade to fallback data, while critical nodes get failure
diagnostics logged and the most appropriate error raised.
"""

import json
import logging
from typing import Any, NoReturn

from jsonschema.exceptions import ValidationError

from co_scientist.llm_json import get_fallback_response

logger = logging.getLogger(__name__)


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
