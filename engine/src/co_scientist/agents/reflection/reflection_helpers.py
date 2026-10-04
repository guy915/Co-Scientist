import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Any, NamedTuple, Optional, cast

from co_scientist.tools.response_parser import parse_mcp_result

logger = logging.getLogger(__name__)


# The hyphenated suffix excludes pathway notation such as RAGE-JAK2.
_HYPHENATED_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,5}-[0-9]{1,2}[A-Z]?)\b")
_STANDALONE_RE = re.compile(r"\b([A-Z][A-Z0-9]{2,5})\b")

# These ordinary words, abbreviations and broad families are not specific gene
# queries.
_STOP = frozenset(
    {
        "THE",
        "AND",
        "FOR",
        "WITH",
        "THIS",
        "THAT",
        "FROM",
        "INTO",
        "BUT",
        "NOT",
        "HAS",
        "CAN",
        "MAY",
        "WILL",
        "ARE",
        "WAS",
        "TWO",
        "ONE",
        "USE",
        "NEW",
        "ALL",
        "HOW",
        "ANY",
        "ITS",
        "VIA",
        "WHO",
        "WHY",
        "YET",
        "SET",
        "OUR",
        "OUT",
        "WAY",
        "TRY",
        "LET",
        "PUT",
        "GET",
        "END",
        "DID",
        "HIS",
        "HER",
        "BEEN",
        "ALSO",
        "SHOW",
        "THAN",
        "DOES",
        "SUCH",
        "HAVE",
        "MORE",
        "WELL",
        "MOST",
        "ONLY",
        "BOTH",
        "SOME",
        "MCP",
        "LLM",
        "API",
        "PDF",
        "URL",
        "PCT",
        "KEY",
        "RED",
        "DNA",
        "RNA",
        "ATP",
        "ADP",
        "GDP",
        "GTP",
        "USA",
        "NIH",
        "CSF",
        "CNS",
        "BBB",
        "PPI",
        "PET",
        "MRI",
        "CVE",
        "ROS",
        "iPSC",
        "CRISPR",
        "ELISA",
        "GWAS",
        "SNP",
        "DOID",
        "MESH",
        "HGNC",
        "CHEBI",
        "CYP450",
        "CSPG",
        "CSPGS",
    }
)

_ALIAS_MAP: dict[str, str] = {
    "RAGE": "AGER",
    "MK2": "MAPKAPK2",
    "P38": "MAPK14",
    "P53": "TP53",
    "BACE": "BACE1",
    "YKL40": "CHI3L1",
    "MCP1": "CCL2",
    "ABETA": "APP",
    "APOE4": "APOE",
}


def _normalize_entity(raw: str) -> str:
    """INDRA canonical gene names omit hyphens and use aliases such as AGER
    for RAGE."""
    normalized = raw.replace("-", "")
    upper = normalized.upper()
    return _ALIAS_MAP.get(upper, normalized)


def _should_skip_entity(upper: str, seen: set[str]) -> bool:
    return upper in _STOP or upper in seen


def _is_mutation_notation(raw: str) -> bool:
    """Single-letter/digit mutation labels such as V600E are not standalone
    gene names."""
    return len(raw) >= 2 and raw[0].isupper() and raw[1].isdigit()


def _add_hyphenated_entities(
    hyphenated: list[str], seen: set[str], result: list[str]
) -> None:
    """Hyphenated names are higher-signal; marking their prefixes prevents a
    second standalone match for the same entity."""
    for raw in hyphenated:
        prefix = raw.split("-")[0].upper()
        seen.add(prefix)
        normalized = _normalize_entity(raw)
        upper = normalized.upper()
        if _should_skip_entity(upper, seen):
            continue
        seen.add(upper)
        result.append(normalized)


def _add_standalone_entities(
    standalone: list[str], seen: set[str], result: list[str], max_entities: int
) -> None:
    for raw in standalone:
        if len(result) >= max_entities:
            break
        if _is_mutation_notation(raw):
            continue
        normalized = _normalize_entity(raw)
        upper = normalized.upper()
        if _should_skip_entity(upper, seen):
            continue
        seen.add(upper)
        result.append(normalized)


