import json

from co_scientist import constants
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
    """Introduction/recent_findings are required in both generation schemas.

    Every published proposal opens with an Introduction and a Recent
    findings and related research section before the mechanism
    (docs/CORPUS-EXTRACTION.md, hypotheses/als-generation-output.md --
    34 lines, sha256 025d46737463); no field carried this before (MO-6).
    """
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
    """safety_and_toxicity is required in both generation schemas (MO-10).

    The published proposal itself carries a pharmacological safety and
    toxicity section (docs/CORPUS-EXTRACTION.md, validated-outputs/kira6-
    detailed-output-validated.md -- 220 lines, sha256 b5a22b590874); no
    proposer-side field carried this before, distinct from the reviewer's
    safety_ethical_concerns (dual-use/ethics, REVIEW_SCHEMA).
    """
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
