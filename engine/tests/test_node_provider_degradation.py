"""Terminal-synthesis nodes degrade when the provider cannot be reached.

Production run 49a509b0 completed 146 tasks and then lost every one of
them: the terminal ``research_overview`` task spent its three durable
attempts on a provider that first stalled for 600s twice and then
returned an upstream overload, the run settled ``failed``, and because
``engine.finalize`` is only ever enqueued as that node's ``None``
successor, no report was written at all.

Each of these nodes already has a registered fallback in
``llm_json._ENHANCEMENT_NODE_FALLBACKS``, but only the JSON-parse
exhaustion path serves it -- a provider error or a timeout leaves
``call_llm_json`` by a different door. These tests pin the missing half:
a provider failure degrades the node to its documented empty result and
is recorded in ``degraded_nodes`` so the report can say the section is
blank, while the two errors the durable worker itself answers keep
propagating.
"""

from typing import Any

import pytest
from litellm.exceptions import APIError

from co_scientist.agents.meta_review import meta_review as mr
from co_scientist.agents.meta_review import research_overview as ro
from co_scientist.agents.proximity import proximity as px
from co_scientist.checkpoint import (
    restore_workflow_state,
    serialize_workflow_state,
)
from co_scientist.exceptions import (
    LLMCallBudgetExceededError,
    LLMRateLimitParkError,
    LLMTimeoutError,
)
from co_scientist.scheduling.models import TaskType
from tests._state import make_hypothesis, make_review, make_state

# The two shapes the incident produced, in the order it produced them.
_TIMEOUT = LLMTimeoutError(
    "LLM call to openrouter/minimax/minimax-m3:free exceeded 600.0s"
)
_UPSTREAM = APIError(
    status_code=500,
    message="OpenrouterException - Upstream error from Nvidia: overloaded",
    llm_provider="openrouter",
    model="minimax/minimax-m3:free",
)

# The two the durable worker answers itself -- a park waits for a clock and
# a spent ceiling terminates the run, so neither may be swallowed here.
_CONTROL_FLOW: list[Exception] = [
    LLMCallBudgetExceededError(count=2501, ceiling=2500),
    LLMRateLimitParkError(resume_at=1.0, reason="message_per_day"),
]


def _raiser(error: Exception) -> Any:
    """Return an async stand-in for ``call_llm_json`` that raises ``error``."""

    async def _call(*_: Any, **__: Any) -> dict[str, Any]:
        raise error

    return _call


def _overview_state(**overrides: Any) -> Any:
    """A state whose publishable pool reaches the synthesis call."""
    return make_state(
        hypotheses=[make_hypothesis(text="H", elo_rating=1700)],
        research_goal="g",
        supervisor_model_name="test/model",
        meta_review={},
        articles=[],
        **overrides,
    )


