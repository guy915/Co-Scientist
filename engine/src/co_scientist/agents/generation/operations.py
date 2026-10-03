"""Generation planning and finalization shared by graph and durable callers."""

import asyncio
import logging
from collections import Counter
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any

from co_scientist.agents.generation.citations import (
    ReferenceIndex,
    build_reference_index,
)
from co_scientist.agents.meta_review.research_overview import (
    format_interim_overview,
)
from co_scientist.config.schema import EnrichmentConfig, ToolConfig
from co_scientist.constants import (
    LITERATURE_REVIEW_FAILED,
    MAX_CONCURRENT_LLM_CALLS,
    PROGRESS_GENERATE_COMPLETE,
    PROGRESS_GENERATE_START,
)
from co_scientist.exceptions import GenerationError
from co_scientist.mcp_client import get_mcp_client
from co_scientist.models import GenerationMethod, Hypothesis
from co_scientist.progress import emit_progress
from co_scientist.state import AppendHypotheses, WorkflowState
from co_scientist.tools.response_parser import parse_mcp_result

logger = logging.getLogger(__name__)


GENERATION_STRATEGY_LABELS = frozenset(
    {"dev_isolation", "lit_and_tools", "lit_only", "no_lit"}
)
TOOLS_REQUIRING_STRATEGIES = frozenset({"dev_isolation", "lit_and_tools"})


@dataclass
class GenerationCounts:
    """Hypothesis allocation, including serialized durable-run mode flags."""

    tools_count: int
    debate_with_lit_count: int
    debate_only_count: int
    assumptions_count: int = 0
    is_dev_isolation: bool = False
    is_degraded_mode: bool = False

    @property
    def strategy_counts(self) -> dict[str, int]:
        """Hypothesis counts in canonical strategy order, including zeroes."""
        return {
            "tools": self.tools_count,
            "debate_lit": self.debate_with_lit_count,
            "debate_only": self.debate_only_count,
            "assumptions": self.assumptions_count,
        }


def _check_literature_availability(
    articles_with_reasoning: str | None, mcp_available: bool
) -> bool:
    """Require successful literature review and live MCP access."""
    return (
        articles_with_reasoning is not None
        and articles_with_reasoning != LITERATURE_REVIEW_FAILED
        and mcp_available
    )


def _forced_generation_strategy(state: WorkflowState) -> str | None:
    """Use a recognized ablation override, otherwise derive the strategy."""
    forced = state.get("generation_strategy")
    if isinstance(forced, str) and forced in GENERATION_STRATEGY_LABELS:
        return forced
    return None


def _classify_generation_strategy(
    state: WorkflowState, has_literature: bool, enable_tool_calling: bool
) -> str:
    """Resolve isolation, literature with tools, literature, or latent-only."""
    if state.get("dev_test_lit_tools_isolation", False):
        return "dev_isolation"
    if has_literature:
        return "lit_and_tools" if enable_tool_calling else "lit_only"
    return "no_lit"


