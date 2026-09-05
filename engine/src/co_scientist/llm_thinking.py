"""Thinking/reasoning-mode argument shaping for LiteLLM completion calls.

Split from ``co_scientist.llm_request``: selects the thinking knob
(DeepSeek's native ``thinking`` object), the reasoning tier, and the
``max_tokens`` floor a thinking call needs. Every name here is re-exported
from ``co_scientist.llm_request`` so that module's namespace is unchanged.
"""

import logging
from dataclasses import dataclass
from typing import Any, Final

from co_scientist.config.env_vars import parse_list_env
from co_scientist.constants import THINKING_FLOOR_MAX_TOKENS
from co_scientist.constants_pricing import MODEL_PRICING

logger = logging.getLogger(__name__)

# Provider-capability shim: some providers reject
# response_format={"type": "json_schema", ...} outright (DeepSeek returns an
# invalid-request error). For those models every schema'd call is downgraded,
# per call, to {"type": "json_object"} with the schema restated as prompt
# text, and missing required fields are back-filled with empty defaults
# (json_object mode has no server-side schema enforcement, so nested
# required fields are routinely omitted). Models that support json_schema
# are untouched.
#
# Checked BEFORE litellm's capability registry: it marks deepseek/* as
# supporting response schema, but the DeepSeek API only accepts json_object.
#
# ``ox-alpha`` is here for a harder reason: no host serving it accepts
# ``json_schema`` at all, and paired with ``require_parameters`` below
# that is not a soft degradation -- the gateway finds no eligible host
# and fails outright ("No endpoints found that can handle the requested
# parameters"). Measured live: ``json_object`` plus that constraint
# answers, ``json_schema`` plus it 404s.
_JSON_OBJECT_ONLY_MODEL_FAMILIES: tuple[str, ...] = ("deepseek",)

# Routes that normalize reasoning control into their own parameter rather
# than forwarding the provider's. A gateway serves many models through one
# schema, so it cannot honour each provider's native knob, and the failure
# is silent in the worst direction: sending DeepSeek's ``thinking`` object
# through OpenRouter does not disable thinking, it *enables* it. Measured
# on `openrouter/deepseek/deepseek-v4-flash`: a max_tokens=24 call carrying
# ``{"thinking": {"type": "disabled"}}` spent all 24 tokens reasoning and
# returned empty content -- the budget-exhaustion shape AGENTS.md
# documents, from a parameter asking for the opposite.
_REASONING_PARAM_ROUTES: tuple[str, ...] = ("openrouter/",)

# The tier requested when thinking is on. DeepSeek implements only `high`
# and `max`, so this is the floor rather than a high setting.
_REASONING_EFFORT: Final[str] = "high"


# How far above a model's listed rate a routed call may land. A gateway
# spreads one model across hosts an order of magnitude apart in price and
# speed -- seventeen for `deepseek-v4-flash`, $0.068 to $0.44 per million
# input tokens -- so without a ceiling a call can be billed at five times
# what ``constants_pricing`` estimates.
#
# Two is deliberately loose: it keeps thirteen of the seventeen hosts
# eligible (losing one is not an outage) while excluding the tail costing
# 2.7x-8x listed rate. Tight enough to force the single cheapest host
# would make every price move a hard 404 on every call.
_MAX_PRICE_MULTIPLE: Final[float] = 2.0


# How a gateway route is addressed, beyond the reasoning knob itself.
# ``require_parameters`` makes the reasoning knob above binding instead
# of advisory, by restricting routing to hosts that accept it.
#
# This used to also carry ``"sort": "throughput"`` -- measured over six
# concurrent calls on `openrouter/deepseek/deepseek-v4-flash`: the
# slowest took 32.9s unconstrained against a 2.3s median, 7.1s
# constrained. But throughput-sort repicks the fastest upstream *per
# call*, scattering consecutive calls across Modal/Friendli/Together --
# very likely why production's prompt-cache hit rate collapsed to 6.9%
# (33.7% monthly baseline) on 2026-09-04, the heaviest repeated-prompt
# day (~1,000 requests, ~28k-token prompts, $4.70): a prefix cached on
# one upstream is wasted the instant the next call lands elsewhere -- at
# that length and repeat rate, locality beats chasing the fastest host
# of the instant.
#
# ``order`` (added per call below) replaces ``sort``: a preference list
# OpenRouter tries in sequence, falling to its own default (price-
# weighted) selection only once every listed upstream is unavailable,
# per https://openrouter.ai/docs/features/provider-routing. Either field
# disables OpenRouter's own load balancing and the docs do not say which
# wins if both are sent, so only ``order`` is sent.
#
# Losing ``sort`` reopens what it closed -- an upstream up but slow,
# which ``allow_fallbacks`` doesn't catch. ``_MIN_THROUGHPUT_TOKENS_PER_SEC``
# below is the replacement floor.
_GATEWAY_PROVIDER: Final[dict[str, Any]] = {
    "require_parameters": True,
    "allow_fallbacks": True,
}

