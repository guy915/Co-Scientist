"""Dynamic tool-instruction builders for the generation prompts."""

from typing import Any


def _format_tool_entry(tool_config: Any) -> list[str]:
    """Format one tool's markdown bullet entry, plus its indented snippet.

    Args:
        tool_config: A ToolConfig with ``mcp_tool_name``, ``description``,
            and an optional ``prompt_snippet``.

    Returns:
        Lines for this tool's entry, ending with a blank line separating it
        from the next tool.
    """
    lines = [f"- `{tool_config.mcp_tool_name}`: {tool_config.description}"]

    # Add prompt snippet if available
    # prompt_snippet is per-tool usage guidance authored in the YAML
    # config, indented here so it nests under the tool's list entry.
    if tool_config.prompt_snippet:
        snippet_lines = tool_config.prompt_snippet.strip().split("\n")
        lines.extend(f"  {line}" for line in snippet_lines)

    lines.append("")  # blank line between tools
    return lines


def _resolve_tool_registry(
    tool_ids: list[str],
    tool_registry: Any | None,
) -> tuple[Any | None, list[str]]:
    """Fall back to the global tool registry when none is supplied.

    Also defaults tool_ids to the draft-generation workflow's tool list when
    the caller passed none, since that default only makes sense once a
    registry is available to resolve it against.

    Args:
        tool_ids: Caller-supplied tool IDs, possibly empty.
        tool_registry: Caller-supplied registry, or None to fall back to the
            global one.

    Returns:
        The resolved (tool_registry, tool_ids) pair. tool_registry may still
        be None if the global registry is unavailable.
    """
    if tool_registry is None:
        try:
            from co_scientist.config import (
                get_tool_registry,
            )

            tool_registry = get_tool_registry()
            # If no tool_ids provided, get them from draft workflow
            if not tool_ids:
                tool_ids = tool_registry.get_tools_for_workflow(
                    "draft_generation"
                )
        except Exception:
            pass

    return tool_registry, tool_ids


def _tool_entry_sections(tool_id: str, tool_registry: Any) -> list[str]:
    """Format one tool_id's entry lines, or [] if unknown/disabled."""
    tool_config = tool_registry.get_tool(tool_id)
    if not tool_config or not tool_config.enabled:
        return []
    return _format_tool_entry(tool_config)


def build_tool_instructions(
    tool_ids: list[str],
    tool_registry: Any | None = None,
) -> str:
    """Build dynamic tool instructions section from tool registry.

    Args:
        tool_ids: List of tool IDs to include in instructions
        tool_registry: ToolRegistry instance with tool configurations

    Returns:
        Formatted markdown section describing available tools
    """
    tool_registry, tool_ids = _resolve_tool_registry(tool_ids, tool_registry)

    if not tool_registry or not tool_ids:
        # Minimal fallback when no config available
        return (
            "No tool configuration available."
            " Literature tools may not be accessible."
        )

    sections = []
    for tool_id in tool_ids:
        sections.extend(_tool_entry_sections(tool_id, tool_registry))

    if not sections:
        return "No tools available."

    return "\n".join(sections).strip()
