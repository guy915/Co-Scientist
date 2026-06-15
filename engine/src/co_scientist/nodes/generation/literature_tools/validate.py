# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Phase 2 on lit-tool-based generation: Validate novelty and refine/pivot.

This phase uses a two-stage approach:
1. Per-hypothesis per-paper novelty analysis (parallel)
2. Synthesis agent decides approve/refine/pivot based on analyses (with tool
access)
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING, cast

from co_scientist.constants import (
    EXTENDED_MAX_TOKENS,
    GENERATE_LIT_TOOL_MAX_PAPERS,
    HIGH_TEMPERATURE,
    INITIAL_ELO_RATING,
    VALIDATION_SYNTHESIS_BATCH_SIZE,
    get_validate_max_iterations,
)
from co_scientist.exceptions import ResponseParseError
from co_scientist.llm import (
    call_llm_json,
    call_llm_with_tools,
    attempt_json_repair,
)
from co_scientist.models import GenerationMethod, Hypothesis
from co_scientist.prompts import (
    get_hypothesis_novelty_analysis_prompt,
    get_validation_synthesis_prompt_with_tools,
)
from co_scientist.schemas import (HYPOTHESIS_NOVELTY_ANALYSIS_SCHEMA)
from co_scientist.state import WorkflowState
from co_scientist.tools.literature import literature_tools
from co_scientist.nodes.generation.citations import resolve_citation_keys
from co_scientist.tools.provider import HybridToolProvider
from co_scientist.tools.response_parser import ResponseParser

if TYPE_CHECKING:
    from co_scientist.config import ToolConfig, ToolRegistry

logger = logging.getLogger(__name__)


