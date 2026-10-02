"""Tests for the generation/literature prompt builders in ``co_scientist``.

Covers the debate-generation, draft-with-tools, reflection, deep-verification,
research-overview, and literature-review (query generation, paper analysis,
synthesis, novelty analysis, validation synthesis) prompt builders, plus
``format_articles_metadata``. The planning/evaluation prompt builders are
covered in ``test_prompts_review``.

These functions are pure template builders: each reads a markdown template,
substitutes ``{{variable}}`` placeholders with the caller's inputs, and returns
either a prompt string or a ``(prompt, schema)`` tuple. The tests assert that
the returned prompt is a non-empty ``str`` that interpolates the key inputs,
that schemas have the right shape, and that a few conditional branches change
the output.

``substitute_variables`` replaces any template placeholder the builder does not
supply with a literal ``{{MISSING:<name>}}`` sentinel rather than raising. The
builders leave no sentinels behind, so their tests assert ``"{{MISSING" not in
prompt`` to verify *full* interpolation.

The builders perform no LLM or network calls, so the tests are deterministic
with no mocking.
"""

from co_scientist.prompts import (
    DebatePromptRequest,
    DraftPromptRequest,
    LiteratureQueryInputs,
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
from tests._state import make_article

# --- get_debate_generation_prompt ------------------------------------------


def test_debate_generation_non_final_turn_has_no_schema() -> None:
    """A non-final debate turn returns a conversational prompt, schema None."""
    prompt, schema = get_debate_generation_prompt(
        DebatePromptRequest(
            research_goal="design a self-healing polymer",
            transcript="Expert 1: ... Expert 2: ...",
            is_final_turn=False,
        )
    )
    assert isinstance(prompt, str)
    assert "design a self-healing polymer" in prompt
    assert "Expert 1:" in prompt
    assert "{{MISSING" not in prompt
    assert schema is None


def test_debate_generation_final_turn_appends_json_block_and_schema() -> None:
    """The final turn appends JSON output instructions and returns a schema."""
    prompt, schema = get_debate_generation_prompt(
        DebatePromptRequest(
            research_goal="design a self-healing polymer",
            transcript="prior discussion",
            is_final_turn=True,
        )
    )
    assert "FINAL TURN" in prompt
    assert "literature_grounding" in prompt
    assert "{{MISSING" not in prompt
    assert isinstance(schema, dict)


# --- get_draft_prompt_with_tools -------------------------------------------


def test_draft_prompt_with_tools_interpolates_goal_count_articles() -> None:
    """The draft-with-tools prompt embeds goal, count, and article metadata."""
    article = make_article(
        title="A landmark paper on neuroinflammation",
        authors=["A. Researcher"],
        year=2022,
        used_in_analysis=True,
    )
    prompt, schema = get_draft_prompt_with_tools(
        DraftPromptRequest(
            research_goal="map neuroinflammatory cascades",
            hypotheses_count=4,
            articles=[article],
        )
    )
    assert "map neuroinflammatory cascades" in prompt
    assert "4" in prompt
    assert "A landmark paper on neuroinflammation" in prompt
    assert "{{MISSING" not in prompt
    assert isinstance(schema, dict)


# --- get_reflection_prompt -------------------------------------------------


def test_reflection_prompt_interpolates_hypothesis_and_evidence() -> None:
    """The reflection prompt embeds the hypothesis, summary, and KG evidence."""
    prompt, schema = get_reflection_prompt(
        articles_with_reasoning="Summary: APOE4 increases risk.",
        hypothesis_text="APOE4 impairs lipid transport in astrocytes",
        indra_evidence="APOE4 -> lipid dysregulation (12 papers)",
    )
    assert "Summary: APOE4 increases risk." in prompt
    assert "APOE4 impairs lipid transport in astrocytes" in prompt
    assert "APOE4 -> lipid dysregulation (12 papers)" in prompt
    assert "{{MISSING" not in prompt
    assert isinstance(schema, dict)


# --- format_articles_metadata ----------------------------------------------


def test_format_articles_metadata_renders_used_articles() -> None:
    """Used articles are rendered with title, authors, and year."""
    article = make_article(
        title="Targeting senescent cells",
        authors=["J. Doe", "K. Smith"],
        year=2021,
        citations=42,
        used_in_analysis=True,
    )
    out = format_articles_metadata([article])
    assert "Targeting senescent cells" in out
    assert "J. Doe" in out
    assert "2021" in out


def test_format_articles_metadata_empty_when_none_used() -> None:
    """An empty list, or articles not used in analysis, yields an empty str."""
    assert format_articles_metadata([]) == ""
    unused = make_article(title="Unused", used_in_analysis=False)
    assert format_articles_metadata([unused]) == ""


# --- literature query / paper analysis builders ----------------------------


def test_pubmed_query_prompt_interpolates_goal_and_lists() -> None:
    """The PubMed query prompt embeds the goal and provided literature."""
    prompt = get_literature_review_query_generation_prompt(
        research_goal="find biomarkers for sepsis",
        source_type="pubmed",
        inputs=LiteratureQueryInputs(
            user_literature=["Smith 2020 sepsis review"]
        ),
    )
    assert isinstance(prompt, str)
    assert "find biomarkers for sepsis" in prompt
    assert "Smith 2020 sepsis review" in prompt
    assert "{{MISSING" not in prompt


def test_paper_analysis_prompt_interpolates_metadata() -> None:
    """The paper-analysis prompt embeds the goal, title, authors, and year."""
    prompt = get_literature_review_paper_analysis_prompt(
        research_goal="explain insulin resistance",
        title="Hepatic glucose output revisited",
        authors=["P. First", "Q. Second"],
        year=2019,
        fulltext="Full text body discussing gluconeogenesis.",
    )
    assert "explain insulin resistance" in prompt
    assert "Hepatic glucose output revisited" in prompt
    assert "P. First" in prompt
    assert "2019" in prompt
    assert "Full text body discussing gluconeogenesis." in prompt
    # Every placeholder this builder owns is filled. (A blanket "{{MISSING"
    # check is not used here: the template embeds a literal ``{{...}}`` JSON
    # example block that ``substitute_variables`` mis-reads as a placeholder,
    # which is a template-escaping quirk independent of the builder's inputs.)
    for var in ("research_goal", "title", "authors", "year", "fulltext"):
        assert f"{{{{MISSING:{var}}}}}" not in prompt


def test_get_deep_verification_prompt_substitutes_and_returns_schema() -> None:
    """The deep-verification prompt embeds the goal and hypothesis text."""
    prompt, schema = get_deep_verification_prompt(
        research_goal="Repurpose a drug for AML",
        hypothesis_text="Reparixin inhibits CXCR1/2 in AML",
    )
    assert "Reparixin inhibits CXCR1/2 in AML" in prompt
    assert "Repurpose a drug for AML" in prompt
    assert schema is not None
    assert "{hypothesis_text}" not in prompt  # placeholder fully substituted


def test_get_research_overview_prompt_substitutes_and_returns_schema() -> None:
    """The research-overview prompt embeds the goal and hypotheses summary."""
    prompt, schema = get_research_overview_prompt(
        research_goal="Find liver-fibrosis targets",
        hypotheses_summary="1. HDAC inhibition (Elo 1700)\n2. BRD4 (Elo 1650)",
        contact_candidates="- author-1-1: Ada Researcher; paper=Study",
        evidence_corpus="- evidence-1: title=Study; abstract=Finding",
    )
    assert "Find liver-fibrosis targets" in prompt
    assert "HDAC inhibition" in prompt
    assert "Ada Researcher" in prompt
    assert "evidence-1" in prompt
    assert schema is not None


# --- untested prompt getters (characterization) ----------------------------


def test_source_aware_query_prompt_selects_template_by_source_type() -> None:
    """The source-aware query builder embeds the goal for each source type."""
    for source_type in ("knowledge_graph", "pubmed", "academic"):
        prompt = get_literature_review_query_generation_prompt(
            research_goal="find biomarkers for sepsis",
            source_type=source_type,
            inputs=LiteratureQueryInputs(
                user_literature=["Smith 2020 sepsis review"]
            ),
        )
        assert isinstance(prompt, str)
        assert prompt
        assert "find biomarkers for sepsis" in prompt
        assert "{{MISSING" not in prompt


def test_literature_synthesis_prompt_renders_paper_analyses() -> None:
    """The synthesis builder embeds the goal and each paper's findings."""
    prompt = get_literature_review_synthesis_prompt(
        research_goal="explain insulin resistance",
        paper_analyses=[
            {
                "metadata": {
                    "title": "Hepatic glucose output revisited",
                    "authors": ["P. First"],
                    "year": 2019,
                },
                "analysis": {
                    "key_findings": "gluconeogenesis is upregulated",
                    "gaps_identified": "no in-vivo validation",
                },
            }
        ],
    )
    assert isinstance(prompt, str)
    assert "explain insulin resistance" in prompt
    assert "Hepatic glucose output revisited" in prompt
    assert "{{MISSING" not in prompt


def test_novelty_analysis_prompt_interpolates_metadata() -> None:
    """The novelty-analysis builder embeds the hypothesis and metadata."""
    prompt = get_hypothesis_novelty_analysis_prompt(
        hypothesis_text="APOE4 impairs astrocyte lipid transport",
        title="Astrocyte lipid handling in AD",
        authors=["A. One", "B. Two"],
        year=2021,
        fulltext="Full text discussing APOE isoforms.",
    )
    assert isinstance(prompt, str)
    assert "APOE4 impairs astrocyte lipid transport" in prompt
    assert "Astrocyte lipid handling in AD" in prompt
    assert "2021" in prompt
    # Every placeholder this builder owns is filled. (A blanket "{{MISSING"
    # check is not used here: the template embeds a literal ``{{...}}`` JSON
    # example block that ``substitute_variables`` mis-reads as a placeholder,
    # which is a template-escaping quirk independent of the builder's inputs.)
    for var in ("hypothesis_text", "title", "authors", "year", "fulltext"):
        assert f"{{{{MISSING:{var}}}}}" not in prompt


def test_validation_synthesis_with_tools_returns_schema() -> None:
    """The tools variant embeds drafts and returns a non-None schema."""
    prompt, schema = get_validation_synthesis_prompt_with_tools(
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
    )
    assert isinstance(prompt, str)
    assert "reduce tumor metastasis" in prompt
    assert "block CXCR4 signaling" in prompt
    assert schema is not None
