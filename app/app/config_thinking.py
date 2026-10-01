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

from co_scientist.llm import deepseek_thinking_extra_body as _thinking_body
from co_scientist.llm import model_reasons as _model_reasons
from co_scientist.llm import reasoning_effort_args as _effort_args


def _is_deepseek(model_name: str) -> bool:
    """Whether this model reasons, and so needs the floors below.

    Asks the engine rather than matching a family substring. The two are
    no longer the same question: the deployed model is not DeepSeek and
    does not reason, while the models behind it in the fallback chain do,
    and a substring test would have answered "no" for all three -- lifting
    no budget and no deadline for the two that need both.

    The name is kept because ``app.config`` re-exports it and the floors
    below read as a pair with it.
    """
    reasons: bool = _model_reasons(model_name)
    return reasons


def deepseek_non_thinking_extra_body(model_name: str) -> dict[str, Any]:
    """Return an ``extra_body`` that disables DeepSeek V4 thinking mode.

    Currently has no caller: title generation was the one app call site
    that opted out (a 3-6 word extraction whose ``max_tokens=24`` a
    reasoning spend would have consumed entirely), and it now thinks like
    every other call site -- see ``deepseek_thinking_kwargs``. Kept as a
    tested seam rather than deleted, the same way the engine keeps its own
    ``enable_thinking=False`` disable knob at the top of the budget-
    escalation ladder (``llm/tools/iteration.py``) even though most calls
    never take that rung: a future call site sized for a small, fixed
    extraction where a reasoning spend would blow the budget can opt out
    without re-deriving this shape. ``test_config_thinking.py`` pins both
    this and ``deepseek_thinking_kwargs`` against the same engine helper
    (``deepseek_thinking_extra_body``) so the enable/disable shapes stay in
    step with each other and with the route. Non-DeepSeek models get an
    empty dict.

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


CONVERSATIONAL_REASONING_EFFORT = "medium"
"""Reasoning tier for the interview and post-run chat turns.

These are scoping conversations, not the science: they gate which fields
the run starts with, not what the run itself concludes. The engine's own
nodes keep ``_REASONING_EFFORT``'s "high" floor unchanged -- this is a
per-surface override, passed explicitly by the two call sites that want
it, not a change to that floor or to any other app call site (titling and
the session announcement stay on the provider default this module
requests). A cheaper deliberation also shortens the tail of chains of
thought long enough to spend the whole answer budget -- see
``thinking_off_kwargs`` for the retry once one does anyway.
"""


def deepseek_thinking_kwargs(
    model_name: str, *, effort: str | None = None
) -> dict[str, Any]:
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
    the fix lands.

    Which of the two shapes carries the tier is the engine's decision, not
    a rule restated here: a gateway route states it inside its own
    ``reasoning`` object, and a top-level ``reasoning_effort`` beside that
    is the copy litellm refuses outright for a model its OpenRouter support
    map does not list. Engine calls survive such a refusal because they all
    pass ``drop_params``; these app call sites reach litellm directly and do
    not, so the redundant field failed the contextual safety screen and
    parked runs for human review. Spread into a completion call
    (``**deepseek_thinking_kwargs``). Used by every app call site that
    reaches a model directly and streams: interview, Q&A, session
    announcement, and titling. Safety and claim verification used to be on
    this list too; both now route through the engine's ``call_llm_json``
    seam, which applies its own thinking kwargs and floor, so they no
    longer call ``litellm`` directly at all. Non-DeepSeek models get an
    empty dict.

    Args:
        model_name: Model name in litellm format.
        effort: Override the reasoning tier this call requests (e.g.
            ``CONVERSATIONAL_REASONING_EFFORT``). None keeps the engine's
            own "high" floor. A native DeepSeek route aliases anything
            below "high" back onto it, so the override only changes
            behavior on a route whose gateway respects a lower tier.

    Returns:
        ``extra_body`` in the shape this model's route understands, plus
        the reasoning tier; ``{}`` for a model with no thinking mode.
    """
    extra_body = _thinking_body(model_name, enabled=True)
    if not extra_body:
        return {}
    effort_args: dict[str, Any] = _effort_args(model_name, enabled=True)
    kwargs: dict[str, Any] = {"extra_body": extra_body, **effort_args}
    if effort is not None:
        _set_reasoning_effort(kwargs, effort)
    return kwargs


def _set_reasoning_effort(kwargs: dict[str, Any], effort: str) -> None:
    """Overwrite the reasoning tier in ``kwargs``, wherever it landed.

    ``deepseek_thinking_kwargs`` builds one of two shapes: a top-level
    ``reasoning_effort`` string (a direct, non-gateway route) or a nested
    ``extra_body["reasoning"]["effort"]`` (a gateway route, or DeepSeek
    reached through one). Mutates in place since the caller already owns
    a fresh dict for this call.
    """
    if "reasoning_effort" in kwargs:
        kwargs["reasoning_effort"] = effort
    reasoning = kwargs.get("extra_body", {}).get("reasoning")
    if isinstance(reasoning, dict) and "effort" in reasoning:
        reasoning["effort"] = effort


def thinking_off_kwargs(model_name: str) -> dict[str, Any]:
    """Kwargs disabling this model's thinking mode for one call.

    The rung a thinking-only turn is retried at: a streamed turn that
    reasoned and then wrote no answer at all is retried once with thinking
    off, mirroring the engine's own non-streaming ladder for
    ``LLMThinkingOnlyError`` (``llm.attempts.escalation.BudgetEscalation``)
    without reimplementing it -- these app call sites make one request, not a
    ladder of them, so one retry at this rung is the whole mechanism they
    need.

    Args:
        model_name: Model name in litellm format.

    Returns:
        ``{"extra_body": ...}`` carrying this model's disable knob, or
        ``{}`` for a model with no thinking mode.
    """
    extra_body = deepseek_non_thinking_extra_body(model_name)
    return {"extra_body": extra_body} if extra_body else {}


THINKING_FLOOR_MAX_TOKENS = 18_000
"""Smallest total budget an app-side thinking call may be sent with.

The provider counts reasoning against ``max_tokens`` alongside the answer,
so a budget sized for the answer alone lets a long chain of thought consume
the whole allowance: the call returns ``finish_reason="length"`` with empty
content, is billed in full, and is retried. The engine hit exactly this on
every node whose budget predated thinking being switched on
(``co_scientist.constants.THINKING_FLOOR_MAX_TOKENS``, which this mirrors);
the app's *streaming* calls bypass that layer by invoking
``litellm.acompletion`` directly, so they need the floor applied at their
own call sites. A one-shot call that parses JSON belongs on the engine's
``call_llm_json`` seam instead (see ``safety/semantic.py`` and
``claims/verifier.py``), which applies this same floor on its own -- these
functions are for the call sites that must stream and so cannot use it.

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
for the length of it. The interview, the post-run Q&A chat, and the session
announcement all relay their chain of thought to the scientist as it
arrives (``qa_stream.stream_llm_deltas`` yields ``reasoning`` fragments the
same way ``run_start_announcement`` does), so a stalled provider is caught
by the stall timeout long before this floor matters and a long reasoning
pass reads as visible progress rather than a quiet chat. Titling is the
one call with nobody watching at all -- it runs after the create response,
as a background task (``runs.crud._populate_run_title``), so a four-minute
floor costs nothing a caller can see. Before applying this floor to
another call site, check whether it streams to a live reader or runs
unwatched in the background -- a blocking request that shows the caller
nothing until it returns needs a different answer than a bigger number
here.
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
