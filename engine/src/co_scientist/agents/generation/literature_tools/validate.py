"""Literature validation, novelty analysis and evidence-grounded synthesis."""

import asyncio
import dataclasses
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NamedTuple, Optional, cast

from co_scientist.agents.generation.citations import (
    hypothesis_from_llm_output,
)
from co_scientist.agents.generation.literature_tools.draft import (
    _setup_tool_provider,
)
from co_scientist.constants import (
    DEEP_HYPOTHESIS_MAX_TOKENS,
    EXTENDED_MAX_TOKENS,
    GENERATE_LIT_TOOL_MAX_PAPERS,
    HIGH_TEMPERATURE,
    VALIDATION_SYNTHESIS_BATCH_SIZE,
    VALIDATION_SYNTHESIS_MAX_TOKENS_CAP,
    VALIDATION_SYNTHESIS_TOKENS_PER_HYPOTHESIS,
    corpus_slug,
    get_validate_max_iterations,
    scaled_max_tokens,
    strip_citation_markers,
    truncate_for_prompt,
)
from co_scientist.exceptions import TASK_CONTROL_FLOW_ERRORS
from co_scientist.llm import (
    CompletionSpec,
    LLMCallOptions,
    ToolLoop,
    call_llm_json,
    call_llm_with_tools,
    parse_tool_loop_json,
)
from co_scientist.models import GenerationMethod, Hypothesis
from co_scientist.prompts import (
    ValidationSynthesisRequest,
    get_hypothesis_novelty_analysis_prompt,
    get_validation_synthesis_prompt_with_tools,
)
from co_scientist.schemas import HYPOTHESIS_NOVELTY_ANALYSIS_SCHEMA
from co_scientist.state import WorkflowState
from co_scientist.tools.provider import MCPToolProvider
from co_scientist.tools.response_parser import ResponseParser, parse_mcp_result

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from co_scientist.config import ToolConfig, ToolRegistry


@dataclass(frozen=True)
class _NoveltySearchContext:
    """Shared inputs for the validation phase's per-hypothesis searches.

    Attributes:
        mcp_client: MCP client for tool access.
        tool_registry: Optional ToolRegistry for config-driven tool
            selection.
        shared_slug: Shared corpus slug reused from the draft phase.
        run_id: Current run id, if any.
    """

    mcp_client: Any
    tool_registry: Optional["ToolRegistry"]
    shared_slug: str
    run_id: str | None


def _find_search_tool(
    tool_registry: Optional["ToolRegistry"],
) -> tuple[str | None, Optional["ToolConfig"]]:
    """Find the first search-category tool from the validation workflow.

    Returns (tool_id, tool_config) or (None, None) if no search tool is
    configured.
    """
    if not tool_registry:
        return None, None

    tool_ids = tool_registry.get_tools_for_workflow("validation")
    # First matching tool wins: workflow config order in the YAML controls
    # priority, this loop just picks the first "search"-category entry.
    for tool_id in tool_ids:
        tool_config = tool_registry.get_tool(tool_id)
        if tool_config and tool_config.category in (
            "search",
            "search_with_content",
        ):
            return tool_id, tool_config
    return None, None


def _first(*values: Any) -> Any:
    """Return the first truthy value, or the last value if none are truthy."""
    for value in values:
        if value:
            return value
    return values[-1] if values else None


def _articles_to_paper_dict(articles: list[Any]) -> dict[str, dict[str, Any]]:
    """Converts parsed Article objects into the paper-dict format.

    The output is the format expected by analyze_paper_novelty.

    Args:
        articles: Article objects parsed from a search tool's response.

    Returns:
        {paper_id: {"title": ..., "authors": [...], "year": ...,
        "fulltext": ...}}
    """
    papers: dict[str, dict[str, Any]] = {}
    for article in articles:
        paper_id = _first(article.source_id, article.url, article.title)
        papers[paper_id] = {
            "title": article.title,
            "authors": article.authors,
            "year": article.year,
            "fulltext": _first(article.content, article.abstract, ""),
        }
    return papers


def _build_search_canonical_params(
    hypothesis_text: str,
    max_papers: int,
    shared_slug: str,
    run_id: str | None,
) -> dict[str, Any]:
    """Build the canonical search params for one hypothesis's paper search.

    Canonical params get mapped by the caller through the tool's own
    parameter mapping (domain/tool-specific field names); "slug" carries
    the shared corpus slug so this search reuses the warm corpus.

    Args:
        hypothesis_text: text of the draft hypothesis being validated.
        max_papers: maximum number of papers to retrieve.
        shared_slug: shared corpus slug reused from the draft phase.
        run_id: current run id, if any.

    Returns:
        The canonical search params dict.
    """
    canonical_params: dict[str, Any] = {
        "query": hypothesis_text[:200],
        "max_papers": max_papers,
        "slug": shared_slug,
    }
    if run_id:
        canonical_params["run_id"] = run_id
    return canonical_params


