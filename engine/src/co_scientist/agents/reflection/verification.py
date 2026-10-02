"""Shared single-hypothesis verification, independent of orchestration."""

import asyncio
import dataclasses
import logging
from typing import Any

from co_scientist.agents.reflection.deep_verification_evidence import (
    _augment_evidence_context_with_meta_review,
    _probe_queries,
    _retrieve_probe_evidence,
    _retrieved_evidence_context,
)
from co_scientist.agents.reflection.deep_verification_evidence import (
    with_researched as _with_researched,
)
from co_scientist.agents.reflection.evidence_context import (
    PUBLIC_SNIPPET_CHARS,
    EvidenceCaps,
    build_evidence_context,
)
from co_scientist.constants import EXTENDED_MAX_TOKENS, LOW_TEMPERATURE
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS
from co_scientist.llm import CompletionSpec, call_llm_json
from co_scientist.models import Hypothesis
from co_scientist.prompts import get_deep_verification_prompt
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

# Ceiling on the opening evidence block, before the probe block is appended
# to it. Eight full-length sources' worth (PUBLIC_SNIPPET_CHARS), so it trims
# a long corpus rather than competing with the per-source truncation.
_MAX_VERIFICATION_CONTEXT_CHARS = 8 * PUBLIC_SNIPPET_CHARS


@dataclasses.dataclass(frozen=True)
class _VerificationContext:
    """Batch-invariant inputs shared by every hypothesis verification.

    ``state`` is carried alongside the extracted scalars because probe
    retrieval reads the full workflow state (search config, MCP client).
    """

    research_goal: str
    model_name: str
    tool_registry: Any | None
    state: WorkflowState


async def _call_verification(
    hypothesis: Hypothesis,
    context: _VerificationContext,
    evidence_context: str,
) -> dict[str, Any]:
    """Call the verifier once against the supplied evidence snapshot."""
    prompt, schema = get_deep_verification_prompt(
        research_goal=context.research_goal,
        hypothesis_text=hypothesis.text,
        tool_registry=context.tool_registry,
        evidence_context=evidence_context,
    )
    return await call_llm_json(
        prompt=prompt,
        spec=CompletionSpec(
            model_name=context.model_name,
            max_tokens=EXTENDED_MAX_TOKENS,
            temperature=LOW_TEMPERATURE,
            json_schema=schema,
        ),
    )


async def _verify_one(
    hypothesis: Hypothesis,
    context: _VerificationContext,
    semaphore: asyncio.Semaphore,
    evidence_context: str,
) -> dict[str, Any] | None:
    """Run probing-question deep verification for one hypothesis.

    Args:
        hypothesis: The hypothesis to deep-verify.
        context: Batch-invariant context (research goal, model, tool
            registry, full workflow state for probe retrieval).
        semaphore: Concurrency limiter shared across verifications.
        evidence_context: Bounded analyzed-source excerpts.

    Returns:
        The parsed deep-verification result, or None if the call failed.
    """
    evidence_context = _augment_evidence_context_with_meta_review(
        evidence_context, context.state
    )
    return await _verify_within_semaphore(
        semaphore, hypothesis, context, evidence_context
    )


async def _verify_within_semaphore(
    semaphore: asyncio.Semaphore,
    hypothesis: Hypothesis,
    context: _VerificationContext,
    evidence_context: str,
) -> dict[str, Any] | None:
    """Runs verification bounded by the shared semaphore, isolating failure.

    Bounds concurrent verifications across the whole top-k batch. Broad
    except by design: one hypothesis's failure should not abort the batch;
    None means the batch records an explicit ``unverified`` verdict for it
    (audit E9) rather than passing it silently. The two control-flow
    errors are not one hypothesis's failure and are re-raised -- see
    ``TASK_CONTROL_FLOW_ERRORS``.

    Raises:
        LLMRateLimitParkError: A platform cap the worker must park on.
        LLMCallBudgetExceededError: The run's spend ceiling is exhausted.
    """
    async with semaphore:
        try:
            return await _verify_with_probes(
                hypothesis, context, evidence_context
            )
        except TASK_CONTROL_FLOW_ERRORS:
            raise
        except Exception as e:
            logger.error("Deep verification failed: %s", e)
            return None


async def _verify_with_probes(
    hypothesis: Hypothesis,
    context: _VerificationContext,
    evidence_context: str,
) -> dict[str, Any]:
    """Runs the initial verification call, then a targeted probe retry.

    The probe round searches once from what the first call asked about
    and stops. Where the reviews already researched this hypothesis,
    ``with_researched`` adds what they found, so verification answers
    its own questions against evidence that went back a level.
    """
    initial = await _call_verification(hypothesis, context, evidence_context)
    queries = _probe_queries(initial)
    probed, retrieval_errors = await _retrieve_probe_evidence(
        context.state, queries
    )
    articles = _with_researched(context.state, hypothesis, probed)
    if not articles:
        initial["retrieval_queries"] = queries
        initial["retrieval_errors"] = retrieval_errors
        initial["retrieved_articles"] = []
        initial["verification_llm_calls"] = 1
        return initial
    targeted_context = _retrieved_evidence_context(articles)
    result = await _call_verification(
        hypothesis,
        context,
        f"{evidence_context}\n\nTargeted probe evidence:\n{targeted_context}",
    )
    result["retrieval_queries"] = queries
    result["retrieval_errors"] = retrieval_errors
    result["retrieved_articles"] = [article.to_dict() for article in articles]
    result["verification_llm_calls"] = 2
    return result


def _verification_evidence_context(state: WorkflowState) -> str:
    """Format bounded public and private evidence for verification prompts.

    Bounded by total length rather than by source count: unlike a review,
    verification probes whatever the run has gathered, so breadth is the
    point and the only real limit is the prompt it has to fit in.
    """
    context = build_evidence_context(
        state.get("articles"),
        private_sources=state.get("context_enrichment_sources"),
        caps=EvidenceCaps(total_chars=_MAX_VERIFICATION_CONTEXT_CHARS),
    )
    return context or "No retrieved evidence available."
