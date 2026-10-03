from __future__ import annotations

import json

from co_scientist import constants
from co_scientist.agents.generation.citations import (
    ReferenceIndex,
    build_reference_index,
    hypothesis_from_llm_output,
    resolve_citation_keys,
)
from co_scientist.constants import strip_citation_markers
from co_scientist.models import Article, GenerationMethod
from co_scientist.schemas import get_schema_for_prompt
from co_scientist.schemas.generation import (
    GENERATION_SCHEMA,
    HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA,
    MAX_TITLE_CHARS,
)
from co_scientist.schemas.review import (
    DEEP_VERIFICATION_SCHEMA,
    FEASIBILITY_STEPS_MAX_ITEMS,
    FULL_REVIEW_SCHEMA,
    PER_AXIS_REVIEW_PARTS,
    REVIEW_BATCH_SCHEMA,
    REVIEW_SCHEMA,
    REVIEWS_SUMMARY_PARTS,
)
from co_scientist.schemas.synthesis import EVOLUTION_SCHEMA

_DEFAULT_CRITERIA = {
    "relevance",
    "plausibility",
    "novelty",
    "testability",
    "safety",
}


def test_research_overview_top_k_constant() -> None:
    assert constants.RESEARCH_OVERVIEW_TOP_K == 10


def test_deep_verification_schema_registered() -> None:
    schema = get_schema_for_prompt("deep_verification")
    assert schema is not None
    props = (
        schema["schema"]["properties"]
        if "schema" in schema
        else schema["properties"]
    )
    assert "probes" in props
    assert "verdict" in props


def test_research_overview_schema_registered() -> None:
    schema = get_schema_for_prompt("research_overview")
    assert schema is not None
    props = (
        schema["schema"]["properties"]
        if "schema" in schema
        else schema["properties"]
    )
    assert "overview" in props
    assert "nih_specific_aims" in props


def test_review_scores_include_all_default_criteria() -> None:
    single_scores = REVIEW_SCHEMA["schema"]["properties"]["scores"]
    batch_scores = REVIEW_BATCH_SCHEMA["schema"]["properties"]["reviews"][
        "items"
    ]["properties"]["scores"]
    for scores in (single_scores, batch_scores):
        required = set(scores["required"])
        assert required >= _DEFAULT_CRITERIA, (
            f"missing default criteria: {_DEFAULT_CRITERIA - required}"
        )
        for criterion in _DEFAULT_CRITERIA:
            assert scores["properties"][criterion]["type"] == "integer"


def test_review_score_axes_are_correctness_first() -> None:
    """Schema property insertion order is the order the model reads the axes."""
    single_scores = REVIEW_SCHEMA["schema"]["properties"]["scores"]
    ordered = list(single_scores["properties"])
    assert ordered == [
        "scientific_soundness",
        "plausibility",
        "novelty",
        "testability",
        "potential_impact",
        "relevance",
        "safety",
        "clarity",
    ]


def test_research_overview_enforces_nih_specific_aims_format() -> None:
    schema = get_schema_for_prompt("research_overview")
    assert schema is not None
    body = schema.get("schema", schema)
    assert "nih_specific_aims" in body["required"]
    aims = body["properties"]["nih_specific_aims"]
    assert set(aims["required"]) == {
        "disease_description",
        "unmet_need",
        "proposed_solution",
        "aims",
        "pilot_evaluation",
    }
    aim_item = aims["properties"]["aims"]["items"]
    assert set(aim_item["required"]) == {
        "overarching_goal",
        "hypothesis",
        "reasoning",
    }


def test_optional_properties_stay_out_of_required() -> None:
    """Closed schemas must declare optional fields without requiring them."""
    review_item = REVIEW_BATCH_SCHEMA["schema"]["properties"]["reviews"][
        "items"
    ]
    optional = ((review_item, "comparative_notes"),)
    for node, name in optional:
        assert name in node["properties"], f"{name} no longer declared"
        assert name not in node["required"], f"{name} became required"


def test_generation_category_is_required() -> None:
    generation_item = GENERATION_SCHEMA["schema"]["properties"]["hypotheses"][
        "items"
    ]
    synthesis_item = HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA["schema"][
        "properties"
    ]["hypotheses"]["items"]
    for node in (generation_item, synthesis_item):
        assert "category" in node["properties"], "category no longer declared"
        assert "category" in node["required"], "category no longer required"