@pytest.mark.parametrize("error", [_TIMEOUT, _UPSTREAM])
async def test_overview_degrades_on_an_unreachable_provider(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """A stalled or failing provider yields the empty overview, not a raise."""
    monkeypatch.setattr(ro, "call_llm_json", _raiser(error))
    state = _overview_state()

    out = await ro.research_overview_node(state)

    assert out["research_overview"] == {}
    assert state["degraded_nodes"] == ["research_overview"]


@pytest.mark.parametrize("error", _CONTROL_FLOW)
async def test_overview_reraises_the_worker_owned_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """A park and a spent call ceiling must still reach the worker."""
    monkeypatch.setattr(ro, "call_llm_json", _raiser(error))

    with pytest.raises(type(error)):
        await ro.research_overview_node(_overview_state())


async def test_interim_overview_failure_is_not_a_degraded_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A periodic firing publishes nothing, so it labels no report section.

    ``degraded_sections`` names a blank section of the finished report.
    The interim firing writes no document -- the terminal one still can --
    so recording it here would tag an overview that came out fine.
    """
    monkeypatch.setattr(ro, "call_llm_json", _raiser(_UPSTREAM))
    state = _overview_state(next_task=TaskType.SYNTHESIZE.value)

    out = await ro.research_overview_node(state)

    assert "interim_overview" not in out
    assert state.get("degraded_nodes", []) == []


def _reviewed_state() -> Any:
    """A state carrying one reviewed hypothesis, so meta-review calls out."""
    hypothesis = make_hypothesis(text="H")
    hypothesis.reviews = [make_review()]
    return make_state(
        hypotheses=[hypothesis],
        research_goal="g",
        supervisor_model_name="test/model",
    )


@pytest.mark.parametrize("error", [_TIMEOUT, _UPSTREAM])
async def test_meta_review_degrades_on_an_unreachable_provider(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """Meta-review falls back to its empty synthesis rather than failing.

    Its summary renders into the report, so the degraded one must not
    borrow the no-reviews branch's wording: this run had its reviews.
    """
    monkeypatch.setattr(mr, "call_llm_json", _raiser(error))
    state = _reviewed_state()

    out = await mr.meta_review_node(state)

    assert out["meta_review"]["summary"] == (
        "Meta-review synthesis was unavailable for this cycle"
    )
    assert out["meta_review"]["strategic_recommendations"] == []
    assert state["degraded_nodes"] == ["meta_review"]


@pytest.mark.parametrize("error", _CONTROL_FLOW)
async def test_meta_review_reraises_the_worker_owned_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """The same two errors keep propagating out of meta-review."""
    monkeypatch.setattr(mr, "call_llm_json", _raiser(error))

    with pytest.raises(type(error)):
        await mr.meta_review_node(_reviewed_state())


def _pair_state() -> Any:
    """Two hypotheses, the minimum proximity needs to cluster anything."""
    return make_state(
        hypotheses=[make_hypothesis(text="A"), make_hypothesis(text="B")],
        research_goal="g",
        model_name="test/model",
    )


@pytest.mark.parametrize("error", [_TIMEOUT, _UPSTREAM])
async def test_proximity_degrades_on_an_unreachable_provider(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """Proximity skips deduplication for the cycle instead of failing."""
    monkeypatch.setattr(px, "call_llm_json", _raiser(error))
    state = _pair_state()

    out = await px.proximity_node(state)

    assert len(out["hypotheses"]) == 2
    assert state["degraded_nodes"] == ["proximity_analysis"]


@pytest.mark.parametrize("error", _CONTROL_FLOW)
async def test_proximity_reraises_the_worker_owned_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """The same two errors keep propagating out of proximity."""
    monkeypatch.setattr(px, "call_llm_json", _raiser(error))

    with pytest.raises(type(error)):
        await px.proximity_node(_pair_state())


# Each node with the state that reaches its LLM call. On the durable path
# the same provider failure goes two ways, decided by whether the task
# running the node still holds a retry: the tests above leave the flag
# unset, which is the graph path and always degrades.
_NODE_CASES = [
    pytest.param(
        ro, ro.research_overview_node, _overview_state, id="research_overview"
    ),
    pytest.param(mr, mr.meta_review_node, _reviewed_state, id="meta_review"),
    pytest.param(px, px.proximity_node, _pair_state, id="proximity"),
]


@pytest.mark.parametrize(("module", "node", "build_state"), _NODE_CASES)
@pytest.mark.parametrize("error", [_TIMEOUT, _UPSTREAM])
async def test_a_provider_failure_propagates_while_attempts_remain(
    monkeypatch: pytest.MonkeyPatch,
    module: Any,
    node: Any,
    build_state: Any,
    error: Exception,
) -> None:
    """A retry the task still holds is worth more than a blank section.

    Extended run bc77950f met the same provider trouble as 49a509b0 and
    published a full overview on its third durable attempt. Degrading on
    the first would have thrown those two attempts away.
    """
    monkeypatch.setattr(module, "call_llm_json", _raiser(error))
    state = build_state()
    state["durable_retries_remain"] = True

    with pytest.raises(type(error)):
        await node(state)

    assert state.get("degraded_nodes", []) == []


@pytest.mark.parametrize(("module", "node", "build_state"), _NODE_CASES)
@pytest.mark.parametrize("error", [_TIMEOUT, _UPSTREAM])
async def test_the_last_durable_attempt_degrades_instead(
    monkeypatch: pytest.MonkeyPatch,
    module: Any,
    node: Any,
    build_state: Any,
    error: Exception,
) -> None:
    """With no retry left, raising would settle the run and lose the report."""
    monkeypatch.setattr(module, "call_llm_json", _raiser(error))
    state = build_state()
    state["durable_retries_remain"] = False

    await node(state)

    assert len(state["degraded_nodes"]) == 1


@pytest.mark.parametrize("error", _CONTROL_FLOW)
@pytest.mark.parametrize("retries_remain", [True, False])
async def test_control_flow_errors_reraise_whatever_the_attempt(
    monkeypatch: pytest.MonkeyPatch, error: Exception, retries_remain: bool
) -> None:
    """Neither error is "this call failed", so no attempt count absorbs them."""
    monkeypatch.setattr(ro, "call_llm_json", _raiser(error))
    state = _overview_state(durable_retries_remain=retries_remain)

    with pytest.raises(type(error)):
        await ro.research_overview_node(state)

    assert state.get("degraded_nodes", []) == []


async def test_the_interim_firing_also_spends_its_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The periodic firing shares the task's retry budget, so it uses it.

    It labels no report section either way (the test above), but a retry
    it declines to take is one the terminal firing never gets.
    """
    monkeypatch.setattr(ro, "call_llm_json", _raiser(_UPSTREAM))
    state = _overview_state(
        next_task=TaskType.SYNTHESIZE.value, durable_retries_remain=True
    )

    with pytest.raises(APIError):
        await ro.research_overview_node(state)


def test_the_attempt_flag_never_rides_a_checkpoint() -> None:
    """It describes one durable attempt, so persisting it would misread.

    A checkpoint written on attempt 1 is restored by attempt 2 and by
    every later node; carrying "retries remain" into them would report
    the wrong task's budget.
    """
    envelope = serialize_workflow_state(
        _overview_state(durable_retries_remain=True), last_event_seq=0
    )

    assert "durable_retries_remain" not in envelope["state"]
    assert "durable_retries_remain" not in restore_workflow_state(envelope)
