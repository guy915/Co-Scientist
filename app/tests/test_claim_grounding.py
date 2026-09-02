"""Claim-level grounding pipeline wiring (Milestone 5 / M9).

Covers ``app.claim_grounding.ground_hypotheses``: it must persist the
claim-evidence graph, block a hypothesis whose claim is contradicted by the
evidence, leave a supported/insufficient hypothesis eligible, and drive the
report's publication-gate exclusion end-to-end.
"""

from __future__ import annotations

from typing import Any

from app import store
from app.claim_grounding import (
    GroundingResult,
    GroundingTarget,
    evidence_passages,
    ground_hypotheses,
)
from app.claims import as_passages
from tests._drain_helpers import _build_report, _build_report_ranking
from tests._store_helpers import _add

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
# Too short to yield an atomic claim, so a hypothesis built from it carries
# exactly the one claim the test is about (see claims._MIN_CLAIM_WORDS).
_NO_CLAIM = "Kinase X trial."


def _add_categorical(run_id: str, title: str, claim: str, db: str) -> str:
    """A hypothesis whose only claim is a categorical (mechanism) one.

    Contradiction blocking is role-aware, so a fixture has to say which
    role it is exercising; the mechanism field is what carries the
    established-fact claims.
    """
    return _add(run_id, title, _NO_CLAIM, db, mechanism=claim)


def _assert_contradicted_graph(
    run_id: str, bad_id: str, ok_id: str, db_path: str
) -> None:
    """The persisted graph has a provenance-stamped contradicts edge.

    The contradicts edge's support span carries provenance (evidence id +
    located offsets); the benign speculation resolves to insufficient.
    """
    edges = store.list_claim_evidence(run_id, db_path=db_path)
    labels = {e["hypothesis_id"]: e["label"] for e in edges}
    assert labels.get(bad_id) == "contradicts"
    contradicted_edge = next(e for e in edges if e["hypothesis_id"] == bad_id)
    assert contradicted_edge["claim_role"] == "categorical"
    spans = contradicted_edge["contradicting"]
    assert spans  # spans recorded
    span = spans[0]
    assert span["evidence_id"] == "passage-0"
    assert span["quote"] and span["end"] > span["start"] >= 0
    assert contradicted_edge["assessor"]  # provenance recorded
    speculative_edge = next(e for e in edges if e["hypothesis_id"] == ok_id)
    assert speculative_edge["label"] == "insufficient"
    assert speculative_edge["claim_role"] == "speculative"


def test_ground_persists_graph_and_blocks_contradicted(
    isolated_db: str,
) -> None:
    run = store.create_run("grounding goal", "standard", "mock", {})
    bad_id = _add_categorical(
        run.id, "Contradicted", _CONTRADICTED, isolated_db
    )
    ok_id = _add(run.id, "Benign", _SUPPORTED, isolated_db)

    result = ground_hypotheses(
        run.id,
        store.list_hypotheses(run.id),
        as_passages([_CONTRADICTING_EVIDENCE]),
        target=GroundingTarget(db_path=isolated_db),
    )

    assert isinstance(result, GroundingResult)
    # Contradictions quarantine a proposal; a speculation without any supported
    # scientific context cannot enter ranking either.
    assert result.blocked_ids == frozenset({bad_id, ok_id})

    _assert_contradicted_graph(run.id, bad_id, ok_id, isolated_db)

    # A claim_gate audit row was recorded for the block.
    decisions = store.list_safety_decisions(run.id, db_path=isolated_db)
    assert any(
        d["stage"] == "claim_gate" and d["decision"] == "block"
        for d in decisions
    )


