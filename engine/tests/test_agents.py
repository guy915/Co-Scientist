from __future__ import annotations

from typing import Any

import pytest
from litellm.exceptions import APIError

from co_scientist.agents.meta_review import meta_review as mr
from co_scientist.agents.meta_review import research_overview as ro
from co_scientist.agents.proximity import proximity as px
from co_scientist.exceptions import (
    LLMTimeoutError,
)
from co_scientist.task_runtime import next_task_type
from co_scientist.workflow_topology import (
    WORKFLOW_ROUTES,
)
from tests._state import (
    decision_states,
    make_hypothesis,
    make_review,
    make_state,
)

# Node keys persist in tasks and checkpoints; renaming requires a data
# migration.


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


def _raiser(error: Exception) -> Any:

    async def _call(*_: Any, **__: Any) -> dict[str, Any]:
        raise error

    return _call


def _overview_state(**overrides: Any) -> Any:
    return make_state(
        hypotheses=[make_hypothesis(text="H", elo_rating=1700)],
        research_goal="g",
        supervisor_model_name="test/model",
        meta_review={},
        articles=[],
        **overrides,
    )


def _reviewed_state() -> Any:
    hypothesis = make_hypothesis(text="H")
    hypothesis.reviews = [make_review()]
    return make_state(
        hypotheses=[hypothesis],
        research_goal="g",
        supervisor_model_name="test/model",
    )


def _pair_state() -> Any:
    return make_state(
        hypotheses=[make_hypothesis(text="A"), make_hypothesis(text="B")],
        research_goal="g",
        model_name="test/model",
    )


# (module, node, state builder, name recorded in degraded_nodes)
_NODE_CASES = [
    pytest.param(
        ro,
        ro.research_overview_node,
        _overview_state,
        "research_overview",
        id="research_overview",
    ),
    pytest.param(
        mr,
        mr.meta_review_node,
        _reviewed_state,
        "meta_review",
        id="meta_review",
    ),
    pytest.param(
        px,
        px.proximity_node,
        _pair_state,
        "proximity_analysis",
        id="proximity",
    ),
]


@pytest.mark.parametrize(
    ("module", "node", "build_state", "degraded_name"), _NODE_CASES
)
@pytest.mark.parametrize("error", [_TIMEOUT, _UPSTREAM])
@pytest.mark.parametrize(
    "retries_remain", [None, False, True], ids=["graph", "last", "remain"]
)
async def test_provider_failure_degrades_only_on_the_last_attempt(
    monkeypatch: pytest.MonkeyPatch,
    module: Any,
    node: Any,
    build_state: Any,
    degraded_name: str,
    error: Exception,
    retries_remain: bool | None,
) -> None:
    """Use remaining durable retries before settling for a blank report
    section; raising after the last one would settle the run without it."""
    monkeypatch.setattr(module, "call_llm_json", _raiser(error))
    state = build_state()
    if retries_remain is not None:
        state["durable_retries_remain"] = retries_remain

    if retries_remain:
        with pytest.raises(type(error)):
            await node(state)
        assert state.get("degraded_nodes", []) == []
    else:
        await node(state)
        assert state["degraded_nodes"] == [degraded_name]


@pytest.mark.parametrize("node", sorted(WORKFLOW_ROUTES))
def test_a_safety_halt_ends_the_durable_path_from_every_node(
    node: str,
) -> None:
    for state in decision_states():
        halted = make_state(**{**state, "safety_blocked": True})
        assert next_task_type(node, halted) is None
