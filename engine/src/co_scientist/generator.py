"""Main HypothesisGenerator class.

Provides an interface inspired by the original AI-CoScientist integration,
but uses LangGraph under the hood.
"""
# pylint: disable=inconsistent-quotes

import logging
import time
import uuid
from typing import Any, Literal, cast, overload
from collections.abc import AsyncIterator, Awaitable, Callable

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from co_scientist.constants import (
    DEFAULT_MAX_ITERATIONS,
    DEFAULT_INITIAL_HYPOTHESES_COUNT,
    DEFAULT_EVOLUTION_MAX_COUNT,
)
from co_scientist.models import ExecutionMetrics, merge_metrics
# Node callables, one per LangGraph node; see _build_graph below for how
# they are wired into the workflow graph.
from co_scientist.nodes.generate import generate_node
from co_scientist.nodes.literature_review import literature_review_node
from co_scientist.nodes.reflection import reflection_node
from co_scientist.nodes.review import review_node
from co_scientist.nodes.ranking import ranking_node
from co_scientist.nodes.deep_verification import deep_verification_node
from co_scientist.nodes.meta_review import meta_review_node
from co_scientist.nodes.evolve import evolve_node
from co_scientist.nodes.proximity import proximity_node
from co_scientist.nodes.research_overview import research_overview_node
from co_scientist.nodes.supervisor import supervisor_node
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)

# Compiled LangGraph workflow. The fourth type parameter (StateT) is left
# loose because langgraph's compile() leaks an unbound type variable.
CompiledWorkflow = CompiledStateGraph[Any, Any, Any, Any]

# State fields streamed to callers as plain last-write-wins copies. Two
# streamed fields are handled separately in _handle_streaming: metrics
# (merged across nodes) and supervisor_guidance (renamed to research_plan).
_STREAMED_STATE_KEYS = (
    "hypotheses",
    "meta_review",
    "research_overview",
    "tournament_matchups",
    "evolution_details",
    "current_iteration",
    "articles_with_reasoning",
    "literature_review_queries",
    "articles",
    "debate_transcripts",
)


def _after_ranking(state: WorkflowState) -> str:
    """Decide what to do after ranking based on workflow state."""
    current_iteration = state.get("current_iteration", 0)
    max_iterations = state.get("max_iterations", 0)
    # Check if we've already run meta_review (indicates we're in
    # iteration cycle)
    has_meta_review = bool(state.get("meta_review", {}))

    if not has_meta_review:
        # First ranking - check if we should start iterating
        if current_iteration < max_iterations:
            logger.info("Starting iteration %s/%s", current_iteration + 1,
                        max_iterations)
            return "iterate"
        else:
            logger.info("No iterations needed, ending workflow")
            return "end"
    else:
        # We're in an iteration cycle - go through proximity for
        # deduplication
        logger.info("Going through proximity check")
        return "proximity"


def _after_proximity(state: WorkflowState) -> str:
    """Check if should continue after proximity deduplication."""
    # Note: proximity node increments current_iteration
    current_iteration = state.get("current_iteration", 0)
    max_iterations = state.get("max_iterations", 0)

    if current_iteration < max_iterations:
        logger.info("Continuing to iteration %s/%s", current_iteration + 1,
                    max_iterations)
        return "iterate"
    else:
        logger.info("All iterations complete after deduplication")
        return "end"


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
    enable_tool_calling_generation = opts.get("enable_tool_calling_generation",
                                              False)
    if not enable_tool_calling_generation:
        return False

    # Check MCP availability first - if unavailable, disable tool calling
    if not mcp_available:
        logger.warning("enable_tool_calling_generation=True but MCP server"
                       " unavailable - disabling tool-calling mode")
        return False

    # Then check if literature review node is enabled
    if enable_literature_review_node:
        return True

    # Only raise error if user explicitly disabled literature review but
    # enabled tool calling
    if opts.get("enable_literature_review_node") is False:
        raise ValueError("enable_tool_calling_generation requires"
                         " enable_literature_review_node=True. "
                         "Tool-calling generation needs literature context"
                         " from the review node.")

    # Literature review was disabled due to MCP unavailability, disable
    # tool calling
    logger.warning("enable_tool_calling_generation=True but literature"
                   " review node unavailable - disabling tool-calling mode")
    return False


