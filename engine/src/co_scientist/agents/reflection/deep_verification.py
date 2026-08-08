"""Deep-verification node - probing-question analysis of top hypotheses."""

import asyncio
import dataclasses
import logging
from typing import Any

from co_scientist.agents.reflection.deep_verification_evidence import (
    _MAX_PROBE_SOURCES as _MAX_PROBE_SOURCES,
)
from co_scientist.agents.reflection.deep_verification_evidence import (
    _probe_queries as _probe_queries,
)
from co_scientist.agents.reflection.deep_verification_evidence import (
    _retrieve_probe_evidence as _retrieve_probe_evidence,
)
from co_scientist.agents.reflection.deep_verification_evidence import (
    _retrieved_evidence_context as _retrieved_evidence_context,
)
from co_scientist.agents.reflection.deep_verification_evidence import (
    merge_retrieved_articles as merge_retrieved_articles,
)
from co_scientist.agents.reflection.evidence_context import (
    PUBLIC_SNIPPET_CHARS,
    EvidenceCaps,
    build_evidence_context,
)
from co_scientist.agents.reflection.verification_freshness import (
    DEEP_VERIFICATION_PROMPT_VERSION as DEEP_VERIFICATION_PROMPT_VERSION,
)
from co_scientist.agents.reflection.verification_freshness import (
    _select_hypotheses_to_verify as _select_hypotheses_to_verify,
)
from co_scientist.agents.reflection.verification_freshness import (
    verification_fingerprint as verification_fingerprint,
)
from co_scientist.constants import (
    DEEP_VERIFICATION_TOP_K,
    EXTENDED_MAX_TOKENS,
    LOW_TEMPERATURE,
    MAX_CONCURRENT_LLM_CALLS,
    PROGRESS_DEEP_VERIFICATION_COMPLETE,
    PROGRESS_DEEP_VERIFICATION_START,
)
from co_scientist.llm import (
    CompletionSpec,
    call_llm_json,
)
from co_scientist.models import (
    Article,
    Hypothesis,
    MetricDeltas,
    create_metrics_update,
    phase_message,
)
from co_scientist.progress import emit_progress
from co_scientist.prompts import get_deep_verification_prompt
from co_scientist.prompts._common import _format_meta_review_context
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
_VALID_VERDICTS = frozenset({"holds", "weakened", "undermined"})

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
    (audit E9) rather than passing it silently.
    """
    async with semaphore:
        try:
            return await _verify_with_probes(
                hypothesis, context, evidence_context
            )
        except Exception as e:
            logger.error("Deep verification failed: %s", e)
            return None


def _augment_evidence_context_with_meta_review(
    evidence_context: str, state: WorkflowState
) -> str:
    """Appends cross-agent meta-review feedback to the evidence context.

    Cross-agent meta-review feedback names recurring error patterns across
    the run; appending it lets deep verification's probing questions target
    those patterns, so meta-review reaches this agent too (the disclosed
    all-agent feedback loop, audit E28). Returns evidence_context unchanged
    when no meta-review exists yet.
    """
    meta_context = _format_meta_review_context(state.get("meta_review"))
    if not meta_context:
        return evidence_context
    return (
        f"{evidence_context}\n\nCross-agent meta-review feedback "
        f"(recurring patterns to probe):\n{meta_context}"
    )


async def _verify_with_probes(
    hypothesis: Hypothesis,
    context: _VerificationContext,
    evidence_context: str,
) -> dict[str, Any]:
    """Runs the initial verification call, then a targeted probe retry."""
    initial = await _call_verification(hypothesis, context, evidence_context)
    queries = _probe_queries(initial)
    articles, retrieval_errors = await _retrieve_probe_evidence(
        context.state, queries
    )
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


def mark_hypothesis_unverified(hypothesis: Hypothesis) -> None:
    """Record the explicit ``unverified`` state on one hypothesis.

    The fingerprint is deliberately left stale so the next deep-verification
    pass re-attempts instead of trusting the failure. Unverified is not
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
        if result is None or result.get("verdict") not in _VALID_VERDICTS:
            mark_hypothesis_unverified(hypothesis)
            unverified_count += 1
            continue
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
    """Deep verification of the post-tournament leaders, top-k by Elo.

    Runs after each ranking pass (audit E9), so the Elo ordering it
    selects by is the tournament's, not the arbitrary all-tied pool order
    of a pre-ranking pass. Verification decomposes each leader into
    sub-assumptions, probes them, and decontextualizes its context-bound
    claims (audit E4); a verification that cannot be produced records an
    explicit ``unverified`` verdict rather than passing silently.

    Already-verified leaders whose inputs have not changed keep their
    verification and are skipped; evolution clears the probes of any
    hypothesis whose text it rewrites, so freshly-evolved leaders are
    re-verified here.

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

    to_verify = _select_hypotheses_to_verify(hypotheses, state["model_name"])

    # The whole top-k is current: every leader's stored verification was
    # produced from the inputs it still has. Skip the LLM calls and return
    # an empty delta -- no hypotheses/metrics/messages changes needed.
    if not to_verify:
        logger.info(
            "Deep verification: top-%s unchanged since verification, reusing",
            DEEP_VERIFICATION_TOP_K,
        )
        await emit_progress(
            state,
            "deep_verification_complete",
            f"Reused deep verification for top {DEEP_VERIFICATION_TOP_K}",
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
        f"Deep-verifying top {len(to_verify)} hypotheses...",
        PROGRESS_DEEP_VERIFICATION_START,
    )

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
