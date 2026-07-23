"""The ``HypothesisGenerator`` class, the package's public entry point.

Wraps the LangGraph workflow behind an async interface: it lazily compiles
the graph (topology in ``graph``), resolves MCP availability (mixin in
``availability``), prepares each run's initial state (``run_setup`` and
``initial_state``), and executes the workflow in either non-streaming or
streaming mode (streaming/resume execution is the mixin in
``run_execution``; stream shaping in ``streaming``).
"""

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Literal, cast, overload

from langgraph.graph import StateGraph

from co_scientist.cache import scoped_cache_override
from co_scientist.constants import (
    DEFAULT_EVOLUTION_MAX_COUNT,
    DEFAULT_INITIAL_HYPOTHESES_COUNT,
    DEFAULT_MAX_ITERATIONS,
)
from co_scientist.generator.availability import McpAvailabilityMixin
from co_scientist.generator.graph import (
    CompiledWorkflow,
    _add_workflow_edges,
    _add_workflow_nodes,
)
from co_scientist.generator.initial_state import (
    RunCallbacks,
    RunCapabilities,
    RunIdentity,
    _build_initial_state,
)
from co_scientist.generator.options import GeneratorOptions
from co_scientist.generator.run_execution import (
    _GRAPH_RECURSION_LIMIT,
    StreamExecutionMixin,
)
from co_scientist.generator.run_setup import (
    _build_tool_registry,
    _configure_cache_dir_env,
    _resolve_dev_isolation_flag,
    _resolve_run_identity,
    _resolve_tool_calling_generation,
)
from co_scientist.generator.streaming import _build_generation_result
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


