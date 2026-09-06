"""OpenRouter gateway routing: provider order, throughput floor, price cap.

Split out of ``llm_thinking`` to keep that module under the repo's file-
length ceiling. Every public and private name here is re-exported from
``co_scientist.llm_thinking`` so nothing importing from there (including
tests that patch ``llm_thinking.<name>``) needs to change.
"""

from dataclasses import dataclass
from typing import Any, Final

from co_scientist.config.env_vars import parse_list_env
from co_scientist.constants_pricing import MODEL_PRICING

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
# parameters", check whether ``MODEL_PRICING`` has drifted below what
# the headline hosts now actually charge -- raising this multiple is
# the wrong fix; updating the pricing constant is the right one, since
# that constant is also this project's own cost estimate.
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
            One entry, `nvidia/nemotron-3.5-lightning:free`, lists no
            `response_format` in its own `supported_parameters` (checked
            against OpenRouter's public model listing 2026-09-05) -- paired
            with `require_parameters`, a schema'd call cannot land there at
            all. Pre-existing on the paid chain this deployment inherited
            it from; not a reason to reorder, just a rung that is
            effectively text-only if a call ever reaches it.
    """

    takes_reasoning_knob: bool
    spends_budget_thinking: bool
    fallbacks: tuple[str, ...] = ()


# OpenRouter's own ceiling on the ``models`` fallback array: "'models'
# array must have 3 items or fewer." Hit in production on run b82f9162
# (2026-09-06 00:19 UTC): the six-rung ``minimax-m3:free`` chain below
# (added in 61c4be3d) sent all six as ``models``, every gateway call
# 400'd on the first request of the run, and the semantic safety screen
# -- the first caller -- fell back to "assessment unavailable" and held
# the run at intake. Declared here so the shape is checked once, in
# ``test_llm_gateway_fallback.py``, rather than re-discovered per chain.
_GATEWAY_MAX_FALLBACKS: Final[int] = 3

# The models this deployment reaches through the gateway, and the order it
# falls through them.
#
# **No chain's ``fallbacks`` may exceed ``_GATEWAY_MAX_FALLBACKS``** --
# OpenRouter's own cap on the ``models`` array (see the comment on that
# constant above).
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
    # A non-default chain head kept for a deployment that opts back into
    # it. It was the deployed primary from 2026-09-05 until a real express
    # run measured its single host (Decart) answering only 7 of 85 calls --
    # a shared free pool saturated most of the day (1 of 11 live probes
    # answered, matching the same shape noted 2026-08-26) -- against its
    # own first fallback rung, Minimax M3, serving 74 of those calls at $0.
    # ``app.config`` now defaults every tier straight to that rung instead,
    # with no chain behind it. This entry's own chain is unchanged, for
    # whoever opts back in.
    "openrouter/z-ai/glm-5.2:free": GatewayModel(
        takes_reasoning_knob=True,
        spends_budget_thinking=True,
        fallbacks=(
            "minimax/minimax-m3:free",
            "nvidia/nemotron-3-super-120b-a12b:free",
            "nvidia/nemotron-3.5-lightning:free",
        ),
    ),
    # The deployed primary (also ``app.config``'s default on every tier),
    # now heading its own all-free chain again -- a second reversal in one
    # day. Measured 2026-09-05/06 through this account's OpenRouter key:
    # every ``:free`` variant carries its own per-model daily cap (~100
    # requests/day, plus a shared 20 req/min across all free variants), not
    # the "one saturated pool" shape the 2026-09-06 single-model switch
    # assumed -- the 429 body for a different free model read "Daily limit
    # reached... Credits don't affect this cap", `limit_source:
    # openrouter_shared_capacity`. A single free primary with nothing behind
    # it therefore stops the whole run dead the moment its own ~100/day is
    # spent, however healthy every other free model is. OpenRouter's
    # ``models`` fallback array falls through on a 429 exactly as it does on
    # a provider error, so a chain of N free models buys roughly N x 100
    # free calls/day before any of them needs a real spend.
    #
    # **Every rung in this chain must be priced $0/$0.** A free primary
    # disarms ``_gateway_provider``'s price cap outright (see the comment
    # above ``_GATEWAY_MODELS``): zero has no meaningful multiple, so the
    # route goes out uncapped. That is safe only because there is nothing
    # here to overspend on -- a paid rung appended below a free primary was
    # exactly the 2026-08-26 incident ($1.25/$4.25 "last resort" served
    # 3.17M tokens, billed $5.23 in an afternoon, because 429 is the
    # *normal* state of a shared free pool, not the rare case a last resort
    # assumes). ``test_no_fallback_costs_more_than_the_model_above_it``
    # holds this chain to that rule over the declared table, not by
    # inspection.
    #
    # Order follows the live probe (3 concurrent JSON requests each,
    # 2026-09-05/06): Nemotron Super and GLM M2.7 answered 3/3 fast
    # (~1-3s, GMICloud/Nvidia); Gemma answered 2/3 (Google AI Studio, one
    # upstream 429). Every rung reasons and spends its budget thinking
    # (checked against each model's ``supported_parameters`` listing,
    # which carries ``reasoning`` for all of them), so none is inferred
    # rather than declared.
    #
    # Trimmed from six rungs to three (production run b82f9162,
    # 2026-09-06) to respect ``_GATEWAY_MAX_FALLBACKS`` -- see that
    # constant's comment above. Dots Note (3/3 at 1-5s, AtlasCloud),
    # Nemotron Lightning (3/3 but slow, 8-23s, and its own listing
    # carries no ``response_format`` at all -- paired with
    # ``require_parameters`` a schema'd call cannot land there) and GLM
    # 5.2 (0/3, saturated) stay declared below as standalone entries, at
    # $0/$0, so a deployment can still name one directly as its own
    # primary or hand-edit it back into a trio; they no longer ride in
    # this default chain.
    "openrouter/minimax/minimax-m3:free": GatewayModel(
        takes_reasoning_knob=True,
        spends_budget_thinking=True,
        fallbacks=(
            "nvidia/nemotron-3-super-120b-a12b:free",
            "google/gemma-4-31b-it:free",
            "minimax/minimax-m2.7:free",
        ),
    ),
    "openrouter/nvidia/nemotron-3-super-120b-a12b:free": GatewayModel(
        takes_reasoning_knob=True, spends_budget_thinking=True
    ),
    "openrouter/google/gemma-4-31b-it:free": GatewayModel(
        takes_reasoning_knob=True, spends_budget_thinking=True
    ),
    "openrouter/minimax/minimax-m2.7:free": GatewayModel(
        takes_reasoning_knob=True, spends_budget_thinking=True
    ),
    "openrouter/dots-studio/dots-3-note-preview:free": GatewayModel(
        takes_reasoning_knob=True, spends_budget_thinking=True
    ),
    "openrouter/nvidia/nemotron-3.5-lightning:free": GatewayModel(
        takes_reasoning_knob=True, spends_budget_thinking=True
    ),
    # The paid alternative chain head, kept for a deployment that opts back
    # into it (``app.config`` no longer defaults here). Its own chain and
    # rationale are unchanged.
    "openrouter/z-ai/glm-5.3-flash": GatewayModel(
        takes_reasoning_knob=True,
        spends_budget_thinking=True,
        fallbacks=(
            "minimax/minimax-m3:free",
            "nvidia/nemotron-3.5-lightning:free",
        ),
    ),
}


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
