"""Storage-layer invariants.

Covers the append-only event log, evidence/citation linkage, and report
survival.
"""

from __future__ import annotations

import os

import pytest

from app import store
from app.citations import CitationState


@pytest.fixture
def db(isolated_db: str) -> str:
    return os.environ["COSCIENTIST_DB_PATH"]


def test_event_log_is_append_only_and_strictly_increasing(db: str) -> None:
    run = store.create_run("test", "standard", "mock", {})
    seqs = []
    for i in range(5):
        seqs.append(store.append_event(run.id, "log", {"i": i}))
    events = store.list_events(run.id)
    assert seqs == [e["seq"] for e in events]
    # Strictly monotonic.
    assert all(seqs[i] < seqs[i + 1] for i in range(4))


def test_list_events_filters_after_seq(db: str) -> None:
    run = store.create_run("filter test", "standard", "mock", {})
    for i in range(4):
        store.append_event(run.id, "log", {"i": i})
    half = store.list_events(run.id)[1]["seq"]
    after = store.list_events(run.id, after_seq=half)
    assert len(after) == 2
    for ev in after:
        assert ev["seq"] > half


def test_list_runs_reports_top_elo(db: str) -> None:
    run = store.create_run("top-elo", "standard", "mock", {})
    for rating in (1240, 1310, 1180):
        hid = store.add_hypothesis(
            store.NewHypothesis(
                run_id=run.id,
                title="t",
                statement="s",
                created_by_agent="generation",
            )
        )
        store.update_hypothesis_state(
            hid, store.HypothesisStateChanges(elo_rating=rating)
        )
    # A second run with no hypotheses reports None rather than a stray value.
    store.create_run("no-hyps", "standard", "mock", {})

    by_goal = {r.research_goal: r for r in store.list_runs()}
    assert by_goal["top-elo"].top_elo == 1310
    assert by_goal["no-hyps"].top_elo is None
    # A single-run read does not carry the aggregate.
    assert store.get_run(run.id) is not None
    assert store.get_run(run.id).top_elo is None  # type: ignore[union-attr]


def test_list_runs_reports_top_hypotheses_by_elo(db: str) -> None:
    run = store.create_run("top-hyps", "standard", "mock", {})
    for title, rating in (("Low", 1180), ("High", 1320), ("Mid", 1250)):
        hid = store.add_hypothesis(
            store.NewHypothesis(
                run_id=run.id,
                title=title,
                statement="s",
                created_by_agent="generation",
            )
        )
        store.update_hypothesis_state(
            hid, store.HypothesisStateChanges(elo_rating=rating)
        )
    # A run with no hypotheses reports an empty list, not None or a stray value.
    store.create_run("no-hyps", "standard", "mock", {})

    by_goal = {r.research_goal: r for r in store.list_runs()}
    # Ordered by Elo descending, so the highest-rated hypotheses lead.
    assert by_goal["top-hyps"].top_hypotheses == ["High", "Mid", "Low"]
    assert by_goal["no-hyps"].top_hypotheses == []
    # A single-run read does not carry the list enrichment.
    single = store.get_run(run.id)
    assert single is not None
    assert single.top_hypotheses is None


def test_list_runs_caps_top_hypotheses_at_three(db: str) -> None:
    run = store.create_run("many-hyps", "standard", "mock", {})
    for rating in (1300, 1290, 1280, 1270, 1260):
        hid = store.add_hypothesis(
            store.NewHypothesis(
                run_id=run.id,
                title=f"h{rating}",
                statement="s",
                created_by_agent="generation",
            )
        )
        store.update_hypothesis_state(
            hid, store.HypothesisStateChanges(elo_rating=rating)
        )

    listed = {r.research_goal: r for r in store.list_runs()}["many-hyps"]
    assert listed.top_hypotheses == ["h1300", "h1290", "h1280"]


def test_list_runs_reports_latest_pipeline_stage(db: str) -> None:
    run = store.create_run("staged", "standard", "mock", {})
    store.append_event(run.id, "supervisor.plan", {})
    store.append_event(run.id, "generate", {})
    store.append_event(run.id, "ranking", {})
    # A later non-stage event (status) does not shift the reported stage.
    store.append_event(run.id, "status", {"status": "running"})
    # A run with no pipeline events yet reports None.
    store.create_run("unstaged", "standard", "mock", {})

    by_goal = {r.research_goal: r for r in store.list_runs()}
    assert by_goal["staged"].latest_stage == "ranking"
    assert by_goal["unstaged"].latest_stage is None
    # A single-run read does not carry the list enrichment.
    single = store.get_run(run.id)
    assert single is not None
    assert single.latest_stage is None


def test_hypothesis_state_decoupled_from_hypothesis_row(db: str) -> None:
    run = store.create_run("decoupling test", "standard", "mock", {})
    hid = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="t",
            statement="s",
            mechanism="m",
            expected_effect="e",
            experimental_context="x",
            created_by_agent="generation",
        )
    )
    # Mutate state.
    store.update_hypothesis_state(
        hid, store.HypothesisStateChanges(elo_rating=1300, win_delta=1)
    )
    store.update_hypothesis_state(
        hid, store.HypothesisStateChanges(elo_rating=1350, win_delta=1)
    )
    h = store.get_hypothesis(hid)
    assert h is not None
    assert h["elo_rating"] == 1350
    assert h["win_count"] == 2
    # Original immutable fields on `hypotheses` row stay untouched.
    assert h["title"] == "t"
    assert h["statement"] == "s"


