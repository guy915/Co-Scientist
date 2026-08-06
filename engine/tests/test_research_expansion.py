"""Tests for research expansion as a distinct technique (audit E11b).

Pins the three things that make a later generate cycle different from the
initial one instead of a relabel: the detection signal, the distinct
broad-exploratory-retrieval prompt section with bounded pool coverage,
and the draft agent's larger tool-loop budget.
"""

from co_scientist.agents.generation.literature_tools.draft import (
    _compute_draft_iteration_budget,
)
from co_scientist.agents.generation.research_expansion import (
    EXPANSION_EXTRA_DRAFT_ITERATIONS,
    EXPANSION_POOL_ITEM_CHARS,
    EXPANSION_POOL_SAMPLE_SIZE,
    build_expansion_section,
    explored_hypothesis_summaries,
    is_research_expansion,
)
from co_scientist.constants import get_draft_max_iterations
from co_scientist.prompts import (
    DraftPromptRequest,
    get_draft_prompt_with_tools,
)
from tests._state import make_hypothesis, make_state


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
