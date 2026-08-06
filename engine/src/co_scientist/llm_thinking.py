"""Thinking/reasoning-mode argument shaping for LiteLLM completion calls.

Split from ``co_scientist.llm_request``: selects the thinking knob
(DeepSeek's native ``thinking`` object), the reasoning tier, and the
``max_tokens`` floor a thinking call needs. Every name here is re-exported
from ``co_scientist.llm_request`` so that module's namespace is unchanged.
"""

import logging
from typing import Any

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
        ``{"thinking": {"type": "enabled"|"disabled"}}`` for DeepSeek models,
        else ``{}``.
    """
    lowered = model_name.lower()
    if any(family in lowered for family in _JSON_OBJECT_ONLY_MODEL_FAMILIES):
        return {"thinking": {"type": "enabled" if enabled else "disabled"}}
    return {}


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

    if enable_thinking:
        completion_args["max_tokens"] = max(
            completion_args["max_tokens"], THINKING_FLOOR_MAX_TOKENS
        )
