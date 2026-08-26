"""Thinking/reasoning-mode argument shaping for LiteLLM completion calls.

Split from ``co_scientist.llm_request``: selects the thinking knob
(DeepSeek's native ``thinking`` object), the reasoning tier, and the
``max_tokens`` floor a thinking call needs. Every name here is re-exported
from ``co_scientist.llm_request`` so that module's namespace is unchanged.
"""

import logging
from dataclasses import dataclass
from typing import Any, Final

from co_scientist.constants import THINKING_FLOOR_MAX_TOKENS
from co_scientist.constants_pricing import MODEL_PRICING

logger = logging.getLogger(__name__)

# Provider-capability shim: some providers reject
# response_format={"type": "json_schema", ...} outright (DeepSeek returns an
# invalid-request error). For those models every schema'd call is downgraded,
# per call, to {"type": "json_object"} with the schema restated as prompt
# text, and missing required fields are back-filled with empty defaults
# before schema validation (json_object mode has no server-side schema
# enforcement, so nested required fields are routinely omitted). Models that
# support json_schema are untouched.
#
# Families listed here are checked BEFORE litellm's capability registry:
# litellm's cost map marks deepseek/* as supporting response schema, but the
# DeepSeek API only accepts json_object, so the registry alone cannot be
# trusted for these providers.
#
# ``ox-alpha`` is here for a different reason than DeepSeek, and a harder
# one: no host serving it accepts ``json_schema`` at all. Paired with
# ``require_parameters`` below that is not a soft degradation to an
# unconstrained answer -- the gateway finds no eligible host and the call
# fails outright ("No endpoints found that can handle the requested
# parameters"). Measured live: ``json_object`` plus the same routing
# constraint answers, ``json_schema`` plus it 404s.
_JSON_OBJECT_ONLY_MODEL_FAMILIES: tuple[str, ...] = ("deepseek", "ox-alpha")

# Routes that normalize reasoning control into their own parameter rather
# than forwarding the provider's. A gateway serves many models through one
# schema, so it cannot honour each provider's native knob, and the failure
# is silent in the worst direction: sending DeepSeek's ``thinking`` object
# through OpenRouter does not disable thinking, it *enables* it. Measured
# on `openrouter/deepseek/deepseek-v4-flash` -- a max_tokens=24 call
# carrying ``{"thinking": {"type": "disabled"}}` spent all 24 tokens on
# reasoning and returned empty content, which is exactly the budget-
# exhaustion shape documented in AGENTS.md, arriving from a parameter that
# was asking for the opposite.
_REASONING_PARAM_ROUTES: tuple[str, ...] = ("openrouter/",)

# The tier requested when thinking is on. DeepSeek implements only `high`
# and `max`, so this is the floor rather than a high setting.
_REASONING_EFFORT: Final[str] = "high"


# How far above a model's listed rate a routed call may land. A gateway
# spreads one model across hosts an order of magnitude apart in price as
# well as speed -- seventeen for `deepseek-v4-flash`, from $0.068 to $0.44
# per million input tokens -- and ``sort`` below picks on throughput,
# which does not consider price at all. Without a ceiling a call can be
# billed at five times what ``constants_pricing`` estimates, so the run
# cost this project reports is not an upper bound on anything.
#
# Two is deliberately loose. It keeps thirteen of the seventeen hosts
# eligible, so throughput routing still has a real field to choose from
# and losing a host is not an outage, while excluding the tail that costs
# 2.7x to 8x the listed rate. A cap tight enough to force the single
# cheapest host would make every price move a hard 404 on every call.
_MAX_PRICE_MULTIPLE: Final[float] = 2.0


