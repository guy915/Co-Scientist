from __future__ import annotations

import datetime

from co_scientist.config.schema import (
    ToolConfig,
    resolve_content_params,
)


def test_resolve_content_params_resolves_multiple_keys() -> None:
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


def test_map_parameters_converts_recency_years_to_starting_year() -> None:
    tool = ToolConfig(
        server="s1",
        mcp_tool_name="search",
        parameter_mapping={"recency_years": "starting_year"},
    )
    result = tool.map_parameters({"recency_years": 5})
    assert result == {"starting_year": datetime.datetime.now().year - 5}
