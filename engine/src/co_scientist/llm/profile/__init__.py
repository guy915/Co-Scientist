"""Model capabilities, routing facts and prices.

Exact routes override matching family defaults. Admission, request shaping
and pricing read the same ModelProfile without depending on higher LLM layers.
"""

import enum
from dataclasses import dataclass
from typing import Any, Final, TypedDict


@dataclass(frozen=True)
class ModelPrice:
    """USD price per million tokens for one model.

    Attributes:
        prompt_usd_per_million: Cost per million prompt (input) tokens.
        completion_usd_per_million: Cost per million completion (output)
            tokens. Reasoning tokens are billed at this same rate: most
            providers do not price them separately, and this table has no
            third rate to place them under.
        cached_prompt_usd_per_million: Cost per million prompt tokens the
            provider served from its prompt cache. Zero means *not
            measured for this model*, not free: ``estimate_cost_usd`` then
            prices every prompt token at the full input rate, which is
            what this table did before caching was read at all. Set it
            only for a model whose cache-read rate has been checked
            against the provider's own quote.
    """

    prompt_usd_per_million: float = 0.0
    completion_usd_per_million: float = 0.0
    cached_prompt_usd_per_million: float = 0.0


class Thinking(enum.Enum):
    """Which request shape selects a model's reasoning mode.

    Attributes:
        NONE: The model has no reasoning knob to send.
        NATIVE: DeepSeek's own ``thinking`` object plus a top-level
            ``reasoning_effort``, on the DeepSeek API itself.
        GATEWAY: The gateway's normalized ``reasoning`` object. A gateway
            serves many models through one schema, so it cannot honour each
            provider's native knob, and the failure is silent in the worst
            direction: sending DeepSeek's ``thinking`` object through
            OpenRouter does not disable thinking, it *enables* it. Measured
            on `openrouter/deepseek/deepseek-v4-flash`: a max_tokens=24
            call carrying ``{"thinking": {"type": "disabled"}}`` spent all
            24 tokens reasoning and returned empty content.
    """

    NONE = "none"
    NATIVE = "native"
    GATEWAY = "gateway"


