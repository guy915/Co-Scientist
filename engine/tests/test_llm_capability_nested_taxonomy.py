"""The json_object shims reshape a genuinely nested schema, not just its top.

``META_REVIEW_SCHEMA``'s ``recurring_themes`` is the first schema in this
engine deep enough for the four provider-capability shims
(``_prune_unknown_properties``, ``_backfill_required_fields``,
``_truncate_oversized_arrays``, ``_truncate_oversized_strings``) to be
exercised below their first level: an object inside an array inside an
object, whose own properties include another array of objects, whose items
hold an array of strings.

Every case here drives the REAL schema rather than a synthetic one, and
each ends at ``_backfill_and_validate`` -- the assembled pipeline the
production downgrade path actually runs -- because four passing unit calls
do not prove the response validates. The offline backend cannot stand in
for this: it fills every array with exactly one item, so a taxonomy it
produces never overruns a cap and never omits a nested required field.
"""

from typing import Any

import pytest

from co_scientist import llm_json_attempt
from co_scientist.llm_json import (
    _backfill_required_fields,
    _prune_unknown_properties,
    _truncate_oversized_arrays,
)
from co_scientist.llm_json_truncate_strings import _truncate_oversized_strings
from co_scientist.schemas.meta_review_schema import META_REVIEW_SCHEMA

_SCHEMA: dict[str, Any] = META_REVIEW_SCHEMA["schema"]


def _theme(**overrides: Any) -> dict[str, Any]:
    """One well-formed ``recurring_themes`` entry, with overrides applied."""
    theme: dict[str, Any] = {
        "theme": "Core Hypothesis and Mechanism",
        "description": "How the proposed mechanism itself is argued.",
        "frequency": "very common",
        "sub_themes": [_sub_theme()],
    }
    theme.update(overrides)
    return theme


def _sub_theme(**overrides: Any) -> dict[str, Any]:
    """One well-formed ``sub_themes`` entry, with overrides applied."""
    sub: dict[str, Any] = {
        "theme": "Primary Driver vs. Consequence",
        "description": "Whether the mechanism initiates or follows.",
        "points": ["Provide evidence for the temporal sequence."],
    }
    sub.update(overrides)
    return sub


def _themes_node() -> dict[str, Any]:
    """The ``recurring_themes`` array schema node."""
    node = _SCHEMA["properties"]["recurring_themes"]
    assert isinstance(node, dict)
    return node


def test_prune_drops_an_invented_key_two_levels_down() -> None:
    """A key invented inside a sub-theme is dropped, not left to fail."""
    result: dict[str, Any] = {
        "recurring_themes": [
            _theme(
                sub_themes=[
                    _sub_theme(example_reviews=["review 3"], severity="high")
                ]
            )
        ]
    }

    _prune_unknown_properties(result, _SCHEMA)

    sub = result["recurring_themes"][0]["sub_themes"][0]
    assert set(sub) == {"theme", "description", "points"}


def test_backfill_fills_a_required_field_two_levels_down() -> None:
    """A sub-theme missing its required ``description`` is filled in place."""
    sub = _sub_theme()
    del sub["description"]
    result: dict[str, Any] = {"recurring_themes": [_theme(sub_themes=[sub])]}

    _backfill_required_fields(result, _SCHEMA)

    assert result["recurring_themes"][0]["sub_themes"][0]["description"] == ""


def test_backfill_fills_a_missing_sub_theme_array() -> None:
    """A theme that omits ``sub_themes`` entirely gets an empty list.

    The whole point of nesting is that the model may not produce it; a
    flat answer must degrade to a flat taxonomy rather than failing the
    whole response.
    """
    theme = _theme()
    del theme["sub_themes"]
    result: dict[str, Any] = {"recurring_themes": [theme]}

    _backfill_required_fields(result, _SCHEMA)

    assert result["recurring_themes"][0]["sub_themes"] == []


def test_truncate_cuts_an_oversized_array_inside_a_nested_object() -> None:
    """An over-long ``points`` list -- an array in an object in an array."""
    cap = _themes_node()["items"]["properties"]["sub_themes"]["items"][
        "properties"
    ]["points"]["maxItems"]
    over = [f"point {index}" for index in range(cap + 4)]
    result: dict[str, Any] = {
        "recurring_themes": [_theme(sub_themes=[_sub_theme(points=over)])]
    }

    _truncate_oversized_arrays(result, _SCHEMA)

    points = result["recurring_themes"][0]["sub_themes"][0]["points"]
    assert points == over[:cap]


