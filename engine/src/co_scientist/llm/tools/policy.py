"""Two policies the tool loop applies around its iterations.

Split out of ``llm.tools.loop`` for length, and re-exported there so the
names keep their original module namespace -- tests patch them on the
loop, and a split that silently moves a monkeypatch seam breaks suites
that still pass.

Both are about what the loop does *besides* calling the model: warning it
before its budget runs out, and refusing to cache a transcript that cannot
be honestly replayed.

The budget has two ceilings because an iteration count alone does not
bound cost. Every turn re-sends the whole transcript, so turn N costs
more than turn N-1 and total spend grows with the square of the turn
count -- a loop allowed 14 turns can cost three times one that finished
in 9, not 1.5 times. Measured on a live extended run: nine comprehensive
reflection items reached the 14-turn ceiling and between them re-sent
1.81M prompt tokens, 44% of that phase and 24% of the whole run's input,
and by definition produced no observation, since reaching the ceiling is
what "the loop failed" means. The token ceiling is what makes the cost of
a loop quotable before it starts, the same property ``research.budget``
exists to give the research descent.
"""

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from co_scientist.llm.values import LLMCallOptions
from co_scientist.tool_effects import is_local_tool

if TYPE_CHECKING:
    from co_scientist.llm.tools.loop import ToolLoop

logger = logging.getLogger(__name__)


# A hard cap alone produces truncated, wasted work: the model spends its
# last iteration mid-investigation and the loop raises on top of it. Warning
# it while it still has room converts the stop into a handoff -- it can state
# what it has rather than being cut off. Injected as a *user* turn because a
# system message mid-conversation is ignored by several providers, and as a
# fraction rather than a fixed count so it scales with the caller's budget.
_HANDOFF_FRACTION = 0.8

# Below this, 80% lands on iteration 1 or 2 and the warning arrives before
# the model has done anything worth wrapping up.
_MIN_ITERATIONS_FOR_HANDOFF = 4

# Prompt tokens one loop may re-send across all its turns, summed the way
# a bill is: a turn's whole transcript, every turn.
#
# This default is a backstop, not a tuned figure, and is deliberately
# loose: it exists to catch a loop that has stopped converging, and every
# caller whose spend has actually been measured should pass its own. On
# the run above, the two most expensive generation items alone re-sent
# 1.30M and 0.73M prompt tokens -- 27% of the whole run's input in two
# work items -- which is the shape this catches. Tightening it toward
# what a *reflection* loop costs would silently shorten drafting loops
# whose spend nobody has measured, so the number that matters lives at
# the call site (see ``simulation_execution.SIMULATION_TOKEN_BUDGET``).
DEFAULT_TOOL_LOOP_TOKEN_BUDGET = 300_000

# Divisor turning transcript characters into an approximate token count.
# Deliberately local: asking the provider would mean plumbing usage back
# out of every iteration to enforce a ceiling that only needs to be
# roughly right, and a budget this size does not turn on a few percent.
_CHARS_PER_TOKEN = 4


def transcript_tokens(messages: list[dict[str, Any]]) -> int:
    """Approximates what re-sending this transcript costs in tokens.

    Args:
        messages: The conversation as the loop will next send it.

    Returns:
        An estimate in tokens, from total content length. Tool calls
        carried on an assistant message are counted through their
        serialized form, since the provider bills for those too.
    """
    chars = 0
    for message in messages:
        chars += len(str(message.get("content") or ""))
        calls = message.get("tool_calls")
        if calls:
            chars += len(str(calls))
    return chars // _CHARS_PER_TOKEN


def _handoff_iteration(max_iterations: int) -> int:
    """Returns the 0-based iteration to warn on, or -1 to never warn."""
    if max_iterations < _MIN_ITERATIONS_FOR_HANDOFF:
        return -1
    return int(max_iterations * _HANDOFF_FRACTION)


