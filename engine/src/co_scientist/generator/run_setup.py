"""Per-run and per-instance setup helpers for the hypothesis generator.

Resolves caller-supplied generation options against system availability
(tool-calling generation, dev isolation mode, dev mode), applies
constructor-supplied cache overrides to the environment, mints run
identities, and builds the optional tool registry.

This is where the process environment is allowed to reach a run: a flag is
read here once, at the boundary, and travels the rest of the way as workflow
state, so a node's behavior is a function of the state it was handed.
"""

import logging
import os
import time
import uuid
from typing import Any

from co_scientist.config.registry import parse_bool_env
from co_scientist.offline_llm import is_offline_model

logger = logging.getLogger(__name__)


def _resolve_tool_calling_generation(
    opts: dict[str, Any],
    mcp_available: bool,
    enable_literature_review_node: bool,
    model_name: str,
) -> bool:
    """Determines whether tool-calling generation should be enabled.

    Tool-calling generation (the agentic literature-exploration draft
    path) is on by default whenever the run has literature tools
    available -- MCP reachable and the literature review node enabled --
    because the model deciding when to search/read is the technique's
    point, and no production caller opts in explicitly. A caller opt-out
    (``enable_tool_calling_generation=False`` in opts) stays available.

    Two conditions force the plain path regardless of the request:

    - The offline backend answers completions locally and never emits
      tool calls, so a tool loop would "finish" on its first free-text
      reply and fail parsing. Offline runs stay deterministic.
    - MCP or the literature review node is unavailable: the draft agent
      would have no tools to call.

    Args:
        opts: Caller-supplied generation options.
        mcp_available: Whether the MCP server is available.
        enable_literature_review_node: Whether the literature review node
            will run for this call.
        model_name: The worker model name for this run.

    Returns:
        Whether tool-calling generation should be enabled.

    Raises:
        ValueError: If the caller explicitly disabled the literature
            review node while explicitly requesting tool-calling
            generation.
    """
    requested = opts.get("enable_tool_calling_generation")

    if _tool_calling_disabled_before_availability(requested, model_name):
        return False

    # Check MCP availability first - if unavailable, disable tool calling
    if not mcp_available:
        if requested:
            logger.warning(
                "enable_tool_calling_generation=True but MCP server"
                " unavailable - disabling tool-calling mode"
            )
        return False

    return _resolve_tool_calling_given_mcp_available(
        opts, enable_literature_review_node, requested
    )


def _tool_calling_disabled_before_availability(
    requested: bool | None, model_name: str
) -> bool:
    """Forces the plain path for offline backends and explicit opt-outs.

    These two conditions hold regardless of tool availability: the
    offline responder never emits tool calls (a tool loop would finish
    on its first free-text reply), and an explicit False is the caller
    opt-out the default-on resolution preserves.

    Args:
        requested: The caller's explicit tool-calling request, or None.
        model_name: The worker model name for this run.

    Returns:
        True when tool-calling generation must stay off for this reason.
    """
    if is_offline_model(model_name):
        if requested:
            logger.warning(
                "enable_tool_calling_generation=True but the offline"
                " backend is active - disabling tool-calling mode"
            )
        return True

    if requested is False:
        logger.info("Tool-calling generation disabled by caller option")
        return True

    return False


def _resolve_tool_calling_given_mcp_available(
    opts: dict[str, Any],
    enable_literature_review_node: bool,
    requested: bool | None,
) -> bool:
    """Resolves tool-calling generation once MCP is known to be available.

    Still requires the literature review node; raises if the caller
    explicitly disabled it while explicitly requesting tool-calling
    generation, otherwise disables tool-calling (with a warning for an
    explicit request, silently for the default-on resolution).

    Args:
        opts: Caller-supplied generation options.
        enable_literature_review_node: Whether the literature review node
            will run for this call.
        requested: The caller's explicit tool-calling request, or None
            when the option was omitted (default-on resolution).

    Returns:
        Whether tool-calling generation should be enabled.

    Raises:
        ValueError: If the caller explicitly disabled the literature
            review node while explicitly requesting tool-calling
            generation.
    """
    if enable_literature_review_node:
        if requested is None:
            logger.info(
                "Tool-calling generation enabled by default"
                " (MCP server and literature review node available)"
            )
        return True

    # Only raise error if user explicitly disabled literature review but
    # enabled tool calling
    if requested and opts.get("enable_literature_review_node") is False:
        raise ValueError(
            "enable_tool_calling_generation requires"
            " enable_literature_review_node=True. "
            "Tool-calling generation needs literature context"
            " from the review node."
        )

    # Literature review was disabled, so the draft agent would have no
    # literature context; disable tool calling.
    if requested:
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


def _resolve_dev_mode_flag(opts: dict[str, Any]) -> bool:
    """Resolves dev mode for a run, from opts or the process environment.

    Dev mode shrinks the literature-review budget for fast iteration. The
    ``COSCIENTIST_DEV_MODE`` environment variable is the outer default a
    developer sets once for a whole session; an explicit ``dev_mode`` opt is
    the inner, per-run answer and wins over it. Reading the env here rather
    than inside the literature review node keeps the node a function of the
    state it is handed -- and keeps the flag visible in a checkpoint, which
    an ambient env read never is.

    Args:
        opts: Caller-supplied generation options.

    Returns:
        Whether dev mode is enabled for this run.
    """
    requested = opts.get("dev_mode")
    if requested is None:
        requested = parse_bool_env(os.getenv("COSCIENTIST_DEV_MODE", "false"))
    enabled = bool(requested)
    if enabled:
        logger.info(
            "Dev mode enabled: using the reduced literature-review budget"
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
