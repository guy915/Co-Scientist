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
from co_scientist.nodes.generation.citations import (
    ReferenceIndex,
    hypothesis_from_llm_output,
)
from co_scientist.prompts._common import _format_meta_review_context
from co_scientist.prompts.generation_formatting import (
    _build_citation_reference_section,
)
from co_scientist.prompts.loading import load_prompt_with_schema
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


async def generate_with_assumptions(
    state: WorkflowState,
    count: int,
    articles_with_reasoning: str | None = None,
    reference_index: ReferenceIndex | None = None,
) -> list[Hypothesis]:
    """Generate ``count`` hypotheses by interrogating the area's assumptions.

    In a literature-available run the technique still starts from the area's
    assumptions, but grounds each hypothesis's claims in the supplied
    references so the ``literature_grounding`` field cites real ``[C*]`` keys
    rather than inventing citations (SSR §4). With no reference index (the
    degraded LLM-only path) it behaves exactly as before.

    Args:
        state: Current workflow state (supplies the research goal and any
            meta-review feedback for a later research-expansion cycle).
        count: Number of hypotheses to request.
        articles_with_reasoning: Optional literature-review synthesis prose,
            admitted only alongside a real reference index.
        reference_index: Optional shared ``[C*]`` citation index; when
            non-empty its keys are offered to the prompt and its sources
            resolve the generated hypotheses' citation keys.

    Returns:
        The generated hypotheses, tagged ``GenerationMethod.ASSUMPTIONS``.
    """
    if reference_index is not None and not reference_index.is_empty():
        reference_text = reference_index.text
        sources: dict[str, dict[str, Any]] = reference_index.sources
        has_references = True
    else:
        reference_text = ""
        sources = {}
        has_references = False
    # Prose literature context is admitted only alongside a real reference
    # index, so a stale degraded-mode summary string can never leak in.
    literature_context = (
        "Relevant findings from the literature review:\n"
        f"{articles_with_reasoning}\n"
        if has_references and articles_with_reasoning
        else ""
    )
    prompt, schema = load_prompt_with_schema(
        "generation_assumptions",
        {
            "research_goal": state["research_goal"],
            "num_hypotheses": count,
            "meta_review_context": _format_meta_review_context(
                state.get("meta_review")
            ),
            "domain_context": "",
            "citation_reference_section": _build_citation_reference_section(
                reference_text
            ),
            "literature_context": literature_context,
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
        hypothesis_from_llm_output(h, sources, GenerationMethod.ASSUMPTIONS)
        for h in raw
    ]
    logger.info(
        "Assumptions generation produced %s hypotheses", len(hypotheses)
    )
    return hypotheses