# Soft throughput floor replacing what ``sort: throughput`` protected,
# without its per-call repicking. OpenRouter documents this as
# *deprioritization* -- "moved to the end of the list, not excluded" --
# so an undocumented interaction with ``order`` is at worst a no-op (25
# tok/s sits below every upstream's measured median, lowest Together at
# 42.65, see ``_DEFAULT_UPSTREAM_ORDER``) and overrides ``order`` only
# when the ordered host is already the problem.
#
# 25 is sized off the incident, not the medians: at the 600s call
# ceiling, an 8k-token reply (the large-output tier below) clears in
# 320s at 25 tok/s -- comfortable margin -- while the incident's "single
# digit tokens per second" still trips it. Applies to p50 (OpenRouter's
# rolling per-endpoint stat, not this request), so it flags a
# persistently degraded host, not one slow response.
_MIN_THROUGHPUT_TOKENS_PER_SEC: Final[int] = 25

# Env var that overrides the preferred upstream order without a deploy.
# Read per call (see ``parse_list_env``), not cached at import, for the
# same reason ``parse_timeout_env`` is: an operator retuning this after a
# cache-locality regression should not need to restart the process.
_UPSTREAM_ORDER_ENV: Final[str] = "COSCIENTIST_GATEWAY_PROVIDER_ORDER"

# Derived from OpenRouter's per-request log for `z-ai/glm-5.3-flash` on
# 2026-09-04 (slugs verified against
# https://openrouter.ai/api/v1/providers). Median tok/s / TTFT: Modal
# 62.5/0.96s (n=8), Friendli 121.2/6.0s (n=2), Together 42.7/5.25s
# (n=10). Rough latency (TTFT + out/throughput) by shape: small output
# (~250 tok, most calls) Modal 5.0s / Friendli 8.1s / Together 11.1s;
# large output (~7.5k tok, a minority) Modal 121s / Friendli 68s /
# Together 181s. Modal wins the majority shape and Together loses both,
# so Together is last regardless of the split. Friendli only overtakes
# Modal on a call-weighted average once large-output calls exceed ~5.5%
# of traffic (break-even 5.0+115.95p == 8.06+59.84p); with n=2 it is
# also too thin a sample to hand nearly all traffic to on a mechanism
# that only falls through when a host is down. Re-derive if that
# fraction is ever measured above ~5.5%; until then, Modal first.
_DEFAULT_UPSTREAM_ORDER: Final[tuple[str, ...]] = (
    "modal",
    "friendli",
    "together",
)


def _upstream_order() -> tuple[str, ...]:
    """The preferred upstream order for a gateway call, env-overridable.

    Returns:
        ``COSCIENTIST_GATEWAY_PROVIDER_ORDER`` parsed as a comma-separated
        list when set, ``_DEFAULT_UPSTREAM_ORDER`` when unset, or an
        empty tuple for an explicit empty-string value -- a deliberate
        opt-out that makes ``_gateway_provider`` omit ``order`` entirely.
    """
    return parse_list_env(_UPSTREAM_ORDER_ENV, _DEFAULT_UPSTREAM_ORDER)


