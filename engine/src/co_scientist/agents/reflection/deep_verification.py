"""Deep-verification node - probing-question analysis of top hypotheses."""

import asyncio
import dataclasses
import logging
from typing import Any

from co_scientist.constants import (
    DEEP_VERIFICATION_TOP_K,
    EXTENDED_MAX_TOKENS,
    LOW_TEMPERATURE,
    MAX_CONCURRENT_LLM_CALLS,
    PROGRESS_DEEP_VERIFICATION_COMPLETE,
    PROGRESS_DEEP_VERIFICATION_START,
)
from co_scientist.llm import call_llm_json
from co_scientist.models import (
    Article,
    Hypothesis,
    create_metrics_update,
    phase_message,
    rank_by_elo,
)
from co_scientist.progress import emit_progress
from co_scientist.prompts import get_deep_verification_prompt
from co_scientist.prompts._common import _format_meta_review_context
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

_MAX_PROBE_QUERIES = 3
_MAX_PROBE_SOURCES = 6


def _probe_queries(result: dict[str, Any]) -> list[str]:
    """Return the keyword searches for the load-bearing probing questions.

    Each probe carries its own ``search_query`` because the question it was
    written from is prose, and the literature back end ANDs every term of it:
    asking "Does tamoxifen reduce acrB transcript levels by >=50% within 1-2
    hours?" demands a paper containing "does", "1-2" and "50", which matches
    nothing. A probe that omitted the query falls back to its question, which
    at least preserves the old behaviour rather than dropping the search.
    """
    probes = result.get("probes") or []
    ordered = sorted(
        probes,
        key=lambda probe: not bool(probe.get("assumption_is_fundamental")),
    )
    queries: list[str] = []
    seen: set[str] = set()
    for probe in ordered:
        raw = probe.get("search_query") or probe.get("question") or ""
        query = " ".join(str(raw).split())
        key = query.casefold()
        if not query or key in seen:
            continue
        seen.add(key)
        queries.append(query)
        if len(queries) == _MAX_PROBE_QUERIES:
            break
    return queries


async def _retrieve_probe_evidence(
    state: WorkflowState, queries: list[str]
) -> tuple[list[Article], list[str]]:
    """Execute targeted literature searches for verification questions."""
    if not queries or not state.get("mcp_available"):
        return [], []

    from co_scientist.agents.generation.literature_review.helpers import (
        build_articles_from_metadata,
    )
    from co_scientist.agents.generation.literature_review.orchestration import (
        _phase2_collect_papers,
    )
    from co_scientist.agents.generation.literature_review.run_config import (
        _get_search_config,
    )
    from co_scientist.mcp_client import get_mcp_client

    config = dataclasses.replace(
        _get_search_config(state), papers_to_read_count=_MAX_PROBE_SOURCES
    )
    errors: list[str] = []
    try:
        client = await get_mcp_client(tool_registry=config.tool_registry)
        metadata, _ = await _phase2_collect_papers(
            queries, state, config, client, errors
        )
    except Exception as exc:
        logger.warning("Probe evidence retrieval unavailable: %s", exc)
        return [], [*errors, str(exc)]

    articles = build_articles_from_metadata(metadata, config.source_name)
    usable = [
        article
        for article in articles
        if not article.is_retracted and (article.abstract or article.content)
    ]
    return usable[:_MAX_PROBE_SOURCES], errors


def _retrieved_evidence_context(articles: list[Article]) -> str:
    """Format newly retrieved sources with stable verification keys."""
    sections = []
    for index, article in enumerate(articles):
        content = article.abstract or article.content or ""
        sections.append(f"[V{index + 1}] {article.title}: {content[:2000]}")
    return "\n\n".join(sections)


async def _call_verification(
    hypothesis: Hypothesis,
    research_goal: str,
    model_name: str,
    tool_registry: Any | None,
    evidence_context: str,
) -> dict[str, Any]:
    """Call the verifier once against the supplied evidence snapshot."""
    prompt, schema = get_deep_verification_prompt(
        research_goal=research_goal,
        hypothesis_text=hypothesis.text,
        tool_registry=tool_registry,
        evidence_context=evidence_context,
    )
    return await call_llm_json(
        prompt=prompt,
        model_name=model_name,
        max_tokens=EXTENDED_MAX_TOKENS,
        temperature=LOW_TEMPERATURE,
        json_schema=schema,
    )


async def _verify_one(
    hypothesis: Hypothesis,
    research_goal: str,
    model_name: str,
    semaphore: asyncio.Semaphore,
    tool_registry: Any | None,
    evidence_context: str,
    state: WorkflowState,
) -> dict[str, Any] | None:
    """Run probing-question deep verification for one hypothesis.

    Args:
        hypothesis: The hypothesis to deep-verify.
        research_goal: The overall research goal for context.
        model_name: Model name in litellm format.
        semaphore: Concurrency limiter shared across verifications.
        tool_registry: Optional registry for domain-specific prompt variables.
        evidence_context: Bounded analyzed-source excerpts.
        state: Full state used to execute targeted probe retrieval.

    Returns:
        The parsed deep-verification result, or None if the call failed.
    """
    evidence_context = _augment_evidence_context_with_meta_review(
        evidence_context, state
    )
    return await _verify_within_semaphore(
        semaphore,
        hypothesis,
        research_goal,
        model_name,
        tool_registry,
        evidence_context,
        state,
    )


