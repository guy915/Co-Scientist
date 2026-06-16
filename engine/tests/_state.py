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
"""Factories for building WorkflowState and Hypothesis values in node tests.

The pipeline nodes read from and write to a large ``WorkflowState`` TypedDict.
``make_state`` returns a complete state populated with inert defaults so a test
only has to override the few fields it exercises.
"""

from typing import Any, cast

from co_scientist.models import ExecutionMetrics, Hypothesis
from co_scientist.state import WorkflowState


def make_hypothesis(text: str = "a hypothesis", **overrides: Any) -> Hypothesis:
    """Build a Hypothesis with the given text and field overrides.

    Args:
        text: The hypothesis text.
        **overrides: Any Hypothesis dataclass fields to override (e.g.
            ``elo_rating``, ``score``, ``reviews``).

    Returns:
        A Hypothesis instance.
    """
    fields: dict[str, Any] = {"text": text}
    fields.update(overrides)
    return Hypothesis(**fields)


def make_state(**overrides: Any) -> WorkflowState:
    """Build a complete WorkflowState with inert defaults.

    Args:
        **overrides: WorkflowState keys to override (e.g. ``hypotheses``,
            ``model_name``, ``current_iteration``).

    Returns:
        A WorkflowState with every key populated; overrides applied last.
    """
    base: dict[str, Any] = {
        "research_goal": "test research goal",
        "model_name": "test-model",
        "supervisor_model_name": "test-model",
        "max_iterations": 1,
        "initial_hypotheses_count": 2,
        "evolution_max_count": 2,
        "hypotheses": [],
        "current_iteration": 0,
        "supervisor_guidance": {},
        "meta_review": {},
        "removed_duplicates": [],
        "tournament_matchups": [],
        "evolution_details": [],
        "metrics": ExecutionMetrics(),
        "start_time": 0.0,
        "run_id": "test-run",
        "progress_callback": None,
        "messages": [],
        "preferences": None,
        "attributes": None,
        "constraints": None,
        "starting_hypotheses": None,
        "literature": None,
        "articles_with_reasoning": None,
        "literature_review_queries": None,
        "articles": None,
        "generation_corpus_slug": None,
        "debate_transcripts": None,
        "mcp_available": False,
        "pubmed_available": False,
        "enable_tool_calling_generation": False,
        "dev_test_lit_tools_isolation": False,
        "tool_registry": None,
        "context_enrichment_sources": None,
    }
    base.update(overrides)
    return cast(WorkflowState, base)
