"""Tests for the ``activity`` discriminator on run_events payloads.

Covers the pure mapping (``activity_for_event``), its coverage of every
engine node, and the round trip through ``store.append_event``/
``list_events`` including backward compatibility with events persisted
before this field existed.
"""

from __future__ import annotations

import json
import sqlite3

from app import store
from app.store.event_activity import (
    ACTIVITY_OTHER,
    ACTIVITY_VALUES,
    activity_for_event,
)


def test_known_node_types_map_to_their_activity() -> None:
    assert activity_for_event("supervisor.plan", {}) == "planning"
    assert activity_for_event("literature_review", {}) == "literature_search"
    assert activity_for_event("generate", {}) == "drafting"
    assert activity_for_event("reflection", {}) == "review"
    assert activity_for_event("ranking", {}) == "tournament"
    assert activity_for_event("evolve", {}) == "evolution"
    assert activity_for_event("proximity", {}) == "deduplication"
    assert activity_for_event("meta_review", {}) == "synthesis"
    assert activity_for_event("safety_screen", {}) == "safety"


def test_scientific_task_reads_node_name_from_payload_task() -> None:
    payload = {"task": "ranking", "status": "completed"}
    assert activity_for_event("scientific_task", payload) == "tournament"


def test_unknown_stage_maps_to_catch_all_never_raises() -> None:
    assert activity_for_event("some_future_node", {}) == ACTIVITY_OTHER
    assert (
        activity_for_event("scientific_task", {"task": "nonexistent"})
        == ACTIVITY_OTHER
    )
    assert activity_for_event("lifecycle", {"event": "queued"}) == (
        ACTIVITY_OTHER
    )


def test_every_node_in_node_to_agent_has_an_activity() -> None:
    """A node added to the engine without an activity must not go unnoticed."""
    from co_scientist.agents import NODE_TO_AGENT

    for node_name in NODE_TO_AGENT:
        activity = activity_for_event(node_name, {})
        assert activity in ACTIVITY_VALUES
        assert activity != ACTIVITY_OTHER, (
            f"node {node_name!r} has no activity mapping"
        )


def test_append_event_persists_activity_inside_payload(
    isolated_db: str,
) -> None:
    run = store.create_run("activity test", "standard", "mock", {})
    store.append_event(run.id, "ranking", {"iteration": 1})
    events = store.list_events(run.id)
    assert events[-1]["payload"]["activity"] == "tournament"


def test_list_events_reads_row_persisted_without_activity_key(
    isolated_db: str,
) -> None:
    """A run resumed across this deploy replays events with no ``activity``.

    Simulates that by inserting a row directly, bypassing ``append_event``'s
    activity computation entirely.
    """
    run = store.create_run("legacy row test", "standard", "mock", {})
    old_payload = {"status": "completed"}
    with sqlite3.connect(isolated_db) as conn:
        conn.execute(
            "INSERT INTO run_events (run_id, seq, type, payload_json, "
            "created_at) VALUES (?, 1, 'status', ?, 0)",
            (run.id, json.dumps(old_payload)),
        )
        conn.commit()
    events = store.list_events(run.id)
    assert events[0]["payload"] == old_payload
    assert "activity" not in events[0]["payload"]
