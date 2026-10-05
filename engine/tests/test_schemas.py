from __future__ import annotations

import json

import pytest

from co_scientist.agents.generation.citations import (
    build_reference_index,
    hypothesis_from_llm_output,
    resolve_citation_keys,
)
from co_scientist.constants import strip_citation_markers
from co_scientist.models import Article, GenerationMethod
from co_scientist.schemas.generation import (
    GENERATION_SCHEMA,
    HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA,
    MAX_TITLE_CHARS,
)
from co_scientist.schemas.review import (
    DEEP_VERIFICATION_SCHEMA,
    FULL_REVIEW_SCHEMA,
    PER_AXIS_REVIEW_PARTS,
    REVIEW_BATCH_SCHEMA,
    REVIEW_SCHEMA,
)
from co_scientist.schemas.synthesis import EVOLUTION_SCHEMA


def test_review_score_axes_are_correctness_first() -> None:
    """Schema property insertion order is the order the model reads the axes."""
    single_scores = REVIEW_SCHEMA["schema"]["properties"]["scores"]
    assert list(single_scores["properties"]) == [
        "scientific_soundness",
        "plausibility",
        "novelty",
        "testability",
        "potential_impact",
        "relevance",
        "safety",
        "clarity",
    ]


def test_optional_properties_stay_out_of_required() -> None:
    """Closed schemas must declare optional fields without requiring them."""
    review_item = REVIEW_BATCH_SCHEMA["schema"]["properties"]["reviews"][
        "items"
    ]
    full = FULL_REVIEW_SCHEMA["schema"]
    for node, name in (
        (review_item, "comparative_notes"),
        (full, "go_no_go_recommendation"),
        (full, "time_to_verdict"),
    ):
        assert name in node["properties"], f"{name} no longer declared"
        assert name not in node["required"], f"{name} became required"


def test_generation_schemas_require_authored_fields() -> None:
    generation_item = GENERATION_SCHEMA["schema"]["properties"]["hypotheses"][
        "items"
    ]
    synthesis_item = HYPOTHESIS_VALIDATION_SYNTHESIS_SCHEMA["schema"][
        "properties"
    ]["hypotheses"]["items"]
    evolution_node = EVOLUTION_SCHEMA["schema"]
    for node in (generation_item, synthesis_item):
        for name in (
            "category",
            "introduction",
            "recent_findings",
            "safety_and_toxicity",
        ):
            assert name in node["properties"], f"{name} no longer declared"
            assert name in node["required"], f"{name} no longer required"
    for node in (generation_item, synthesis_item, evolution_node):
        assert "title" in node["required"]
        assert node["properties"]["title"]["maxLength"] == MAX_TITLE_CHARS


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


def _used_article(
    title: str = "Title",
    authors: list[str] | None = None,
    year: int | None = 2023,
) -> Article:
    return Article(
        title=title,
        authors=authors if authors is not None else ["Jane Q. Smith"],
        year=year,
        url="",
        used_in_analysis=True,
    )


@pytest.mark.parametrize(
    ("grounding", "expected"),
    [
        ("Grounded in [C1].", ["C1"]),
        ("cite [C99] and [C1]", ["C1"]),
        ("uses [C2] then [C1]", ["C2", "C1"]),
        ("[C2] ... [C1] ... [C2]", ["C2", "C1"]),
        ("[C10] then [C1]", ["C10", "C1"]),
        (None, []),
        ("", []),
        ("[C7] [C8]", []),
        ("[c1]", []),
        ("[C]", []),
        ("[C1x]", []),
        ("[ C1]", []),
        ("[C 1]", []),
        ("C1", []),
        ("[CC1]", []),
    ],
)
def test_resolve_citation_keys_matches_only_known_bracketed_keys(
    grounding: str | None, expected: list[str]
) -> None:
    sources = {
        "C1": {"title": "A"},
        "C2": {"title": "B"},
        "C10": {"title": "ten"},
    }
    assert list(resolve_citation_keys(grounding, sources)) == expected


@pytest.mark.parametrize(
    ("authors", "year", "label"),
    [
        (["Jane Q. Smith"], 2023, "Smith et al., 2023"),
        (["Mary van der Berg"], 2023, "Berg et al., 2023"),
        ([], 2020, "Unknown et al., 2020"),
    ],
)
def test_reference_index_labels_papers_by_last_name_and_year(
    authors: list[str], year: int, label: str
) -> None:
    idx = build_reference_index(
        [_used_article(title="T", authors=authors, year=year)], None
    )
    assert idx.text == f"[C1] {label} — T"


