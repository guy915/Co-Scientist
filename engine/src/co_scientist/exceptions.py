"""Domain-specific exception hierarchy for the co-scientist engine.

All errors raised by engine code inherit from ``CoScientistError`` so callers
can catch the entire family with a single ``except`` clause while still being
able to distinguish individual failure modes.
"""


# Flat hierarchy by design: each subclass below sits directly under this
# base rather than under one another, since they represent independent
# failure domains (config, generation, response parsing) rather than a
# taxonomy of one error specializing another.
class CoScientistError(Exception):
    """Base class for all errors raised by the co-scientist engine."""


# Raised by ToolRegistry and the MCP tool provider (config/registry.py,
# tools/provider.py) when tool configuration is missing or not initialized.
class ConfigError(CoScientistError):
    """The tool registry or configuration is not initialized or invalid."""


# Raised by the debate and review nodes (agents/generation/debate.py,
# agents/reflection/review.py) once retries are exhausted without usable
# output.
class GenerationError(CoScientistError):
    """Hypothesis generation or debate failed to produce a result."""


# Raised by the literature-tools draft/validate helpers when an LLM response
# cannot be coerced into the expected structured JSON after repair attempts.
class ResponseParseError(CoScientistError):
    """An LLM response could not be parsed or repaired into expected JSON."""


# Raised by call_llm when a provider accepts a request and then never
# answers. Distinct from a generic call failure because it is deliberately
# not retried: both retry loops built on the escalation ladder re-raise it
# immediately (see llm_json_retry._run_json_attempt and its plain-text
# counterpart llm_text_retry._run_text_attempt), since a provider that has
# stopped responding will not answer a second identical request any sooner,
# and retrying multiplies one stalled call by the attempt count.
class LLMTimeoutError(CoScientistError):
    """An LLM call exceeded its wall-clock budget without responding."""


# Raised by call_llm when a completion comes back empty because the whole
# max_tokens allowance went on the chain of thought (finish_reason="length"
# with no content). Distinct from a generic empty response because the
# answer is deterministic rather than incidental: the same request repeated
# at the same budget reasons its way into the same wall, so the retry loop
# answers it by changing the budget instead (see
# llm_json_retry.BudgetEscalation, shared by call_llm_json and call_llm's
# own escalation loop in llm_text_retry alike).
#
# Also a ValueError: an empty completion has raised one from
# _extract_completion_content since before this subclass existed, and
# callers were written against that contract.
class LLMBudgetExhaustedError(CoScientistError, ValueError):
    """An LLM spent its whole token budget reasoning and answered nothing."""


# Raised when a completion ends normally (finish_reason is neither "length"
# nor "error" -- the latter is OpenRouter reporting a mid-stream provider
# failure, not the model's own choice, and is a plain retryable failure
# instead; see llm_response._empty_content_error) having produced reasoning
# tokens and no answer tokens at all -- the model thought, decided it was
# finished, and wrote nothing. Distinct from budget exhaustion because a
# bigger allowance is not the remedy: production saw a call reason for 1149
# tokens against an 18000 budget and return empty, then do the same on
# attempts 2 and 3, so a plain retry is not the remedy either. The retry
# loop answers it by turning thinking off (see llm_json_retry.BudgetEscalation
# and llm_text_retry, which both climb this same ladder).
#
# Also a ValueError, for the same reason LLMBudgetExhaustedError is.
class LLMThinkingOnlyError(CoScientistError, ValueError):
    """An LLM finished its chain of thought and wrote no answer at all."""


