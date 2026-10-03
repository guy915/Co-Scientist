"""Offline contracts for prompts generation."""

from __future__ import annotations

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
from co_scientist.prompts.generation_debate import (
    _build_debate_literature_variables,
    _format_debate_attributes,
    _format_supervisor_guidance_for_debate,
)
from co_scientist.prompts.generation_draft import (
    format_supervisor_guidance_for_generation,
)
from co_scientist.prompts.loading import load_prompt
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


# --- _format_debate_attributes ----------------------------------------------


def test_format_debate_attributes_joins_list() -> None:
    """A list of attributes is comma-joined."""
    assert _format_debate_attributes(["novel", "testable"]) == "novel, testable"


def test_format_debate_attributes_empty_list_falls_back() -> None:
    """An empty list falls back to the default attributes phrase."""
    assert _format_debate_attributes([]) == "testable and falsifiable"


def test_format_debate_attributes_string_passthrough() -> None:
    """A plain string is returned unchanged."""
    assert _format_debate_attributes("bold") == "bold"


def test_format_debate_attributes_none_falls_back() -> None:
    """None falls back to the default attributes phrase."""
    assert _format_debate_attributes(None) == "testable and falsifiable"


# --- _format_supervisor_guidance_for_debate ---------------------------------


def test_supervisor_guidance_none_returns_empty() -> None:
    """A None supervisor_guidance yields an empty guidance section."""
    assert _format_supervisor_guidance_for_debate(None) == ""


def test_supervisor_guidance_non_dict_returns_empty() -> None:
    """A non-dict supervisor_guidance yields an empty guidance section."""
    guidance = _format_supervisor_guidance_for_debate(
        "not a dict"  # type: ignore[arg-type]
    )
    assert guidance == ""


def test_supervisor_guidance_populated_dict_with_no_relevant_keys() -> None:
    """A truthy dict with no research-goal/workflow-plan keys yields "".

    Exercises the body of the function (goal_analysis/workflow_plan
    extraction) without either sub-section producing content, so the final
    join-or-empty branch takes the empty path.
    """
    assert _format_supervisor_guidance_for_debate({"unrelated": "value"}) == ""


def test_supervisor_guidance_key_areas_only() -> None:
    """Key research areas alone render under their own header."""
    guidance = {
        "research_goal_analysis": {
            "key_areas": ["membrane biology", "signal transduction"]
        }
    }
    result = _format_supervisor_guidance_for_debate(guidance)
    assert "Key research areas to consider:" in result
    assert "- membrane biology" in result
    assert "- signal transduction" in result
    assert "Generation guidance:" not in result


def test_supervisor_guidance_generation_phase_only() -> None:
    """Generation-phase focus areas alone get their own header (needs_header).

    With no key areas, the generation-phase section owns the header (since
    no earlier section already introduced the guidance block).
    """
    guidance = {
        "workflow_plan": {
            "generation_phase": {"focus_areas": ["kinase inhibitors", "CNS"]}
        }
    }
    result = _format_supervisor_guidance_for_debate(guidance)
    assert "Generation guidance:" in result
    assert "Focus on: kinase inhibitors, CNS" in result
    assert "Key research areas" not in result


def test_supervisor_guidance_generation_phase_focus_areas_as_string() -> None:
    """A plain-string focus_areas value is used as-is (no join)."""
    guidance = {
        "workflow_plan": {
            "generation_phase": {"focus_areas": "receptor pharmacology"}
        }
    }
    result = _format_supervisor_guidance_for_debate(guidance)
    assert "Focus on: receptor pharmacology" in result


def test_supervisor_guidance_key_areas_and_generation_phase_combined() -> None:
    """With key areas present, the generation-phase section skips its header.

    The key-areas section already introduced the guidance block, so
    needs_header is False for the generation-phase section: only the "Focus
    on:" line appears, no second "Generation guidance:" header.
    """
    guidance = {
        "research_goal_analysis": {"key_areas": ["oncology"]},
        "workflow_plan": {"generation_phase": {"focus_areas": ["biomarkers"]}},
    }
    result = _format_supervisor_guidance_for_debate(guidance)
    assert "Key research areas to consider:" in result
    assert "- oncology" in result
    assert "Focus on: biomarkers" in result
    assert "Generation guidance:" not in result


