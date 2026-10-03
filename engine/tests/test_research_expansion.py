"""Tests for research expansion as a distinct technique (audit E11b).

Pins the three things that make a later generate cycle different from the
initial one instead of a relabel: the detection signal, the distinct
broad-exploratory-retrieval prompt section with bounded pool coverage,
and the draft agent's larger tool-loop budget.
"""

from pathlib import Path
from typing import Any, cast

import pytest

from co_scientist.agents.generation.expansion_research import (
    EXPANSION_EXTRA_DRAFT_ITERATIONS,
    EXPANSION_POOL_ITEM_CHARS,
    EXPANSION_POOL_SAMPLE_SIZE,
    ExpansionResearch,
    _expansion_goal,
    build_expansion_section,
    explored_hypothesis_summaries,
    is_research_expansion,
    research_for_expansion,
)
from co_scientist.agents.generation.literature_tools.draft import (
    _compute_draft_iteration_budget,
)
from co_scientist.constants import get_draft_max_iterations
from co_scientist.mcp_client import MCPToolClient
from co_scientist.prompts import (
    DraftPromptRequest,
    get_draft_prompt_with_tools,
)
from tests._research_tools import (
    _PAPERS,
    FakeResearchClient,
    _ScriptedModel,
    research_registry,
)
from tests._state import make_hypothesis, make_state


@pytest.fixture
def expansion_model(monkeypatch: pytest.MonkeyPatch) -> _ScriptedModel:
    """Route the adapter's model calls to the shared scripted answerer."""
    model = _ScriptedModel()
    monkeypatch.setattr(
        "co_scientist.research_adapter.model.call_llm_json", model
    )
    return model


@pytest.fixture
def expansion_client(monkeypatch: pytest.MonkeyPatch) -> FakeResearchClient:
    """Serve this module's MCP calls from a scripted client."""
    fake = FakeResearchClient(
        {
            "search_alpha": _PAPERS,
            "read_pdf": {
                "content": "TGF-beta blockade reduced fibrosis in a"
                " human cohort."
            },
        }
    )

    async def get_client(**_: Any) -> MCPToolClient:
        return cast(MCPToolClient, fake)

    monkeypatch.setattr("co_scientist.mcp_client.get_mcp_client", get_client)
    return fake


def test_initial_generation_cycle_is_not_expansion() -> None:
    """Iteration 0 is initial drafting, not research expansion."""
    assert not is_research_expansion(make_state(current_iteration=0))
    assert not is_research_expansion(make_state())


def test_later_generate_cycles_are_expansion() -> None:
    """Any generate cycle after a completed iteration is expansion."""
    assert is_research_expansion(make_state(current_iteration=1))
    assert is_research_expansion(make_state(current_iteration=3))


def test_expansion_section_absent_on_initial_cycle() -> None:
    """The initial cycle keeps its focused-grounding prompt unchanged."""
    assert build_expansion_section(make_state(current_iteration=0)) == ""


def test_expansion_section_switches_to_broad_retrieval() -> None:
    """Expansion cycles instruct diverse retrieval before ideation."""
    state = make_state(current_iteration=2)
    section = build_expansion_section(state)
    assert "Research Expansion Cycle" in section
    assert "DIVERSE" in section
    assert "before" in section.lower()


def test_expansion_section_names_the_explored_pool_bounded() -> None:
    """Coverage lists explored hypotheses, capped and truncated."""
    long_text = "explored direction " + "x" * 500
    hypotheses = [make_hypothesis(text=f"hyp {i}") for i in range(20)]
    hypotheses.append(make_hypothesis(text=long_text))
    state = make_state(current_iteration=1, hypotheses=hypotheses)

    summaries = explored_hypothesis_summaries(state)
    assert len(summaries) == EXPANSION_POOL_SAMPLE_SIZE
    assert all(len(s) <= EXPANSION_POOL_ITEM_CHARS + 3 for s in summaries)

    section = build_expansion_section(state)
    assert "hyp 0" in section
    # The capped sample never reaches hypothesis 15.
    assert "hyp 15" not in section
    assert "do NOT re-derive" in section


def test_expansion_section_with_empty_pool_omits_coverage() -> None:
    """Expansion before any hypothesis exists still switches behavior."""
    state = make_state(current_iteration=1, hypotheses=[])
    section = build_expansion_section(state)
    assert "Research Expansion Cycle" in section
    assert "already explored" not in section


def test_draft_prompt_renders_expansion_section() -> None:
    """The draft-with-tools prompt splices the expansion section in."""
    section = build_expansion_section(make_state(current_iteration=1))
    prompt, _ = get_draft_prompt_with_tools(
        DraftPromptRequest(
            research_goal="repurpose a kinase inhibitor",
            hypotheses_count=2,
            research_expansion_section=section,
        )
    )
    assert "Research Expansion Cycle" in prompt
    assert "{{MISSING" not in prompt