@dataclass(frozen=True)
class ModelProfile:
    """Everything the engine acts on that depends on which model it calls.

    Every field defaults to what an unknown model gets: no reasoning knob,
    no routing, no price, no override of anything litellm's registry says.
    Each fact is a property of the model, stated rather than inferred from a
    family substring at the point of use -- inferring them is what made a
    rival vendor's model run with no reasoning knob and no price ceiling
    while looking configured, and what once let a single ``"deepseek"``
    substring gate four unrelated behaviours.

    Attributes:
        reasons: Whether the model can consume its whole ``max_tokens``
            before answering, needing ``THINKING_FLOOR_MAX_TOKENS``. The
            question the token floor actually asks, and deliberately not
            "does it take the reasoning parameter" (``thinking``). The two
            came apart in production: a model reporting
            ``reasoning_tokens=0`` and no reasoning parameter still
            returned ``finish_reason="length"`` with empty content at an
            8000-token budget, costing 24 answerless round-trips in one
            express run. When unsure, fund it: a ceiling is not a spend.
        thinking: How this model's reasoning mode is selected on the wire.
        reasoning_can_disable: Whether disabling reasoning on this model's
            own endpoint is honoured rather than 400ing. Default False:
            every declared gateway model is an OpenRouter free variant and
            none has evidence it accepts a disable -- one of them,
            `minimax/minimax-m3:free`, is *confirmed* to reject it outright
            ("Reasoning is mandatory for this endpoint and cannot be
            disabled", production run b82f9162's recovered finalize,
            2026-09-06 04:39:30 UTC), and a request can land on any host
            ``fallbacks`` lists, including this one, from a chain whose head
            never disables. A model with real evidence of honouring a
            disable earns ``True`` from a live probe against *every* rung of
            its own chain, not by assumption -- see
            ``test_no_chain_head_claims_disable_support_a_fallback_lacks``.
            When False, a caller asking for disabled reasoning instead gets
            it enabled at the smallest effort this gateway exposes (see
            ``llm.request.gateway_body._minimal_reasoning_knob``) -- never a
            bare resend of the rejected request.
        gateway: Whether the model is addressed through the OpenRouter
            gateway with declared routing: its request carries the
            ``provider`` block (upstream order, throughput floor, price
            ceiling, any pin) and the ``fallbacks`` below. Not the same as
            an ``openrouter/`` name: a route the engine knows nothing about
            is sent no routing at all.
        fallbacks: Gateway-relative ids to try, in order, when unavailable.
            The gateway walks the list itself: a 429 from a saturated pool
            is not a transport error the engine's retry ladder fixes. One
            entry, `nvidia/nemotron-3.5-lightning:free`, lists no
            `response_format` in its own `supported_parameters` (checked
            against OpenRouter's public model listing 2026-09-05) -- paired
            with `require_parameters`, a schema'd call cannot land there at
            all. Pre-existing on the paid chain this deployment inherited
            it from; not a reason to reorder, just a rung that is
            effectively text-only if a call ever reaches it.
        verified_provider: Pin a provisional route to the one provider whose
            current pricing and data-use terms were inspected. The request
            also requires zero retention and denies data collection.
        provider_only: Pin an inspected provider without imposing a data-use
            policy. Promotional free routes use this to avoid another host.
        json_schema: Whether the endpoint accepts a ``json_schema``
            ``response_format``. ``None`` leaves it to litellm's capability
            registry (and to True if that lookup raises); a stated value is
            checked before the registry, which is wrong for every route that
            has one: it marks deepseek/* as supporting response schema when
            the DeepSeek API only accepts ``json_object``, and its answer for
            a volatile free or stealth listing has been observed to flip
            between True and False across runs on the same day. Paired with
            ``require_parameters`` an unsupported format is a hard 404, not a
            soft degradation, so every gateway route states it.
        min_temperature: The lowest sampling temperature the model should be
            sent; a lower request is raised to it.
        price: The model's list price, or ``None`` when it has none on
            record, which prices at zero (an unlisted model degrades to "no
            cost tracked" rather than breaking telemetry) and leaves a
            gateway call without a price ceiling.
        promotional_free: Whether OpenRouter's own page calls this exact
            route free despite an ID without the ``:free`` suffix, so that it
            is admitted to zero-cost requests and may omit ancillary rates in
            its catalog entry. Fresh catalog prices and a zero token-price
            ceiling still gate every call.
    """

    reasons: bool = False
    thinking: Thinking = Thinking.NONE
    reasoning_can_disable: bool = False
    gateway: bool = False
    fallbacks: tuple[str, ...] = ()
    verified_provider: str | None = None
    provider_only: str | None = None
    json_schema: bool | None = None
    min_temperature: float | None = None
    price: ModelPrice | None = None
    promotional_free: bool = False


class Facts(TypedDict, total=False):
    """The fields of ``ModelProfile`` that one table entry states."""

    reasons: bool
    thinking: Thinking
    reasoning_can_disable: bool
    gateway: bool
    fallbacks: tuple[str, ...]
    verified_provider: str | None
    provider_only: str | None
    json_schema: bool | None
    min_temperature: float | None
    price: ModelPrice | None
    promotional_free: bool


@dataclass(frozen=True)
class Family:
    """Facts shared by every route whose name matches.

    Attributes:
        facts: What the family states about its members.
        prefix: The name must start with this (the name is lowercased).
        contains: The name must contain this.
    """

    facts: Facts
    prefix: str = ""
    contains: str = ""

    def matches(self, name: str) -> bool:
        """Whether a lowercased route name belongs to this family."""
        return name.startswith(self.prefix) and self.contains in name


# Zero is an explicit ceiling for free routes, including per-request fees:
# the routing block caps every price at it (``_gateway_provider``) and the
# free-request admission re-checks it per call. Static zero-token-price
# entries are an estimate, not proof of current availability or of every
# applicable charge.
_FREE: Final = ModelPrice(0.0, 0.0)