def test_unsupported_categorical_rationale_is_quarantined(
    isolated_db: str,
) -> None:
    """A proposal label cannot excuse unsupported background rationale."""
    run = store.create_run("grounding goal", "standard", "engine", {})
    hypothesis_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Unsupported rationale",
            statement="We hypothesize kinase X may alter neuronal recovery.",
            mechanism="Kinase X is established as the recovery controller.",
        ),
        db_path=isolated_db,
    )

    result = ground_hypotheses(
        run.id,
        store.list_hypotheses(run.id, db_path=isolated_db),
        as_passages(["An unrelated passage about photosynthesis in plants."]),
        target=GroundingTarget(db_path=isolated_db),
    )

    assert result.blocked_ids == frozenset({hypothesis_id})
    edges = store.list_claim_evidence(run.id, db_path=isolated_db)
    by_role = {edge["claim_role"]: edge for edge in edges}
    assert by_role["speculative"]["label"] == "insufficient"
    assert by_role["categorical"]["label"] == "insufficient"


def _seed_contradiction_report_run(
    db_path: str, bad_claim_is_categorical: bool
) -> tuple[Any, str, str]:
    """Seed a two-idea run whose evidence contradicts one of them.

    Args:
        db_path: Per-test database.
        bad_claim_is_categorical: Whether the contradicted claim is carried
            as established-fact rationale (mechanism) or as the proposal
            itself (statement). That role is the whole difference between
            an idea the report withholds and one it publishes.

    Returns:
        The run, the contradicted hypothesis id, and the benign one's.
    """
    run = store.create_run("grounding goal", "standard", "engine", {})
    bad_id = (
        _add_categorical(run.id, "Contradicted", _CONTRADICTED, db_path)
        if bad_claim_is_categorical
        else _add(run.id, "Contradicted", _CONTRADICTED, db_path)
    )
    ok_id = _add(run.id, "Benign", _SUPPORTED, db_path)
    store.add_evidence(
        store.NewEvidence(
            run_id=run.id,
            title="Kinase X mouse study",
            abstract=_CONTRADICTING_EVIDENCE,
        ),
        db_path=db_path,
    )
    store.add_evidence(
        store.NewEvidence(
            run_id=run.id,
            title="Cardiovascular diet study",
            abstract=(
                "A dietary change improves cardiovascular outcomes in adults."
            ),
        ),
        db_path=db_path,
    )

    # Ground against the run's real evidence rows so the support spans carry a
    # real evidence id / url (the provenance path a live run exercises).
    ground_hypotheses(
        run.id,
        store.list_hypotheses(run.id),
        evidence_passages(run.id, db_path=db_path),
        target=GroundingTarget(db_path=db_path),
    )
    return run, bad_id, ok_id


def test_contradicted_hypothesis_excluded_from_report(
    isolated_db: str,
) -> None:
    """End-to-end: a contradicted established-fact claim leaves the report."""
    run, bad_id, ok_id = _seed_contradiction_report_run(
        isolated_db, bad_claim_is_categorical=True
    )

    payload, markdown = _build_report(run, isolated_db)

    leaderboard_ids = {row["id"] for row in payload["leaderboard"]}
    assert bad_id not in leaderboard_ids
    assert ok_id in leaderboard_ids
    assert "kinase X reduces melanoma" not in markdown


def test_a_contradicted_proposal_still_reaches_the_report(
    isolated_db: str,
) -> None:
    """The same contradiction, on the idea itself, publishes instead.

    Evidence against a *proposal* is a finding about that proposal, and the
    report is where the reader is owed it; only a contradicted
    established-fact claim withholds the idea. This has to agree with
    ``publication_gate``, which stopped blocking on the speculative case --
    otherwise an idea the gate ranked would still vanish here.
    """
    run, bad_id, ok_id = _seed_contradiction_report_run(
        isolated_db, bad_claim_is_categorical=False
    )

    payload, _markdown = _build_report(run, isolated_db)

    leaderboard_ids = {row["id"] for row in payload["leaderboard"]}
    assert bad_id in leaderboard_ids
    assert ok_id in leaderboard_ids


