"""Which mature-review tasks the durable path enqueues.

The durable fan-out is the path production runs, and it used to carry its
own copy of the maturity rule. Both copies re-issued a simulation review
that had already succeeded whenever the full review had not -- so fixing
only the engine's copy would have left the cost exactly where it was
being paid.
"""

from __future__ import annotations

from typing import Any

from co_scientist.models import Hypothesis

from app.engine_tasks_fanout import _maturity_specs


def _hypothesis(**enrichments: Any) -> Hypothesis:
    """An engine hypothesis carrying the given stored reviews."""
    hypothesis = Hypothesis(id="h1", text="a mechanism")
    hypothesis.enrichments.update(enrichments)
    return hypothesis


def test_a_fresh_hypothesis_is_owed_both() -> None:
    assert _maturity_specs(_hypothesis(), 0) == [
        ("h1", "full"),
        ("h1", "simulation"),
    ]


def test_a_succeeded_simulation_is_not_re_enqueued() -> None:
    """One firing of the tool loop per hypothesis, not one per iteration.

    The task's idempotency key carries the checkpoint sequence, so a
    later iteration is a genuinely new row rather than a no-op collision:
    the work really did run again, on the tier where that work is a tool
    loop.
    """
    hypothesis = _hypothesis(simulation={"verdict": "breaks_down"})

    for iteration in (0, 1, 2):
        assert _maturity_specs(hypothesis, iteration) == [("h1", "full")]


def test_a_mature_hypothesis_gets_its_recurrent_review() -> None:
    assert _maturity_specs(_hypothesis(full={"verdict": "sound"}), 1) == [
        ("h1", "recurrent")
    ]