def test_generation_and_evolution_schemas_require_title() -> None:
    generation_item = GENERATION_SCHEMA["schema"]["properties"]["hypotheses"][
        "items"
    ]
    synthesis_item = HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA["schema"][
        "properties"
    ]["hypotheses"]["items"]
    evolution_node = EVOLUTION_SCHEMA["schema"]
    for node in (generation_item, synthesis_item, evolution_node):
        assert "title" in node["properties"], "title no longer declared"
        assert "title" in node["required"], "title no longer required"
        assert node["properties"]["title"]["maxLength"] == MAX_TITLE_CHARS
    assert (
        generation_item["properties"]["title"]
        is synthesis_item["properties"]["title"]
        is evolution_node["properties"]["title"]
    )


def test_generation_schemas_require_scene_setting() -> None:
    generation_item = GENERATION_SCHEMA["schema"]["properties"]["hypotheses"][
        "items"
    ]
    synthesis_item = HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA["schema"][
        "properties"
    ]["hypotheses"]["items"]
    for node in (generation_item, synthesis_item):
        for name in ("introduction", "recent_findings"):
            assert name in node["properties"], f"{name} no longer declared"
            assert name in node["required"], f"{name} no longer required"


def test_generation_schemas_require_safety_and_toxicity() -> None:
    generation_item = GENERATION_SCHEMA["schema"]["properties"]["hypotheses"][
        "items"
    ]
    synthesis_item = HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA["schema"][
        "properties"
    ]["hypotheses"]["items"]
    for node in (generation_item, synthesis_item):
        assert "safety_and_toxicity" in node["properties"]
        assert "safety_and_toxicity" in node["required"]


def test_assumption_support_vocabulary_is_unified() -> None:
    """Different enums for the same judgment silently hide one agent's
    failure state."""
    dv_enum = DEEP_VERIFICATION_SCHEMA["schema"]["properties"][
        "sub_assumptions"
    ]["items"]["properties"]["status"]["enum"]
    fr_enum = FULL_REVIEW_SCHEMA["schema"]["properties"]["assumptions"][
        "items"
    ]["properties"]["support"]["enum"]
    assert dv_enum == fr_enum == ["supported", "uncertain", "likely_false"]


def test_go_no_go_fields_are_declared_but_optional() -> None:
    node = FULL_REVIEW_SCHEMA["schema"]
    assert "go_no_go_recommendation" in node["properties"]
    assert "time_to_verdict" in node["properties"]
    assert "go_no_go_recommendation" not in node["required"]
    assert "time_to_verdict" not in node["required"]


def test_reviews_summary_carries_the_published_eight_parts() -> None:
    node = FULL_REVIEW_SCHEMA["schema"]["properties"]["reviews_summary"]
    assert list(node["properties"]) == list(REVIEWS_SUMMARY_PARTS)
    assert node["required"] == list(REVIEWS_SUMMARY_PARTS)


def test_reviews_summary_is_required_on_the_full_review() -> None:
    assert "reviews_summary" in FULL_REVIEW_SCHEMA["schema"]["required"]


def test_per_axis_sub_structure_stays_off_the_batch_review_schema() -> None:
    """Batch schema fields multiply output once per pool item and review
    cycle."""
    full = json.dumps(FULL_REVIEW_SCHEMA, sort_keys=True)
    initial = json.dumps(REVIEW_SCHEMA, sort_keys=True)
    batch = json.dumps(REVIEW_BATCH_SCHEMA, sort_keys=True)
    for part in PER_AXIS_REVIEW_PARTS:
        assert part in full, part
        assert part not in initial, part
        assert part not in batch, part


def test_feasibility_steps_is_a_bounded_list() -> None:
    """Prose newlines can break JSON; downgraded arrays also need defensive
    bounds."""
    node = FULL_REVIEW_SCHEMA["schema"]["properties"]["feasibility_steps"]
    assert node["type"] == "array"
    assert node["maxItems"] == FEASIBILITY_STEPS_MAX_ITEMS


def test_reviews_summary_lists_are_arrays_not_prose() -> None:
    """Bulleted prose can introduce raw newlines inside JSON strings."""
    props = FULL_REVIEW_SCHEMA["schema"]["properties"]["reviews_summary"][
        "properties"
    ]
    prose = {"executive_verdict", "conclusion"}
    for name, subschema in props.items():
        expected = "string" if name in prose else "array"
        assert subschema["type"] == expected, name


