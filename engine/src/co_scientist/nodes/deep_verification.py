"""Deep-verification node - probing-question analysis of top hypotheses."""

import asyncio
import logging
from typing import Any

from co_scientist.constants import DEEP_VERIFICATION_TOP_K
from co_scientist.constants import EXTENDED_MAX_TOKENS
from co_scientist.constants import LOW_TEMPERATURE
from co_scientist.constants import MAX_CONCURRENT_LLM_CALLS
from co_scientist.constants import PROGRESS_DEEP_VERIFICATION_COMPLETE
from co_scientist.constants import PROGRESS_DEEP_VERIFICATION_START
from co_scientist.llm import call_llm_json
from co_scientist.models import create_metrics_update
from co_scientist.models import Hypothesis
from co_scientist.prompts import get_deep_verification_prompt
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


async def _verify_one(
    hypothesis: Hypothesis,
    research_goal: str,
    model_name: str,
    semaphore: asyncio.Semaphore,
    tool_registry: Any | None,
) -> dict[str, Any] | None:
    """Run probing-question deep verification for one hypothesis.

    Args:
        hypothesis: The hypothesis to deep-verify.
        research_goal: The overall research goal for context.
        model_name: Model name in litellm format.
        semaphore: Concurrency limiter shared across verifications.
        tool_registry: Optional registry for domain-specific prompt variables.

    Returns:
        The parsed deep-verification result, or None if the call failed.
    """
    async with semaphore:
        prompt, schema = get_deep_verification_prompt(
            research_goal=research_goal,
            hypothesis_text=hypothesis.text,
            tool_registry=tool_registry,
        )
        try:
            return await call_llm_json(
                prompt=prompt,
                model_name=model_name,
                max_tokens=EXTENDED_MAX_TOKENS,
                temperature=LOW_TEMPERATURE,
                json_schema=schema,
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Deep verification failed: %s", e)
            return None


async def deep_verification_node(state: WorkflowState) -> dict[str, Any]:
    """Probing-question deep verification of the top-k hypotheses by Elo.

    Runs after ranking. Already-verified leaders whose text has not changed
    keep their probes and are skipped; evolution clears the probes of any
    hypothesis whose text it rewrites, so freshly-evolved leaders are
    re-verified here.

    Args:
        state: The current workflow state.

    Returns:
        A state delta with verified hypotheses, metrics, and a status message.
    """
    hypotheses = state["hypotheses"]
    if not hypotheses:
        return {}

    ranked = sorted(hypotheses, key=lambda h: h.elo_rating, reverse=True)
    top_k = ranked[:DEEP_VERIFICATION_TOP_K]
    to_verify = [h for h in top_k if not h.deep_verification_probes]

    if not to_verify:
        logger.info("Deep verification: top-%s already verified, skipping",
                    DEEP_VERIFICATION_TOP_K)
        return {}

    progress_callback = state.get("progress_callback")
    if progress_callback is not None:
        await progress_callback(
            "deep_verification_start", {
                "message": f"Deep-verifying top {len(to_verify)} hypotheses...",
                "progress": PROGRESS_DEEP_VERIFICATION_START,
            })

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)
    tool_registry = state.get("tool_registry")
    results = await asyncio.gather(*[
        _verify_one(h, state["research_goal"], state["model_name"], semaphore,
                    tool_registry) for h in to_verify
    ])

    verified_count = 0
    for hypothesis, result in zip(to_verify, results):
        if result:
            hypothesis.deep_verification_probes = result.get("probes", [])
            hypothesis.deep_verification_verdict = result.get("verdict")
            verified_count += 1

    if progress_callback is not None:
        await progress_callback(
            "deep_verification_complete", {
                "message": f"Deep-verified {verified_count} hypotheses",
                "progress": PROGRESS_DEEP_VERIFICATION_COMPLETE,
            })

    logger.info("Deep verification complete: %s hypotheses", verified_count)
    metrics = create_metrics_update(llm_calls_delta=verified_count)
    return {
        "hypotheses":
            hypotheses,
        "metrics":
            metrics,
        "messages": [{
            "role": "assistant",
            "content": f"Deep-verified {verified_count} top hypotheses",
            "metadata": {
                "phase": "deep_verification"
            },
        }],
    }
