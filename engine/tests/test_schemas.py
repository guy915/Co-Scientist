"""Offline contracts for schemas."""

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

# The paper's five default output criteria (SSR §1). "relevance" is the
# engine's name for alignment with the research goal.
_DEFAULT_CRITERIA = {
    "relevance",  # alignment
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
    # JSON-schema 'properties' must declare probes + verdict.
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
    """Every default output criterion is a scored axis (SSR §1).

    Alignment (relevance), plausibility, novelty, testability, and safety must
    all be required integer scores in both the single and batch review schemas,
    so a review that omits any of the five is not a complete response.
    """
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
    """R14-17: axis order mirrors Google's published review appendix.

    Google's per-hypothesis appendix always orders its four review axes
    Correctness -> Novelty -> Feasibility -> Impact potential; this
    system's extra axes (relevance, safety, clarity) trail. Property
    order in a JSON Schema object node is dict insertion order, which is
    what the model sees the properties listed in -- a pure ordering
    change, not a shape change, so this test only checks order.
    """
    single_scores = REVIEW_SCHEMA["schema"]["properties"]["scores"]
    ordered = list(single_scores["properties"])
    assert ordered == [
        "scientific_soundness",  # Correctness (1 of 2)
        "plausibility",  # Correctness (2 of 2)
        "novelty",  # Novelty
        "testability",  # Feasibility
        "potential_impact",  # Impact potential
        "relevance",
        "safety",
        "clarity",
    ]


def test_research_overview_enforces_nih_specific_aims_format() -> None:
    """The overview must produce the NIH Specific Aims structure (SSR §4).

    Structurally asserts the page Google's published exemplars print: the
    disease/unmet-need/solution preamble, the aims, and the closing pilot
    study -- all schema-required so a response omitting them is rejected.
    ``test_published_artifact_shapes.py`` is what ties this vocabulary back
    to those exemplars; this test only pins that the schema enforces it.
    """
    schema = get_schema_for_prompt("research_overview")
    assert schema is not None
    body = schema.get("schema", schema)
    # nih_specific_aims is a top-level required field.
    assert "nih_specific_aims" in body["required"]
    aims = body["properties"]["nih_specific_aims"]
    assert set(aims["required"]) == {
        "disease_description",
        "unmet_need",
        "proposed_solution",
        "aims",
        "pilot_evaluation",
    }
    # Every aim states its goal, the hypothesis it tests, and why.
    aim_item = aims["properties"]["aims"]["items"]
    assert set(aim_item["required"]) == {
        "overarching_goal",
        "hypothesis",
        "reasoning",
    }


def test_optional_properties_stay_out_of_required() -> None:
    """The deliberately-optional schema keys must not become required.

    ``schemas.builders.obj`` derives ``required`` from ``properties``, which
    is right for all but a few of the object nodes here; these are the
    exceptions, and nothing else notices if an ``optional=`` argument is
    dropped -- the model simply starts being rejected for omitting a field
    it was told it could omit. Each is closed
    (``additionalProperties: False``), so the key must stay declared as
    well as stay out of ``required``.
    """
    review_item = REVIEW_BATCH_SCHEMA["schema"]["properties"]["reviews"][
        "items"
    ]
    optional = ((review_item, "comparative_notes"),)
    for node, name in optional:
        assert name in node["properties"], f"{name} no longer declared"
        assert name not in node["required"], f"{name} became required"


def test_generation_category_is_required() -> None:
    """Category is required in both generation schemas that carry it (K7).

    Categorization was inconsistent while the field was optional and absent
    from the prompt body. The field is now required, and the templates
    present its value contract (see the prompt-contract tests).
    """
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
    """R14-12: every hypothesis-producing call authors its own title.

    Google's published titles are a compact, authored noun phrase, never a
    truncated first sentence -- shared by identity across GENERATION_SCHEMA,
    HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA, and EVOLUTION_SCHEMA, the same
    three call sites _EXPERIMENT_FIELD already backs (R14-20). Bounded by
    maxLength so a schema-enforcing provider cannot return an unbounded
    string; app/app/engine_adapter/drain/hypothesis_title.py clamps again
    defensively for the json_object downgrade, which does not enforce it.
    """
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
    # Shared by identity, not restated -- the same pattern _EXPERIMENT_FIELD
    # already establishes for these three schemas.
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
    """Deep verification and full review score one judgement, one way.

    Both ask whether the evidence backs one assumption -- deep
    verification's ``sub_assumptions[].status`` and full review's
    ``assumptions[].support`` -- and used to disagree on the third value
    (``unsupported`` vs. ``likely_false``) despite both prompts defining
    it identically ("the evidence points against it"). One vocabulary
    now backs both, so a reader cannot be written against one enum and
    silently miss the other's third state.
    """
    dv_enum = DEEP_VERIFICATION_SCHEMA["schema"]["properties"][
        "sub_assumptions"
    ]["items"]["properties"]["status"]["enum"]
    fr_enum = FULL_REVIEW_SCHEMA["schema"]["properties"]["assumptions"][
        "items"
    ]["properties"]["support"]["enum"]
    assert dv_enum == fr_enum == ["supported", "uncertain", "likely_false"]


def test_go_no_go_fields_are_declared_but_optional() -> None:
    """R14-15: Google's own files carry this framing in only 8 of 19.

    Declared (a downgraded json_object caller can still populate them by
    name) but not required -- treating them as mandatory would make this
    schema stricter than the published system it is modeling.
    """
    node = FULL_REVIEW_SCHEMA["schema"]
    assert "go_no_go_recommendation" in node["properties"]
    assert "time_to_verdict" in node["properties"]
    assert "go_no_go_recommendation" not in node["required"]
    assert "time_to_verdict" not in node["required"]


def test_reviews_summary_carries_the_published_eight_parts() -> None:
    """R14-14: the published per-hypothesis "Reviews summary" block.

    Every populated file in the 19-hypothesis published run prints the
    same eight numbered parts under "Reviews summary" (Executive Verdict
    through Conclusion). Ours used to carry only ``review_summary``, one
    2-3 sentence string on the initial screen, so the block had no source
    at all. Declared on the full review rather than the initial screen
    because the initial screen's result travels as a typed dataclass
    field (``HypothesisReview.review_summary: str``) that several prompt
    projections read as a string, while a full review's whole raw
    response reaches the drain through ``hypothesis.enrichments``.
    """
    node = FULL_REVIEW_SCHEMA["schema"]["properties"]["reviews_summary"]
    assert list(node["properties"]) == list(REVIEWS_SUMMARY_PARTS)
    assert node["required"] == list(REVIEWS_SUMMARY_PARTS)


def test_reviews_summary_is_required_on_the_full_review() -> None:
    """Optional and unnamed by the prompt, nothing ever asked for it.

    A field the prompt does not mention and the schema does not require
    is a declaration, not an output. The argument is structural: no local
    store holds a provider-backed full review produced after the block
    shipped, so its fill rate was never measured either way. Required
    here, and named by ``full_review.md``'s own numbered instructions,
    which is the pairing that makes requiring it safe (see
    ``test_full_review_prompt_names_every_required_field``).
    """
    assert "reviews_summary" in FULL_REVIEW_SCHEMA["schema"]["required"]


def test_per_axis_sub_structure_stays_off_the_batch_review_schema() -> None:
    """R14-17's per-axis parts live on the full review and nowhere else.

    ``REVIEW_SCHEMA`` and ``REVIEW_BATCH_SCHEMA`` share
    ``_SCORES_SCHEMA``/``_DETAILED_FEEDBACK_SCHEMA`` by identity, and the
    batch call reviews the whole pool in one turn -- so a field added
    there costs its output tokens once per pool item, per review cycle.
    The full review already runs once per mature hypothesis, so the same
    content added here multiplies by nothing.
    """
    full = json.dumps(FULL_REVIEW_SCHEMA, sort_keys=True)
    initial = json.dumps(REVIEW_SCHEMA, sort_keys=True)
    batch = json.dumps(REVIEW_BATCH_SCHEMA, sort_keys=True)
    for part in PER_AXIS_REVIEW_PARTS:
        assert part in full, part
        assert part not in initial, part
        assert part not in batch, part


def test_feasibility_steps_is_a_bounded_list() -> None:
    """The published "Steps to Test the Idea" is a list, and model output.

    A prose paragraph invites a raw newline inside a JSON string value,
    which discards the whole response; an unbounded array lets a
    json_object-downgrade answer inflate without limit.
    """
    node = FULL_REVIEW_SCHEMA["schema"]["properties"]["feasibility_steps"]
    assert node["type"] == "array"
    assert node["maxItems"] == FEASIBILITY_STEPS_MAX_ITEMS


def test_reviews_summary_lists_are_arrays_not_prose() -> None:
    """Parts 2-7 are bulleted in every published exemplar; 1 and 8 are prose.

    Asking for prose where the published shape is a list invites a raw
    newline inside a JSON string value, which discards the whole
    response.
    """
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
    """Build an Article flagged for analysis (the only kind indexed)."""
    return Article(
        title=title,
        authors=authors if authors is not None else ["Jane Q. Smith"],
        year=year,
        url=url,
        used_in_analysis=True,
    )


# --- resolve_citation_keys: happy path -------------------------------------


def test_resolve_single_existing_key() -> None:
    """A single ``[C*]`` key present in sources resolves to its metadata."""
    sources = {"C1": {"type": "paper", "title": "A"}}
    result = resolve_citation_keys("Grounded in [C1].", sources)
    assert result == {"C1": {"type": "paper", "title": "A"}}


def test_resolve_returns_same_dict_object() -> None:
    """Resolved value is the exact source dict (not a copy)."""
    payload = {"type": "paper", "title": "A"}
    sources = {"C1": payload}
    result = resolve_citation_keys("see [C1]", sources)
    assert result["C1"] is payload


def test_resolve_multiple_keys() -> None:
    """Multiple distinct keys all resolve."""
    sources = {"C1": {"title": "A"}, "C2": {"title": "B"}}
    result = resolve_citation_keys("[C1] and [C2]", sources)
    assert set(result) == {"C1", "C2"}


def test_resolve_multi_digit_key() -> None:
    """Multi-digit keys such as ``[C10]`` resolve correctly."""
    sources = {"C10": {"title": "ten"}, "C1": {"title": "one"}}
    result = resolve_citation_keys("[C10] then [C1]", sources)
    assert list(result) == ["C10", "C1"]


# --- resolve_citation_keys: unresolved / missing handling ------------------


def test_resolve_missing_key_silently_dropped() -> None:
    """A key in the text but absent from sources is silently dropped."""
    sources = {"C1": {"title": "A"}}
    result = resolve_citation_keys("cite [C99] and [C1]", sources)
    assert list(result) == ["C1"]


def test_resolve_all_keys_missing_returns_empty() -> None:
    """When no cited key exists in sources, the result is empty."""
    sources = {"C1": {"title": "A"}}
    result = resolve_citation_keys("[C7] [C8]", sources)
    assert result == {}


# --- resolve_citation_keys: ordering and duplicates ------------------------


def test_resolve_preserves_first_occurrence_order() -> None:
    """Keys are returned in first-occurrence order, not source order."""
    sources = {"C1": {"title": "A"}, "C2": {"title": "B"}}
    result = resolve_citation_keys("uses [C2] then [C1]", sources)
    assert list(result) == ["C2", "C1"]


def test_resolve_deduplicates_repeated_keys() -> None:
    """A key cited more than once appears exactly once in the result."""
    sources = {"C1": {"title": "A"}, "C2": {"title": "B"}}
    result = resolve_citation_keys("[C2] ... [C1] ... [C2]", sources)
    assert list(result) == ["C2", "C1"]


# --- resolve_citation_keys: guards -----------------------------------------


def test_resolve_none_grounding_returns_empty() -> None:
    """``None`` grounding short-circuits to an empty map."""
    assert resolve_citation_keys(None, {"C1": {"title": "A"}}) == {}


def test_resolve_empty_grounding_returns_empty() -> None:
    """Empty-string grounding short-circuits to an empty map."""
    assert resolve_citation_keys("", {"C1": {"title": "A"}}) == {}


def test_resolve_empty_sources_returns_empty() -> None:
    """Empty sources short-circuit to an empty map even with cited keys."""
    assert resolve_citation_keys("[C1]", {}) == {}


# --- resolve_citation_keys: malformed keys ---------------------------------
# The matching regex is ``\[C\d+\]`` - uppercase C, one-or-more digits, with
# the brackets immediately abutting. The following must NOT match.


def test_resolve_lowercase_key_not_matched() -> None:
    """``[c1]`` (lowercase c) is not a valid key."""
    assert resolve_citation_keys("[c1]", {"C1": {"title": "A"}}) == {}


def test_resolve_key_without_digit_not_matched() -> None:
    """``[C]`` (no digit) is not a valid key."""
    assert resolve_citation_keys("[C]", {"C1": {"title": "A"}}) == {}


def test_resolve_key_with_trailing_char_not_matched() -> None:
    """``[C1x]`` (trailing non-digit before ``]``) is not a valid key."""
    assert resolve_citation_keys("[C1x]", {"C1": {"title": "A"}}) == {}


def test_resolve_key_with_inner_space_not_matched() -> None:
    """``[ C1]`` and ``[C 1]`` (whitespace inside brackets) are not valid."""
    assert resolve_citation_keys("[ C1]", {"C1": {"title": "A"}}) == {}
    assert resolve_citation_keys("[C 1]", {"C1": {"title": "A"}}) == {}


def test_resolve_unbracketed_key_not_matched() -> None:
    """A bare ``C1`` without brackets is not a valid key."""
    assert resolve_citation_keys("C1", {"C1": {"title": "A"}}) == {}


def test_resolve_double_c_key_not_matched() -> None:
    """``[CC1]`` (double C) is not a valid key."""
    assert resolve_citation_keys("[CC1]", {"C1": {"title": "A"}}) == {}


# --- ReferenceIndex --------------------------------------------------------


def test_reference_index_is_empty_true_when_no_sources() -> None:
    """``is_empty`` is True when the sources dict is empty."""
    assert ReferenceIndex(text="").is_empty() is True


def test_reference_index_is_empty_false_with_sources() -> None:
    """``is_empty`` is False when at least one source is present."""
    idx = ReferenceIndex(text="[C1] foo", sources={"C1": {"title": "A"}})
    assert idx.is_empty() is False


# --- build_reference_index: basic shape ------------------------------------


def test_build_index_paper_label_with_year() -> None:
    """A paper with authors and a year uses the ``Last et al., YEAR`` label."""
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
    """The label author is the last whitespace-delimited token of authors[0]."""
    art = _used_article(title="T", authors=["Mary van der Berg"])
    idx = build_reference_index([art], None)
    assert idx.text == "[C1] Berg et al., 2023 — T"


def test_build_index_no_authors_uses_unknown() -> None:
    """With no authors, the label author falls back to ``Unknown``."""
    art = _used_article(title="T", authors=[], year=2020)
    idx = build_reference_index([art], None)
    assert idx.text == "[C1] Unknown et al., 2020 — T"


def test_build_index_no_year_label_falls_back_to_title() -> None:
    """Without a year, the label uses the first 50 characters of the title."""
    long_title = "A very long title that exceeds fifty chars for the fallback"
    art = _used_article(title=long_title, authors=["Bob Lee"], year=None)
    idx = build_reference_index([art], None)
    assert idx.text == f"[C1] {long_title[:50]} — {long_title[:80]}"


# --- build_reference_index: used_in_analysis filtering ---------------------


def test_build_index_skips_unused_articles() -> None:
    """Articles without ``used_in_analysis`` are excluded and not numbered."""
    skip = Article(
        title="Skip", authors=["A B"], year=2000, used_in_analysis=False
    )
    use = _used_article(title="Use", authors=["C D"], year=2001)
    idx = build_reference_index([skip, use], None)
    assert list(idx.sources) == ["C1"]
    assert idx.sources["C1"]["title"] == "Use"


# --- build_reference_index: shared key namespace ---------------------------


def test_build_index_papers_numbered_before_enrichment() -> None:
    """Papers occupy leading keys; enrichment sources follow in one space."""
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
    """An enrichment item missing fields gets default display and empty data."""
    idx = build_reference_index(None, [{}])
    assert idx.text == "[C1] External source"
    assert idx.sources["C1"] == {
        "type": "knowledge_graph",
        "display": "External source",
        "tool_id": "",
        "data": {},
    }


def test_build_index_preserves_private_document_type() -> None:
    """Private corpus sources remain distinguishable from knowledge graphs."""
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


# --- build_reference_index: empty inputs -----------------------------------


def test_build_index_none_inputs_is_empty() -> None:
    """Passing ``None`` for both inputs yields an empty index."""
    idx = build_reference_index(None, None)
    assert idx.text == ""
    assert idx.sources == {}
    assert idx.is_empty() is True


def test_build_index_empty_lists_is_empty() -> None:
    """Passing empty lists for both inputs yields an empty index."""
    idx = build_reference_index([], [])
    assert idx.is_empty() is True


# --- round-trip contract ---------------------------------------------------


def test_round_trip_build_then_resolve() -> None:
    """Keys produced by build_reference_index resolve back to their sources."""
    art = _used_article(title="Use", authors=["C D"], year=2001)
    enrichment = [{"display": "KG fact", "tool_id": "indra", "data": {}}]
    idx = build_reference_index([art], enrichment)
    grounding = "Supported by [C1] and [C2]."
    resolved = resolve_citation_keys(grounding, idx.sources)
    assert list(resolved) == ["C1", "C2"]
    assert resolved["C1"] is idx.sources["C1"]
    assert resolved["C2"] is idx.sources["C2"]


# --- hypothesis_from_llm_output ---------------------------------------------


def test_hypothesis_from_llm_output_carries_authored_title() -> None:
    """R14-12: the LLM-authored title reaches the constructed Hypothesis."""
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
    """A payload omitting title (json_object downgrade) degrades safely.

    The engine carries None through unvalidated -- the fallback to a
    derived title lives at the app's drain, the single point it is
    resolved, not here.
    """
    hyp = hypothesis_from_llm_output(
        {"hypothesis": "X inhibits Y."},
        sources={},
        generation_method=GenerationMethod.DEBATE,
    )
    assert hyp.title is None


def test_hypothesis_from_llm_output_carries_scene_setting() -> None:
    """The scene-setting fields (MO-6) reach the constructed Hypothesis."""
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
    """A payload omitting the fields (json_object downgrade) degrades safely."""
    hyp = hypothesis_from_llm_output(
        {"hypothesis": "X inhibits Y."},
        sources={},
        generation_method=GenerationMethod.DEBATE,
    )
    assert hyp.introduction is None
    assert hyp.recent_findings is None


def test_hypothesis_from_llm_output_carries_safety_and_toxicity() -> None:
    """The proposer's own safety assessment (MO-10) reaches the Hypothesis."""
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
    """R14-20: the structured experiment plan renders as prose on Hypothesis."""
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
    """A json_object-downgrade response with a string experiment survives."""
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
    """The name-outside-parens shape, e.g. 'Smith et al. (2019)'.

    This is the first regex alternative (paper-qa's own); every other
    author-year test here exercises the second (parenthesized) one, so
    this is the only test that would notice the first alternative going
    missing.
    """
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