# How a gateway route is addressed, beyond the reasoning knob itself.
# ``require_parameters`` is part of the same concern rather than a separate
# tuning: it restricts routing to hosts that actually accept every
# parameter sent, which is what makes the reasoning knob above binding
# instead of advisory. ``sort`` is a latency fix -- a gateway spreads one
# model across hosts an order of magnitude apart in speed, and by default
# picks on price, so a call can land on one serving single-digit tokens per
# second. Measured over six concurrent calls on
# `openrouter/deepseek/deepseek-v4-flash`: unconstrained, the slowest took
# 32.9s against a 2.3s median; constrained, 7.1s. The tail is what matters,
# because a node waits on its slowest call and the engine's own ceiling is
# 600s -- two calls hit exactly that during the first routed run.
_GATEWAY_PROVIDER: Final[dict[str, Any]] = {
    "require_parameters": True,
    "sort": "throughput",
}


@dataclass(frozen=True)
class GatewayModel:
    """What a gateway route needs to know about one model.

    Every fact here is a property of the model rather than of the route,
    and none is discoverable from its name -- which is why they are stated
    rather than inferred from a family substring. Inferring them is what
    made a rival vendor's model run with no reasoning configured and no
    price ceiling while looking exactly like a configured one. The two
    reasoning fields are separate for the same reason one scale down: a
    model can decline the parameter and still spend the budget.

    Attributes:
        takes_reasoning_knob: Whether to send the gateway's ``reasoning``
            parameter. A model that does not accept it gains nothing from
            being asked.
        spends_budget_thinking: Whether the model can consume its whole
            ``max_tokens`` before writing any answer, and so needs
            ``THINKING_FLOOR_MAX_TOKENS``. Deliberately separate from the
            knob above, because the two came apart in production: Ox Alpha
            reports ``reasoning_tokens=0`` and takes no reasoning
            parameter, yet still returns ``finish_reason="length"`` with
            empty content at an 8000-token budget -- it spends the
            allowance on something the API does not itemise. Recording
            that as "does not reason" cost 24 answerless round-trips in a
            single express run, each one climbing the escalation ladder to
            arrive at the budget this floor would have given it first.
            When unsure, fund it: a ceiling is not a spend.
        fallbacks: Gateway-relative ids to try, in order, when this model
            is unavailable. The gateway walks the list itself, which is
            the only layer that can: a 429 from a saturated free pool is
            not something the engine's retry ladder fixes by asking the
            same host again, and it is not a transport error either.
    """

    takes_reasoning_knob: bool
    spends_budget_thinking: bool
    fallbacks: tuple[str, ...] = ()