def _merge_node_state_into_cumulative(
    cumulative_state: dict[str, Any],
    node_state: dict[str, Any],
) -> None:
    """Applies one LangGraph node's incremental update to cumulative state.

    LangGraph's astream only yields the fields updated by each node, not the
    full state, so the caller keeps a running ``cumulative_state`` across the
    stream and merges each node's update into it. Most fields are plain
    last-write-wins copies; two are special-cased: ``supervisor_guidance``
    (renamed to ``research_plan``) and ``metrics`` (merged, not replaced).

    Args:
        cumulative_state: Streaming state accumulated across nodes so far;
            updated in place.
        node_state: The incremental state returned by the node that just ran.
    """
    for key in _STREAMED_STATE_KEYS:
        if key in node_state:
            cumulative_state[key] = node_state[key]
            logger.debug("updated %s", key)
    if "supervisor_guidance" in node_state:
        cumulative_state["research_plan"] = node_state["supervisor_guidance"]
        logger.debug("updated research_plan")
    if "metrics" in node_state:
        cumulative_state["metrics"] = merge_metrics(cumulative_state["metrics"],
                                                    node_state["metrics"])
        logger.debug(
            "merged metrics: reviews=%s, "
            "tournaments=%s, evolutions=%s, llm_calls=%s",
            cumulative_state["metrics"].reviews_count,
            cumulative_state["metrics"].tournaments_count,
            cumulative_state["metrics"].evolutions_count,
            cumulative_state["metrics"].llm_calls,
        )


def _build_stream_state_dict(
        cumulative_state: dict[str, Any]) -> dict[str, Any]:
    """Shapes cumulative streaming state into a per-node yield payload.

    Args:
        cumulative_state: Streaming state accumulated across nodes so far.

    Returns:
        The dict yielded to the caller alongside the completed node's name.
    """
    metrics = cumulative_state["metrics"]
    state_dict = {key: cumulative_state[key] for key in _STREAMED_STATE_KEYS}
    state_dict.update({
        "hypotheses": [h.to_dict() for h in cumulative_state["hypotheses"]],
        "articles": [a.to_dict() for a in cumulative_state["articles"]],
        "research_plan": cumulative_state["research_plan"],
        "metrics": {
            "hypothesis_count": metrics.hypothesis_count,
            "reviews_count": metrics.reviews_count,
            "tournaments_count": metrics.tournaments_count,
            "evolutions_count": metrics.evolutions_count,
            "llm_calls": metrics.llm_calls,
        },
    })
    return state_dict


def _build_generation_result(
    final_state: WorkflowState,
    execution_time: float,
) -> dict[str, Any]:
    """Formats a completed workflow's final state into the result dict.

    Args:
        final_state: The workflow state returned by the graph's ``ainvoke``.
        execution_time: Wall-clock seconds spent in ``ainvoke``.

    Returns:
        The dictionary returned to callers of ``generate_hypotheses`` when
        ``stream=False``.
    """
    metrics = final_state["metrics"]
    return {
        "hypotheses": [h.to_dict() for h in final_state["hypotheses"]],
        "meta_review": final_state.get("meta_review", {}),
        "research_overview": final_state.get("research_overview", {}),
        "research_plan": final_state.get("supervisor_guidance", {}),
        "tournament_matchups": final_state.get("tournament_matchups", []),
        "evolution_details": final_state.get("evolution_details", []),
        "debate_transcripts": final_state.get("debate_transcripts"),
        "execution_time": execution_time,
        "metrics": {
            "total_time": execution_time,
            "hypothesis_count": metrics.hypothesis_count,
            "reviews_count": metrics.reviews_count,
            "tournaments_count": metrics.tournaments_count,
            "evolutions_count": metrics.evolutions_count,
            "phase_times": metrics.phase_times,
            "llm_calls": metrics.llm_calls,
        },
    }


