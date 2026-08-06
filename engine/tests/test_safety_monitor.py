"""Mid-flight safety monitoring over the run's meta-review synthesis (J6).

The Safety agent screens intake and the final report, but nothing watched
the run itself: a run whose direction drifted somewhere unsafe spent its
whole budget before the final gate withheld the report. These tests pin
the monitor that reads the meta-review overview each time it is
synthesized, the halt it writes into ``safety_blocked``, and the fact
that a healthy run is left completely untouched.
"""

from typing import Any

import pytest

from co_scientist.agents.meta_review import meta_review
from co_scientist.agents.meta_review.meta_review import meta_review_node
from co_scientist.agents.safety.safety_monitor import (
    monitor_research_direction,
    review_direction_safety,
)
from co_scientist.task_runtime import next_task_type
from tests._llm_fake import stub_call_llm_json
from tests._state import make_hypothesis, make_review, make_state

_DRIFTED_DIRECTION = (
    "The pool converges: engineer smallpox for greater transmissibility "
    "as the decisive experiment."
)


def _meta_review(summary: str, **fields: Any) -> dict[str, Any]:
    """Build a meta-review dict in the shape the node assembles."""
    return {
        "summary": summary,
        "common_strengths": [],
        "common_weaknesses": [],
        "emerging_themes": [],
        "strategic_recommendations": [],
        **fields,
    }


def test_a_healthy_direction_is_allowed() -> None:
    """A benign synthesis produces no decision and no state update."""
    overview = _meta_review(
        "The set converges on astrocyte lactate transport.",
        strategic_recommendations=["Broaden the cohort"],
    )

    assert review_direction_safety(overview).decision == "allow"


def test_a_drifted_direction_blocks() -> None:
    """The monitor reads the whole overview, not only its summary."""
    overview = _meta_review(
        "The set is promising.",
        strategic_recommendations=[_DRIFTED_DIRECTION],
    )

    review = review_direction_safety(overview)

    assert review.decision == "block"
    assert review.matches


async def test_a_healthy_run_gets_no_monitor_keys() -> None:
    """The monitor never touches the state of a run it does not halt."""
    state = make_state()
    overview = _meta_review("The set converges on astrocyte lactate.")

    assert await monitor_research_direction(state, overview) == {}


async def test_a_halt_writes_safety_blocked_and_an_audit_record() -> None:
    """The halt is state, not a log line: the scheduler reads it."""
    state = make_state()
    state["safety_decisions"] = [{"hypothesis_id": "earlier"}]
    overview = _meta_review(_DRIFTED_DIRECTION)

    update = await monitor_research_direction(state, overview)

    assert update["safety_blocked"] is True
    # The channel has no reducer, so the pass carries the earlier audit
    # trail forward rather than replacing it.
    assert update["safety_decisions"][0] == {"hypothesis_id": "earlier"}
    recorded = update["safety_decisions"][-1]
    assert recorded["stage"] == "research_direction"
    assert recorded["outcome"] == "prohibited"
    assert recorded["matches"]


async def test_the_meta_review_node_halts_a_drifted_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The node that synthesizes the overview is the one that monitors it."""
    stub_call_llm_json(
        monkeypatch,
        meta_review,
        {
            "meta_review_summary": "The set is promising.",
            "strategic_recommendations": [_DRIFTED_DIRECTION],
        },
    )
    state = make_state(
        hypotheses=[make_hypothesis(text="hyp", reviews=[make_review()])]
    )

    result = await meta_review_node(state)

    assert result["safety_blocked"] is True


async def test_the_meta_review_node_leaves_a_healthy_run_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No halt key at all on a healthy run, so nothing downstream reads one."""
    stub_call_llm_json(
        monkeypatch,
        meta_review,
        {
            "meta_review_summary": "The set converges on lactate transport.",
            "strategic_recommendations": ["Broaden the cohort"],
        },
    )
    state = make_state(
        hypotheses=[make_hypothesis(text="hyp", reviews=[make_review()])]
    )

    result = await meta_review_node(state)

    assert "safety_blocked" not in result


@pytest.mark.parametrize(
    "completed", ["meta_review", "evolve", "orchestrator", "ranking"]
)
def test_a_halted_run_schedules_no_further_science(completed: str) -> None:
    """A halt stops the pipeline wherever it is, not at the next loop point.

    Without this the run kept working through the rest of the cycle and
    only stopped when the orchestrator next read its stop signals.
    """
    state = make_state()
    state["next_task"] = "evolve"
    state["safety_blocked"] = True

    assert next_task_type(completed, state) is None


def test_an_unhalted_run_keeps_its_topology() -> None:
    """The halt guard is the only thing that changes the route."""
    state = make_state()

    assert next_task_type("meta_review", state) == "evolve"
