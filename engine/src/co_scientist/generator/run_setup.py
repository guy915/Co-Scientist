"""Per-run and per-instance setup helpers for the hypothesis generator.

Resolves caller-supplied generation options against system availability
(tool-calling generation, dev isolation mode), applies constructor-supplied
cache overrides to the environment, mints run identities, and builds the
optional tool registry.
"""

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


def _resolve_tool_calling_generation(
    opts: dict[str, Any],
    mcp_available: bool,
    enable_literature_review_node: bool,
) -> bool:
    """Determines whether tool-calling generation should be enabled.

    Tool-calling generation requires MCP availability and the literature
    review node; this validates the user's request against both,
    disabling (or raising) when the requirement isn't met.

    Args:
        opts: Caller-supplied generation options.
        mcp_available: Whether the MCP server is available.
        enable_literature_review_node: Whether the literature review node
            will run for this call.

    Returns:
        Whether tool-calling generation should be enabled.

    Raises:
        ValueError: If the user explicitly disabled the literature review
            node while requesting tool-calling generation.
    """
    # Determine if generate node should use tool-calling generation
    # user can override via opts, default False
    enable_tool_calling_generation = opts.get(
        "enable_tool_calling_generation", False
    )
    if not enable_tool_calling_generation:
        return False

    # Check MCP availability first - if unavailable, disable tool calling
    if not mcp_available:
        logger.warning(
            "enable_tool_calling_generation=True but MCP server"
            " unavailable - disabling tool-calling mode"
        )
        return False

    # Then check if literature review node is enabled
    if enable_literature_review_node:
        return True

    # Only raise error if user explicitly disabled literature review but
    # enabled tool calling
    if opts.get("enable_literature_review_node") is False:
        raise ValueError(
            "enable_tool_calling_generation requires"
            " enable_literature_review_node=True. "
            "Tool-calling generation needs literature context"
            " from the review node."
        )

    # Literature review was disabled due to MCP unavailability, disable
    # tool calling
    logger.warning(
        "enable_tool_calling_generation=True but literature"
        " review node unavailable - disabling tool-calling mode"
    )
    return False


def _configure_cache_dir_env(cache_dir: str | None) -> None:
    """Applies a constructor-supplied cache-directory override to the env.

    ``cache.get_cache()`` reads ``COSCIENTIST_CACHE_DIR`` once and memoizes
    the result process-wide, so this only takes effect if the generator is
    constructed before any LLM call happens elsewhere in the process. No
    caller passes ``cache_dir`` today (unlike ``enable_cache``, which is
    scoped per-task instead -- see ``cache.scoped_cache_override`` and its
    use in ``generator/core.py``), so this mutation is left as the
    process-wide default it has always been.

    Args:
        cache_dir: Directory for cache files (None = leave the existing env
            var, if any, untouched).
    """
    if cache_dir is None:
        return

    import os

    os.environ["COSCIENTIST_CACHE_DIR"] = cache_dir


def _resolve_run_identity(run_id: str | None) -> tuple[float, str]:
    """Mints a start time/run id for a new generation call and logs it.

    Args:
        run_id: Caller-supplied run id, or None to mint a fresh uuid4.

    Returns:
        Tuple of (start_time, run_id).
    """
    start_time = time.time()
    if run_id is None:
        run_id = str(uuid.uuid4())
    logger.info("Starting hypothesis generation with run_id=%s", run_id)
    return start_time, run_id


def _resolve_dev_isolation_flag(opts: dict[str, Any]) -> bool:
    """Reads the dev lit-tools-isolation flag from opts, logging if enabled.

    Args:
        opts: Caller-supplied generation options.

    Returns:
        Whether dev lit-tools isolation mode is enabled.
    """
    enabled = bool(opts.get("dev_test_lit_tools_isolation", False))
    if enabled:
        logger.info(
            "Dev isolation mode enabled: forcing lit review cache"
            " + all hypotheses to lit tools"
        )
    return enabled


def _build_tool_registry(
    tools_config: str | None,
    disable_tools: list[str] | None,
) -> Any:
    """Build the configured or bundled-default scientific tool registry.

    Args:
        tools_config: Path to custom tools YAML config file. None loads the
            bundled default registry.
        disable_tools: List of tool IDs to disable (None = use all enabled
            tools).

    Returns:
        An initialized ``ToolRegistry`` instance.
    """
    from co_scientist.config import (
        ToolRegistry,
    )

    registry = ToolRegistry(
        config_path=tools_config,
        disabled_tools=disable_tools,
    )
    logger.info(
        "Initialized %s tool registry: %s enabled tools",
        "custom" if tools_config else "bundled-default",
        len(registry.get_enabled_tools()),
    )
    return registry