async def _search_papers_via_tool_config(
    tool_config: "ToolConfig",
    hypothesis_text: str,
    ctx: _NoveltySearchContext,
    max_papers: int,
) -> dict[str, dict[str, Any]]:
    """Search for papers for a hypothesis using a resolved config tool.

    Args:
        tool_config: the resolved search tool config for this workflow.
        hypothesis_text: text of the draft hypothesis being validated.
        ctx: shared search inputs (client, registry, slug, run id).
        max_papers: maximum number of papers to retrieve.

    Returns:
        Papers in the dict format expected by analyze_paper_novelty:
        {paper_id: {"title": ..., "authors": [...], "year": ...,
        "fulltext": ...}}
    """
    canonical_params = _build_search_canonical_params(
        hypothesis_text, max_papers, ctx.shared_slug, ctx.run_id
    )
    mapped_params = tool_config.map_parameters(canonical_params)

    result = await ctx.mcp_client.call_tool(
        tool_config.mcp_tool_name, **mapped_params
    )

    # Parse response through ResponseParser -> List[Article]
    parser = ResponseParser(tool_config)
    articles = parser.parse_to_articles(result)

    return _articles_to_paper_dict(articles)


async def _search_papers_legacy_fallback(
    hypothesis_text: str,
    ctx: _NoveltySearchContext,
    max_papers: int,
) -> dict[str, dict[str, Any]]:
    """Search via the legacy pubmed_search_with_fulltext tool directly.

    Used only when no tool_registry is available at all (backwards
    compatibility for callers that never thread one through state).

    Args:
        hypothesis_text: text of the draft hypothesis being validated.
        ctx: shared search inputs (client, registry, slug, run id).
        max_papers: maximum number of papers to retrieve.

    Returns:
        Papers in the dict format expected by analyze_paper_novelty.
    """
    result = await ctx.mcp_client.call_tool(
        "pubmed_search_with_fulltext",
        query=hypothesis_text[:200],
        max_papers=max_papers,
        slug=ctx.shared_slug,
        run_id=ctx.run_id,
    )
    # Generic fallback normalizer (unlike ResponseParser above, which is
    # driven by the tool's YAML-configured response_format).
    return cast(dict[str, dict[str, Any]], parse_mcp_result(result))


def _skip_search_no_tool_configured() -> dict[str, dict[str, Any]]:
    """Log and return no papers when validation has no search tool configured.

    Not an error: returning {} just means there is nothing to compare this
    hypothesis against, so validation continues without it.

    Returns:
        An empty papers dict.
    """
    logger.warning(
        "no search tools configured for validation workflow,"
        " skipping novelty search"
    )
    return {}


async def _search_papers_for_hypothesis(
    hypothesis_text: str,
    ctx: _NoveltySearchContext,
    max_papers: int,
) -> dict[str, dict[str, Any]]:
    """Search for papers related to a hypothesis using config-driven tools.

    Three-way branch: (1) config-driven search via the resolved tool, (2) a
    registry exists but has no search tool configured for validation --
    skip the novelty search rather than error, (3) legacy no-registry
    fallback calling pubmed_search_with_fulltext directly (backwards
    compatibility).

    Args:
        hypothesis_text: text of the draft hypothesis being validated.
        ctx: shared search inputs (client, registry, slug, run id).
        max_papers: maximum number of papers to retrieve.

    Returns:
        Papers in the dict format expected by analyze_paper_novelty:
        {paper_id: {"title": ..., "authors": [...], "year": ...,
        "fulltext": ...}}
    """
    _, tool_config = _find_search_tool(ctx.tool_registry)

    if tool_config:
        return await _search_papers_via_tool_config(
            tool_config, hypothesis_text, ctx, max_papers
        )

    if ctx.tool_registry:
        return _skip_search_no_tool_configured()

    return await _search_papers_legacy_fallback(
        hypothesis_text, ctx, max_papers
    )


# Type of the per-paper novelty analyzer defined in validate.py
# (_analyze_paper_novelty): (hypothesis_text, hypothesis_idx, paper_id,
# metadata, model_name) -> analysis dict or None on failure.
_PaperAnalyzer = Callable[
    [str, int, str, dict[str, Any], str],
    Awaitable[dict[str, Any] | None],
]


@dataclass(frozen=True)
class _NoveltyStageContext:
    """Shared inputs for the Stage 1 novelty-analysis fan-out.

    Attributes:
        model_name: Model to use for the novelty-analysis LLM calls.
        search: Shared search inputs (client, registry, slug, run id).
        analyze_paper: Per-paper novelty analyzer from validate.py.
    """

    model_name: str
    search: _NoveltySearchContext
    analyze_paper: _PaperAnalyzer


def _build_novelty_analysis_prompt(
    hypothesis_text: str, metadata: dict[str, Any]
) -> str:
    """Build the per-paper novelty-analysis prompt, truncating long fulltext.

    Strips the candidate paper's own inline citation markers from the
    prompt copy (``metadata`` itself, standing in for a stored record,
    is left untouched) -- left in, the novelty-verdict model can copy
    one into its own reasoning.

    Args:
        hypothesis_text: text of the draft hypothesis being validated.
        metadata: paper metadata dict (title/authors/year/fulltext).

    Returns:
        The assembled novelty-analysis prompt text.
    """
    fulltext = strip_citation_markers(
        truncate_for_prompt(metadata.get("fulltext", ""))
    )
    return get_hypothesis_novelty_analysis_prompt(
        hypothesis_text=hypothesis_text,
        title=metadata.get("title", "Unknown"),
        authors=metadata.get("authors", []),
        year=metadata.get("year"),
        fulltext=fulltext,
    )


