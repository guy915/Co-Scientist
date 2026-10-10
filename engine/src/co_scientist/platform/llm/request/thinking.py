import contextlib
import logging
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any, Final

from co_scientist.core._context import _bind_contextvar
from co_scientist.core.constants import (
    MINIMAL_REASONING_MAX_TOKENS,
    THINKING_FLOOR_MAX_TOKENS,
)
from co_scientist.core.env_vars import parse_list_env
from co_scientist.platform.llm.profile import ModelProfile, Thinking, is_free_route, model_profile
from co_scientist.platform.llm.request.anthropic import haiku_thinking, output_limit
from co_scientist.platform.llm.roles import current_call_policy, role_reasons

logger = logging.getLogger(__name__)


# Prefer stable upstream order for cache locality; only the price cap bounds
# fallback spend.
_GATEWAY_PROVIDER: Final[dict[str, Any]] = {
    "require_parameters": True,
    "allow_fallbacks": True,
}

# OpenRouter deprioritizes low-throughput hosts rather than excluding them.
# At 25 tokens/second an 8k answer fits comfortably inside the 600-second
# ceiling.
_MIN_THROUGHPUT_TOKENS_PER_SEC: Final[int] = 25

# Allow floating-point headroom at headline rates while excluding higher-priced
# tiers.
# If capped routes disappear, update stale profile prices rather than widening
# the multiple.
_MAX_PRICE_MULTIPLE: Final[float] = 1.05


# Read per call so operators can retune locality without restarting.
_UPSTREAM_ORDER_ENV: Final[str] = "COSCIENTIST_GATEWAY_PROVIDER_ORDER"

# Prefer the first-party host among headline-priced endpoints; throughput here
# is unmeasured.
_DEFAULT_UPSTREAM_ORDER: Final[tuple[str, ...]] = (
    "z-ai",
    "deepinfra",
    "novita",
    "gmicloud",
)


def _upstream_order() -> tuple[str, ...]:
    """An explicit empty override opts out of upstream ordering."""
    return parse_list_env(_UPSTREAM_ORDER_ENV, _DEFAULT_UPSTREAM_ORDER)


# OpenRouter accepts at most three entries in its models fallback array.
_GATEWAY_MAX_FALLBACKS: Final[int] = 3


def _apply_provider_pin(provider: dict[str, Any], profile: ModelProfile) -> None:
    if profile.verified_provider:
        provider.pop("order", None)
        provider["only"] = [profile.verified_provider]
        provider["zdr"] = True
        provider["data_collection"] = "deny"


def _gateway_provider(model_name: str) -> dict[str, Any]:
    profile = model_profile(model_name)
    provider = dict(_GATEWAY_PROVIDER)
    provider["preferred_min_throughput"] = _MIN_THROUGHPUT_TOKENS_PER_SEC
    order = _upstream_order()
    if order:
        provider["order"] = list(order)
    _apply_provider_pin(provider, profile)
    price = profile.price
    if price is None:
        return provider
    provider["max_price"] = {
        "prompt": price.prompt_usd_per_million * _MAX_PRICE_MULTIPLE,
        "completion": (price.completion_usd_per_million * _MAX_PRICE_MULTIPLE),
    }
    if price.prompt_usd_per_million == price.completion_usd_per_million == 0:
        provider["max_price"]["request"] = 0.0
    return provider


# DeepSeek implements only high and max; high is its lowest reasoning tier.
_REASONING_EFFORT: Final[str] = "high"

# A low tier does not bound reasoning; use it only after an explicit cap is
# refused.
# A host rejecting low itself remains an unhandled provider failure.
_MINIMAL_REASONING_EFFORT: Final[str] = "low"

# Task-local recovery cannot leak into concurrent requests sharing the process.
_minimal_reasoning_forced: ContextVar[bool] = ContextVar("minimal_reasoning_forced", default=False)


@contextlib.contextmanager
def scoped_minimal_reasoning() -> Iterator[None]:
    with _bind_contextvar(_minimal_reasoning_forced, True):
        yield


def _minimal_reasoning_knob(recovering: bool) -> dict[str, Any]:
    """
    A tier name does not bound reasoning; prefer the cap, recover to the tier.
    The gateway defines cap and tier as alternatives; never send both.
    """
    if recovering:
        return {"enabled": True, "effort": _MINIMAL_REASONING_EFFORT}
    return {"enabled": True, "max_tokens": MINIMAL_REASONING_MAX_TOKENS}


