"""Tests for how the token budgets in ``constants`` relate to the floor.

``_apply_thinking_args`` raises any reasoning call's ``max_tokens`` to
``THINKING_FLOOR_MAX_TOKENS``, so a constant's value only describes the
request that goes out if it clears the floor. These pin the relationship
rather than the numbers: a budget below the floor must be a *base* (an
answer budget the floor is meant to replace), and every ``*_CAP`` must be
above it (a ceiling that means the same thing whether or not the model
reasons).

The point is the next constant somebody adds, not the ones here today --
which is why the cap check discovers its subjects from the module rather
than listing them.
"""

from co_scientist import constants
from co_scientist.constants import THINKING_FLOOR_MAX_TOKENS


def _declared_caps() -> dict[str, int]:
    """Every ``*_MAX_TOKENS_CAP`` constant, found by name not by list."""
    return {
        name: value
        for name, value in vars(constants).items()
        if name.endswith("_MAX_TOKENS_CAP")
        and not name.startswith("_")
        and isinstance(value, int)
    }


def test_every_scaled_cap_clears_the_thinking_floor() -> None:
    """No cap may sit below the floor, because such a cap says two things.

    Reasoning is billed against ``max_tokens`` alongside the answer, so
    ``_apply_thinking_args`` lifts every thinking call to the floor. A cap
    beneath it is therefore overwritten on the DeepSeek-family models this
    engine deploys on, and enforced as written on a provider with no
    thinking mode -- one constant, two different ceilings, and the one that
    is silently discarded is the one production uses.

    ``DRAFT_MAX_TOKENS_CAP`` was that cap at 16000, discovered only by
    reading the arithmetic. Asserted over every cap the module declares so
    the next one is discovered by a failing test instead.
    """
    caps = _declared_caps()

    assert caps, "no *_MAX_TOKENS_CAP constants found; did they get renamed?"
    below = {
        name: value
        for name, value in caps.items()
        if value <= THINKING_FLOOR_MAX_TOKENS
    }
    assert not below, (
        f"caps at or below THINKING_FLOOR_MAX_TOKENS "
        f"({THINKING_FLOOR_MAX_TOKENS}): {below}. A cap under the floor is "
        "overwritten wherever the model reasons; raise it above the floor or "
        "delete it."
    )


def test_the_floor_is_the_thinking_budget_under_another_name() -> None:
    """The two names are one derived number, not two tuned ones.

    ``THINKING_FLOOR_MAX_TOKENS`` is the budget the nodes sized for thinking
    from the start already run against, which is the whole argument for
    raising every other thinking call to it: it asks for nothing this
    deployment has not already proven. Splitting the values would quietly
    retire that argument, so the tie is asserted rather than left implicit.
    """
    assert THINKING_FLOOR_MAX_TOKENS == constants.THINKING_MAX_TOKENS


def test_base_budgets_below_the_floor_are_the_designed_case() -> None:
    """A base under the floor is the floor working, not a defect.

    The counterpart to the cap rule, kept next to it so the two are read
    together: bases describe what a call's answer costs and are *meant* to
    be superseded, caps describe a ceiling and must not be. Without this,
    "every budget must clear the floor" is the obvious over-correction, and
    it would mean sending 18000 to a literature-review query call that
    answers in a few hundred tokens on a provider that never reasons.
    """
    for base in (
        constants.DEFAULT_MAX_TOKENS,
        constants.EXTENDED_MAX_TOKENS,
        constants.LONG_MAX_TOKENS,
    ):
        assert base < THINKING_FLOOR_MAX_TOKENS


def test_the_draft_budget_never_reaches_its_own_cap() -> None:
    """The draft cap is a runaway backstop, not a ceiling runs meet.

    The base dominates the sum at every count a run tier can ask for, so
    the cap's value is free to be chosen for coherence with the floor and
    its sibling caps rather than tuned. Pinned because that freedom is
    exactly what stops holding if per-hypothesis pricing is ever raised.

    The count is the largest tier's ``initial_hypotheses_count`` (ultra, in
    the app's ``run_modes.RUN_TIER_DEFAULTS``), restated rather than
    imported because the engine is a library that knows nothing about the
    app's tiers. It is also generous: the coordinator routes only about half
    of a batch to the tool-based path, so a real draft call asks for fewer.
    """
    largest_tier_count = 16
    budget = constants.scaled_max_tokens(
        constants.DEEP_HYPOTHESIS_MAX_TOKENS,
        largest_tier_count,
        per_item=constants.DRAFT_TOKENS_PER_HYPOTHESIS,
        cap=constants.DRAFT_MAX_TOKENS_CAP,
    )

    assert budget < constants.DRAFT_MAX_TOKENS_CAP
    assert budget < THINKING_FLOOR_MAX_TOKENS


def test_deep_hypothesis_budget_is_a_base_below_the_floor() -> None:
    """The K6 generation budget funds the answer; the floor funds thinking.

    ``DEEP_HYPOTHESIS_MAX_TOKENS`` raised the generation family's answer
    budget above ``EXTENDED_MAX_TOKENS`` without becoming a ceiling on a
    thinking model: it must stay below the floor so ``_apply_thinking_args``
    still replaces it there, exactly like the other answer bases, while
    non-thinking providers honor the larger answer allowance.
    """
    assert constants.EXTENDED_MAX_TOKENS < constants.DEEP_HYPOTHESIS_MAX_TOKENS
    assert constants.DEEP_HYPOTHESIS_MAX_TOKENS < THINKING_FLOOR_MAX_TOKENS


def test_research_overview_budget_clears_the_floor() -> None:
    """The K6 overview budget must bind on thinking models too.

    The overview's depth guidance asks for a multi-paragraph strategy
    document plus an NIH aims page; on a thinking model the chain of
    thought and that answer share one allowance, so a budget at or below
    the floor would leave the answer whatever the reasoning did not spend.
    The budget sits at the largest scaled batch cap already proven in
    production, nowhere beyond it.
    """
    assert THINKING_FLOOR_MAX_TOKENS < constants.RESEARCH_OVERVIEW_MAX_TOKENS
    assert constants.RESEARCH_OVERVIEW_MAX_TOKENS <= (
        constants.REVIEW_BATCH_MAX_TOKENS_CAP
    )