async def _gather_novelty_analyses(
    novelty_analysis_tasks: list[Awaitable[dict[str, Any] | None]],
    idx: int,
) -> list[dict[str, Any]]:
    """Await parallel per-paper novelty analyses and drop failed ones.

    Args:
        novelty_analysis_tasks: pending per-paper novelty-analysis
            coroutines for one hypothesis.
        idx: 1-based index of this draft within the batch, for logging.

    Returns:
        List of successful per-paper novelty analysis results.
    """
    logger.info(
        "Running %s novelty analyses in parallel for hypothesis %s",
        len(novelty_analysis_tasks),
        idx,
    )
    novelty_analyses_results = await asyncio.gather(*novelty_analysis_tasks)

    novelty_analyses = [a for a in novelty_analyses_results if a is not None]
    logger.info(
        "Completed %s novelty analyses for hypothesis %s",
        len(novelty_analyses),
        idx,
    )
    return novelty_analyses


async def _run_parallel_novelty_analyses(
    hypothesis_text: str,
    idx: int,
    papers: dict[str, dict[str, Any]],
    model_name: str,
    analyze_paper: _PaperAnalyzer,
) -> list[dict[str, Any]]:
    """Run per-paper novelty analysis for one hypothesis's papers in parallel.

    Args:
        hypothesis_text: text of the draft hypothesis being validated.
        idx: 1-based index of this draft within the batch, for logging.
        papers: papers to analyze, keyed by paper id, in the dict format
            returned by _search_papers_for_hypothesis.
        model_name: model to use for the novelty-analysis LLM calls.
        analyze_paper: per-paper novelty analyzer from validate.py.

    Returns:
        List of successful per-paper novelty analysis results (failed
        analyses are filtered out).
    """
    # Stage 1a: analyze each paper in parallel for this hypothesis
    novelty_analysis_tasks = [
        analyze_paper(hypothesis_text, idx, paper_id, metadata, model_name)
        for paper_id, metadata in papers.items()
    ]

    if not novelty_analysis_tasks:
        logger.warning("No papers with fulltext found for hypothesis %s", idx)
        return []

    return await _gather_novelty_analyses(novelty_analysis_tasks, idx)


async def _search_papers_for_draft(
    hypothesis_text: str,
    idx: int,
    search_ctx: _NoveltySearchContext,
) -> dict[str, dict[str, Any]]:
    """Search for papers related to one draft, degrading to empty on error.

    Args:
        hypothesis_text: text of the draft hypothesis being validated.
        idx: 1-based index of this draft within the batch, for logging.
        search_ctx: shared search inputs (client, registry, slug, run id).

    Returns:
        Papers in the dict format expected by analyze_paper_novelty, or
        {} if the search failed.
    """
    try:
        papers = await _search_papers_for_hypothesis(
            hypothesis_text,
            search_ctx,
            max_papers=GENERATE_LIT_TOOL_MAX_PAPERS,
        )
        logger.info("Found %s papers for hypothesis %s", len(papers), idx)
        return papers
    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception as e:
        logger.error("Failed to search papers for hypothesis %s: %s", idx, e)
        return {}


async def _gather_hypothesis_novelty_analyses(
    idx: int,
    total: int,
    draft: dict[str, str],
    ctx: _NoveltyStageContext,
) -> dict[str, Any]:
    """Search literature and run per-paper novelty analysis for one draft.

    Args:
        idx: 1-based index of this draft within the batch, for logging.
        total: total number of drafts being processed, for logging.
        draft: draft dict from Phase 1 (keyed "hypothesis" or "text").
        ctx: shared Stage 1 inputs (model, search inputs, analyzer).

    Returns:
        Dict with "draft" and "novelty_analyses" keys.
    """
    # Draft dicts key text as either "hypothesis" or "text"; accept both.
    hypothesis_text = draft.get("hypothesis") or draft.get("text", "")
    logger.info(
        "Analyzing hypothesis %s/%s: %s...", idx, total, hypothesis_text[:80]
    )
    papers = await _search_papers_for_draft(hypothesis_text, idx, ctx.search)
    novelty_analyses = await _run_parallel_novelty_analyses(
        hypothesis_text, idx, papers, ctx.model_name, ctx.analyze_paper
    )

    return {"draft": draft, "novelty_analyses": novelty_analyses}


async def _run_novelty_analysis_stage(
    draft_hypotheses: list[dict[str, str]],
    state: WorkflowState,
    search_ctx: _NoveltySearchContext,
    analyze_paper: _PaperAnalyzer,
) -> list[dict[str, Any]]:
    """Run Stage 1 per-hypothesis novelty analysis for every draft.

    Args:
        draft_hypotheses: list of draft dicts from Phase 1.
        state: current workflow state (used for the novelty-analysis model).
        search_ctx: shared search inputs (client, registry, slug, run id).
        analyze_paper: per-paper novelty analyzer from validate.py.

    Returns:
        List of dicts with "draft" and "novelty_analyses" keys, one per
        draft hypothesis, ready for synthesis.
    """
    ctx = _NoveltyStageContext(
        model_name=state["model_name"],
        search=search_ctx,
        analyze_paper=analyze_paper,
    )
    total_drafts = len(draft_hypotheses)
    return [
        await _gather_hypothesis_novelty_analyses(idx, total_drafts, draft, ctx)
        for idx, draft in enumerate(draft_hypotheses, 1)
    ]


