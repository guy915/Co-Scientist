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

"""Storage-layer invariants: append-only event log, evidence/citation linkage, reports survive."""
from __future__ import annotations

import os

import pytest

from app import store


@pytest.fixture
def db(isolated_db: str) -> str:
    return os.environ["COSCIENTIST_DB_PATH"]


def test_event_log_is_append_only_and_strictly_increasing(db: str):
    run = store.create_run("test", "standard", "mock", {})
    seqs = []
    for i in range(5):
        seqs.append(store.append_event(run.id, "log", {"i": i}))
    events = store.list_events(run.id)
    assert seqs == [e["seq"] for e in events]
    # Strictly monotonic.
    assert all(seqs[i] < seqs[i + 1] for i in range(4))


def test_list_events_filters_after_seq(db: str):
    run = store.create_run("filter test", "standard", "mock", {})
    for i in range(4):
        store.append_event(run.id, "log", {"i": i})
    half = store.list_events(run.id)[1]["seq"]
    after = store.list_events(run.id, after_seq=half)
    assert len(after) == 2
    for ev in after:
        assert ev["seq"] > half


def test_hypothesis_state_decoupled_from_hypothesis_row(db: str):
    run = store.create_run("decoupling test", "standard", "mock", {})
    hid = store.add_hypothesis(
        run.id, title="t", statement="s", mechanism="m",
        expected_effect="e", experimental_context="x",
        created_by_agent="generation",
    )
    # Mutate state.
    store.update_hypothesis_state(hid, elo_rating=1300, win_delta=1)
    store.update_hypothesis_state(hid, elo_rating=1350, win_delta=1)
    h = store.get_hypothesis(hid)
    assert h["elo_rating"] == 1350
    assert h["win_count"] == 2
    # Original immutable fields on `hypotheses` row stay untouched.
    assert h["title"] == "t"
    assert h["statement"] == "s"


def test_evolved_hypothesis_has_parent_and_higher_generation(db: str):
    run = store.create_run("lineage", "standard", "mock", {})
    parent = store.add_hypothesis(
        run.id, title="P", statement="ps",
        created_by_agent="generation",
    )
    child = store.add_hypothesis(
        run.id, title="C", statement="cs",
        created_by_agent="evolution", parent_id=parent, generation=1,
    )
    rows = store.list_hypotheses(run.id)
    by_id = {r["id"]: r for r in rows}
    assert by_id[child]["parent_id"] == parent
    assert by_id[child]["generation"] == 1
    assert by_id[parent]["parent_id"] is None
    assert by_id[parent]["generation"] == 0


def test_reports_round_trip_markdown_to_disk(db: str):
    run = store.create_run("report rt", "standard", "mock", {})
    saved = store.save_report(run.id, {"k": "v"}, "# Hello\nbody", db_path=db)
    assert saved["markdown_path"].endswith(".md")
    md = store.read_report_markdown(run.id, db_path=db)
    assert md and "Hello" in md
    rep = store.get_latest_report(run.id, db_path=db)
    assert rep and rep["payload"] == {"k": "v"}


def test_safety_decision_persists_matches_array(db: str):
    run = store.create_run("safety", "standard", "mock", {})
    store.add_safety_decision(run.id, "intake", "block", "test reason", ["match-a", "match-b"])
    rows = store.list_safety_decisions(run.id)
    assert rows[0]["decision"] == "block"
    assert rows[0]["matches"] == ["match-a", "match-b"]


def test_match_log_preserves_pre_post_elo(db: str):
    run = store.create_run("matches", "standard", "mock", {})
    store.add_match(run.id, 1, "w", "l", 1200, 1212, 1200, 1188, "rationale")
    rows = store.list_matches(run.id)
    assert rows[0]["winner_elo_before"] == 1200
    assert rows[0]["winner_elo_after"] == 1212
    assert rows[0]["loser_elo_before"] == 1200
    assert rows[0]["loser_elo_after"] == 1188
