"""Co-Scientist: a LangGraph reimplementation of Google's AI Co-Scientist.

This package provides a clean, modular implementation of Google's AI
Co-Scientist framework using LangGraph for workflow orchestration.

Key features:
- Drop-in replacement for the original AI-CoScientist
- Prompts stored as markdown files for easy modification
- Parallel execution of reviews and evolution
- In-memory LLM token/cost/latency telemetry (see ``llm_telemetry``)
- Clean separation of concerns with typed state management

Example usage:
    >>> from co_scientist import HypothesisGenerator
    >>>
    >>> generator = HypothesisGenerator(
    ...     model_name="deepseek/deepseek-v4-flash",
    ...     max_iterations=1,
    ...     initial_hypotheses_count=5,
    ...     evolution_max_count=3
    ... )
    >>>
    >>> result = await generator.generate_hypotheses(
    ...     research_goal="Develop novel approaches for early cancer detection",
    ...     callbacks=RunCallbacks(
    ...         progress=lambda phase, data: print(f"{phase}: {data}")
    ...     ),
    ... )
    >>>
    >>> for hyp in result["hypotheses"]:
    ...     print(f"- {hyp['text']} (score: {hyp['score']})")
"""

from co_scientist.cache import (
    clear_cache,
    clear_node_cache,
    get_cache_stats,
    get_node_cache_stats,
)
from co_scientist.config import ToolRegistry, get_tool_registry
from co_scientist.generator import (
    GeneratorOptions,
    HypothesisGenerator,
    RunCallbacks,
)
from co_scientist.models import ExecutionMetrics, Hypothesis, HypothesisReview
from co_scientist.state import WorkflowState

# Keep this in sync with the [project] version in pyproject.toml; the two
# are not read from a single source of truth.
__version__ = "0.2.0"
__all__ = [
    "ExecutionMetrics",
    "GeneratorOptions",
    "Hypothesis",
    "HypothesisGenerator",
    "HypothesisReview",
    "RunCallbacks",
    "ToolRegistry",
    "WorkflowState",
    "clear_cache",
    "clear_node_cache",
    "get_cache_stats",
    "get_node_cache_stats",
    "get_tool_registry",
]
