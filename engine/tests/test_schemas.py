from co_scientist import constants
from co_scientist.schemas import get_schema_for_prompt
from co_scientist.schemas.generation import (
    GENERATION_SCHEMA,
    HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA,
)
from co_scientist.schemas.review import (
    DEEP_VERIFICATION_SCHEMA,
    FULL_REVIEW_SCHEMA,
    REVIEW_BATCH_SCHEMA,
    REVIEW_SCHEMA,
)

# The paper's five default output criteria (SSR §1). "relevance" is the
# engine's name for alignment with the research goal.
_DEFAULT_CRITERIA = {
    "relevance",  # alignment
    "plausibility",
    "novelty",
    "testability",
    "safety",
}


def test_deep_verification_top_k_constant() -> None:
    assert constants.DEEP_VERIFICATION_TOP_K == 3
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
