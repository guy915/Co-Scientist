"""Phase 2.6: literature review context enrichment.

Fetches background context (e.g. knowledge-graph causal edges) for entities
extracted from the research goal, and formats those sources as a labeled
``[C*]`` section appended to the synthesis. Entirely YAML-driven: a no-op
unless the workflow lists ``context_enrichment_tools``.
"""

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from co_scientist.agents.generation.literature_review.helpers import (
    SearchConfig,
)
from co_scientist.mcp_client import MCPToolClient
from co_scientist.nodes.reflection_helpers import extract_entity_names
from co_scientist.state import WorkflowState

if TYPE_CHECKING:
    from co_scientist.config import ToolConfig, ToolRegistry, WorkflowConfig

logger = logging.getLogger(__name__)

# Max chars injected into synthesis prompt from all enrichment tools combined
_CONTEXT_ENRICHMENT_MAX_CHARS = 1500
# Max results requested per entity per tool call
_CONTEXT_ENRICHMENT_RESULTS_PER_ENTITY = 4
# Sentinel returned by _try_json_decode when raw isn't valid JSON, so a
# successfully-decoded ``None``/``null`` payload isn't mistaken for failure.
_NOT_JSON = object()


async def _call_enrichment_tool_for_entity(
    tool_name: str,
    mapped_params: dict[str, Any],
    mcp_client: MCPToolClient,
) -> Any:
    """Call one enrichment tool for one entity; returns raw result or None."""
    try:
        return await mcp_client.call_tool(tool_name, **mapped_params)
    except Exception as e:
        # Enrichment is best-effort background context, not a required
        # input, so a failed call for one entity/tool just yields no
        # evidence for it rather than aborting the whole node.
        logger.debug("context enrichment call failed (%s): %s", tool_name, e)
        return None


def _format_generic_items(
    items: list[Any],
) -> tuple[str, list[dict[str, Any]]]:
    """Format a generic list of result items as (display_text, structured).

    Shared by the "results"-wrapped dict shape and the bare-list shape in
    `_parse_enrichment_result`: both just cap the list, stringify each item
    for display, and carry the raw payload through (when it's a dict).
    """
    capped = items[:_CONTEXT_ENRICHMENT_RESULTS_PER_ENTITY]
    text = "\n".join(str(item)[:120] for item in capped)
    structured = [
        {
            "display": str(item)[:120],
            "data": item if isinstance(item, dict) else {},
        }
        for item in capped
    ]
    return text, structured