def test_hypothesis_row_carries_scene_setting(db: str) -> None:
    """Introduction/Recent findings (MO-6) round-trip through the store."""
    run = store.create_run("scene-setting test", "standard", "mock", {})
    hid = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="t",
            statement="s",
            introduction=(
                "Metabolic disease remains a major cause of morbidity."
            ),
            recent_findings="Aldolase inhibitors have shown early promise.",
            created_by_agent="generation",
        )
    )
    h = store.get_hypothesis(hid)
    assert h is not None
    assert h["introduction"] == (
        "Metabolic disease remains a major cause of morbidity."
    )
    assert h["recent_findings"] == (
        "Aldolase inhibitors have shown early promise."
    )


def test_hypothesis_row_carries_safety_and_toxicity(db: str) -> None:
    """The proposer's own safety assessment (MO-10) round-trips."""
    run = store.create_run("safety test", "standard", "mock", {})
    hid = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="t",
            statement="s",
            safety_and_toxicity="Limited human safety data exists.",
            created_by_agent="generation",
        )
    )
    h = store.get_hypothesis(hid)
    assert h is not None
    assert h["safety_and_toxicity"] == "Limited human safety data exists."


def test_evolved_hypothesis_has_parent_and_higher_generation(db: str) -> None:
    run = store.create_run("lineage", "standard", "mock", {})
    parent = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="P",
            statement="ps",
            created_by_agent="generation",
        )
    )
    child = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="C",
            statement="cs",
            parent_id=parent,
            generation=1,
            created_by_agent="evolution",
        )
    )
    rows = store.list_hypotheses(run.id)
    by_id = {r["id"]: r for r in rows}
    assert by_id[child]["parent_id"] == parent
    assert by_id[child]["generation"] == 1
    assert by_id[parent]["parent_id"] is None
    assert by_id[parent]["generation"] == 0


def test_multi_parent_hypothesis_records_every_parent(db: str) -> None:
    """A combination child keeps parent_id primary and parent_ids all."""
    run = store.create_run("multi-parent", "standard", "mock", {})
    primary = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id, title="P1", statement="p1", hypothesis_id="p1"
        )
    )
    partner = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id, title="P2", statement="p2", hypothesis_id="p2"
        )
    )
    child = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="C",
            statement="cs",
            hypothesis_id="c1",
            parent_id=primary,
            parent_ids=[primary, partner],
            generation=1,
            created_by_agent="evolution",
        )
    )

    rows = {r["id"]: r for r in store.list_hypotheses(run.id)}
    # Lineage listing carries the full parent list, primary leading.
    assert rows[child]["parent_id"] == primary
    assert rows[child]["parent_ids"] == [primary, partner]
    # Single-parent rows read back no multi-parent list.
    assert rows[primary]["parent_ids"] is None
    assert rows[partner]["parent_ids"] is None
    # get_hypothesis agrees with the listing.
    single = store.get_hypothesis(child)
    assert single is not None and single["parent_ids"] == [primary, partner]


def test_redact_hypothesis_fields_overwrites_detail_columns(db: str) -> None:
    run = store.create_run("redact", "standard", "mock", {})
    hid = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="H",
            statement="keep me",
            mechanism="secret mechanism",
            experimental_context="secret protocol",
        )
    )
    store.redact_hypothesis_fields(
        hid, {"mechanism": "[X]", "experimental_context": "[X]"}
    )
    row = store.get_hypothesis(hid)
    assert row is not None
    assert row["mechanism"] == "[X]"
    assert row["experimental_context"] == "[X]"
    # The statement (not a redactable detail column) is untouched.
    assert row["statement"] == "keep me"


def test_redact_hypothesis_fields_rejects_non_redactable_column(
    db: str,
) -> None:
    run = store.create_run("redact", "standard", "mock", {})
    hid = store.add_hypothesis(
        store.NewHypothesis(run_id=run.id, title="H", statement="s")
    )
    with pytest.raises(ValueError, match="non-redactable"):
        store.redact_hypothesis_fields(hid, {"statement": "wiped"})


def test_safety_decision_persists_matches_array(db: str) -> None:
    run = store.create_run("safety", "standard", "mock", {})
    store.add_safety_decision(
        store.NewSafetyDecision(
            run_id=run.id,
            stage="intake",
            decision="block",
            reason="test reason",
            matches=["match-a", "match-b"],
        )
    )
    rows = store.list_safety_decisions(run.id)
    assert rows[0]["decision"] == "block"
    assert rows[0]["matches"] == ["match-a", "match-b"]


