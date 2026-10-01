"""Gateway ``extra_body`` construction for LiteLLM completion calls.

Split from ``llm.request.thinking`` on the same grounds that module was
split from ``llm.request.completion``: this holds the functions that build
the actual ``extra_body``/``reasoning`` payload a call carries from a model's
profile (``llm.profile``) -- distinct from ``llm.request.thinking``'s own
concern of deciding *whether* a call will effectively reason and what budget
that funds.
"""

import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any, Final

from co_scientist.constants import MINIMAL_REASONING_MAX_TOKENS
from co_scientist.llm.profile import ModelProfile, Thinking, model_profile
from co_scientist.llm.request.gateway_routing import _gateway_provider

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
    of the reasoning spend -- ``app.claim_verifier``'s entailment judge is
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