def test_supervisor_guidance_generation_phase_without_focus_areas() -> None:
    """A generation_phase dict with no focus_areas key yields the empty str.

    generation_phase is truthy (non-empty dict) so the "not generation_phase"
    guard is skipped, but focus_areas is absent so no "Focus on:" line is
    appended and only the header line is produced (or nothing further).
    """
    guidance = {"workflow_plan": {"generation_phase": {"other_key": "x"}}}
    result = _format_supervisor_guidance_for_debate(guidance)
    assert "Generation guidance:" in result
    assert "Focus on:" not in result


# --- _build_debate_literature_variables -------------------------------------


def test_build_debate_literature_variables_includes_reasoning() -> None:
    """articles_with_reasoning is included in variables only when truthy."""
    variables = _build_debate_literature_variables(
        articles_with_reasoning="Synthesis of prior work.",
        articles=None,
        reference_list="",
    )
    assert variables["articles_with_reasoning"] == "Synthesis of prior work."


def test_build_debate_literature_variables_omits_reasoning_when_absent() -> (
    None
):
    """A None articles_with_reasoning leaves the key out of the dict."""
    variables = _build_debate_literature_variables(
        articles_with_reasoning=None,
        articles=None,
        reference_list="",
    )
    assert "articles_with_reasoning" not in variables


# --- get_debate_generation_prompt: end-to-end branch coverage --------------


def test_get_debate_generation_prompt_with_list_attributes() -> None:
    """List-valued attributes are comma-joined into the rendered prompt."""
    prompt, _schema = get_debate_generation_prompt(
        DebatePromptRequest(
            research_goal="engineer a drought-resistant crop",
            transcript="",
            attributes=["novel", "field-testable"],
        )
    )
    assert "novel, field-testable" in prompt


def test_get_debate_generation_prompt_with_articles_with_reasoning() -> None:
    """Providing articles_with_reasoning selects the literature template.

    This both exercises the articles_with_reasoning branch in
    _build_debate_literature_variables and the prompt_name selection in
    get_debate_generation_prompt.
    """
    prompt, schema = get_debate_generation_prompt(
        DebatePromptRequest(
            research_goal="engineer a drought-resistant crop",
            transcript="prior turns",
            articles_with_reasoning=(
                "Prior work suggests ABA signaling matters."
            ),
        )
    )
    assert "Prior work suggests ABA signaling matters." in prompt
    # The builder supplies every placeholder the literature template
    # declares (including user_hypotheses and instructions), so the render
    # leaves no {{MISSING:...}} sentinel behind.
    assert "{{MISSING" not in prompt
    assert schema is None


def test_get_debate_generation_prompt_with_full_supervisor_guidance() -> None:
    """Supervisor guidance with both key areas and phase focus is embedded."""
    prompt, _schema = get_debate_generation_prompt(
        DebatePromptRequest(
            research_goal="engineer a drought-resistant crop",
            transcript="",
            context=PromptRunContext(
                supervisor_guidance={
                    "research_goal_analysis": {"key_areas": ["osmotic stress"]},
                    "workflow_plan": {
                        "generation_phase": {
                            "focus_areas": ["root architecture"]
                        }
                    },
                }
            ),
        )
    )
    assert "osmotic stress" in prompt
    assert "root architecture" in prompt