def test_match_log_preserves_pre_post_elo(db: str) -> None:
    run = store.create_run("matches", "standard", "mock", {})
    store.add_match(
        store.NewMatch(
            run_id=run.id,
            iteration=1,
            winner_id="w",
            loser_id="l",
            winner_before=1200,
            winner_after=1212,
            loser_before=1200,
            loser_after=1188,
            rationale="rationale",
        )
    )
    rows = store.list_matches(run.id)
    assert rows[0]["winner_elo_before"] == 1200
    assert rows[0]["winner_elo_after"] == 1212
    assert rows[0]["loser_elo_before"] == 1200
    assert rows[0]["loser_elo_after"] == 1188


def test_match_log_records_debate_turns(db: str) -> None:
    run = store.create_run("matches", "standard", "mock", {})
    # A single-turn comparison (default) and a multi-turn scientific debate.
    store.add_match(
        store.NewMatch(
            run_id=run.id,
            iteration=1,
            winner_id="w",
            loser_id="l",
            winner_before=1200,
            winner_after=1212,
            loser_before=1200,
            loser_after=1188,
            rationale="single",
        )
    )
    store.add_match(
        store.NewMatch(
            run_id=run.id,
            iteration=1,
            winner_id="w",
            loser_id="l",
            winner_before=1212,
            winner_after=1230,
            loser_before=1188,
            loser_after=1170,
            rationale="multi",
            debate_turns=3,
        )
    )
    rows = store.list_matches(run.id)
    assert rows[0]["debate_turns"] == 1
    assert rows[1]["debate_turns"] == 3


def test_connections_pair_wal_with_normal_synchronous(db: str) -> None:
    """Commits must not each pay their own fsync.

    Left at the default, every commit fsyncs, and on network-attached
    storage that fsync is what a writer holds the single SQLite write lock
    for. Under a wide worker cohort the lock stayed saturated and ordinary
    API writes exhausted their 30-second busy timeout, so creating a run
    returned "database is locked". NORMAL is the setting WAL is designed to
    be paired with: the log is still fsynced at checkpoints, so a crashed
    process loses nothing, and only an OS-level failure can cost the most
    recent transactions -- which a run reconstructs from its checkpoint
    anyway.
    """
    with store.connect() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        # 0=OFF, 1=NORMAL, 2=FULL. Per-connection, so it must be set by
        # connect() rather than once at schema init.
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1


def test_connections_enforce_foreign_keys(db: str) -> None:
    """Every connection must enforce FKs, not just the schema-init one.

    foreign_keys is per-connection, so setting it only during schema init
    left every ordinary connection with FKs OFF and the schema's ON DELETE
    CASCADE clauses never fired.
    """
    with store.connect() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def _seed_cascade_children(run_id: str) -> None:
    """Populate one row in each FK-linked child table of a run."""
    hid = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run_id,
            title="t",
            statement="s",
            created_by_agent="generation",
        )
    )
    eid = store.add_evidence(
        store.NewEvidence(run_id=run_id, title="paper", source="pubmed")
    )
    store.add_review(
        store.NewReview(
            run_id=run_id,
            hypothesis_id=hid,
            reviewer_agent="reflection",
            summary="sum",
            critique="crit",
        )
    )
    store.add_citation(
        store.NewCitation(
            run_id=run_id,
            hypothesis_id=hid,
            evidence_id=eid,
            claim="c",
            state=CitationState.VERIFIED,
        )
    )
    store.append_event(run_id, "log", {"i": 0})


def test_deleting_a_run_cascades_to_child_rows(db: str) -> None:
    """ON DELETE CASCADE removes child rows without any manual cleanup."""
    run = store.create_run("cascade", "standard", "mock", {})
    _seed_cascade_children(run.id)

    # Delete the parent directly -- no manual child cleanup on this path.
    with store.connect() as conn:
        conn.execute("DELETE FROM runs WHERE id=?", (run.id,))

    assert store.list_hypotheses(run.id) == []
    assert store.list_evidence(run.id) == []
    assert store.list_reviews(run.id) == []
    assert store.list_citations(run.id) == []
    assert store.list_events(run.id) == []


# Tables read (and deleted) one run at a time by ``_list_by_run``. A run's
# rows are a slice of a table that holds every run's, so a missing run_id
# index does not merely make the query slower -- it makes one run's read
# proportional to every other run's writes.
_PER_RUN_LISTED_TABLES = (
    "evidence",
    "citations",
    "claim_evidence",
    "safety_decisions",
    "reviews",
    "matches",
    "proximity_edges",
)


@pytest.mark.parametrize("table", _PER_RUN_LISTED_TABLES)
def test_per_run_listing_never_scans_the_whole_table(
    db: str, table: str
) -> None:
    """Every per-run listing must reach its rows through an index.

    citations, claim_evidence, and safety_decisions each carried an index
    for someone else (hypothesis_id, or nothing at all), so the per-run
    query planned a full table scan across every run in the database.
    """
    with store.connect() as conn:
        plan = conn.execute(
            f"EXPLAIN QUERY PLAN SELECT * FROM {table} WHERE run_id=? "
            "ORDER BY created_at ASC",
            ("any-run",),
        ).fetchall()
    detail = " ".join(row["detail"] for row in plan)
    assert f"SCAN {table}" not in detail, detail
