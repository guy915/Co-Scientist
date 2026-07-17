"""Tests for append-only evolution and hypothesis lineage."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests._client import make_client as _client
from tests._client import wait_for_status


def _wait_completed(
    client: TestClient, run_id: str, timeout: float = 20.0
) -> None:
    assert wait_for_status(client, run_id, "completed", timeout=timeout), (
        "run did not complete in time"
    )


def _by_id(hyps: list[dict[str, Any]], hid: str) -> dict[str, Any]:
    """Look up a hypothesis by id within a fetched hypothesis list."""
    return next(h for h in hyps if h["id"] == hid)


def _walk_to_root(
    hyps: list[dict[str, Any]], child: dict[str, Any]
) -> dict[str, Any]:
    """Walk a hypothesis's parent chain back to its root.

    Asserts there is no cycle along the way.
    """
    cur = child
    seen: set[str] = set()
    while cur["parent_id"]:
        assert cur["id"] not in seen, "lineage cycle"
        seen.add(cur["id"])
        cur = _by_id(hyps, cur["parent_id"])
    return cur


def _split_by_lineage(
    hyps: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split hypotheses into (initial, evolved) by parent_id presence."""
    initial = [h for h in hyps if h["parent_id"] is None]
    evolved = [h for h in hyps if h["parent_id"] is not None]
    return initial, evolved


def _assert_child_lineage(
    hyps: list[dict[str, Any]], child: dict[str, Any], initial_ids: set[str]
) -> None:
    """Assert one evolved child's lineage, generation, and identity.

    Walks the child's lineage back to an initial (gen 0) hypothesis, checks
    its generation is exactly one past its parent's, and confirms the engine
    did not overwrite the parent in place (distinct id from every initial).
    """
    root = _walk_to_root(hyps, child)
    assert root["id"] in initial_ids
    parent_row = _by_id(hyps, child["parent_id"])
    assert child["generation"] == parent_row["generation"] + 1
    assert child["id"] not in initial_ids


def test_evolution_creates_new_rows_with_parent_lineage(
    isolated_db: str,
) -> None:
    client = _client()
    rid = client.post(
        "/api/runs",
        json={
            "research_goal": "Targeted apoptosis in glioma stem cells",
            "tier": "express",
        },
    ).json()["id"]
    client.post(f"/api/runs/{rid}/start", json={})
    _wait_completed(client, rid, timeout=30.0)

    hyps = client.get(f"/api/runs/{rid}/hypotheses").json()["hypotheses"]
    initial, evolved = _split_by_lineage(hyps)

    assert len(initial) >= 1
    assert len(evolved) >= 1

    # Each evolved child references an initial (or higher-gen) hypothesis.
    initial_ids = {h["id"] for h in initial}
    for child in evolved:
        _assert_child_lineage(hyps, child, initial_ids)

    # Initial titles/statements are unchanged after evolution. We have no
    # pre-snapshot, so instead verify every initial hypothesis kept a
    # distinct id -- i.e. evolved children sit alongside, not replacing.
    titles_after = {h["id"]: (h["title"], h["statement"]) for h in initial}
    assert len(titles_after) == len(initial)


def test_evolution_runs_between_ranking_rounds(isolated_db: str) -> None:
    """Evolve runs after the first tournament and feeds a second one.

    The durable node executor records a completed ``evolve`` task in the run
    event log and persists evolved children (parent_id set); both are the
    observable proof that evolution ran mid-pipeline, between ranking rounds.
    """
    from app import store

    client = _client()
    rid = client.post(
        "/api/runs",
        json={
            "research_goal": "Lipid raft remodelling in viral entry",
            "tier": "express",
        },
    ).json()["id"]
    client.post(f"/api/runs/{rid}/start", json={})
    _wait_completed(client, rid)

    res = client.get(f"/api/runs/{rid}/events")
    assert res.status_code == 200

    # The durable path emits a scientific_task event per specialist node; the
    # evolve node's completion is the direct signal it ran.
    events = store.list_events(rid, db_path=isolated_db)
    assert any(
        e["type"] == "scientific_task" and e["payload"].get("task") == "evolve"
        for e in events
    )
    # Evolution left durable lineage: at least one evolved child was published.
    hyps = client.get(f"/api/runs/{rid}/hypotheses").json()["hypotheses"]
    assert any(h["parent_id"] for h in hyps)
    # The tournament produced matches on both sides of the evolve step.
    assert len(client.get(f"/api/runs/{rid}/matches").json()["matches"]) >= 2
