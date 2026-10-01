"""Judging one ``call_llm_json`` response: parse, repair, validate, cache.

The attempt loop (``llm.attempts.retry``) makes the call; this module is
the ``Judge`` it hands the response text to. It parses (and, if needed,
repairs) the raw text, validates it against the schema (applying the
json_object provider-capability backfill shim first), and caches a
validated result. A response that does not pass is ``Rejected`` -- with the
validation error as feedback for the next attempt when one can follow --
and the loop decides what to do next: which rung to send it at, and
whether to wait first.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

from jsonschema.exceptions import ValidationError

from co_scientist.cache import LLMCache, LLMCacheRequest, NullCache
from co_scientist.llm.attempts.contract import Accepted, Attempt, Rejected
from co_scientist.llm.attempts.escalation import _JsonCallSpec
from co_scientist.llm.request.completion import (
    _supports_json_schema_response_format,
)
from co_scientist.llm.structured.repair import attempt_json_repair
from co_scientist.llm.structured.truncate_strings import (
    _truncate_oversized_strings,
)
from co_scientist.llm.structured.validate import (
    _backfill_required_fields,
    _prune_unknown_properties,
    _truncate_oversized_arrays,
    _validation_feedback,
    validate_json_schema,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ParsedResponse:
    """What parsing (and any repair) made of one attempt's response text.

    Attributes:
        result: The parsed JSON dict, or None when nothing parsed.
        repaired: Whether the result needed JSON repair before validation.
        parse_error: The original parse failure, used by the caller only
            when every repair attempt also fails.
    """

    result: dict[str, Any] | None
    repaired: bool
    parse_error: Exception | None


def _parse_or_repair_json(
    response_text: str,
    is_final_attempt: bool,
) -> _ParsedResponse:
    """Parses response text as JSON, falling back to repair strategies.

    Args:
        response_text: Raw (fence-stripped) LLM response text.
        is_final_attempt: Whether this is the last retry attempt; major
            (truncation-indicating) repairs are only attempted then.

    Returns:
        What parsing and any repair made of the response text.
    """
    result: dict[str, Any] | None = None
    parse_error: Exception | None = None
    try:
        result = json.loads(response_text)
        if not isinstance(result, dict):
            parse_error = ValueError("Parsed JSON is not a dictionary")
            result = None
    except json.JSONDecodeError as e:
        parse_error = e
        result = None

    repaired = False
    if result is None:
        result, _ = attempt_json_repair(
            response_text, allow_major_repairs=is_final_attempt
        )
        repaired = result is not None

    return _ParsedResponse(result, repaired, parse_error)


def _backfill_and_validate(
    result: dict[str, Any],
    json_schema: dict[str, Any],
    model_name: str,
) -> None:
    """Applies the provider-capability shims, then validates.

    Args:
        result: Parsed JSON dict to validate (and possibly reshape).
        json_schema: JSON schema dict (may have a nested "schema" key).
        model_name: Model name in litellm format, used to decide whether the
            json_object provider-capability shim applies.

    Raises:
        ValidationError: If ``result`` doesn't match ``json_schema``.
    """
    # Provider-capability shim: calls downgraded to json_object have no
    # server-side schema enforcement, so the answer can miss required fields,
    # carry invented ones, overrun a maxItems cap, or overrun a maxLength cap
    # -- all four fail a closed schema, and none is fixed by asking again.
    # Reshape to what the schema declares before validating, keyed on the
    # same condition as the downgrade in call_llm. Where the provider does
    # enforce the schema, an over-long array or string is a real anomaly and
    # stays a validation failure -- this shim only runs on the downgrade
    # path.
    if not _supports_json_schema_response_format(model_name):
        schema = json_schema.get("schema", json_schema)
        _prune_unknown_properties(result, schema)
        _backfill_required_fields(result, schema)
        _truncate_oversized_arrays(result, schema)
        _truncate_oversized_strings(result, schema)
    validate_json_schema(result, json_schema)


def _validation_failure(
    error: ValidationError,
    response_text: str,
    attempt: Attempt,
    repaired: bool,
) -> Rejected:
    """Builds the rejection for a schema validation failure.

    Args:
        error: The validation error raised for this attempt's result.
        response_text: The raw (fence-stripped) response text for this
            attempt.
        attempt: Which attempt this is.
        repaired: Whether the result needed JSON repair before validation.

    Returns:
        A rejection carrying the error, plus validation feedback for the
        next prompt unless this is the final attempt.
    """
    logger.warning(
        "Schema validation failed%s on attempt %s: %s",
        " after repair" if repaired else "",
        attempt.number,
        error.message,
    )
    feedback = None if attempt.is_final else _validation_feedback(error)
    return Rejected(error, response_text, feedback)


@dataclass(frozen=True)
class JsonJudge:
    """Judges the response text of each ``call_llm_json`` attempt.

    Attributes:
        original_prompt: The prompt without validation feedback; each
            attempt's prompt is this plus the latest feedback.
        spec: The model/token/schema fields of the call.
        cache: The cache tier a validated result is stored in.
    """

    original_prompt: str
    spec: _JsonCallSpec
    cache: LLMCache | NullCache

    def prompt_for(self, attempt: Attempt) -> str:
        """The prompt an attempt sends: the original plus any feedback."""
        return self.original_prompt + (attempt.feedback or "")

    def verdict(
        self, response_text: str, attempt: Attempt
    ) -> Accepted[dict[str, Any]] | Rejected:
        """Parses, repairs and validates one attempt's response.

        Does not raise on a validation or parse failure -- that is a
        rejection the loop retries with feedback. A caller's genuine call
        failure never reaches here.

        Args:
            response_text: The raw (fence-stripped) response text.
            attempt: Which attempt this is.

        Returns:
            The validated dict (already cached), or the reason it was not.
        """
        # Minor repairs are always tried, major ones (which indicate
        # truncation) only on the final attempt.
        parsed = _parse_or_repair_json(response_text, attempt.is_final)
        if parsed.result is None:
            return Rejected(
                parsed.parse_error
                or ValueError("All repair strategies failed"),
                response_text,
            )
        return self._validated(
            parsed.result, parsed.repaired, response_text, attempt
        )

    def _validated(
        self,
        result: dict[str, Any],
        repaired: bool,
        response_text: str,
        attempt: Attempt,
    ) -> Accepted[dict[str, Any]] | Rejected:
        """Validates a parsed result against the schema, caching it."""
        try:
            if self.spec.json_schema is not None:
                _backfill_and_validate(
                    result, self.spec.json_schema, self.spec.model_name
                )
        except ValidationError as e:
            return _validation_failure(e, response_text, attempt, repaired)
        self._cache_result(self.prompt_for(attempt), result)
        return Accepted(result)

    def _cache_result(self, prompt: str, result: dict[str, Any]) -> None:
        """Caches a schema-validated (or schema-less) attempt result.

        Keyed on the prompt this attempt actually sent.
        """
        self.cache.set(
            LLMCacheRequest(
                prompt=prompt,
                model_name=self.spec.model_name,
                temperature=self.spec.temperature,
                max_tokens=self.spec.max_tokens,
                json_schema=self.spec.json_schema,
            ),
            result,
        )
