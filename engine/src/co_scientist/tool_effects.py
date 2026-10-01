"""Effect typing for tool calls, and the batching rule it drives.

Every tool declares what it does to the world -- reads, writes, appends,
talks to the network, spawns a process. Three of those are *barrier*
effects: a barrier tool runs alone, never concurrently with a sibling in
the same model turn, because two writers (or a writer and a reader) racing
inside one turn produce a result the transcript cannot explain.

The vocabulary is deliberately reused rather than re-derived at each
enforcement point: today it gates concurrency in ``llm.tools.loop``; the
same declaration is what a plan-mode gate and an approval gate should read
when those exist, so a tool is described once and enforced in several
places.

**The default is the whole point.** A tool whose effects cannot be
resolved -- absent from the registry, or declaring a token this module does
not know -- is treated as a barrier. That is the fail-closed direction: a
mis-declared tool loses parallelism, which costs latency, rather than
silently running a process concurrently with everything else, which costs
correctness. Getting this default backwards re-creates the bug the module
exists to prevent.
"""

import logging
from enum import Flag, auto
from typing import Any

logger = logging.getLogger(__name__)


class ToolEffect(Flag):
    """What a tool does to the world outside the conversation."""

    NONE = 0
    READ = auto()
    WRITE = auto()
    APPEND = auto()
    NETWORK = auto()
    PROCESS = auto()


# Effects that force a tool to run alone. WRITE and APPEND mutate state a
# sibling call may be reading; PROCESS spawns something whose own effects
# are unknowable from here. NETWORK is deliberately absent: a remote read
# is the common case on this host (every MCP literature tool is one), and
# serializing those would undo the concurrency the loop exists to provide.
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
    """Resolves declared effect names into a combined ToolEffect.

    Args:
        names: Effect tokens as written in a tool declaration, e.g.
            ``["read", "network"]``. Case and surrounding space are
            ignored.

    Returns:
        The union of the named effects. An empty list, or any list
        containing a token this module does not know, resolves to
        ``UNDECLARED_EFFECTS`` -- a typo must not silently widen
        concurrency.
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
    """Reports whether a tool with these effects must run alone."""
    return bool(effects & BARRIER_EFFECTS)


# Effects for tools that are not MCP calls. Local tools -- the ones that
# execute commands and write files -- have no registry entry to read, so
# they declare here at import time. A plain dict rather than anything
# stateful: this is a static description of code, written once at module
# import and never mutated per run, so it is not the kind of
# process-global state the host's threading rules are about.
_LOCAL_EFFECTS: dict[str, ToolEffect] = {}


def declare_local_tool(name: str, effects: ToolEffect) -> None:
    """Records the effects of a tool that is not backed by MCP.

    Args:
        name: The tool name as the model sees it.
        effects: What the tool does to the world.
    """
    _LOCAL_EFFECTS[name] = effects


def is_local_tool(name: str) -> bool:
    """Reports whether a tool name is served locally rather than by MCP."""
    return name in _LOCAL_EFFECTS


def resolve_tool_effects(mcp_tool_name: str) -> ToolEffect:
    """Looks up one tool's declared effects by the name the model called.

    Local tools are consulted first, because they are the ones whose
    effects actually differ: they execute commands and write files, and
    they have no registry entry to fall back on. The MCP registry is then
    consulted lazily and its failures are swallowed -- a configuration
    problem must degrade this to "run everything serially", never break a
    run that was working. Import is deferred because ``config.registry``
    imports the tool schema, which would otherwise close a cycle back
    through this module.

    Note what the fail-closed default hides here. An unregistered local
    tool already resolves to a barrier, so a *write* tool behaves
    identically whether or not this function knows about it. The
    difference is only visible on a local tool that reads: it batches
    with its siblings once declared, and serializes when the declaration
    is not consulted.

    Args:
        mcp_tool_name: The name the model called -- a local tool name, or
            an MCP tool name rather than the YAML tool id.

    Returns:
        The tool's declared effects, or ``UNDECLARED_EFFECTS`` when the
        tool is unknown or the registry is unavailable.
    """
    local = _LOCAL_EFFECTS.get(mcp_tool_name)
    if local is not None:
        return local

    try:
        from co_scientist.config.registry import get_tool_registry

        tool = get_tool_registry().get_tool_by_mcp_name(mcp_tool_name)
    except Exception:  # see docstring: degrade to serial, never break a run
        logger.warning(
            "tool registry unavailable resolving effects for %r; "
            "treating the tool as a barrier",
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
    """Returns a tool call's function name, or "" when it has none."""
    function = getattr(tool_call, "function", None)
    return getattr(function, "name", "") or ""


def batch_by_effects(tool_calls: list[Any]) -> list[list[Any]]:
    """Splits one turn's tool calls into runs that may execute together.

    Walks the calls in the order the model emitted them and accumulates
    maximal *contiguous* runs of non-barrier calls. A barrier call becomes
    a batch of its own, which is what serializes it against both its
    predecessors and its successors. Order is preserved throughout, so
    concatenating each batch's results reproduces the model's own ordering
    without a re-sort.

    Contiguity matters: reordering calls to group compatible ones would
    change execution order relative to what the model asked for, and a
    model that emits read-then-write-then-read is entitled to that
    sequence.

    Args:
        tool_calls: The ``tool_calls`` list from an assistant message.

    Returns:
        A list of batches, each a non-empty list of tool calls, together
        containing every input call exactly once and in order.
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