def effective_thinking_enabled(model_name: str, enable_thinking: bool) -> bool:
    """Funding and diagnostics must reflect forced reasoning, not the
    requested disable.
    """
    if (enable_thinking and role_reasons()) or _minimal_reasoning_forced.get():
        return True
    profile = model_profile(model_name)
    if profile.thinking is Thinking.NONE:
        # No knob is sent, so a model that reasons by default keeps reasoning.
        return profile.reasons
    return profile.thinking is Thinking.GATEWAY and not profile.reasoning_can_disable


def deepseek_thinking_extra_body(model_name: str, *, enabled: bool = True) -> dict[str, Any]:
    """DeepSeek separates reasoning_content from content; JSON parsing still
    needs room for an answer.
    """
    lowered = model_name.lower()
    profile = model_profile(lowered)
    enabled = enabled and role_reasons()
    if profile.thinking is Thinking.NATIVE:
        return {"thinking": {"type": "enabled" if enabled else "disabled"}}
    if not profile.gateway:
        return {}
    return _gateway_body(lowered, profile, enabled)


# Free routes bill per request, not per token, so they reason at the most the
# gateway offers; it maps "max" down to each model's top tier. Chat keeps a
# middle tier so users are not left waiting, and paid routes keep the role's own
# effort because they bill per token.
_GATEWAY_MAX_EFFORT: Final[str] = "max"
_CONVERSATIONAL_ROLES: Final = frozenset(("chat", "interview"))


def _gateway_effort(lowered: str) -> str:
    policy = current_call_policy()
    if policy.role in _CONVERSATIONAL_ROLES:
        # Imported here: live evaluations configure the environment before config loads.
        from co_scientist.core.config import CONVERSATIONAL_REASONING_EFFORT

        return CONVERSATIONAL_REASONING_EFFORT
    if is_free_route(lowered):
        return _GATEWAY_MAX_EFFORT
    return policy.effort


def _gateway_body(lowered: str, profile: ModelProfile, enabled: bool) -> dict[str, Any]:
    body: dict[str, Any] = {"provider": _gateway_provider(lowered)}
    if profile.fallbacks:
        body["models"] = list(profile.fallbacks)
    if profile.thinking is not Thinking.GATEWAY:
        return body
    forced = _minimal_reasoning_forced.get()
    if not enabled and (not profile.reasoning_can_disable or forced):
        body["reasoning"] = _minimal_reasoning_knob(recovering=forced)
        return body
    reasoning: dict[str, Any] = {"enabled": enabled}
    if enabled:
        reasoning["effort"] = profile.pinned_effort or _gateway_effort(lowered)
    body["reasoning"] = reasoning
    return body


def model_reasons(model_name: str) -> bool:
    """Spending budget on reasoning differs from accepting a reasoning
    parameter (e.g. Ox Alpha).
    """
    return model_profile(model_name).reasons


def reasoning_effort_args(model_name: str, *, enabled: bool = True) -> dict[str, Any]:
    """DeepSeek high is its lowest tier; gateway routes already carry the
    tier and reject duplicates.
    """
    if enabled and role_reasons() and model_profile(model_name).thinking is Thinking.NATIVE:
        return {"reasoning_effort": _REASONING_EFFORT}
    return {}


def effective_max_tokens(model_name: str, max_tokens: int, enable_thinking: bool) -> int:
    """Funding and failure records must share the wire budget, including
    forced reasoning.
    """
    if model_name == "anthropic/claude-haiku-5-5":
        return min(max_tokens, output_limit())
    if not (effective_thinking_enabled(model_name, enable_thinking) and model_reasons(model_name)):
        return max_tokens
    return max(max_tokens, THINKING_FLOOR_MAX_TOKENS)


def _apply_thinking_args(
    completion_args: dict[str, Any], model_name: str, enable_thinking: bool
) -> None:
    """Centralize the reasoning floor so new callers cannot send answer-sized
    budgets.
    """
    profile = model_profile(model_name)
    if profile.supported_efforts is not None:
        effort = current_call_policy().azure_effort if enable_thinking else "none"
        completion_args["reasoning_effort"] = effort
        if effort != "none":
            completion_args["max_tokens"] = max(
                completion_args["max_tokens"], THINKING_FLOOR_MAX_TOKENS
            )
        return
    thinking = deepseek_thinking_extra_body(model_name, enabled=enable_thinking)
    if thinking:
        completion_args["extra_body"] = thinking
        completion_args.update(reasoning_effort_args(model_name, enabled=enable_thinking))

    completion_args["max_tokens"] = effective_max_tokens(
        model_name, completion_args["max_tokens"], enable_thinking
    )