def _cache_enabled_env_value(enable_cache: bool | None) -> str | None:
    """Renders the cache-enabled flag as the string env var cache.py expects.

    Args:
        enable_cache: Enable/disable LLM response caching, or None.

    Returns:
        "true"/"false" for a non-None input, else None (passthrough).
    """
    if enable_cache is None:
        return None
    return "true" if enable_cache else "false"


def _configure_cache_env(enable_cache: bool | None,
                         cache_dir: str | None) -> None:
    """Applies constructor-supplied cache overrides to the environment.

    ``cache.get_cache()`` reads these env vars once and memoizes the result
    process-wide, so this only takes effect if the generator is constructed
    before any LLM call happens elsewhere in the process.

    Args:
        enable_cache: Enable/disable LLM response caching (None = leave the
            existing env var, if any, untouched).
        cache_dir: Directory for cache files (None = leave the existing env
            var, if any, untouched).
    """
    if enable_cache is None and cache_dir is None:
        return

    import os  # pylint: disable=import-outside-toplevel

    overrides: tuple[tuple[str | None, str], ...] = (
        (_cache_enabled_env_value(enable_cache), "COSCIENTIST_CACHE_ENABLED"),
        (cache_dir, "COSCIENTIST_CACHE_DIR"),
    )
    for value, env_key in overrides:
        if value is not None:
            os.environ[env_key] = value


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
        logger.info("Dev isolation mode enabled: forcing lit review cache"
                    " + all hypotheses to lit tools")
    return enabled


def _build_tool_registry(
    tools_config: str | None,
    disable_tools: list[str] | None,
) -> Any | None:
    """Builds the tool registry from constructor options, if requested.

    Args:
        tools_config: Path to custom tools YAML config file (None = use
            defaults).
        disable_tools: List of tool IDs to disable (None = use all enabled
            tools).

    Returns:
        A ``ToolRegistry`` instance, or None if neither option was supplied.
    """
    if tools_config is None and disable_tools is None:
        return None

    from co_scientist.config import ToolRegistry  # pylint: disable=import-outside-toplevel

    registry = ToolRegistry(
        config_path=tools_config,
        disabled_tools=disable_tools,
    )
    logger.info("Initialized tool registry: %s enabled tools",
                len(registry.get_enabled_tools()))
    return registry


