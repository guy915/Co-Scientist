"""Deep-verification node - probing-question analysis before ranking."""

import asyncio
import logging
from typing import Any

from co_scientist.agents.reflection.deep_verification_evidence import (
    merge_retrieved_articles as merge_retrieved_articles,
)
from co_scientist.agents.reflection.verification import (
    DEEP_VERIFICATION_PROMPT_VERSION as DEEP_VERIFICATION_PROMPT_VERSION,
)
from co_scientist.agents.reflection.verification import (
    _verification_evidence_context as _verification_evidence_context,
)
from co_scientist.agents.reflection.verification import (
    _VerificationContext as _VerificationContext,
)
from co_scientist.agents.reflection.verification import (
    _verify_one as _verify_one,
)
from co_scientist.agents.reflection.verification import (
    has_valid_verification,
    select_hypotheses_to_verify,
)
from co_scientist.agents.reflection.verification import (
    mark_verification_issued as mark_verification_issued,
)
from co_scientist.agents.reflection.verification import (
    verification_fingerprint as verification_fingerprint,
)
from co_scientist.agents.reflection.verification import (
    verification_issued as verification_issued,
)
from co_scientist.constants import (
    MAX_CONCURRENT_LLM_CALLS,
    PROGRESS_DEEP_VERIFICATION_COMPLETE,
    PROGRESS_DEEP_VERIFICATION_START,
)
from co_scientist.models import (
    Article,
    Hypothesis,
    MetricDeltas,
    create_metrics_update,
    phase_message,
)
from co_scientist.progress import emit_progress
from co_scientist.schemas.review import (
    DEEP_VERIFICATION_MAX_DECONTEXTUALIZATIONS,
    DEEP_VERIFICATION_MAX_SUB_ASSUMPTIONS,
)
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

# The verdict a verification explicitly carries when it could not be
# produced (provider failure, or output that did not survive validation).
# Never model output -- the schema enum has no such value -- and never
# blocking: an unverified idea still ranks and publishes, mirroring the
# "Unverified" badge policy for merely-unsupported claims. No verdict bars
# ranking any more; "undermined" (audit E9) now demotes instead, sorting
# the idea below every sound one -- see models.UNDERMINED_VERDICT.
VERDICT_UNVERIFIED = "unverified"
_select_hypotheses_to_verify = select_hypotheses_to_verify


def mark_hypothesis_unverified(hypothesis: Hypothesis) -> None:
    """Record the explicit ``unverified`` state on one hypothesis.

    The fingerprint is left stale so nothing reads the failure as a
    stored verdict, but the once-ever marker has already been written, so
    the idea is not re-offered -- the attempt was spent. Unverified is not
    blocking -- the idea still ranks and publishes, as every verdict now
    does; it just carries the explicit state, mirroring the "Unverified"
    badge policy for merely-unsupported claims (audit E9).
    """
    hypothesis.deep_verification_probes = []
    hypothesis.deep_verification_verdict = VERDICT_UNVERIFIED
    hypothesis.enrichments.pop("deep_verification", None)


def _bounded_verification(result: dict[str, Any]) -> dict[str, Any]:
    """The storable verification record, decomposition lists bounded.

    The schema caps both lists already; this is the second bound on the
    stored side, so a response that slipped a lax provider cannot grow the
    checkpoint indefinitely.
    """
    bounded = dict(result)
    bounded["sub_assumptions"] = list(
        (result.get("sub_assumptions") or [])[
            :DEEP_VERIFICATION_MAX_SUB_ASSUMPTIONS
        ]
    )
    bounded["decontextualizations"] = list(
        (result.get("decontextualizations") or [])[
            :DEEP_VERIFICATION_MAX_DECONTEXTUALIZATIONS
        ]
    )
    return bounded


def _apply_verification_results(
    to_verify: list[Hypothesis],
    results: list[dict[str, Any] | None],
    model_name: str,
) -> tuple[int, int]:
    """Applies deep-verification results onto their hypotheses in place.

    Fails closed (audit E9): a None result (provider failure, see
    _verify_one) or one without a usable verdict (output that never
    survived validation) records an explicit ``unverified`` verdict rather
    than passing silently. Either failure also leaves the fingerprint
    stale, so the next cycle retries instead of recording the failure as
    current -- but the stale probes of the attempt being replaced are
    cleared, since carrying them would read as a verdict this attempt
    never produced.

    The fingerprint is recomputed here rather than reused from selection:
    probe retrieval can add citations mid-verification, and storing the
    pre-call value would mark the hypothesis current against inputs the
    stored answer was not actually produced from.

    Args:
        to_verify: Hypotheses that were sent for verification.
        results: Per-hypothesis results, aligned with to_verify.
        model_name: Verifier model the batch ran on.

    Returns:
        Counts of (verified, unverified) hypotheses.
    """
    verified_count = 0
    unverified_count = 0
    for hypothesis, result in zip(to_verify, results, strict=True):
        if not has_valid_verification(result):
            mark_hypothesis_unverified(hypothesis)
            unverified_count += 1
            continue
        assert result is not None
        hypothesis.deep_verification_probes = result.get("probes", [])
        hypothesis.deep_verification_verdict = result.get("verdict")
        hypothesis.enrichments["deep_verification"] = _bounded_verification(
            result
        )
        hypothesis.deep_verification_fingerprint = verification_fingerprint(
            hypothesis, model_name
        )
        verified_count += 1
    return verified_count, unverified_count


