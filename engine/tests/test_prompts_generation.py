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
    ValidationSynthesisRequest,
    format_articles_metadata,
    get_debate_generation_prompt,
    get_deep_verification_prompt,
    get_draft_prompt_with_tools,
    get_hypothesis_novelty_analysis_prompt,
    get_literature_review_paper_analysis_prompt,
    get_literature_review_query_generation_prompt,
    get_literature_review_synthesis_prompt,
    get_reflection_prompt,
    get_research_overview_prompt,
    get_validation_synthesis_prompt_with_tools,
)
from co_scientist.prompts.generation_draft import (
    format_supervisor_guidance_for_generation,
)
from co_scientist.prompts.loading import load_prompt
from tests._state import make_article


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


def test_debate_final_turn_alone_carries_the_output_schema() -> None:
    _, no_schema = _debate(is_final_turn=False)
    prompt, schema = _debate(is_final_turn=True)
    assert no_schema is None
    assert isinstance(schema, dict)
    assert "FINAL TURN" in prompt
    assert "literature_grounding" in prompt
    assert "to enable [Y]" not in prompt
    assert "falsification" in prompt.lower()


def test_debate_prompt_without_optional_inputs_has_no_missing_slots() -> None:
    for articles in ("lit synthesis", None):
        for seeds in (["a seed hypothesis"], None):
            prompt, _ = _debate(
                articles_with_reasoning=articles, user_hypotheses=seeds
            )
            assert "{{MISSING" not in prompt
    prompt, _ = _debate(articles_with_reasoning="lit synthesis")
    assert "No user-provided starting hypotheses." in prompt


def test_meta_review_feedback_reaches_the_post_debate_template() -> None:
    raw = load_prompt(
        "generation_after_debate",
        {
            "research_goal": "A goal",
            "domain_context": "",
            "reviews_overview": "META-REVIEW-FEEDBACK-MARKER",
            "num_hypotheses": 2,
            "hypotheses_so_far": "",
            "debate_transcript": "",
        },
    )
    assert "META-REVIEW-FEEDBACK-MARKER" in raw


def test_format_articles_metadata_renders_only_used_articles() -> None:
    unused = make_article(title="Unused", used_in_analysis=False)
    assert format_articles_metadata([]) == ""
    assert format_articles_metadata([unused]) == ""
    out = format_articles_metadata([_ARTICLE, unused])
    assert "A landmark paper on neuroinflammation" in out
    assert "A. Researcher" in out
    assert "Unused" not in out


_GUIDANCE = {
    "research_goal_analysis": {"key_areas": ["oncology"]},
    "workflow_plan": {"generation_phase": {"focus_areas": ["biomarkers"]}},
    "config_synthesis": {
        "preferences": ["testable within two years"],
        "draft_instructions": ["anchor each idea in a reported result"],
        "debate_instructions": ["attack the weakest causal link"],
        "review_instructions": ["penalize restatements of known biology"],
    },
}


def test_supervisor_guidance_routes_each_instruction_to_its_writer() -> None:
    draft, _ = get_draft_prompt_with_tools(
        DraftPromptRequest(
            research_goal="find a new target in fibrosis",
            hypotheses_count=3,
            context=PromptRunContext(supervisor_guidance=_GUIDANCE),
        )
    )
    debate, _ = _debate(context=PromptRunContext(supervisor_guidance=_GUIDANCE))

    assert "anchor each idea in a reported result" in draft
    assert "attack the weakest causal link" not in draft
    assert "attack the weakest causal link" in debate
    assert "anchor each idea in a reported result" not in debate
    for prompt in (draft, debate):
        assert "penalize restatements of known biology" not in prompt
        assert "biomarkers" in prompt
        assert "testable within two years" in prompt
        assert "{{MISSING" not in prompt


@pytest.mark.parametrize(
    "guidance",
    [
        None,
        {},
        {"unrelated": 1},
        {"workflow_plan": {"generation_phase": "focus on kinases"}},
        {"workflow_plan": "draft broadly", "config_synthesis": "be bold"},
    ],
)
def test_draft_guidance_is_empty_without_a_usable_plan(
    guidance: dict[str, Any] | None,
) -> None:
    assert format_supervisor_guidance_for_generation(guidance) == ""


def test_draft_guidance_bullets_a_bare_string_as_one_item() -> None:
    result = format_supervisor_guidance_for_generation(
        {"config_synthesis": {"preferences": "must be falsifiable"}}
    )
    assert "- must be falsifiable\n" in result
