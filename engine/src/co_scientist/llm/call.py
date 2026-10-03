"""The ``call_llm`` and ``call_llm_json`` entry points.

The raw one-attempt completion both are built on is ``llm.attempts.single``,
the loop that retries it -- the rungs, the waits, what is never retried --
is ``llm.attempts.retry.run_attempts``, and ``call_llm_with_tools`` lives in
``llm.tools.loop``. Each entry point here only says how to make one attempt
at a given rung (and, for JSON, how to judge the response); outside the
package, all three are imported from ``co_scientist.llm``.
"""

import dataclasses
import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

from co_scientist.cache import LLMCacheRequest
from co_scientist.llm.admission.free_policy import scoped_api_key
from co_scientist.llm.attempts.escalation import (
    BudgetEscalation,
    _JsonCallSpec,
    escalated_max_tokens,
    escalated_spec,
)
from co_scientist.llm.attempts.json_attempt import (
    JsonJudge,
    _call_llm_single_attempt,
)
from co_scientist.llm.attempts.retry import (
    Attempt,
    AttemptPlan,
    Judge,
    Rejected,
    run_attempts,
)
from co_scientist.llm.precall import _prepare_llm_call
from co_scientist.llm.request.thinking import scoped_minimal_reasoning
from co_scientist.llm.structured.validate import (
    _handle_json_retries_exhausted,
    extract_response_json,
)
from co_scientist.llm.values import CompletionSpec, LLMCallOptions

logger = logging.getLogger(__name__)


def _call_for_attempt(
    prompt: str, spec: CompletionSpec, opt: LLMCallOptions, temperature: float
) -> Callable[[Attempt], Awaitable[str]]:
    """Builds the attempt-maker ``call_llm`` hands the attempt loop.

    Mirrors ``_json_call_for_attempt``: caching and the outer failure log
    are off for every rung (the retry loop owns both -- a successful rung is
    cached once, by the caller, under the caller's own unescalated request;
    a failed one is logged once, by the loop), the top rung turns thinking
    off, and the recovery rung (a provider that rejected that disable as
    mandatory) resends with reasoning forced back on at minimal effort via
    ``scoped_minimal_reasoning`` rather than the literal rejected request.
    ``temperature`` is the already-clamped value from the caller's own
    cache lookup, so every rung sends the same one.

    Args:
        prompt: The prompt to send on every attempt.
        spec: The call spec as the caller sized it.
        opt: The caller's own options; only ``enable_thinking`` matters here.
        temperature: The clamped temperature to send on every attempt.

    Returns:
        A callable making one attempt at its rung.
    """
    inner_opt = LLMCallOptions(
        use_cache=False, enable_thinking=opt.enable_thinking, log_failures=False
    )

    async def _attempt(attempt: Attempt) -> str:
        escalation = attempt.rung
        attempt_spec = dataclasses.replace(
            spec,
            temperature=temperature,
            max_tokens=escalated_max_tokens(spec.max_tokens, escalation),
        )
        attempt_opt = inner_opt
        if escalation is BudgetEscalation.NO_THINKING:
            attempt_opt = dataclasses.replace(inner_opt, enable_thinking=False)
        if escalation is BudgetEscalation.MINIMAL_REASONING_REQUIRED:
            attempt_opt = dataclasses.replace(inner_opt, enable_thinking=False)
            with scoped_minimal_reasoning():
                return await _call_llm_single_attempt(
                    prompt, attempt_spec, attempt_opt
                )
        return await _call_llm_single_attempt(prompt, attempt_spec, attempt_opt)

    return _attempt


