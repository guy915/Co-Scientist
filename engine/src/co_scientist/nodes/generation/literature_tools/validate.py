"""Phase 2 on lit-tool-based generation: Validate novelty and refine/pivot.

This phase uses a two-stage approach:
1. Per-hypothesis per-paper novelty analysis (parallel)
2. Synthesis agent decides approve/refine/pivot based on analyses (with tool
access)
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Optional, TYPE_CHECKING, cast

from co_scientist.constants import (
    corpus_slug,
    EXTENDED_MAX_TOKENS,
    GENERATE_LIT_TOOL_MAX_PAPERS,
    HIGH_TEMPERATURE,
    VALIDATION_SYNTHESIS_BATCH_SIZE,
    VALIDATION_SYNTHESIS_MAX_TOKENS_CAP,
    VALIDATION_SYNTHESIS_TOKENS_PER_HYPOTHESIS,
    get_validate_max_iterations,
    scaled_max_tokens,
)
from co_scientist.exceptions import ResponseParseError
from co_scientist.llm import call_llm_json, call_llm_with_tools
from co_scientist.llm_json import attempt_json_repair, extract_response_json
from co_scientist.models import GenerationMethod, Hypothesis
from co_scientist.prompts import (
    get_hypothesis_novelty_analysis_prompt,
    get_validation_synthesis_prompt_with_tools,
)
from co_scientist.schemas import (HYPOTHESIS_NOVELTY_ANALYSIS_SCHEMA)
from co_scientist.state import WorkflowState
from co_scientist.nodes.generation.citations import hypothesis_from_llm_output
from co_scientist.tools.provider import MCPToolProvider
from co_scientist.tools.response_parser import ResponseParser, parse_mcp_result

if TYPE_CHECKING:
    from co_scientist.config import ToolConfig, ToolRegistry

logger = logging.getLogger(__name__)

# Type of the nested `_call_synthesis` closure defined inside
# validate_hypotheses (it closes over per-call state like the tool
# provider and research goal); threading it through as a plain callable
# lets the batch-execution/retry helpers below stay free of that closure
# state.
_SynthesisCaller = Callable[[list[dict[str, Any]], str, Optional[list[str]]],
                            Awaitable[list[dict[str, Any]]]]


def _find_search_tool(
    tool_registry: Optional["ToolRegistry"]
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
        if tool_config and tool_config.category in ("search",
                                                    "search_with_content"):
            return tool_id, tool_config
    return None, None


def _articles_to_paper_dict(articles: list[Any]) -> dict[str, dict[str, Any]]:
    """Convert parsed Article objects into the paper-dict format expected
    by analyze_paper_novelty.

    Args:
        articles: Article objects parsed from a search tool's response.

    Returns:
        {paper_id: {"title": ..., "authors": [...], "year": ...,
        "fulltext": ...}}
    """
    papers: dict[str, dict[str, Any]] = {}
    for article in articles:
        paper_id = article.source_id or article.url or article.title
        papers[paper_id] = {
            "title": article.title,
            "authors": article.authors,
            "year": article.year,
            "fulltext": article.content or article.abstract or "",
        }
    return papers


async def _search_papers_via_tool_config(
    tool_config: "ToolConfig",
    hypothesis_text: str,
    mcp_client: Any,
    max_papers: int,
    shared_slug: str,
    run_id: str | None,
) -> dict[str, dict[str, Any]]:
    """Search for papers for a hypothesis using a resolved config tool.

    Args:
        tool_config: the resolved search tool config for this workflow.
        hypothesis_text: text of the draft hypothesis being validated.
        mcp_client: MCP client for tool access.
        max_papers: maximum number of papers to retrieve.
        shared_slug: shared corpus slug reused from the draft phase.
        run_id: current run id, if any.

    Returns:
        Papers in the dict format expected by analyze_paper_novelty:
        {paper_id: {"title": ..., "authors": [...], "year": ...,
        "fulltext": ...}}
    """
    # Canonical params get mapped below through the tool's own parameter
    # mapping (domain/tool-specific field names); "slug" carries the
    # shared corpus slug so this search reuses the warm corpus.
    canonical_params = {
        "query": hypothesis_text[:200],
        "max_papers": max_papers,
        "slug": shared_slug,
    }
    if run_id:
        canonical_params["run_id"] = run_id
    mapped_params = tool_config.map_parameters(canonical_params)

    result = await mcp_client.call_tool(tool_config.mcp_tool_name,
                                        **mapped_params)

    # Parse response through ResponseParser -> List[Article]
    parser = ResponseParser(tool_config)
    articles = parser.parse_to_articles(result)

    return _articles_to_paper_dict(articles)


async def _search_papers_for_hypothesis(
    hypothesis_text: str,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    max_papers: int,
    shared_slug: str,
    run_id: str | None,
) -> dict[str, dict[str, Any]]:
    """Search for papers related to a hypothesis using config-driven tools.

    Returns papers in the dict format expected by analyze_paper_novelty:
    {paper_id: {"title": ..., "authors": [...], "year": ...,
    "fulltext": ...}}

    Falls back to pubmed_search_with_fulltext when no tool_registry is provided
    (backwards compatibility).
    """
    # Three-way branch: (1) config-driven search via the resolved tool,
    # (2) a registry exists but has no search tool configured for
    # validation -- skip the novelty search rather than error, (3) legacy
    # no-registry fallback calling pubmed_search_with_fulltext directly.
    _, tool_config = _find_search_tool(tool_registry)

    if tool_config:
        return await _search_papers_via_tool_config(tool_config,
                                                    hypothesis_text, mcp_client,
                                                    max_papers, shared_slug,
                                                    run_id)

    if tool_registry:
        # Registry exists but has no search tools for validation — skip novelty
        # search
        # Not an error: returning {} just means there is nothing to compare
        # this hypothesis against, so validation continues without it.
        logger.warning("no search tools configured for validation workflow,"
                       " skipping novelty search")
        return {}

    # Legacy fallback: no registry at all, try pubmed directly
    result = await mcp_client.call_tool(
        "pubmed_search_with_fulltext",
        query=hypothesis_text[:200],
        max_papers=max_papers,
        slug=shared_slug,
        run_id=run_id,
    )
    # Generic fallback normalizer (unlike ResponseParser above, which is
    # driven by the tool's YAML-configured response_format).
    return cast(dict[str, dict[str, Any]], parse_mcp_result(result))


async def _analyze_paper_novelty(
    hypothesis_text: str,
    hypothesis_idx: int,
    paper_id: str,
    metadata: dict[str, Any],
    model_name: str,
) -> dict[str, Any] | None:
    """Analyze a single paper's novelty relative to one draft hypothesis.

    Args:
        hypothesis_text: text of the draft hypothesis being validated.
        hypothesis_idx: 1-based index of the hypothesis, for log messages.
        paper_id: identifier for the paper within its hypothesis's paper set.
        metadata: paper metadata dict (title/authors/year/fulltext).
        model_name: model to use for the novelty-analysis LLM call.

    Returns:
        Dict with "paper_metadata" and "analysis" keys, or None if the
        analysis call failed (failures are logged, not raised, so one bad
        paper does not abort the hypothesis's whole novelty analysis).
    """
    fulltext = metadata.get("fulltext", "")

    # Truncate if too long
    max_chars = 200_000
    # Keeps the per-paper prompt size bounded regardless of how long the
    # source paper's fulltext is.
    if len(fulltext) > max_chars:
        fulltext = fulltext[:max_chars] + "\n\n[... truncated for length ...]"

    # Extract paper info
    title = metadata.get("title", "Unknown")
    authors = metadata.get("authors", [])
    year = metadata.get("year")

    # Get analysis prompt
    prompt = get_hypothesis_novelty_analysis_prompt(
        hypothesis_text=hypothesis_text,
        title=title,
        authors=authors,
        year=year,
        fulltext=fulltext,
    )

    # Call LLM for structured analysis
    try:
        analysis = await call_llm_json(
            prompt=prompt,
            model_name=model_name,
            json_schema=HYPOTHESIS_NOVELTY_ANALYSIS_SCHEMA,
            max_tokens=EXTENDED_MAX_TOKENS,
            temperature=HIGH_TEMPERATURE,
        )

        return {
            "paper_metadata": {
                "paper_id": paper_id,
                "title": title,
                "year": year,
                "authors": authors,
            },
            "analysis": analysis,
        }
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to analyze paper %s for hypothesis %s: %s",
                     paper_id, hypothesis_idx, e)
        # None is filtered out by the caller rather than aborting the whole
        # hypothesis's novelty analysis over one bad paper.
        return None


async def _run_parallel_novelty_analyses(
    hypothesis_text: str,
    idx: int,
    papers: dict[str, dict[str, Any]],
    model_name: str,
) -> list[dict[str, Any]]:
    """Run per-paper novelty analysis for one hypothesis's papers in parallel.

    Args:
        hypothesis_text: text of the draft hypothesis being validated.
        idx: 1-based index of this draft within the batch, for logging.
        papers: papers to analyze, keyed by paper id, in the dict format
            returned by _search_papers_for_hypothesis.
        model_name: model to use for the novelty-analysis LLM calls.

    Returns:
        List of successful per-paper novelty analysis results (failed
        analyses are filtered out).
    """
    # Stage 1a: analyze each paper in parallel for this hypothesis
    novelty_analysis_tasks = [
        _analyze_paper_novelty(hypothesis_text, idx, paper_id, metadata,
                               model_name)
        for paper_id, metadata in papers.items()
    ]

    if novelty_analysis_tasks:
        logger.info("Running %s novelty analyses in parallel for hypothesis %s",
                    len(novelty_analysis_tasks), idx)
        novelty_analyses_results = await asyncio.gather(*novelty_analysis_tasks)

        # Filter out failed analyses
        novelty_analyses = [
            a for a in novelty_analyses_results if a is not None
        ]
        logger.info("Completed %s novelty analyses for hypothesis %s",
                    len(novelty_analyses), idx)
    else:
        novelty_analyses = []
        logger.warning("No papers with fulltext found for hypothesis %s", idx)

    return novelty_analyses


async def _gather_hypothesis_novelty_analyses(
    idx: int,
    total: int,
    draft: dict[str, str],
    model_name: str,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    shared_slug: str,
    run_id: str | None,
) -> dict[str, Any]:
    """Search literature and run per-paper novelty analysis for one draft.

    Args:
        idx: 1-based index of this draft within the batch, for logging.
        total: total number of drafts being processed, for logging.
        draft: draft hypothesis dict from Phase 1 (keyed "hypothesis" or
            "text").
        model_name: model to use for the novelty-analysis LLM calls.
        mcp_client: MCP client for tool access.
        tool_registry: optional ToolRegistry for config-driven tool
            selection.
        shared_slug: shared corpus slug reused from the draft phase.
        run_id: current run id, if any.

    Returns:
        Dict with "draft" and "novelty_analyses" keys, ready for synthesis.
    """
    # Draft dicts may key the text as either "hypothesis" or "text"
    # depending on how Phase 1's LLM output named the field; accept both.
    hypothesis_text = draft.get("hypothesis") or draft.get("text", "")
    logger.info("Analyzing hypothesis %s/%s: %s...", idx, total,
                hypothesis_text[:80])

    # Search for papers related to this hypothesis (config-driven)
    try:
        papers = await _search_papers_for_hypothesis(
            hypothesis_text=hypothesis_text,
            mcp_client=mcp_client,
            tool_registry=tool_registry,
            max_papers=GENERATE_LIT_TOOL_MAX_PAPERS,
            shared_slug=shared_slug,
            run_id=run_id,
        )
        logger.info("Found %s papers for hypothesis %s", len(papers), idx)

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Failed to search papers for hypothesis %s: %s", idx, e)
        papers = {}

    novelty_analyses = await _run_parallel_novelty_analyses(
        hypothesis_text, idx, papers, model_name)

    return {"draft": draft, "novelty_analyses": novelty_analyses}


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
    # get tool registry if not provided
    if tool_registry is None:
        try:
            from co_scientist.config import get_tool_registry  # pylint: disable=import-outside-toplevel
            tool_registry = get_tool_registry()
            logger.info("Using global tool registry for validation")
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to get tool registry: %s", e)

    # Initialize hybrid tool provider
    provider = MCPToolProvider(mcp_client=mcp_client)

    # Get tool whitelist from registry
    if tool_registry:
        tool_ids = tool_registry.get_tools_for_workflow("validation")
        mcp_whitelist = tool_registry.get_mcp_tool_names(tool_ids)
        logger.info("Validation tool whitelist: %s", mcp_whitelist)
    else:
        mcp_whitelist = None
        logger.warning("No tool registry - using all available MCP tools")

    tools_dict, openai_tools = provider.get_tools(mcp_whitelist=mcp_whitelist)
    logger.info("Initialized validation provider with %s tools",
                len(tools_dict))

    # Calculate iteration budget for synthesis
    # Sized from the TOTAL hypothesis count but applied per synthesis call,
    # so each batch (and each single-hypothesis retry) gets the full budget.
    max_iterations = get_validate_max_iterations(total_hypotheses)
    logger.info("Validation synthesis budget: %s iterations", max_iterations)

    return provider, openai_tools, tool_registry, max_iterations


def _parse_synthesis_response(final_response: str,
                              batch_label: str) -> list[dict[str, Any]]:
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
    response_text = extract_response_json(final_response)
    response_data, was_repaired = attempt_json_repair(response_text,
                                                      allow_major_repairs=True)

    if response_data is None:
        logger.error("Failed to parse batch %s JSON response", batch_label)
        logger.error("Response: %s...", final_response[:500])
        raise ResponseParseError("Validation synthesis returned invalid JSON"
                                 f" (batch {batch_label})")

    if was_repaired:
        logger.warning("Batch %s JSON required repairs", batch_label)

    result: list[dict[str, Any]] = response_data.get("hypotheses", [])
    logger.debug("Batch %s synthesis returned %s hypotheses", batch_label,
                 len(result))
    return result


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

    all_validated_hypotheses: list[dict[str, Any]] = []
    failed_batches: list[tuple[int, list[dict[str, Any]]]] = []

    for i, result in enumerate(raw_results):
        if isinstance(result, Exception):
            logger.warning(
                "Batch %s failed (%s); will retry hypotheses individually",
                i + 1, result)
            failed_batches.append((i, batches[i]))
        else:
            all_validated_hypotheses.extend(result)  # type: ignore[arg-type]

    logger.info("%s/%s batches succeeded, %s need individual retry",
                len(batches) - len(failed_batches), len(batches),
                len(failed_batches))

    return all_validated_hypotheses, failed_batches


async def _retry_one_hypothesis(
    batch_idx: int,
    hyp_idx: int,
    hyp_data: dict[str, Any],
    accumulated_texts: list[str],
    all_validated_hypotheses: list[dict[str, Any]],
    call_synthesis: _SynthesisCaller,
) -> None:
    """Retry a single hypothesis from a failed batch, best-effort.

    A hypothesis whose individual retry also fails is dropped; the run
    continues with whatever validated. Successful results are appended to
    ``all_validated_hypotheses`` and their texts to ``accumulated_texts`` in
    place, so subsequent retries in the same pass see this one's context.

    Args:
        batch_idx: 0-based index of the failed batch this hypothesis came
            from, used in the retry label and error logging.
        hyp_idx: 0-based index of this hypothesis within its failed batch,
            used in the retry label and error logging.
        hyp_data: the hypothesis dict to retry.
        accumulated_texts: hypothesis texts validated so far; extended in
            place on success.
        all_validated_hypotheses: validated hypothesis dicts accumulated so
            far; extended in place on success.
        call_synthesis: the synthesis callable to invoke per hypothesis.
    """
    label = f"{batch_idx + 1}_retry_{hyp_idx + 1}"
    context = accumulated_texts if accumulated_texts else None
    try:
        single_result = await call_synthesis([hyp_data], label, context)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error(
            "Individual retry failed for batch %s,"
            " hypothesis %s: %s", batch_idx + 1, hyp_idx + 1, e)
        return

    all_validated_hypotheses.extend(single_result)
    # Accumulate for subsequent retries within this loop
    for h in single_result:
        text = h.get("hypothesis", "")
        if text:
            accumulated_texts.append(text)


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
    # Seed context with texts from successful batches
    accumulated_texts: list[str] = [
        h.get("hypothesis", "")
        for h in all_validated_hypotheses
        if h.get("hypothesis")
    ]

    for batch_idx, failed_batch in failed_batches:
        for hyp_idx, hyp_data in enumerate(failed_batch):
            await _retry_one_hypothesis(batch_idx, hyp_idx, hyp_data,
                                        accumulated_texts,
                                        all_validated_hypotheses,
                                        call_synthesis)


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


async def _run_novelty_analysis_stage(
    draft_hypotheses: list[dict[str, str]],
    state: WorkflowState,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    shared_slug: str,
    run_id: str | None,
) -> list[dict[str, Any]]:
    """Run Stage 1 per-hypothesis novelty analysis for every draft.

    Args:
        draft_hypotheses: list of draft dicts from Phase 1.
        state: current workflow state (used for the novelty-analysis model).
        mcp_client: MCP client for tool access.
        tool_registry: optional ToolRegistry for config-driven tool
            selection.
        shared_slug: shared corpus slug reused from the draft phase.
        run_id: current run id, if any.

    Returns:
        List of dicts with "draft" and "novelty_analyses" keys, one per
        draft hypothesis, ready for synthesis.
    """
    total_drafts = len(draft_hypotheses)
    hypotheses_with_analyses = []
    for idx, draft in enumerate(draft_hypotheses, 1):
        hypotheses_with_analyses.append(await
                                        _gather_hypothesis_novelty_analyses(
                                            idx, total_drafts, draft,
                                            state["model_name"], mcp_client,
                                            tool_registry, shared_slug, run_id))
    return hypotheses_with_analyses


async def _run_single_synthesis_call(
    batch: list[dict[str, Any]],
    batch_label: str,
    already_validated_texts: list[str] | None,
    state: WorkflowState,
    research_goal: str,
    max_iterations: int,
    tool_registry: Optional["ToolRegistry"],
    reference_index: Any | None,
    provider: MCPToolProvider,
    openai_tools: list[Any],
) -> list[dict[str, Any]]:
    """Run one synthesis batch call and return the parsed hypotheses list.

    already_validated_texts lets a retried single-hypothesis call see what
    has already been validated, so the synthesis agent is less likely to
    produce a near-duplicate on retry.

    Args:
        batch: hypothesis batch (with novelty analyses) to synthesize.
        batch_label: label identifying this batch, used in logging.
        already_validated_texts: hypothesis texts already validated in
            prior batches/retries, or None.
        state: current workflow state.
        research_goal: the run's research goal text.
        max_iterations: synthesis tool-calling iteration budget.
        tool_registry: optional ToolRegistry for config-driven tool
            selection.
        reference_index: optional citation reference index supplying the
            `[C*]` reference list.
        provider: the validation-phase MCP tool provider.
        openai_tools: OpenAI-format tool schemas available to the agent.

    Returns:
        The parsed "hypotheses" list from the synthesis response.
    """
    batch_size = len(batch)
    logger.info("Processing synthesis batch %s (%s hypotheses)", batch_label,
                batch_size)

    ref_text = reference_index.text if reference_index else ""
    synthesis_prompt, _ = get_validation_synthesis_prompt_with_tools(
        research_goal=research_goal,
        hypotheses_with_analyses=batch,
        articles=state.get("articles"),
        articles_with_reasoning=state.get("articles_with_reasoning"),
        max_iterations=max_iterations,
        tool_registry=tool_registry,
        reference_list=ref_text,
        already_validated_texts=already_validated_texts,
    )

    synthesis_max_tokens = scaled_max_tokens(
        EXTENDED_MAX_TOKENS,
        batch_size,
        per_item=VALIDATION_SYNTHESIS_TOKENS_PER_HYPOTHESIS,
        cap=VALIDATION_SYNTHESIS_MAX_TOKENS_CAP,
    )
    logger.debug("Batch %s token budget: %s for %s hypotheses", batch_label,
                 synthesis_max_tokens, batch_size)

    tracked_executor, tool_call_counts = provider.tracked_executor(
        f"Validation batch {batch_label}")

    final_response, _ = await call_llm_with_tools(
        prompt=synthesis_prompt,
        model_name=state["model_name"],
        tools=openai_tools,
        tool_executor=tracked_executor,
        max_tokens=synthesis_max_tokens,
        temperature=HIGH_TEMPERATURE,
        max_iterations=max_iterations,
        run_id=state.get("run_id"),
        prompt_name=f"validation_synthesis_batch_{batch_label}",
        prompt_metadata={
            "batch_label":
                batch_label,
            "batch_size":
                batch_size,
            "max_iterations":
                max_iterations,
            "retry_context_count":
                len(already_validated_texts) if already_validated_texts else 0,
        },
    )

    total_calls = sum(tool_call_counts.values())
    if total_calls > 0:
        calls_summary = ", ".join(
            f"{n}={c}" for n, c in tool_call_counts.items())
        logger.info("Batch %s: %s tool calls (%s)", batch_label, total_calls,
                    calls_summary)

    return _parse_synthesis_response(final_response, batch_label)


async def validate_hypotheses(
    state: WorkflowState,
    draft_hypotheses: list[dict[str, str]],
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"] = None,
    reference_index: Any | None = None,
) -> list[Hypothesis]:
    """Phase 2: validate novelty and refine/pivot drafts.

    Two-stage approach:
    1. per-hypothesis per-paper novelty analysis (parallel)
    2. synthesis agent decides approve/refine/pivot (with tool access for
    pivoting)

    Args:
        state: current workflow state
        draft_hypotheses: list of draft dicts from Phase 1
        mcp_client: MCP client for tool access
        tool_registry: optional ToolRegistry for config-driven tool selection
        reference_index: optional citation reference index supplying the
            `[C*]` reference list and source map

    Returns:
        list of validated Hypothesis objects with novelty_validation
    """
    logger.info("Phase 2: Validating %s draft hypotheses",
                len(draft_hypotheses))

    # Get state variables
    run_id = state.get("run_id")
    research_goal = state["research_goal"]

    # Same deterministic slug the draft phase used (warm corpus reuse).
    shared_slug = corpus_slug(research_goal)
    logger.info("Reusing shared corpus from draft phase: %s", shared_slug)

    # Stage 1: per-hypothesis novelty analysis
    hypotheses_with_analyses = await _run_novelty_analysis_stage(
        draft_hypotheses, state, mcp_client, tool_registry, shared_slug, run_id)

    # Stage 2: synthesis - decide approve/refine/pivot for all hypotheses
    # synthesis agent has tool access for searching additional papers when
    # pivoting
    total_hypotheses = len(hypotheses_with_analyses)

    logger.info(
        "Running validation synthesis for %s hypotheses in batches of %s",
        total_hypotheses, VALIDATION_SYNTHESIS_BATCH_SIZE)

    provider, openai_tools, tool_registry, max_iterations = (
        _setup_validation_tool_provider(mcp_client, tool_registry,
                                        total_hypotheses))

    # Batch hypotheses
    batches = [
        hypotheses_with_analyses[i:i + VALIDATION_SYNTHESIS_BATCH_SIZE]
        for i in range(0, total_hypotheses, VALIDATION_SYNTHESIS_BATCH_SIZE)
    ]
    logger.info("Split into %s batches of up to %s hypotheses", len(batches),
                VALIDATION_SYNTHESIS_BATCH_SIZE)

    # Thin wrapper around the module-level synthesis call: keeps the
    # _SynthesisCaller signature (batch, batch_label, already_validated_texts)
    # used by the batch-execution/retry helpers below, while threading the
    # per-call state (provider, openai_tools, max_iterations, tool_registry,
    # research_goal, reference_index) through as explicit arguments.
    async def _call_synthesis(
        batch: list[dict[str, Any]],
        batch_label: str,
        already_validated_texts: list[str] | None,
    ) -> list[dict[str, Any]]:
        """Run one synthesis call and return the parsed hypotheses list."""
        return await _run_single_synthesis_call(batch, batch_label,
                                                already_validated_texts, state,
                                                research_goal, max_iterations,
                                                tool_registry, reference_index,
                                                provider, openai_tools)

    # Execute all batches in parallel; capture failures without aborting,
    # then retry any failed batches one hypothesis at a time.
    all_validated_hypotheses, failed_batches = await _run_synthesis_batches(
        batches, _call_synthesis)

    if failed_batches:
        await _retry_failed_synthesis_batches(failed_batches,
                                              all_validated_hypotheses,
                                              _call_synthesis)

    logger.info("Combined %s validated hypotheses from %s batches",
                len(all_validated_hypotheses), len(batches))

    # Create Hypothesis objects from synthesis output; order matches
    # hypotheses_with_analyses order (batched sequentially).
    hypotheses = _build_hypotheses_from_synthesis(all_validated_hypotheses,
                                                  reference_index)

    logger.info("Generated %s validated hypotheses", len(hypotheses))
    return hypotheses
