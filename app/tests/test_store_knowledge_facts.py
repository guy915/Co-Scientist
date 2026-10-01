"""Store round-trip and report-finalize wiring for knowledge facts (G14).

``derive_knowledge_facts`` itself (pure, no DB) is tested in
``test_knowledge_facts.py``; this file covers the durable store I/O
(``replace_knowledge_facts``/``list_knowledge_facts``) and the real
end-to-end path: a run's report finalizing actually persists rows a caller
can read back, including through the collections endpoint.
"""

from __future__ import annotations

from typing import Any

from app import store
from app.report import build as report_build
from app.report import finalize as report_finalize
from tests._client import drain as _drain
from tests._store_helpers import _add

_SUPPORTED = "IL-6 increases inflammation via STAT3 signaling."


async def _emit(type_: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": type_, "payload": payload}


def _finalize(run: Any, db_path: str) -> None:
    """Run the real finalize_report pipeline (safety gate + persistence)."""
    _drain(
        report_finalize.finalize_report(
            run.id,
            report_build.ReportRequest(
                research_goal=run.research_goal,
                run_mode="standard",
                provider="engine",
                execution_time=1.0,
                db_path=db_path,
            ),
            _emit,
        )
    )


# --- store round-trip --------------------------------------------------


def test_replace_and_list_round_trip(isolated_db: str) -> None:
    run = store.create_run("kf goal", "standard", "mock", {})
    hyp_id = _add(run.id, "H", _SUPPORTED, isolated_db)
    facts = [
        {
            "hypothesis_id": hyp_id,
            "evidence_id": "ev-1",
            "kind": "fact",
            "statement": "IL-6 increases inflammation.",
            "entities": ["IL6"],
            "state": "supports",
        }
    ]

    store.replace_knowledge_facts(run.id, facts, db_path=isolated_db)
    rows = store.list_knowledge_facts(run.id, db_path=isolated_db)

    assert len(rows) == 1
    assert rows[0]["kind"] == "fact"
    assert rows[0]["statement"] == "IL-6 increases inflammation."
    assert rows[0]["entities"] == ["IL6"]
    assert rows[0]["evidence_id"] == "ev-1"


def test_replace_clears_prior_rows(isolated_db: str) -> None:
    """A second replace fully supersedes the first -- no accumulation."""
    run = store.create_run("kf goal", "standard", "mock", {})
    hyp_id = _add(run.id, "H", _SUPPORTED, isolated_db)
    first = [
        {
            "hypothesis_id": hyp_id,
            "kind": "fact",
            "statement": "First.",
            "entities": [],
            "state": "supports",
        }
    ]
    second = [
        {
            "hypothesis_id": hyp_id,
            "kind": "contradiction",
            "statement": "Second.",
            "entities": [],
            "state": "contradicts",
        }
    ]

    store.replace_knowledge_facts(run.id, first, db_path=isolated_db)
    store.replace_knowledge_facts(run.id, second, db_path=isolated_db)
    rows = store.list_knowledge_facts(run.id, db_path=isolated_db)

    assert len(rows) == 1
    assert rows[0]["statement"] == "Second."


def test_list_filters_by_kind(isolated_db: str) -> None:
    run = store.create_run("kf goal", "standard", "mock", {})
    hyp_id = _add(run.id, "H", _SUPPORTED, isolated_db)
    store.replace_knowledge_facts(
        run.id,
        [
            {
                "hypothesis_id": hyp_id,
                "kind": "fact",
                "statement": "A fact.",
                "entities": [],
                "state": "supports",
            },
            {
                "hypothesis_id": hyp_id,
                "kind": "contradiction",
                "statement": "A contradiction.",
                "entities": [],
                "state": "contradicts",
            },
        ],
        db_path=isolated_db,
    )

    facts_only = store.list_knowledge_facts(
        run.id, kind="fact", db_path=isolated_db
    )
    assert [r["statement"] for r in facts_only] == ["A fact."]


def test_list_filters_by_entity_case_insensitively(isolated_db: str) -> None:
    run = store.create_run("kf goal", "standard", "mock", {})
    hyp_id = _add(run.id, "H", _SUPPORTED, isolated_db)
    store.replace_knowledge_facts(
        run.id,
        [
            {
                "hypothesis_id": hyp_id,
                "kind": "fact",
                "statement": "About TREM2.",
                "entities": ["TREM2"],
                "state": "supports",
            },
            {
                "hypothesis_id": hyp_id,
                "kind": "fact",
                "statement": "About KRAS.",
                "entities": ["KRAS"],
                "state": "supports",
            },
        ],
        db_path=isolated_db,
    )

    matched = store.list_knowledge_facts(
        run.id, entity="trem2", db_path=isolated_db
    )
    assert [r["statement"] for r in matched] == ["About TREM2."]


def test_facts_are_scoped_per_run(isolated_db: str) -> None:
    """A fact belongs to exactly one run -- G14's per-run-only requirement."""
    run_a = store.create_run("goal a", "standard", "mock", {})
    run_b = store.create_run("goal b", "standard", "mock", {})
    hyp_a = _add(run_a.id, "H", _SUPPORTED, isolated_db)
    store.replace_knowledge_facts(
        run_a.id,
        [
            {
                "hypothesis_id": hyp_a,
                "kind": "fact",
                "statement": "Only in run A.",
                "entities": [],
                "state": "supports",
            }
        ],
        db_path=isolated_db,
    )

    assert store.list_knowledge_facts(run_b.id, db_path=isolated_db) == []
    assert len(store.list_knowledge_facts(run_a.id, db_path=isolated_db)) == 1


def test_run_deletion_cascades_to_knowledge_facts(isolated_db: str) -> None:
    """Deleting a run's row cascades to its knowledge_facts (FK CASCADE)."""
    run = store.create_run("kf goal", "standard", "mock", {})
    hyp_id = _add(run.id, "H", _SUPPORTED, isolated_db)
    store.replace_knowledge_facts(
        run.id,
        [
            {
                "hypothesis_id": hyp_id,
                "kind": "fact",
                "statement": "Doomed.",
                "entities": [],
                "state": "supports",
            }
        ],
        db_path=isolated_db,
    )
    assert len(store.list_knowledge_facts(run.id, db_path=isolated_db)) == 1

    with store.connect(isolated_db) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM runs WHERE id = ?", (run.id,))

    assert store.list_knowledge_facts(run.id, db_path=isolated_db) == []


# --- end-to-end: report finalize persists facts -------------------------


def test_finalize_report_persists_knowledge_facts(isolated_db: str) -> None:
    """A published report derives and durably persists its knowledge facts.

    Drives the real ``finalize_report`` pipeline (safety gate included) --
    not a fixture -- against a run carrying one supports and one contradicts
    claim-evidence edge, then reads the rows back from the store.

    The two edges sit on separate hypotheses on purpose. A contradicted
    claim excludes its own hypothesis from synthesis, so putting both on one
    idea leaves the leaderboard empty and the run is blocked from publishing
    (finding N25 removed the offline exemption that used to let this
    through), which would mean no report and so no facts to assert on.
    """
    run = store.create_run("kf e2e goal", "standard", "mock", {})
    hyp_id = _add(run.id, "Supported", _SUPPORTED, isolated_db)
    contradicted_id = _add(run.id, "Contradicted", _SUPPORTED, isolated_db)
    store.add_claim_evidence(
        store.NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=hyp_id,
            claim="IL-6 increases inflammation via STAT3 signaling.",
            label="supports",
            supporting=[{"evidence_id": "ev-1", "quote": "IL-6 raises it."}],
            contradicting=[],
            assessor="deterministic-v1",
        ),
        db_path=isolated_db,
    )
    store.add_claim_evidence(
        store.NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=contradicted_id,
            claim="TREM2 has no role in this pathway.",
            label="contradicts",
            supporting=[],
            contradicting=[
                {"evidence_id": "ev-2", "quote": "TREM2 is central."}
            ],
            assessor="deterministic-v1",
        ),
        db_path=isolated_db,
    )

    assert store.list_knowledge_facts(run.id, db_path=isolated_db) == []

    _finalize(run, isolated_db)

    facts = store.list_knowledge_facts(run.id, db_path=isolated_db)
    by_kind = {row["kind"]: row for row in facts}
    assert set(by_kind) == {"fact", "contradiction"}
    assert by_kind["fact"]["evidence_id"] == "ev-1"
    assert by_kind["fact"]["hypothesis_id"] == hyp_id
    assert "IL6" in by_kind["fact"]["entities"]
    assert by_kind["contradiction"]["evidence_id"] == "ev-2"
    assert "TREM2" in by_kind["contradiction"]["entities"]


