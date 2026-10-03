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
from dataclasses import dataclass, field
from typing import Any

from co_scientist.agents.generation.coordinator_strategy import (
    GENERATION_STRATEGY_LABELS,
    TOOLS_REQUIRING_STRATEGIES,
)
from co_scientist.config.registry import parse_bool_env
from co_scientist.constants import ELO_K_FACTOR
from co_scientist.offline.llm import is_offline_model
from co_scientist.research_adapter.budget import tier_researches


@dataclass(frozen=True)
class GeneratorOptions:
    """Optional generator configuration beyond the core run-size knobs.

    Every field defaults to the generator's historical default, so
    ``GeneratorOptions()`` reproduces the old all-defaults constructor.

    Attributes:
        supervisor_model_name: Model for the supervisor and meta-review
            steps (None = use the generator's ``model_name``).
        tournament_pairs: Number of Elo tournament comparisons per ranking.
        elo_k_factor: Rating sensitivity applied to every committed match.
        literature_review_papers_count: Number of papers to read/analyze.
        enable_cache: Enable/disable LLM response caching for this
            generator's own calls (None = the process default from
            ``COSCIENTIST_CACHE_ENABLED``). Scoped to this generator's own
            execution via ``cache.scoped_cache_override`` rather than
            mutating that env var, so it never disables caching for another
            generator running in the same process.
        cache_dir: Directory for cache files (None = use default).
        tools_config: Path to custom tools YAML config file (None =
            use defaults).
        disable_tools: Tool IDs to disable (None = use all enabled tools).
        budget: Optional serialized ``scheduling.Budget`` (keys
            ``max_iterations``/``max_llm_calls``/``max_tasks``/
            ``max_wall_clock_s``) giving the adaptive scheduler hard
            termination ceilings beyond ``max_iterations``. None derives a
            budget from ``max_iterations`` alone.
        api_key: Bring-your-own-key provider credential for the run. When
            set, every completion the run makes passes it to litellm as
            the per-call ``api_key``, overriding the deployment's
            environment credential for this generator's execution only --
            no env mutation, no process-wide state. The key is held on the
            instance and scoped into a task-local contextvar around
            execution; it is never placed in the workflow state, so it
            cannot enter a checkpoint. Caching is force-disabled for such
            runs (cache keys carry no credential, so a shared cache could
            replay one tenant's responses into another's run).
    """

    supervisor_model_name: str | None = None
    tournament_pairs: int = 12
    elo_k_factor: int = ELO_K_FACTOR
    literature_review_papers_count: int = 8
    enable_cache: bool | None = None
    cache_dir: str | None = None
    tools_config: str | None = None
    disable_tools: list[str] | None = None
    budget: dict[str, Any] | None = field(default=None)
    api_key: str | None = None


logger = logging.getLogger(__name__)


def _resolve_meta_review(opts: dict[str, Any]) -> bool:
    """Decide whether the periodic meta-review cadence may fire.

    Default on: only an explicit ``enable_meta_review=False`` in opts
    disables it. Unlike the tier-shaped capability toggles above, this has
    no availability precondition -- meta-review is an ordinary model call
    that runs on every backend, so the offline backend is not a refusal
    here. Gates the scheduler's cadence check only
    (``scheduling.policy_cadence._check_meta_review_cadence``); the EVOLVE
    branch still enters the meta_review node, so disabling this removes
    *periodic* system-wide feedback, not the node.

    Args:
        opts: Caller-supplied generation options.

    Returns:
        Whether the periodic meta-review cadence is enabled for this run.
    """
    return opts.get("enable_meta_review", True) is not False


def _resolve_generation_strategy(
    opts: dict[str, Any], enable_tool_calling_generation: bool
) -> str:
    """Resolve a forced generation-strategy label, or "" to derive the mix.

    An ablation caller may pin the generation strategy rather than letting
    the coordinator derive it from literature/tool availability. Only a
    known ``coordinator_strategy`` label is honored; anything else derives.
    A tools-requiring label (``dev_isolation``/``lit_and_tools``) is refused
    when tool-calling generation resolved off -- the same shape
    ``_resolve_tool_calling_generation`` uses -- because those route into
    the tool-based draft path, which has no tool loop to run without it.

    Args:
        opts: Caller-supplied generation options.
        enable_tool_calling_generation: Whether tool-calling generation
            resolved on for this run.

    Returns:
        A validated strategy label, or "" to derive the mix.
    """
    requested = opts.get("generation_strategy")
    if not isinstance(requested, str) or requested not in (
        GENERATION_STRATEGY_LABELS
    ):
        return ""
    if (
        requested in TOOLS_REQUIRING_STRATEGIES
        and not enable_tool_calling_generation
    ):
        logger.warning(
            "generation_strategy=%s requires tool-calling generation, which"
            " is off for this run - deriving the strategy instead",
            requested,
        )
        return ""
    return requested