async def deep_verification_node(state: WorkflowState) -> dict[str, Any]:
    """Deep verification of every idea still owed one, before ranking.

    Runs between the safety screen and the tournament, mirroring
    ``03-reflection.md``: ``ReviewHypothesis`` verifies the hypothesis and
    only then creates its ``AddToTournament`` task. Verification
    decomposes each idea into sub-assumptions, probes them, and
    decontextualizes its context-bound claims (audit E4); a verification
    that cannot be produced records an explicit ``unverified`` verdict
    rather than passing silently.

    Blanket but incremental -- the initial pool once, then each cycle's
    new children once, so the cost is pool-sized rather than pool x
    cycles. ``verification`` owns that rule.

    Args:
        state: The current workflow state.

    Returns:
        A state delta with verified hypotheses, metrics, and a status
        message.
    """
    hypotheses = state["hypotheses"]
    # Edge case: nothing to verify yet (e.g. called before generation).
    if not hypotheses:
        return {}

    to_verify = select_hypotheses_to_verify(hypotheses, state["model_name"])

    # Every idea has already had its verification: the steady state from
    # the second cycle on, and the first thing a resumed run finds. Skip
    # the calls and return an empty delta.
    if not to_verify:
        logger.info("Deep verification: every idea already verified, reusing")
        await emit_progress(
            state,
            "deep_verification_complete",
            "Reused deep verification for the whole pool",
            PROGRESS_DEEP_VERIFICATION_COMPLETE,
        )
        return {}

    verified, unverified, llm_calls = await _run_verification_batch(
        state, to_verify
    )
    return _deep_verification_result(
        hypotheses, state["articles"], verified, unverified, llm_calls
    )


def _deep_verification_result(
    hypotheses: list[Hypothesis],
    articles: list[Article] | None,
    verified_count: int,
    unverified_count: int,
    llm_calls: int,
) -> dict[str, Any]:
    """Builds the deep_verification_node state delta after a batch runs."""
    logger.info(
        "Deep verification complete: %s hypotheses, %s unverified",
        verified_count,
        unverified_count,
    )
    message = f"Deep-verified {verified_count} top hypotheses"
    if unverified_count:
        message += (
            f"; {unverified_count} left explicitly unverified after a"
            " verification failure"
        )
    metrics = create_metrics_update(deltas=MetricDeltas(llm_calls=llm_calls))
    return {
        "hypotheses": hypotheses,
        "articles": articles,
        "metrics": metrics,
        "messages": phase_message("deep_verification", message),
    }


async def _run_verification_batch(
    state: WorkflowState,
    to_verify: list[Hypothesis],
) -> tuple[int, int, int]:
    """Runs deep verification for a batch of hypotheses and applies results.

    Verifies concurrently (semaphore-bounded), applies results in place on
    the same Hypothesis objects, and emits progress before and after.

    Args:
        state: Current workflow state.
        to_verify: Hypotheses to verify.

    Returns:
        Verified count, explicitly-unverified count, and actual
        verification LLM calls.
    """
    await emit_progress(
        state,
        "deep_verification_start",
        f"Deep-verifying {len(to_verify)} hypotheses...",
        PROGRESS_DEEP_VERIFICATION_START,
    )

    # Marked before the calls go out, never after: the attempt is spent
    # when it is issued, so a hypothesis whose verification fails must
    # not be re-offered next cycle (verification).
    for hypothesis in to_verify:
        mark_verification_issued(hypothesis)

    tool_registry = state.get("tool_registry")
    evidence_context = _verification_evidence_context(state)
    results = await _gather_verification_results(
        to_verify, state, tool_registry, evidence_context
    )
    verified_count, unverified_count, llm_calls = _finalize_verification_batch(
        to_verify, results, state
    )

    await emit_progress(
        state,
        "deep_verification_complete",
        f"Deep-verified {verified_count} hypotheses",
        PROGRESS_DEEP_VERIFICATION_COMPLETE,
    )

    return verified_count, unverified_count, llm_calls


async def _gather_verification_results(
    to_verify: list[Hypothesis],
    state: WorkflowState,
    tool_registry: Any | None,
    evidence_context: str,
) -> list[dict[str, Any] | None]:
    """Runs _verify_one for every hypothesis concurrently, semaphore-bounded.

    The semaphore is created fresh per call, local to this node, and caps
    in-flight LLM calls across the whole batch.
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)
    context = _VerificationContext(
        research_goal=state["research_goal"],
        model_name=state["model_name"],
        tool_registry=tool_registry,
        state=state,
    )
    return await asyncio.gather(
        *[
            _verify_one(h, context, semaphore, evidence_context)
            for h in to_verify
        ]
    )


def _finalize_verification_batch(
    to_verify: list[Hypothesis],
    results: list[dict[str, Any] | None],
    state: WorkflowState,
) -> tuple[int, int, int]:
    """Applies results, merges retrieved articles, and tallies LLM calls.

    Returns:
        Verified count, explicitly-unverified count, and LLM calls. A
        degraded (empty-dict) result still spent its initial call, so it
        is billed even though it lands as unverified.
    """
    verified_count, unverified_count = _apply_verification_results(
        to_verify, results, state["model_name"]
    )
    state["articles"] = merge_retrieved_articles(state.get("articles"), results)
    llm_calls = sum(
        int(result.get("verification_llm_calls", 1))
        for result in results
        if result is not None
    )
    return verified_count, unverified_count, llm_calls
