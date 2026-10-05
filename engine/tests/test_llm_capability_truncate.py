from __future__ import annotations

import json
from typing import Any

import pytest
from jsonschema.exceptions import ValidationError

from co_scientist.llm import CompletionSpec, call_llm_json
from co_scientist.llm.attempts import json_attempt
from co_scientist.llm.structured.validate import reshape_json_output
from co_scientist.schemas.planning import META_REVIEW_SCHEMA
from tests._llm_fake import disable_llm_cache as _disable_cache
from tests.test_llm_capability_shim import (
    _capture_acompletion,
    _completion,
    _patch_registry,
)

_LLM_CAPABILITY_NESTED_TAXONOMY_SCHEMA: dict[str, Any] = META_REVIEW_SCHEMA[
    "schema"
]


def _theme(**overrides: Any) -> dict[str, Any]:
    theme: dict[str, Any] = {
        "theme": "Core Hypothesis and Mechanism",
        "description": "How the proposed mechanism itself is argued.",
        "frequency": "very common",
        "sub_themes": [_sub_theme()],
    }
    theme.update(overrides)
    return theme


def _sub_theme(**overrides: Any) -> dict[str, Any]:
    sub: dict[str, Any] = {
        "theme": "Primary Driver vs. Consequence",
        "description": "Whether the mechanism initiates or follows.",
        "points": ["Provide evidence for the temporal sequence."],
    }
    sub.update(overrides)
    return sub


def _themes_node() -> dict[str, Any]:
    node = _LLM_CAPABILITY_NESTED_TAXONOMY_SCHEMA["properties"][
        "recurring_themes"
    ]
    assert isinstance(node, dict)
    return node


def test_prune_drops_an_invented_key_two_levels_down() -> None:
    result: dict[str, Any] = {
        "recurring_themes": [
            _theme(
                sub_themes=[
                    _sub_theme(example_reviews=["review 3"], severity="high")
                ]
            )
        ]
    }

    reshape_json_output(result, _LLM_CAPABILITY_NESTED_TAXONOMY_SCHEMA)

    sub = result["recurring_themes"][0]["sub_themes"][0]
    assert set(sub) == {"theme", "description", "points"}


def test_backfill_fills_a_required_field_two_levels_down() -> None:
    sub = _sub_theme()
    del sub["description"]
    result: dict[str, Any] = {"recurring_themes": [_theme(sub_themes=[sub])]}

    reshape_json_output(result, _LLM_CAPABILITY_NESTED_TAXONOMY_SCHEMA)

    assert result["recurring_themes"][0]["sub_themes"][0]["description"] == ""


def test_backfill_fills_a_missing_sub_theme_array() -> None:
    theme = _theme()
    del theme["sub_themes"]
    result: dict[str, Any] = {"recurring_themes": [theme]}

    reshape_json_output(result, _LLM_CAPABILITY_NESTED_TAXONOMY_SCHEMA)

    assert result["recurring_themes"][0]["sub_themes"] == []


def test_truncate_cuts_an_oversized_array_inside_a_nested_object() -> None:
    cap = _themes_node()["items"]["properties"]["sub_themes"]["items"][
        "properties"
    ]["points"]["maxItems"]
    over = [f"point {index}" for index in range(cap + 4)]
    result: dict[str, Any] = {
        "recurring_themes": [_theme(sub_themes=[_sub_theme(points=over)])]
    }

    reshape_json_output(result, _LLM_CAPABILITY_NESTED_TAXONOMY_SCHEMA)

    points = result["recurring_themes"][0]["sub_themes"][0]["points"]
    assert points == over[:cap]


def test_truncate_cuts_an_oversized_sub_theme_array() -> None:
    cap = _themes_node()["items"]["properties"]["sub_themes"]["maxItems"]
    result: dict[str, Any] = {
        "recurring_themes": [
            _theme(sub_themes=[_sub_theme() for _ in range(cap + 3)])
        ]
    }

    reshape_json_output(result, _LLM_CAPABILITY_NESTED_TAXONOMY_SCHEMA)

    assert len(result["recurring_themes"][0]["sub_themes"]) == cap


def test_truncate_strings_recurses_into_a_sub_theme() -> None:
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

    reshape_json_output(result, schema)

    subs = result["recurring_themes"][0]["sub_themes"]
    assert len(subs[0]["theme"]) == 10
    assert subs[1]["theme"] == "short"


def _minimal_valid_response() -> dict[str, Any]:
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
    monkeypatch.setattr(
        json_attempt,
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

    json_attempt._backfill_and_validate(
        response, META_REVIEW_SCHEMA, "openrouter/minimax/minimax-m3:free"
    )

    sub = response["recurring_themes"][0]["sub_themes"][0]
    assert sub["description"] == ""
    assert "example_reviews" not in sub
    assert len(sub["points"]) == point_cap


def test_the_published_taxonomy_shape_survives_the_shims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        json_attempt,
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

    json_attempt._backfill_and_validate(
        response, META_REVIEW_SCHEMA, "openrouter/minimax/minimax-m3:free"
    )

    assert len(response["recurring_themes"]) == 5
    assert len(response["recurring_themes"][0]["sub_themes"]) == 8
    assert len(response["recurring_themes"][0]["sub_themes"][0]["points"]) == 5


_LLM_CAPABILITY_TRUNCATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 5,
        },
        "group": {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 2,
                }
            },
        },
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "notes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 1,
                    }
                },
            },
        },
        "unbounded": {"type": "array", "items": {"type": "string"}},
    },
}


