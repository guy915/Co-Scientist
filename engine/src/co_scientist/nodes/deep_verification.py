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
from co_scientist.models import phase_message
from co_scientist.models import Hypothesis
from co_scientist.models import rank_by_elo
from co_scientist.nodes.progress import emit_progress
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
    # Semaphore bounds how many of these run concurrently across the whole
    # top-k batch, shared with the caller via the `semaphore` argument.
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
            # Deliberately broad: one hypothesis's verification failing
            # (timeout, malformed response, provider error, etc.) should
            # not abort the whole batch. The caller treats None as "leave
            # this hypothesis's existing probes/verdict untouched."
            logger.error("Deep verification failed: %s", e)
            return None


def _select_hypotheses_to_verify(
        hypotheses: list[Hypothesis]) -> list[Hypothesis]:
    """Picks the current Elo leaders that still need deep verification.

    Use the shared Elo ranking policy to pick the current leaders, then
    only re-verify those without existing probes: a hypothesis keeps its
    probes/verdict across iterations unless evolve.py rewrote its text
    (which clears them), so this is naturally idempotent/incremental.

    Args:
        hypotheses: The full hypothesis pool.

    Returns:
        Top-k-by-Elo hypotheses that lack deep-verification probes.
    """
    ranked = rank_by_elo(hypotheses)
    top_k = ranked[:DEEP_VERIFICATION_TOP_K]
    return [h for h in top_k if not h.deep_verification_probes]


def _apply_verification_results(to_verify: list[Hypothesis],
                                results: list[dict[str, Any] | None]) -> int:
    """Applies deep-verification results onto their hypotheses in place.

    A None result (call failed, see _verify_one) is silently skipped,
    leaving that hypothesis's prior probes/verdict (typically empty, since
    it was selected for verification) unchanged rather than raising.

    Args:
        to_verify: Hypotheses that were sent for verification.
        results: Per-hypothesis results, aligned with to_verify.

    Returns:
        Count of hypotheses whose probes/verdict were updated.
    """
    verified_count = 0
    for hypothesis, result in zip(to_verify, results):
        if result:
            hypothesis.deep_verification_probes = result.get("probes", [])
            hypothesis.deep_verification_verdict = result.get("verdict")
            verified_count += 1
    return verified_count


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
    # Edge case: nothing to verify yet (e.g. called before generation).
    if not hypotheses:
        return {}

    to_verify = _select_hypotheses_to_verify(hypotheses)

    # Edge case: the whole top-k is already verified (no evolution touched
    # any of them since last time). Skip the LLM calls and return an empty
    # delta -- no hypotheses/metrics/messages changes needed.
    if not to_verify:
        logger.info("Deep verification: top-%s already verified, skipping",
                    DEEP_VERIFICATION_TOP_K)
        return {}

    verified_count = await _run_verification_batch(state, to_verify)

    logger.info("Deep verification complete: %s hypotheses", verified_count)
    metrics = create_metrics_update(llm_calls_delta=verified_count)
    return {
        "hypotheses":
            hypotheses,
        "metrics":
            metrics,
        "messages":
            phase_message("deep_verification",
                          f"Deep-verified {verified_count} top hypotheses"),
    }


async def _run_verification_batch(
    state: WorkflowState,
    to_verify: list[Hypothesis],
) -> int:
    """Runs deep verification for a batch of hypotheses and applies results.

    Verifies the given hypotheses concurrently, bounded by a semaphore
    (created fresh per call, local to this node) that caps in-flight LLM
    calls, and applies the results in place on the same Hypothesis objects
    passed in. Emits progress before and after.

    Args:
        state: Current workflow state.
        to_verify: Hypotheses to verify.

    Returns:
        Count of hypotheses whose probes/verdict were updated.
    """
    await emit_progress(state, "deep_verification_start",
                        f"Deep-verifying top {len(to_verify)} hypotheses...",
                        PROGRESS_DEEP_VERIFICATION_START)

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)
    tool_registry = state.get("tool_registry")
    results = await asyncio.gather(*[
        _verify_one(h, state["research_goal"], state["model_name"], semaphore,
                    tool_registry) for h in to_verify
    ])

    verified_count = _apply_verification_results(to_verify, results)

    await emit_progress(state, "deep_verification_complete",
                        f"Deep-verified {verified_count} hypotheses",
                        PROGRESS_DEEP_VERIFICATION_COMPLETE)

    return verified_count