def test_draft_prompt_without_sections_is_unchanged() -> None:
    """No sections passed means no expansion/falsified text in the prompt."""
    prompt, _ = get_draft_prompt_with_tools(
        DraftPromptRequest(
            research_goal="repurpose a kinase inhibitor",
            hypotheses_count=2,
        )
    )
    assert "Research Expansion Cycle" not in prompt
    assert "Verified Incorrect" not in prompt
    assert "{{MISSING" not in prompt


def test_draft_prompt_renders_falsified_assumptions_section() -> None:
    """The K9 avoid-or-rework block also reaches the draft prompt."""
    prompt, _ = get_draft_prompt_with_tools(
        DraftPromptRequest(
            research_goal="repurpose a kinase inhibitor",
            hypotheses_count=2,
            falsified_assumptions_section=(
                "## Assumptions Verified Incorrect (avoid or rework)\n"
                "- Does efflux matter? -- finding: no.\n"
            ),
        )
    )
    assert "Verified Incorrect" in prompt
    assert "Does efflux matter?" in prompt


def test_expansion_draft_budget_gets_extra_retrieval_rounds() -> None:
    """Broad retrieval gets more tool-loop iterations than focused drafting."""
    base = _compute_draft_iteration_budget(3)
    expanded = _compute_draft_iteration_budget(3, is_expansion=True)
    assert base == get_draft_max_iterations(3)
    assert expanded == base + EXPANSION_EXTRA_DRAFT_ITERATIONS


async def test_the_initial_cycle_buys_no_exploration(tmp_path: Path) -> None:
    """Iteration 0 is the literature review's ground, already researched."""
    state = make_state(current_iteration=0, research_tier="extended")

    assert await research_for_expansion(state) is None


async def test_a_tier_that_funds_no_research_explores_nothing(
    tmp_path: Path,
) -> None:
    """Expansion is a prompt on the shallow tiers, not a second gathering."""
    state = make_state(current_iteration=1, research_tier="standard")

    assert await research_for_expansion(state) is None


def test_the_expansion_goal_names_the_explored_ground_to_avoid() -> None:
    """The pool is the boundary to plan around, not a question to ask."""
    state = make_state(
        current_iteration=1,
        research_goal="why does fibrosis progress?",
        hypotheses=[make_hypothesis(text="TGF-beta drives it")],
    )

    goal = _expansion_goal(state)

    assert goal.startswith("why does fibrosis progress?")
    assert "TGF-beta drives it" in goal
    assert "do NOT cover" in goal or "NOT cover" in goal


def test_the_expansion_goal_is_the_bare_goal_before_any_hypothesis() -> None:
    state = make_state(current_iteration=1, research_goal="why fibrosis?")

    assert _expansion_goal(state) == "why fibrosis?"


def test_findings_reach_the_generation_prompt() -> None:
    """A finding that lives only in the ledger was recorded, not used."""
    explored = ExpansionResearch(
        section="- collagen crosslinking is under-studied [PMID:1]\n",
        articles=[],
        ledger={},
    )
    state = explored.applied_to(make_state(current_iteration=1))

    section = build_expansion_section(state)

    assert "collagen crosslinking is under-studied [PMID:1]" in section


def test_the_prompt_carries_no_evidence_block_when_nothing_explored() -> None:
    """The shallow tiers keep the prompt-and-tool-budget behaviour alone."""
    section = build_expansion_section(make_state(current_iteration=1))

    assert "Research Expansion Cycle" in section
    assert "Ground new hypotheses in this material" not in section


async def test_an_expansion_cycle_explores_and_grounds_the_next_draft(
    tmp_path: Path,
    expansion_model: _ScriptedModel,
    expansion_client: FakeResearchClient,
) -> None:
    """A later cycle drafts against evidence the first cycle never had.

    The whole point of the technique: the gathering below is one the
    initial generation pass does not run.
    """
    state = make_state(
        current_iteration=1,
        research_goal="reverse fibrosis",
        model_name="offline/test",
        run_id="run-1",
        mcp_available=True,
        research_tier="extended",
        tool_registry=research_registry(tmp_path),
        hypotheses=[make_hypothesis(text="TGF-beta drives it")],
    )

    explored = await research_for_expansion(state)

    assert explored is not None
    assert "Blockade reduced fibrosis in humans" in explored.section
    assert explored.articles
    assert explored.ledger["findings"]
    # The already-explored hypothesis is the boundary the planning call
    # was given, which is what makes this expansion and not a repeat.
    assert "TGF-beta drives it" in expansion_model.prompts[0]
    assert "Blockade reduced fibrosis in humans" in build_expansion_section(
        explored.applied_to(state)
    )


def test_explored_articles_are_merged_before_the_citation_namespace() -> None:
    """A paper this cycle found and no strategy can cite was not delivered."""
    existing = object()
    found = object()
    state = ExpansionResearch("s", [found], {}).applied_to(
        make_state(current_iteration=1, articles=[existing])
    )

    assert state["articles"] == [existing, found]