def test_reference_index_without_year_falls_back_to_title() -> None:
    long_title = "A very long title that exceeds fifty chars for the fallback"
    art = _used_article(title=long_title, authors=["Bob Lee"], year=None)
    idx = build_reference_index([art], None)
    assert idx.text == f"[C1] {long_title[:50]} — {long_title[:80]}"


def test_reference_index_numbers_used_papers_before_enrichment() -> None:
    skip = Article(title="Skip", year=2000, used_in_analysis=False)
    use = _used_article(title="Use", authors=["C D"], year=2001)
    enrichment = [
        {
            "display": "INDRA: KRAS -> RAF1",
            "tool_id": "indra",
            "data": {"belief": 0.9},
        },
        {
            "display": "Private result excerpt",
            "tool_id": "private_corpus",
            "source_type": "private_document",
            "data": {"private": True},
        },
        {},
    ]
    idx = build_reference_index([skip, use], enrichment)
    assert list(idx.sources) == ["C1", "C2", "C3", "C4"]
    assert idx.sources["C1"]["title"] == "Use"
    assert idx.sources["C2"]["type"] == "knowledge_graph"
    assert idx.sources["C3"]["type"] == "private_document"
    assert idx.sources["C4"] == {
        "type": "knowledge_graph",
        "display": "External source",
        "tool_id": "",
        "data": {},
    }
    resolved = resolve_citation_keys("Supported by [C1] and [C2].", idx.sources)
    assert resolved["C2"] is idx.sources["C2"]


def test_reference_index_is_empty_without_sources() -> None:
    assert build_reference_index(None, None).is_empty()
    assert build_reference_index([], []).is_empty()


def test_hypothesis_from_llm_output_carries_authored_fields() -> None:
    hyp = hypothesis_from_llm_output(
        {
            "hypothesis": "X inhibits Y.",
            "title": "X-Mediated Suppression of Y",
            "introduction": "ALS is a fatal neurodegenerative disease.",
            "recent_findings": "TDP-43 mislocalization is well documented.",
            "safety_and_toxicity": "Limited human safety data exists for X.",
            "experiment": {
                "steps": ["Script the assay.", "Run the pilot."],
                "go_criterion": "Effect size >= 0.5.",
                "no_go_criterion": "Effect size < 0.2.",
            },
        },
        sources={},
        generation_method=GenerationMethod.DEBATE,
    )
    assert hyp.title == "X-Mediated Suppression of Y"
    assert hyp.introduction == "ALS is a fatal neurodegenerative disease."
    assert hyp.recent_findings == "TDP-43 mislocalization is well documented."
    assert hyp.safety_and_toxicity == "Limited human safety data exists for X."
    assert hyp.experiment == (
        "1. Script the assay.\n2. Run the pilot."
        "\n**Go:** Effect size >= 0.5."
        "\n**No-Go:** Effect size < 0.2."
    )


def test_hypothesis_from_llm_output_defaults_missing_fields() -> None:
    hyp = hypothesis_from_llm_output(
        {"hypothesis": "X inhibits Y.", "experiment": "old-style paragraph."},
        sources={},
        generation_method=GenerationMethod.DEBATE,
    )
    assert hyp.title is None
    assert hyp.introduction is None
    assert hyp.recent_findings is None
    assert hyp.experiment == "old-style paragraph."


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Recent studies (Smith et al. 1999) show that this is true.",
            "Recent studies  show that this is true.",
        ),
        (
            "The method was adopted by (Smith, 1999, 2001; Johnson, 2002).",
            "The method was adopted by .",
        ),
        (
            "Smith et al. (2019) first proposed this mechanism.",
            " first proposed this mechanism.",
        ),
        (
            "This was shown by (Smith and Jones, 2021).",
            "This was shown by .",
        ),
        ("This was shown previously [12].", "This was shown previously ."),
        (
            "Multiple groups reported this [3,4].",
            "Multiple groups reported this .",
        ),
        ("Supported by prior work [C1] and [C12].", None),
        ("Full protocol details are provided (see Methods).", None),
        ("There are no references in this text.", None),
    ],
)
def test_strip_citation_markers_removes_only_foreign_citations(
    text: str, expected: str | None
) -> None:
    assert strip_citation_markers(text) == (expected or text)
