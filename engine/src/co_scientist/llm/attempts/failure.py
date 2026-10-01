"""Naming and reporting a failed completion call.

The two names here belong together because they answer one question --
who writes a failure down, and under which name -- which is the
distinction that made a recovered call read as four separate production
errors.
"""

import logging

from co_scientist.exceptions import short_error_text
from co_scientist.llm.request.thinking import (
    annotate_failure_context,
    effective_max_tokens,
)
from co_scientist.llm.values import CompletionSpec, LLMCallOptions

# Deliberately named for the module this split out of, not for this one.
# The record is persisted and the Logs panel filters on the logger name,
# so "which file is this function in" is not something an operator should
# have to track. Splitting on size must not move a diagnostics surface.
logger = logging.getLogger("co_scientist.llm")


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
    logger.warning(
        "LLM call failed (model %s, max_tokens %s, call site asked for %s): %s",
        spec.model_name,
        effective_max_tokens(
            spec.model_name, spec.max_tokens, opt.enable_thinking
        ),
        spec.max_tokens,
        short_error_text(error),
    )
