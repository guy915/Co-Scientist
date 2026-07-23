"""Offline engine workflow: unified event vocabulary and artifact shape.

These tests drive the streaming engine surface (``run_workflow`` directly, the
path the demo seeder and resume worker use) pinned to the deterministic offline
backend. They assert the unified engine event vocabulary, the terminal
lifecycle, and the shape of the deep-verification and research-overview
artifacts. The offline router's per-call determinism is proven in the engine's
own ``tests/test_offline_llm.py``; run-level artifact determinism does *not*
hold here (later prompts embed fresh per-hypothesis identifiers), so it is not
asserted.
"""

from __future__ import annotations

from typing import Any

from app import engine_adapter, store
from tests._client import drain as _drain


def _run_offline_workflow(goal: str) -> tuple[str, list[dict[str, Any]]]:
    """Drive one express offline engine run and return (run_id, events)."""
    run = store.create_run(goal, "express", "engine", {"tier": "express"})
    events = _drain(
        engine_adapter.run_workflow(
            run.id,
            run.research_goal,
            {"tier": "express"},
            engine_adapter.WorkflowOptions(
                force_provider="engine", sleep_seconds=0
            ),
        )
    )
    return run.id, events


def test_offline_workflow_emits_canonical_event_sequence(
    isolated_db: str,
) -> None:
    """The unified engine stream emits the canonical stages in graph order."""
    _run_id, events = _run_offline_workflow("Sequence test goal")
    types = [e["type"] for e in events]

    # Every canonical stage the engine graph runs appears at least once.
    expected_present = {
        "safety.intake",
        "supervisor.plan",
        "generate",
        "review",
        "ranking",
        "evolve",
        "meta_review",
        "deep_verification",
        "proximity",
        "research_overview",
        "safety.hypothesis",
        "citation.grounding",
        "citation_audit",
        "safety.final",
        "report",
    }
    assert expected_present <= set(types), (
        f"missing stages: {expected_present - set(types)}"
    )

    # Ordering the graph guarantees: intake gates first, planning precedes
    # generation, and the report is the last thing before the terminal status.
    assert types.index("safety.intake") < types.index("supervisor.plan")
    assert types.index("supervisor.plan") < types.index("generate")
    assert types.index("generate") < types.index("report")
    assert types[-1] == "status"
    assert types.index("report") == len(types) - 2


def test_offline_workflow_completes_with_report(isolated_db: str) -> None:
    """A keyless offline run reaches completed and publishes a ranked report."""
    run_id, events = _run_offline_workflow("Completion test goal")

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


def _assert_probe_entry(entry: dict[str, Any]) -> None:
    """Assert one deep-verification probe entry carries a verdict and probes."""
    assert entry.get("verdict")
    assert entry.get("probes")


def test_offline_deep_verification_writes_reviews(isolated_db: str) -> None:
    """Deep verification emits a shaped event and attaches its review rows."""
    run_id, events = _run_offline_workflow("Deep verification goal")

    dv_events = [e for e in events if e["type"] == "deep_verification"]
    assert dv_events
    payload = dv_events[0]["payload"]
    assert payload["verified"] >= 1
    assert len(payload["probes"]) == payload["verified"]
    for entry in payload["probes"]:
        _assert_probe_entry(entry)

    # The reviews table carries deep_verification-authored rows for the probed
    # hypotheses, alongside the standard review pass.
    reviews = store.list_reviews(run_id, db_path=isolated_db)
    deep = [r for r in reviews if r["reviewer_agent"] == "deep_verification"]
    assert deep


def test_offline_research_overview_rides_report(isolated_db: str) -> None:
    """The research overview lands in the report payload and its markdown."""
    run_id, events = _run_offline_workflow("Research overview goal")

    ro_events = [e for e in events if e["type"] == "research_overview"]
    assert ro_events
    overview = ro_events[0]["payload"]["research_overview"]
    assert overview["overview"]
    assert overview["nih_specific_aims"]

    report = store.get_latest_report(run_id, db_path=isolated_db)
    assert report is not None
    assert report["payload"].get("research_overview")

    markdown = report["markdown_text"]
    assert "## Research Overview" in markdown