def test_truncate_drops_items_past_max_items() -> None:
    obj: dict[str, Any] = {"steps": ["a", "b", "c", "d", "e", "f"]}

    reshape_json_output(obj, _LLM_CAPABILITY_TRUNCATE_SCHEMA)

    assert obj == {"steps": ["a", "b", "c", "d", "e"]}


def test_truncate_recurses_into_an_array_inside_an_object_inside_an_array() -> (
    None
):
    obj: dict[str, Any] = {
        "sections": [
            {"notes": ["first", "second"]},
            {"notes": ["only one already"]},
        ]
    }

    reshape_json_output(obj, _LLM_CAPABILITY_TRUNCATE_SCHEMA)

    assert obj == {
        "sections": [
            {"notes": ["first"]},
            {"notes": ["only one already"]},
        ]
    }


def test_truncate_leaves_arrays_within_bound_untouched() -> None:
    obj: dict[str, Any] = {"steps": ["a", "b"]}

    reshape_json_output(obj, _LLM_CAPABILITY_TRUNCATE_SCHEMA)

    assert obj == {"steps": ["a", "b"]}


def test_truncate_ignores_arrays_without_max_items() -> None:
    obj: dict[str, Any] = {"unbounded": list("abcdefghij")}

    reshape_json_output(obj, _LLM_CAPABILITY_TRUNCATE_SCHEMA)

    assert obj == {"unbounded": list("abcdefghij")}


def test_truncate_ignores_non_list_values_under_an_array_schema() -> None:
    obj: dict[str, Any] = {"steps": "not a list"}

    reshape_json_output(obj, _LLM_CAPABILITY_TRUNCATE_SCHEMA)

    assert obj == {"steps": "not a list"}


class TestLlmCapabilityTruncate:
    def test_truncate_recurses_into_nested_objects(self) -> None:
        obj: dict[str, Any] = {"group": {"tags": ["x", "y", "z"]}}

        reshape_json_output(obj, _LLM_CAPABILITY_TRUNCATE_SCHEMA)

        assert obj == {"group": {"tags": ["x", "y"]}}

    def test_truncate_noop_for_non_dict_inputs(self) -> None:
        reshape_json_output(
            ["not", "a", "dict"], _LLM_CAPABILITY_TRUNCATE_SCHEMA
        )
        reshape_json_output({"a": 1}, "not a schema")


_LLM_CAPABILITY_TRUNCATE_STRINGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "maxLength": 20},
        "code": {"type": "string", "minLength": 3, "maxLength": 5},
        "group": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "maxLength": 10},
            },
        },
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "note": {"type": "string", "maxLength": 8},
                },
            },
        },
        "tags": {
            "type": "array",
            "items": {"type": "string", "maxLength": 6},
        },
        "unbounded": {"type": "string"},
    },
}


def test_truncate_cuts_a_string_past_max_length() -> None:
    obj: dict[str, Any] = {"title": "this is way too long a title"}

    reshape_json_output(obj, _LLM_CAPABILITY_TRUNCATE_STRINGS_SCHEMA)

    assert len(obj["title"]) <= 20


def test_truncate_prefers_a_word_boundary_near_the_limit() -> None:
    obj: dict[str, Any] = {"title": "abcdefghij klmnopqr stuvwxyz"}

    reshape_json_output(obj, _LLM_CAPABILITY_TRUNCATE_STRINGS_SCHEMA)

    assert obj["title"] == "abcdefghij klmnopqr"
    assert len(obj["title"]) <= 20
    assert not obj["title"].endswith(" ")


def test_truncate_hard_cuts_when_no_boundary_is_near() -> None:
    value = "onelongwordwithnospaceatall"
    obj: dict[str, Any] = {"title": value}

    reshape_json_output(obj, _LLM_CAPABILITY_TRUNCATE_STRINGS_SCHEMA)

    assert obj["title"] == value[:20]
    assert len(obj["title"]) == 20


def test_truncate_leaves_minlength_and_pattern_violations_untouched() -> None:
    obj: dict[str, Any] = {"code": "ab"}

    reshape_json_output(obj, _LLM_CAPABILITY_TRUNCATE_STRINGS_SCHEMA)

    assert obj["code"] == "ab"


def test_truncate_leaves_strings_within_bound_untouched() -> None:
    obj: dict[str, Any] = {"title": "short"}

    reshape_json_output(obj, _LLM_CAPABILITY_TRUNCATE_STRINGS_SCHEMA)

    assert obj["title"] == "short"


