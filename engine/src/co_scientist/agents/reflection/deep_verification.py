"""Grounded assumption probing and verification of leading hypotheses."""

import asyncio
import dataclasses
import hashlib
import json
import logging
from collections.abc import Mapping
from typing import Any

from co_scientist.agents.reflection.deep_verification_evidence import (
    PUBLIC_SNIPPET_CHARS,
    EvidenceCaps,
    _augment_evidence_context_with_meta_review,
    _probe_queries,
    _retrieve_probe_evidence,
    _retrieved_evidence_context,
    build_evidence_context,
)
from co_scientist.agents.reflection.deep_verification_evidence import (
    merge_retrieved_articles as merge_retrieved_articles,
)
from co_scientist.agents.reflection.deep_verification_evidence import (
    with_researched as _with_researched,
)
from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    LOW_TEMPERATURE,
    MAX_CONCURRENT_LLM_CALLS,
    PROGRESS_DEEP_VERIFICATION_COMPLETE,
    PROGRESS_DEEP_VERIFICATION_START,
)
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS
from co_scientist.llm import CompletionSpec, call_llm_json
from co_scientist.models import (
    Article,
    Hypothesis,
    MetricDeltas,
    create_metrics_update,
    phase_message,
)
from co_scientist.progress import emit_progress
from co_scientist.prompts import get_deep_verification_prompt
from co_scientist.schemas.review import (
    DEEP_VERIFICATION_MAX_DECONTEXTUALIZATIONS,
    DEEP_VERIFICATION_MAX_SUB_ASSUMPTIONS,
)
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


_VALID_VERDICTS = frozenset({"holds", "weakened", "undermined"})


def has_valid_verification(result: Mapping[str, Any] | None) -> bool:
    """Whether a result carries one of the verifier's usable verdicts."""
    verdict = result.get("verdict") if result is not None else None
    return isinstance(verdict, str) and verdict in _VALID_VERDICTS


async def verify_hypothesis(
    state: WorkflowState, hypothesis: Hypothesis
) -> dict[str, Any] | None:
    """Verify one idea with a fresh call-local concurrency guard.

    Graph batches call the same leaf with their shared batch semaphore;
    durable items have no shared event-loop primitives or context assembly.
    The leaf preserves ordinary failures as None and task-control errors.
    """
    context = _VerificationContext(
        research_goal=state["research_goal"],
        model_name=state["model_name"],
        tool_registry=state.get("tool_registry"),
        state=state,
    )
    return await _verify_one(
        hypothesis,
        context,
        asyncio.Semaphore(1),
        _verification_evidence_context(state),
    )


# Enrichment key recording that this hypothesis has had its one deep
# verification. Checkpointed with the hypothesis (see the module
# docstring), so a resume cannot re-fire the wave.
VERIFICATION_MARKER = "deep_verification_issued"


# Bump whenever the deep-verification prompt or schema changes in a way that
# would produce a different answer to the same question. Verifications
# carrying an older version are re-run rather than trusted, since the stored
# probes were produced by a prompt this code no longer sends.
# 2: the verification gained sub-assumption decomposition and
# decontextualization (audit E4) and a fail-closed ``unverified`` verdict
# (audit E9). Moving the node ahead of the tournament did not bump this:
# the prompt and schema are unchanged, only which hypotheses are asked.
DEEP_VERIFICATION_PROMPT_VERSION = 2


def _cited_evidence_identities(hypothesis: Hypothesis) -> list[str]:
    """Return stable identities for the evidence a hypothesis cites.

    Only cited sources count. The evidence context handed to the verifier
    is assembled run-wide, so hashing all of it would make any new article
    anywhere invalidate every hypothesis's fingerprint and re-verify the
    whole leaderboard for evidence that never mentioned it.
    """
    identities = set()
    for key, source in (hypothesis.citation_map or {}).items():
        source = source if isinstance(source, dict) else {}
        identity = (
            source.get("source_id")
            or source.get("doi")
            or source.get("url")
            or source.get("title")
            or key
        )
        identities.add(str(identity))
    return sorted(identities)


def verification_fingerprint(hypothesis: Hypothesis, model_name: str) -> str:
    """Digest the inputs a deep verification would be produced from.

    Covers the hypothesis text, the verifier model, the prompt version, and
    the evidence the hypothesis cites. Two verifications with the same
    fingerprint would be asked the same question against the same material,
    so the stored answer still holds and the call can be skipped.

    Args:
        hypothesis: The hypothesis that would be verified.
        model_name: Verifier model the call would run on.

    Returns:
        A hex digest to compare against the hypothesis's stored value.
    """
    payload = json.dumps(
        {
            "prompt_version": DEEP_VERIFICATION_PROMPT_VERSION,
            "model": model_name,
            "text": " ".join((hypothesis.text or "").split()),
            "evidence": _cited_evidence_identities(hypothesis),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verification_issued(hypothesis: Hypothesis) -> bool:
    """Return whether this hypothesis has already had its one attempt."""
    return bool(hypothesis.enrichments.get(VERIFICATION_MARKER))


def mark_verification_issued(hypothesis: Hypothesis) -> None:
    """Record the verification attempt, before its answer is known."""
    hypothesis.enrichments[VERIFICATION_MARKER] = True


def _needs_verification(hypothesis: Hypothesis, model_name: str) -> bool:
    """Return whether one hypothesis is owed a deep verification now.

    Three conditions, in the order they eliminate the most work: an idea
    barred from the tournament has nothing to guard, an idea that already
    spent its one attempt gets no second, and an idea already carrying a
    verification produced from the inputs it still has needs no repeat.
    """
    if not hypothesis.is_rankable():
        return False
    if verification_issued(hypothesis):
        return False
    return hypothesis.deep_verification_fingerprint != (
        verification_fingerprint(hypothesis, model_name)
    )


def select_hypotheses_to_verify(
    hypotheses: list[Hypothesis],
    model_name: str,
) -> list[Hypothesis]:
    """Picks every rankable hypothesis still owed its one verification.

    Blanket over the pool rather than top-k by Elo, because verification
    now runs *before* the tournament: there is no Elo ordering to select
    by yet, and the published listing verifies each hypothesis on the way
    into the tournament rather than a slice of it afterwards.

    Args:
        hypotheses: The full hypothesis pool.
        model_name: Verifier model the batch would run on.

    Returns:
        The hypotheses to verify now, in pool order.
    """
    return [
        hypothesis
        for hypothesis in hypotheses
        if _needs_verification(hypothesis, model_name)
    ]


# Compatibility for existing library callers.
_select_hypotheses_to_verify = select_hypotheses_to_verify


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
