from __future__ import annotations

import re
from collections.abc import Callable
from functools import partial
from typing import Any

import pytest

from co_scientist.prompts import (
    DebatePromptRequest,
    DraftPromptRequest,
    LiteratureQueryInputs,
    PromptRunContext,
    SupervisorPromptInputs,
    ValidationSynthesisRequest,
    get_debate_generation_prompt,
    get_deep_verification_prompt,
    get_draft_prompt_with_tools,
    get_hypothesis_novelty_analysis_prompt,
    get_literature_review_paper_analysis_prompt,
    get_literature_review_query_generation_prompt,
    get_literature_review_synthesis_prompt,
    get_reflection_prompt,
    get_research_overview_prompt,
    get_review_prompt,
    get_supervisor_prompt,
    get_validation_synthesis_prompt_with_tools,
)
from co_scientist.prompts.generation_draft import (
    format_supervisor_guidance_for_generation,
)
from tests._state import make_article

_GUIDANCE: dict[str, Any] = {
    "research_goal_analysis": {
        "key_areas": ["mitochondrial dysfunction", "oxidative stress"],
    },
    "workflow_plan": {
        "generation_phase": {
            "focus_areas": ["metabolic pathways"],
            "diversity_targets": "broad",
            "quantity_target": 5,
        },
        "review_phase": {
            "critical_criteria": ["novelty", "testability"],
            "review_depth": "deep",
        },
        "evolution_phase": {
            "refinement_priorities": ["specificity"],
            "iteration_strategy": "incremental",
        },
    },
}


def test_prompt_builders_include_run_setup_guidance() -> None:
    setup_guidance = "Run setup:\n- Requirements:\n  - Focus on primary data"
    focus_guidance = "Prefer novelty while preserving testability."
    prompt, _ = get_supervisor_prompt(
        SupervisorPromptInputs(research_goal="g", criteria=["Causal clarity"]),
        PromptRunContext(
            run_setup_guidance=setup_guidance,
            run_focus_guidance=focus_guidance,
        ),
    )
    assert "Run Setup Guidance" in prompt
    assert "Run Focus Guidance" in prompt
    assert "Focus on primary data" in prompt
    assert "Prefer novelty" in prompt
    assert "Causal clarity" in prompt


def test_review_prompt_critical_criteria_caps_count_and_questions() -> None:
    """The json_object downgrade does not enforce maxItems server-side."""
    guidance = {
        "workflow_plan": {
            "review_phase": {
                "critical_criteria": [
                    {
                        "name": f"criterion {i}",
                        "questions": [
                            {"name": f"q{i}-{j}", "question": f"text {i}-{j}?"}
                            for j in range(6)
                        ],
                    }
                    for i in range(8)
                ]
            }
        }
    }
    prompt, _ = get_review_prompt(
        research_goal="g",
        hypothesis_text="h",
        context=PromptRunContext(supervisor_guidance=guidance),
    )
    assert "criterion 5" in prompt
    assert "criterion 6" not in prompt
    assert "text 0-3?" in prompt
    assert "text 0-4?" not in prompt


def test_review_prompt_critical_criteria_malformed_entries_degrade() -> None:
    guidance = {
        "workflow_plan": {
            "review_phase": {
                "critical_criteria": [
                    {"name": "Valid Criterion", "questions": ["plain text q"]},
                    {"name": ""},
                    {"questions": []},
                    42,
                    None,
                ],
            }
        }
    }
    prompt, _ = get_review_prompt(
        research_goal="g",
        hypothesis_text="h",
        context=PromptRunContext(supervisor_guidance=guidance),
    )
    assert "Valid Criterion" in prompt
    assert "plain text q" in prompt


def _enum_values(node: Any, path: str = "") -> list[tuple[str, list[Any]]]:
    if not isinstance(node, dict):
        return []
    found: list[tuple[str, list[Any]]] = []
    if "enum" in node:
        found.append((path or "<root>", node["enum"]))
    for name, subschema in (node.get("properties") or {}).items():
        found += _enum_values(subschema, f"{path}.{name}" if path else name)
    if "items" in node:
        found += _enum_values(node["items"], path + "[]")
    return found


def _as_prompt(built: Any) -> str:
    return built[0] if isinstance(built, tuple) else str(built)


def _debate(**fields: Any) -> Any:
    return get_debate_generation_prompt(
        DebatePromptRequest(
            research_goal="design a self-healing polymer",
            transcript="Expert 1: ... Expert 2: ...",
            **fields,
        )
    )


_ARTICLE = make_article(
    title="A landmark paper on neuroinflammation",
    authors=["A. Researcher"],
    year=2022,
    used_in_analysis=True,
)


