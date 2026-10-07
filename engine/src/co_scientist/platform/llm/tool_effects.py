"""Unknown effects fail closed to serial execution; concurrent writers make
transcripts incoherent.
"""

import logging
from enum import Flag, auto
from typing import Any

logger = logging.getLogger(__name__)


class ToolEffect(Flag):
    NONE = 0
    READ = auto()
    WRITE = auto()
    APPEND = auto()
    NETWORK = auto()
    PROCESS = auto()


# Writes and processes are barriers; network reads remain concurrent for
# literature retrieval.
BARRIER_EFFECTS = ToolEffect.WRITE | ToolEffect.APPEND | ToolEffect.PROCESS

# The fail-closed result for anything this module cannot resolve.
UNDECLARED_EFFECTS = ToolEffect.WRITE

_EFFECT_NAMES = {
    "read": ToolEffect.READ,
    "write": ToolEffect.WRITE,
    "append": ToolEffect.APPEND,
    "network": ToolEffect.NETWORK,
    "process": ToolEffect.PROCESS,
}


def parse_effects(names: list[str]) -> ToolEffect:
    """Unknown effect tokens must reduce parallelism rather than silently
    permit races.
    """
    if not names:
        return UNDECLARED_EFFECTS

    combined = ToolEffect.NONE
    for name in names:
        effect = _EFFECT_NAMES.get(name.strip().lower())
        if effect is None:
            logger.warning(
                "unknown tool effect %r; treating the tool as a barrier",
                name,
            )
            return UNDECLARED_EFFECTS
        combined |= effect
    return combined


def is_barrier(effects: ToolEffect) -> bool:
    return bool(effects & BARRIER_EFFECTS)


# Local tools declare effects once at import; they have no MCP registry entries.
_LOCAL_EFFECTS: dict[str, ToolEffect] = {}


def declare_local_tool(name: str, effects: ToolEffect) -> None:
    _LOCAL_EFFECTS[name] = effects


def is_local_tool(name: str) -> bool:
    return name in _LOCAL_EFFECTS


def resolve_tool_effects(mcp_tool_name: str) -> ToolEffect:
    """Local tools lack MCP entries; lazy registry import avoids a cycle, and
    lookup failures degrade to serial.
    """
    local = _LOCAL_EFFECTS.get(mcp_tool_name)
    if local is not None:
        return local

    try:
        from co_scientist.platform.retrieval.config.registry import get_tool_registry

        tool = get_tool_registry().get_tool_by_mcp_name(mcp_tool_name)
    except Exception:  # Lookup failure must degrade to serial execution, never break a run.
        logger.warning(
            "tool registry unavailable resolving effects for %r; treating the tool as a barrier",
            mcp_tool_name,
        )
        return UNDECLARED_EFFECTS

    if tool is None:
        logger.warning(
            "no registry entry for tool %r; treating it as a barrier",
            mcp_tool_name,
        )
        return UNDECLARED_EFFECTS
    return parse_effects(tool.effects)


def _tool_call_name(tool_call: Any) -> str:
    function = getattr(tool_call, "function", None)
    return getattr(function, "name", "") or ""


def batch_by_effects(tool_calls: list[Any]) -> list[list[Any]]:
    """Keep contiguous batches: regrouping read/write calls would change the
    model's requested order.
    """
    batches: list[list[Any]] = []
    current: list[Any] = []

    for tool_call in tool_calls:
        effects = resolve_tool_effects(_tool_call_name(tool_call))
        if is_barrier(effects):
            if current:
                batches.append(current)
                current = []
            batches.append([tool_call])
            continue
        current.append(tool_call)

    if current:
        batches.append(current)
    return batches