async def call_llm(
    prompt: str,
    spec: CompletionSpec,
    options: LLMCallOptions | None = None,
    max_attempts: int = 3,
) -> str:
    """Call an LLM via litellm and return the response.

    An answerless completion -- the whole budget spent reasoning
    (``LLMBudgetExhaustedError``), or reasoning that stopped normally and
    wrote nothing (``LLMThinkingOnlyError``) -- climbs the same
    budget-escalation ladder ``call_llm_json`` uses (see
    ``llm.attempts.escalation.BudgetEscalation``) instead of failing on the
    first attempt. A direct caller such as the literature-review synthesis
    step used to get exactly one attempt and no way to recover from either
    shape; see ``llm.attempts.retry.run_attempts`` for the loop, which also
    waits out a throttle or an outage and never retries a timeout.

    Args:
        prompt: The rendered prompt to send.
        spec: Which model to call and how to sample/shape the output.
        options: Cache, telemetry, and thinking behavior; defaults to
            ``LLMCallOptions()``.
        max_attempts: How many attempts the escalation ladder makes before
            giving up. 3, not ``call_llm_json``'s 5: the ladder has exactly
            three rungs that change the request -- the original call,
            ``RAISED_BUDGET``, then ``NO_THINKING`` (see
            ``llm.attempts.escalation.BudgetEscalation``) -- so three attempts
            walk it in full, and a fourth or fifth would only resend the
            identical ``NO_THINKING`` request, which the "a floor is not a
            guarantee" gotcha (root ``AGENTS.md``) calls the same doomed
            call billed again, not a retry. ``call_llm_json`` keeps 5
            because two of its failure kinds -- a schema failure and a
            parse failure -- hold their current rung and genuinely benefit
            from asking again (with validation feedback, or simply again);
            plain ``call_llm`` has neither failure kind, so nothing past
            the third attempt is answerable by trying again. Still an
            explicit parameter, so a caller that wants more attempts (for
            the ordinary-hiccup case a retry does recover) can ask for it.
    """
    opt = options if options is not None else LLMCallOptions()
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
        content = await run_attempts(
            _call_for_attempt(prompt, spec, opt, request.temperature),
            AttemptPlan(spec.model_name, max_attempts),
        )
        # Cached under the caller's own unescalated request, exactly as
        # call_llm_json caches under its spec's own max_tokens rather than
        # whatever rung finally answered -- otherwise a call that always
        # needs escalation would never populate the key its own next call
        # actually looks up under.
        cache.set(request, {"text": content})
        return content


async def _call_llm_for_json(
    prompt: str, spec: _JsonCallSpec, enable_thinking: bool = True
) -> str:
    """Makes the raw LLM call for one call_llm_json attempt.

    Caching is disabled on the inner call: call_llm_json keeps its own
    cache of the validated dict and returns from it before ever reaching
    this point, so a raw-text entry would only duplicate every cached
    payload on disk (and could replay an invalid response into the loop).
    Calls the single-attempt primitive directly (not the public
    ``call_llm``), so this raw call stays exactly one attempt -- the
    escalation loop and attempt count are ``call_llm_json``'s own, above
    this function, and must not also run inside it.

    Returns:
        The response text with any markdown code fences stripped.

    Raises:
        ValueError: If the LLM returns None or an empty response.
    """
    response_text = await _call_llm_single_attempt(
        prompt,
        CompletionSpec(
            model_name=spec.model_name,
            max_tokens=spec.max_tokens,
            temperature=spec.temperature,
            json_schema=spec.json_schema,
            force_json=not spec.json_schema,
        ),
        LLMCallOptions(
            use_cache=False,
            enable_thinking=enable_thinking,
            log_failures=False,
        ),
    )
    if not response_text:
        # Silent: the raise carries the whole message, and the retry loop
        # -- which knows the attempt number and whether it was terminal --
        # is the one layer that writes it down.
        raise ValueError(
            "LLM returned None or empty response. "
            "Check API keys, rate limits, and model availability."
        )

    # Extract JSON from markdown code blocks if present.
    return extract_response_json(response_text)


