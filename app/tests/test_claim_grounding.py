"""Claim-level grounding pipeline wiring (Milestone 5 / M9).

Covers ``app.claim_grounding.ground_hypotheses``: it must persist the
claim-evidence graph, block a hypothesis whose claim is contradicted by the
evidence, leave a supported/insufficient hypothesis eligible, and drive the
report's publication-gate exclusion end-to-end.
"""

from __future__ import annotations

from app import report_render, store
from app.claim_grounding import GroundingResult, ground_hypotheses

# A claim whose evidence flatly contradicts it (negation marker + shared terms).
_CONTRADICTED = (
    "Inhibiting kinase X reduces melanoma tumor growth in mouse models."
)
_CONTRADICTING_EVIDENCE = (
    "In mouse models, inhibiting kinase X did not reduce melanoma tumor "
    "growth; there was no significant effect on tumor growth."
)
# A benign claim the same evidence pool neither contradicts.
_SUPPORTED = "A dietary change improves cardiovascular outcomes in adults."


def _add(run_id: str, title: str, statement: str, db: str) -> str:
    return store.add_hypothesis(
        run_id, title=title, statement=statement, db_path=db
    )


def test_ground_persists_graph_and_blocks_contradicted(
    isolated_db: str,
) -> None:
    run = store.create_run("grounding goal", "standard", "mock", {})
    bad_id = _add(run.id, "Contradicted", _CONTRADICTED, isolated_db)
    ok_id = _add(run.id, "Benign", _SUPPORTED, isolated_db)

    result = ground_hypotheses(
        run.id,
        store.list_hypotheses(run.id),
        [_CONTRADICTING_EVIDENCE],
        db_path=isolated_db,
    )

    assert isinstance(result, GroundingResult)
    # Only the contradicted hypothesis is blocked.
    assert result.blocked_ids == frozenset({bad_id})
    assert ok_id not in result.blocked_ids

    # The claim-evidence graph is persisted, with a contradicts edge.
    edges = store.list_claim_evidence(run.id, db_path=isolated_db)
    labels = {e["hypothesis_id"]: e["label"] for e in edges}
    assert labels.get(bad_id) == "contradicts"
    contradicted_edge = next(e for e in edges if e["hypothesis_id"] == bad_id)
    assert contradicted_edge["contradicting"]  # passages recorded
    assert contradicted_edge["assessor"]  # provenance recorded

    # A claim_gate audit row was recorded for the block.
    decisions = store.list_safety_decisions(run.id, db_path=isolated_db)
    assert any(
        d["stage"] == "claim_gate" and d["decision"] == "block"
        for d in decisions
    )


def test_contradicted_hypothesis_excluded_from_report(
    isolated_db: str,
) -> None:
    """End-to-end: a grounded, contradicted hypothesis leaves the report."""
    run = store.create_run("grounding goal", "standard", "engine", {})
    bad_id = _add(run.id, "Contradicted", _CONTRADICTED, isolated_db)
    ok_id = _add(run.id, "Benign", _SUPPORTED, isolated_db)
    store.add_evidence(
        run.id,
        "Kinase X mouse study",
        abstract=_CONTRADICTING_EVIDENCE,
        db_path=isolated_db,
    )

    ground_hypotheses(
        run.id,
        store.list_hypotheses(run.id),
        [_CONTRADICTING_EVIDENCE],
        db_path=isolated_db,
    )

    payload, markdown = report_render._build_report_content(
        run_id=run.id,
        research_goal=run.research_goal,
        run_mode="standard",
        provider="engine",
        citation_summary=None,
        meta_review=None,
        research_overview=None,
        execution_time=1.0,
        summary=None,
        db_path=isolated_db,
    )

    leaderboard_ids = {row["id"] for row in payload["leaderboard"]}
    assert bad_id not in leaderboard_ids
    assert ok_id in leaderboard_ids
    assert "kinase X reduces melanoma" not in markdown


def test_ground_records_claim_evidence_round_trip(isolated_db: str) -> None:
    """The store round-trips claim-evidence edges with decoded passages."""
    run = store.create_run("grounding goal", "standard", "mock", {})
    store.add_claim_evidence(
        run.id,
        "hyp-1",
        "A supported claim about a mechanism.",
        "supports",
        ["Supporting passage one.", "Supporting passage two."],
        [],
        "deterministic-v1",
        db_path=isolated_db,
    )
    edges = store.list_claim_evidence(run.id, db_path=isolated_db)
    assert len(edges) == 1
    assert edges[0]["label"] == "supports"
    assert edges[0]["supporting"] == [
        "Supporting passage one.",
        "Supporting passage two.",
    ]
    assert edges[0]["contradicting"] == []