def _determine_generation_counts(
    state: WorkflowState,
    total_count: int,
    has_literature: bool,
    enable_tool_calling: bool,
) -> GenerationCounts:
    """Reserve assumptions for batches of four, then allocate the remainder."""
    strategy = _forced_generation_strategy(
        state
    ) or _classify_generation_strategy(
        state, has_literature, enable_tool_calling
    )
    if strategy == "dev_isolation":
        return GenerationCounts(total_count, 0, 0, is_dev_isolation=True)

    assumptions = total_count // 4 if total_count >= 4 else 0
    remainder = total_count - assumptions
    tools = max(1, remainder // 2) if strategy == "lit_and_tools" else 0
    return GenerationCounts(
        tools_count=tools,
        debate_with_lit_count=(
            remainder - tools
            if strategy in {"lit_and_tools", "lit_only"}
            else 0
        ),
        debate_only_count=remainder if strategy == "no_lit" else 0,
        assumptions_count=assumptions,
        is_degraded_mode=strategy == "no_lit",
    )


async def _report_generation_start(
    state: WorkflowState, counts: GenerationCounts, total_count: int
) -> None:
    """Log and emit the same resolved allocation once."""
    extra: dict[str, Any] = {}
    if counts.is_dev_isolation:
        logger.info(
            "Dev isolation mode: allocating all hypotheses"
            " to lit tools generation (no debate)"
        )
        message = (
            f"Generating {total_count} hypotheses with lit"
            " tools only (dev isolation mode)..."
        )
        extra = {"dev_isolation_mode": True}
    elif counts.debate_with_lit_count > 0:
        message = _report_literature_start(counts, total_count)
    elif counts.is_degraded_mode:
        logger.warning(
            "No literature review tools available - generating"
            " hypotheses from model latent knowledge only"
        )
        message = (
            f"Generating {counts.debate_only_count} hypotheses"
            " without literature review..."
        )
        extra = {"literature_review_available": False, "degraded_mode": True}
    else:
        # A one-hypothesis lit-and-tools batch has historically emitted
        # no start event; keep that lifecycle contract.
        return
    await emit_progress(
        state, "generation_start", message, PROGRESS_GENERATE_START, **extra
    )


def _report_literature_start(counts: GenerationCounts, total_count: int) -> str:
    """Log the literature-aware mix and return its progress message."""
    if counts.tools_count > 0:
        logger.info(
            "Condition (a): Generating %s hypotheses with literature review "
            "(%s tool-based + %s debate-with-literature)",
            total_count,
            counts.tools_count,
            counts.debate_with_lit_count,
        )
        return (
            f"Generating {total_count} hypotheses"
            f" ({counts.tools_count} tool-based"
            f" + {counts.debate_with_lit_count} debate-with-literature)..."
        )
    logger.info(
        "Condition (c): Generating %s hypotheses with debate-with-literature",
        total_count,
    )
    return f"Generating {total_count} hypotheses with debate-with-literature..."


@dataclass(frozen=True)
class _ResolvedEnrichment:
    """One enrichment config resolved against the tool registry.

    Attributes:
        enrichment: The enrichment config (input field, tool, result shape).
        tool_config: The resolved tool config for enrichment.tool.
        output_key: Key under which results are stored on hyp.enrichments.
    """

    enrichment: EnrichmentConfig
    tool_config: ToolConfig
    output_key: str


def _extract_enrichment_payload(
    parsed: Any, enrichment: EnrichmentConfig
) -> Any:
    """Extract the nested results array from a parsed enrichment result.

    E.g. pulls out the "results" array for an NvdSearchResponse-shaped
    result; returns parsed unchanged when no results_path is configured or
    parsed is not a dict.
    """
    if enrichment.results_path and isinstance(parsed, dict):
        return parsed.get(enrichment.results_path, parsed)
    return parsed


async def _call_enrichment_tool(
    hyp: Hypothesis,
    enrichment: EnrichmentConfig,
    tool_config: ToolConfig,
    mcp_client: Any,
    semaphore: asyncio.Semaphore,
) -> Any:
    """Call one enrichment tool for one hypothesis and return its payload.

    input_field selects which hypothesis attribute to query with (e.g. its
    explanation instead of its text); falls back to text.
    """
    input_value = getattr(hyp, enrichment.input_field, hyp.text)
    async with semaphore:
        result = await mcp_client.call_tool(
            tool_config.mcp_tool_name,
            topic=input_value,
            max_results=enrichment.max_results,
        )
    parsed = parse_mcp_result(result)
    return _extract_enrichment_payload(parsed, enrichment)


async def _enrich_one_hypothesis(
    hyp: Hypothesis,
    resolved: _ResolvedEnrichment,
    mcp_client: Any,
    semaphore: asyncio.Semaphore,
) -> None:
    """Run one enrichment tool call for one hypothesis, best-effort.

    Args:
        hyp: the hypothesis to enrich; the result is stored on
            hyp.enrichments[resolved.output_key].
        resolved: the enrichment config with its resolved tool config and
            output key.
        mcp_client: MCP client used to call the enrichment tool.
        semaphore: shared concurrency limiter across all enrichment calls.
    """
    output_key = resolved.output_key
    try:
        hyp.enrichments[output_key] = await _call_enrichment_tool(
            hyp,
            resolved.enrichment,
            resolved.tool_config,
            mcp_client,
            semaphore,
        )
    except Exception as e:
        # Enrichment is supplementary, not load-bearing: a failure here must
        # not fail hypothesis generation, so it is recorded on the
        # hypothesis instead of being raised.
        logger.warning(
            "enrichment '%s' failed for hypothesis: %s", output_key, e
        )
        hyp.enrichments[output_key] = {"error": str(e)}


async def _run_one_enrichment(
    enrichment: EnrichmentConfig,
    tool_registry: Any,
    hypotheses: list[Hypothesis],
    mcp_client: Any,
    semaphore: asyncio.Semaphore,
) -> None:
    """Resolve one enrichment config's tool and fan out calls per hypothesis.

    No-op (with a warning) when the config's tool is not found in the
    registry.
    """
    tool_config = tool_registry.get_tool(enrichment.tool)
    if not tool_config:
        logger.warning(
            "enrichment tool '%s' not found in registry", enrichment.tool
        )
        return

    resolved = _ResolvedEnrichment(
        enrichment=enrichment,
        tool_config=tool_config,
        output_key=enrichment.output_key or enrichment.tool,
    )
    logger.info(
        "running enrichment '%s' via %s for %s hypotheses",
        resolved.output_key,
        tool_config.mcp_tool_name,
        len(hypotheses),
    )

    # Fan out one call per hypothesis for this enrichment config; the
    # semaphore inside _enrich_one_hypothesis bounds actual concurrency.
    await asyncio.gather(
        *(
            _enrich_one_hypothesis(hyp, resolved, mcp_client, semaphore)
            for hyp in hypotheses
        )
    )


async def _enrich_hypotheses(
    hypotheses: list[Hypothesis],
    state: WorkflowState,
) -> None:
    """Run post-generation enrichment tools and attach results to hypotheses.

    Reads enrichment configs from the tool registry. For each config, calls
    the specified tool with each hypothesis's input_field value and stores
    the result in hypothesis.enrichments[output_key].
    """
    # No-op unless the domain's tool config declares enrichment tools (e.g.
    # a CVE lookup for a cyber domain) - most domains have none configured.
    tool_registry = state.get("tool_registry")
    if not tool_registry:
        return

    enrichment_configs = tool_registry.get_enrichment_configs()
    if not enrichment_configs:
        return

    mcp_client = await get_mcp_client(tool_registry=tool_registry)
    # Reuse the same concurrency cap as LLM calls even though these are tool
    # calls, not LLM calls - it is a reasonable shared limit on outstanding
    # MCP requests and avoids adding a second constant for the same purpose.
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)

    # Enrichment configs are independent of each other, so they overlap
    # rather than run in sequence: awaiting each config's whole per-hypothesis
    # fan-out before starting the next made wall-clock the sum over configs
    # while the shared semaphore -- the thing that actually bounds MCP
    # concurrency -- sat mostly idle. Every shipped domain declares one
    # enrichment today, so this only matters for the next one that adds a
    # second.
    await asyncio.gather(
        *(
            _run_one_enrichment(
                enrichment, tool_registry, hypotheses, mcp_client, semaphore
            )
            for enrichment in enrichment_configs
        )
    )


