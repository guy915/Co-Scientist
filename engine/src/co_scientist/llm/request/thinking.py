"""Reasoning budgets, gateway routing and provider request shaping."""

import contextlib
import logging
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any, Final

from co_scientist.config.env_vars import parse_list_env
from co_scientist.constants import (
    MINIMAL_REASONING_MAX_TOKENS,
    THINKING_FLOOR_MAX_TOKENS,
)
from co_scientist.llm.profile import ModelProfile, Thinking, model_profile

logger = logging.getLogger(__name__)


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
#
# ``allow_fallbacks: True`` is the safety valve for both the order below
# and the price cap: OpenRouter falls through to *any* host under
# ``max_price`` once every ordered host is unavailable, rather than
# failing the call. That is intended -- a request answered by an
# unlisted but affordable host beats one that errors -- and it is why
# the price cap, not the order, is what actually bounds spend.
_GATEWAY_PROVIDER: Final[dict[str, Any]] = {
    "require_parameters": True,
    "allow_fallbacks": True,
}

# Soft throughput floor replacing what ``sort: throughput`` protected,
# without its per-call repicking. OpenRouter documents this as
# *deprioritization* -- "moved to the end of the list, not excluded" --
# so an undocumented interaction with ``order`` is at worst a no-op (25
# tok/s sits below every upstream's measured median, lowest Together at
# 42.65, see the throughput note on ``_DEFAULT_UPSTREAM_ORDER`` below)
# and overrides ``order`` only when the ordered host is already the
# problem.
#
# 25 is sized off the incident, not the medians: at the 600s call
# ceiling, an 8k-token reply (the large-output tier below) clears in
# 320s at 25 tok/s -- comfortable margin -- while the incident's "single
# digit tokens per second" still trips it. Applies to p50 (OpenRouter's
# rolling per-endpoint stat, not this request), so it flags a
# persistently degraded host, not one slow response.
_MIN_THROUGHPUT_TOKENS_PER_SEC: Final[int] = 25

# How far above a model's listed rate a routed call may land. A gateway
# spreads one model across hosts that differ sharply in price. For
# `z-ai/glm-5.3-flash`'s endpoint list on 2026-09-05: four hosts (Z.AI,
# DeepInfra, Novita, GMICloud) charge the listed $0.075/$0.25 headline
# rate; a middle band (Morph 1.29x, Wafer 1.33x, Makora 1.87x, Modal
# 1.9998x) sits strictly between 1x and 2x; sixteen more hosts sit at
# exactly 2x ($0.15/$0.50, Friendli and Together among them). A cap of
# 2.0 admits that whole middle band plus the 2x tier -- which is how a
# production run ended up routed to Modal (1.9998x) and billed $4.70 for
# work priced at $2.50 headline.
#
# 1.05 is the tightest cap that still admits every headline-rate host
# (the highest, at exactly 1.0x, has zero margin against float
# representation in the gateway's own price comparison) while excluding
# the entire middle band and the 2x tier above it -- the next host up,
# Morph at 1.29x, is nowhere close, so there is no host this admits by
# accident. Tighter than that (forcing a single specific host) would
# make an ordinary provider price move a hard 404 on every call: the
# gateway refuses the request outright rather than degrading, per
# ``require_parameters``/``max_price`` semantics. If every gateway call
# starts failing with "No endpoints found that can handle the requested
# parameters", check whether the route's price in the model profile
# table (``llm.profile.routes``) has drifted below what the headline
# hosts now actually charge -- raising this multiple is the wrong fix;
# updating that price is the right one, since it is also this project's
# own cost estimate (``MODEL_PRICING``).
#
# ``COSCIENTIST_GATEWAY_PROVIDER_ORDER`` can only reorder hosts that
# already pass this cap -- naming a 2x host there is a silent no-op,
# since ``max_price`` is enforced by the gateway itself and
# ``allow_fallbacks`` does not relax it.
_MAX_PRICE_MULTIPLE: Final[float] = 1.05