def _gateway(
    price: ModelPrice,
    *,
    fallbacks: tuple[str, ...] = (),
    json_schema: bool = False,
    verified_provider: str | None = None,
    provider_only: str | None = None,
) -> Facts:
    """A route reached through the OpenRouter gateway with declared routing.

    Every declared route reasons and takes the gateway's reasoning knob, and
    none is known to honour a disabled reasoning mode. ``json_schema`` is
    stated for each rather than left to litellm's registry: every rung in a
    gateway chain is paired with ``require_parameters`` (see
    ``llm.request.gateway_routing._GATEWAY_PROVIDER``), which turns an
    unsupported ``response_format`` into a hard 404 instead of a soft
    degradation, and at least one declared fallback
    (``nvidia/nemotron-3.5-lightning:free``) lists no ``response_format``
    support at all in its own OpenRouter listing, so ``json_object`` is the
    only format proven safe across every rung a chain might land on.
    """
    return {
        "gateway": True,
        "thinking": Thinking.GATEWAY,
        "reasons": True,
        "reasoning_can_disable": False,
        "json_schema": json_schema,
        "price": price,
        "fallbacks": fallbacks,
        "verified_provider": verified_provider,
        "provider_only": provider_only,
    }


# **A fallback may only ever be cheaper than the model above it**, and no
# chain may exceed ``_GATEWAY_MAX_FALLBACKS`` (OpenRouter's own cap on the
# ``models`` array). Wired the other way once -- free primary, paid last
# resort -- a "last resort" priced at $1.25/$4.25 served 3.17M tokens and
# billed $5.23 in an afternoon, because 429 is the *normal* state of a shared
# free pool, so the expensive rung was the routine destination rather than the
# emergency one. The guard against it already existed -- ``_gateway_provider``
# caps a routed call at ``_MAX_PRICE_MULTIPLE`` times the primary's listed
# rate -- but a primary priced at zero previously skipped the cap, leaving the
# request unbounded. Both rules are checked over this table by
# ``test_llm_gateway_pricing.py``. Current model eligibility still needs
# verification before live use.
#
# **Do not append paid fallbacks under free routes.**
ROUTES: Final[dict[str, Facts]] = {
    # Former system default, retained for explicit deployment overrides.
    # Campaign probes observed reasoning on both Nex variants; use bounded-
    # minimal reasoning and fund its answer. No model fallback is declared.
    "openrouter/nex-agi/nex-n2.5-pro:free": _gateway(_FREE),
    "openrouter/nex-agi/nex-n2.5-mini:free": _gateway(_FREE),
    # Provisional successor, not a system default. The listed ModelRun host
    # alone has been checked for exact-zero pricing and zero retention.
    # Pinned Qwen has native structured output but no JSON object mode (a
    # JSON object request hard-404ed on 2026-09-25).
    "openrouter/qwen/qwen3.8-27b:free": _gateway(
        _FREE, json_schema=True, verified_provider="modelrun"
    ),
    # A non-default chain head kept for a deployment that opts into it. It
    # was the deployed primary from 2026-09-05 until a real express
    # run measured its single host (Decart) answering only 7 of 85 calls --
    # a shared free pool saturated most of the day (1 of 11 live probes
    # answered, matching the same shape noted 2026-08-26) -- against its
    # own first fallback rung, Minimax M3, serving 74 of those calls at $0.
    # The 2026-09-06 default switch went straight to that rung; this entry's
    # chain remains for deployments that explicitly select it.
    "openrouter/z-ai/glm-5.2:free": _gateway(
        _FREE,
        fallbacks=(
            "minimax/minimax-m3:free",
            "nvidia/nemotron-3-super-120b-a12b:free",
            "nvidia/nemotron-3.5-lightning:free",
        ),
    ),
    # The previously deployed primary, retained with its all-free chain for
    # deployments that explicitly select it. Measured 2026-09-05/06 through
    # this account's OpenRouter key:
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
    # Every rung must be priced $0/$0. The provider's zero ceiling also
    # binds fallback selection; a paid rung cannot escape it on a 429.
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
    # 2026-09-06) to respect ``_GATEWAY_MAX_FALLBACKS``. Dots Note (3/3 at
    # 1-5s, AtlasCloud), Nemotron Lightning (3/3 but slow, 8-23s, and its own
    # listing carries no ``response_format`` at all -- paired with
    # ``require_parameters`` a schema'd call cannot land there) and GLM 5.2
    # (0/3, saturated) stay declared below as standalone entries, at $0/$0,
    # so a deployment can still name one directly as its own primary or
    # hand-edit it back into a trio; they no longer ride in this default
    # chain.
    "openrouter/minimax/minimax-m3:free": _gateway(
        _FREE,
        fallbacks=(
            "nvidia/nemotron-3-super-120b-a12b:free",
            "google/gemma-4-31b-it:free",
            "minimax/minimax-m2.7:free",
        ),
    ),
    "openrouter/nvidia/nemotron-3-super-120b-a12b:free": _gateway(_FREE),
    "openrouter/google/gemma-4-31b-it:free": _gateway(_FREE),
    "openrouter/minimax/minimax-m2.7:free": _gateway(_FREE),
    "openrouter/dots-studio/dots-3-note-preview:free": _gateway(_FREE),
    "openrouter/nvidia/nemotron-3.5-lightning:free": _gateway(_FREE),
    # Selected zero-price system default. OpenRouter's own page calls this
    # exact preview free despite its unsuffixed ID; promotional admission
    # rechecks the current listing on every call, while this route pins
    # Stealth with no fallbacks.
    "openrouter/stealth/space-bunny-alpha": {
        **_gateway(_FREE, provider_only="Stealth"),
        "promotional_free": True,
    },
    # The paid alternative chain head, kept for a deployment that opts back
    # into it (``app.config`` no longer defaults here). Its price is the
    # historical promotional rate and its routing ceiling uses the same
    # configured price multiple as other paid entries; revalidate current
    # pricing before choosing this route.
    "openrouter/z-ai/glm-5.3-flash": _gateway(
        ModelPrice(0.075, 0.25, 0.015),
        fallbacks=(
            "minimax/minimax-m3:free",
            "nvidia/nemotron-3.5-lightning:free",
        ),
    ),
    # Gemma's endpoint has JSON object mode only. Exact endpoint evidence,
    # ahead of the generic gateway downgrade; not otherwise declared.
    "openrouter/google/gemma-4-26b-a4b-it:free": {"json_schema": False},
    # DeepSeek's own API. The family supplies everything but the price.
    "deepseek/deepseek-v4-flash": {"price": ModelPrice(0.44, 1.32)},
    "deepseek/deepseek-v4-pro": {"price": ModelPrice(1.32, 3.96)},
    "deepseek/deepseek-chat": {"price": ModelPrice(0.44, 1.32)},
    "deepseek/deepseek-reasoner": {"price": ModelPrice(1.32, 3.96)},
    "gemini/gemini-2.5-flash": {"price": ModelPrice(0.30, 2.50)},
    "gemini/gemini-2.5-flash-lite": {"price": ModelPrice(0.10, 0.40)},
    "gemini/gemini-2.5-pro": {"price": ModelPrice(1.25, 10.00)},
    "gemini/gemini-3.1-flash-lite": {"price": ModelPrice(0.25, 1.50)},
    # The same DeepSeek weights reached through OpenRouter, which routes
    # across seventeen hosts spanning 6.5x on input and 7.9x on output.
    # Which one a call lands on is a routing decision, not a property of
    # the model (see ``llm.request.gateway_routing``), so these are the rates
    # a price-capped route can actually be held to rather than an average
    # over hosts the cap excludes. Listed separately because they are a
    # different bill, not a different model: the worker tier costs roughly a
    # fifth of first-party peak. Rates move as hosts come and go -- these
    # were OpenRouter's quoted prices in August 2026, and OpenRouter reports
    # the exact cost of each call in its own dashboard, which is the billing
    # record this only estimates.
    "openrouter/deepseek/deepseek-v4-flash": {
        "price": ModelPrice(0.083, 0.165, 0.017)
    },
    # Priced off the fp8 hosts rather than the cheapest row on the board: the
    # headline rate for this model belongs to an fp4 host at 95% uptime, and
    # ``_MAX_PRICE_MULTIPLE`` scales whatever is written here into the routing
    # ceiling, so a rate copied from the cheapest quantized host would cap the
    # route below every full-precision one. At 2x this, twenty of the model's
    # twenty-nine hosts stay eligible, and the tail charging up to 3.4x this
    # on input and 4.7x on output -- DeepSeek's own first-party endpoint among
    # them, at 0.22/0.66 -- is excluded.
    "openrouter/deepseek/deepseek-v4-flash-0731": {
        "price": ModelPrice(0.13, 0.28, 0.028)
    },
    # The paid last resort, and the only rung that can spend anything. At
    # twenty times the rate of the DeepSeek route this replaced, a run that
    # falls all the way through costs materially more than one that does
    # not -- so a bill appearing here is a signal that both free rungs were
    # unavailable, not that the model was chosen.
    "openrouter/deepseek/deepseek-v4-pro": {
        "price": ModelPrice(1.60, 3.20, 0.13)
    },
    "openai/gpt-4o": {"price": ModelPrice(2.50, 10.00)},
    # Azure resells OpenAI's models at OpenAI's list price. Present because
    # ``BYOK_PROVIDER_DEFAULT_MODELS`` names it, and an unpriced model reports
    # every run as costing nothing.
    "azure/gpt-4o": {"price": ModelPrice(2.50, 10.00)},
    "openai/gpt-4o-mini": {"price": ModelPrice(0.15, 0.60)},
    "anthropic/claude-sonnet-4-5": {"price": ModelPrice(3.00, 15.00)},
}