if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry


# Type of the nested `_call_synthesis` closure defined inside
# _run_synthesis_stage_batches in validate.py (it closes over a
# _SynthesisContext); threading it through as a plain callable lets the
# batch-execution/retry helpers below stay free of that closure state.
_SynthesisCaller = Callable[
    [list[dict[str, Any]], str, list[str] | None],
    Awaitable[list[dict[str, Any]]],
]


class _SynthesisContext(NamedTuple):
    """Per-call state shared by every synthesis batch/retry invocation.

    Bundles the locals _run_single_synthesis_call needs beyond its own
    batch/batch_label/already_validated_texts arguments, so callers thread
    one object instead of seven positional locals.
    """

    state: WorkflowState
    research_goal: str
    max_iterations: int
    tool_registry: Optional["ToolRegistry"]
    reference_index: Any | None
    provider: MCPToolProvider
    openai_tools: list[Any]


class _SynthesisCallInputs(NamedTuple):
    """Prompt and token budget assembled for one synthesis batch call."""

    prompt: str
    max_tokens: int


@dataclass(frozen=True)
class _SynthesisRetryState:
    """Accumulators and caller shared across individual synthesis retries.

    Attributes:
        all_validated_hypotheses: Validated hypothesis dicts accumulated so
            far; successful retries are appended here in place.
        accumulated_texts: Hypothesis texts validated so far; extended in
            place so subsequent retries in the same pass see this context.
        call_synthesis: The synthesis callable to invoke per hypothesis.
    """

    all_validated_hypotheses: list[dict[str, Any]]
    accumulated_texts: list[str]
    call_synthesis: _SynthesisCaller


def _setup_validation_tool_provider(
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    total_hypotheses: int,
) -> tuple[MCPToolProvider, list[Any], Optional["ToolRegistry"], int]:
    """Resolve the tool registry/whitelist and init the synthesis provider.

    Also computes the per-call synthesis iteration budget, since it is
    sized from the same total_hypotheses count.

    Args:
        mcp_client: MCP client for tool access.
        tool_registry: optional ToolRegistry for config-driven tool
            selection; resolved from the global registry when None.
        total_hypotheses: total draft count, used to size the iteration
            budget.

    Returns:
        Tuple of (provider, openai_tools, resolved tool_registry,
        max_iterations).
    """
    provider, openai_tools, tool_registry = _setup_tool_provider(
        mcp_client, tool_registry, "validation", "validation", logger
    )

    # Calculate iteration budget for synthesis
    # Sized from the TOTAL hypothesis count but applied per synthesis call,
    # so each batch (and each single-hypothesis retry) gets the full budget.
    max_iterations = get_validate_max_iterations(total_hypotheses)
    logger.info("Validation synthesis budget: %s iterations", max_iterations)

    return provider, openai_tools, tool_registry, max_iterations


def _compute_synthesis_max_tokens(
    batch: list[dict[str, Any]], batch_label: str
) -> int:
    """Scale and log the synthesis call's max-token budget for one batch.

    Args:
        batch: hypothesis batch (with novelty analyses) to synthesize.
        batch_label: label identifying this batch, used in logging.

    Returns:
        The scaled max-tokens budget for this batch's synthesis call.
    """
    # K6: the synthesis writes the final hypotheses at full depth, so the
    # base is the deep-generation budget rather than the generic extended
    # one.
    synthesis_max_tokens = scaled_max_tokens(
        DEEP_HYPOTHESIS_MAX_TOKENS,
        len(batch),
        per_item=VALIDATION_SYNTHESIS_TOKENS_PER_HYPOTHESIS,
        cap=VALIDATION_SYNTHESIS_MAX_TOKENS_CAP,
    )
    logger.debug(
        "Batch %s token budget: %s for %s hypotheses",
        batch_label,
        synthesis_max_tokens,
        len(batch),
    )
    return synthesis_max_tokens


def _build_synthesis_call_inputs(
    batch: list[dict[str, Any]],
    batch_label: str,
    already_validated_texts: list[str] | None,
    ctx: _SynthesisContext,
) -> _SynthesisCallInputs:
    """Build the synthesis prompt and its token budget for one batch.

    Args:
        batch: hypothesis batch (with novelty analyses) to synthesize.
        batch_label: label identifying this batch, used in logging.
        already_validated_texts: hypothesis texts already validated in
            prior batches/retries, or None.
        ctx: shared per-call synthesis state.

    Returns:
        The (prompt, max_tokens) inputs for this batch's synthesis call.
    """
    ref_text = ctx.reference_index.text if ctx.reference_index else ""
    synthesis_prompt, _ = get_validation_synthesis_prompt_with_tools(
        ValidationSynthesisRequest(
            research_goal=ctx.research_goal,
            hypotheses_with_analyses=batch,
            articles=ctx.state.get("articles"),
            articles_with_reasoning=ctx.state.get("articles_with_reasoning"),
            max_iterations=ctx.max_iterations,
            tool_registry=ctx.tool_registry,
            reference_list=ref_text,
            already_validated_texts=already_validated_texts,
        )
    )

    synthesis_max_tokens = _compute_synthesis_max_tokens(batch, batch_label)

    return _SynthesisCallInputs(synthesis_prompt, synthesis_max_tokens)