def test_truncate_cuts_an_oversized_sub_theme_array() -> None:
    """The middle level is capped too, not only the leaf and the root."""
    cap = _themes_node()["items"]["properties"]["sub_themes"]["maxItems"]
    result: dict[str, Any] = {
        "recurring_themes": [
            _theme(sub_themes=[_sub_theme() for _ in range(cap + 3)])
        ]
    }

    _truncate_oversized_arrays(result, _SCHEMA)

    assert len(result["recurring_themes"][0]["sub_themes"]) == cap


def test_truncate_strings_recurses_into_a_sub_theme() -> None:
    """A ``maxLength`` two levels down is enforced by the string shim."""
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "recurring_themes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "sub_themes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "theme": {
                                        "type": "string",
                                        "maxLength": 10,
                                    }
                                },
                            },
                        }
                    },
                },
            }
        },
    }
    result: dict[str, Any] = {
        "recurring_themes": [
            {"sub_themes": [{"theme": "a" * 40}, {"theme": "short"}]}
        ]
    }

    _truncate_oversized_strings(result, schema)

    subs = result["recurring_themes"][0]["sub_themes"]
    assert len(subs[0]["theme"]) == 10
    assert subs[1]["theme"] == "short"


def _minimal_valid_response() -> dict[str, Any]:
    """The smallest meta-review answer the real schema accepts."""
    return {
        "meta_review_summary": "",
        "recurring_themes": [],
        "strengths": [],
        "weaknesses": [],
        "process_assessment": {
            "generation_process": "",
            "review_process": "",
            "evolution_process": "",
        },
        "strategic_recommendations": [],
        "potential_connections": [],
        "candidate_comparison": {
            "thematic_summary": "",
            "axes": [],
            "ideas": [],
        },
        "existing_solutions_comparison": {
            "summary": "",
            "axes": [],
            "rows": [],
        },
        "main_research_directions": "",
    }


def test_a_mangled_nested_taxonomy_validates_after_the_shims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every nested failure at once, through the real downgrade pipeline.

    An invented key two levels down, a required field missing two levels
    down, an over-long array inside a nested object -- the combination a
    json_object-mode model actually returns. The assertion that matters is
    that ``_backfill_and_validate`` does not raise.
    """
    monkeypatch.setattr(
        llm_json_attempt,
        "_supports_json_schema_response_format",
        lambda _model: False,
    )
    caps = _themes_node()["items"]["properties"]["sub_themes"]
    point_cap = caps["items"]["properties"]["points"]["maxItems"]
    mangled = _sub_theme(
        points=[f"point {index}" for index in range(point_cap + 3)],
        example_reviews=["review 3"],
    )
    del mangled["description"]
    response = _minimal_valid_response()
    response["recurring_themes"] = [
        _theme(sub_themes=[mangled for _ in range(caps["maxItems"] + 2)])
    ]

    llm_json_attempt._backfill_and_validate(
        response, META_REVIEW_SCHEMA, "openrouter/minimax/minimax-m3:free"
    )

    sub = response["recurring_themes"][0]["sub_themes"][0]
    assert sub["description"] == ""
    assert "example_reviews" not in sub
    assert len(sub["points"]) == point_cap


def test_the_published_taxonomy_shape_survives_the_shims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exemplar's own maxima pass through untouched.

    Google's critique carries five themes, eight points under its largest
    theme and five sub-points under its largest point. A cap set below any
    of those would silently clip a faithful answer, so the discriminating
    check is that a taxonomy shaped exactly like the artifact comes back
    unchanged.
    """
    monkeypatch.setattr(
        llm_json_attempt,
        "_supports_json_schema_response_format",
        lambda _model: False,
    )
    published = [
        _theme(
            sub_themes=[
                _sub_theme(points=[f"point {i}" for i in range(5)])
                for _ in range(8)
            ]
        )
        for _ in range(5)
    ]
    response = _minimal_valid_response()
    response["recurring_themes"] = published

    llm_json_attempt._backfill_and_validate(
        response, META_REVIEW_SCHEMA, "openrouter/minimax/minimax-m3:free"
    )

    assert len(response["recurring_themes"]) == 5
    assert len(response["recurring_themes"][0]["sub_themes"]) == 8
    assert len(response["recurring_themes"][0]["sub_themes"][0]["points"]) == 5