def _format_one_indra_statement(
    s: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    """Format one INDRA subject/object/relation statement as a causal edge.

    INDRA statements encode subject/object/relation triples with a belief
    score; format as a readable causal edge for the synthesis prompt.
    Returns None when the statement lacks either endpoint name.
    """
    subj = (s.get("subj") or {}).get("name", "")
    obj = (s.get("obj") or {}).get("name", "")
    if not (subj and obj):
        return None
    rel = s.get("type", "")
    belief = s.get("belief", 0)
    display = f"{subj} \u2192 {obj} [{rel}] (belief: {belief:.2f})"
    return display, {"display": f"INDRA: {display}", "data": s}


def _format_indra_statements(
    stmts: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Format INDRA subject/object/relation statements as causal-edge text."""
    lines = []
    items = []
    for s in stmts[:_CONTEXT_ENRICHMENT_RESULTS_PER_ENTITY]:
        formatted = _format_one_indra_statement(s)
        if not formatted:
            continue
        display, item = formatted
        lines.append(f"- {display}")
        items.append(item)
    return "\n".join(lines), items


def _try_json_decode(raw: str) -> Any:
    """Decode `raw` as JSON, or return the _NOT_JSON sentinel on failure."""
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return _NOT_JSON


def _wrap_as_text_result(value: Any) -> tuple[str, list[dict[str, Any]]]:
    """Truncate `value` to display text and wrap it as a single display item.

    Used for enrichment payloads that don't match any known shape (a plain
    string that isn't JSON, or a scalar value): falls back to a single
    stringified display item, or an empty result for falsy values.
    """
    text = str(value)[:300] if value else ""
    return text, [{"display": text, "data": {}}] if text else []


def _format_dict_result(
    data: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    """Format a dict-shaped enrichment result.

    Handles the INDRA "statements" shape and the generic "results" list
    shape, falling back to stringifying the whole dict (truncated) as a
    single display item.
    """
    # INDRA-shaped response: has a "statements" key (even when empty). Never
    # fall through to the raw-dict repr for this format.
    if "statements" in data:
        stmts = data.get("statements", [])
        if not stmts:
            return "", []  # entity had no results - skip cleanly
        return _format_indra_statements(stmts)

    # Generic "results" list shape (non-INDRA tools that wrap their payload
    # in a results key).
    results = data.get("results", [])
    if results:
        return _format_generic_items(results)

    text = str(data)[:300]
    return text, [{"display": text, "data": data}] if text else []


def _parse_enrichment_result(raw: Any) -> tuple[str, list[dict[str, Any]]]:
    """Extract formatted text AND structured items from an enrichment result.

    Returns (display_text, structured_items) where structured_items is a
    list of dicts suitable for storage in context_enrichment_sources.
    """
    data = raw
    if isinstance(raw, str):
        data = _try_json_decode(raw)
        if data is _NOT_JSON:
            # Not JSON: treat the raw string itself as the display text.
            return _wrap_as_text_result(raw)

    if isinstance(data, dict):
        return _format_dict_result(data)

    if isinstance(data, list):
        # Generic bare-list response shape.
        return _format_generic_items(data)

    # Scalar (or falsy) result: stringify directly.
    return _wrap_as_text_result(data)


async def _call_enrichment_tool_for_entities(
    tool_config: Any,
    entities: list[str],
    mcp_client: MCPToolClient,
) -> tuple[str, list[dict[str, Any]]]:
    """Call one enrichment tool for all entities in parallel.

    Returns (formatted_text, structured_items) where structured_items carry
    the tool_id so they can be stored in context_enrichment_sources.
    """
    tool_name = tool_config.mcp_tool_name
    tool_id = getattr(tool_config, "tool_id", tool_name)
    canonical = {
        "entity_name": "",
        "limit": _CONTEXT_ENRICHMENT_RESULTS_PER_ENTITY,
    }

    async def _query_one(entity: str) -> tuple[str, list[dict[str, Any]]]:
        # map_parameters translates the canonical entity_name/limit pair
        # into this tool's own YAML-configured parameter names.
        params = tool_config.map_parameters(
            {**canonical, "entity_name": entity}
        )
        raw = await _call_enrichment_tool_for_entity(
            tool_name, params, mcp_client
        )
        if raw is None:
            return "", []
        text, items = _parse_enrichment_result(raw)
        # Tag each item with entity and tool_id for citation building
        for item in items:
            item.setdefault("tool_id", tool_id)
            item.setdefault("entity", entity)
        return text, items

    # One tool call per entity, all in parallel.
    per_entity = await asyncio.gather(*[_query_one(e) for e in entities])

    text_lines: list[str] = []
    all_items: list[dict[str, Any]] = []
    for entity, (text, items) in zip(entities, per_entity, strict=True):
        if text:
            text_lines.append(f"[{entity}]\n{text}")
        all_items.extend(items)

    return "\n\n".join(text_lines), all_items


def _resolve_enrichment_tool_configs(
    workflow: "WorkflowConfig",
    tool_registry: "ToolRegistry",
    mcp_client: MCPToolClient,
) -> list["ToolConfig"]:
    """Resolve the enabled, available context-enrichment tool configs.

    Stashes the originating YAML tool_id onto each resolved config (via
    ``_yaml_tool_id``) for downstream citation building.
    """
    tool_configs = []
    for tool_id in workflow.context_enrichment_tools:
        tc = tool_registry.get_tool(tool_id)
        if tc and tc.enabled and mcp_client.has_tool(tc.mcp_tool_name):
            tc._yaml_tool_id = tool_id
            tool_configs.append(tc)
        else:
            logger.debug(
                "context enrichment: tool '%s' unavailable or disabled", tool_id
            )
    return tool_configs


def _aggregate_enrichment_results(
    tool_configs: list["ToolConfig"],
    tool_results: list[Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Aggregate per-tool enrichment results into display sections and items.

    ``tool_results`` may contain exceptions (from
    ``asyncio.gather(..., return_exceptions=True)``); those tools are
    skipped and logged rather than aborting aggregation for the rest.
    """
    sections: list[str] = []
    all_structured: list[dict[str, Any]] = []
    for tc, result in zip(tool_configs, tool_results, strict=True):
        if isinstance(result, BaseException):
            logger.debug(
                "context enrichment: %s raised %s", tc.mcp_tool_name, result
            )
            continue
        text, items = result
        if text:
            sections.append(f"**{tc.display_name}**\n{text}")
        # Tag items with the yaml tool_id
        yaml_tool_id = getattr(tc, "_yaml_tool_id", tc.mcp_tool_name)
        for item in items:
            item["tool_id"] = yaml_tool_id
        all_structured.extend(items)
    return sections, all_structured


def _resolve_enrichment_context(
    state: WorkflowState,
    config: SearchConfig,
) -> "tuple[WorkflowConfig, ToolRegistry, list[str]] | None":
    """Resolve the workflow, tool registry, and entities needed to enrich.

    Returns None if context_enrichment_tools isn't configured for this
    workflow (keeping lit review unchanged for domains that don't use it),
    or if no entities could be extracted from the research goal - either
    case means Phase 2.6 has nothing to do.
    """
    workflow = config.workflow
    if not workflow or not workflow.context_enrichment_tools:
        return None

    tool_registry = config.tool_registry
    if not tool_registry:
        return None

    # Entities (e.g. gene/protein names) are pulled from the research goal
    # text itself, not from any paper content, since enrichment runs
    # independently of/in parallel with paper search and content fetching.
    entities = extract_entity_names(state["research_goal"], max_entities=3)
    if not entities:
        logger.debug(
            "context enrichment: no entities extracted from research goal"
        )
        return None

    return workflow, tool_registry, entities


async def _run_enrichment_tools(
    entities: list[str],
    tool_configs: list["ToolConfig"],
    mcp_client: MCPToolClient,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Query every tool_config for every entity in parallel, and aggregate.

    return_exceptions=True so one tool's failure doesn't drop results from
    the others.
    """
    tool_tasks = [
        _call_enrichment_tool_for_entities(tc, entities, mcp_client)
        for tc in tool_configs
    ]
    tool_results = await asyncio.gather(*tool_tasks, return_exceptions=True)
    return _aggregate_enrichment_results(tool_configs, tool_results)


def _cap_enrichment_text(combined: str) -> str:
    """Truncate combined enrichment text to the synthesis prompt budget.

    Enrichment content can be large across several tools/entities; capping
    it keeps it from crowding out the paper-analysis content in the prompt
    budget.
    """
    if len(combined) > _CONTEXT_ENRICHMENT_MAX_CHARS:
        return combined[:_CONTEXT_ENRICHMENT_MAX_CHARS] + "\n[...truncated]"
    return combined


async def _phase2_6_fetch_context_enrichment(
    state: WorkflowState,
    config: SearchConfig,
    mcp_client: MCPToolClient,
) -> tuple[str, list[dict[str, Any]]]:
    """Phase 2.6: fetch background context from knowledge-graph tools.

    Completely YAML-driven: only runs when the literature_review workflow
    lists tools under 'context_enrichment_tools'. Returns ("", []) when not
    configured, keeping lit review unchanged for other domains.

    Calls all configured tools x all extracted entities in parallel.
    Output text is capped to avoid bloating the synthesis prompt.

    Returns:
        (formatted_text_for_synthesis, structured_items_for_citation_index)
    """
    empty: tuple[str, list[dict[str, Any]]] = ("", [])

    resolved = _resolve_enrichment_context(state, config)
    if resolved is None:
        return empty
    workflow, tool_registry, entities = resolved

    logger.info(
        "Phase 2.6: fetching context enrichment for entities %s via %s tool(s)",
        entities,
        len(workflow.context_enrichment_tools),
    )

    tool_configs = _resolve_enrichment_tool_configs(
        workflow, tool_registry, mcp_client
    )
    if not tool_configs:
        return empty

    sections, all_structured = await _run_enrichment_tools(
        entities, tool_configs, mcp_client
    )
    if not sections and not all_structured:
        return empty

    combined = _cap_enrichment_text("\n\n".join(sections))

    logger.info(
        "Phase 2.6 complete: %s tool(s), %s structured items (%s chars)",
        len(sections),
        len(all_structured),
        len(combined),
    )
    return combined, all_structured


def _format_kg_section_with_keys(
    context_enrichment_sources: list[dict[str, Any]],
    paper_count: int,
) -> str:
    """Format context enrichment sources as a labeled [C*] section.

    Keys start at C{paper_count + 1}, exactly matching what
    build_reference_index will assign at generation time (papers fill
    C1..Cn first, then these entries follow). This lets the generation LLM
    see the same [C*] handles in articles_with_reasoning that appear in its
    Citation Reference List.
    """
    if not context_enrichment_sources:
        return ""
    lines = []
    for i, item in enumerate(context_enrichment_sources):
        # 1-indexed key offset by paper_count so these keys pick up exactly
        # where the paper citations ([C1]..[C{paper_count}]) leave off.
        key = f"C{paper_count + i + 1}"
        display = item.get("display", "External source")
        lines.append(f"[{key}] {display}")
    return "\n\n---\n\n## Knowledge Graph Evidence\n\n" + "\n\n".join(lines)