def _log_synthesis_tool_call_summary(
    batch_label: str,
    tool_call_counts: dict[str, int],
) -> None:
    """Log the total/per-tool call counts for one synthesis batch, if any.

    Args:
        batch_label: label identifying this batch, used in logging.
        tool_call_counts: per-tool-name call counts from the tracked
            executor.
    """
    total_calls = sum(tool_call_counts.values())
    if total_calls > 0:
        calls_summary = ", ".join(
            f"{n}={c}" for n, c in tool_call_counts.items()
        )
        logger.info(
            "Batch %s: %s tool calls (%s)",
            batch_label,
            total_calls,
            calls_summary,
        )


def _parse_synthesis_response(
    final_response: str, batch_label: str
) -> list[dict[str, Any]]:
    """Parse one synthesis batch's final LLM response into hypothesis dicts.

    Args:
        final_response: the synthesis agent's final tool-call-loop response.
        batch_label: label identifying this batch, used in errors/logging.

    Returns:
        The parsed "hypotheses" list from the response.

    Raises:
        ResponseParseError: if the response cannot be parsed as JSON even
            after repair attempts.
    """
    result: list[dict[str, Any]] = parse_tool_loop_json(
        final_response,
        "hypotheses",
        f"Validation synthesis (batch {batch_label})",
    )
    logger.debug(
        "Batch %s synthesis returned %s hypotheses", batch_label, len(result)
    )
    return result


def _partition_synthesis_results(
    batches: list[list[dict[str, Any]]],
    raw_results: list[list[dict[str, Any]] | BaseException],
) -> tuple[list[dict[str, Any]], list[tuple[int, list[dict[str, Any]]]]]:
    """Split gathered synthesis results into validated hypotheses vs failures.

    Args:
        batches: the hypothesis batches the results correspond to.
        raw_results: per-batch results or exceptions from
            asyncio.gather(return_exceptions=True).

    Returns:
        Tuple of (validated hypothesis dicts from batches that succeeded,
        list of (batch_index, batch) pairs for batches that raised).

    Raises:
        LLMRateLimitParkError: A platform cap the worker must park on.
        LLMCallBudgetExceededError: The run's spend ceiling is exhausted.
    """
    # A gather collecting exceptions as values swallows a control-flow
    # error exactly as a bare handler would, and this one is worse than
    # most: a park routed into `failed_batches` is answered by retrying
    # its hypotheses *one at a time* against the cap that just refused
    # the batch. Neither error is per-batch (see TASK_CONTROL_FLOW_ERRORS).
    for result in raw_results:
        if isinstance(result, TASK_CONTROL_FLOW_ERRORS):
            raise result
    all_validated_hypotheses: list[dict[str, Any]] = []
    failed_batches: list[tuple[int, list[dict[str, Any]]]] = []

    for i, result in enumerate(raw_results):
        if isinstance(result, Exception):
            logger.warning(
                "Batch %s failed (%s); will retry hypotheses individually",
                i + 1,
                result,
            )
            failed_batches.append((i, batches[i]))
        else:
            # gather(return_exceptions=True) types results as possibly
            # BaseException; the isinstance branch above already filtered
            # those out, which mypy cannot narrow across the if/else.
            all_validated_hypotheses.extend(result)  # type: ignore[arg-type]

    return all_validated_hypotheses, failed_batches


async def _run_synthesis_batches(
    batches: list[list[dict[str, Any]]],
    call_synthesis: _SynthesisCaller,
) -> tuple[list[dict[str, Any]], list[tuple[int, list[dict[str, Any]]]]]:
    """Run every batch's synthesis call in parallel, isolating failures.

    Args:
        batches: hypothesis batches to run synthesis over.
        call_synthesis: the (batch, batch_label, already_validated_texts)
            synthesis callable to invoke for each batch.

    Returns:
        Tuple of (validated hypothesis dicts from batches that succeeded,
        list of (batch_index, batch) pairs for batches that raised).
    """
    # return_exceptions=True: one batch's exception must not cancel or
    # abort the other batches running concurrently in this gather.
    raw_results = await asyncio.gather(
        *[
            call_synthesis(batch, str(i + 1), None)
            for i, batch in enumerate(batches)
        ],
        return_exceptions=True,
    )

    all_validated_hypotheses, failed_batches = _partition_synthesis_results(
        batches, raw_results
    )
    logger.info(
        "%s/%s batches succeeded, %s need individual retry",
        len(batches) - len(failed_batches),
        len(batches),
        len(failed_batches),
    )

    return all_validated_hypotheses, failed_batches


def _accumulate_retry_result(
    single_result: list[dict[str, Any]],
    all_validated_hypotheses: list[dict[str, Any]],
    accumulated_texts: list[str],
) -> None:
    """Merge one successful individual retry into the shared accumulators.

    Args:
        single_result: the validated hypothesis dict(s) from one retry.
        all_validated_hypotheses: validated hypothesis dicts accumulated so
            far; extended in place.
        accumulated_texts: hypothesis texts validated so far; extended in
            place so subsequent retries in the same pass see this context.
    """
    all_validated_hypotheses.extend(single_result)
    for h in single_result:
        text = h.get("hypothesis", "")
        if text:
            accumulated_texts.append(text)