def _extract_papers_for_hypothesis(
    hypothesis_with_analyses: Dict[str, Any],
    literature_grounding: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Extract papers cited by this hypothesis from novelty analysis metadata.

    When literature_grounding is available, filters to only papers whose
    author+year appear in the grounding text. Falls back to all analyzed
    papers for this hypothesis when grounding is empty or has no matches.
    """
    from co_scientist.nodes.generation.papers import analyses_to_candidates, filter_papers_by_grounding  # pylint: disable=import-outside-toplevel

    analyses = hypothesis_with_analyses.get("novelty_analyses", [])
    candidates = analyses_to_candidates(analyses)

    if literature_grounding:
        matched = filter_papers_by_grounding(candidates, literature_grounding)
        if matched:
            return matched

    # fallback: return all papers analyzed for this hypothesis
    return [{"title": c["title"], "url": c["url"]} for c in candidates]


def _find_search_tool(
    tool_registry: Optional["ToolRegistry"]
) -> Tuple[Optional[str], Optional["ToolConfig"]]:
    """Find the first search-category tool from the validation workflow.

    Returns (tool_id, tool_config) or (None, None) if no search tool is
    configured.
    """
    if not tool_registry:
        return None, None

    tool_ids = tool_registry.get_tools_for_workflow("validation")
    for tool_id in tool_ids:
        tool_config = tool_registry.get_tool(tool_id)
        if tool_config and tool_config.category in ("search",
                                                    "search_with_content"):
            return tool_id, tool_config
    return None, None


async def _search_papers_for_hypothesis(
    hypothesis_text: str,
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"],
    max_papers: int,
    shared_slug: str,
    run_id: Optional[str],
) -> Dict[str, Dict[str, Any]]:
    """Search for papers related to a hypothesis using config-driven tools.

    Returns papers in the dict format expected by analyze_paper_novelty:
    {paper_id: {"title": ..., "authors": [...], "year": ...,
    "fulltext": ...}}

    Falls back to pubmed_search_with_fulltext when no tool_registry is provided
    (backwards compatibility).
    """
    _, tool_config = _find_search_tool(tool_registry)

    if tool_config:
        # config-driven search
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

        # parse response through ResponseParser -> List[Article]
        parser = ResponseParser(tool_config)
        articles = parser.parse_to_articles(result)

        # convert List[Article] to the {paper_id: {...}} dict format
        papers = {}
        for article in articles:
            paper_id = article.source_id or article.url or article.title
            papers[paper_id] = {
                "title": article.title,
                "authors": article.authors,
                "year": article.year,
                "fulltext": article.content or article.abstract or "",
            }
        return papers

    if tool_registry:
        # registry exists but has no search tools for validation — skip novelty
        # search
        logger.warning("no search tools configured for validation workflow,"
                       " skipping novelty search")
        return {}

    # legacy fallback: no registry at all, try pubmed directly
    result = await mcp_client.call_tool(
        "pubmed_search_with_fulltext",
        query=hypothesis_text[:200],
        max_papers=max_papers,
        slug=shared_slug,
        run_id=run_id,
    )
    if isinstance(result, str):
        return cast(Dict[str, Dict[str, Any]], json.loads(result))
    return cast(Dict[str, Dict[str, Any]], result)


async def validate_hypotheses(
    state: WorkflowState,
    draft_hypotheses: List[Dict[str, str]],
    mcp_client: Any,
    tool_registry: Optional["ToolRegistry"] = None,
    reference_index: Optional[Any] = None,
) -> List[Hypothesis]:
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

    Returns:
        list of validated Hypothesis objects with novelty_validation
    """
    logger.info("Phase 2: Validating %s draft hypotheses",
                len(draft_hypotheses))

    # get state variables
    run_id = state.get("run_id")
    research_goal = state["research_goal"]

    # get shared slug from draft phase (warm corpus reuse)
    shared_slug = state.get("generation_corpus_slug")
    if not shared_slug:
        # fallback if draft phase didn't set it
        import hashlib  # pylint: disable=import-outside-toplevel

        shared_slug = "research_" + hashlib.md5(
            research_goal.encode()).hexdigest()[:8]
        logger.warning("Draft phase didn't set corpus slug, using fallback: %s",
                       shared_slug)
    else:
        logger.info("Reusing shared corpus from draft phase: %s", shared_slug)

    # stage 1: per-hypothesis novelty analysis
    hypotheses_with_analyses = []

    for idx, draft in enumerate(draft_hypotheses, 1):
        hypothesis_text = draft.get("hypothesis") or draft.get("text", "")
        logger.info("Analyzing hypothesis %s/%s: %s...", idx,
                    len(draft_hypotheses), hypothesis_text[:80])

        # search for papers related to this hypothesis (config-driven)
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
            logger.error("Failed to search papers for hypothesis %s: %s", idx,
                         e)
            papers = {}

        # stage 1a: analyze each paper in parallel for this hypothesis
        novelty_analysis_tasks = []

        async def analyze_paper_novelty(
                paper_id: str, metadata: Dict[str,
                                              Any]) -> Optional[Dict[str, Any]]:
            """Analyze single paper for novelty assessment."""
            fulltext = metadata.get("fulltext", "")

            # truncate if too long
            max_chars = 200_000
            if len(fulltext) > max_chars:
                fulltext = (fulltext[:max_chars] +
                            "\n\n[... truncated for length ...]")

            # extract paper info
            title = metadata.get("title", "Unknown")
            authors = metadata.get("authors", [])
            year = metadata.get("year")

            # get analysis prompt
            prompt = get_hypothesis_novelty_analysis_prompt(
                hypothesis_text=hypothesis_text,  # pylint: disable=cell-var-from-loop
                title=title,
                authors=authors,
                year=year,
                fulltext=fulltext,
            )

            # call LLM for structured analysis
            try:
                analysis = await call_llm_json(
                    prompt=prompt,
                    model_name=state["model_name"],
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
                logger.error(
                    "Failed to analyze paper %s for hypothesis %s: %s",
                    paper_id,
                    idx,  # pylint: disable=cell-var-from-loop
                    e)
                return None

        # analyze all papers in parallel
        for paper_id, metadata in papers.items():
            task = analyze_paper_novelty(paper_id, metadata)
            novelty_analysis_tasks.append(task)

        if novelty_analysis_tasks:
            logger.info(
                "Running %s novelty analyses in parallel for hypothesis %s",
                len(novelty_analysis_tasks), idx)
            novelty_analyses_results = await asyncio.gather(
                *novelty_analysis_tasks)

            # filter out failed analyses
            novelty_analyses = [
                a for a in novelty_analyses_results if a is not None
            ]
            logger.info("Completed %s novelty analyses for hypothesis %s",
                        len(novelty_analyses), idx)
        else:
            novelty_analyses = []
            logger.warning("No papers with fulltext found for hypothesis %s",
                           idx)

        # collect hypothesis with its analyses
        hypotheses_with_analyses.append({
            "draft": draft,
            "novelty_analyses": novelty_analyses
        })

    # stage 2: synthesis - decide approve/refine/pivot for all hypotheses
    # synthesis agent has tool access for searching additional papers when
    # pivoting
    total_hypotheses = len(hypotheses_with_analyses)

    logger.info(
        "Running validation synthesis for %s hypotheses in batches of %s",
        total_hypotheses, VALIDATION_SYNTHESIS_BATCH_SIZE)

    # set up tool provider for synthesis phase
    # get tool registry if not provided
    if tool_registry is None:
        try:
            from co_scientist.config import get_tool_registry  # pylint: disable=import-outside-toplevel
            tool_registry = get_tool_registry()
            logger.info("Using global tool registry for validation")
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Failed to get tool registry: %s", e)

    # initialize hybrid tool provider
    provider = HybridToolProvider(mcp_client=mcp_client,
                                  python_registry=literature_tools)

    # get tool whitelist from registry
    if tool_registry:
        tool_ids = tool_registry.get_tools_for_workflow("validation")
        mcp_whitelist = tool_registry.get_mcp_tool_names(tool_ids)
        logger.info("Validation tool whitelist: %s", mcp_whitelist)
    else:
        mcp_whitelist = None
        logger.warning("No tool registry - using all available MCP tools")

    tools_dict, openai_tools = provider.get_tools(mcp_whitelist=mcp_whitelist,
                                                  python_whitelist=[])
    logger.info("Initialized validation provider with %s tools",
                len(tools_dict))

    # calculate iteration budget for synthesis
    max_iterations = get_validate_max_iterations(total_hypotheses)
    logger.info("Validation synthesis budget: %s iterations", max_iterations)

    # batch hypotheses
    batches = [
        hypotheses_with_analyses[i:i + VALIDATION_SYNTHESIS_BATCH_SIZE]
        for i in range(0, total_hypotheses, VALIDATION_SYNTHESIS_BATCH_SIZE)
    ]
    logger.info("Split into %s batches of up to %s hypotheses", len(batches),
                VALIDATION_SYNTHESIS_BATCH_SIZE)

    # -------------------------------------------------------------------------
    # helpers
    # -------------------------------------------------------------------------

    def _extract_response_json(raw: str) -> str:
        """Strip markdown code fences and whitespace from an LLM response."""
        text = raw.strip()
        lower = text.lower()
        if "```json" in lower:
            start = lower.find("```json") + 7
            end = text.find("```", start)
            text = text[start:] if end == -1 else text[start:end]
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            text = text[start:] if end == -1 else text[start:end]
        return text.strip().strip("\n").strip()

    async def _call_synthesis(
        batch: List[Dict[str, Any]],
        batch_label: str,
        already_validated_texts: Optional[List[str]],
    ) -> List[Dict[str, Any]]:
        """Run one synthesis call and return the parsed hypotheses list."""
        batch_size = len(batch)
        logger.info("Processing synthesis batch %s (%s hypotheses)",
                    batch_label, batch_size)

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

        from co_scientist.prompts import save_prompt_to_disk  # pylint: disable=import-outside-toplevel
        save_prompt_to_disk(
            run_id=state.get("run_id", "unknown"),
            prompt_name=f"validation_synthesis_batch_{batch_label}",
            content=synthesis_prompt,
            metadata={
                "batch_label":
                    batch_label,
                "batch_size":
                    batch_size,
                "max_iterations":
                    max_iterations,
                "retry_context_count":
                    len(already_validated_texts)
                    if already_validated_texts else 0,
            },
        )

        synthesis_max_tokens = min(EXTENDED_MAX_TOKENS + (batch_size * 2500),
                                   20000)
        logger.debug("Batch %s token budget: %s for %s hypotheses", batch_label,
                     synthesis_max_tokens, batch_size)

        tool_call_counts: Dict[str, int] = {}

        async def tracked_executor(tool_call: Any) -> Dict[str, Any]:
            name = tool_call.function.name
            tool_call_counts[name] = tool_call_counts.get(name, 0) + 1
            logger.info("Validation batch %s: %s call #%s", batch_label, name,
                        tool_call_counts[name])
            return await provider.execute_tool_call(tool_call)

        final_response, _ = await call_llm_with_tools(
            prompt=synthesis_prompt,
            model_name=state["model_name"],
            tools=openai_tools,
            tool_executor=tracked_executor,
            max_tokens=synthesis_max_tokens,
            temperature=HIGH_TEMPERATURE,
            max_iterations=max_iterations,
        )

        total_calls = sum(tool_call_counts.values())
        if total_calls > 0:
            calls_summary = ", ".join(
                f"{n}={c}" for n, c in tool_call_counts.items())
            logger.info("Batch %s: %s tool calls (%s)", batch_label,
                        total_calls, calls_summary)

        response_text = _extract_response_json(final_response)
        response_data, was_repaired = attempt_json_repair(
            response_text, allow_major_repairs=True)

        if response_data is None:
            logger.error("Failed to parse batch %s JSON response", batch_label)
            logger.error("Response: %s...", final_response[:500])
            raise ResponseParseError(
                "Validation synthesis returned invalid JSON"
                f" (batch {batch_label})")

        if was_repaired:
            logger.warning("Batch %s JSON required repairs", batch_label)

        result: List[Dict[str, Any]] = response_data.get("hypotheses", [])
        logger.debug("Batch %s synthesis returned %s hypotheses", batch_label,
                     len(result))
        return result

    # -------------------------------------------------------------------------
    # execute all batches in parallel; capture failures without aborting
    # -------------------------------------------------------------------------

    raw_results = await asyncio.gather(
        *[
            _call_synthesis(batch, str(i + 1), None)
            for i, batch in enumerate(batches)
        ],
        return_exceptions=True,
    )

    all_validated_hypotheses: List[Dict[str, Any]] = []
    failed_batches: List[Tuple[int, List[Dict[str, Any]]]] = []

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

    # -------------------------------------------------------------------------
    # retry failed batches one hypothesis at a time, accumulating context
    # -------------------------------------------------------------------------

    if failed_batches:
        # seed context with texts from successful batches
        accumulated_texts: List[str] = [
            h.get("hypothesis", "")
            for h in all_validated_hypotheses
            if h.get("hypothesis")
        ]

        for batch_idx, failed_batch in failed_batches:
            for hyp_idx, hyp_data in enumerate(failed_batch):
                label = f"{batch_idx + 1}_retry_{hyp_idx + 1}"
                context = accumulated_texts if accumulated_texts else None
                try:
                    single_result = await _call_synthesis([hyp_data], label,
                                                          context)
                    all_validated_hypotheses.extend(single_result)
                    # accumulate for subsequent retries within this loop
                    for h in single_result:
                        text = h.get("hypothesis", "")
                        if text:
                            accumulated_texts.append(text)
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.error(
                        "Individual retry failed for batch %s,"
                        " hypothesis %s: %s", batch_idx + 1, hyp_idx + 1, e)

    logger.info("Combined %s validated hypotheses from %s batches",
                len(all_validated_hypotheses), len(batches))

    # create Hypothesis objects from synthesis
    # output order matches hypotheses_with_analyses order (batched sequentially)
    ref_sources = reference_index.sources if reference_index else {}
    hypotheses = []
    for i, hyp_data in enumerate(all_validated_hypotheses):

        hypothesis_text = hyp_data.get("hypothesis") or hyp_data.get("text", "")
        explanation = hyp_data.get("explanation")
        literature_grounding = hyp_data.get("literature_grounding")
        experiment = hyp_data.get("experiment")

        citation_map = resolve_citation_keys(literature_grounding, ref_sources)

        hypothesis = Hypothesis(
            text=hypothesis_text,
            explanation=explanation,
            literature_grounding=literature_grounding,
            experiment=experiment,
            novelty_validation=hyp_data.get("novelty_validation"),
            score=0.0,
            elo_rating=INITIAL_ELO_RATING,
            generation_method=GenerationMethod.LITERATURE_TOOLS,
            citation_map=citation_map,
        )
        hypotheses.append(hypothesis)

    logger.info("Generated %s validated hypotheses", len(hypotheses))
    return hypotheses
