"""Public behavior of tool content-parameter placeholder substitution."""

from typing import Any

import pytest

from co_scientist.config.content_params import resolve_content_params


@pytest.mark.parametrize(
    ("value", "context", "expected"),
    [
        ("plain string", {}, "plain string"),
        ("{unknown}", {}, "{unknown}"),
        ("{goal}", {"goal": ["a", "b"]}, ["a", "b"]),
        ("{goal}", {"goal": {"nested": 1}}, {"nested": 1}),
        ("{count}", {"count": 5}, 5),
        ("study {name}", {"name": "cancer"}, "study cancer"),
        (
            "prefix {goal} suffix",
            {"goal": ["a", "b"]},
            "prefix ['a', 'b'] suffix",
        ),
        ("{a}-{b}", {"a": "X", "b": "Y"}, "X-Y"),
        ("{a}-{b}", {"a": "{b}", "b": "Y"}, "Y-Y"),
        (
            "{known} and {unknown}",
            {"known": "value"},
            "value and {unknown}",
        ),
        (
            ["{topic}", "static", 3],
            {"topic": "genomics"},
            ["genomics", "static", 3],
        ),
        (["{nums}"], {"nums": [1, 2, 3]}, ["[1, 2, 3]"]),
        (42, {"x": "y"}, 42),
        (True, {"x": "y"}, True),
        ({"inner": "{x}"}, {"x": "y"}, {"inner": "{x}"}),
    ],
)
def test_resolve_content_parameter(
    value: Any, context: dict[str, Any], expected: Any
) -> None:
    """Typed whole values and string list entries follow distinct rules."""
    assert resolve_content_params({"value": value}, context) == {
        "value": expected
    }


def test_resolve_content_params_empty_params_returns_empty_dict() -> None:
    """An empty params dict resolves to an empty dict."""
    assert resolve_content_params({}, {"research_goal": "X"}) == {}


def test_resolve_content_params_resolves_multiple_keys() -> None:
    """Every key is resolved independently without changing the input."""
    params = {
        "query": "{research_goal}",
        "tags": ["{focus_areas}", "static-tag"],
        "limit": 10,
    }
    context = {"research_goal": "Cure cancer", "focus_areas": "immunotherapy"}
    assert resolve_content_params(params, context) == {
        "query": "Cure cancer",
        "tags": ["immunotherapy", "static-tag"],
        "limit": 10,
    }
    assert params["query"] == "{research_goal}"
    assert params["tags"] == ["{focus_areas}", "static-tag"]


def test_resolve_content_params_leaves_nested_containers_untouched() -> None:
    """Containers inside values pass through without recursive substitution."""
    nested = {"inner": "{x}"}
    result = resolve_content_params(
        {"nested": nested, "list": [nested]}, {"x": "y"}
    )
    assert result["nested"] is nested
    assert result["list"][0] is nested