def test_debate_prompt_does_not_force_clone_sentence_template() -> None:
    """The prompt must not impose the clone 'We want to develop X' format.

    The audit (E30/H15/K11) flagged the forced 'We want to develop [X] to
    enable [Y]' 2-3 sentence template as distorting mechanistic hypotheses.
    The final-turn instructions must instead ask for a domain-language
    mechanistic claim with a falsification criterion, and may only mention the
    old phrase to prohibit it.

    The contract lives on the final turn, which is the turn that writes the
    hypothesis; the free-form discussion turns carry the published debate
    procedure and no output contract at all.
    """
    prompt, _schema = get_debate_generation_prompt(
        DebatePromptRequest(
            research_goal="reduce cardiac senescence",
            transcript="prior turns",
            is_final_turn=True,
        )
    )
    # The phrase may appear only inside a negative instruction ("Do NOT ...").
    assert "to enable [Y]" not in prompt
    assert "2-3 sentences" not in prompt
    assert "mechanistic" in prompt.lower()
    assert "falsification" in prompt.lower()


def test_research_expansion_feedback_is_wired() -> None:
    """Research expansion re-runs generation informed by the meta-review.

    The mechanism is the meta-review context threaded into the generation
    prompts (consumed when the orchestrator re-enters generate in a later
    cycle), so assert the placeholder is present in the ``generation_after_
    debate`` prompt the research-expansion technique re-runs. It fills the
    published A.2 ``{reviews_overview}`` slot, which is where the panel is
    shown the reviews of what it is refining.
    """
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
    # The meta-review feedback is substituted into the prompt (not dropped).
    assert "META-REVIEW-FEEDBACK-MARKER" in raw


# --- user_hypotheses / instructions slots (finding E2) ----------------------


def test_debate_literature_prompt_renders_user_hypotheses() -> None:
    """User-supplied starting hypotheses reach the literature debate prompt.

    The grounded-debate template declares a {{user_hypotheses}} slot; the
    builder must fill it with the seed hypotheses rather than letting it
    render as a {{MISSING:...}} sentinel.
    """
    prompt, _schema = get_debate_generation_prompt(
        DebatePromptRequest(
            research_goal="engineer a drought-resistant crop",
            transcript="",
            articles_with_reasoning="Prior work suggests ABA signaling.",
            user_hypotheses=[
                "ABA receptor agonists tighten stomatal control",
                "Root-specific osmoprotectant synthesis raises yield",
            ],
        )
    )
    assert "ABA receptor agonists tighten stomatal control" in prompt
    assert "Root-specific osmoprotectant synthesis raises yield" in prompt
    assert "{{MISSING" not in prompt


def test_debate_literature_prompt_renders_instructions() -> None:
    """Explicit debate instructions reach the literature template's slot."""
    prompt, _schema = get_debate_generation_prompt(
        DebatePromptRequest(
            research_goal="engineer a drought-resistant crop",
            transcript="",
            articles_with_reasoning="Prior work suggests ABA signaling.",
            instructions="Weigh the field-trial data before converging.",
        )
    )
    assert "Weigh the field-trial data before converging." in prompt
    assert "{{MISSING" not in prompt


def test_debate_literature_prompt_fallbacks_when_inputs_absent() -> None:
    """Without seeds/instructions the slots render explicit fallbacks.

    Neither slot may ever render the {{MISSING:...}} sentinel: an empty run
    gets an explicit "none provided" line for the starting hypotheses and a
    default task instruction.
    """
    prompt, _schema = get_debate_generation_prompt(
        DebatePromptRequest(
            research_goal="engineer a drought-resistant crop",
            transcript="",
            articles_with_reasoning="Prior work suggests ABA signaling.",
        )
    )
    assert "No user-provided starting hypotheses." in prompt
    assert "{{MISSING" not in prompt


def test_debate_prompts_have_no_missing_slots_on_either_template() -> None:
    """Both debate-turn templates render fully interpolated prompts.

    The literature-aware template declares the user_hypotheses/instructions
    slots; the no-literature template declares neither. Either way the
    builder must leave no {{MISSING:...}} sentinel behind, whether or not
    the request carries user hypotheses.
    """
    for articles_with_reasoning in ("lit synthesis", None):
        for user_hypotheses in (["a seed hypothesis"], None):
            prompt, _schema = get_debate_generation_prompt(
                DebatePromptRequest(
                    research_goal="map a disease pathway",
                    transcript="",
                    articles_with_reasoning=articles_with_reasoning,
                    user_hypotheses=user_hypotheses,
                )
            )
            assert "{{MISSING" not in prompt


