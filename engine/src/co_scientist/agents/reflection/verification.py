"""Incremental verification selection and single-hypothesis execution."""

import asyncio
import dataclasses
import hashlib
import json
import logging
from collections.abc import Mapping
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