@dataclass(frozen=True)
class GatewayModel:
    """What a gateway route needs to know about one model.

    Every fact here is a property of the model, stated rather than
    inferred from a family substring -- inferring them is what made a
    rival vendor's model run with no reasoning knob and no price ceiling
    while looking configured.

    Attributes:
        takes_reasoning_knob: Whether to send the gateway's ``reasoning``
            parameter; a model that rejects it gains nothing from asking.
        spends_budget_thinking: Whether the model can consume its whole
            ``max_tokens`` before answering, needing
            ``THINKING_FLOOR_MAX_TOKENS``. Separate from the knob above:
            a model reporting ``reasoning_tokens=0`` and no reasoning
            parameter still returned ``finish_reason="length"`` with
            empty content at an 8000-token budget in production, costing
            24 answerless round-trips in one express run. When unsure,
            fund it: a ceiling is not a spend.
        fallbacks: Gateway-relative ids to try, in order, when unavailable.
            The gateway walks the list itself: a 429 from a saturated
            pool is not a transport error the engine's retry ladder fixes.
    """

    takes_reasoning_knob: bool
    spends_budget_thinking: bool
    fallbacks: tuple[str, ...] = ()


# The models this deployment reaches through the gateway, and the order it
# falls through them.
#
# **A fallback may only ever be cheaper than the model above it.** Wired the
# other way once -- free primary, paid last resort -- a "last resort" priced
# at $1.25/$4.25 served 3.17M tokens and billed $5.23 in an afternoon,
# because 429 is the *normal* state of a shared free pool, so the expensive
# rung was the routine destination rather than the emergency one. The guard
# against it already existed -- ``_gateway_provider`` caps a routed call at
# ``_MAX_PRICE_MULTIPLE`` times the primary's listed rate -- but a primary
# priced at zero has no meaningful multiple, so the cap was skipped and the
# request could be served at any price the gateway liked. A *priced*
# primary arms the ceiling; free rungs below it are safe for the same
# reason they were dangerous above it.
_GATEWAY_MODELS: Final[dict[str, GatewayModel]] = {
    "openrouter/z-ai/glm-5.3-flash": GatewayModel(
        takes_reasoning_knob=True,
        spends_budget_thinking=True,
        fallbacks=(
            "minimax/minimax-m3:free",
            "nvidia/nemotron-3.5-lightning:free",
        ),
    ),
    "openrouter/minimax/minimax-m3:free": GatewayModel(
        takes_reasoning_knob=True, spends_budget_thinking=True
    ),
    "openrouter/nvidia/nemotron-3.5-lightning:free": GatewayModel(
        takes_reasoning_knob=True, spends_budget_thinking=True
    ),
    "openrouter/z-ai/glm-5.2:free": GatewayModel(
        takes_reasoning_knob=True, spends_budget_thinking=True
    ),
}


def _is_gateway_route(model_name: str) -> bool:
    """Whether this route is served through a model gateway."""
    lowered = model_name.lower()
    return any(lowered.startswith(r) for r in _REASONING_PARAM_ROUTES)


def _gateway_provider(model_name: str) -> dict[str, Any]:
    """Return the routing block for a gateway call, price-capped.

    Args:
        model_name: Model name in litellm format, already lowercased.

    Returns:
        ``_GATEWAY_PROVIDER`` plus ``preferred_min_throughput``, the
        preferred upstream ``order`` (unless env-disabled), and a
        ``max_price`` ceiling from the model's listed rate -- omitted for
        a model absent from ``MODEL_PRICING``, which has no rate to cap.
    """
    provider = dict(_GATEWAY_PROVIDER)
    provider["preferred_min_throughput"] = _MIN_THROUGHPUT_TOKENS_PER_SEC
    order = _upstream_order()
    if order:
        provider["order"] = list(order)
    price = MODEL_PRICING.get(model_name)
    if price is None or not price.prompt_usd_per_million:
        return provider
    provider["max_price"] = {
        "prompt": price.prompt_usd_per_million * _MAX_PRICE_MULTIPLE,
        "completion": (price.completion_usd_per_million * _MAX_PRICE_MULTIPLE),
    }
    return provider