def test_finalize_report_replaces_facts_on_re_finalize(
    isolated_db: str,
) -> None:
    """Re-finalizing does not accumulate duplicate knowledge-facts rows."""
    run = store.create_run("kf goal", "standard", "mock", {})
    hyp_id = _add(run.id, "Supported", _SUPPORTED, isolated_db)
    store.add_claim_evidence(
        store.NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=hyp_id,
            claim="A supported claim.",
            label="supports",
            supporting=[],
            contradicting=[],
            assessor="deterministic-v1",
        ),
        db_path=isolated_db,
    )

    _finalize(run, isolated_db)
    first = store.list_knowledge_facts(run.id, db_path=isolated_db)
    assert len(first) == 1

    # A second finalize call is a documented no-op (report already
    # published) at the finalize_report layer, so exercise the persistence
    # helper directly the way a resumed run's re-finalize would.
    store.replace_knowledge_facts(
        run.id,
        [dict(row, evidence_id=None) for row in first],
        db_path=isolated_db,
    )
    second = store.list_knowledge_facts(run.id, db_path=isolated_db)
    assert len(second) == 1


async def test_knowledge_facts_endpoint_returns_persisted_rows(
    isolated_db: str,
) -> None:
    """``GET /runs/{id}/knowledge-facts`` reads back the persisted rows."""
    from app.runs_collections import get_knowledge_facts

    run = store.create_run("kf goal", "standard", "mock", {})
    hyp_id = _add(run.id, "H", _SUPPORTED, isolated_db)
    store.replace_knowledge_facts(
        run.id,
        [
            {
                "hypothesis_id": hyp_id,
                "kind": "fact",
                "statement": "Endpoint-visible fact.",
                "entities": ["IL6"],
                "state": "supports",
            }
        ],
        db_path=isolated_db,
    )

    result = await get_knowledge_facts(run.id, kind=None, entity=None)

    assert len(result["knowledge_facts"]) == 1
    assert result["knowledge_facts"][0]["statement"] == (
        "Endpoint-visible fact."
    )