async def _retry_one_hypothesis(
    batch_idx: int,
    hyp_idx: int,
    hyp_data: dict[str, Any],
    retry_state: _SynthesisRetryState,
) -> None:
    """Retry a single hypothesis from a failed batch, best-effort.

    A hypothesis whose individual retry also fails is dropped; the run
    continues with whatever validated.

    Args:
        batch_idx: 0-based index of the failed batch, used in the retry
            label and error logging.
        hyp_idx: 0-based index of this hypothesis within its failed batch.
        hyp_data: the hypothesis dict to retry.
        retry_state: shared retry accumulators and synthesis callable;
            its lists are extended in place on success.
    """
    label = f"{batch_idx + 1}_retry_{hyp_idx + 1}"
    accumulated_texts = retry_state.accumulated_texts
    context = accumulated_texts if accumulated_texts else None
    try:
        single_result = await retry_state.call_synthesis(
            [hyp_data], label, context
        )
    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception as e:
        logger.error(
            "Individual retry failed for batch %s, hypothesis %s: %s",
            batch_idx + 1,
            hyp_idx + 1,
            e,
        )
        return

    _accumulate_retry_result(
        single_result,
        retry_state.all_validated_hypotheses,
        accumulated_texts,
    )


async def _retry_failed_synthesis_batches(
    failed_batches: list[tuple[int, list[dict[str, Any]]]],
    all_validated_hypotheses: list[dict[str, Any]],
    call_synthesis: _SynthesisCaller,
) -> None:
    """Retry each hypothesis from the failed batches one at a time.

    Single-hypothesis calls shrink the blast radius: one bad hypothesis or
    truncated output no longer sinks its batch-mates.

    Args:
        failed_batches: (batch_index, batch) pairs that failed as a whole
            batch.
        all_validated_hypotheses: validated hypothesis dicts accumulated so
            far; successful retries are appended here in place.
        call_synthesis: the synthesis callable to invoke per hypothesis.
    """
    retry_state = _SynthesisRetryState(
        all_validated_hypotheses=all_validated_hypotheses,
        # Seed context with texts from successful batches
        accumulated_texts=[
            h.get("hypothesis", "")
            for h in all_validated_hypotheses
            if h.get("hypothesis")
        ],
        call_synthesis=call_synthesis,
    )

    for batch_idx, failed_batch in failed_batches:
        for hyp_idx, hyp_data in enumerate(failed_batch):
            await _retry_one_hypothesis(
                batch_idx, hyp_idx, hyp_data, retry_state
            )


def _build_hypotheses_from_synthesis(
    all_validated_hypotheses: list[dict[str, Any]],
    reference_index: Any | None,
) -> list[Hypothesis]:
    """Build Hypothesis objects from the synthesis stage's raw output.

    Output order matches hypotheses_with_analyses order (batched
    sequentially).

    Args:
        all_validated_hypotheses: raw hypothesis dicts from synthesis.
        reference_index: optional citation reference index supplying the
            source map for citation-key resolution.

    Returns:
        List of Hypothesis objects tagged GenerationMethod.LITERATURE_TOOLS.
    """
    ref_sources = reference_index.sources if reference_index else {}
    hypotheses = []
    for hyp_data in all_validated_hypotheses:
        # novelty_validation is this generation path's caller-specific
        # extra field, threaded through hypothesis_from_llm_output's
        # **extra (shared constructor also used by debate.py).
        hypothesis = hypothesis_from_llm_output(
            hyp_data,
            ref_sources,
            GenerationMethod.LITERATURE_TOOLS,
            novelty_validation=hyp_data.get("novelty_validation"),
        )
        hypotheses.append(hypothesis)
    return hypotheses


if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry


def _build_paper_metadata(
    paper_id: str, metadata: dict[str, Any]
) -> dict[str, Any]:
    """Build the paper_metadata sub-dict for a novelty analysis result.

    Args:
        paper_id: identifier for the paper within its hypothesis's paper
            set.
        metadata: paper metadata dict (title/authors/year/fulltext).

    Returns:
        The paper_metadata dict.
    """
    return {
        "paper_id": paper_id,
        "title": metadata.get("title", "Unknown"),
        "year": metadata.get("year"),
        "authors": metadata.get("authors", []),
    }


def _synthesis_tool_contract(
    tool_registry: Optional["ToolRegistry"],
) -> dict[str, Any] | None:
    """Resolve the tool registry's config as a cache-key-able contract.

    The synthesis agent's tool *schema* (names/descriptions/params) is
    already part of the LLM cache key via ``ToolLoop.tools``; this instead
    captures what those tools actually do -- which sources are enabled,
    their endpoints and parameter mappings -- so a registry change that
    leaves the schema untouched still invalidates a cached transcript.
    Mirrors ``agents/generation/literature_review/node.py``'s
    ``_literature_cache_params`` tool_contract.

    Returns:
        The registry config as a plain dict, or None with no registry.
    """
    if tool_registry is None:
        return None
    return dataclasses.asdict(tool_registry.config)