def deepseek_thinking_extra_body(
    model_name: str, *, enabled: bool = True
) -> dict[str, Any]:
    """Return an ``extra_body`` selecting DeepSeek V4 thinking mode.

    DeepSeek V4 (pro/flash) are reasoning models: the chain of thought
    returns separately as ``reasoning_content``, never mixed into
    ``content``, so JSON parsing is unaffected as long as ``max_tokens``
    leaves room for the answer after the reasoning spend -- which
    ``_apply_thinking_args`` ensures by raising any thinking call to
    ``THINKING_FLOOR_MAX_TOKENS``. Non-DeepSeek models get an empty dict.

    Thinking is on for every node. ``enabled=False`` remains the seam for
    opting a call site out; nothing uses it today. A future opt-out would
    pay off on the ranking tournament's pairwise matchups (O(n^2) per
    cycle, ``ranking_debate.py``) and supervisor allocation, alone on the
    run's serial spine (``supervisor_decision.py``).

    Args:
        model_name: Model name in litellm format.
        enabled: Whether to request thinking mode; distinct from omitting
            the field, since the API's own default is enabled.

    Returns:
        The ``extra_body`` this model's route needs: DeepSeek's native
        ``thinking`` object direct, or a gateway's ``reasoning`` object
        plus the routing constraint that makes it binding. Empty for a
        model with no thinking mode.
    """
    lowered = model_name.lower()
    declared = _GATEWAY_MODELS.get(lowered)
    if declared is not None:
        return _declared_gateway_body(lowered, declared, enabled)
    if "deepseek" not in lowered:
        return {}
    if not _is_gateway_route(lowered):
        return {"thinking": {"type": "enabled" if enabled else "disabled"}}
    reasoning: dict[str, Any] = {"enabled": enabled}
    if enabled:
        reasoning["effort"] = _REASONING_EFFORT
    return {"reasoning": reasoning, "provider": _gateway_provider(lowered)}


def _declared_gateway_body(
    lowered: str, declared: GatewayModel, enabled: bool
) -> dict[str, Any]:
    """Build the ``extra_body`` for a model declared in ``_GATEWAY_MODELS``.

    Args:
        lowered: Model name in litellm format, already lowercased.
        declared: What the gateway needs to know about this model.
        enabled: Whether thinking mode is requested for this call.

    Returns:
        The routing constraint always, the fallback chain when one is
        declared, and the reasoning knob only for a model that reasons.
    """
    body: dict[str, Any] = {"provider": _gateway_provider(lowered)}
    if declared.fallbacks:
        body["models"] = list(declared.fallbacks)
    if not declared.takes_reasoning_knob:
        return body
    reasoning: dict[str, Any] = {"enabled": enabled}
    if enabled:
        reasoning["effort"] = _REASONING_EFFORT
    body["reasoning"] = reasoning
    return body


def model_reasons(model_name: str) -> bool:
    """Whether this model can spend its whole budget before answering.

    The question the token floor actually asks, and deliberately not "does
    it take the reasoning parameter". The two came apart in production: Ox
    Alpha answers no to the second and yes to this one, and conflating them
    withheld the floor from a model that needed it, costing 24 answerless
    round-trips in one express run.

    Args:
        model_name: Model name in litellm format.

    Returns:
        True for a declared gateway model that spends its budget thinking,
        and for any DeepSeek model, whose whole family does.
    """
    lowered = model_name.lower()
    declared = _GATEWAY_MODELS.get(lowered)
    if declared is not None:
        return declared.spends_budget_thinking
    return "deepseek" in lowered


def reasoning_effort_args(
    model_name: str, *, enabled: bool = True
) -> dict[str, Any]:
    """Kwargs selecting the reasoning tier, when supported.

    ``high`` is the floor, not a high setting: DeepSeek implements only
    ``high`` and ``max`` and aliases OpenAI's lower names onto ``high``,
    so there is no cheaper way to think than this (the rung below is
    ``enabled=False``). Also DeepSeek's default once thinking is on, so
    this field is belt-and-braces against litellm 1.80.x stripping
    ``reasoning_effort`` outright (BerriAI/litellm#27439) -- inert today
    since the value equals the default, correct once the fix lands.

    **Direct routes only.** A gateway route already carries the tier
    inside the ``reasoning`` object ``deepseek_thinking_extra_body``
    builds for it; sending it again is the same instruction twice, and
    the gateway rejects the copy (litellm raises
    ``UnsupportedParamsError`` for a model whose OpenRouter support map
    omits the parameter). Engine calls pass ``drop_params`` and never
    saw it; the app's direct litellm call sites do not, and the
    redundant field there failed the contextual safety screen outright
    rather than erroring visibly.

    Empty for models without a thinking mode, for gateway routes, and when
    thinking is disabled for the call.

    Args:
        model_name: Model name in litellm format.
        enabled: Whether thinking mode is requested for this call.

    Returns:
        ``{"reasoning_effort": "high"}`` when the tier applies and the route
        has nowhere else to state it, else ``{}``.
    """
    if _is_gateway_route(model_name):
        return {}
    if enabled and deepseek_thinking_extra_body(model_name):
        return {"reasoning_effort": "high"}
    return {}