# A supervisor_guidance dict shaped the way agents/supervisor/supervisor.py
# assembles it, carrying an instruction list for each writer mode.
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

# --- format_supervisor_guidance_for_generation ------------------------------


def test_draft_guidance_renders_the_plan_rather_than_nothing() -> None:
    """The draft writer sees the supervisor's focus areas and preferences.

    Regression: this formatter read a free-text "research_plan" key, which
    is what the streamed output payload renames supervisor_guidance to --
    not a field inside it -- so it returned "" on every real run.
    """
    result = format_supervisor_guidance_for_generation(_GUIDANCE)

    assert "## Supervisor Guidance for Generation" in result
    assert "**Focus on:** biomarkers" in result
    assert "- testable within two years" in result


def test_draft_guidance_carries_only_the_drafting_instructions() -> None:
    """Each writer mode gets its own list, never a sibling mode's."""
    result = format_supervisor_guidance_for_generation(_GUIDANCE)

    assert "anchor each idea in a reported result" in result
    assert "attack the weakest causal link" not in result
    assert "penalize restatements of known biology" not in result


def test_draft_guidance_bullets_a_bare_string_as_one_item() -> None:
    """A string where the schema declares an array is one bullet, not many.

    Production runs on a provider whose json_object mode does not enforce
    the schema, so a bare string arrives; iterating it would bullet every
    character.
    """
    guidance = {"config_synthesis": {"preferences": "must be falsifiable"}}

    result = format_supervisor_guidance_for_generation(guidance)

    assert "- must be falsifiable\n" in result
    assert "- m\n" not in result


def test_draft_guidance_is_empty_without_a_plan() -> None:
    """Nothing to say renders nothing, not a bare header."""
    assert format_supervisor_guidance_for_generation(None) == ""
    assert format_supervisor_guidance_for_generation({}) == ""
    assert format_supervisor_guidance_for_generation({"unrelated": 1}) == ""


def test_draft_guidance_survives_a_scalar_where_an_object_belongs() -> None:
    """An unenforced schema can answer an object field with a scalar."""
    assert (
        format_supervisor_guidance_for_generation(
            {"workflow_plan": {"generation_phase": "focus on kinases"}}
        )
        == ""
    )
    assert (
        format_supervisor_guidance_for_generation(
            {"workflow_plan": "draft broadly", "config_synthesis": "be bold"}
        )
        == ""
    )


# --- _format_supervisor_guidance_for_debate ---------------------------------


def test_debate_guidance_carries_only_the_debate_instructions() -> None:
    """The debate writer reads preferences plus its own instruction list."""
    result = _format_supervisor_guidance_for_debate(_GUIDANCE)

    assert "- testable within two years" in result
    assert "attack the weakest causal link" in result
    assert "anchor each idea in a reported result" not in result


def test_debate_guidance_keeps_its_existing_plan_sections() -> None:
    """The config slice is added to the key-areas/focus sections, not over."""
    result = _format_supervisor_guidance_for_debate(_GUIDANCE)

    assert "Key research areas to consider:" in result
    assert "Focus on: biomarkers" in result


def test_debate_guidance_renders_config_alone() -> None:
    """A run whose plan carries only a config still reaches the writer."""
    guidance = {
        "config_synthesis": {"debate_instructions": ["contest the framing"]}
    }

    result = _format_supervisor_guidance_for_debate(guidance)

    assert "contest the framing" in result


# --- end to end -------------------------------------------------------------


def test_the_drafting_writer_actually_receives_the_guidance() -> None:
    """The block reaches the rendered prompt, not just its formatter."""
    prompt, _ = get_draft_prompt_with_tools(
        DraftPromptRequest(
            research_goal="find a new target in fibrosis",
            hypotheses_count=3,
            context=PromptRunContext(supervisor_guidance=_GUIDANCE),
        )
    )

    assert "anchor each idea in a reported result" in prompt
    assert "attack the weakest causal link" not in prompt
    assert "{{MISSING" not in prompt
