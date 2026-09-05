"""Thinking/reasoning-mode argument shaping for LiteLLM completion calls.

Split from ``co_scientist.llm_request``: selects the thinking knob
(DeepSeek's native ``thinking`` object), the reasoning tier, and the
``max_tokens`` floor a thinking call needs. Every name here is re-exported
from ``co_scientist.llm_request`` so that module's namespace is unchanged.
"""

import logging
from typing import Any, Final

from co_scientist.constants import THINKING_FLOOR_MAX_TOKENS
from co_scientist.llm_gateway_routing import (
    _DEFAULT_UPSTREAM_ORDER as _DEFAULT_UPSTREAM_ORDER,
)
from co_scientist.llm_gateway_routing import (
    _GATEWAY_MODELS as _GATEWAY_MODELS,
)
from co_scientist.llm_gateway_routing import (
    _GATEWAY_PROVIDER as _GATEWAY_PROVIDER,
)
from co_scientist.llm_gateway_routing import (
    _MAX_PRICE_MULTIPLE as _MAX_PRICE_MULTIPLE,
)
from co_scientist.llm_gateway_routing import (
    _MIN_THROUGHPUT_TOKENS_PER_SEC as _MIN_THROUGHPUT_TOKENS_PER_SEC,
)
from co_scientist.llm_gateway_routing import (
    _UPSTREAM_ORDER_ENV as _UPSTREAM_ORDER_ENV,
)
from co_scientist.llm_gateway_routing import (
    GatewayModel as GatewayModel,
)
from co_scientist.llm_gateway_routing import (
    _gateway_provider as _gateway_provider,
)
from co_scientist.llm_gateway_routing import (
    _upstream_order as _upstream_order,
)

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
# The free gateway models (``z-ai/glm-5.2:free`` and its fallback chain)
# don't need an entry here: litellm's own registry already reports no
# response-schema support for them, so ``_supports_json_schema_response_format``
# downgrades them via that path, not this family list. If a future model
# in the chain fails that check the other way (registry says yes, host
# says no -- a hard 404 paired with ``require_parameters``, not a soft
# degradation), add it here rather than assuming the registry is right.
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


def _is_gateway_route(model_name: str) -> bool:
    """Whether this route is served through a model gateway."""
    lowered = model_name.lower()
    return any(lowered.startswith(r) for r in _REASONING_PARAM_ROUTES)


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
