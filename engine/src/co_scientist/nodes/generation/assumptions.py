"""Iterative-assumptions hypothesis generation (SSR §4).

The assumptions technique decomposes the research area into its underlying
assumptions and generates hypotheses that challenge the weakest ones. It is a
single structured call (unlike the multi-turn debate), producing hypotheses
directly via the shared ``GENERATION_SCHEMA`` shape, tagged with
``GenerationMethod.ASSUMPTIONS``.
"""

from __future__ import annotations

import logging
from typing import Any

from co_scientist.constants import EXTENDED_MAX_TOKENS, MEDIUM_TEMPERATURE
from co_scientist.llm import call_llm_json
from co_scientist.models import GenerationMethod, Hypothesis
from co_scientist.nodes.generation.citations import hypothesis_from_llm_output
from co_scientist.prompts._common import _format_meta_review_context
from co_scientist.prompts.loading import load_prompt_with_schema
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


async def generate_with_assumptions(
    state: WorkflowState, count: int
) -> list[Hypothesis]:
    """Generate ``count`` hypotheses by interrogating the area's assumptions.

    Args:
        state: Current workflow state (supplies the research goal and any
            meta-review feedback for a later research-expansion cycle).
        count: Number of hypotheses to request.

    Returns:
        The generated hypotheses, tagged ``GenerationMethod.ASSUMPTIONS``.
    """
    prompt, schema = load_prompt_with_schema(
        "generation_assumptions",
        {
            "research_goal": state["research_goal"],
            "num_hypotheses": count,
            "meta_review_context": _format_meta_review_context(
                state.get("meta_review")
            ),
            "domain_context": "",
        },
    )
    response = await call_llm_json(
        prompt,
        state["model_name"],
        max_tokens=EXTENDED_MAX_TOKENS,
        temperature=MEDIUM_TEMPERATURE,
        json_schema=schema,
        run_id=state.get("run_id"),
        prompt_name="generation_assumptions",
    )
    raw: list[dict[str, Any]] = response.get("hypotheses", [])
    hypotheses = [
        hypothesis_from_llm_output(h, {}, GenerationMethod.ASSUMPTIONS)
        for h in raw
    ]
    logger.info(
        "Assumptions generation produced %s hypotheses", len(hypotheses)
    )
    return hypotheses