class HypothesisGenerator(McpAvailabilityMixin, StreamExecutionMixin):
    """Async wrapper for hypothesis generation using LangGraph.

    Args:
        model_name: LLM model to use (litellm format).
        max_iterations: Number of refinement iterations.
        initial_hypotheses_count: Number of initial hypotheses.
        evolution_max_count: Number of top hypotheses to evolve.
        options: Advanced configuration beyond the four run-size knobs
            above -- the supervisor model, Elo/tournament/literature
            tuning, caching, tool configuration, and the scheduler budget.
            Every field is documented on ``GeneratorOptions`` and defaults
            to the generator's historical default; omit it entirely for the
            all-defaults behavior.

    ``generate_hypotheses`` and ``resume_hypotheses`` accept an ``opts``
    dict with user preferences and inputs:
        - preferences: Desired approach or focus.
        - attributes: Key qualities to prioritize.
        - constraints: Requirements or boundaries.
        - enable_literature_review_node: Whether to include the literature
          review node (default: auto-detect MCP availability).
        - enable_tool_calling_generation: Enable tool-calling generation
          where the generate node queries literature tools directly
          (requires enable_literature_review_node=True + MCP server,
          default: False).
        - dev_test_lit_tools_isolation: Dev mode - force lit review cache,
          all hypotheses to lit tools (default: False).
        - user_inputs: Dictionary with ``starting_hypotheses``
          (user-provided starting hypotheses) and ``literature``
          (user-provided literature references).

    Non-streaming runs resolve to a result dict with ``hypotheses``,
    ``meta_review``, ``execution_time``, and ``metrics`` keys.

    Example:
        >>> generator = HypothesisGenerator(
        ...     model_name="deepseek/deepseek-v4-flash",
        ...     max_iterations=1,
        ...     initial_hypotheses_count=5,
        ...     evolution_max_count=3
        ... )
        >>> result = await generator.generate_hypotheses(
        ...     research_goal="Cure cancer",
        ...     callbacks=RunCallbacks(progress=my_callback),
        ... )
    """

    def __init__(
        self,
        model_name: str = "deepseek/deepseek-v4-flash",
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        initial_hypotheses_count: int = DEFAULT_INITIAL_HYPOTHESES_COUNT,
        evolution_max_count: int = DEFAULT_EVOLUTION_MAX_COUNT,
        options: GeneratorOptions | None = None,
    ):
        """Initialize the generator; parameters are documented on the class."""
        opts = options if options is not None else GeneratorOptions()
        # Constructor arguments become per-instance defaults that seed the
        # initial workflow state on every generate_hypotheses() call below.
        self._init_model_and_budget(
            model_name,
            opts.supervisor_model_name,
            max_iterations,
            opts.budget,
        )
        self._init_count_params(
            initial_hypotheses_count,
            evolution_max_count,
            opts.tournament_pairs,
            opts.elo_k_factor,
            opts.literature_review_papers_count,
        )
        self._init_cache_settings(opts.enable_cache, opts.cache_dir)
        # Bundled provider-neutral registry unless a custom config replaces
        # it (faithful runs must not silently collapse to a single source).
        self._tool_registry = _build_tool_registry(
            opts.tools_config, opts.disable_tools
        )
        self._graph: CompiledWorkflow | None = None  # built lazily
        self._mcp_available: bool | None = None
        self._pubmed_available: bool | None = None

    def _init_model_and_budget(
        self,
        model_name: str,
        supervisor_model_name: str | None,
        max_iterations: int,
        budget: dict[str, Any] | None,
    ) -> None:
        """Sets the model, iteration, and compute-budget attributes.

        Args:
            model_name: Worker-tier model, documented on the class.
            supervisor_model_name: Planning model, defaulting to model_name.
            max_iterations: Maximum refinement iterations for the run.
            budget: Extra adaptive-scheduler budget fields, if any.
        """
        self.model_name = model_name
        self.supervisor_model_name = supervisor_model_name or model_name
        self.max_iterations = max_iterations
        # The scheduler always sees max_iterations; merge it into an explicit
        # budget so a run configured with only max_iterations still terminates.
        self.budget = {"max_iterations": max_iterations, **(budget or {})}

    def _init_count_params(
        self,
        initial_hypotheses_count: int,
        evolution_max_count: int,
        tournament_pairs: int,
        elo_k_factor: int,
        literature_review_papers_count: int,
    ) -> None:
        """Sets the per-node count and Elo-tuning attributes.

        The counts are documented on the class; only ``elo_k_factor`` is
        validated here, since a non-positive step size makes the tournament
        ratings never move.

        Raises:
            ValueError: If ``elo_k_factor`` is not positive.
        """
        self.initial_hypotheses_count = initial_hypotheses_count
        self.evolution_max_count = evolution_max_count
        self.tournament_pairs = tournament_pairs
        if elo_k_factor <= 0:
            raise ValueError("elo_k_factor must be positive")
        self.elo_k_factor = elo_k_factor
        self.literature_review_papers_count = literature_review_papers_count

    def _init_cache_settings(
        self, enable_cache: bool | None, cache_dir: str | None
    ) -> None:
        """Sets the per-instance cache override and applies the cache-dir env.

        enable_cache is applied per-run (see _generate_hypotheses_* and
        resume_hypotheses) via cache.scoped_cache_override rather than here,
        so it never mutates process-global state. cache_dir has no such
        per-run mechanism (nothing passes it today); it still configures the
        process-wide default the way it always has.
        """
        self.enable_cache = enable_cache
        _configure_cache_dir_env(cache_dir)

    def _build_graph(
        self, enable_literature_review_node: bool = True
    ) -> CompiledWorkflow:
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
        _add_workflow_nodes(workflow, enable_literature_review_node)
        _add_workflow_edges(workflow, enable_literature_review_node)
        return workflow.compile()

    def _ensure_graph_built(self, enable_literature_review_node: bool) -> None:
        """Builds and caches self._graph on first call; a no-op afterward.

        Args:
            enable_literature_review_node: Whether the literature review node
                should be included if the graph is being built now.
        """
        if self._graph is None:
            self._graph = self._build_graph(
                enable_literature_review_node=enable_literature_review_node
            )

    async def _prepare_generation(
        self,
        research_goal: str,
        progress_callback: None
        | (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
        opts: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> WorkflowState:
        """Prepare generation: set up state, check MCP, build graph.

        Returns:
            The prepared initial workflow state (including "start_time" and
            "run_id" keys).
        """
        start_time, run_id = _resolve_run_identity(run_id)
        opts = opts or {}
        user_inputs = opts.get("user_inputs") or {}
        (
            capabilities,
            enable_literature_review_node,
        ) = await self._resolve_generation_settings(opts)
        # Build graph if not already built, or rebuild if the setting changed.
        self._ensure_graph_built(enable_literature_review_node)
        return _build_initial_state(
            config_fields=self._initial_config_fields(),
            identity=RunIdentity(
                research_goal=research_goal,
                start_time=start_time,
                run_id=run_id,
                progress_callback=progress_callback,
            ),
            capabilities=capabilities,
            opts=opts,
            user_inputs=user_inputs,
        )

    async def _resolve_generation_settings(
        self, opts: dict[str, Any]
    ) -> tuple[RunCapabilities, bool]:
        """Resolves literature-review/MCP/tool-calling/dev-isolation settings.

        Args:
            opts: Caller-supplied generation options.

        Returns:
            Tuple of (capabilities, enable_literature_review_node).
        """
        (
            mcp_available,
            pubmed_available,
            enable_literature_review_node,
        ) = await self._resolve_literature_review_settings(opts)
        capabilities = RunCapabilities(
            mcp_available=mcp_available,
            pubmed_available=pubmed_available,
            enable_tool_calling_generation=_resolve_tool_calling_generation(
                opts, mcp_available, enable_literature_review_node
            ),
            # This flag is threaded through to the initial state and the
            # consuming nodes branch on it directly.
            dev_test_lit_tools_isolation=_resolve_dev_isolation_flag(opts),
        )
        return capabilities, enable_literature_review_node

    def _initial_config_fields(self) -> dict[str, Any]:
        """Builds the generator-config fragment of the initial state.

        Returns:
            State fields sourced from the generator's own configuration
            (model names, iteration/count knobs, and the tool registry).
        """
        return {
            "model_name": self.model_name,
            "supervisor_model_name": self.supervisor_model_name,
            "max_iterations": self.max_iterations,
            "initial_hypotheses_count": self.initial_hypotheses_count,
            "evolution_max_count": self.evolution_max_count,
            "tournament_pairs": self.tournament_pairs,
            "elo_k_factor": self.elo_k_factor,
            "literature_review_papers_count": (
                self.literature_review_papers_count
            ),
            # Adaptive-scheduler compute budget (Milestone 2).
            "budget": self.budget,
            # Tool registry for config-driven tool selection
            "tool_registry": self._tool_registry,
        }

    @property
    def tool_registry(self) -> Any:
        """Return the configured registry for restored durable task state."""
        return self._tool_registry

    async def prepare_task_state(
        self,
        research_goal: str,
        *,
        progress_callback: None
        | (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
        opts: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> WorkflowState:
        """Prepare the initial state for node-level durable task execution."""
        return await self._prepare_generation(
            research_goal,
            progress_callback=progress_callback,
            opts=opts,
            run_id=run_id,
        )

    # Two @overload stubs give type checkers a precise return type per
    # stream value; the un-decorated implementation below (with a union
    # return type) is what actually runs.
    @overload
    def generate_hypotheses(
        self,
        research_goal: str,
        callbacks: RunCallbacks | None = None,
        opts: dict[str, Any] | None = None,
        run_id: str | None = None,
        stream: Literal[False] = False,
    ) -> Awaitable[dict[str, Any]]: ...

    @overload
    def generate_hypotheses(
        self,
        research_goal: str,
        callbacks: RunCallbacks | None = None,
        opts: dict[str, Any] | None = None,
        run_id: str | None = None,
        stream: Literal[True] = True,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]: ...

    def generate_hypotheses(
        self,
        research_goal: str,
        callbacks: RunCallbacks | None = None,
        opts: dict[str, Any] | None = None,
        run_id: str | None = None,
        stream: bool = False,
    ) -> Awaitable[dict[str, Any]] | AsyncIterator[tuple[str, dict[str, Any]]]:
        """Generate hypotheses, with optional streaming.

        Args:
            research_goal: The research question or goal.
            callbacks: Optional async progress/checkpoint hooks. The
                checkpoint hook runs only in streaming mode.
            opts: User preferences and inputs; keys in the class docstring.
            run_id: Unique identifier for this run (generated if omitted).
            stream: If True, return an async iterator yielding
                ``(node_name, state_dict)`` tuples; if False, return a
                coroutine resolving to the result dict (class docstring).
        """
        cb = callbacks or RunCallbacks()
        if stream:
            return self._generate_hypotheses_with_streaming(
                research_goal=research_goal,
                progress_callback=cb.progress,
                opts=opts,
                run_id=run_id,
                checkpoint_callback=cb.checkpoint,
            )
        return self._generate_hypotheses_without_streaming(
            research_goal=research_goal,
            progress_callback=cb.progress,
            opts=opts,
            run_id=run_id,
        )

    async def _generate_hypotheses_without_streaming(
        self,
        research_goal: str,
        progress_callback: None
        | (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
        opts: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Internal method to handle non-streaming generation.

        Returns final result dictionary.
        """
        with scoped_cache_override(self.enable_cache):
            # Prepare generation (shared setup logic)
            initial_state = await self._prepare_generation(
                research_goal=research_goal,
                progress_callback=progress_callback,
                opts=opts,
                run_id=run_id,
            )
            return await self._run_graph_to_completion(
                initial_state, initial_state["start_time"]
            )

    async def _run_graph_to_completion(
        self, initial_state: WorkflowState, start_time: float
    ) -> dict[str, Any]:
        """Invokes the compiled graph to completion and shapes the result.

        Args:
            initial_state: The prepared initial workflow state.
            start_time: Wall-clock start time (``time.time()``) for the run.

        Returns:
            The dictionary returned to callers of ``generate_hypotheses``
            when ``stream`` is False.
        """
        assert self._graph is not None  # built by _prepare_generation
        try:
            final_state = await self._graph.ainvoke(
                initial_state,
                config={"recursion_limit": _GRAPH_RECURSION_LIMIT},
            )
            execution_time = time.time() - start_time
            return _build_generation_result(
                cast(WorkflowState, final_state), execution_time
            )
        except Exception as e:
            logger.error("Hypothesis generation failed: %s", e, exc_info=True)
            raise
