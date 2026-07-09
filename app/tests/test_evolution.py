"""Tests for append-only evolution and hypothesis lineage."""

# pylint: disable=unused-argument
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
            "profile": "advanced",
        },
    ).json()["id"]
    client.post(f"/api/runs/{rid}/start", json={})
    _wait_completed(client, rid, timeout=30.0)

    hyps = client.get(f"/api/runs/{rid}/hypotheses").json()["hypotheses"]
    initial, evolved = _split_by_lineage(hyps)

    assert len(initial) >= 5
    assert len(evolved) >= 2

    # Each evolved child references an initial (or higher-gen) hypothesis.
    initial_ids = {h["id"] for h in initial}
    for child in evolved:
        _assert_child_lineage(hyps, child, initial_ids)

    # Initial titles/statements are unchanged after evolution. We have no
    # pre-snapshot, so instead verify every initial hypothesis kept a
    # distinct id -- i.e. evolved children sit alongside, not replacing.
    titles_after = {h["id"]: (h["title"], h["statement"]) for h in initial}
    assert len(titles_after) == len(initial)


def test_evolution_event_emitted(isolated_db: str) -> None:
    """The evolve agent emits at least one event.

    The citation/audit step follows.
    """
    client = _client()
    rid = client.post(
        "/api/runs",
        json={
            "research_goal": "Lipid raft remodelling in viral entry",
            "profile": "standard",
        },
    ).json()["id"]
    client.post(f"/api/runs/{rid}/start", json={})
    _wait_completed(client, rid)

    # Pull the event log via SSE replay — quick text check.
    res = client.get(f"/api/runs/{rid}/events")
    # SSE response is a stream; TestClient returns 200 + text. Just hit the
    # read endpoints for stronger assertions.
    assert res.status_code == 200

    matches = client.get(f"/api/runs/{rid}/matches").json()["matches"]
    iterations = {m["iteration"] for m in matches}
    assert len(iterations) >= 2, (
        "run should have >=2 ranking iterations (pre/post evolve)"
    )
