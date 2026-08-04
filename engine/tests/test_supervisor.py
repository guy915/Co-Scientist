"""Tests for supervisor_node: research-plan and workflow-guidance assembly.

The node builds a real prompt then makes a single ``call_llm_json`` call whose
JSON response it reshapes into a ``supervisor_guidance`` dict. These tests stub
that call out and assert on the deterministic mapping from the LLM response to
the returned state update, including the ``key_areas`` logging guard that must
tolerate a non-dict ``research_goal_analysis``.
"""

import pytest

from co_scientist.agents.supervisor import supervisor
from co_scientist.agents.supervisor.supervisor import supervisor_node
from tests._llm_fake import stub_call_llm_json
from tests._state import make_state


async def test_guidance_carries_response_subobjects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each response sub-object is copied verbatim into supervisor_guidance."""
    response = {
        "research_goal_analysis": {
            "summary": "study alpha pathway",
            "key_areas": ["a", "b"],
        },
        "workflow_plan": {"iterations": 3},
        "config_synthesis": {
            "preferences": ["testable within 2 years"],
            "review_instructions": ["check the assay measures the claim"],
            "attributes": [
                {"name": "Feasibility", "rubric": "1 impossible .. 5 routine"}
            ],
        },
        "performance_assessment": {"status": "on track"},
        "adjustment_recommendations": ["broaden search"],
        "output_preparation": {"format": "ranked list"},
    }
    stub_call_llm_json(monkeypatch, supervisor, response)

    result = await supervisor_node(make_state())

    guidance = result["supervisor_guidance"]
    # Every response sub-object is carried into guidance verbatim.
    for key in (
        "research_goal_analysis",
        "workflow_plan",
        "config_synthesis",
        "performance_assessment",
        "adjustment_recommendations",
        "output_preparation",
    ):
        assert guidance[key] == response[key]
    # Metrics update is always emitted (one LLM call this node).
    assert result["metrics"] is not None
    assert result["metrics"].llm_calls == 1


async def test_missing_response_fields_default_to_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty response yields guidance with empty defaults, not a crash."""
    stub_call_llm_json(monkeypatch, supervisor, {})

    result = await supervisor_node(make_state())

    guidance = result["supervisor_guidance"]
    assert guidance["research_goal_analysis"] == {}
    assert guidance["workflow_plan"] == {}
    assert guidance["config_synthesis"] == {}
    assert guidance["performance_assessment"] == {}
    assert guidance["adjustment_recommendations"] == []
    assert guidance["output_preparation"] == {}


async def test_list_research_goal_analysis_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A list research_goal_analysis falls back to empty key_areas safely.

    The node only reads ``key_areas`` when the analysis is a dict; a list must
    pass through the logging guard without raising and still be carried in the
    guidance unchanged.
    """
    analysis = ["area one", "area two"]
    stub_call_llm_json(
        monkeypatch, supervisor, {"research_goal_analysis": analysis}
    )

    result = await supervisor_node(make_state())

    guidance = result["supervisor_guidance"]
    assert guidance["research_goal_analysis"] == analysis
    # key_areas falls back to empty, so the message metadata reports zero.
    assert result["messages"][0]["metadata"]["key_areas"] == 0


async def test_key_areas_feed_message_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Present key_areas are counted into the emitted message metadata."""
    stub_call_llm_json(
        monkeypatch,
        supervisor,
        {
            "research_goal_analysis": {
                "key_areas": ["alpha", "beta", "gamma", "delta"],
            }
        },
    )

    result = await supervisor_node(make_state())

    assert result["supervisor_guidance"]["research_goal_analysis"][
        "key_areas"
    ] == ["alpha", "beta", "gamma", "delta"]
    message = result["messages"][0]
    assert message["metadata"]["phase"] == "supervisor"
    assert message["metadata"]["key_areas"] == 4