def _resolve_tool_calling_generation(
    opts: dict[str, Any],
    mcp_available: bool,
    enable_literature_review_node: bool,
    model_name: str,
) -> bool:
    """Determines whether tool-calling generation should be enabled.

    Tool-calling generation (the agentic literature-exploration draft
    path) is opt-in: the caller asks for it with
    ``enable_tool_calling_generation=True`` in opts, and it then runs
    only where the run has literature tools available -- MCP reachable
    and the literature review node enabled. It is opt-in because the
    model deciding when to search and read costs an LLM round-trip per
    tool call, each carrying every prior result forward, which is worth
    funding at the deep tiers and not at every tier.

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


def _resolve_simulation_execution(
    opts: dict[str, Any], model_name: str
) -> bool:
    """Decides whether the simulation review may run what it simulates.

    Opt-in, like tool-calling generation and for the same reason: it is a
    tool loop per hypothesis, and the app asks for it on the deep tiers
    only. Two conditions force it off regardless of the request -- the
    offline backend never emits a tool call, so the loop would end on its
    first free-text reply having run nothing, and an explicit False
    short-circuits.

    Not checked here: whether this host can confine a command. That is a
    property of the machine the review executes on rather than of the
    run, and a worker cohort can outlive the process that resolved this,
    so ``simulation_execution`` asks at the point of use and degrades
    there.

    Args:
        opts: The caller's run options.
        model_name: The worker model name for this run.

    Returns:
        Whether the simulation review may execute.
    """
    requested = opts.get("enable_simulation_execution")
    if not requested:
        return False
    if is_offline_model(model_name):
        logger.warning(
            "enable_simulation_execution=True but the offline backend is "
            "active - the simulation review will step through mentally"
        )
        return False
    return True


def _resolve_overview_review(opts: dict[str, Any], model_name: str) -> bool:
    """Decides whether the terminal research overview is accuracy-reviewed.

    Opt-in, like ``_resolve_simulation_execution`` and for the same
    reason: it is extra LLM calls on top of the terminal synthesis, and
    the app asks for it on the deep tiers only. The offline backend
    forces it off regardless of the request -- it answers every
    schema-constrained call deterministically, so a review of that
    output would check nothing real and only add calls.

    Args:
        opts: The caller's run options.
        model_name: The supervisor model name for this run.

    Returns:
        Whether the research-overview node may run its review/revise
        cycle over the drafted overview.
    """
    requested = opts.get("enable_overview_review")
    if not requested:
        return False
    if is_offline_model(model_name):
        logger.warning(
            "enable_overview_review=True but the offline backend is "
            "active - the research overview will publish unreviewed"
        )
        return False
    return True


def _resolve_research_tier(opts: dict[str, Any], mcp_available: bool) -> str:
    """Decides how much deep research this run may do, if any.

    Opt-in and tier-shaped, like tool-calling generation and executed
    simulation -- with one difference: the caller passes its tier
    verbatim rather than a decision, because which tiers buy research is
    already stated once, in ``research_adapter.budget``. A second copy of
    that list on the caller's side is how the two drift apart. An unknown
    or shallow tier buys nothing, so a caller that says nothing
    researches nothing.

    Forced off regardless of the request when the MCP server is
    unreachable, because the loop's whole shape is search, read, search
    again and there would be nowhere to search. Whether the literature
    review *node* runs is deliberately not a condition -- research has
    two owners now, and the reviews resolve the run's search sources
    from its tool registry themselves, so a run with the review turned
    off still researches inside its deep reviews. The offline backend is
    not a condition either: these are ordinary schema-constrained
    completions, which it answers deterministically, so an offline run
    still exercises the whole path.

    Args:
        opts: Caller-supplied generation options.
        mcp_available: Whether the MCP server is available.

    Returns:
        The tier to research at, or "" for no research.
    """
    requested = opts.get("research_tier")
    if not isinstance(requested, str) or not tier_researches(requested):
        return ""
    if not mcp_available:
        logger.warning(
            "research_tier=%s requested but no literature tools are"
            " available - skipping deep research",
            requested,
        )
        return ""
    return requested


def _tool_calling_disabled_before_availability(
    requested: bool | None, model_name: str
) -> bool:
    """Forces the plain path for offline backends and explicit opt-outs.

    These two conditions hold regardless of tool availability: the
    offline responder never emits tool calls (a tool loop would finish
    on its first free-text reply), and an explicit False short-circuits
    before any availability check.

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

    Tool-calling generation is opt-in: with the literature review node
    running, it is enabled only for an explicit request. Raises if the
    caller explicitly disabled that node while explicitly requesting
    tool-calling generation, and otherwise disables tool-calling.

    Args:
        opts: Caller-supplied generation options.
        enable_literature_review_node: Whether the literature review node
            will run for this call.
        requested: The caller's explicit tool-calling request, or None
            when the option was omitted (which is not a request).

    Returns:
        Whether tool-calling generation should be enabled.

    Raises:
        ValueError: If the caller explicitly disabled the literature
            review node while explicitly requesting tool-calling
            generation.
    """
    if enable_literature_review_node:
        # Opt-in, not default-on: an omitted option is not a request. The
        # draft agent spends one LLM round-trip per tool call and carries
        # every prior result into the next prompt, so one hypothesis
        # costs ~9 calls on prompts that grow past 12k tokens -- per
        # hypothesis, per cycle. Default-on put that on every run
        # including express, where it became the single largest line in
        # the token budget. Callers that want it ask for it, and the app
        # asks only for the tiers whose envelope funds it.
        return requested is True

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