def _used_article(
    title: str = "Title",
    authors: list[str] | None = None,
    year: int | None = 2023,
    url: str = "",
) -> Article:
    return Article(
        title=title,
        authors=authors if authors is not None else ["Jane Q. Smith"],
        year=year,
        url=url,
        used_in_analysis=True,
    )


def test_resolve_single_existing_key() -> None:
    sources = {"C1": {"type": "paper", "title": "A"}}
    result = resolve_citation_keys("Grounded in [C1].", sources)
    assert result == {"C1": {"type": "paper", "title": "A"}}


def test_resolve_returns_same_dict_object() -> None:
    payload = {"type": "paper", "title": "A"}
    sources = {"C1": payload}
    result = resolve_citation_keys("see [C1]", sources)
    assert result["C1"] is payload


def test_resolve_multiple_keys() -> None:
    sources = {"C1": {"title": "A"}, "C2": {"title": "B"}}
    result = resolve_citation_keys("[C1] and [C2]", sources)
    assert set(result) == {"C1", "C2"}


def test_resolve_multi_digit_key() -> None:
    sources = {"C10": {"title": "ten"}, "C1": {"title": "one"}}
    result = resolve_citation_keys("[C10] then [C1]", sources)
    assert list(result) == ["C10", "C1"]


def test_resolve_missing_key_silently_dropped() -> None:
    sources = {"C1": {"title": "A"}}
    result = resolve_citation_keys("cite [C99] and [C1]", sources)
    assert list(result) == ["C1"]


def test_resolve_all_keys_missing_returns_empty() -> None:
    sources = {"C1": {"title": "A"}}
    result = resolve_citation_keys("[C7] [C8]", sources)
    assert result == {}


def test_resolve_preserves_first_occurrence_order() -> None:
    sources = {"C1": {"title": "A"}, "C2": {"title": "B"}}
    result = resolve_citation_keys("uses [C2] then [C1]", sources)
    assert list(result) == ["C2", "C1"]


def test_resolve_deduplicates_repeated_keys() -> None:
    sources = {"C1": {"title": "A"}, "C2": {"title": "B"}}
    result = resolve_citation_keys("[C2] ... [C1] ... [C2]", sources)
    assert list(result) == ["C2", "C1"]


def test_resolve_none_grounding_returns_empty() -> None:
    assert resolve_citation_keys(None, {"C1": {"title": "A"}}) == {}


def test_resolve_empty_grounding_returns_empty() -> None:
    assert resolve_citation_keys("", {"C1": {"title": "A"}}) == {}


def test_resolve_empty_sources_returns_empty() -> None:
    assert resolve_citation_keys("[C1]", {}) == {}


def test_resolve_lowercase_key_not_matched() -> None:
    assert resolve_citation_keys("[c1]", {"C1": {"title": "A"}}) == {}


def test_resolve_key_without_digit_not_matched() -> None:
    assert resolve_citation_keys("[C]", {"C1": {"title": "A"}}) == {}


def test_resolve_key_with_trailing_char_not_matched() -> None:
    assert resolve_citation_keys("[C1x]", {"C1": {"title": "A"}}) == {}


def test_resolve_key_with_inner_space_not_matched() -> None:
    assert resolve_citation_keys("[ C1]", {"C1": {"title": "A"}}) == {}
    assert resolve_citation_keys("[C 1]", {"C1": {"title": "A"}}) == {}


def test_resolve_unbracketed_key_not_matched() -> None:
    assert resolve_citation_keys("C1", {"C1": {"title": "A"}}) == {}


def test_resolve_double_c_key_not_matched() -> None:
    assert resolve_citation_keys("[CC1]", {"C1": {"title": "A"}}) == {}


def test_reference_index_is_empty_true_when_no_sources() -> None:
    assert ReferenceIndex(text="").is_empty() is True


def test_reference_index_is_empty_false_with_sources() -> None:
    idx = ReferenceIndex(text="[C1] foo", sources={"C1": {"title": "A"}})
    assert idx.is_empty() is False


def test_build_index_paper_label_with_year() -> None:
    idx = build_reference_index([_used_article(title="T")], None)
    assert idx.text == "[C1] Smith et al., 2023 — T"
    assert idx.sources == {
        "C1": {
            "type": "paper",
            "title": "T",
            "url": "",
            "authors": ["Jane Q. Smith"],
            "year": 2023,
        }
    }