# Env var that overrides the preferred upstream order without a deploy.
# Read per call (see ``parse_list_env``), not cached at import, for the
# same reason ``parse_timeout_env`` is: an operator retuning this after a
# cache-locality regression should not need to restart the process.
_UPSTREAM_ORDER_ENV: Final[str] = "COSCIENTIST_GATEWAY_PROVIDER_ORDER"

# The four hosts that serve `z-ai/glm-5.3-flash` at OpenRouter's listed
# rate (verified against https://openrouter.ai/api/v1/providers and the
# model's own endpoint list on 2026-09-05: Z.AI, DeepInfra, Novita and
# GMICloud all price at $0.075/$0.25 prompt/completion per million
# tokens and all support the ``reasoning``/``response_format``/
# ``max_tokens``/``temperature`` parameters this route sends -- see
# ``_MAX_PRICE_MULTIPLE`` above for where the other three dozen
# endpoints on this model sit). Z.AI first as the first-party host for
# this model; DeepInfra, Novita, GMICloud follow in no particular
# preference beyond being priced identically to it.
#
# This replaces a throughput-derived order (Modal/Friendli/Together,
# pinned 2026-09-04 for the cache-locality reason documented on
# ``_GATEWAY_PROVIDER`` above) that optimized for measured speed without
# noticing all three sit in the 2x price tier -- exactly the
# $4.70-vs-$2.50 incident ``_MAX_PRICE_MULTIPLE`` now excludes them for.
# The headline-priced hosts' throughput is NOT measured (no production
# traffic has landed on them yet); if any of them turns out to be the
# "single digit tokens per second" shape the original `sort: throughput`
# incident was about, ``_MIN_THROUGHPUT_TOKENS_PER_SEC`` is the floor
# that deprioritizes it without needing a re-pin, and
# ``COSCIENTIST_GATEWAY_PROVIDER_ORDER`` lets an operator retune this
# order live. Do not re-promote a 2x-priced host to the front of this
# list for throughput alone without raising ``_MAX_PRICE_MULTIPLE`` in
# the same change -- that pairing is exactly what caused the incident.
_DEFAULT_UPSTREAM_ORDER: Final[tuple[str, ...]] = (
    "z-ai",
    "deepinfra",
    "novita",
    "gmicloud",
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


# OpenRouter's own ceiling on the ``models`` fallback array: "'models'
# array must have 3 items or fewer." Hit in production on run b82f9162
# (2026-09-06 00:19 UTC): the six-rung ``minimax-m3:free`` chain (added in
# 61c4be3d) sent all six as ``models``, every gateway call 400'd on the
# first request of the run, and the semantic safety screen -- the first
# caller -- fell back to "assessment unavailable" and held the run at
# intake. Declared here, beside the rest of the routing policy, so the shape
# is checked once over the declared routes (``llm.profile.routes``) in
# ``test_llm_gateway_pricing.py`` rather than re-discovered per chain.
_GATEWAY_MAX_FALLBACKS: Final[int] = 3


def _apply_provider_pin(
    provider: dict[str, Any], profile: ModelProfile
) -> None:
    if profile.verified_provider:
        provider.pop("order", None)
        provider["only"] = [profile.verified_provider]
        provider["zdr"] = True
        provider["data_collection"] = "deny"
    elif profile.provider_only:
        provider.pop("order", None)
        provider["only"] = [profile.provider_only]
        provider["allow_fallbacks"] = False


def _gateway_provider(model_name: str) -> dict[str, Any]:
    """Return the routing block for a gateway call, price-capped.

    Args:
        model_name: Model name in litellm format, already lowercased.

    Returns:
        ``_GATEWAY_PROVIDER`` plus ``preferred_min_throughput``, the
        preferred upstream ``order`` (unless env-disabled), and a
        ``max_price`` ceiling from the model's listed rate -- omitted for
        a model with no price in its profile, which has no rate to cap.
    """
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


# The tier requested when thinking is on. DeepSeek implements only `high`
# and `max`, so this is the floor rather than a high setting.
_REASONING_EFFORT: Final[str] = "high"

# The smallest reasoning tier this gateway's unified ``reasoning`` object
# exposes (OpenRouter's own three-tier "low"/"medium"/"high", mirrored by
# litellm's `reasoning_effort`). No longer the first thing a
# mandatory-reasoning model is sent -- it bounds nothing: production
# measured 24547 reasoning tokens from a "low" request against a
# 24000-token budget (run 6760ce63) -- so it is now the *recovery* shape,
# sent only after a host rejects the explicit bound
# ``_minimal_reasoning_knob`` prefers. Unlike ``_REASONING_EFFORT`` this
# value is unprobed against the models it is used for: a host that
# rejects "low" itself fails with a different 400 the retry ladder does
# not recognise, which is an accepted gap, not a hidden one -- see
# ``escalation_for_error``.
_MINIMAL_REASONING_EFFORT: Final[str] = "low"

# Forces the next completion this task makes to request the smallest
# permitted reasoning tier instead of disabling it outright, however the
# call site's own ``enable_thinking`` reads. Set only by the retry loop's
# recovery rung for a "reasoning is mandatory" 400 (``llm.attempts.escalation
# .BudgetEscalation.MINIMAL_REASONING_REQUIRED``), scoped to that one
# attempt -- a ``ContextVar`` rather than a new bool threaded through
# ``CompletionShape``/``LLMCallOptions`` and every function between the
# retry loop and this module, mirroring
# ``llm.admission.credentials.scoped_api_key``: each asyncio task gets its own
# copy, so one recovery attempt cannot leak into a concurrent call sharing the
# process.
_minimal_reasoning_forced: ContextVar[bool] = ContextVar(
    "minimal_reasoning_forced", default=False
)


@contextlib.contextmanager
def scoped_minimal_reasoning() -> Iterator[None]:
    """Force the smallest permitted reasoning tier for calls in this block.

    Entered by the retry loop for exactly one attempt, when a provider has
    just rejected a disabled-reasoning request as mandatory -- see the
    module comment on ``_minimal_reasoning_forced``.
    """
    token = _minimal_reasoning_forced.set(True)
    try:
        yield
    finally:
        _minimal_reasoning_forced.reset(token)


def _minimal_reasoning_knob(recovering: bool) -> dict[str, Any]:
    """The ``reasoning`` object for a call forced to reason against its wish.

    Two shapes, because the second exists to survive the first being
    refused. By default the request carries an explicit bound on the
    chain of thought (``MINIMAL_REASONING_MAX_TOKENS``): a tier name
    alone bounds nothing -- production measured 24547 reasoning tokens
    from a "low" request against a 24000-token budget (run 6760ce63) --
    and the whole point of forcing reasoning on a classification call is
    to spend as little of it as the endpoint permits. Only the bound is
    sent, never the bound and a tier together: the gateway documents the
    two as alternatives and this deployment has not probed sending both.

    ``recovering`` is the retry loop mid-recovery from a provider that
    refused the request outright (``scoped_minimal_reasoning``), which
    includes refusing the bound itself. It then falls back to the tier
    name -- the shape production has actually been served -- rather than
    resending a request already rejected.

    Args:
        recovering: Whether this call is the retry loop's own recovery
            attempt after a refusal.

    Returns:
        Reasoning enabled, bounded by an explicit token cap, or at the
        smallest tier the gateway exposes when recovering.
    """
    if recovering:
        return {"enabled": True, "effort": _MINIMAL_REASONING_EFFORT}
    return {"enabled": True, "max_tokens": MINIMAL_REASONING_MAX_TOKENS}


def effective_thinking_enabled(model_name: str, enable_thinking: bool) -> bool:
    """Whether this call will actually reason, per what the endpoint requires.

    Distinct from the call site's own ``enable_thinking``: a caller asking
    to disable reasoning can still be sent a request that reasons, either
    because the declared model rejects disabling outright
    (``ModelProfile.reasoning_can_disable``) or because the retry loop is
    mid-recovery from exactly that rejection (``scoped_minimal_reasoning``).
    Both funding (``effective_max_tokens``) and failure reporting
    (``annotate_failure_context``) need this real answer, not the request
    as asked -- an unfunded mandatory-reasoning call reproduces the same
    answerless-completion shape the token floor exists to prevent.

    Args:
        model_name: Model name in litellm format.
        enable_thinking: Whether the call site itself requested thinking.

    Returns:
        True if the outgoing request will carry reasoning enabled, for any
        reason; False only when it will genuinely go out disabled.
    """
    if enable_thinking or _minimal_reasoning_forced.get():
        return True
    profile = model_profile(model_name)
    return (
        profile.thinking is Thinking.GATEWAY
        and not profile.reasoning_can_disable
    )


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

    Thinking is on for every node. ``enabled=False`` opts a call site out
    of the reasoning spend -- ``app.claims.verifier``'s entailment judge is
    the one caller today, on a classification task a chain of thought
    does not earn its keep on. Whether the wire actually carries a
    disable is this function's decision, not the caller's: a declared
    gateway model that rejects disabling outright
    (``ModelProfile.reasoning_can_disable``) is sent bounded minimal
    reasoning instead, never the literal request already known to 400 --
    see ``_gateway_body`` and ``_minimal_reasoning_knob``.

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
    profile = model_profile(lowered)
    if profile.thinking is Thinking.NATIVE:
        return {"thinking": {"type": "enabled" if enabled else "disabled"}}
    if not profile.gateway:
        return {}
    return _gateway_body(lowered, profile, enabled)


def _gateway_body(
    lowered: str, profile: ModelProfile, enabled: bool
) -> dict[str, Any]:
    """Build the ``extra_body`` for a model reached through the gateway.

    Args:
        lowered: Model name in litellm format, already lowercased.
        profile: What the gateway needs to know about this model.
        enabled: Whether thinking mode is requested for this call.

    Returns:
        The routing constraint always, the fallback chain when one is
        declared, and the reasoning knob only for a model that takes it --
        bounded (``_minimal_reasoning_knob``) rather than a bare disable
        when either the model itself rejects disabling
        (``profile.reasoning_can_disable``) or the retry loop is
        recovering from exactly that rejection
        (``scoped_minimal_reasoning``); see ``effective_thinking_enabled``
        for the matching token-floor decision.
    """
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
        reasoning["effort"] = _REASONING_EFFORT
    body["reasoning"] = reasoning
    return body


def model_reasons(model_name: str) -> bool:
    """Whether this model can spend its whole budget before answering.

    The question the token floor actually asks, and deliberately not "does
    it take the reasoning parameter" (``ModelProfile.thinking``). The two
    came apart in production: Ox Alpha answers no to the second and yes to
    this one, and conflating them withheld the floor from a model that
    needed it, costing 24 answerless round-trips in one express run.

    Args:
        model_name: Model name in litellm format.

    Returns:
        ``ModelProfile.reasons``: True for a declared gateway model that
        spends its budget thinking, and for any DeepSeek model, whose whole
        family does.
    """
    return model_profile(model_name).reasons


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
    if enabled and model_profile(model_name).thinking is Thinking.NATIVE:
        return {"reasoning_effort": _REASONING_EFFORT}
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
        ``max_tokens`` unchanged when this call will not reason,
        otherwise raised to ``THINKING_FLOOR_MAX_TOKENS``. Whether it
        will reason is ``effective_thinking_enabled``, not the raw
        ``enable_thinking`` argument: a call that asked to disable
        reasoning but is going out with it forced on still needs the
        floor, or funding it reproduces the exact bug the floor exists to
        prevent. That forced call gets the *same* floor as any other
        thinking call, because its chain of thought is bounded in the
        request itself (``MINIMAL_REASONING_MAX_TOKENS``); a premium
        floor was tried instead and lost, since the reasoning simply grew
        to fill it -- see that constant's docstring.
    """
    if not (
        effective_thinking_enabled(model_name, enable_thinking)
        and model_reasons(model_name)
    ):
        return max_tokens
    return max(max_tokens, THINKING_FLOOR_MAX_TOKENS)


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
