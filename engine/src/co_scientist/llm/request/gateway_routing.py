"""OpenRouter gateway routing: provider order, throughput floor, price cap.

Split out of ``llm.request.thinking`` to keep that module under the repo's
file-length ceiling. What each model's routing is -- its pin, its fallback
chain, its price -- is stated in ``llm.profile``; this is the policy applied
to it.
"""

from typing import Any, Final

from co_scientist.config.env_vars import parse_list_env
from co_scientist.llm.profile import ModelProfile, model_profile

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
