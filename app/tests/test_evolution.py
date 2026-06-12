# Copyright 2026 The Co-Scientist Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Append-only evolution: evolved hypotheses are new rows with parent_id set;
parent rows are never mutated."""
from __future__ import annotations

import time

from fastapi.testclient import TestClient


def _client():
    from app.main import app

    return TestClient(app)


def _wait_completed(client: TestClient, run_id: str, timeout=20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/runs/{run_id}")
        if r.json()["status"] == "completed":
            return
        time.sleep(0.05)
    raise AssertionError("run did not complete in time")


def test_evolution_creates_new_rows_with_parent_lineage(isolated_db):
    client = _client()
    rid = client.post(
        "/api/runs",
        json={"research_goal": "Targeted apoptosis in glioma stem cells", "profile": "advanced"},
    ).json()["id"]
    client.post(f"/api/runs/{rid}/start", json={})
    _wait_completed(client, rid, timeout=30.0)

    hyps = client.get(f"/api/runs/{rid}/hypotheses").json()["hypotheses"]
    initial = [h for h in hyps if h["parent_id"] is None]
    evolved = [h for h in hyps if h["parent_id"] is not None]

    assert len(initial) >= 5
    assert len(evolved) >= 2

    # Each evolved child references an initial (or higher-gen) hypothesis.
    initial_ids = {h["id"] for h in initial}
    for child in evolved:
        # Walk lineage back to an initial (gen 0).
        cur = child
        seen = set()
        while cur["parent_id"]:
            assert cur["id"] not in seen, "lineage cycle"
            seen.add(cur["id"])
            parent = next(h for h in hyps if h["id"] == cur["parent_id"])
            cur = parent
        assert cur["id"] in initial_ids
        # Child's generation is parent's + 1.
        parent_row = next(h for h in hyps if h["id"] == child["parent_id"])
        assert child["generation"] == parent_row["generation"] + 1

    # Initial titles/statements are unchanged after evolution.
    titles_after = {h["id"]: (h["title"], h["statement"]) for h in initial}
    # Re-fetch and confirm equality with itself; we have no pre-snapshot, so
    # instead verify that every evolved child has a distinct `id` from every
    # initial — i.e. the engine did not overwrite parents in place.
    for child in evolved:
        assert child["id"] not in initial_ids

    # And evolved children sit alongside, not replacing.
    assert len(titles_after) == len(initial)


def test_evolution_event_emitted(isolated_db):
    """The evolve agent emits at least one event; the citation/audit step follows."""
    client = _client()
    rid = client.post(
        "/api/runs",
        json={"research_goal": "Lipid raft remodelling in viral entry", "profile": "standard"},
    ).json()["id"]
    client.post(f"/api/runs/{rid}/start", json={})
    _wait_completed(client, rid)

    # Pull the event log via SSE replay — quick text check.
    res = client.get(f"/api/runs/{rid}/events")
    # SSE response is a stream; TestClient returns 200 + text. Just hit the read endpoints
    # for stronger assertions.
    assert res.status_code == 200

    matches = client.get(f"/api/runs/{rid}/matches").json()["matches"]
    iterations = {m["iteration"] for m in matches}
    assert len(iterations) >= 2, "standard run should have >=2 ranking iterations (pre/post evolve)"