# Raised by llm_call_budget.record_provider_request once a run's counted
# provider requests exceed its configured max_llm_calls ceiling (see
# app.run_modes.RUN_TIER_DEFAULTS and
# co_scientist.scheduling.policy_checks._llm_call_budget_check, which
# terminates a run between tasks from the same count). That check only
# runs between the supervisor's scheduling decisions, so a task that fires
# hundreds of calls inside one node was never interrupted by it; this is
# the enforcement point *inside* a task, at the seam every provider
# request passes through. Deliberately not a ValueError: everything
# reaching the worker boundary as a bare ValueError is treated as a
# transient provider hiccup and keeps its retry budget (see
# UnsupportedTaskError's docstring), and retrying a run that has already
# overspent its ceiling would only keep spending against it. Both retry
# loops built on the escalation ladder re-raise it immediately, exactly as
# they do LLMTimeoutError, since the run is already over its ceiling and
# another attempt would only add to the overrun.
class LLMCallBudgetExceededError(CoScientistError):
    """A run's LLM-call ceiling was exceeded; the run must abort, not retry."""

    def __init__(self, count: int, ceiling: int) -> None:
        """Records the overrun so callers and log lines can report it.

        Args:
            count: The provider requests counted for the run, including
                the one that pushed it past ``ceiling``.
            ceiling: The run's configured ``max_llm_calls``.
        """
        self.count = count
        self.ceiling = ceiling
        super().__init__(
            f"LLM-call ceiling exceeded: {count} provider requests against "
            f"a budget of {ceiling}; aborting the run"
        )


# Raised by the retry loops (llm_json_retry/llm_text_retry, which share this
# classification) when a 429 carries evidence of a platform-wide cap --
# OpenRouter's free-model per-minute/per-day ceiling, not the ordinary
# transient upstream-provider throttle the jittered backoff already
# absorbs -- whose reset is too far away for that backoff to wait out. A
# cap that resets in minutes or hours cannot be answered inside one call's
# five-attempt, roughly-one-minute retry budget; spending it anyway only
# fails the task and burns the durable retry budget along with it. Callers
# that can park a unit of work until ``resume_at`` (a durable task queue,
# in particular) should catch this instead of treating it as an ordinary
# transient failure; a caller with nothing to park should let it fail.
# Deliberately not a ValueError, for the same reason
# LLMCallBudgetExceededError is not: a bare ValueError reaching the worker
# boundary is treated as a transient hiccup with its retry budget intact,
# and retrying against a cap that has not reset yet would only spend that
# budget for nothing.
class LLMRateLimitParkError(CoScientistError):
    """A platform-wide rate-limit cap should park the task, not retry it."""

    def __init__(self, resume_at: float, reason: str) -> None:
        """Records when the cap resets and why this was classified as one.

        Args:
            resume_at: Epoch seconds when the platform cap is expected to
                reset -- from a response header when one was usable,
                otherwise a conservative default (see
                ``llm_json_retry._platform_rate_limit_park``).
            reason: Short machine-readable tag for what was matched (e.g.
                ``"x_ratelimit_reset_header"``, ``"message_per_day"``),
                carried through to the parked task's attempt history.
        """
        self.resume_at = resume_at
        self.reason = reason
        super().__init__(
            f"platform rate limit hit ({reason}); resume at "
            f"{resume_at:.0f} (epoch seconds)"
        )


# Raised when an MCP tool accepts a call and never returns. The LLM timeout
# covers litellm.acompletion only, which left tool invocations unbounded: a
# server whose stream broke mid-call parked the awaiting run forever, with no
# error, no retry and nothing in the log after the request went out. Callers
# that can degrade (per-source literature search, the availability probe)
# catch this and carry on without that source.
class MCPToolTimeoutError(CoScientistError):
    """An MCP tool call exceeded its wall-clock budget without responding."""


# The longest a provider error may be when it reaches a log line. Not a
# style preference: litellm reports a DeepSeek json-mode parse failure by
# appending the entire completion to the message ("Unable to get json
# response - Unterminated string ... Original Response: {8KB}"), and the
# wrappers log the same exception twice -- once where the call failed and
# once in the retry loop. Whole, that is multiple kilobytes per occurrence
# into a store whose single writer this codebase has already had starved by
# log volume, and it buries the clause that says what actually went wrong.
_MAX_LOGGED_ERROR_CHARS = 400


def short_error_text(error: BaseException) -> str:
    """Render an exception for a log line, bounded in length.

    The head is kept rather than the tail: a provider error states the
    failure first and echoes the payload afterwards, so the first few
    hundred characters are the diagnosis and the rest is the evidence that
    already reached the caller as the exception itself.

    Args:
        error: The exception to render.

    Returns:
        The exception's text, truncated with a count of what was dropped.
    """
    text = str(error).strip()
    dropped = len(text) - _MAX_LOGGED_ERROR_CHARS
    if dropped <= 0:
        return text
    return f"{text[:_MAX_LOGGED_ERROR_CHARS]}... (+{dropped} more chars)"