def _handoff_spend(max_prompt_tokens: int) -> int:
    """Returns the cumulative spend at which to warn, in prompt tokens."""
    return int(max_prompt_tokens * _HANDOFF_FRACTION)


def _turns_remaining(
    iteration: int, spent: int, loop: "ToolLoop", messages: list[dict[str, Any]]
) -> int:
    """How many more turns this loop can actually afford, both ceilings.

    The turn ceiling alone overstates it whenever spend is the binding
    constraint, and the wrap-up message is a promise about how much room
    is left: telling a model eleven turns remain when the budget affords
    two is how a loop ends mid-step having been warned. So the spend
    ceiling is converted into turns at the transcript's current size --
    the next turn costs at least what this one did, growing -- and the
    smaller of the two is what the model is told.

    Args:
        iteration: The 0-based turn about to run.
        spent: Prompt tokens re-sent so far, this turn included.
        loop: The loop carrying both ceilings.
        messages: The conversation as it will next be sent.

    Returns:
        Turns remaining, never below one -- the turn being warned on is
        itself still available.
    """
    by_turns = loop.max_iterations - iteration
    per_turn = max(transcript_tokens(messages), 1)
    by_spend = (loop.max_prompt_tokens - spent) // per_turn
    return max(1, min(by_turns, by_spend))


def _handoff_message(remaining: int) -> dict[str, Any]:
    """Builds the one-shot wrap-up turn injected near the loop's bound."""
    return {
        "role": "user",
        "content": (
            f"You have {remaining} tool-calling turn(s) left before this "
            "task is stopped. Stop opening new lines of investigation. "
            "Use any remaining turns to finish what is in progress, then "
            "give your final answer, reporting what you established and "
            "what remains uncertain. A partial answer that says what is "
            "missing is far more useful than being cut off mid-step."
        ),
    }


def closing_message() -> dict[str, Any]:
    """The turn that ends a loop, asking for the answer and nothing else.

    Stripping the tools is not on its own enough. Sent the transcript as
    it stands, a model mid-investigation carries on narrating it: the
    first closing turn measured came back with "let me check one more
    detail... I'll quickly verify a couple of points", which is a
    sentence about work it can no longer do rather than a report of the
    work it did. So the closing turn says the tools are gone, that this
    is the last turn, and that describing a next step is not an answer.
    """
    return {
        "role": "user",
        "content": (
            "Your tools are no longer available and this is your final"
            " turn. Do not describe what you would do next and do not"
            " propose further steps -- neither is possible now. Write"
            " your answer from what you have already established:"
            " what you did, the actual numbers you saw, what they imply,"
            " and what is still uncertain because you ran out of room."
        ),
    }


def _contains_local_tool(tools: list[dict[str, Any]]) -> bool:
    """Reports whether any offered tool acts on this machine."""
    return any(
        is_local_tool(schema.get("function", {}).get("name", ""))
        for schema in tools
    )


def _guard_cache_for_local_tools(
    loop: "ToolLoop", options: LLMCallOptions
) -> LLMCallOptions:
    """Disables caching for any loop that can execute local tools.

    A cached tool-loop entry replays the whole transcript, tool results
    included. That is sound while every tool is a literature lookup, whose
    answer does not depend on this machine. It is not sound for a tool
    that ran a command in a workspace: the replay would hand the model
    output from a *different* run's directory as though it had just
    executed there, and the failure is invisible -- plausible output,
    correct shape, describing files that do not exist.

    Enforced here rather than trusted to each call site, because the cost
    of forgetting is fabricated evidence rather than a crash, and the loss
    from being wrong in this direction is only a cache miss.

    Args:
        loop: The tool set offered to the model.
        options: The caller's cache and telemetry choices.

    Returns:
        ``options``, or a copy with caching disabled.
    """
    if not options.use_cache or not _contains_local_tool(loop.tools):
        return options
    logger.debug(
        "disabling the tool-loop cache: local tools cannot be replayed"
    )
    return replace(options, use_cache=False)
