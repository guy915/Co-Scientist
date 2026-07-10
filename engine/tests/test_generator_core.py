"""Tests for HypothesisGenerator's run paths: streaming and non-streaming.

``tests/test_generator.py`` covers construction, graph compilation, and
``_prepare_generation`` in isolation. This file drives the two full run
paths -- ``generate_hypotheses(stream=False)`` and
``generate_hypotheses(stream=True)`` -- against a fake compiled graph
installed on ``gen._graph`` before the call, so ``_ensure_graph_built``
reuses it instead of compiling (and running) the real node graph. Every
call passes ``enable_literature_review_node=False`` so ``_prepare_generation``
skips the MCP availability probes entirely (see
``test_explicit_disable_skips_mcp_probe`` in ``test_generator.py`` for the
same technique).
"""

import inspect
from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

import pytest

from co_scientist.generator import HypothesisGenerator
from co_scientist.models import ExecutionMetrics
from co_scientist.state import WorkflowState
from tests._state import make_hypothesis, make_state

_NO_LIT_REVIEW: dict[str, Any] = {"enable_literature_review_node": False}


class _FakeCompiledGraph:
    """Stub compiled workflow graph for exercising the generator's run paths.

    Supports both ``ainvoke`` (non-streaming) and ``astream`` (streaming)
    with canned responses, plus optional errors to exercise the generator's
    exception-propagation branches.
    """

    def __init__(
        self,
        *,
        final_state: WorkflowState | None = None,
        invoke_error: Exception | None = None,
        chunks: Sequence[dict[str, dict[str, Any]]] = (),
        stream_error: Exception | None = None,
    ) -> None:
        """Configures the stub's canned ``ainvoke``/``astream`` behavior.

        Args:
            final_state: The state ``ainvoke`` returns, when not erroring.
            invoke_error: If set, ``ainvoke`` raises this instead of
                returning ``final_state``.
            chunks: The sequence of ``{node_name: node_state}`` dicts that
                ``astream`` yields, in order.
            stream_error: If set, raised after all ``chunks`` are yielded.
        """
        self._final_state = final_state
        self._invoke_error = invoke_error
        self._chunks = chunks
        self._stream_error = stream_error

    async def ainvoke(
        self, state: WorkflowState, config: dict[str, int]
    ) -> WorkflowState:
        """Returns the configured final state, or raises ``invoke_error``."""
        if self._invoke_error is not None:
            raise self._invoke_error
        assert self._final_state is not None
        return self._final_state

    async def astream(
        self, state: WorkflowState, config: dict[str, int]
    ) -> AsyncIterator[dict[str, dict[str, Any]]]:
        """Yields the configured chunks, then raises ``stream_error`` if set."""
        for chunk in self._chunks:
            yield chunk
        if self._stream_error is not None:
            raise self._stream_error


def _install_fake_graph(
    gen: HypothesisGenerator, graph: _FakeCompiledGraph
) -> None:
    """Pre-installs a fake compiled graph so ``_ensure_graph_built`` no-ops.

    Args:
        gen: The generator under test.
        graph: The fake graph to install in place of a real compiled one.
    """
    gen._graph = cast(Any, graph)


# --- generate_hypotheses(stream=False) --------------------------------------


async def test_stream_false_returns_coroutine_that_resolves_to_result() -> None:
    """stream=False returns an awaitable resolving to the shaped result."""
    gen = HypothesisGenerator()
    final_state = make_state(
        hypotheses=[make_hypothesis("Final hypothesis")],
        metrics=ExecutionMetrics(hypothesis_count=1, llm_calls=3),
        meta_review={"summary": "done"},
    )
    _install_fake_graph(gen, _FakeCompiledGraph(final_state=final_state))

    coro = gen.generate_hypotheses("goal", opts=_NO_LIT_REVIEW, stream=False)
    assert inspect.iscoroutine(coro)

    result = await coro
    assert len(result["hypotheses"]) == 1
    assert result["hypotheses"][0]["text"] == "Final hypothesis"
    assert result["meta_review"] == {"summary": "done"}
    assert result["metrics"]["llm_calls"] == 3
    assert result["execution_time"] >= 0.0


async def test_non_streaming_propagates_graph_errors() -> None:
    """A graph.ainvoke failure propagates unchanged to the caller."""
    gen = HypothesisGenerator()
    boom = RuntimeError("ainvoke exploded")
    _install_fake_graph(gen, _FakeCompiledGraph(invoke_error=boom))

    with pytest.raises(RuntimeError, match="ainvoke exploded"):
        await gen.generate_hypotheses("goal", opts=_NO_LIT_REVIEW, stream=False)


# --- generate_hypotheses(stream=True) ---------------------------------------


async def test_stream_true_returns_async_iterator_yielding_each_node() -> None:
    """stream=True returns an async iterator of (node_name, state) tuples."""
    gen = HypothesisGenerator()
    chunks: list[dict[str, dict[str, Any]]] = [
        {"supervisor": {"supervisor_guidance": {"plan": "p1"}}},
        {
            "generate": {
                "hypotheses": [make_hypothesis("streamed h")],
                "metrics": ExecutionMetrics(llm_calls=1),
            }
        },
    ]
    _install_fake_graph(gen, _FakeCompiledGraph(chunks=chunks))

    result = gen.generate_hypotheses("goal", opts=_NO_LIT_REVIEW, stream=True)
    assert not inspect.iscoroutine(result)
    assert hasattr(result, "__anext__")

    seen: list[tuple[str, dict[str, Any]]] = []
    async for node_name, state_dict in result:
        seen.append((node_name, state_dict))

    assert [name for name, _ in seen] == ["supervisor", "generate"]
    # After the second chunk, cumulative state reflects both updates.
    _, final_payload = seen[-1]
    assert final_payload["research_plan"] == {"plan": "p1"}
    assert final_payload["hypotheses"][0]["text"] == "streamed h"
    assert final_payload["metrics"]["llm_calls"] == 1


async def test_streaming_propagates_errors_raised_mid_stream() -> None:
    """A graph.astream failure after some chunks still propagates."""
    gen = HypothesisGenerator()
    boom = RuntimeError("astream exploded")
    chunks: list[dict[str, dict[str, Any]]] = [
        {"supervisor": {"supervisor_guidance": {"plan": "p1"}}}
    ]
    _install_fake_graph(
        gen, _FakeCompiledGraph(chunks=chunks, stream_error=boom)
    )

    seen: list[tuple[str, dict[str, Any]]] = []
    with pytest.raises(RuntimeError, match="astream exploded"):
        async for node_name, state_dict in gen.generate_hypotheses(
            "goal", opts=_NO_LIT_REVIEW, stream=True
        ):
            seen.append((node_name, state_dict))

    assert len(seen) == 1
