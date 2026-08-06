"""Durable-path successors are read from the engine's route table.

The durable task path is the only path production runs, and every node
commit on it used to name its successor as a literal --
``"comprehensive_reflection"``, ``"ranking"``, ``"orchestrator"``, and a
verbatim re-implementation of the graph's MCP branch after ``generate``.
``co_scientist.task_runtime.next_task_type`` is what the in-process graph
routes on, and ``engine/tests/test_task_runtime.py`` pins that table
against the graph's topology -- so a re-route would have applied to the
engine's own routing and silently not to production, while a green suite
reported routing as verified.

These tests divert the route table and require the durable commits to
follow the diversion, so spelling a successor out on the app side again
fails rather than passing until it reaches a run.
"""

from typing import Any

import pytest

from app import (
    engine_tasks,
    engine_tasks_fanout_reflection,
    engine_tasks_ranking,
    store,
)
from app.engine_tasks_context import TaskCommit
from tests._engine_tasks_helpers import _seed_checkpoint, _task_state

# The nodes whose successor the durable path schedules itself, instead of
# taking the one ``execute_task_node`` hands back from the engine. Every
# one of them commits outside the graph: the four fan-out aggregates and
# the tournament finalizer.
_ROUTED_NODES = (
    "generate",
    "review",
    "comprehensive_reflection",
    "deep_verification",
    "ranking",
)

# A real graph node that is not the true successor of any node above, so
# scheduling it can only mean the diverted table was consulted.
_DIVERTED_TO = "proximity"


async def _schedule_successor(
    node: str, commit: TaskCommit, state: dict[str, Any]
) -> str:
    """Run the real durable commit helper that schedules ``node``'s successor.

    Args:
        node: Engine node being committed.
        commit: The leased task, its checkpoint sequence, and db path.
        state: Workflow state the commit checkpoints.

    Returns:
        The id of the successor task the commit enqueued.
    """
    if node == "ranking":
        result = await engine_tasks_ranking._commit_ranking_finalize(
            commit, state, {}
        )
        return str(result["successor_task_id"])
    advance = engine_tasks_fanout_reflection._checkpoint_and_advance
    _, successor_id = await advance(commit, state, node)
    return str(successor_id)


async def _commit_node(
    run_id: str, node: str, db_path: str, *, mcp_available: bool = False
) -> str:
    """Commit one durable node and return the task type it scheduled.

    Args:
        run_id: Run the node task belongs to.
        node: Engine node to commit.
        db_path: Per-test SQLite database.
        mcp_available: MCP availability the committed state carries, which
            is what the graph's post-``generate`` branch routes on.

    Returns:
        The durable task type of the enqueued successor.
    """
    state = _task_state(run_id)
    state["mcp_available"] = mcp_available
    checkpoint_seq = _seed_checkpoint(run_id, state, db_path=db_path)
    task = store.enqueue_task(
        store.NewTask(
            run_id=run_id,
            task_type=f"{engine_tasks.NODE_TASK_PREFIX}{node}",
            inputs={"checkpoint_seq": checkpoint_seq},
            idempotency_key=f"{node}:commit",
        ),
        db_path=db_path,
    )
    successor_id = await _schedule_successor(
        node, TaskCommit(task, checkpoint_seq, db_path), state
    )
    successor = store.get_task(successor_id, db_path=db_path)
    assert successor is not None
    return successor.task_type


@pytest.mark.asyncio
@pytest.mark.parametrize("node", _ROUTED_NODES)
async def test_durable_successor_matches_the_engine_route_table(
    isolated_db: str, node: str
) -> None:
    """Each durable commit schedules exactly what the route table names.

    The expectation is read from the table rather than written out, so it
    tracks a re-route instead of pinning today's topology in place.
    """
    from co_scientist.task_runtime import next_task_type

    run = store.create_run("Durable routing", "standard", "engine", {})
    scheduled = await _commit_node(run.id, node, isolated_db)
    expected = next_task_type(node, {"mcp_available": False})
    assert scheduled == f"{engine_tasks.NODE_TASK_PREFIX}{expected}"


@pytest.mark.asyncio
@pytest.mark.parametrize("node", _ROUTED_NODES)
async def test_durable_successor_follows_a_rerouted_graph(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch, node: str
) -> None:
    """A graph re-route reaches production, not just the engine's routing."""
    import co_scientist.task_runtime as task_runtime

    monkeypatch.setitem(task_runtime._NEXT_TASK_ROUTES, node, _DIVERTED_TO)
    run = store.create_run("Durable routing", "standard", "engine", {})
    scheduled = await _commit_node(run.id, node, isolated_db)
    assert scheduled == f"{engine_tasks.NODE_TASK_PREFIX}{_DIVERTED_TO}"


def _inverted_generate_route(state: Any) -> str:
    """``generate``'s MCP branch, re-routed to the opposite successor."""
    return "review" if state.get("mcp_available") else "reflection"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mcp_available", "expected"),
    [(True, "review"), (False, "reflection")],
)
async def test_generate_mcp_branch_is_not_reimplemented(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    mcp_available: bool,
    expected: str,
) -> None:
    """The branch after ``generate`` is the table's resolver, not a copy.

    ``_route_after_generate`` is a state-dependent route, and the durable
    path carried a verbatim re-implementation of it. Inverting the real
    resolver separates the two: anything still deriving the branch from
    ``mcp_available`` itself schedules the opposite of the live graph.
    """
    import co_scientist.task_runtime as task_runtime

    monkeypatch.setitem(
        task_runtime._NEXT_TASK_ROUTES, "generate", _inverted_generate_route
    )
    run = store.create_run("Durable routing", "standard", "engine", {})
    scheduled = await _commit_node(
        run.id, "generate", isolated_db, mcp_available=mcp_available
    )
    assert scheduled == f"{engine_tasks.NODE_TASK_PREFIX}{expected}"
