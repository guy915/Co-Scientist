"""Async hypothesis generation, graph configuration, streaming, and resume."""

import asyncio
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
from co_scientist.generator.run_setup import (
    _build_tool_registry,
    _configure_cache_dir_env,
    _resolve_dev_isolation_flag,
    _resolve_dev_mode_flag,
    _resolve_generation_strategy,
    _resolve_meta_review,
    _resolve_overview_review,
    _resolve_research_tier,
    _resolve_run_identity,
    _resolve_simulation_execution,
    _resolve_tool_calling_generation,
)
from co_scientist.generator.streaming import (
    _build_generation_result,
    _build_stream_state_dict,
    _initial_cumulative_stream_state,
    _merge_node_state_into_cumulative,
    cumulative_stream_state_from,
)
from co_scientist.llm import scoped_api_key
from co_scientist.models import (
    run_scoped_hypothesis_ids,
    run_seed_material,
)
from co_scientist.state import WorkflowState

logger = logging.getLogger(__name__)


_GRAPH_RECURSION_LIMIT = 100


def _decide_enable_literature_review(
    opts: dict[str, Any], mcp_available: bool
) -> bool:
    """Decides whether the literature review node should run this call."""
    enable_literature_review_node = opts.get(
        "enable_literature_review_node", mcp_available
    )
    if not mcp_available and enable_literature_review_node:
        logger.warning(
            "Literature review node requested but MCP server"
            " unavailable - disabling"
        )
        return False
    return cast(bool, enable_literature_review_node)


