# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Co-Scientist: AI Co-Scientist framework reimplemented with LangGraph.

This package provides a clean, modular implementation of the AI Co-Scientist
framework using LangGraph for workflow orchestration.

Key features:
- Drop-in replacement for the original AI-CoScientist
- Prompts stored as markdown files for easy modification
- Parallel execution of reviews and evolution
- Native LangSmith integration for observability
- Clean separation of concerns with typed state management

Example usage:
    >>> from co_scientist import HypothesisGenerator
    >>>
    >>> generator = HypothesisGenerator(
    ...     model_name="gemini/gemini-2.5-flash",
    ...     max_iterations=1,
    ...     initial_hypotheses_count=5,
    ...     evolution_max_count=3
    ... )
    >>>
    >>> result = await generator.generate_hypotheses(
    ...     research_goal="Develop novel approaches for early cancer detection",
    ...     progress_callback=lambda phase, data: print(f"{phase}: {data}")
    ... )
    >>>
    >>> for hyp in result["hypotheses"]:
    ...     print(f"- {hyp['text']} (score: {hyp['score']})")
"""

import sys

# ensure Python version compatibility
if sys.version_info < (3, 10):
    raise RuntimeError("Co-Scientist requires Python >= 3.10. "
                       "Please upgrade to Python 3.10 or newer.")

# pylint: disable=wrong-import-position
from co_scientist.generator import HypothesisGenerator
from co_scientist.models import Hypothesis, HypothesisReview, ExecutionMetrics
from co_scientist.state import WorkflowState, WorkflowConfig
from co_scientist.cache import (
    clear_cache,
    get_cache_stats,
    clear_node_cache,
    get_node_cache_stats,
)
from co_scientist.console import ConsoleReporter
from co_scientist.config import ToolRegistry, get_tool_registry
# pylint: enable=wrong-import-position

__version__ = "0.2.0"
__all__ = [
    "HypothesisGenerator",
    "Hypothesis",
    "HypothesisReview",
    "ExecutionMetrics",
    "WorkflowState",
    "WorkflowConfig",
    "ConsoleReporter",
    "clear_cache",
    "get_cache_stats",
    "clear_node_cache",
    "get_node_cache_stats",
    "ToolRegistry",
    "get_tool_registry",
]