@dataclass
class GenerationResults:
    """Encapsulates results from parallel generation execution."""

    tools_hypotheses: list[Hypothesis]
    debate_with_lit_hypotheses: list[Hypothesis]
    debate_only_hypotheses: list[Hypothesis]
    # One entry per debate run (both debate_with_lit and debate_only feed
    # this); tool-based generation has no transcript equivalent.
    debate_transcripts: list[dict[str, Any]]
    # Hypotheses from the iterative-assumptions technique (SSR §4); a plain
    # list like the tools path, with no transcript.
    assumptions_hypotheses: list[Hypothesis] = field(default_factory=list)
    # Real LLM calls spent across every strategy that ran this cycle
    # (finding L3 -- generation previously reported none at all).
    llm_call_count: int = 0

    @property
    def all_hypotheses(self) -> list[Hypothesis]:
        """All generated hypotheses across every strategy, in method order."""
        return (
            self.tools_hypotheses
            + self.debate_with_lit_hypotheses
            + self.debate_only_hypotheses
            + self.assumptions_hypotheses
        )


def _unpack_generation_results(
    tasks: list[tuple[str, Coroutine[Any, Any, Any]]],
    results: list[Any],
) -> GenerationResults:
    """Collect ordered strategy results and real provider-call counts."""
    buckets: dict[str, list[Hypothesis]] = {
        "tools": [],
        "debate_lit": [],
        "debate_only": [],
        "assumptions": [],
    }
    debate_transcripts: list[dict[str, Any]] = []
    llm_call_count = 0
    for (kind, _), result in zip(tasks, results, strict=True):
        if kind in ("debate_lit", "debate_only"):
            hypotheses, transcripts, llm_calls = result
            debate_transcripts.extend(transcripts)
        else:
            hypotheses, llm_calls = result
        buckets[kind] = hypotheses
        llm_call_count += int(llm_calls)
    return GenerationResults(
        tools_hypotheses=buckets["tools"],
        debate_with_lit_hypotheses=buckets["debate_lit"],
        debate_only_hypotheses=buckets["debate_only"],
        debate_transcripts=debate_transcripts,
        assumptions_hypotheses=buckets["assumptions"],
        llm_call_count=llm_call_count,
    )


