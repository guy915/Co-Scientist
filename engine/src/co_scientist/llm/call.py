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
    """The retry loop owns caching/logging; every rung preserves the already-
    clamped temperature.
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
                return await _call_llm_single_attempt(prompt, attempt_spec, attempt_opt)
        return await _call_llm_single_attempt(prompt, attempt_spec, attempt_opt)

    return _attempt


async def call_llm(
    prompt: str,
    spec: CompletionSpec,
    options: LLMCallOptions | None = None,
    max_attempts: int = 3,
) -> str:
    """Three attempts cover ordinary budget rungs; JSON needs extra room for
    parse/schema correction.
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
        # Cache under the original request so calls needing escalation can hit
        # next time.
        cache.set(request, {"text": content})
        return content


async def _call_llm_for_json(prompt: str, spec: _JsonCallSpec, enable_thinking: bool = True) -> str:
    """Never nest another attempt loop or cache unvalidated raw text beside
    the validated JSON entry.
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
        # The retry boundary logs once with attempt number and terminality.
        raise ValueError(
            "LLM returned None or empty response. "
            "Check API keys, rate limits, and model availability."
        )

    return extract_response_json(response_text)


def _json_call_for_attempt(
    json_spec: _JsonCallSpec, enable_thinking: bool, judge: JsonJudge
) -> Callable[[Attempt], Awaitable[str]]:
    """Resolve the raw-response seam in this module so installed test fakes
    still intercept it.
    """

    async def _call_for_json(attempt: Attempt) -> str:
        escalation = attempt.rung
        attempt_prompt = judge.prompt_for(attempt)
        call_enable_thinking = enable_thinking and escalation is not BudgetEscalation.NO_THINKING
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


def _json_judge(judge: JsonJudge, max_attempts: int) -> Judge[str, dict[str, Any]]:

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
    opt = options if options is not None else LLMCallOptions()
    # Scope the explicit key over every attempt, without putting it in the
    # JSON/cache spec.
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
