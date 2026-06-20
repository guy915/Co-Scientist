from co_scientist import constants
from co_scientist.schemas import get_schema_for_prompt


def test_deep_verification_top_k_constant() -> None:
    assert constants.DEEP_VERIFICATION_TOP_K == 3
    assert constants.RESEARCH_OVERVIEW_TOP_K == 10


def test_deep_verification_schema_registered() -> None:
    schema = get_schema_for_prompt("deep_verification")
    assert schema is not None
    # JSON-schema 'properties' must declare probes + verdict.
    props = schema["schema"]["properties"] if "schema" in schema else schema[
        "properties"]
    assert "probes" in props
    assert "verdict" in props


def test_research_overview_schema_registered() -> None:
    schema = get_schema_for_prompt("research_overview")
    assert schema is not None
    props = schema["schema"]["properties"] if "schema" in schema else schema[
        "properties"]
    assert "overview" in props
    assert "nih_specific_aims" in props