def _apply_degraded_mode_fallback(hypotheses: list[Hypothesis]) -> None:
    """Sets a fallback literature_grounding message in degraded mode.

    Applies to every hypothesis generated without a literature review.
    """
    for hyp in hypotheses:
        # Always overwrite in non-lit-mcp mode to prevent hallucinated
        # citations: even if the model produced its own literature_grounding
        # text (it was told not to have literature), replace it so the
        # user-facing field never implies grounding that does not exist.
        hyp.literature_grounding = (
            "No literature review available. This hypothesis is based"
            " on the model's latent knowledge and has not been"
            " validated against current research literature."
            " Novelty and scientific validity should be independently"
            " verified."
        )


def _log_bucket_methods(label: str, hypotheses: list[Hypothesis]) -> None:
    """Log the generation_method of every hypothesis in one bucket.

    No-op when the bucket is empty.

    Args:
        label: name of the bucket, used as the log line prefix.
        hypotheses: hypotheses in this bucket.
    """
    if not hypotheses:
        return
    logger.debug(
        "%s generation_methods: %s",
        label,
        [
            h.generation_method.value if h.generation_method else None
            for h in hypotheses
        ],
    )


def _log_generation_summary(results: GenerationResults) -> None:
    """Log summary of generated hypotheses.

    The breakdown covers every bucket that feeds all_hypotheses. Assumptions
    was left out of it while still being counted in the total, so any run
    allocating an assumptions slice (total_count >= 4) logged parts that did
    not sum to the total it printed.
    """
    total = len(results.all_hypotheses)
    logger.info(
        "Generated %s total hypotheses (%s tool-based,"
        " %s debate-with-lit, %s debate-only, %s assumptions)",
        total,
        len(results.tools_hypotheses),
        len(results.debate_with_lit_hypotheses),
        len(results.debate_only_hypotheses),
        len(results.assumptions_hypotheses),
    )

    _log_bucket_methods("tool-based", results.tools_hypotheses)
    _log_bucket_methods("debate-with-Lit", results.debate_with_lit_hypotheses)
    _log_bucket_methods("debate-only", results.debate_only_hypotheses)
    _log_bucket_methods("assumptions", results.assumptions_hypotheses)


async def _emit_complete_progress(
    state: WorkflowState, results: GenerationResults, counts: GenerationCounts
) -> str:
    """Emit progress callback for generation complete.

    Returns:
        The human-readable generation summary message that was emitted.
    """
    parts = [
        f"{len(hypotheses)} {label}"
        for count, hypotheses, label in (
            (counts.tools_count, results.tools_hypotheses, "tool-based"),
            (
                counts.debate_with_lit_count,
                results.debate_with_lit_hypotheses,
                "debate-with-literature",
            ),
            (
                counts.debate_only_count,
                results.debate_only_hypotheses,
                "debate-only",
            ),
            (
                counts.assumptions_count,
                results.assumptions_hypotheses,
                "assumptions",
            ),
        )
        if count > 0
    ]
    all_hypotheses = results.all_hypotheses

    message = f"Generated {len(all_hypotheses)} hypotheses ({', '.join(parts)})"

    await emit_progress(
        state,
        "generation_complete",
        message,
        PROGRESS_GENERATE_COMPLETE,
        hypotheses_count=len(all_hypotheses),
    )
    return message


@dataclass(frozen=True)
class GenerationPlan:
    """Resolved allocation and shared inputs for one generation cycle.

    Attributes:
        counts: Hypothesis allocation per method, including mode flags.
        reference_index: Shared citation keys across the enabled strategies.
        literature: Literature context, with any interim overview prepended.
            Debate-only callers must explicitly omit this context.
    """

    counts: GenerationCounts
    reference_index: ReferenceIndex
    literature: str | None


def _log_reference_index_summary(reference_index: ReferenceIndex) -> None:
    """Log a paper/KG-source breakdown of a non-empty reference index."""
    if reference_index.is_empty():
        return
    # Keys are uniformly "C<n>"; the paper/KG split lives in each source's
    # "type" field (see build_reference_index).
    counts = Counter(s.get("type") for s in reference_index.sources.values())
    logger.info(
        "Built reference index: %s paper(s), %s KG source(s)",
        counts["paper"],
        counts["knowledge_graph"],
    )