def extract_entity_names(text: str, max_entities: int = 3) -> list[str]:
    hyphenated = _HYPHENATED_RE.findall(text)
    standalone = _STANDALONE_RE.findall(text)

    seen: set[str] = set()
    result: list[str] = []

    _add_hyphenated_entities(hyphenated, seen, result)
    _add_standalone_entities(standalone, seen, result, max_entities)

    return result[:max_entities]


if TYPE_CHECKING:
    from co_scientist.config import ToolRegistry


# Mixed workflow lists include literature tools; only knowledge-graph source
# types accept the INDRA entity-query parameters.
_KNOWLEDGE_GRAPH_SOURCE_TYPE = "knowledge_graph"


def get_kg_tools_for_workflow(
    tool_registry: Optional["ToolRegistry"], workflow_name: str
) -> list[str]:
    """Knowledge-graph tools are opt-in by workflow, even if the server
    advertises them."""
    if tool_registry is None:
        return []
    try:
        # Registry IDs differ from the actual server names has_tool and
        # call_tool require.
        tool_ids = tool_registry.get_tools_for_workflow(workflow_name)
        if not tool_ids:
            return []
        return tool_registry.get_mcp_tool_names(
            _knowledge_graph_tool_ids(tool_registry, tool_ids)
        )
    except Exception:
        # Optional registry failures must not prevent reflection.
        return []


def _knowledge_graph_tool_ids(
    tool_registry: "ToolRegistry", tool_ids: list[str]
) -> list[str]:
    kept = []
    for tool_id in tool_ids:
        tool = tool_registry.get_tool(tool_id)
        if tool and tool.source_type == _KNOWLEDGE_GRAPH_SOURCE_TYPE:
            kept.append(tool_id)
    return kept


async def _fetch_evidence_result(
    client: Any,
    mcp_names: list[str],
    entities: list[str],
    max_statements: int,
) -> dict[str, Any] | None:
    tool_name = _pick_available_tool(client, mcp_names)
    if not tool_name:
        return None

    all_stmts = await _query_entities(
        client, tool_name, entities, max_statements
    )
    if not all_stmts:
        return None

    # Pool before capping preserves the existing global evidence budget,
    # including first-entity crowding of later entities.
    capped = all_stmts[:max_statements]
    return {
        "prompt_text": _format_evidence(capped, entities),
        "enrichment_items": _build_enrichment_items(capped, entities),
    }


async def fetch_indra_evidence(
    hypothesis_text: str,
    tool_registry: Optional["ToolRegistry"] = None,
    max_statements: int = 5,
    workflow_name: str = "reflection",
) -> dict[str, Any]:
    empty = {"prompt_text": "", "enrichment_items": []}

    mcp_names = get_kg_tools_for_workflow(tool_registry, workflow_name)
    if not mcp_names:
        return empty

    entities = extract_entity_names(hypothesis_text)
    if not entities:
        return empty

    result = await _resolve_indra_result(
        tool_registry, mcp_names, entities, max_statements
    )
    return result if result is not None else empty


async def _resolve_indra_result(
    tool_registry: Optional["ToolRegistry"],
    mcp_names: list[str],
    entities: list[str],
    max_statements: int,
) -> dict[str, Any] | None:
    """Optional enrichment failures must not abort the scientific review."""
    try:
        from co_scientist.mcp_client import get_mcp_client

        # Reuse the shared client rather than opening another connection for
        # each idea.
        client = await get_mcp_client(tool_registry=tool_registry)
        return await _fetch_evidence_result(
            client, mcp_names, entities, max_statements
        )
    except Exception as e:
        logger.debug("reflection evidence fetch skipped: %s", e)
        return None


def _pick_available_tool(client: Any, mcp_names: list[str]) -> str:
    for name in mcp_names:
        if client.has_tool(name):
            return name
    return ""


_EVIDENCE_LIMIT = 25


