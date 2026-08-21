"""Thinking/reasoning-mode argument shaping for LiteLLM completion calls.

Split from ``co_scientist.llm_request``: selects the thinking knob
(DeepSeek's native ``thinking`` object), the reasoning tier, and the
``max_tokens`` floor a thinking call needs. Every name here is re-exported
from ``co_scientist.llm_request`` so that module's namespace is unchanged.
"""

import logging
from typing import Any, Final

from co_scientist.constants import THINKING_FLOOR_MAX_TOKENS

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
_JSON_OBJECT_ONLY_MODEL_FAMILIES: tuple[str, ...] = ("deepseek",)

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


def _is_gateway_route(model_name: str) -> bool:
    """Whether this route is served through a model gateway."""
    lowered = model_name.lower()
    return any(lowered.startswith(r) for r in _REASONING_PARAM_ROUTES)


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
    if not any(f in lowered for f in _JSON_OBJECT_ONLY_MODEL_FAMILIES):
        return {}
    if not _is_gateway_route(lowered):
        return {"thinking": {"type": "enabled" if enabled else "disabled"}}
    reasoning: dict[str, Any] = {"enabled": enabled}
    if enabled:
        reasoning["effort"] = _REASONING_EFFORT
    return {"reasoning": reasoning, "provider": dict(_GATEWAY_PROVIDER)}


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

    Empty for models without a thinking mode, and when thinking is disabled
    for the call.

    Args:
        model_name: Model name in litellm format.
        enabled: Whether thinking mode is requested for this call.

    Returns:
        ``{"reasoning_effort": "high"}`` when the tier applies, else ``{}``.
    """
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
    if enable_thinking and deepseek_thinking_extra_body(model_name):
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