def test_build_index_first_author_is_last_token() -> None:
    art = _used_article(title="T", authors=["Mary van der Berg"])
    idx = build_reference_index([art], None)
    assert idx.text == "[C1] Berg et al., 2023 — T"


def test_build_index_no_authors_uses_unknown() -> None:
    art = _used_article(title="T", authors=[], year=2020)
    idx = build_reference_index([art], None)
    assert idx.text == "[C1] Unknown et al., 2020 — T"


def test_build_index_no_year_label_falls_back_to_title() -> None:
    long_title = "A very long title that exceeds fifty chars for the fallback"
    art = _used_article(title=long_title, authors=["Bob Lee"], year=None)
    idx = build_reference_index([art], None)
    assert idx.text == f"[C1] {long_title[:50]} — {long_title[:80]}"


def test_build_index_skips_unused_articles() -> None:
    skip = Article(
        title="Skip", authors=["A B"], year=2000, used_in_analysis=False
    )
    use = _used_article(title="Use", authors=["C D"], year=2001)
    idx = build_reference_index([skip, use], None)
    assert list(idx.sources) == ["C1"]
    assert idx.sources["C1"]["title"] == "Use"


def test_build_index_papers_numbered_before_enrichment() -> None:
    art = _used_article(title="Use", authors=["C D"], year=2001)
    enrichment = [
        {
            "display": "INDRA: KRAS -> RAF1",
            "tool_id": "indra",
            "data": {"belief": 0.9},
        }
    ]
    idx = build_reference_index([art], enrichment)
    assert list(idx.sources) == ["C1", "C2"]
    assert idx.sources["C1"]["type"] == "paper"
    assert idx.sources["C2"] == {
        "type": "knowledge_graph",
        "display": "INDRA: KRAS -> RAF1",
        "tool_id": "indra",
        "data": {"belief": 0.9},
    }


def test_build_index_enrichment_display_defaults() -> None:
    idx = build_reference_index(None, [{}])
    assert idx.text == "[C1] External source"
    assert idx.sources["C1"] == {
        "type": "knowledge_graph",
        "display": "External source",
        "tool_id": "",
        "data": {},
    }


def test_build_index_preserves_private_document_type() -> None:
    idx = build_reference_index(
        None,
        [
            {
                "display": "Private result excerpt",
                "tool_id": "private_corpus",
                "source_type": "private_document",
                "data": {"document_id": "doc-1", "private": True},
            }
        ],
    )

    assert idx.sources["C1"]["type"] == "private_document"
    assert idx.sources["C1"]["data"]["private"] is True


def test_build_index_none_inputs_is_empty() -> None:
    idx = build_reference_index(None, None)
    assert idx.text == ""
    assert idx.sources == {}
    assert idx.is_empty() is True


def test_build_index_empty_lists_is_empty() -> None:
    idx = build_reference_index([], [])
    assert idx.is_empty() is True


def test_round_trip_build_then_resolve() -> None:
    art = _used_article(title="Use", authors=["C D"], year=2001)
    enrichment = [{"display": "KG fact", "tool_id": "indra", "data": {}}]
    idx = build_reference_index([art], enrichment)
    grounding = "Supported by [C1] and [C2]."
    resolved = resolve_citation_keys(grounding, idx.sources)
    assert list(resolved) == ["C1", "C2"]
    assert resolved["C1"] is idx.sources["C1"]
    assert resolved["C2"] is idx.sources["C2"]


def test_hypothesis_from_llm_output_carries_authored_title() -> None:
    """Coverage is owed only to reviewed ideas; new entrants first owe a
    review."""
    hyp = hypothesis_from_llm_output(
        {
            "hypothesis": "X inhibits Y.",
            "title": "X-Mediated Suppression of Y",
        },
        sources={},
        generation_method=GenerationMethod.DEBATE,
    )
    assert hyp.title == "X-Mediated Suppression of Y"


def test_hypothesis_from_llm_output_defaults_missing_title() -> None:
    """Coverage is owed only to reviewed ideas; new entrants first owe a
    review."""
    hyp = hypothesis_from_llm_output(
        {"hypothesis": "X inhibits Y."},
        sources={},
        generation_method=GenerationMethod.DEBATE,
    )
    assert hyp.title is None