def _json_call_for_attempt(
    json_spec: _JsonCallSpec, enable_thinking: bool, judge: JsonJudge
) -> Callable[[Attempt], Awaitable[str]]:
    """Builds the attempt-maker ``call_llm_json`` hands the attempt loop.

    Defined here rather than in ``llm.attempts.retry`` so the inner call
    resolves ``_call_llm_for_json`` through this module's globals: that name
    is the raw-response seam tests install a fake at (see
    ``tests/test_supervisor_decision_schema.py``), and a closure living in
    another module would look it up somewhere the patch never reaches.

    Args:
        json_spec: The call spec as the calling node sized it.
        enable_thinking: Whether the caller asked for thinking at all; the
            top escalation rung turns it off regardless, and the recovery
            rung below that forces it back on at minimal effort.
        judge: The call's judge, which says what prompt an attempt sends:
            the original plus the validation feedback of the last rejected
            response.

    Returns:
        A callable making one attempt at its rung.
    """

    async def _call_for_json(attempt: Attempt) -> str:
        """Raw LLM call (via call_llm) for one attempt.

        ``attempt.rung`` is the loop's answer to a previous attempt that
        came back with no answer: it raises this attempt's token budget,
        at ``NO_THINKING`` turns thinking off, and at
        ``MINIMAL_REASONING_REQUIRED`` -- a provider that rejected that
        disable as mandatory -- resends with reasoning forced back on at
        the smallest tier the gateway exposes rather than the literal
        rejected request.
        """
        escalation = attempt.rung
        attempt_prompt = judge.prompt_for(attempt)
        call_enable_thinking = (
            enable_thinking and escalation is not BudgetEscalation.NO_THINKING
        )
        if escalation is BudgetEscalation.MINIMAL_REASONING_REQUIRED:
            with scoped_minimal_reasoning():
                return await _call_llm_for_json(
                    attempt_prompt,
                    escalated_spec(json_spec, escalation),
                    enable_thinking=False,
                )
        return await _call_llm_for_json(
            attempt_prompt,
            escalated_spec(json_spec, escalation),
            enable_thinking=call_enable_thinking,
        )

    return _call_for_json


def _json_judge(
    judge: JsonJudge, max_attempts: int
) -> Judge[str, dict[str, Any]]:
    """The attempt loop's judge for ``call_llm_json``.

    Args:
        judge: Judges one response: parse, repair, validate, cache.
        max_attempts: How many attempts the loop makes, for the error
            raised when every one of them was rejected.

    Returns:
        A judge whose exhaustion resolves to the schema's fallback data
        when it has one, and to the last validation or parse error when it
        does not.
    """

    def exhausted(last: Rejected) -> dict[str, Any]:
        return _handle_json_retries_exhausted(
            judge.spec.json_schema, last.error, last.response_text, max_attempts
        )

    return Judge(judge.verdict, exhausted)


async def call_llm_json(
    prompt: str,
    spec: CompletionSpec,
    max_attempts: int = 5,
    options: LLMCallOptions | None = None,
) -> dict[str, Any]:
    """Call LLM and parse JSON, with validation/retry logic.

    Args:
        prompt: The rendered prompt for the first attempt.
        spec: Which model to call and how to sample/shape the output;
            ``force_json`` is ignored because JSON is always parsed.
        max_attempts: How many attempts before giving up.
        options: Cache, telemetry, and thinking behavior; defaults to
            ``LLMCallOptions()``.
    """
    opt = options if options is not None else LLMCallOptions()
    # The explicit spec key (when any) scopes over the whole attempt loop,
    # so every attempt's inner call_llm resolves the same effective key
    # from the context without the credential entering _JsonCallSpec.
    with scoped_api_key(spec.api_key):
        request = LLMCacheRequest(
            prompt=prompt,
            model_name=spec.model_name,
            temperature=spec.temperature,
            max_tokens=spec.max_tokens,
            json_schema=spec.json_schema,
        )
        request, cache, cached_response = await _prepare_llm_call(request, opt)
        if cached_response is not None:
            logger.debug("using cached llm json response")
            return cached_response
        json_spec = _JsonCallSpec(
            spec.model_name,
            spec.max_tokens,
            request.temperature,
            spec.json_schema,
        )

        judge = JsonJudge(prompt, json_spec, cache)
        return await run_attempts(
            _json_call_for_attempt(json_spec, opt.enable_thinking, judge),
            AttemptPlan(json_spec.model_name, max_attempts),
            _json_judge(judge, max_attempts),
        )
