"""Two policies the tool loop applies around its iterations.

Split out of ``llm_tool_loop`` for length, and re-exported there so the
names keep their original module namespace -- tests patch them on the
loop, and a split that silently moves a monkeypatch seam breaks suites
that still pass.

Both are about what the loop does *besides* calling the model: warning it
before the iteration budget runs out, and refusing to cache a transcript
that cannot be honestly replayed.
"""

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from co_scientist.llm_types import LLMCallOptions
from co_scientist.tool_effects import is_local_tool

if TYPE_CHECKING:
    from co_scientist.llm_tool_loop import ToolLoop

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


def _handoff_iteration(max_iterations: int) -> int:
    """Returns the 0-based iteration to warn on, or -1 to never warn."""
    if max_iterations < _MIN_ITERATIONS_FOR_HANDOFF:
        return -1
    return int(max_iterations * _HANDOFF_FRACTION)


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