# builder, strings that must be interpolated into the rendered prompt
_BUILDERS: dict[str, tuple[Callable[[], Any], list[str]]] = {
    "debate": (
        lambda: _debate(
            attributes=["novel", "field-testable"],
            articles_with_reasoning="Prior work suggests ABA signaling.",
            user_hypotheses=["ABA receptor agonists tighten stomatal control"],
            instructions="Weigh the field-trial data before converging.",
        ),
        [
            "design a self-healing polymer",
            "Expert 1:",
            "novel, field-testable",
            "Prior work suggests ABA signaling.",
            "ABA receptor agonists tighten stomatal control",
            "Weigh the field-trial data before converging.",
        ],
    ),
    "draft": (
        lambda: get_draft_prompt_with_tools(
            DraftPromptRequest(
                research_goal="map neuroinflammatory cascades",
                hypotheses_count=4,
                articles=[_ARTICLE],
            )
        ),
        ["map neuroinflammatory cascades", "A landmark paper on neuro"],
    ),
    "reflection": (
        lambda: get_reflection_prompt(
            articles_with_reasoning="Summary: APOE4 increases risk.",
            hypothesis_text="APOE4 impairs lipid transport in astrocytes",
            indra_evidence="APOE4 -> lipid dysregulation (12 papers)",
        ),
        [
            "Summary: APOE4 increases risk.",
            "APOE4 impairs lipid transport in astrocytes",
            "APOE4 -> lipid dysregulation (12 papers)",
        ],
    ),
    "deep_verification": (
        lambda: get_deep_verification_prompt(
            research_goal="Repurpose a drug for AML",
            hypothesis_text="Reparixin inhibits CXCR1/2 in AML",
        ),
        ["Reparixin inhibits CXCR1/2 in AML", "Repurpose a drug for AML"],
    ),
    "research_overview": (
        lambda: get_research_overview_prompt(
            research_goal="Find liver-fibrosis targets",
            hypotheses_summary="1. HDAC inhibition (Elo 1700)",
            contact_candidates="- author-1-1: Ada Researcher; paper=Study",
            evidence_corpus="- evidence-1: title=Study; abstract=Finding",
        ),
        ["HDAC inhibition", "Ada Researcher", "evidence-1"],
    ),
    "paper_analysis": (
        lambda: get_literature_review_paper_analysis_prompt(
            research_goal="explain insulin resistance",
            title="Hepatic glucose output revisited",
            authors=["P. First", "Q. Second"],
            year=2019,
            fulltext="Full text body discussing gluconeogenesis.",
        ),
        ["explain insulin resistance", "P. First", "gluconeogenesis"],
    ),
    "novelty_analysis": (
        lambda: get_hypothesis_novelty_analysis_prompt(
            hypothesis_text="APOE4 impairs astrocyte lipid transport",
            title="Astrocyte lipid handling in AD",
            authors=["A. One", "B. Two"],
            year=2021,
            fulltext="Full text discussing APOE isoforms.",
        ),
        ["APOE4 impairs astrocyte lipid transport", "APOE isoforms"],
    ),
    "literature_synthesis": (
        lambda: get_literature_review_synthesis_prompt(
            research_goal="explain insulin resistance",
            paper_analyses=[
                {
                    "metadata": {
                        "title": "Hepatic glucose output revisited",
                        "authors": ["P. First"],
                        "year": 2019,
                    },
                    "analysis": {"key_findings": "gluconeogenesis is up"},
                }
            ],
        ),
        ["explain insulin resistance", "Hepatic glucose output revisited"],
    ),
    "validation_synthesis": (
        lambda: get_validation_synthesis_prompt_with_tools(
            ValidationSynthesisRequest(
                research_goal="reduce tumor metastasis",
                hypotheses_with_analyses=[
                    {
                        "draft": {
                            "text": "block CXCR4 signaling",
                            "gap_reasoning": "under-studied",
                            "literature_sources": "[C1]",
                        },
                        "novelty_analyses": [],
                    }
                ],
                max_iterations=5,
            )
        ),
        ["reduce tumor metastasis", "block CXCR4 signaling"],
    ),
    **{
        f"query_{source}": (
            partial(
                get_literature_review_query_generation_prompt,
                research_goal="find biomarkers for sepsis",
                source_type=source,
                inputs=LiteratureQueryInputs(
                    user_literature=["Smith 2020 sepsis review"]
                ),
            ),
            ["find biomarkers for sepsis"],
        )
        for source in ("knowledge_graph", "pubmed", "academic")
    },
}


@pytest.mark.parametrize("name", sorted(_BUILDERS))
def test_prompt_builders_fill_every_slot(name: str) -> None:
    build, expected = _BUILDERS[name]
    prompt = _as_prompt(build())
    assert prompt
    for text in expected:
        assert text in prompt
    # Literal JSON braces resemble placeholders, so only whole slots count.
    assert not re.search(r"\{\{MISSING:\w+\}\}", prompt)


_PLAN_GUIDANCE = {
    "research_goal_analysis": {"key_areas": ["oncology"]},
    "workflow_plan": {"generation_phase": {"focus_areas": ["biomarkers"]}},
    "config_synthesis": {
        "preferences": ["testable within two years"],
        "draft_instructions": ["anchor each idea in a reported result"],
        "debate_instructions": ["attack the weakest causal link"],
        "review_instructions": ["penalize restatements of known biology"],
    },
}


def test_draft_guidance_bullets_a_bare_string_as_one_item() -> None:
    result = format_supervisor_guidance_for_generation(
        {"config_synthesis": {"preferences": "must be falsifiable"}}
    )
    assert "- must be falsifiable\n" in result
