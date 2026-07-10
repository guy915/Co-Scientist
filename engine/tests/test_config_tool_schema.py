"""Tests for the ``recency_years`` -> ``starting_year`` parameter mapping.

``config/schema.py`` (and ``test_config_schema.py``) exercise the general
``from_dict`` default-filling behavior of the ``tool_schema`` dataclasses.
This file targets the one piece of real logic in the module: converting a
canonical ``recency_years`` lookback window into an absolute
``starting_year`` when a tool's ``parameter_mapping`` requests it, both
directly (``_recency_years_to_starting_year``) and through
``ToolConfig.map_parameters``.
"""

import datetime

from co_scientist.config.tool_schema import (
    ToolConfig,
    _recency_years_to_starting_year,
)

# --- _recency_years_to_starting_year --------------------------------------


def test_recency_years_to_starting_year_positive_value() -> None:
    """A positive lookback window converts to an absolute starting year."""
    current_year = datetime.datetime.now().year
    assert _recency_years_to_starting_year(7) == current_year - 7


def test_recency_years_to_starting_year_zero_is_none() -> None:
    """A zero lookback window has no meaningful starting year."""
    assert _recency_years_to_starting_year(0) is None


def test_recency_years_to_starting_year_negative_is_none() -> None:
    """A negative lookback window has no meaningful starting year."""
    assert _recency_years_to_starting_year(-3) is None


# --- ToolConfig.map_parameters: no mapping configured ----------------------


def test_map_parameters_without_mapping_returns_as_is() -> None:
    """With no parameter_mapping configured, params pass through unchanged."""
    tool = ToolConfig(server="s1", mcp_tool_name="search")
    result = tool.map_parameters({"query": "cancer", "max_papers": 5})
    assert result == {"query": "cancer", "max_papers": 5}


# --- ToolConfig.map_parameters: recency_years -> starting_year -------------


def test_map_parameters_converts_recency_years_to_starting_year() -> None:
    """recency_years maps to starting_year via the absolute-year helper."""
    tool = ToolConfig(
        server="s1",
        mcp_tool_name="search",
        parameter_mapping={"recency_years": "starting_year"},
    )
    current_year = datetime.datetime.now().year

    result = tool.map_parameters({"recency_years": 5})

    assert result == {"starting_year": current_year - 5}


def test_map_parameters_recency_years_zero_maps_to_none() -> None:
    """A zero recency_years value maps starting_year to None."""
    tool = ToolConfig(
        server="s1",
        mcp_tool_name="search",
        parameter_mapping={"recency_years": "starting_year"},
    )
    result = tool.map_parameters({"recency_years": 0})
    assert result == {"starting_year": None}


def test_map_parameters_renames_without_recency_conversion() -> None:
    """A plain rename (not recency_years->starting_year) passes value as-is."""
    tool = ToolConfig(
        server="s1",
        mcp_tool_name="search",
        parameter_mapping={"max_papers": "max_results"},
    )
    result = tool.map_parameters({"max_papers": 10})
    assert result == {"max_results": 10}


def test_map_parameters_null_mapping_drops_parameter() -> None:
    """A parameter explicitly mapped to null in YAML is dropped entirely."""
    tool = ToolConfig(
        server="s1",
        mcp_tool_name="search",
        parameter_mapping={"unused_param": None},
    )
    result = tool.map_parameters({"unused_param": "x", "query": "cancer"})
    assert result == {"query": "cancer"}


def test_map_parameters_unmapped_key_uses_canonical_name() -> None:
    """A canonical key absent from parameter_mapping keeps its own name."""
    tool = ToolConfig(
        server="s1",
        mcp_tool_name="search",
        parameter_mapping={"max_papers": "max_results"},
    )
    result = tool.map_parameters({"query": "cancer"})
    assert result == {"query": "cancer"}
