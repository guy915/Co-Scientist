"""Post-generation enrichment tool calls for the generation coordinator.

Reads enrichment configs from the tool registry and fans out one MCP tool
call per (enrichment config, hypothesis) pair, attaching results to each
hypothesis's enrichments dict. Enrichment is supplementary: failures are
recorded on the hypothesis, never raised.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from co_scientist.config.schema import EnrichmentConfig, ToolConfig
from co_scientist.constants import MAX_CONCURRENT_LLM_CALLS
from co_scientist.mcp_client import get_mcp_client
from co_scientist.models import Hypothesis
from co_scientist.state import WorkflowState
from co_scientist.tools.response_parser import parse_mcp_result

logger = logging.getLogger(__name__)


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

    for enrichment in enrichment_configs:
        await _run_one_enrichment(
            enrichment, tool_registry, hypotheses, mcp_client, semaphore
        )
