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
"""Generation node - creates initial hypotheses.

Main entry point for the LangGraph workflow. All generation logic
has been moved to the generation/ package for better organization.
"""
# pylint: disable=inconsistent-quotes

import logging
from typing import Any

from co_scientist.models import create_metrics_update
from co_scientist.state import WorkflowState
from co_scientist.nodes.generation import generate_hypotheses

logger = logging.getLogger(__name__)


async def generate_node(state: WorkflowState) -> dict[str, Any]:
    """LangGraph node for hypothesis generation.

    Delegates to generation coordinator which orchestrates all strategies:
    - Literature usage (standard or tool-based)
    - Debate generation (with or without literature review, depending on
      configuration and availability)

    Args:
        state: current workflow state

    Returns:
        dict with hypotheses, debate_transcripts, metrics, and message
    """
    logger.info("Starting generate node")

    # delegate to coordinator
    result = await generate_hypotheses(state)

    # add metrics
    hypothesis_count = result.get("hypothesis_count",
                                  len(result.get("hypotheses", [])))
    metrics = create_metrics_update(hypothesis_count=hypothesis_count)
    result["metrics"] = metrics

    logger.info("Generate node complete: %s",
                result.get('message', 'generated hypotheses'))

    return result
