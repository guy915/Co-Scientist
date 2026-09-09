"""MO-2: recurring critique themes are a nested taxonomy, not a flat list.

Google's published meta-review critique
(``references/core/google-co-scientist/.../meta-review-critiques/
als-meta-review-critique.md``) organizes the recurring critiques as five
Roman-numbered themes, each holding named critique points, and several of
those points holding their own guidance sub-points -- three levels, not
one. Our schema flattened all of that to ``{theme, description,
frequency}`` (commit ``69d10874``, recorded as an accepted adaptation in
``docs/PARITY.md``'s ``META-CRITIQUE-TAXONOMY-001`` row); these pin the
nesting back on.

The caps come from the published artifact's own maxima -- five themes,
eight points under theme V ("General Advice Based on Common Critiques"),
five sub-points under theme I's "Specificity" -- so a taxonomy shaped like
the exemplar is never clipped by ``_truncate_oversized_arrays``.
"""

from typing import Any

from co_scientist.agents.meta_review.meta_review_themes import (
    normalize_recurring_themes,
)
from co_scientist.schemas.meta_review_schema import META_REVIEW_SCHEMA


def _themes_node() -> dict[str, Any]:
    """The schema node describing one ``recurring_themes`` entry."""
    node = META_REVIEW_SCHEMA["schema"]["properties"]["recurring_themes"]
    assert isinstance(node, dict)
    return node


def test_schema_nests_sub_themes_under_each_theme() -> None:
    """A theme entry declares sub-themes, which declare their own points."""
    item = _themes_node()["items"]
    sub_themes = item["properties"]["sub_themes"]
    assert "sub_themes" in item["required"]

    sub_item = sub_themes["items"]
    assert set(sub_item["properties"]) == {"theme", "description", "points"}
    assert sub_item["properties"]["points"]["items"] == {"type": "string"}


def test_schema_caps_do_not_clip_the_published_taxonomy() -> None:
    """The exemplar's own maxima fit inside every cap.

    Five themes, eight points under the largest theme, five sub-points
    under the largest point. A cap below any of these would truncate a
    taxonomy shaped exactly like the artifact it is derived from.
    """
    themes = _themes_node()
    sub_themes = themes["items"]["properties"]["sub_themes"]
    points = sub_themes["items"]["properties"]["points"]

    assert themes["maxItems"] >= 5
    assert sub_themes["maxItems"] >= 8
    assert points["maxItems"] >= 5


def test_normalize_carries_the_nesting_through() -> None:
    """Sub-themes and their points survive normalization."""
    normalized = normalize_recurring_themes(
        [
            {
                "theme": "Core Hypothesis and Mechanism",
                "description": "How the mechanism itself is argued.",
                "frequency": 4,
                "sub_themes": [
                    {
                        "theme": "Primary Driver vs. Consequence",
                        "description": "Proving the mechanism initiates.",
                        "points": ["Provide longitudinal evidence.", 7],
                    }
                ],
            }
        ]
    )

    assert normalized == [
        {
            "theme": "Core Hypothesis and Mechanism",
            "description": "How the mechanism itself is argued.",
            "frequency": "4",
            "sub_themes": [
                {
                    "theme": "Primary Driver vs. Consequence",
                    "description": "Proving the mechanism initiates.",
                    "points": ["Provide longitudinal evidence.", "7"],
                }
            ],
        }
    ]


def test_normalize_tolerates_a_flat_entry_from_an_older_checkpoint() -> None:
    """A resumed run's flat theme gains an empty sub-theme list, not a crash.

    ``meta_review`` is checkpointed state, so a run interrupted before
    this schema existed resumes carrying the flat three-field shape.
    """
    normalized = normalize_recurring_themes(
        [
            {
                "theme": "mitochondrial dysfunction",
                "description": "recurs across the reviewed pool",
                "frequency": "3",
            },
            "oxidative stress",
        ]
    )

    assert normalized == [
        {
            "theme": "mitochondrial dysfunction",
            "description": "recurs across the reviewed pool",
            "frequency": "3",
            "sub_themes": [],
        },
        {
            "theme": "oxidative stress",
            "description": "",
            "frequency": "",
            "sub_themes": [],
        },
    ]


def test_normalize_tolerates_junk_in_the_nested_positions() -> None:
    """json_object mode enforces nothing, so every nested shape is a guess."""
    normalized = normalize_recurring_themes(
        [
            {"theme": "t", "sub_themes": "not a list"},
            {
                "theme": "u",
                "sub_themes": ["a bare sub-theme", {"points": "not a list"}],
            },
        ]
    )

    assert normalized[0]["sub_themes"] == []
    assert normalized[1]["sub_themes"] == [
        {"theme": "a bare sub-theme", "description": "", "points": []},
        {"theme": "", "description": "", "points": []},
    ]
