"""DeepSeek thinking-mode request shaping and its token/timeout floors.

Split out of ``app.config`` to keep that module within the size cap.
Holds the DeepSeek-detection helper, the ``extra_body``/``reasoning_effort``
builders that switch DeepSeek V4 thinking on or off for a call, and the
paired token-budget/timeout floors those calls must be sent with so a long
chain of thought never exhausts ``max_tokens`` before the answer is
written. Every name is re-exported from ``app.config``, so callers and
``test_config_thinking.py``'s imports are unaffected.
"""

from __future__ import annotations

from typing import Any

from co_scientist.llm_request import (
    deepseek_thinking_extra_body as _thinking_body,
)


def _is_deepseek(model_name: str) -> bool:
    """Whether ``model_name`` targets a DeepSeek model (thinking-capable)."""
    return "deepseek" in model_name.lower()


def deepseek_non_thinking_extra_body(model_name: str) -> dict[str, Any]:
    """Return an ``extra_body`` that disables DeepSeek V4 thinking mode.

    Used by one call site: title generation, a 3-6 word extraction whose
    ``max_tokens=24`` a reasoning spend would consume entirely, returning an
    empty completion and leaving the run untitled. That coupling runs both
    ways -- a non-thinking call spends its whole budget on the answer, so
    opting any call site in or out of thinking means revisiting its
    ``max_tokens`` in the same edit. Every other app call uses the thinking
    variant below. Non-DeepSeek models get an empty dict.

    Args:
        model_name: Model name in litellm format.

    Returns:
        The disable knob this model's route understands, or ``{}`` for a
        model with no thinking mode. The engine picks the shape: a gateway
        normalizes reasoning into its own parameter, and DeepSeek's native
        one sent through OpenRouter enables thinking instead of disabling.
    """
    # Annotated because this project's mypy treats engine symbols as Any.
    knob: dict[str, Any] = _thinking_body(model_name, enabled=False)
    return knob


def deepseek_thinking_kwargs(model_name: str) -> dict[str, Any]:
    """Build litellm kwargs enabling DeepSeek V4 thinking at low effort.

    DeepSeek V4 (pro/flash) return chain-of-thought separately as
    ``reasoning_content`` and never fold it into ``content``, so structured
    parsing survives as long as ``max_tokens`` leaves room for the answer
    after the reasoning spend. Call sites do not size for that themselves --
    the interview and claim-verifier budgets were answer-sized and had to be
    lifted -- so pass the budget through ``thinking_safe_max_tokens`` below
    wherever these kwargs are spread. ``reasoning_effort='high'`` is the
    *floor*, not a high setting:
    DeepSeek implements only ``high`` and ``max`` and accepts OpenAI's lower
    names as aliases onto ``high``, so there is no cheaper tier than this
    short of switching thinking off. It is also DeepSeek's own default once
    thinking is enabled, which makes the field belt-and-braces rather than
    load-bearing -- litellm 1.80.x drops ``reasoning_effort`` from the
    request body entirely (BerriAI/litellm#27439), and because the value
    matches the provider default that bug changes nothing here. Sending it
    anyway means the intent is recorded and the call is already correct when
    the fix lands. Spread into a completion call
    (``**deepseek_thinking_kwargs``). Used by every app call except titling:
    interview, Q&A, safety, and claim verification. Non-DeepSeek models get
    an empty dict.

    Args:
        model_name: Model name in litellm format.

    Returns:
        ``extra_body`` in the shape this model's route understands, plus
        the reasoning tier; ``{}`` for a model with no thinking mode.
    """
    extra_body = _thinking_body(model_name, enabled=True)
    if not extra_body:
        return {}
    return {"extra_body": extra_body, "reasoning_effort": "high"}


THINKING_FLOOR_MAX_TOKENS = 18_000
"""Smallest total budget an app-side thinking call may be sent with.

The provider counts reasoning against ``max_tokens`` alongside the answer,
so a budget sized for the answer alone lets a long chain of thought consume
the whole allowance: the call returns ``finish_reason="length"`` with empty
content, is billed in full, and is retried. The engine hit exactly this on
every node whose budget predated thinking being switched on
(``co_scientist.constants.THINKING_FLOOR_MAX_TOKENS``, which this mirrors);
the app's calls bypass that layer by invoking ``litellm.acompletion``
directly, so they need the floor applied at their own call sites.

A ceiling is not a spend -- raising it costs nothing on calls that answer
briefly, and only removes the failure mode on the ones that reason at
length.
"""


def thinking_safe_max_tokens(model_name: str, answer_tokens: int) -> int:
    """Return a ``max_tokens`` that leaves room to reason and then answer.

    Args:
        model_name: Model name in litellm format.
        answer_tokens: Budget the call site wants for the answer itself.

    Returns:
        ``answer_tokens`` for models without a thinking mode, else at least
        ``THINKING_FLOOR_MAX_TOKENS``. Only ever raises, so a call site that
        already asked for more keeps its own number.
    """
    if not _is_deepseek(model_name):
        return answer_tokens
    return max(answer_tokens, THINKING_FLOOR_MAX_TOKENS)


THINKING_FLOOR_TIMEOUT_SECONDS = 240.0
"""Smallest wall clock an app-side thinking call may be given.

The token budget and the clock are one setting in two places: funding a
chain of thought without extending the deadline just moves the failure from
a truncated answer to an abandoned one, and both land in the same silent
fallback. ``THINKING_FLOOR_MAX_TOKENS`` admits 18k tokens, so the clock has
to admit 18k tokens arriving -- 240s is that budget at a deliberately
pessimistic 75 tok/s, well under what the provider sustains in practice.

A long deadline is only acceptable where nobody is watching a blank screen
for the length of it. The safety and claim-verifier calls are background
durable tasks, and the interview relays its chain of thought to the
scientist as it arrives. Q&A is the weak case: it streams, so a stalled
provider is still caught quickly, but it forwards only answer deltas, so a
long reasoning pass does read as a quiet chat. Before applying this floor
to another call site, check which of those three it is -- a blocking
request that shows the caller nothing until it returns needs a different
answer than a bigger number here.
"""


def thinking_safe_timeout(model_name: str, answer_seconds: float) -> float:
    """Return a timeout that lets a funded chain of thought finish arriving.

    Args:
        model_name: Model name in litellm format.
        answer_seconds: Deadline the call site wants for the answer itself.

    Returns:
        ``answer_seconds`` for models without a thinking mode, else at least
        ``THINKING_FLOOR_TIMEOUT_SECONDS``. Only ever raises, so a call site
        that already allowed more keeps its own number.
    """
    if not _is_deepseek(model_name):
        return answer_seconds
    return max(answer_seconds, THINKING_FLOOR_TIMEOUT_SECONDS)
