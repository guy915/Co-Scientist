"""Tests for append-only evolution and hypothesis lineage."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app import engine_adapter, store
from tests._client import DEFAULT_TEST_CLIENT_ID, wait_for_status
from tests._client import make_client as _client
from tests._drain_helpers import _engine_hypothesis


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


def _three_generation_state() -> dict[str, Any]:
    """A final state whose lineage runs root -> child -> grandchild.

    Two generations deep on purpose: a run that evolves more than once
    breeds from children as well as roots, and depth one cannot tell a
    correct parent walk from one that stops at the first hop.
    """
    return {
        "hypotheses": [
            _engine_hypothesis(
                "root-1",
                "Root hypothesis about glioma stem-cell apoptosis.",
                parent_id=None,
                generation=0,
                origin="generation",
            ),
            _engine_hypothesis(
                "child-1",
                "Refined hypothesis naming a specific caspase cascade.",
                parent_id="root-1",
                generation=1,
                origin="evolution",
            ),
            _engine_hypothesis(
                "grandchild-1",
                "Further refined hypothesis adding a delivery route.",
                parent_id="child-1",
                generation=2,
                origin="evolution",
            ),
        ],
        "articles": [],
        "tournament_matchups": [],
        "meta_review": {},
        "evolution_details": [],
        "research_overview": {},
    }


def test_evolution_creates_new_rows_with_parent_lineage(
    isolated_db: str,
) -> None:
    """Evolved rows sit alongside their parents and keep a walkable lineage.

    Driven through the drain rather than a live run. A live run cannot
    assert that any child exists: the near-duplicate guard legitimately
    creates no child when a refinement lands on text a peer already holds,
    which offline content -- built from one goal's small template pool --
    reaches often enough to make the assertion a coin flip. What the
    product does guarantee is that whatever evolution *does* produce is
    appended with correct lineage, which is what this pins, at the depth
    a multi-iteration run actually reaches.
    """
    run = store.create_run(
        "Targeted apoptosis in glioma stem cells",
        "express",
        "engine",
        {},
        store.RunCreateOptions(
            client_id=DEFAULT_TEST_CLIENT_ID, db_path=isolated_db
        ),
    )
    engine_adapter._persist_final_state(
        run_id=run.id,
        final_state=_three_generation_state(),
        db_path=isolated_db,
    )

    client = _client()
    hyps = client.get(f"/api/runs/{run.id}/hypotheses").json()["hypotheses"]
    initial, evolved = _split_by_lineage(hyps)

    # Append semantics: the root survives its own refinement.
    assert [h["id"] for h in initial] == ["root-1"]
    assert {h["id"] for h in evolved} == {"child-1", "grandchild-1"}

    initial_ids = {h["id"] for h in initial}
    for child in evolved:
        _assert_child_lineage(hyps, child, initial_ids)


def test_evolution_runs_between_ranking_rounds(isolated_db: str) -> None:
    """Evolve runs after the first tournament and feeds a second one.

    The durable node executor records a completed ``evolve`` task in the run
    event log, and the tournament produces matches on both sides of it.

    Deliberately does not assert that a child was published. The
    near-duplicate guard creates no child when a refinement matches text a
    peer already holds, which is correct behaviour and happens often enough
    against offline content to make that assertion a coin flip. Lineage
    itself is pinned deterministically by
    ``test_evolution_creates_new_rows_with_parent_lineage``.
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
    # The tournament produced matches on both sides of the evolve step.
    assert len(client.get(f"/api/runs/{rid}/matches").json()["matches"]) >= 2