# The models this deployment reaches through the gateway, and the order it
# falls through them. Ox Alpha is free and serves the whole run; GLM 5.2's
# free pool catches it when Ox Alpha is rate-limited; Muse Spark is the
# paid last resort, reached only when both free models are unavailable.
#
# Note what the middle rung is worth today: `z-ai/glm-5.2:free` returned
# 429 on every one of nine live probes, its free pool being saturated
# rather than the account being throttled. So the chain's real behaviour
# under an Ox Alpha outage is a fall to the paid model, at $1.25/$4.25 per
# million -- twenty times the rate of anything else here. That is the
# chain doing what it was asked to do, not a defect, but it is the one
# way this configuration spends money.
_GATEWAY_MODELS: Final[dict[str, GatewayModel]] = {
    "openrouter/stealth/ox-alpha": GatewayModel(
        takes_reasoning_knob=False,
        spends_budget_thinking=True,
        fallbacks=("z-ai/glm-5.2:free", "meta/muse-spark-1.2"),
    ),
    "openrouter/z-ai/glm-5.2:free": GatewayModel(
        takes_reasoning_knob=True, spends_budget_thinking=True
    ),
    "openrouter/z-ai/glm-5.2": GatewayModel(
        takes_reasoning_knob=True, spends_budget_thinking=True
    ),
    "openrouter/meta/muse-spark-1.2": GatewayModel(
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
        ``_GATEWAY_PROVIDER`` plus a ``max_price`` ceiling derived from
        the model's listed rate. The ceiling is omitted for a model absent
        from ``MODEL_PRICING``: an unpriced model has no rate to be a
        multiple of, and capping it at zero would refuse every host.
    """
    provider = dict(_GATEWAY_PROVIDER)
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

    DeepSeek V4 (pro/flash) are reasoning models: the chain of thought is
    returned separately as ``reasoning_content`` and never mixed into
    ``content``, so structured/JSON parsing is unaffected as long as the
    ``max_tokens`` budget leaves room for the answer after the reasoning
    spend. Budgets are not sized for that per node -- most predate thinking
    being switched on everywhere -- so ``_apply_thinking_args`` raises any
    thinking call to ``THINKING_FLOOR_MAX_TOKENS``. Non-DeepSeek models get
    an empty dict.

    Thinking is on for every node. ``enabled=False`` remains the seam for
    opting a call site out; nothing uses it today. Any future opt-out is a
    latency decision, and the two call sites where it would pay are the
    ranking tournament's pairwise matchups, which run O(n^2) times per cycle
    (``agents/ranking/ranking_debate.py``), and supervisor allocation, which
    runs once per loop point on the run's serial spine where nothing else is
    executing (``agents/supervisor/supervisor_decision.py``).

    Args:
        model_name: Model name in litellm format.
        enabled: Whether to request thinking mode. False explicitly disables
            it, which is not the same as omitting the field -- the API's own
            default is enabled.

    Returns:
        The ``extra_body`` this model's route needs: DeepSeek's native
        ``thinking`` object direct, or a gateway's ``reasoning`` object
        plus the routing constraint that makes it binding (see
        ``_REASONING_PARAM_ROUTES`` and ``_GATEWAY_PROVIDER``). Empty for
        a model with no thinking mode.
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

    ``high`` is the floor, not a high setting. DeepSeek implements exactly
    two tiers, ``high`` and ``max``, and accepts OpenAI's lower names
    (``low``, ``medium``) as aliases onto ``high`` -- the parameter and its
    vocabulary are OpenAI's, and DeepSeek only supports the top of that
    ladder. There is no cheaper way to think than this; the rung below is
    ``enabled=False``. ``high`` is also DeepSeek's default once thinking is
    on, so this field is belt-and-braces: litellm 1.80.x strips
    ``reasoning_effort`` from the body outright (BerriAI/litellm#27439), and
    since the value equals the default, that bug is inert. Sending it keeps
    the intent explicit and the call correct once the fix lands.

    **Direct routes only.** A gateway route already carries the tier inside
    the ``reasoning`` object ``deepseek_thinking_extra_body`` builds for it,
    so this field beside it is the same instruction twice -- and the copy
    the gateway rejects, since litellm raises ``UnsupportedParamsError`` for
    a model whose OpenRouter support map does not list the parameter. Engine
    calls pass ``drop_params`` and so never saw it; the app's own call sites
    invoke litellm directly without that, and the redundant field failed the
    contextual safety screen outright -- which parks a run for human review
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
    ``call_llm`` (which reports it). They were two numbers once: the error
    log printed the call site's own ``max_tokens`` while the request carried
    the floored value, so a budget-exhausted DeepSeek call logged
    "max_tokens: 8000" beside "reasoning_tokens=18001" and read as a
    provider fault rather than a budget one.

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

    Also lifts ``max_tokens`` to ``THINKING_FLOOR_MAX_TOKENS`` when the call
    will actually think, because the budget has to cover the chain of thought
    as well as the answer -- see that constant for why an answer-sized budget
    silently turns into an empty response. Applied here rather than at the
    call sites so a node cannot be added later with a budget that predates
    thinking; the floor only ever raises, so a node that sized itself above
    it keeps its own number.

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
    wherever the failure is finally logged. The budget, because the floor
    and the retry ladder's own escalations both move it, and a reader
    comparing ``max_tokens`` against ``reasoning_tokens`` is relying on
    the two having come from the same request -- a second computation is a
    second chance to disagree with the wire. The call site, because the
    layer that writes the record is shared by every node: a production
    export of fifteen answerless completions could be narrowed to a
    budget constant, and ten call sites share the commonest one.

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
