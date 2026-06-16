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
"""Reflection node - analyzes hypotheses against literature observations."""
# pylint: disable=inconsistent-quotes

import asyncio
import logging
from typing import Any

from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    LOW_TEMPERATURE,
    PROGRESS_REFLECTION_START,
    PROGRESS_REFLECTION_COMPLETE,
)
from co_scientist.llm import call_llm_json
from co_scientist.models import Hypothesis
from co_scientist.prompts import get_reflection_prompt
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


async def analyze_single_hypothesis(
    hypothesis: Hypothesis,
    articles_with_reasoning: str,
    model_name: str,
    hypothesis_index: int,
    total_count: int,
    run_id: str | None = None,
    tool_registry: Any | None = None,
) -> dict[str, Any] | None:
    """Analyze a single hypothesis against literature observations.

    Args:
        hypothesis: hypothesis to analyze
        articles_with_reasoning: literature review context
        model_name: llm model to use
        hypothesis_index: index for logging (1-based)
        total_count: total hypotheses count for logging
        run_id: optional run ID for saving prompts
        tool_registry: optional ToolRegistry for dynamic tool instructions

    Returns:
        dict with classification and reasoning, or None if failed
    """
    logger.debug("\n→ analyzing hypothesis %s/%s", hypothesis_index,
                 total_count)

    # Pre-fetch INDRA evidence for this hypothesis (non-critical, skip on
    # failure)
    indra_data = await _fetch_indra_for_hypothesis(
        hypothesis.text,
        tool_registry,
        hypothesis_index,
    )

    # Get reflection prompt (uses formatted text for LLM context)
    prompt, schema = get_reflection_prompt(
        articles_with_reasoning=articles_with_reasoning,
        hypothesis_text=hypothesis.text,
        tool_registry=tool_registry,
        indra_evidence=indra_data.get("prompt_text", ""),
    )

    # Save prompt to disk for debugging
    if run_id:
        from co_scientist.prompts import save_prompt_to_disk  # pylint: disable=import-outside-toplevel
        save_prompt_to_disk(
            run_id=run_id,
            prompt_name=f"reflection_{hypothesis_index}",
            content=prompt,
            metadata={
                "hypothesis_index": hypothesis_index,
                "total_count": total_count,
                "prompt_length_chars": len(prompt),
            },
        )

    try:
        # Call llm
        response = await call_llm_json(
            prompt=prompt,
            model_name=model_name,
            max_tokens=EXTENDED_MAX_TOKENS,
            temperature=LOW_TEMPERATURE,
            json_schema=schema,
        )

        classification = response.get("classification", "neutral")
        reasoning = response.get("reasoning", "")

        logger.debug("hypothesis %s classification: %s", hypothesis_index,
                     classification)

        return {
            "classification": classification,
            "reasoning": reasoning,
            "indra_enrichment_items": indra_data.get("enrichment_items", []),
        }

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Reflection failed for hypothesis %s: %s",
                     hypothesis_index, e)
        return None


async def reflection_node(state: WorkflowState) -> dict[str, Any]:
    """Analyze each hypothesis against literature observations.

    this node:
    1. for each generated hypothesis, calls the llm with reflection prompt
    2. analyzes if hypothesis provides novel causal explanation
    3. classifies as: already explained, other explanations more likely,
       missing piece, neutral, or disproved
    4. stores reflection metadata on each hypothesis

    Args:
        state: current workflow state

    Returns:
        dictionary with updated state fields
    """
    logger.debug("\n=== reflection node ===")
    logger.info("Analyzing hypotheses against literature observations")

    # Get articles with reasoning from state
    articles_with_reasoning = state.get("articles_with_reasoning")
    if not articles_with_reasoning:
        logger.warning(
            "No articles_with_reasoning in state, skipping reflection")
        return {}

    # Get hypotheses from state
    hypotheses = state.get("hypotheses", [])
    if not hypotheses:
        logger.warning("No hypotheses in state, skipping reflection")
        return {}

    logger.debug("analyzing %s hypotheses against literature", len(hypotheses))

    # Emit progress
    progress_callback = state.get("progress_callback")
    if progress_callback is not None:
        await progress_callback(
            "reflection_start",
            {
                "message": f"Analyzing {len(hypotheses)} hypotheses"
                           " against literature...",
                "progress": PROGRESS_REFLECTION_START,
                "hypotheses_count": len(hypotheses),
            },
        )

    # Analyze all hypotheses in parallel
    logger.info("Running %s reflection analyses in parallel", len(hypotheses))

    tool_registry = state.get("tool_registry")
    analysis_tasks = [
        analyze_single_hypothesis(
            hypothesis=hyp,
            articles_with_reasoning=articles_with_reasoning,
            model_name=state["model_name"],
            hypothesis_index=i + 1,
            total_count=len(hypotheses),
            run_id=state.get("run_id"),
            tool_registry=tool_registry,
        ) for i, hyp in enumerate(hypotheses)
    ]

    # Gather all results
    analysis_results = await asyncio.gather(*analysis_tasks)

    # Apply results to hypotheses
    for hypothesis, result in zip(hypotheses, analysis_results):
        if result:
            classification = result.get("classification", "neutral")
            reasoning = result.get("reasoning", "")
            hypothesis.reflection_notes = (
                f"{reasoning}\n\nClassification: {classification}")
            # Store knowledge graph evidence in enrichments (yaml-driven,
            # only present for biomedical configs)
            enrichment_items = result.get("indra_enrichment_items", [])
            if enrichment_items:
                hypothesis.enrichments["indra_evidence"] = enrichment_items
        else:
            hypothesis.reflection_notes = (
                "Analysis failed\n\nClassification: neutral")

    # Emit progress
    progress_callback = state.get("progress_callback")
    if progress_callback is not None:
        await progress_callback(
            "reflection_complete",
            {
                "message": "Reflection analysis complete",
                "progress": PROGRESS_REFLECTION_COMPLETE,
                "hypotheses_count": len(hypotheses),
            },
        )

    logger.info("Completed reflection analysis for %s hypotheses",
                len(hypotheses))

    return {
        "hypotheses":
            hypotheses,
        "messages": [{
            "role": "assistant",
            "content": (f"completed reflection analysis for"
                        f" {len(hypotheses)} hypotheses"),
            "metadata": {
                "phase": "reflection"
            },
        }],
    }


async def _fetch_indra_for_hypothesis(
    hypothesis_text: str,
    tool_registry: Any | None,
    hypothesis_index: int,
) -> dict[str, Any]:
    """Pre-fetch INDRA knowledge graph evidence for a hypothesis.

    Non-critical: returns empty dict on any failure so reflection
    proceeds without INDRA data if the MCP server or tools are unavailable.

    Returns dict with "prompt_text" (str) and "enrichment_items" (list).
    """
    empty: dict[str, Any] = {"prompt_text": "", "enrichment_items": []}
    try:
        from co_scientist.nodes.reflection_helpers import fetch_indra_evidence  # pylint: disable=import-outside-toplevel

        result = await fetch_indra_evidence(
            hypothesis_text=hypothesis_text,
            tool_registry=tool_registry,
            max_statements=5,
        )
        prompt_text = result.get("prompt_text", "")
        if prompt_text:
            logger.debug(
                "hypothesis %s: fetched INDRA evidence (%s chars, %s items)",
                hypothesis_index, len(prompt_text),
                len(result.get('enrichment_items', [])))
        return result
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.debug("hypothesis %s: INDRA fetch skipped: %s", hypothesis_index,
                     e)
        return empty
