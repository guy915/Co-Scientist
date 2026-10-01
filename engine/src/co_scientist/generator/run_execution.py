"""Streaming execution for the hypothesis generator.

Split out of ``core`` to keep that module focused on configuration and
graph preparation. ``HypothesisGenerator`` mixes in
``StreamExecutionMixin`` (exactly like ``availability``'s
``McpAvailabilityMixin``), so the methods here run with the attributes
its ``__init__`` assigns.
"""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast

from co_scientist.cache import scoped_cache_override
from co_scientist.generator.streaming import (
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

if TYPE_CHECKING:
    from co_scientist.generator.graph import CompiledWorkflow

logger = logging.getLogger(__name__)

# LangGraph super-step budget for one run: each node visit consumes a step,
# so higher max-iteration runs need headroom well above LangGraph's default
# of 25. Applied to every graph invocation (ainvoke and both astream paths).
_GRAPH_RECURSION_LIMIT = 100


def _process_updates_chunk(
    cumulative_state: dict[str, Any],
    updates: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    """Merges an ``"updates"``-mode astream chunk into cumulative state.

    Args:
        cumulative_state: Streaming state accumulated across nodes so far;
            updated in place.
        updates: The chunk's per-node incremental state updates.

    Returns:
        The (node_name, state_dict) pairs pending checkpoint and yield for
        this chunk.
    """
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
    """Checkpoints the full state, then yields each pending node's snapshot.

    A no-op when there is no pending node, e.g. the initial ``"values"``
    item astream emits before any node has run.

    Args:
        pending: The (node_name, state_dict) pairs accumulated since the
            last checkpoint.
        full_state: The full post-super-step ``WorkflowState`` to persist.
        checkpoint_callback: Async hook invoked with the last pending
            node's name and ``full_state`` before anything is yielded.

    Yields:
        Each pending (node_name, state_dict) pair, in order.
    """
    if not pending:
        return
    await checkpoint_callback(pending[-1][0], full_state)
    for node_name, state_dict in pending:
        logger.debug("yielding state for node: %s", node_name)
        yield node_name, state_dict


class StreamExecutionMixin:
    """Streaming/resume execution methods for ``HypothesisGenerator``.

    The declarations under ``TYPE_CHECKING`` below are provided at runtime
    by ``HypothesisGenerator`` (``generator.core``), which assigns the
    attributes in its ``__init__`` and defines the methods directly or via
    ``McpAvailabilityMixin``.
    """

    if TYPE_CHECKING:
        _graph: "CompiledWorkflow | None"
        enable_cache: bool | None
        api_key: str | None
        _tool_registry: Any

        async def _prepare_generation(
            self,
            research_goal: str,
            progress_callback: None
            | (Callable[[str, dict[str, Any]], Awaitable[None]]) = None,
            opts: dict[str, Any] | None = None,
            run_id: str | None = None,
        ) -> WorkflowState: ...

        async def _resolve_literature_review_settings(
            self,
            opts: dict[str, Any],
        ) -> tuple[bool, bool, bool]: ...

        def _ensure_graph_built(
            self, enable_literature_review_node: bool
        ) -> None: ...

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
        with (
            scoped_cache_override(self.enable_cache),
            scoped_api_key(self.api_key),
        ):
            # Prepare generation (shared setup logic)
            initial_state = await self._prepare_generation(
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
        """Internal method to handle streaming generation.

        Args:
            initial_state: Prepared workflow state
            cumulative_seed: Optional pre-seeded cumulative state (used on
                resume so streamed snapshots reflect the restored pool).
            checkpoint_callback: Optional async hook invoked with
                ``(node_name, full_state)`` after each node completes, for
                persisting a resumable checkpoint (Milestone 4).

        Yields:
            Tuple of (node_name, state_dict) after each node completes
        """
        assert self._graph is not None  # built by _prepare_generation
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
        """Stream node updates, checkpointing the full state before each yield.

        Streams in ``["updates", "values"]`` mode so each super-step yields
        both the node's incremental update (for the caller-facing snapshot)
        and the full post-node ``WorkflowState`` (for the checkpoint).
        LangGraph emits the ``updates`` item first, then ``values`` for the
        same step, so the full state is checkpointed once ``values`` arrives.
        """
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
        """Resume a checkpoint-restored run, streaming remaining node outputs.

        The restored state carries ``resume=True`` (from
        ``checkpoint.restore_workflow_state``), so the graph re-enters at the
        orchestrator loop point and continues without re-running completed
        nodes. The streamed cumulative state is seeded from the restored pool
        so snapshots reflect work already done (Milestone 4).

        Args:
            restored_state: A ``WorkflowState`` restored from a checkpoint.
            progress_callback: Live progress callback to re-inject.
            opts: Generation options (used to resolve the graph shape).
            checkpoint_callback: Optional async hook invoked with
                ``(node_name, full_state)`` after each remaining node, so a
                re-interrupted resume stays recoverable.

        Yields:
            Tuple of (node_name, state_dict) after each remaining node.
        """
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
        """Resolves the graph shape and mutates restored_state for resuming.

        Ensures the graph is built for this run's literature-review
        setting, re-injects the live progress callback and tool registry,
        and marks the state as a resume so the graph re-enters at the
        orchestrator.

        Args:
            restored_state: A ``WorkflowState`` restored from a checkpoint;
                mutated in place.
            progress_callback: Live progress callback to re-inject.
            opts: Generation options (used to resolve the graph shape).

        Returns:
            The mutated ``restored_state`` (same object, for convenience).
        """
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