def _batch_hypotheses_for_synthesis(
    hypotheses_with_analyses: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Split Stage 1 output into fixed-size batches for synthesis calls.

    Args:
        hypotheses_with_analyses: Stage 1 output, one dict per draft with
            "draft" and "novelty_analyses" keys.

    Returns:
        List of batches, each up to VALIDATION_SYNTHESIS_BATCH_SIZE long.
    """
    batches = [
        hypotheses_with_analyses[i : i + VALIDATION_SYNTHESIS_BATCH_SIZE]
        for i in range(
            0, len(hypotheses_with_analyses), VALIDATION_SYNTHESIS_BATCH_SIZE
        )
    ]
    logger.info(
        "Split into %s batches of up to %s hypotheses",
        len(batches),
        VALIDATION_SYNTHESIS_BATCH_SIZE,
    )
    return batches


async def _run_and_retry_synthesis_batches(
    batches: list[list[dict[str, Any]]],
    call_synthesis: _SynthesisCaller,
) -> list[dict[str, Any]]:
    """Run every batch and retry any failures one hypothesis at a time.

    Args:
        batches: hypothesis batches to run synthesis over.
        call_synthesis: the synthesis callable to invoke per batch/retry.

    Returns:
        List of validated hypothesis dicts from all batches (including
        individually-retried ones).
    """
    all_validated_hypotheses, failed_batches = await _run_synthesis_batches(
        batches, call_synthesis
    )

    if failed_batches:
        await _retry_failed_synthesis_batches(
            failed_batches, all_validated_hypotheses, call_synthesis
        )

    return all_validated_hypotheses


def _build_synthesis_context(
    hypotheses_with_analyses: list[dict[str, Any]],
    state: WorkflowState,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    reference_index: Any | None,
) -> _SynthesisContext:
    """Resolve the tool provider and assemble the shared synthesis context.

    The research goal is read from state; everything else is threaded in.

    Args:
        hypotheses_with_analyses: Stage 1 output, sized for iteration budget.
        state: current workflow state.
        mcp_client: MCP client for tool access.
        tool_registry: optional ToolRegistry for tool selection.
        reference_index: optional citation reference index.

    Returns:
        The shared per-call synthesis context.
    """
    logger.info(
        "Running validation synthesis for %s hypotheses in batches of %s",
        len(hypotheses_with_analyses),
        VALIDATION_SYNTHESIS_BATCH_SIZE,
    )
    provider, openai_tools, tool_registry, max_iterations = (
        _setup_validation_tool_provider(
            mcp_client, tool_registry, len(hypotheses_with_analyses)
        )
    )
    return _SynthesisContext(
        state,
        state["research_goal"],
        max_iterations,
        tool_registry,
        reference_index,
        provider,
        openai_tools,
    )


if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry


async def _call_novelty_analysis_llm(
    prompt: str, model_name: str
) -> dict[str, Any]:
    """Call the novelty-analysis LLM and return the structured analysis."""
    return await call_llm_json(
        prompt=prompt,
        spec=CompletionSpec(
            model_name=model_name,
            max_tokens=EXTENDED_MAX_TOKENS,
            temperature=HIGH_TEMPERATURE,
            json_schema=HYPOTHESIS_NOVELTY_ANALYSIS_SCHEMA,
        ),
    )


async def _analyze_paper_novelty(
    hypothesis_text: str,
    hypothesis_idx: int,
    paper_id: str,
    metadata: dict[str, Any],
    model_name: str,
) -> dict[str, Any] | None:
    """Analyze a single paper's novelty relative to one draft hypothesis."""
    prompt = _build_novelty_analysis_prompt(hypothesis_text, metadata)

    try:
        analysis = await _call_novelty_analysis_llm(prompt, model_name)
    except TASK_CONTROL_FLOW_ERRORS:
        raise
    except Exception as e:
        logger.error(
            "Failed to analyze paper %s for hypothesis %s: %s",
            paper_id,
            hypothesis_idx,
            e,
        )
        # None is filtered out by the caller rather than aborting the whole
        # hypothesis's novelty analysis over one bad paper.
        return None

    return {
        "paper_metadata": _build_paper_metadata(paper_id, metadata),
        "analysis": analysis,
    }


async def _invoke_synthesis_llm(
    call_inputs: _SynthesisCallInputs,
    batch_label: str,
    ctx: _SynthesisContext,
) -> tuple[str, dict[str, int]]:
    tracked_executor, tool_call_counts = ctx.provider.tracked_executor(
        f"Validation batch {batch_label}"
    )
    final_response, _ = await call_llm_with_tools(
        prompt=call_inputs.prompt,
        spec=CompletionSpec(
            model_name=ctx.state["model_name"],
            max_tokens=call_inputs.max_tokens,
            temperature=HIGH_TEMPERATURE,
        ),
        loop=ToolLoop(
            tools=ctx.openai_tools,
            executor=tracked_executor,
            max_iterations=ctx.max_iterations,
            tool_contract=_synthesis_tool_contract(ctx.tool_registry),
        ),
        options=LLMCallOptions(
            run_id=ctx.state.get("run_id"),
            prompt_name=f"validation_synthesis_batch_{batch_label}",
        ),
    )
    return final_response, tool_call_counts


async def validate_hypotheses(
    state: WorkflowState,
    draft_hypotheses: list[dict[str, str]],
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"] = None,
    reference_index: Any | None = None,
) -> tuple[list[Hypothesis], int]:
    """Phase 2: validate novelty and refine/pivot drafts."""
    logger.info(
        "Phase 2: Validating %s draft hypotheses", len(draft_hypotheses)
    )
    hypotheses_with_analyses = await _run_validate_novelty_stage(
        draft_hypotheses, state, mcp_client, tool_registry
    )
    hypotheses = await _run_synthesis_and_build_hypotheses(
        hypotheses_with_analyses,
        state,
        mcp_client,
        tool_registry,
        reference_index,
    )
    return hypotheses, _count_validation_llm_calls(hypotheses_with_analyses)


async def _run_single_synthesis_call(
    batch: list[dict[str, Any]],
    batch_label: str,
    already_validated_texts: list[str] | None,
    ctx: _SynthesisContext,
) -> list[dict[str, Any]]:
    """Run one synthesis batch call and return the parsed hypotheses list."""
    batch_size = len(batch)
    logger.info(
        "Processing synthesis batch %s (%s hypotheses)", batch_label, batch_size
    )

    call_inputs = _build_synthesis_call_inputs(
        batch, batch_label, already_validated_texts, ctx
    )

    final_response, tool_call_counts = await _invoke_synthesis_llm(
        call_inputs,
        batch_label,
        ctx,
    )
    _log_synthesis_tool_call_summary(batch_label, tool_call_counts)

    return _parse_synthesis_response(final_response, batch_label)


async def _run_synthesis_stage_batches(
    hypotheses_with_analyses: list[dict[str, Any]],
    ctx: _SynthesisContext,
) -> list[dict[str, Any]]:
    """Batch, run, and retry-on-failure the synthesis stage for all drafts."""
    batches = _batch_hypotheses_for_synthesis(hypotheses_with_analyses)

    # Closes over ctx to match the _SynthesisCaller signature used by the
    # batch-execution/retry helpers below.
    async def _call_synthesis(
        batch: list[dict[str, Any]],
        batch_label: str,
        already_validated_texts: list[str] | None,
    ) -> list[dict[str, Any]]:
        """Run one synthesis call and return the parsed hypotheses list."""
        return await _run_single_synthesis_call(
            batch, batch_label, already_validated_texts, ctx
        )

    all_validated_hypotheses = await _run_and_retry_synthesis_batches(
        batches, _call_synthesis
    )
    logger.info(
        "Combined %s validated hypotheses from %s batches",
        len(all_validated_hypotheses),
        len(batches),
    )
    return all_validated_hypotheses


async def _run_validation_synthesis_stage(
    hypotheses_with_analyses: list[dict[str, Any]],
    state: WorkflowState,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    reference_index: Any | None,
) -> list[dict[str, Any]]:
    """Run Stage 2: synthesize approve/refine/pivot decisions for all drafts."""
    ctx = _build_synthesis_context(
        hypotheses_with_analyses,
        state,
        mcp_client,
        tool_registry,
        reference_index,
    )
    return await _run_synthesis_stage_batches(hypotheses_with_analyses, ctx)


async def _run_validate_novelty_stage(
    draft_hypotheses: list[dict[str, str]],
    state: WorkflowState,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
) -> list[dict[str, Any]]:
    """Derive the shared corpus slug and run Stage 1 novelty analysis."""
    # Same deterministic slug the draft phase used (warm corpus reuse).
    shared_slug = corpus_slug(state["research_goal"])
    logger.info("Reusing shared corpus from draft phase: %s", shared_slug)

    search_ctx = _NoveltySearchContext(
        mcp_client=mcp_client,
        tool_registry=tool_registry,
        shared_slug=shared_slug,
        run_id=state.get("run_id"),
    )

    # The per-paper analyzer is threaded in so its call_llm_json seam
    # resolves through validate.py's namespace (tests monkeypatch it
    # there).
    return await _run_novelty_analysis_stage(
        draft_hypotheses,
        state,
        search_ctx,
        analyze_paper=_analyze_paper_novelty,
    )


async def _run_synthesis_and_build_hypotheses(
    hypotheses_with_analyses: list[dict[str, Any]],
    state: WorkflowState,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    reference_index: Any | None,
) -> list[Hypothesis]:
    """Run Stage 2 synthesis and build the final validated Hypothesis list."""
    all_validated_hypotheses = await _run_validation_synthesis_stage(
        hypotheses_with_analyses,
        state,
        mcp_client,
        tool_registry,
        reference_index,
    )

    # Order matches hypotheses_with_analyses order (batched sequentially).
    hypotheses = _build_hypotheses_from_synthesis(
        all_validated_hypotheses, reference_index
    )
    logger.info("Generated %s validated hypotheses", len(hypotheses))
    return hypotheses


def _count_validation_llm_calls(
    hypotheses_with_analyses: list[dict[str, Any]],
) -> int:
    """Estimate successful novelty calls plus one call per synthesis batch.

    Failures, physical retries, and synthesis tool turns can spend more calls;
    this floor retains the legacy node metric alongside transport telemetry.
    """
    novelty_calls = sum(
        len(item.get("novelty_analyses") or [])
        for item in hypotheses_with_analyses
    )
    synthesis_calls = len(
        _batch_hypotheses_for_synthesis(hypotheses_with_analyses)
    )
    return novelty_calls + synthesis_calls
