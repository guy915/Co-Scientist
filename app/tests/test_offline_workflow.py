"""Offline engine workflow: unified event vocabulary and artifact shape.

These tests drive the durable run path (the same node-level task executor a
real ``POST /start`` uses) pinned to the deterministic offline backend, then
read the persisted event log. They assert the unified engine event vocabulary,
the terminal lifecycle, and the shape of the deep-verification and
research-overview artifacts. The offline router's per-call determinism is
proven in the engine's own ``tests/test_offline_llm.py``; run-level artifact
determinism does *not* hold here (later prompts embed fresh per-hypothesis
identifiers), so it is not asserted.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app import store, task_worker


def _run_offline_workflow(
    goal: str, db_path: str
) -> tuple[str, list[dict[str, Any]]]:
    """Drive one express offline engine run and return (run_id, events).

    Delivers the run through the durable task queue and drains it with a
    bounded worker cohort (as the embedded API worker does), then returns the
    persisted event log so the vocabulary and ordering can be asserted.
    """
    run = store.create_run(
        goal,
        "express",
        "engine",
        {"tier": "express"},
        store.RunCreateOptions(llm_backend="offline", db_path=db_path),
    )
    task_worker.enqueue_run_workflow(run.id, db_path=db_path)
    asyncio.run(
        task_worker.run_run_worker_pool(
            run.id,
            "offline-workflow-test",
            policy=task_worker.WorkerPolicy(db_path=db_path),
        )
    )
    events = store.list_events(run.id, db_path=db_path)
    return run.id, events


def test_offline_workflow_emits_canonical_event_sequence(
    isolated_db: str,
) -> None:
    """The durable run emits the gate/stage vocabulary in graph order."""
    _run_id, events = _run_offline_workflow("Sequence test goal", isolated_db)
    types = [e["type"] for e in events]
    # Each durable node commit surfaces a ``scientific_task`` event naming the
    # node it completed; the graph stages are read from those, not from
    # per-node top-level event types (a streaming-path concept).
    nodes = [
        e["payload"].get("task")
        for e in events
        if e["type"] == "scientific_task"
    ]

    # The lifecycle gate/stage events the durable path emits at the boundaries.
    expected_gate_events = {
        "safety.intake",
        "safety.hypothesis",
        "citation.grounding",
        "citation_audit",
        "safety.final",
        "report",
    }
    assert expected_gate_events <= set(types), (
        f"missing gate events: {expected_gate_events - set(types)}"
    )

    # Every substantive graph node the engine runs appears as a completed
    # durable task.
    expected_nodes = {
        "supervisor",
        "generate",
        "review",
        "ranking",
        "evolve",
        "meta_review",
        "deep_verification",
        "proximity",
        "research_overview",
    }
    assert expected_nodes <= set(nodes), (
        f"missing nodes: {expected_nodes - set(nodes)}"
    )

    # Ordering the graph guarantees: intake gates first, planning precedes
    # generation, and the report is the last thing before the terminal status.
    assert types.index("safety.intake") == 0
    assert nodes.index("supervisor") < nodes.index("generate")
    assert types[-1] == "status"
    assert types.index("report") == len(types) - 2


def test_offline_workflow_completes_with_report(isolated_db: str) -> None:
    """A keyless offline run reaches completed and publishes a ranked report."""
    run_id, events = _run_offline_workflow("Completion test goal", isolated_db)

    assert events[-1]["type"] == "status"
    assert events[-1]["payload"].get("status") == "completed"

    final = store.get_run(run_id)
    assert final is not None
    assert final.status == store.RunStatus.COMPLETED.value

    hyps = store.list_hypotheses(run_id)
    assert hyps
    report = store.get_latest_report(run_id)
    assert report is not None
    assert report["payload"]["leaderboard"]
    assert report["payload"]["provider"] == "engine"


def test_offline_deep_verification_writes_reviews(isolated_db: str) -> None:
    """Deep verification runs as a durable node and attaches its review rows."""
    run_id, events = _run_offline_workflow(
        "Deep verification goal", isolated_db
    )

    nodes = [
        e["payload"].get("task")
        for e in events
        if e["type"] == "scientific_task"
    ]
    assert "deep_verification" in nodes

    # The reviews table carries deep_verification-authored rows for the probed
    # hypotheses, alongside the standard review pass.
    reviews = store.list_reviews(run_id, db_path=isolated_db)
    deep = [r for r in reviews if r["reviewer_agent"] == "deep_verification"]
    assert deep
    assert all(r["summary"] for r in deep)


def test_offline_research_overview_rides_report(isolated_db: str) -> None:
    """The research overview lands in the report payload and its markdown."""
    run_id, events = _run_offline_workflow(
        "Research overview goal", isolated_db
    )

    nodes = [
        e["payload"].get("task")
        for e in events
        if e["type"] == "scientific_task"
    ]
    assert "research_overview" in nodes

    report = store.get_latest_report(run_id, db_path=isolated_db)
    assert report is not None
    assert report["payload"].get("research_overview")

    markdown = report["markdown_text"]
    assert "## Research Overview" in markdown
