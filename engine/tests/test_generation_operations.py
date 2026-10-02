"""Supported generation plans preserve strategy and citation contracts."""

import dataclasses

import pytest

from co_scientist.agents.generation import prepare_generation
from co_scientist.constants import LITERATURE_REVIEW_FAILED
from co_scientist.exceptions import GenerationError
from tests._state import make_article, make_state


@pytest.mark.parametrize(
    ("options", "expected_counts", "degraded"),
    [
        ({}, (0, 0, 6, 2), True),
        (
            {"mcp_available": True, "articles_with_reasoning": "papers"},
            (0, 6, 0, 2),
            False,
        ),
        (
            {
                "mcp_available": True,
                "articles_with_reasoning": "papers",
                "enable_tool_calling_generation": True,
            },
            (3, 3, 0, 2),
            False,
        ),
        (
            {
                "mcp_available": True,
                "articles_with_reasoning": LITERATURE_REVIEW_FAILED,
            },
            (0, 0, 6, 2),
            True,
        ),
        (
            {
                "mcp_available": True,
                "articles_with_reasoning": "papers",
                "generation_strategy": "no_lit",
            },
            (0, 0, 6, 2),
            True,
        ),
        ({"dev_test_lit_tools_isolation": True}, (8, 0, 0, 0), False),
        (
            {
                "mcp_available": True,
                "articles_with_reasoning": "papers",
                "enable_tool_calling_generation": True,
                "initial_hypotheses_count": 1,
            },
            (1, 0, 0, 0),
            False,
        ),
    ],
)
async def test_plan_allocations_keep_the_existing_mix(
    options: dict[str, object],
    expected_counts: tuple[int, int, int, int],
    degraded: bool,
) -> None:
    state = make_state(
        **{
            "supervisor_guidance": {"focus": "test"},
            "initial_hypotheses_count": 8,
            **options,
        }
    )
    plan = await prepare_generation(state)

    assert tuple(plan.counts.strategy_counts) == (
        "tools",
        "debate_lit",
        "debate_only",
        "assumptions",
    )
    assert tuple(plan.counts.strategy_counts.values()) == expected_counts
    assert plan.counts.is_degraded_mode is degraded
    assert sum(expected_counts) == state["initial_hypotheses_count"]
    # The counts still serialize to the durable aggregate's existing shape.
    assert set(dataclasses.asdict(plan.counts)) == {
        "tools_count",
        "debate_with_lit_count",
        "debate_only_count",
        "assumptions_count",
        "is_dev_isolation",
        "is_degraded_mode",
    }


async def test_plan_citation_namespace_includes_only_analyzed_sources() -> None:
    state = make_state(
        supervisor_guidance={"focus": "test"},
        mcp_available=True,
        articles_with_reasoning="Read evidence",
        articles=[
            make_article("Analyzed source", used_in_analysis=True),
            make_article("Unread search hit", used_in_analysis=False),
        ],
        context_enrichment_sources=[
            {"type": "knowledge_graph", "display": "A activates B"}
        ],
    )
    plan = await prepare_generation(state)

    assert plan.literature == "Read evidence"
    assert list(plan.reference_index.sources) == ["C1", "C2"]
    assert plan.reference_index.sources["C1"]["title"] == "Analyzed source"
    assert "Unread search hit" not in plan.reference_index.text
    assert "A activates B" in plan.reference_index.text


async def test_plan_requires_supervisor_guidance() -> None:
    with pytest.raises(GenerationError, match="No supervisor_guidance"):
        await prepare_generation(make_state())
