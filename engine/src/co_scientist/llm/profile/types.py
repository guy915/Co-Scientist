"""What the engine knows about one model route, and how a table states it.

``ModelProfile`` is the answer to "what do we know about this model".
``Facts`` is a partial answer, which is what a table entry or a family rule
gives: it names only the fields it states and leaves the rest to whatever
sits beneath it. The two list the same fields (``test_model_profile`` fails
if they drift); they are separate types because a dataclass cannot say which
of its fields were stated and which merely hold their default.
"""

import enum
from dataclasses import dataclass
from typing import TypedDict


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