def test_hypothesis_from_llm_output_carries_scene_setting() -> None:
    """Coverage is owed only to reviewed ideas; new entrants first owe a
    review."""
    hyp = hypothesis_from_llm_output(
        {
            "hypothesis": "X inhibits Y.",
            "introduction": "ALS is a fatal neurodegenerative disease.",
            "recent_findings": "TDP-43 mislocalization is well documented.",
        },
        sources={},
        generation_method=GenerationMethod.DEBATE,
    )
    assert hyp.introduction == "ALS is a fatal neurodegenerative disease."
    assert hyp.recent_findings == "TDP-43 mislocalization is well documented."


def test_hypothesis_from_llm_output_defaults_missing_scene_setting() -> None:
    """Coverage is owed only to reviewed ideas; new entrants first owe a
    review."""
    hyp = hypothesis_from_llm_output(
        {"hypothesis": "X inhibits Y."},
        sources={},
        generation_method=GenerationMethod.DEBATE,
    )
    assert hyp.introduction is None
    assert hyp.recent_findings is None


def test_hypothesis_from_llm_output_carries_safety_and_toxicity() -> None:
    """Coverage is owed only to reviewed ideas; new entrants first owe a
    review."""
    hyp = hypothesis_from_llm_output(
        {
            "hypothesis": "X inhibits Y.",
            "safety_and_toxicity": "Limited human safety data exists for X.",
        },
        sources={},
        generation_method=GenerationMethod.DEBATE,
    )
    assert hyp.safety_and_toxicity == "Limited human safety data exists for X."


def test_hypothesis_from_llm_output_formats_structured_experiment() -> None:
    """Coverage is owed only to reviewed ideas; new entrants first owe a
    review."""
    hyp = hypothesis_from_llm_output(
        {
            "hypothesis": "X inhibits Y.",
            "experiment": {
                "steps": ["Script the assay.", "Run the pilot."],
                "go_criterion": "Effect size >= 0.5.",
                "no_go_criterion": "Effect size < 0.2.",
            },
        },
        sources={},
        generation_method=GenerationMethod.DEBATE,
    )
    assert hyp.experiment == (
        "1. Script the assay.\n2. Run the pilot."
        "\n**Go:** Effect size >= 0.5."
        "\n**No-Go:** Effect size < 0.2."
    )


def test_hypothesis_from_llm_output_degrades_malformed_experiment() -> None:
    """Coverage is owed only to reviewed ideas; new entrants first owe a
    review."""
    hyp = hypothesis_from_llm_output(
        {"hypothesis": "X inhibits Y.", "experiment": "old-style paragraph."},
        sources={},
        generation_method=GenerationMethod.DEBATE,
    )
    assert hyp.experiment == "old-style paragraph."


def test_author_et_al_year_stripped() -> None:
    text = "Recent studies (Smith et al. 1999) show that this is true."
    assert (
        strip_citation_markers(text)
        == "Recent studies  show that this is true."
    )


def test_author_and_author_year_stripped() -> None:
    text = "The method was adopted by (Smith, 1999, 2001; Johnson, 2002)."
    assert strip_citation_markers(text) == "The method was adopted by ."


def test_bare_author_et_al_year_stripped() -> None:
    text = "Smith et al. (2019) first proposed this mechanism."
    assert strip_citation_markers(text) == " first proposed this mechanism."


def test_and_joined_authors_year_stripped() -> None:
    text = "This was shown by (Smith and Jones, 2021)."
    assert strip_citation_markers(text) == "This was shown by ."


def test_numeric_bracket_single_stripped() -> None:
    text = "This mechanism was shown previously [12]."
    assert (
        strip_citation_markers(text) == "This mechanism was shown previously ."
    )


def test_numeric_bracket_list_stripped() -> None:
    text = "Multiple groups reported this [3,4]."
    assert strip_citation_markers(text) == "Multiple groups reported this ."


def test_our_own_reference_key_not_stripped() -> None:
    text = "This is supported by prior work [C1] and [C12]."
    assert strip_citation_markers(text) == text


def test_parenthetical_without_year_not_stripped() -> None:
    text = "Full protocol details are provided (see Methods)."
    assert strip_citation_markers(text) == text


def test_no_citations_unchanged() -> None:
    text = "There are no references in this text."
    assert strip_citation_markers(text) == text