def _process_updates_chunk(
    cumulative_state: dict[str, Any],
    updates: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    """Merges an ``"updates"``-mode astream chunk into cumulative state."""
    pending: list[tuple[str, dict[str, Any]]] = []
    for node_name, node_state in updates.items():
        logger.debug("streaming node: %s", node_name)
        _merge_node_state_into_cumulative(cumulative_state, node_state)
        pending.append((node_name, _build_stream_state_dict(cumulative_state)))
    return pending


async def _drain_pending_with_checkpoint(
    pending: list[tuple[str, dict[str, Any]]],
    full_state: dict[str, Any],
    checkpoint_callback: Callable[[str, dict[str, Any]], Awaitable[None]],
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Checkpoints the full state, then yields each pending node's snapshot."""
    if not pending:
        return
    await checkpoint_callback(pending[-1][0], full_state)
    for node_name, state_dict in pending:
        logger.debug("yielding state for node: %s", node_name)
        yield node_name, state_dict


class HypothesisGenerator:
    """Async wrapper for hypothesis generation using LangGraph.

    Args:
        model_name: LLM model to use (litellm format).
        max_iterations: Number of refinement iterations.
        initial_hypotheses_count: Number of initial hypotheses.
        evolution_max_count: Number of top hypotheses to evolve.
        options: Advanced configuration beyond the four run-size knobs
            above -- the supervisor model, Elo/tournament/literature
            tuning, caching, tool configuration, the scheduler budget,
            and the bring-your-own-key provider credential
            (``GeneratorOptions.api_key``). Every field is documented on
            ``GeneratorOptions`` and defaults to the generator's
            historical default; omit it entirely for the all-defaults
            behavior.

    ``generate_hypotheses`` and ``resume_hypotheses`` accept an ``opts``
    dict with user preferences and inputs:
        - preferences: Desired approach or focus.
        - attributes: Key qualities to prioritize.
        - constraints: Requirements or boundaries.
        - enable_literature_review_node: Whether to include the literature
          review node (default: auto-detect MCP availability).
        - enable_tool_calling_generation: Tool-calling generation where
          the generate node's draft agent queries literature tools
          directly. Opt-in: pass True to request it. An omitted option
          is not a request, because the draft agent costs ~9 LLM calls
          per hypothesis per cycle. A request is still validated against
          availability (MCP server + enable_literature_review_node=True,
          and not the offline backend).
        - dev_test_lit_tools_isolation: Dev mode - force lit review cache,
          all hypotheses to lit tools (default: False).
        - dev_mode: Dev mode - read a far smaller number of papers in the
          literature review, overriding literature_review_papers_count
          (default: the COSCIENTIST_DEV_MODE env var).
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

    _graph: CompiledWorkflow | None
    _graph_shape: bool | None
    _mcp_available: bool | None
    _pubmed_available: bool | None

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
        if opts.elo_k_factor <= 0:
            raise ValueError("elo_k_factor must be positive")
        self.model_name = model_name
        self.supervisor_model_name = opts.supervisor_model_name or model_name
        self.max_iterations = max_iterations
        self.budget = {"max_iterations": max_iterations, **(opts.budget or {})}
        self.initial_hypotheses_count = initial_hypotheses_count
        self.evolution_max_count = evolution_max_count
        self.tournament_pairs = opts.tournament_pairs
        self.elo_k_factor = opts.elo_k_factor
        self.literature_review_papers_count = (
            opts.literature_review_papers_count
        )
        # Credentials stay outside checkpoint state; shared cache keys carry
        # no credential, so bring-your-own-key runs must bypass that cache.
        self.api_key = opts.api_key
        self.enable_cache = False if self.api_key else opts.enable_cache
        _configure_cache_dir_env(opts.cache_dir)
        # Bundled provider-neutral registry unless a custom config replaces
        # it (faithful runs must not silently collapse to a single source).
        self._tool_registry = _build_tool_registry(
            opts.tools_config, opts.disable_tools
        )
        # The graph and the availability answers start empty for the same
        # reason a configuration change clears them: both are built lazily
        # from the registry above, and both are rebuilt whenever the shape
        # they were compiled for stops matching. They are invalidated together.
        self.invalidate_configuration_caches()

    async def prepare_task_state(
        self,
        research_goal: str,
        *,
        progress_callback: None
        | (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
        opts: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> WorkflowState:
        """Prepare generation: set up state, check MCP, build graph."""
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
        """Resolve retrieval, execution, and development capabilities."""
        (
            mcp_available,
            pubmed_available,
            enable_literature_review_node,
        ) = await self._resolve_literature_review_settings(opts)
        # Resolved once here because the generation-strategy resolver needs
        # it: a tools-requiring forced strategy is refused when tool-calling
        # generation is off.
        enable_tool_calling = _resolve_tool_calling_generation(
            opts,
            mcp_available,
            enable_literature_review_node,
            self.model_name,
        )
        capabilities = RunCapabilities(
            mcp_available=mcp_available,
            pubmed_available=pubmed_available,
            enable_tool_calling_generation=enable_tool_calling,
            enable_simulation_execution=_resolve_simulation_execution(
                opts, self.model_name
            ),
            enable_overview_review=_resolve_overview_review(
                opts, self.supervisor_model_name
            ),
            research_tier=_resolve_research_tier(opts, mcp_available),
            enable_meta_review=_resolve_meta_review(opts),
            generation_strategy=_resolve_generation_strategy(
                opts, enable_tool_calling
            ),
            # These flags are threaded through to the initial state and the
            # consuming nodes branch on them directly.
            dev_test_lit_tools_isolation=_resolve_dev_isolation_flag(opts),
            dev_mode=_resolve_dev_mode_flag(opts),
        )
        return capabilities, enable_literature_review_node

    def _initial_config_fields(self) -> dict[str, Any]:
        """Builds the generator-config fragment of the initial state."""
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
        """Generate hypotheses, with optional streaming."""
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
        """Internal method to handle non-streaming generation."""
        with (
            scoped_cache_override(self.enable_cache),
            scoped_api_key(self.api_key),
        ):
            # Prepare generation (shared setup logic)
            initial_state = await self.prepare_task_state(
                research_goal=research_goal,
                progress_callback=progress_callback,
                opts=opts,
                run_id=run_id,
            )
            # Preparation mints no hypotheses, so seeding here rather than
            # inside it keeps the durable path (which prepares state and
            # then runs each node as its own task) on plain uuid4.
            with run_scoped_hypothesis_ids(
                run_seed_material(initial_state["run_id"], research_goal)
            ):
                return await self._run_graph_to_completion(
                    initial_state, initial_state["start_time"]
                )

    async def _run_graph_to_completion(
        self, initial_state: WorkflowState, start_time: float
    ) -> dict[str, Any]:
        """Invokes the compiled graph to completion and shapes the result."""
        assert self._graph is not None  # built by prepare_task_state
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

    async def _check_cached_availability(self) -> tuple[bool, bool]:
        """Lazily checks and caches MCP/PubMed availability for this call."""
        # The two flags are set together and never independently, so once
        # either is known both are.
        if (
            self._mcp_available is not None
            and self._pubmed_available is not None
        ):
            return self._mcp_available, self._pubmed_available

        from co_scientist.mcp_client import (
            check_literature_source_available,
            check_mcp_available,
        )

        # Probe concurrently: the checks are independent and each opens its own
        # MCP round trip.
        mcp_available, pubmed_available = await asyncio.gather(
            check_mcp_available(tool_registry=self._tool_registry),
            check_literature_source_available(
                tool_registry=self._tool_registry
            ),
        )
        self._mcp_available = mcp_available
        self._pubmed_available = pubmed_available
        return mcp_available, pubmed_available

    async def _resolve_literature_review_settings(
        self,
        opts: dict[str, Any],
    ) -> tuple[bool, bool, bool]:
        """Determines literature-review/MCP availability for this call."""
        # Check if explicitly set in opts first to avoid unnecessary MCP
        # checks
        if opts.get("enable_literature_review_node") is False:
            # Literature review explicitly disabled, no need to check MCP
            return False, False, False

        # Check system availability (cached per instance)
        (
            mcp_available,
            pubmed_available,
        ) = await self._check_cached_availability()

        enable_literature_review_node = _decide_enable_literature_review(
            opts, mcp_available
        )
        return mcp_available, pubmed_available, enable_literature_review_node

    def _build_graph(
        self, enable_literature_review_node: bool = True
    ) -> CompiledWorkflow:
        """Build the LangGraph workflow."""
        workflow = StateGraph(WorkflowState)
        _add_workflow_nodes(workflow, enable_literature_review_node)
        _add_workflow_edges(workflow, enable_literature_review_node)
        return cast(CompiledWorkflow, workflow.compile())

    def _ensure_graph_built(self, enable_literature_review_node: bool) -> None:
        """Compile the graph unless a graph for this shape is already held."""
        if self._graph is not None and self._graph_shape in (
            None,
            enable_literature_review_node,
        ):
            return
        self._graph = self._build_graph(
            enable_literature_review_node=enable_literature_review_node
        )
        self._graph_shape = enable_literature_review_node

    def invalidate_configuration_caches(self) -> None:
        """Drop every cached answer derived from the tool configuration."""
        self._graph = None
        self._graph_shape = None
        self._mcp_available = None
        self._pubmed_available = None

    def reload_tool_registry(
        self,
        tools_config: str | None = None,
        disable_tools: list[str] | None = None,
    ) -> None:
        """Rebuild the tool registry and invalidate what it decided."""
        from co_scientist.generator.run_setup import _build_tool_registry

        self._tool_registry = _build_tool_registry(tools_config, disable_tools)
        self.invalidate_configuration_caches()

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
        """Internal method to handle streaming generation."""
        with (
            scoped_cache_override(self.enable_cache),
            scoped_api_key(self.api_key),
        ):
            # Prepare generation (shared setup logic)
            initial_state = await self.prepare_task_state(
                research_goal=research_goal,
                progress_callback=progress_callback,
                opts=opts,
                run_id=run_id,
            )

            # Preparation mints no hypotheses, so seeding here rather than
            # inside it keeps the durable path (which prepares state and
            # then runs each node as its own task) on plain uuid4.
            with run_scoped_hypothesis_ids(
                run_seed_material(initial_state["run_id"], research_goal)
            ):
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
        """Internal method to handle streaming generation."""
        assert self._graph is not None  # built by prepare_task_state
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
                initial_state,
                config={"recursion_limit": _GRAPH_RECURSION_LIMIT},
            ):
                # Chunk is a dict with node names as keys -- the same shape
                # the checkpointed path's "updates" items carry.
                for node_name, state_dict in _process_updates_chunk(
                    cumulative_state, cast(dict[str, Any], chunk)
                ):
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
        checkpoint_callback: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Checkpoint the full state before yielding pending node updates."""
        assert self._graph is not None
        pending: list[tuple[str, dict[str, Any]]] = []
        try:
            async for mode, data in self._graph.astream(
                initial_state,
                stream_mode=["updates", "values"],
                config={"recursion_limit": _GRAPH_RECURSION_LIMIT},
            ):
                if mode == "updates":
                    pending.extend(
                        _process_updates_chunk(
                            cumulative_state, cast(dict[str, Any], data)
                        )
                    )
                    continue
                # mode == "values": the full post-super-step WorkflowState.
                async for item in _drain_pending_with_checkpoint(
                    pending, cast(dict[str, Any], data), checkpoint_callback
                ):
                    yield item
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
        """Resume a restored run and stream the remaining node outputs."""
        opts = opts or {}
        with (
            scoped_cache_override(self.enable_cache),
            scoped_api_key(self.api_key),
        ):
            restored_state = await self._prepare_resume(
                restored_state, progress_callback, opts
            )
            cumulative_seed = cumulative_stream_state_from(restored_state)
            async for node_name, state_dict in self._handle_streaming(
                cast(WorkflowState, restored_state),
                cumulative_seed,
                checkpoint_callback=checkpoint_callback,
            ):
                yield node_name, state_dict

    async def _prepare_resume(
        self,
        restored_state: dict[str, Any],
        progress_callback: None
        | (Callable[[str, dict[str, Any]], Awaitable[None]]),
        opts: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolves the graph shape and mutates restored_state for resuming."""
        (
            _mcp_available,
            _pubmed_available,
            enable_literature_review_node,
        ) = await self._resolve_literature_review_settings(opts)
        self._ensure_graph_built(enable_literature_review_node)

        restored_state["progress_callback"] = progress_callback
        restored_state["tool_registry"] = self._tool_registry
        restored_state["resume"] = True
        return restored_state
