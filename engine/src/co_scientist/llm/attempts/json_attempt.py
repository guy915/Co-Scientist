"""Single LLM requests and the schema-constrained response judge."""

import json
import logging
from dataclasses import dataclass
from typing import Any, cast

from jsonschema.exceptions import ValidationError

from co_scientist.cache import LLMCache, LLMCacheRequest, NullCache
from co_scientist.exceptions import short_error_text
from co_scientist.llm.admission.free_policy import (
    current_api_key,
    scoped_api_key,
)
from co_scientist.llm.attempts.escalation import _JsonCallSpec
from co_scientist.llm.attempts.retry import Accepted, Attempt, Rejected
from co_scientist.llm.precall import _prepare_llm_call
from co_scientist.llm.request.completion import (
    CompletionShape,
    _acompletion_within_timeout,
    _apply_api_key,
    _build_completion_args,
    _supports_json_schema_response_format,
)
from co_scientist.llm.request.response import _extract_completion_content
from co_scientist.llm.request.thinking import (
    annotate_failure_context,
    effective_max_tokens,
)
from co_scientist.llm.structured.validate import (
    _validation_feedback,
    attempt_json_repair,
    reshape_json_output,
    validate_json_schema,
)
from co_scientist.llm.values import CompletionSpec, LLMCallOptions

logger = logging.getLogger(__name__)


# Keep the persisted failure logger stable for the Logs panel filter.
_failure_logger = logging.getLogger("co_scientist.llm")


def _failure_call_site(spec: CompletionSpec, opt: LLMCallOptions) -> str | None:
    """Names the call for a failure record, as specifically as it can.

    ``prompt_name`` is the better label where a node sets one -- it is
    already per-hypothesis or per-matchup, so it distinguishes items within
    a fan-out wave. The schema name is the fallback because every
    structured call has one, and it still identifies the prompt family,
    which is what separates the ten call sites sharing a budget constant.

    Args:
        spec: The spec the failed call was made with.
        opt: The options it was made with.

    Returns:
        A short label, or ``None`` for an unnamed free-text call.
    """
    if opt.prompt_name:
        return opt.prompt_name
    schema_name = (spec.json_schema or {}).get("name")
    return schema_name if isinstance(schema_name, str) else None


def _report_call_llm_failure(
    spec: CompletionSpec,
    opt: LLMCallOptions,
    error: Exception,
) -> None:
    """Annotates a failed call's context, and logs it if nobody above will.

    The annotation is unconditional: it records which call failed and the
    budget the request actually carried, so whichever layer ends up writing
    the record reports what went out. The thinking floor raises the budget
    before the request leaves, and printing the pre-floor number beside a
    reasoning-token count that exceeds it made a budget failure read as a
    provider one.

    The log is conditional (``opt.log_failures``), because the raw call this
    guards is not the layer that knows whether a retry follows. Both
    ``call_llm_json`` and ``call_llm`` run this raw call once per attempt
    under the one attempt loop (``llm.attempts.retry``), which says
    everything this warning would, plus the attempt number and whether the
    ladder gave up -- so both turn this off and log once per attempt in
    that loop (``llm.attempts.retry._log_failure``)
    instead of once here per raw call on top of that. As a result nothing
    in this codebase sets ``log_failures=True`` today, and the warning here
    fires only for a caller of the raw single-attempt primitive
    (``llm.attempts.single._call_llm_single_attempt``) that opts back into it
    directly.

    Warning, not error, for the same reason: a single recovered answerless
    completion put four ERROR rows in the diagnostics panel, and eight of
    one export's ten errors were this.

    Args:
        spec: The spec the failed call was made with.
        opt: The options it was made with; carries the thinking flag that
            decides the floor, and whether to log here at all.
        error: The failure being reported.
    """
    annotate_failure_context(
        error,
        spec.model_name,
        spec.max_tokens,
        opt.enable_thinking,
        _failure_call_site(spec, opt),
    )
    if not opt.log_failures:
        return
    _failure_logger.warning(
        "LLM call failed (model %s, max_tokens %s, call site asked for %s): %s",
        spec.model_name,
        effective_max_tokens(
            spec.model_name, spec.max_tokens, opt.enable_thinking
        ),
        spec.max_tokens,
        short_error_text(error),
    )


async def _call_llm_and_cache(
    request: LLMCacheRequest,
    enable_thinking: bool,
    cache: "LLMCache | NullCache",
) -> str:
    """Runs the actual completion call for one attempt and caches it.

    ``request.temperature`` is assumed already clamped.

    The credential is read from ``llm.admission.credentials.current_api_key`` at
    call time rather than passed in: ``request`` is deliberately
    credential-free (it is the cache key), and the caller already scoped
    the effective key -- an explicit ``CompletionSpec.api_key`` or the
    run's scoped key -- into the current task's context.

    Args:
        request: The request to send, and the key its response is cached
            under.
        enable_thinking: Whether DeepSeek thinking mode is requested.
        cache: The cache tier resolved for this call.

    Returns:
        The non-empty response content, having cached it (only reached once
        content is valid).
    """
    completion_args = _build_completion_args(
        request.prompt,
        request.model_name,
        request.max_tokens,
        request.temperature,
        CompletionShape(
            force_json=bool(request.force_json),
            json_schema=request.json_schema,
            enable_thinking=enable_thinking,
        ),
    )
    _apply_api_key(completion_args, current_api_key())
    response = await _acompletion_within_timeout(
        completion_args, request.model_name
    )
    content = _extract_completion_content(response, request.model_name)
    cache.set(request, {"text": content})
    return content


async def _call_llm_single_attempt(
    prompt: str,
    spec: CompletionSpec,
    opt: LLMCallOptions,
) -> str:
    """Makes exactly one completion attempt: no retry, no escalation.

    Args:
        prompt: The rendered prompt to send.
        spec: Which model to call and how to sample/shape the output.
        opt: Cache, telemetry, and thinking behavior for this one attempt.

    Returns:
        The non-empty response content.
    """
    # An explicit spec key temporarily overrides any run-scoped key for
    # exactly this call; the completion args read the effective key back
    # from the context (see _call_llm_and_cache).
    with scoped_api_key(spec.api_key):
        request = LLMCacheRequest(
            prompt=prompt,
            model_name=spec.model_name,
            temperature=spec.temperature,
            max_tokens=spec.max_tokens,
            json_schema=spec.json_schema,
            force_json=spec.force_json,
        )
        request, cache, cached_response = await _prepare_llm_call(request, opt)
        if cached_response is not None:
            logger.debug("using cached llm response")
            return cast(str, cached_response["text"])
        # Never falls back/retries itself; nothing cached on failure.
        try:
            return await _call_llm_and_cache(
                request, opt.enable_thinking, cache
            )
        except Exception as e:
            _report_call_llm_failure(spec, opt, e)
            raise


# Bound here at import on purpose, so the shim below reads the default
# backend's answer, never an installed backend's: the request format asks the
# installed backend at call time (``llm.request.schema``) and this does not.


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
        reshape_json_output(result, schema)
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