async def _query_single_entity(
    client: Any,
    tool_name: str,
    entity: str,
    max_per_entity: int,
) -> list[dict[str, Any]]:
    try:
        # agent is the INDRA/CoGex entity parameter name.
        raw = await client.call_tool(
            tool_name,
            agent=entity,
            limit=max_per_entity,
            evidence_limit=_EVIDENCE_LIMIT,
        )
        result = _parse_tool_result(raw)
        return cast("list[dict[str, Any]]", result.get("statements", []))
    except Exception as e:
        # One entity failure must not prevent evidence from its peers.
        logger.debug(
            "entity query failed for '%s' via %s: %s", entity, tool_name, e
        )
        return []


async def _query_entities(
    client: Any,
    tool_name: str,
    entities: list[str],
    max_per_entity: int,
) -> list[dict[str, Any]]:
    tasks = [
        _query_single_entity(client, tool_name, entity, max_per_entity)
        for entity in entities[:2]
    ]
    results = await asyncio.gather(*tasks)
    return [stmt for stmts in results for stmt in stmts]


def _parse_tool_result(raw: Any) -> dict[str, Any]:
    try:
        decoded = parse_mcp_result(raw)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _format_evidence(
    statements: list[dict[str, Any]], queried_entities: list[str]
) -> str:
    header = (
        "Structured knowledge from the INDRA biomedical knowledge graph "
        f"(queried for: {', '.join(queried_entities)}):"
    )
    lines = [header]

    for stmt in statements:
        line = _format_single_statement(stmt)
        if line:
            lines.append(line)

    # A bare header would imply evidence exists; an unrenderable set is empty.
    return "\n".join(lines) if len(lines) > 1 else ""


def _ev_count_str(ev_count: int) -> str:
    return f"{ev_count}+" if ev_count >= _EVIDENCE_LIMIT else str(ev_count)


class IndraStatementCore(NamedTuple):
    subj: str
    obj: str
    member_names: list[str]
    rel_type: str
    belief: float
    ev_count: int


def parse_indra_statement(stmt: dict[str, Any]) -> IndraStatementCore:
    """INDRA endpoints can return non-dict agents or complex-member shapes;
    both prompt formatters must interpret those shapes identically."""
    # INDRA complex/family relations use members rather than pairwise subj/obj.
    members = stmt.get("members", [])
    return IndraStatementCore(
        subj=_agent_name(stmt, "subj"),
        obj=_agent_name(stmt, "obj"),
        member_names=[
            m.get("name", "?") for m in members if isinstance(m, dict)
        ],
        rel_type=stmt.get("type", "Unknown"),
        belief=stmt.get("belief", 0),
        ev_count=len(stmt.get("evidence", [])),
    )


def _format_single_statement(stmt: dict[str, Any]) -> str:
    core = parse_indra_statement(stmt)
    ev_str = _ev_count_str(core.ev_count)

    if core.subj and core.obj:
        return (
            f"- {core.subj} --[{core.rel_type}]--> {core.obj} "
            f"(belief: {core.belief:.2f}, {ev_str} papers)"
        )

    if core.member_names:
        return (
            f"- Complex({', '.join(core.member_names)}) [{core.rel_type}] "
            f"(belief: {core.belief:.2f}, {ev_str} papers)"
        )

    return ""


def _build_enrichment_items(
    statements: list[dict[str, Any]],
    queried_entities: list[str],
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for stmt in statements:
        item = _statement_to_enrichment_item(stmt)
        if item:
            items.append(item)

    # Attach query context only once because the UI renders each item as a row.
    if items:
        items[0]["queried_entities"] = ", ".join(queried_entities)
    return items


def _statement_to_enrichment_item(
    stmt: dict[str, Any],
) -> dict[str, str] | None:
    core = parse_indra_statement(stmt)

    if core.subj and core.obj:
        relationship = f"{core.subj} \u2192 {core.obj}"
    elif core.member_names:
        relationship = f"Complex({', '.join(core.member_names)})"
    else:
        return None

    return {
        "relationship": relationship,
        "type": core.rel_type,
        "belief": f"{core.belief:.0%}",
        "evidence_count": _ev_count_str(core.ev_count),
    }


def _agent_name(stmt: dict[str, Any], role: str) -> str:
    agent = stmt.get(role, {})
    if isinstance(agent, dict):
        return cast(str, agent.get("name", ""))
    return ""