FAMILIES: Final[tuple[Family, ...]] = (
    # DeepSeek, whichever host serves it. The whole family reasons, so
    # every member needs the token floor; honours a disabled reasoning mode;
    # and takes DeepSeek's own ``thinking`` object on its own API. Only
    # ``json_object`` is accepted there, which litellm's registry denies
    # knowing: it marks deepseek/* as supporting response schema, and the
    # DeepSeek API answers a schema'd request with an invalid-request error.
    # Every schema'd call is therefore downgraded, per call, to json_object
    # with the schema restated as prompt text, and missing required fields
    # back-filled with empty defaults (json_object mode has no server-side
    # enforcement, so nested required fields are routinely omitted).
    Family(
        contains="deepseek",
        facts={
            "reasons": True,
            "thinking": Thinking.NATIVE,
            "reasoning_can_disable": True,
            "json_schema": False,
        },
    ),
    # DeepSeek reached through OpenRouter: the gateway normalizes reasoning
    # into its own parameter (``Thinking.GATEWAY``) and spreads one model
    # across hosts that differ sharply in price, so the call carries the
    # routing block and its price ceiling even though no entry names the
    # model.
    Family(
        prefix="openrouter/",
        contains="deepseek",
        facts={"thinking": Thinking.GATEWAY, "gateway": True},
    ),
    # Gemini 3 degrades below temperature 1.0.
    Family(contains="gemini-3", facts={"min_temperature": 1.0}),
)


