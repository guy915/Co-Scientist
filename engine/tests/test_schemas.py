from co_scientist import constants
from co_scientist.schemas import get_schema_for_prompt
from co_scientist.schemas.review import REVIEW_BATCH_SCHEMA, REVIEW_SCHEMA

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

    Structurally asserts the NIH Specific Aims page: an introduction, an
    array of aims each with aim/rationale/approach, and an impact statement --
    all schema-required so a response omitting them is rejected.
    """
    schema = get_schema_for_prompt("research_overview")
    assert schema is not None
    body = schema.get("schema", schema)
    # nih_specific_aims is a top-level required field.
    assert "nih_specific_aims" in body["required"]
    aims = body["properties"]["nih_specific_aims"]
    # The page's three required sections.
    assert set(aims["required"]) == {"introduction", "aims", "impact"}
    # Each aim requires the grant-style aim / rationale / approach triple.
    aim_item = aims["properties"]["aims"]["items"]
    assert set(aim_item["required"]) == {"aim", "rationale", "approach"}