class HypothesisGenerator:
    """Async wrapper for hypothesis generation using LangGraph.

    Example:
        >>> generator = HypothesisGenerator(
        ...     model_name="gemini/gemini-2.5-flash",
        ...     max_iterations=1,
        ...     initial_hypotheses_count=5,
        ...     evolution_max_count=3
        ... )
        >>> result = await generator.generate_hypotheses(
        ...     research_goal="Cure cancer",
        ...     progress_callback=my_callback
        ... )
    """

    def __init__(
        self,
        model_name: str = "gemini/gemini-2.5-flash",
        supervisor_model_name: str | None = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        initial_hypotheses_count: int = DEFAULT_INITIAL_HYPOTHESES_COUNT,
        evolution_max_count: int = DEFAULT_EVOLUTION_MAX_COUNT,
        tournament_pairs: int = 12,
        literature_review_papers_count: int = 8,
        enable_cache: bool | None = None,
        cache_dir: str | None = None,
        tools_config: str | None = None,
        disable_tools: list[str] | None = None,
    ):
        """Initialize the hypothesis generator.

        Args:
            model_name: LLM model to use (litellm format)
            max_iterations: Number of refinement iterations
            initial_hypotheses_count: Number of initial hypotheses
            evolution_max_count: Number of top hypotheses to evolve
            tournament_pairs: Number of Elo tournament comparisons per ranking
            literature_review_papers_count: Number of papers to read/analyze
            enable_cache: Enable/disable LLM response caching
                (None = use env var)
            cache_dir: Directory for cache files (None = use default)
            tools_config: Path to custom tools YAML config file
                (None = use defaults)
            disable_tools: List of tool IDs to disable
                (None = use all enabled tools)
        """
        # Constructor arguments become per-instance defaults that seed the
        # initial workflow state on every generate_hypotheses() call below.
        self.model_name = model_name
        self.supervisor_model_name = supervisor_model_name or model_name
        self.max_iterations = max_iterations
        self.initial_hypotheses_count = initial_hypotheses_count
        self.evolution_max_count = evolution_max_count
        self.tournament_pairs = tournament_pairs
        self.literature_review_papers_count = literature_review_papers_count

        # Configure cache if specified
        _configure_cache_env(enable_cache, cache_dir)

        # Initialize tool registry if tools_config or disable_tools specified
        self._tool_registry = _build_tool_registry(tools_config, disable_tools)

        # Build the graph (lazy - only once)
        self._graph: CompiledWorkflow | None = None

        # Cache availability checks per instance (lazy init on first generate
        # call)
        self._mcp_available: bool | None = None
        self._pubmed_available: bool | None = None

    def _build_graph(
            self,
            enable_literature_review_node: bool = True) -> CompiledWorkflow:
        """Build the LangGraph workflow.

        Complete workflow:
        1. SUPERVISOR → creates research plan
        2. LITERATURE_REVIEW → search and analyze literature (optional, if MCP
        available)
        3. GENERATE → initial hypotheses
        4. REFLECTION → analyze hypotheses against literature (skipped if no lit
        review)
        5. REVIEW → parallel peer reviews
        6. RANKING → sort by score, then run Elo tournaments
        7. ITERATIONS (if max_iterations > 0):
           - META_REVIEW → synthesize insights
           - EVOLVE → refine top-k hypotheses
           - REVIEW → re-review evolved hypotheses
           - RANKING → update Elo ratings
           - PROXIMITY → deduplicate similar hypotheses
           - Loop back or END
        8. END → return top hypotheses

        Args:
            enable_literature_review_node: Whether to include literature
                review node (requires MCP server)
        """
        workflow = StateGraph(WorkflowState)

        # These run unconditionally; the literature review and reflection
        # nodes are added conditionally further below.
        # Add all nodes
        workflow.add_node("supervisor", supervisor_node)
        workflow.add_node("generate", generate_node)
        workflow.add_node("review", review_node)
        workflow.add_node("ranking", ranking_node)
        workflow.add_node("deep_verification", deep_verification_node)
        workflow.add_node("meta_review", meta_review_node)
        workflow.add_node("evolve", evolve_node)
        workflow.add_node("proximity", proximity_node)
        workflow.add_node("research_overview", research_overview_node)

        # Conditionally add literature review and reflection nodes
        if enable_literature_review_node:
            workflow.add_node("literature_review", literature_review_node)
            workflow.add_node("reflection", reflection_node)

        # Initial flow - conditional based on literature review availability
        workflow.set_entry_point("supervisor")

        if enable_literature_review_node:
            # Full flow: supervisor → literature_review → generate → reflection
            # → review → ranking
            workflow.add_edge("supervisor", "literature_review")
            workflow.add_edge("literature_review", "generate")
            workflow.add_edge("generate", "reflection")
            workflow.add_edge("reflection", "review")
        else:
            # Simplified flow: supervisor → generate → review → ranking
            workflow.add_edge("supervisor", "generate")
            workflow.add_edge("generate", "review")

        workflow.add_edge("review", "ranking")

        # Iteration cycle: meta_review → evolve → review → ranking → proximity
        workflow.add_edge("meta_review", "evolve")
        workflow.add_edge("evolve", "review")  # Re-review evolved hypotheses

        # Note: review → ranking already defined above

        # Deep-verification runs on the top-ranked hypotheses after ranking,
        # then the same post-ranking routing decision (_after_ranking) is
        # made one node later.
        workflow.add_edge("ranking", "deep_verification")
        workflow.add_conditional_edges(
            "deep_verification", _after_ranking, {
                "iterate": "meta_review",
                "proximity": "proximity",
                "end": "research_overview"
            })

        # After proximity, check if we should continue iterating
        workflow.add_conditional_edges("proximity", _after_proximity, {
            "iterate": "meta_review",
            "end": "research_overview"
        })

        # Terminal synthesis: every completion path flows through the
        # research-overview node before ending.
        workflow.add_edge("research_overview", END)

        return workflow.compile()

    def _ensure_graph_built(self, enable_literature_review_node: bool) -> None:
        """Builds and caches self._graph on first call; a no-op afterward.

        Args:
            enable_literature_review_node: Whether the literature review node
                should be included if the graph is being built now.
        """
        if self._graph is None:
            self._graph = self._build_graph(
                enable_literature_review_node=enable_literature_review_node)

    async def _check_cached_availability(self) -> tuple[bool, bool]:
        """Lazily checks and caches MCP/PubMed availability for this call.

        Each check runs at most once per instance; later calls reuse
        ``self._mcp_available`` / ``self._pubmed_available``.

        Returns:
            Tuple of (mcp_available, pubmed_available).
        """
        from co_scientist.mcp_client import check_mcp_available, check_pubmed_available_via_mcp  # pylint: disable=import-outside-toplevel

        if self._mcp_available is None:
            self._mcp_available = await check_mcp_available(
                tool_registry=self._tool_registry)
        if self._pubmed_available is None:
            self._pubmed_available = await check_pubmed_available_via_mcp(
                tool_registry=self._tool_registry)

        return self._mcp_available, self._pubmed_available

    async def _resolve_literature_review_settings(
        self,
        opts: dict[str, Any],
    ) -> tuple[bool, bool, bool]:
        """Determines literature-review/MCP availability for this call.

        Checks are cached per instance (on ``self._mcp_available`` and
        ``self._pubmed_available``) and skipped entirely when the caller has
        explicitly disabled the literature review node.

        Args:
            opts: Caller-supplied generation options.

        Returns:
            Tuple of (mcp_available, pubmed_available,
            enable_literature_review_node).
        """
        # Check if explicitly set in opts first to avoid unnecessary MCP
        # checks
        if opts.get("enable_literature_review_node") is False:
            # Literature review explicitly disabled, no need to check MCP
            return False, False, False

        # Check system availability (cached per instance)
        mcp_available, pubmed_available = await self._check_cached_availability(
        )

        # Determine if literature review node should be included
        # user can override via opts, otherwise auto-detect based on MCP
        # availability
        enable_literature_review_node = opts.get(
            "enable_literature_review_node", mcp_available)

        if not mcp_available and enable_literature_review_node:
            logger.warning("Literature review node requested but MCP server"
                           " unavailable - disabling")
            enable_literature_review_node = False

        return mcp_available, pubmed_available, enable_literature_review_node

    async def _prepare_generation(
        self,
        research_goal: str,
        progress_callback: None |
        (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
        opts: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> WorkflowState:
        """Prepare generation: set up state, check MCP, build graph.

        Returns:
            The prepared initial workflow state (including "start_time" and
            "run_id" keys).
        """
        start_time, run_id = _resolve_run_identity(run_id)

        # Extract optional fields from opts
        opts = opts or {}
        user_inputs = opts.get("user_inputs") or {}

        # Determine literature review node / MCP availability, then whether
        # tool-calling generation can run (it requires both).
        (mcp_available, pubmed_available, enable_literature_review_node) = (
            await self._resolve_literature_review_settings(opts))
        enable_tool_calling_generation = _resolve_tool_calling_generation(
            opts, mcp_available, enable_literature_review_node)

        # This flag is threaded through to initial_state below and the
        # consuming nodes branch on it directly.
        dev_test_lit_tools_isolation = _resolve_dev_isolation_flag(opts)

        # Build graph if not already built, or rebuild if literature review
        # setting changed
        self._ensure_graph_built(enable_literature_review_node)

        return self._build_initial_state(
            research_goal=research_goal,
            start_time=start_time,
            run_id=run_id,
            progress_callback=progress_callback,
            opts=opts,
            user_inputs=user_inputs,
            mcp_available=mcp_available,
            pubmed_available=pubmed_available,
            enable_tool_calling_generation=enable_tool_calling_generation,
            dev_test_lit_tools_isolation=dev_test_lit_tools_isolation,
        )

    def _initial_config_fields(self) -> dict[str, Any]:
        """Builds the generator-config fragment of the initial state.

        Returns:
            State fields sourced from the generator's own configuration
            (model names, iteration/count knobs, and the tool registry).
        """
        return {
            "model_name":
                self.model_name,
            "supervisor_model_name":
                self.supervisor_model_name,
            "max_iterations":
                self.max_iterations,
            "initial_hypotheses_count":
                self.initial_hypotheses_count,
            "evolution_max_count":
                self.evolution_max_count,
            "tournament_pairs":
                self.tournament_pairs,
            "literature_review_papers_count":
                self.literature_review_papers_count,
            # Tool registry for config-driven tool selection
            "tool_registry":
                self._tool_registry,
        }

    def _initial_runtime_fields(self) -> dict[str, Any]:
        """Builds the empty runtime-state fragment of the initial state.

        Returns:
            State fields that track workflow progress and results, all
            starting at their empty/zero values.
        """
        return {
            "hypotheses": [],
            "current_iteration": 0,
            "supervisor_guidance": {},
            "meta_review": {},
            "research_overview": None,
            "removed_duplicates": [],
            "tournament_matchups": [],
            "evolution_details": [],
            "metrics": ExecutionMetrics(),
            "messages": [],
        }

    def _initial_run_identity_fields(
        self,
        *,
        research_goal: str,
        start_time: float,
        run_id: str,
        progress_callback: None |
        (Callable[[str, dict[str, Any]], Awaitable[None]]),
        mcp_available: bool,
        pubmed_available: bool,
        enable_tool_calling_generation: bool,
        dev_test_lit_tools_isolation: bool,
    ) -> dict[str, Any]:
        """Builds the run-identity/system-availability state fragment.

        Args:
            research_goal: The research question or goal.
            start_time: Wall-clock start time (``time.time()``) for the run.
            run_id: Unique identifier for this run.
            progress_callback: Async callback for progress updates.
            mcp_available: Whether the MCP server is available.
            pubmed_available: Whether PubMed is available via MCP.
            enable_tool_calling_generation: Whether tool-calling generation
                is enabled for this run.
            dev_test_lit_tools_isolation: Whether dev lit-tools isolation
                mode is enabled for this run.

        Returns:
            State fields identifying this run and the system capabilities
            available to it.
        """
        return {
            "research_goal": research_goal,
            "start_time": start_time,
            "run_id": run_id,
            "progress_callback": progress_callback,
            # System availability flags
            "mcp_available": mcp_available,
            "pubmed_available": pubmed_available,
            "enable_tool_calling_generation": enable_tool_calling_generation,
            "dev_test_lit_tools_isolation": dev_test_lit_tools_isolation,
        }

    def _initial_user_and_literature_fields(
        self,
        *,
        opts: dict[str, Any],
        user_inputs: dict[str, Any],
    ) -> dict[str, Any]:
        """Builds the user-input and literature-review-output fragment.

        Args:
            opts: Caller-supplied generation options.
            user_inputs: The ``user_inputs`` sub-dict of opts.

        Returns:
            State fields for optional user preferences/inputs, plus the
            (initially empty) literature review outputs populated later by
            downstream nodes.
        """
        return {
            # Optional user preferences and inputs
            "preferences": opts.get("preferences"),
            "attributes": opts.get("attributes"),
            "constraints": opts.get("constraints"),
            "criteria": opts.get("criteria"),
            "run_focus_guidance": opts.get("run_focus_guidance"),
            "run_setup_guidance": opts.get("run_setup_guidance"),
            "starting_hypotheses": user_inputs.get("starting_hypotheses"),
            "literature": user_inputs.get("literature"),
            # Literature review outputs (populated by downstream nodes)
            "articles_with_reasoning": None,
            "literature_review_queries": None,
            "articles": None,
            "debate_transcripts": None,
            "context_enrichment_sources": None,
        }

    def _build_initial_state(
        self,
        *,
        research_goal: str,
        start_time: float,
        run_id: str,
        progress_callback: None |
        (Callable[[str, dict[str, Any]], Awaitable[None]]),
        opts: dict[str, Any],
        user_inputs: dict[str, Any],
        mcp_available: bool,
        pubmed_available: bool,
        enable_tool_calling_generation: bool,
        dev_test_lit_tools_isolation: bool,
    ) -> WorkflowState:
        """Assembles the initial workflow state dict for a generation run.

        Args:
            research_goal: The research question or goal.
            start_time: Wall-clock start time (``time.time()``) for the run.
            run_id: Unique identifier for this run.
            progress_callback: Async callback for progress updates.
            opts: Caller-supplied generation options.
            user_inputs: The ``user_inputs`` sub-dict of opts.
            mcp_available: Whether the MCP server is available.
            pubmed_available: Whether PubMed is available via MCP.
            enable_tool_calling_generation: Whether tool-calling generation
                is enabled for this run.
            dev_test_lit_tools_isolation: Whether dev lit-tools isolation
                mode is enabled for this run.

        Returns:
            The initial workflow state (including "start_time" and "run_id"
            keys).
        """
        identity_fields = self._initial_run_identity_fields(
            research_goal=research_goal,
            start_time=start_time,
            run_id=run_id,
            progress_callback=progress_callback,
            mcp_available=mcp_available,
            pubmed_available=pubmed_available,
            enable_tool_calling_generation=enable_tool_calling_generation,
            dev_test_lit_tools_isolation=dev_test_lit_tools_isolation,
        )
        user_and_literature_fields = self._initial_user_and_literature_fields(
            opts=opts, user_inputs=user_inputs)
        return cast(
            WorkflowState, {
                **self._initial_config_fields(),
                **self._initial_runtime_fields(),
                **identity_fields,
                **user_and_literature_fields,
            })

    # Two @overload stubs give type checkers a precise return type per
    # stream value; the un-decorated implementation below (with a union
    # return type) is what actually runs.
    @overload
    def generate_hypotheses(
        self,
        research_goal: str,
        progress_callback: None |
        (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
        opts: dict[str, Any] | None = None,
        run_id: str | None = None,
        stream: Literal[False] = False,
    ) -> Awaitable[dict[str, Any]]:
        ...

    @overload
    def generate_hypotheses(
        self,
        research_goal: str,
        progress_callback: None |
        (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
        opts: dict[str, Any] | None = None,
        run_id: str | None = None,
        stream: Literal[True] = True,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        ...

    def generate_hypotheses(
        self,
        research_goal: str,
        progress_callback: None |
        (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
        opts: dict[str, Any] | None = None,
        run_id: str | None = None,
        stream: bool = False,
    ) -> (Awaitable[dict[str, Any]] | AsyncIterator[tuple[str, dict[str, Any]]]
         ):
        """Generate hypotheses, with optional streaming.

        Args:
            research_goal: The research question or goal
            progress_callback: Async callback for progress updates
                             Called with (phase_name, data)
            opts: Optional dictionary with user preferences and inputs:
                - preferences: Desired approach or focus
                - attributes: Key qualities to prioritize
                - constraints: Requirements or boundaries
                - enable_literature_review_node: Whether to include literature
                review node (default: auto-detect MCP availability)
                - enable_tool_calling_generation: Enable tool-calling
                  generation where generate node queries literature tools
                  directly (requires enable_literature_review_node=True
                  + MCP server, default: False)
                - dev_test_lit_tools_isolation: Dev mode - force lit
                  review cache, all hypotheses to lit tools (default: False)
                - user_inputs: Dictionary with:
                  - starting_hypotheses: User-provided starting hypotheses
                  - literature: User-provided literature references
            run_id: Optional unique identifier for this run
                (generated if not provided)
            stream: If True, yields (node_name, state_dict) tuples.
                If False, returns final result dict.

        Returns:
            If stream=False: Coroutine that when awaited returns a
            dictionary with results:
            {
                "hypotheses": [...],
                "meta_review": {...},
                "execution_time": 0.0,
                "metrics": {...}
            }

            If stream=True: AsyncIterator yielding (node_name, state_dict)
            tuples

        Example:
            >>> # Non-streaming
            >>> result = await generator.generate_hypotheses(
            ...     research_goal="...", stream=False)
            >>>
            >>> # Streaming
            >>> async for node_name, state in generator.generate_hypotheses(
            ...         research_goal="...", stream=True):
            >>>     print(f"Completed {node_name}")
        """
        if stream:
            # Streaming path: return async generator directly
            return self._generate_hypotheses_with_streaming(
                research_goal=research_goal,
                progress_callback=progress_callback,
                opts=opts,
                run_id=run_id,
            )
        else:
            # Non-streaming path: return coroutine to be awaited
            return self._generate_hypotheses_without_streaming(
                research_goal=research_goal,
                progress_callback=progress_callback,
                opts=opts,
                run_id=run_id,
            )

    async def _generate_hypotheses_without_streaming(
        self,
        research_goal: str,
        progress_callback: None |
        (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
        opts: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Internal method to handle non-streaming generation.

        Returns final result dictionary.
        """
        # Prepare generation (shared setup logic)
        initial_state = await self._prepare_generation(
            research_goal=research_goal,
            progress_callback=progress_callback,
            opts=opts,
            run_id=run_id,
        )
        start_time = initial_state["start_time"]

        assert self._graph is not None  # built by _prepare_generation
        try:
            # Run the workflow. Uses 100 recursion limit to support higher max
            # iterations.
            final_state = await self._graph.ainvoke(
                initial_state, config={"recursion_limit": 100})

            # Format result to match expected interface
            execution_time = time.time() - start_time

            return _build_generation_result(cast(WorkflowState, final_state),
                                            execution_time)

        except Exception as e:
            logger.error("Hypothesis generation failed: %s", e, exc_info=True)
            raise

    async def _generate_hypotheses_with_streaming(
        self,
        research_goal: str,
        progress_callback: None |
        (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
        opts: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Internal method to handle streaming generation.

        Yields (node_name, state_dict) tuples after each node completes.
        """
        # Prepare generation (shared setup logic)
        initial_state = await self._prepare_generation(
            research_goal=research_goal,
            progress_callback=progress_callback,
            opts=opts,
            run_id=run_id,
        )

        # Delegate to streaming implementation
        async for node_name, state_dict in self._handle_streaming(
            initial_state):
            yield node_name, state_dict

    async def _handle_streaming(
        self,
        initial_state: WorkflowState,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Internal method to handle streaming generation.

        Args:
            initial_state: Prepared workflow state

        Yields:
            Tuple of (node_name, state_dict) after each node completes
        """
        assert self._graph is not None  # built by _prepare_generation
        try:
            # Maintain cumulative state across nodes
            # LangGraph's astream only yields fields updated by each node, not
            # full state
            # Seeds every field a caller might read before its node has run
            # yet. "research_plan" is not in _STREAMED_STATE_KEYS because it
            # is derived from supervisor_guidance below rather than copied
            # directly.
            cumulative_state: dict[str, Any] = {
                "hypotheses": [],
                "meta_review": {},
                "research_overview": {},
                "research_plan": {},
                "tournament_matchups": [],
                "evolution_details": [],
                "current_iteration": 0,
                "metrics": ExecutionMetrics(),
                "articles_with_reasoning": None,
                "literature_review_queries": [],
                "articles": [],
                "debate_transcripts": None,
            }

            # Stream the workflow execution
            async for chunk in self._graph.astream(
                initial_state, config={"recursion_limit": 100}):
                # Chunk is a dict with node names as keys
                for node_name, node_state in chunk.items():
                    logger.debug("streaming node: %s", node_name)

                    _merge_node_state_into_cumulative(cumulative_state,
                                                      node_state)

                    # Yield the node name and CUMULATIVE state
                    state_dict = _build_stream_state_dict(cumulative_state)

                    logger.debug("yielding state for node: %s", node_name)

                    yield node_name, state_dict

        except Exception as e:
            logger.error("Hypothesis generation streaming failed: %s",
                         e,
                         exc_info=True)
            raise


# Export for backwards compatibility
__all__ = ["HypothesisGenerator"]