async def prepare_generation(
    state: WorkflowState,
) -> GenerationPlan:
    """Validate preconditions and resolve strategy, counts, and references.

    Also logs the resolved strategy and emits the generation-start progress
    callback, since both key off the counts computed here.

    Returns:
        The allocation, shared citation namespace, and strategy context.

    Raises:
        GenerationError: if supervisor_guidance is missing from state.
    """
    if not state.get("supervisor_guidance"):
        raise GenerationError(
            "No supervisor_guidance in state for node=generation"
        )
    articles_with_reasoning = state.get("articles_with_reasoning")
    total_count = state["initial_hypotheses_count"]
    has_literature = _check_literature_availability(
        articles_with_reasoning, bool(state.get("mcp_available", False))
    )
    counts = _determine_generation_counts(
        state,
        total_count,
        has_literature,
        bool(state.get("enable_tool_calling_generation", False)),
    )

    # Shared [C*] citation-key namespace for every strategy below.
    reference_index = build_reference_index(
        articles=state.get("articles"),
        context_enrichment_sources=state.get("context_enrichment_sources"),
    )
    _log_reference_index_summary(reference_index)

    await _report_generation_start(state, counts, total_count)

    return GenerationPlan(
        counts=counts,
        reference_index=reference_index,
        literature=_with_interim_overview(state, articles_with_reasoning),
    )


def _with_interim_overview(
    state: WorkflowState, articles_with_reasoning: str | None
) -> str | None:
    """Prepend interim guidance without treating it as retrieved literature.

    Availability is checked before this step. Debate-only calls explicitly
    omit this context, so a run's own synthesis cannot imply grounding.
    """
    block = format_interim_overview(state)
    if not block:
        return articles_with_reasoning
    if not articles_with_reasoning:
        return block
    return f"{block}\n\n{articles_with_reasoning}"


def _stamp_generation_lineage(
    hypotheses: list[Hypothesis], creation_iteration: int
) -> None:
    """Stamp generation-0 lineage and research-expansion provenance in place.

    origin/generation keep their construction defaults (GENERATION, 0); the
    Generation agent produces roots, so parent_id stays None. Later
    research-expansion cycles reuse this node with a higher iteration, in
    which case the underlying generation method is preserved as provenance
    before the observable technique is stamped over it.

    Args:
        hypotheses: hypotheses to stamp, mutated in place.
        creation_iteration: workflow iteration that produced these
            hypotheses.
    """
    for hyp in hypotheses:
        hyp.creation_iteration = creation_iteration
        if creation_iteration > 0:
            if hyp.generation_method is not None:
                hyp.enrichments["base_generation_method"] = (
                    hyp.generation_method.value
                )
            hyp.generation_method = GenerationMethod.RESEARCH_EXPANSION


async def finalize_generation(
    state: WorkflowState,
    counts: GenerationCounts,
    results: GenerationResults,
) -> dict[str, Any]:
    """Apply the degraded-mode fallback, enrich, and build the result dict.

    Args:
        state: current workflow state
        counts: Per-strategy counts from preparation.
        results: Gathered strategy results.

    Returns:
        dict with hypotheses, debate_transcripts, hypothesis_count,
        llm_call_count, message.
    """
    # Only debate_only_hypotheses need the fallback message: tools_ and
    # debate_with_lit_hypotheses are only populated when has_literature was
    # true, so is_degraded_mode and those lists are mutually exclusive by
    # construction. Assumptions generation runs in the same no-literature
    # path, so its hypotheses need the same fallback grounding.
    if counts.is_degraded_mode:
        _apply_degraded_mode_fallback(results.debate_only_hypotheses)
        _apply_degraded_mode_fallback(results.assumptions_hypotheses)

    _log_generation_summary(results)
    message_content = await _emit_complete_progress(state, results, counts)

    all_hypotheses = results.all_hypotheses
    _stamp_generation_lineage(all_hypotheses, state.get("current_iteration", 0))

    # Run post-generation enrichments (e.g., NVD CVE lookup)
    await _enrich_hypotheses(all_hypotheses, state)

    # Append (not replace): a later generation cycle adds to the pool.
    return {
        "hypotheses": AppendHypotheses(all_hypotheses),
        "debate_transcripts": results.debate_transcripts,
        "hypothesis_count": len(all_hypotheses),
        "llm_call_count": results.llm_call_count,
        "message": message_content,
    }