def _seed_speculative_run(db_path: str) -> tuple[Any, str]:
    """Seed a novel-proposal run with one supporting evidence row, grounded."""
    run = store.create_run("novel proposal", "standard", "engine", {})
    hypothesis_id = store.add_hypothesis(
        store.NewHypothesis(
            run_id=run.id,
            title="Novel proposal",
            statement=(
                "We hypothesize channel X may alter neuronal ATP recovery."
            ),
            mechanism="Astrocytes contribute to neuronal energy metabolism.",
        ),
        db_path=db_path,
    )
    store.add_evidence(
        store.NewEvidence(
            run_id=run.id,
            title="General energetics review",
            abstract="Astrocytes contribute to neuronal energy metabolism.",
        ),
        db_path=db_path,
    )
    ground_hypotheses(
        run.id,
        store.list_hypotheses(run.id, db_path=db_path),
        evidence_passages(run.id, db_path=db_path),
        target=GroundingTarget(db_path=db_path),
    )
    return run, hypothesis_id


def test_speculative_insufficient_hypothesis_remains_visible(
    isolated_db: str,
) -> None:
    """Novel proposal text publishes as speculation, never as a finding."""
    run, hypothesis_id = _seed_speculative_run(isolated_db)

    # The claim-evidence status/quote text checked below is part of the
    # full per-hypothesis write-up, which renders on the Top Ranking
    # Hypotheses document (R14-11), not the Research Overview one.
    payload, markdown = _build_report_ranking(run, isolated_db)

    assert hypothesis_id in {row["id"] for row in payload["leaderboard"]}
    edge = next(
        edge
        for edge in store.list_claim_evidence(run.id, db_path=isolated_db)
        if edge["claim_role"] == "speculative"
    )
    assert edge["label"] == "insufficient"
    assert edge["claim_role"] == "speculative"
    report_edges = payload["claim_evidence"]
    assert {item["hypothesis_id"] for item in report_edges} == {hypothesis_id}
    supported = next(
        item for item in report_edges if item["label"] == "supports"
    )
    assert supported["supporting"][0]["source_title"] == (
        "General energetics review"
    )
    assert supported["supporting"][0]["quote"].endswith(
        "Astrocytes contribute to neuronal energy metabolism."
    )
    assert "**Supported · categorical**" in markdown
    assert "General energetics review" in markdown
    assert "Astrocytes contribute to neuronal energy metabolism." in markdown
    assert "**Speculative — evidence insufficient · speculative**" in markdown


def test_ground_records_claim_evidence_round_trip(isolated_db: str) -> None:
    """The store round-trips claim-evidence edges with legacy string passages.

    Bare-string passages (the pre-P0.5 shape) still round-trip, so a store
    holding old rows keeps decoding cleanly.
    """
    run = store.create_run("grounding goal", "standard", "mock", {})
    hyp_id = _add(run.id, "Supported", _SUPPORTED, isolated_db)
    store.add_claim_evidence(
        store.NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=hyp_id,
            claim="A supported claim about a mechanism.",
            label="supports",
            supporting=["Supporting passage one.", "Supporting passage two."],
            contradicting=[],
            assessor="deterministic-v1",
        ),
        db_path=isolated_db,
    )
    edges = store.list_claim_evidence(run.id, db_path=isolated_db)
    assert len(edges) == 1
    assert edges[0]["label"] == "supports"
    assert edges[0]["claim_role"] == "categorical"
    assert edges[0]["supporting"] == [
        "Supporting passage one.",
        "Supporting passage two.",
    ]
    assert edges[0]["contradicting"] == []


def test_evidence_passages_excludes_unavailable_sources(
    isolated_db: str,
) -> None:
    """Unavailable publications cannot supply claim-grounding passages."""
    run = store.create_run("grounding goal", "standard", "engine", {})
    current_id = store.add_evidence(
        store.NewEvidence(
            run_id=run.id,
            title="Current publication",
            url="https://example.org/current",
            abstract="A current result supports the proposed mechanism.",
            available=True,
        ),
        db_path=isolated_db,
    )
    store.add_evidence(
        store.NewEvidence(
            run_id=run.id,
            title="Retracted publication",
            url="https://example.org/retracted",
            abstract="A retracted result must not support the mechanism.",
            available=False,
        ),
        db_path=isolated_db,
    )

    passages = evidence_passages(run.id, db_path=isolated_db)

    assert [passage.evidence_id for passage in passages] == [current_id]
    assert all("retracted" not in passage.text.lower() for passage in passages)