def effective_max_tokens(
    model_name: str, max_tokens: int, enable_thinking: bool
) -> int:
    """The ``max_tokens`` a call actually goes out with, after the floor.

    The single answer to "what budget did the wire carry", shared by
    ``_apply_thinking_args`` (which imposes it) and the failure logging in
    ``call_llm`` (which reports it) -- they were two numbers once, so a
    budget-exhausted DeepSeek call logged "max_tokens: 8000" beside
    "reasoning_tokens=18001" and read as a provider fault, not a budget
    one.

    Args:
        model_name: Model name in litellm format.
        max_tokens: The budget the call site asked for.
        enable_thinking: Whether thinking mode is requested for this call.

    Returns:
        ``max_tokens`` raised to ``THINKING_FLOOR_MAX_TOKENS`` when this
        call will reason, otherwise ``max_tokens`` unchanged.
    """
    if enable_thinking and model_reasons(model_name):
        return max(max_tokens, THINKING_FLOOR_MAX_TOKENS)
    return max_tokens


def _apply_thinking_args(
    completion_args: dict[str, Any], model_name: str, enable_thinking: bool
) -> None:
    """Sets the DeepSeek thinking-mode kwargs on a completion call, in place.

    Also lifts ``max_tokens`` to ``THINKING_FLOOR_MAX_TOKENS`` when the
    call will think, since the budget must cover the chain of thought as
    well as the answer -- see that constant for why an answer-sized budget
    silently returns empty. Applied here, not at call sites, so a node
    added later cannot predate thinking; the floor only raises, so an
    already-larger budget keeps its own number.

    Args:
        completion_args: The in-progress completion kwargs dict; mutated in
            place with "extra_body", reasoning-effort args, and a raised
            "max_tokens" when thinking applies to this model.
        model_name: Model name in litellm format.
        enable_thinking: Whether DeepSeek thinking mode is requested.
    """
    thinking = deepseek_thinking_extra_body(model_name, enabled=enable_thinking)
    if not thinking:
        return

    completion_args["extra_body"] = thinking
    completion_args.update(
        reasoning_effort_args(model_name, enabled=enable_thinking)
    )

    completion_args["max_tokens"] = effective_max_tokens(
        model_name, completion_args["max_tokens"], enable_thinking
    )


_CONTEXT_ATTR: Final = "_co_scientist_failure_context"


def annotate_failure_context(
    error: Exception,
    model_name: str,
    max_tokens: int,
    enable_thinking: bool,
    call_site: str | None = None,
) -> None:
    """Record on ``error`` which call failed and what budget it carried.

    Both facts travel on the exception rather than being recovered
    wherever the failure is finally logged: the budget, because the floor
    and the retry ladder's escalations both move it, and a second
    computation is a second chance to disagree with the wire; the call
    site, because the layer that logs failures is shared by every node --
    a production export of fifteen answerless completions could be
    narrowed to a budget constant, and ten call sites share the commonest
    one.

    Args:
        error: The failure to annotate; annotating twice is harmless.
        model_name: Model name in litellm format.
        max_tokens: The budget the call site asked for.
        enable_thinking: Whether this call requested thinking.
        call_site: Short label naming the call, or ``None`` when the
            caller offered neither a prompt name nor a named schema.
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
    """Render an annotated error's call site and budget, or "".

    Args:
        error: A failure that may carry a context annotation.

    Returns:
        " (label, max_tokens N, call site asked for M)" -- without the
        leading label when the call was unnamed -- or the empty string
        when the failure was raised somewhere that never sent a request.
    """
    context = getattr(error, _CONTEXT_ATTR, None)
    if context is None:
        return ""
    call_site, sent, asked = context
    named = f"{call_site}, " if call_site else ""
    return f" ({named}max_tokens {sent}, call site asked for {asked})"
