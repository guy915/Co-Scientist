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

from co_scientist.agents.generation.citations import (
    ReferenceIndex,
    hypothesis_from_llm_output,
)
from co_scientist.constants import EXTENDED_MAX_TOKENS, MEDIUM_TEMPERATURE
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    call_llm_json,
)
from co_scientist.models import GenerationMethod, Hypothesis
from co_scientist.prompts._common import _format_meta_review_context
from co_scientist.prompts.generation_formatting import (
    _build_citation_reference_section,
)
from co_scientist.prompts.loading import load_prompt_with_schema
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


def _resolve_assumptions_context(
    reference_index: ReferenceIndex | None,
    articles_with_reasoning: str | None,
) -> tuple[str, dict[str, dict[str, Any]], str]:
    """Resolve the reference text/sources/literature-context for one call.

    Prose literature context is admitted only alongside a real (non-empty)
    reference index, so a stale degraded-mode summary string can never leak
    in.

    Returns:
        Tuple of (reference_text, sources, literature_context).
    """
    if reference_index is not None and not reference_index.is_empty():
        reference_text = reference_index.text
        sources: dict[str, dict[str, Any]] = reference_index.sources
        has_references = True
    else:
        reference_text = ""
        sources = {}
        has_references = False

    literature_context = (
        "Relevant findings from the literature review:\n"
        f"{articles_with_reasoning}\n"
        if has_references and articles_with_reasoning
        else ""
    )
    return reference_text, sources, literature_context


def _build_assumptions_prompt(
    state: WorkflowState,
    count: int,
    reference_text: str,
    literature_context: str,
) -> tuple[str, Any]:
    """Build the assumptions-technique prompt/schema for one call."""
    return load_prompt_with_schema(
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


async def _call_assumptions_llm(
    state: WorkflowState,
    prompt: str,
    schema: Any,
) -> dict[str, Any]:
    """Issue the single structured call the assumptions technique makes.

    Args:
        state: Workflow state supplying the model name and run id.
        prompt: The rendered assumptions prompt.
        schema: The JSON schema the response must satisfy.

    Returns:
        The parsed JSON response.
    """
    return await call_llm_json(
        prompt,
        spec=CompletionSpec(
            model_name=state["model_name"],
            max_tokens=EXTENDED_MAX_TOKENS,
            temperature=MEDIUM_TEMPERATURE,
            json_schema=schema,
        ),
        options=LLMCallOptions(
            # Never cached, matching the debate and tool-drafting strategies.
            # Generation fans out one durable task per hypothesis, so several
            # tasks issue this call with an identical prompt and rely on
            # sampling to explore different ideas. A cache hit would serve
            # them all the same hypothesis, and the state reducer dedupes on
            # append -- so the run would quietly commit one hypothesis where
            # the tier asked for several, with nothing failing to show it.
            use_cache=False,
            run_id=state.get("run_id"),
            prompt_name="generation_assumptions",
        ),
    )


async def generate_with_assumptions(
    state: WorkflowState,
    count: int,
    articles_with_reasoning: str | None = None,
    reference_index: ReferenceIndex | None = None,
) -> list[Hypothesis]:
    """Generate ``count`` hypotheses by interrogating the area's assumptions.

    Grounds each hypothesis's claims in the supplied references so
    ``literature_grounding`` cites real ``[C*]`` keys rather than inventing
    citations (SSR §4). With no reference index (the degraded LLM-only
    path) it behaves exactly as before.

    Returns:
        The generated hypotheses, tagged ``GenerationMethod.ASSUMPTIONS``.
    """
    reference_text, sources, literature_context = _resolve_assumptions_context(
        reference_index, articles_with_reasoning
    )
    prompt, schema = _build_assumptions_prompt(
        state, count, reference_text, literature_context
    )
    response = await _call_assumptions_llm(state, prompt, schema)
    raw: list[dict[str, Any]] = response.get("hypotheses", [])
    hypotheses = [
        hypothesis_from_llm_output(h, sources, GenerationMethod.ASSUMPTIONS)
        for h in raw
    ]
    logger.info(
        "Assumptions generation produced %s hypotheses", len(hypotheses)
    )
    return hypotheses