def test_truncate_ignores_strings_without_max_length() -> None:
    long_value = "x" * 500
    obj: dict[str, Any] = {"unbounded": long_value}

    reshape_json_output(obj, _LLM_CAPABILITY_TRUNCATE_STRINGS_SCHEMA)

    assert obj["unbounded"] == long_value


def test_truncate_recurses_into_an_array_of_objects() -> None:
    obj: dict[str, Any] = {
        "sections": [{"note": "way too long"}, {"note": "ok"}]
    }

    reshape_json_output(obj, _LLM_CAPABILITY_TRUNCATE_STRINGS_SCHEMA)

    assert len(obj["sections"][0]["note"]) <= 8
    assert obj["sections"][1]["note"] == "ok"


def test_truncate_recurses_into_an_array_of_strings() -> None:
    obj: dict[str, Any] = {"tags": ["short", "waytoolongtag"]}

    reshape_json_output(obj, _LLM_CAPABILITY_TRUNCATE_STRINGS_SCHEMA)

    assert obj["tags"][0] == "short"
    assert len(obj["tags"][1]) <= 6


def test_truncate_ignores_non_string_values_under_a_string_schema() -> None:
    obj: dict[str, Any] = {"title": 12345}

    reshape_json_output(obj, _LLM_CAPABILITY_TRUNCATE_STRINGS_SCHEMA)

    assert obj["title"] == 12345


class TestLlmCapabilityTruncateStrings:
    def test_truncate_recurses_into_nested_objects(self) -> None:
        obj: dict[str, Any] = {"group": {"name": "way too long a name"}}

        reshape_json_output(obj, _LLM_CAPABILITY_TRUNCATE_STRINGS_SCHEMA)

        assert len(obj["group"]["name"]) <= 10

    def test_truncate_noop_for_non_dict_inputs(self) -> None:
        reshape_json_output(
            ["not", "a", "dict"], _LLM_CAPABILITY_TRUNCATE_STRINGS_SCHEMA
        )
        reshape_json_output({"a": 1}, "not a schema")


_MAX_LENGTH_SCHEMA: dict[str, Any] = {
    "name": "capability_shim_max_length",
    "schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "maxLength": 20},
        },
        "required": ["title"],
    },
}

_LONG_TITLE = json.dumps({"title": "this title runs well past the cap"})


@pytest.mark.usefixtures("clear_capability_cache")
class TestLlmCapabilityTruncateStringsWiring:
    async def test_call_llm_json_truncates_oversized_string_on_downgrade(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """JSON-object providers can repeat the same overlong value on every
        retry."""
        _disable_cache(monkeypatch)
        _patch_registry(monkeypatch, supported=False)
        captured = _capture_acompletion(monkeypatch, [_completion(_LONG_TITLE)])

        result = await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name="test-model", json_schema=_MAX_LENGTH_SCHEMA
            ),
            max_attempts=2,
        )

        assert len(result["title"]) <= 20
        assert len(captured) == 1

    async def test_call_llm_json_no_truncate_for_supported_model(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Native schema providers reject overlong output; trimming there
        would hide an anomaly."""
        _disable_cache(monkeypatch)
        _patch_registry(monkeypatch, supported=True)
        long_title = _completion(_LONG_TITLE)
        _capture_acompletion(monkeypatch, [long_title, long_title])

        with pytest.raises(ValidationError):
            await call_llm_json(
                "a prompt",
                CompletionSpec(
                    model_name="test-model", json_schema=_MAX_LENGTH_SCHEMA
                ),
                max_attempts=2,
            )


_MAX_ITEMS_SCHEMA: dict[str, Any] = {
    "name": "capability_shim_max_items",
    "schema": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
            }
        },
        "required": ["steps"],
    },
}

_SIX_STEPS = json.dumps({"steps": ["a", "b", "c", "d", "e", "f"]})


@pytest.mark.usefixtures("clear_capability_cache")
class TestLlmCapabilityTruncateWiring:
    async def test_call_llm_json_truncates_oversized_array_on_downgrade(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _disable_cache(monkeypatch)
        _patch_registry(monkeypatch, supported=False)
        captured = _capture_acompletion(monkeypatch, [_completion(_SIX_STEPS)])

        result = await call_llm_json(
            "a prompt",
            CompletionSpec(
                model_name="test-model", json_schema=_MAX_ITEMS_SCHEMA
            ),
            max_attempts=2,
        )

        assert result == {"steps": ["a", "b", "c", "d", "e"]}
        assert len(captured) == 1

    async def test_call_llm_json_no_truncate_for_supported_model(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _disable_cache(monkeypatch)
        _patch_registry(monkeypatch, supported=True)
        six_steps = _completion(_SIX_STEPS)
        _capture_acompletion(monkeypatch, [six_steps, six_steps])

        with pytest.raises(ValidationError):
            await call_llm_json(
                "a prompt",
                CompletionSpec(
                    model_name="test-model", json_schema=_MAX_ITEMS_SCHEMA
                ),
                max_attempts=2,
            )