async def _verify_within_semaphore(
    semaphore: asyncio.Semaphore,
    hypothesis: Hypothesis,
    research_goal: str,
    model_name: str,
    tool_registry: Any | None,
    evidence_context: str,
    state: WorkflowState,
) -> dict[str, Any] | None:
    """Runs verification bounded by the shared semaphore, isolating failure.

    Bounds concurrent verifications across the whole top-k batch. Broad
    except by design: one hypothesis's failure should not abort the batch;
    None means "leave its probes/verdict untouched."
    """
    async with semaphore:
        try:
            return await _verify_with_probes(
                hypothesis,
                research_goal,
                model_name,
                tool_registry,
                evidence_context,
                state,
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
    research_goal: str,
    model_name: str,
    tool_registry: Any | None,
    evidence_context: str,
    state: WorkflowState,
) -> dict[str, Any]:
    """Runs the initial verification call, then a targeted probe retry."""
    initial = await _call_verification(
        hypothesis, research_goal, model_name, tool_registry, evidence_context
    )
    queries = _probe_queries(initial)
    articles, retrieval_errors = await _retrieve_probe_evidence(state, queries)
    if not articles:
        initial["retrieval_queries"] = queries
        initial["retrieval_errors"] = retrieval_errors
        initial["retrieved_articles"] = []
        initial["verification_llm_calls"] = 1
        return initial
    targeted_context = _retrieved_evidence_context(articles)
    result = await _call_verification(
        hypothesis,
        research_goal,
        model_name,
        tool_registry,
        f"{evidence_context}\n\nTargeted probe evidence:\n{targeted_context}",
    )
    result["retrieval_queries"] = queries
    result["retrieval_errors"] = retrieval_errors
    result["retrieved_articles"] = [article.to_dict() for article in articles]
    result["verification_llm_calls"] = 2
    return result


def _select_hypotheses_to_verify(
    hypotheses: list[Hypothesis],
) -> list[Hypothesis]:
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


def _verification_evidence_context(state: WorkflowState) -> str:
    """Format bounded public and private evidence for verification prompts."""
    sections = []
    for index, article in enumerate(state.get("articles") or []):
        if not article.used_in_analysis:
            continue
        sections.append(
            f"[P{index + 1}] {article.title}: {(article.abstract or '')[:2000]}"
        )
    for index, source in enumerate(
        state.get("context_enrichment_sources") or []
    ):
        sections.append(
            f"[E{index + 1}] {str(source.get('display') or '')[:2500]}"
        )
    return "\n\n".join(sections)[:16000] or "No retrieved evidence available."


def _apply_verification_results(
    to_verify: list[Hypothesis], results: list[dict[str, Any] | None]
) -> int:
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
    for hypothesis, result in zip(to_verify, results, strict=True):
        if result:
            hypothesis.deep_verification_probes = result.get("probes", [])
            hypothesis.deep_verification_verdict = result.get("verdict")
            verified_count += 1
    return verified_count


def merge_retrieved_articles(
    existing: list[Article] | None,
    results: list[dict[str, Any] | None],
) -> list[Article]:
    """Merge targeted verification sources into the run evidence corpus."""
    merged = list(existing or [])
    identities = {
        (article.source, article.source_id or article.doi or article.url)
        for article in merged
    }
    for result in results:
        if not result:
            continue
        for payload in result.get("retrieved_articles") or []:
            article = Article.from_dict(payload)
            identity = (
                article.source,
                article.source_id or article.doi or article.url,
            )
            if identity in identities:
                continue
            identities.add(identity)
            merged.append(article)
    return merged


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
        logger.info(
            "Deep verification: top-%s already verified, skipping",
            DEEP_VERIFICATION_TOP_K,
        )
        return {}

    verified_count, llm_calls = await _run_verification_batch(state, to_verify)
    return _deep_verification_result(
        hypotheses, state["articles"], verified_count, llm_calls
    )


def _deep_verification_result(
    hypotheses: list[Hypothesis],
    articles: list[Article] | None,
    verified_count: int,
    llm_calls: int,
) -> dict[str, Any]:
    """Builds the deep_verification_node state delta after a batch runs."""
    logger.info("Deep verification complete: %s hypotheses", verified_count)
    metrics = create_metrics_update(llm_calls_delta=llm_calls)
    return {
        "hypotheses": hypotheses,
        "articles": articles,
        "metrics": metrics,
        "messages": phase_message(
            "deep_verification",
            f"Deep-verified {verified_count} top hypotheses",
        ),
    }


async def _run_verification_batch(
    state: WorkflowState,
    to_verify: list[Hypothesis],
) -> tuple[int, int]:
    """Runs deep verification for a batch of hypotheses and applies results.

    Verifies concurrently (semaphore-bounded), applies results in place on
    the same Hypothesis objects, and emits progress before and after.

    Args:
        state: Current workflow state.
        to_verify: Hypotheses to verify.

    Returns:
        Count of updated hypotheses and actual verification LLM calls.
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
    verified_count, llm_calls = _finalize_verification_batch(
        to_verify, results, state
    )

    await emit_progress(
        state,
        "deep_verification_complete",
        f"Deep-verified {verified_count} hypotheses",
        PROGRESS_DEEP_VERIFICATION_COMPLETE,
    )

    return verified_count, llm_calls


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
    return await asyncio.gather(
        *[
            _verify_one(
                h,
                state["research_goal"],
                state["model_name"],
                semaphore,
                tool_registry,
                evidence_context,
                state,
            )
            for h in to_verify
        ]
    )


def _finalize_verification_batch(
    to_verify: list[Hypothesis],
    results: list[dict[str, Any] | None],
    state: WorkflowState,
) -> tuple[int, int]:
    """Applies results, merges retrieved articles, and tallies LLM calls."""
    verified_count = _apply_verification_results(to_verify, results)
    state["articles"] = merge_retrieved_articles(state.get("articles"), results)
    llm_calls = sum(
        int(result.get("verification_llm_calls", 1))
        for result in results
        if result
    )
    return verified_count, llm_calls
