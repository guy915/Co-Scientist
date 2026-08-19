"""Pareto dominance over several objectives.

This is how an objective other than the first one reaches the search.
`fitness` reports one number and can only ever order variants along one
axis; dominance orders them along all of them at once, without needing
the objectives to share a scale.

One variant **dominates** another when it is at least as good on every
objective and strictly better on at least one. The variants nothing
dominates are the **front**: the set of genuinely different trades, none
of which can be improved on one axis without giving something up on
another. That set is what a multi-objective search has to keep breeding
from, because collapsing it to a single winner is precisely the step
that throws away the trade the run was asked to explore.

**A missing objective value is not a bad one.** A variant that reported
accuracy but no latency has no position on the latency axis at all.
Treating None as negative infinity would let any variant dominate it and
quietly drop it from the front; treating None as positive infinity would
let it dominate everything. It is instead excluded from comparison, so a
variant that failed to report an objective can neither dominate nor be
dominated on it.
"""

from collections.abc import Sequence

# One variant's sign-corrected scores, in the spec's declared objective
# order. None marks an objective the variant did not report.
ObjectiveValues = Sequence[float | None]


def dominates(left: ObjectiveValues, right: ObjectiveValues) -> bool:
    """Reports whether ``left`` dominates ``right``.

    Args:
        left: One variant's objective values.
        right: Another's, in the same order.

    Returns:
        True when ``left`` is at least as good on every comparable
        objective and strictly better on at least one.

    An objective either side failed to report is skipped, so a variant
    that reported nothing comparable dominates nothing and is dominated
    by nothing -- it sits outside the ordering rather than at the bottom
    of it.
    """
    strictly_better = False
    for a, b in zip(left, right, strict=False):
        if a is None or b is None:
            continue
        if a < b:
            return False
        if a > b:
            strictly_better = True
    return strictly_better


def pareto_front(values: Sequence[ObjectiveValues]) -> tuple[int, ...]:
    """Finds the indices nothing else dominates.

    Args:
        values: One entry per variant, each the variant's objective
            values in the spec's order.

    Returns:
        The front's indices, ascending. A variant with no comparable
        objective at all is excluded: it is not on the front, it is not
        in the ordering, and reporting it as an optimal trade would put
        a program that measured nothing beside programs that measured
        everything.
    """
    front = []
    for index, candidate in enumerate(values):
        if all(value is None for value in candidate):
            continue
        if not any(
            dominates(other, candidate)
            for position, other in enumerate(values)
            if position != index
        ):
            front.append(index)
    return tuple(front)


def is_multi_objective(values: Sequence[ObjectiveValues]) -> bool:
    """Reports whether more than one objective is in play.

    Used to keep the single-objective case honest: with one objective the
    front is just the joint winners, which is a less useful statement
    than "this is the best", so a surface should say the latter.
    """
    return any(len(candidate) > 1 for candidate in values)