def apply_provider_constraints(completion_args: dict[str, Any], model_name: str) -> None:
    """Every physical call passes here, so engine and app requests share the
    provider's wire rules.
    """
    profile = model_profile(model_name)
    if model_name == "anthropic/claude-haiku-5-5":
        # A thinking-off recovery would invalidate the shared cached prefix.
        completion_args.pop("reasoning_effort", None)
        extra = dict(completion_args.get("extra_body") or {})
        extra.pop("thinking", None)
        extra.pop("output_config", None)
        for field in ("temperature", "top_p", "top_k"):
            extra.pop(field, None)
            completion_args.pop(field, None)
        if extra:
            completion_args["extra_body"] = extra
        else:
            completion_args.pop("extra_body", None)
        # Bundled SDK metadata can lag a verified provider capability.
        completion_args["allowed_openai_params"] = list(
            dict.fromkeys([*completion_args.get("allowed_openai_params", []), "thinking"])
        )
        completion_args["thinking"] = haiku_thinking()
        completion_args["output_config"] = {"effort": "low"}
        completion_args["max_tokens"] = min(
            completion_args.pop("max_completion_tokens", completion_args.get("max_tokens", 0)),
            output_limit(),
        )
    if profile.fixed_sampling:
        completion_args.pop("temperature", None)
        completion_args.pop("top_p", None)
    if profile.max_completion_tokens and "max_tokens" in completion_args:
        completion_args["max_completion_tokens"] = completion_args.pop("max_tokens")
    if profile.responses_api and "/responses/" not in completion_args["model"]:
        # LiteLLM's Responses bridge keeps the chat-completion shape callers
        # parse, including tool calls.
        provider, _, name = str(completion_args["model"]).partition("/")
        completion_args["model"] = f"{provider}/responses/{name}"


_CONTEXT_ATTR: Final = "_co_scientist_failure_context"


def annotate_failure_context(
    error: Exception,
    model_name: str,
    max_tokens: int,
    enable_thinking: bool,
    call_site: str | None = None,
) -> None:
    """Carry the wire budget and item identity on the error; recomputation
    can disagree after escalation.
    """
    setattr(
        error,
        _CONTEXT_ATTR,
        (
            call_site,
            effective_max_tokens(model_name, max_tokens, enable_thinking),
            max_tokens,
        ),
    )


def failure_context_text(error: Exception) -> str:
    context = getattr(error, _CONTEXT_ATTR, None)
    if context is None:
        return ""
    call_site, sent, asked = context
    named = f"{call_site}, " if call_site else ""
    return f" ({named}max_tokens {sent}, call site asked for {asked})"


def deepseek_non_thinking_extra_body(model_name: str) -> dict[str, Any]:
    result: dict[str, Any] = deepseek_thinking_extra_body(model_name, enabled=False)
    return result


def deepseek_thinking_kwargs(model_name: str, *, effort: str | None = None) -> dict[str, Any]:
    extra_body = deepseek_thinking_extra_body(model_name, enabled=True)
    if not extra_body:
        return {}
    kwargs: dict[str, Any] = {
        "extra_body": extra_body,
        **reasoning_effort_args(model_name, enabled=True),
    }
    if effort is not None and not model_profile(model_name).pinned_effort:
        if "reasoning_effort" in kwargs:
            kwargs["reasoning_effort"] = effort
        reasoning = kwargs["extra_body"].get("reasoning")
        if isinstance(reasoning, dict) and "effort" in reasoning:
            reasoning["effort"] = effort
    return kwargs


def thinking_off_kwargs(model_name: str) -> dict[str, Any]:
    extra_body = deepseek_non_thinking_extra_body(model_name)
    return {"extra_body": extra_body} if extra_body else {}


def thinking_safe_max_tokens(model_name: str, answer_tokens: int) -> int:
    if model_name == "anthropic/claude-haiku-5-5":
        # Adaptive thinking spends this budget before the answer. Dispatch
        # clamps it to the role's output limit under the call's own policy.
        return max(answer_tokens, THINKING_FLOOR_MAX_TOKENS)
    result: int = effective_max_tokens(model_name, answer_tokens, True)
    return result


def thinking_safe_timeout(model_name: str, answer_seconds: float) -> float:
    """The conservative 75-token/s clock funds reasoning floors; streaming
    silence is bounded separately.
    """
    # Importing config reads settings; the gateway must stay importable before
    # an evaluation configures its environment.
    from co_scientist.core.config import THINKING_FLOOR_TIMEOUT_SECONDS

    if not model_reasons(model_name):
        return answer_seconds
    return max(answer_seconds, THINKING_FLOOR_TIMEOUT_SECONDS)