def model_profile(model_name: str) -> ModelProfile:
    """What the engine knows about ``model_name``.

    Built from the families the name matches, in order, and then from the
    route's own entry, which overrides all of them; a field nobody states is
    what an unknown model gets. The name is lowercased first, as every
    capability question about a model always was.

    Deliberately not cached: resolving is a handful of dict operations next
    to a network call, and an uncached read is one a test can patch the table
    under (``llm.profile.routes.ROUTES``) without a cache to clear.

    Args:
        model_name: Model name in litellm format, any case.

    Returns:
        The model's profile.
    """
    lowered = model_name.lower()
    facts: dict[str, Any] = {}
    for family in FAMILIES:
        if family.matches(lowered):
            facts.update(family.facts)
    facts.update(ROUTES.get(lowered, {}))
    return ModelProfile(**facts)


def gateway_routes() -> tuple[str, ...]:
    """Every route that is declared with gateway routing, in table order."""
    return tuple(name for name, facts in ROUTES.items() if facts.get("gateway"))


def priced_routes() -> dict[str, ModelPrice]:
    """The list price of every route that has one, by exact route name."""
    return {
        name: price
        for name, facts in ROUTES.items()
        if (price := facts.get("price")) is not None
    }


def promotional_free_route(route: str) -> bool:
    """Whether the gateway-relative id ``route`` is an admitted promotion.

    An exact, case-sensitive match on the id as OpenRouter's catalog spells
    it, unlike ``model_profile``: admission is checked against that
    catalog, whose ids are exact.

    Args:
        route: An OpenRouter model id without the ``openrouter/`` prefix.

    Returns:
        True when the route's own entry marks it promotionally free.
    """
    return bool(ROUTES.get(f"openrouter/{route}", {}).get("promotional_free"))


__all__ = [
    "ModelPrice",
    "ModelProfile",
    "Thinking",
    "gateway_routes",
    "model_profile",
    "priced_routes",
    "promotional_free_route",
]
