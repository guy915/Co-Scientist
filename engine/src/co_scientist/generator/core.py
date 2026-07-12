"""The ``HypothesisGenerator`` class, the package's public entry point.

Wraps the LangGraph workflow behind an async interface: it lazily compiles
the graph (topology in ``graph``), resolves MCP availability (mixin in
``availability``), prepares each run's initial state (``run_setup`` and
``initial_state``), and executes the workflow in either non-streaming or
streaming mode (stream shaping in ``streaming``).
"""

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Literal, cast, overload

from langgraph.graph import StateGraph

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
from co_scientist.generator.initial_state import _build_initial_state
from co_scientist.generator.run_setup import (
    _build_tool_registry,
    _configure_cache_env,
    _resolve_dev_isolation_flag,
    _resolve_run_identity,
    _resolve_tool_calling_generation,
)
from co_scientist.generator.streaming import (
    _build_generation_result,
    _build_stream_state_dict,
    _initial_cumulative_stream_state,
    _merge_node_state_into_cumulative,
    cumulative_stream_state_from,
)
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


class HypothesisGenerator(McpAvailabilityMixin):
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
        budget: dict[str, Any] | None = None,
    ):
        """Initialize the hypothesis generator.

        Args:
            model_name: LLM model to use (litellm format)
            supervisor_model_name: Model for the supervisor and meta-review
                steps (None = use model_name)
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
            budget: Optional serialized ``scheduling.Budget`` (keys
                ``max_iterations``/``max_llm_calls``/``max_tasks``/
                ``max_wall_clock_s``) giving the adaptive scheduler hard
                termination ceilings beyond ``max_iterations``. None derives a
                budget from ``max_iterations`` alone.
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
        # The scheduler always sees max_iterations; merge it into an explicit
        # budget so a run configured with only max_iterations still terminates.
        self.budget = {"max_iterations": max_iterations, **(budget or {})}

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

        # Extract optional fields from opts
        opts = opts or {}
        user_inputs = opts.get("user_inputs") or {}

        # Determine literature review node / MCP availability, then whether
        # tool-calling generation can run (it requires both).
        (
            mcp_available,
            pubmed_available,
            enable_literature_review_node,
        ) = await self._resolve_literature_review_settings(opts)
        enable_tool_calling_generation = _resolve_tool_calling_generation(
            opts, mcp_available, enable_literature_review_node
        )

        # This flag is threaded through to the initial state below and the
        # consuming nodes branch on it directly.
        dev_test_lit_tools_isolation = _resolve_dev_isolation_flag(opts)

        # Build graph if not already built, or rebuild if literature review
        # setting changed
        self._ensure_graph_built(enable_literature_review_node)

        return _build_initial_state(
            config_fields=self._initial_config_fields(),
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
            "model_name": self.model_name,
            "supervisor_model_name": self.supervisor_model_name,
            "max_iterations": self.max_iterations,
            "initial_hypotheses_count": self.initial_hypotheses_count,
            "evolution_max_count": self.evolution_max_count,
            "tournament_pairs": self.tournament_pairs,
            "literature_review_papers_count": (
                self.literature_review_papers_count
            ),
            # Adaptive-scheduler compute budget (Milestone 2).
            "budget": self.budget,
            # Tool registry for config-driven tool selection
            "tool_registry": self._tool_registry,
        }

    # Two @overload stubs give type checkers a precise return type per
    # stream value; the un-decorated implementation below (with a union
    # return type) is what actually runs.
    @overload
    def generate_hypotheses(
        self,
        research_goal: str,
        progress_callback: None
        | (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
        opts: dict[str, Any] | None = None,
        run_id: str | None = None,
        stream: Literal[False] = False,
        checkpoint_callback: None
        | (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
    ) -> Awaitable[dict[str, Any]]: ...

    @overload
    def generate_hypotheses(
        self,
        research_goal: str,
        progress_callback: None
        | (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
        opts: dict[str, Any] | None = None,
        run_id: str | None = None,
        stream: Literal[True] = True,
        checkpoint_callback: None
        | (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]: ...

    def generate_hypotheses(
        self,
        research_goal: str,
        progress_callback: None
        | (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
        opts: dict[str, Any] | None = None,
        run_id: str | None = None,
        stream: bool = False,
        checkpoint_callback: None
        | (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
    ) -> Awaitable[dict[str, Any]] | AsyncIterator[tuple[str, dict[str, Any]]]:
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
            checkpoint_callback: Optional async hook invoked with
                ``(node_name, full_state)`` after each node in streaming mode,
                for persisting a resumable checkpoint. Ignored when
                ``stream`` is False.

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
                checkpoint_callback=checkpoint_callback,
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
        progress_callback: None
        | (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
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
                initial_state, config={"recursion_limit": 100}
            )

            # Format result to match expected interface
            execution_time = time.time() - start_time

            return _build_generation_result(
                cast(WorkflowState, final_state), execution_time
            )

        except Exception as e:
            logger.error("Hypothesis generation failed: %s", e, exc_info=True)
            raise

    async def _generate_hypotheses_with_streaming(
        self,
        research_goal: str,
        progress_callback: None
        | (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
        opts: dict[str, Any] | None = None,
        run_id: str | None = None,
        checkpoint_callback: None
        | (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
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
            initial_state, checkpoint_callback=checkpoint_callback
        ):
            yield node_name, state_dict

    async def _handle_streaming(
        self,
        initial_state: WorkflowState,
        cumulative_seed: dict[str, Any] | None = None,
        checkpoint_callback: None
        | (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Internal method to handle streaming generation.

        Args:
            initial_state: Prepared workflow state
            cumulative_seed: Optional pre-seeded cumulative state (used on
                resume so streamed snapshots reflect the restored pool).
            checkpoint_callback: Optional async hook invoked with
                ``(node_name, full_state)`` after each node completes and
                *before* that node's event is yielded, so a durable checkpoint
                exists before the caller observes (and persists an event for)
                the node. ``full_state`` is the complete post-node
                ``WorkflowState`` (Milestone 4 resume boundary).

        Yields:
            Tuple of (node_name, state_dict) after each node completes
        """
        assert self._graph is not None  # built by _prepare_generation
        # Maintain cumulative state across nodes
        cumulative_state = (
            cumulative_seed
            if cumulative_seed is not None
            else _initial_cumulative_stream_state()
        )

        if checkpoint_callback is None:
            async for item in self._stream_updates_only(
                initial_state, cumulative_state
            ):
                yield item
            return

        async for item in self._stream_with_checkpoints(
            initial_state, cumulative_state, checkpoint_callback
        ):
            yield item

    async def _stream_updates_only(
        self,
        initial_state: WorkflowState,
        cumulative_state: dict[str, Any],
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Stream node updates without checkpointing (the default path)."""
        assert self._graph is not None
        try:
            async for chunk in self._graph.astream(
                initial_state, config={"recursion_limit": 100}
            ):
                # Chunk is a dict with node names as keys
                for node_name, node_state in chunk.items():
                    logger.debug("streaming node: %s", node_name)
                    _merge_node_state_into_cumulative(
                        cumulative_state, node_state
                    )
                    state_dict = _build_stream_state_dict(cumulative_state)
                    logger.debug("yielding state for node: %s", node_name)
                    yield node_name, state_dict
        except Exception as e:
            logger.error(
                "Hypothesis generation streaming failed: %s", e, exc_info=True
            )
            raise

    async def _stream_with_checkpoints(
        self,
        initial_state: WorkflowState,
        cumulative_state: dict[str, Any],
        checkpoint_callback: Callable[
            [str, dict[str, Any]], Awaitable[None]
        ],
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Stream node updates, checkpointing the full state before each yield.

        Streams in ``["updates", "values"]`` mode so each super-step yields
        both the node's incremental update (for the caller-facing snapshot,
        built exactly as the default path does) and the full post-node
        ``WorkflowState`` (for the checkpoint). LangGraph emits the ``updates``
        item first, then the ``values`` item for the same step, so the full
        state is checkpointed — before the node's event is yielded — once the
        matching values item arrives.
        """
        assert self._graph is not None
        pending: list[tuple[str, dict[str, Any]]] = []
        try:
            async for mode, data in self._graph.astream(
                initial_state,
                stream_mode=["updates", "values"],
                config={"recursion_limit": 100},
            ):
                if mode == "updates":
                    updates: dict[str, Any] = cast(dict[str, Any], data)
                    for node_name, node_state in updates.items():
                        logger.debug("streaming node: %s", node_name)
                        _merge_node_state_into_cumulative(
                            cumulative_state, node_state
                        )
                        pending.append(
                            (
                                node_name,
                                _build_stream_state_dict(cumulative_state),
                            )
                        )
                    continue
                # mode == "values": the full post-super-step WorkflowState.
                if not pending:
                    # The initial values item (before any node) has no
                    # pending node; nothing to checkpoint or yield yet.
                    continue
                full_state: dict[str, Any] = cast(dict[str, Any], data)
                await checkpoint_callback(pending[-1][0], full_state)
                for node_name, state_dict in pending:
                    logger.debug("yielding state for node: %s", node_name)
                    yield node_name, state_dict
                pending = []
        except Exception as e:
            logger.error(
                "Hypothesis generation streaming failed: %s", e, exc_info=True
            )
            raise

    async def resume_hypotheses(
        self,
        restored_state: dict[str, Any],
        progress_callback: None
        | (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
        opts: dict[str, Any] | None = None,
        checkpoint_callback: None
        | (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Resume a checkpoint-restored run, streaming remaining node outputs.

        The restored state carries ``resume=True`` (from
        ``checkpoint.restore_workflow_state``), so the graph re-enters at the
        orchestrator loop point and continues without re-running completed
        nodes. The streamed cumulative state is seeded from the restored pool
        so snapshots reflect work already done (Milestone 4).

        Args:
            restored_state: A ``WorkflowState`` restored from a checkpoint.
            progress_callback: Live progress callback to re-inject.
            opts: Generation options (used to resolve the graph shape, e.g.
                literature-review availability).
            checkpoint_callback: Optional async hook invoked with
                ``(node_name, full_state)`` after each remaining node, so a
                re-interrupted resume stays recoverable.

        Yields:
            Tuple of (node_name, state_dict) after each remaining node.
        """
        opts = opts or {}
        (
            _mcp_available,
            _pubmed_available,
            enable_literature_review_node,
        ) = await self._resolve_literature_review_settings(opts)
        self._ensure_graph_built(enable_literature_review_node)

        restored_state["progress_callback"] = progress_callback
        restored_state["tool_registry"] = self._tool_registry
        restored_state["resume"] = True

        cumulative_seed = cumulative_stream_state_from(restored_state)
        async for node_name, state_dict in self._handle_streaming(
            cast(WorkflowState, restored_state),
            cumulative_seed,
            checkpoint_callback=checkpoint_callback,
        ):
            yield node_name, state_dict
