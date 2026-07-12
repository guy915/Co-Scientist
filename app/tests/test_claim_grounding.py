"""Claim-level grounding pipeline wiring (Milestone 5 / M9).

Covers ``app.claim_grounding.ground_hypotheses``: it must persist the
claim-evidence graph, block a hypothesis whose claim is contradicted by the
evidence, leave a supported/insufficient hypothesis eligible, and drive the
report's publication-gate exclusion end-to-end.
"""

from __future__ import annotations

from typing import Any

from app import report_render, store
from app.claim_grounding import (
    GroundingResult,
    build_assessor,
    evidence_passages,
    ground_hypotheses,
)
from app.claims import as_passages

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
        as_passages([_CONTRADICTING_EVIDENCE]),
        db_path=isolated_db,
    )

    assert isinstance(result, GroundingResult)
    # Only the contradicted hypothesis is blocked.
    assert result.blocked_ids == frozenset({bad_id})
    assert ok_id not in result.blocked_ids

    # The claim-evidence graph is persisted, with a contradicts edge whose
    # support span carries provenance (evidence id + located offsets).
    edges = store.list_claim_evidence(run.id, db_path=isolated_db)
    labels = {e["hypothesis_id"]: e["label"] for e in edges}
    assert labels.get(bad_id) == "contradicts"
    contradicted_edge = next(e for e in edges if e["hypothesis_id"] == bad_id)
    spans = contradicted_edge["contradicting"]
    assert spans  # spans recorded
    span = spans[0]
    assert span["evidence_id"] == "passage-0"
    assert span["quote"] and span["end"] > span["start"] >= 0
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

    # Ground against the run's real evidence rows so the support spans carry a
    # real evidence id / url (the provenance path a live run exercises).
    ground_hypotheses(
        run.id,
        store.list_hypotheses(run.id),
        evidence_passages(run.id, db_path=isolated_db),
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
    """The store round-trips claim-evidence edges with legacy string passages.

    Bare-string passages (the pre-P0.5 shape) still round-trip, so a store
    holding old rows keeps decoding cleanly.
    """
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


def test_build_assessor_selects_by_mode() -> None:
    """`build_assessor` returns the deterministic or LLM assessor by mode."""
    _, det_id = build_assessor("deterministic", "unused")
    assert det_id == "deterministic-v1"
    _, llm_id = build_assessor("llm", "deepseek/deepseek-chat")
    assert llm_id == "llm:deepseek/deepseek-chat"


def test_ground_with_llm_assessor_persists_provenance(
    isolated_db: str, monkeypatch: Any
) -> None:
    """Grounding with the LLM assessor (faked) persists llm-tagged spans."""
    import types

    import litellm

    run = store.create_run("grounding goal", "standard", "engine", {})
    hyp_id = _add(
        run.id,
        "Supported",
        "Inhibiting kinase X reduces melanoma tumor growth in mouse models.",
        isolated_db,
    )
    ev_id = store.add_evidence(
        run.id,
        "Kinase X melanoma study",
        abstract="Kinase X inhibition reduces melanoma tumor growth markedly.",
        source="pubmed",
        url="https://example.org/ev",
        db_path=isolated_db,
    )

    # The faked model cites the real evidence id so the span locates.
    def _completion_for_ev(**_kwargs: Any) -> Any:
        content = (
            '{"label": "supports", "supporting": '
            f'[{{"evidence_id": "{ev_id}", '
            '"quote": "reduces melanoma tumor growth"}], '
            '"contradicting": []}'
        )
        message = types.SimpleNamespace(content=content)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)]
        )

    monkeypatch.setattr(litellm, "completion", _completion_for_ev)

    assessor, assessor_id = build_assessor("llm", "deepseek/deepseek-chat")
    ground_hypotheses(
        run.id,
        store.list_hypotheses(run.id),
        evidence_passages(run.id, db_path=isolated_db),
        assessor=assessor,
        assessor_id=assessor_id,
        db_path=isolated_db,
    )

    edges = store.list_claim_evidence(run.id, db_path=isolated_db)
    edge = next(e for e in edges if e["hypothesis_id"] == hyp_id)
    assert edge["assessor"] == "llm:deepseek/deepseek-chat"
    span = edge["supporting"][0]
    assert span["evidence_id"] == ev_id
    assert span["quote"] == "reduces melanoma tumor growth"
    assert span["url"] == "https://example.org/ev"


def test_ground_records_provenance_spans_round_trip(isolated_db: str) -> None:
    """A provenance-stamped support span round-trips through the store."""
    run = store.create_run("grounding goal", "standard", "mock", {})
    span = {
        "evidence_id": "ev-9",
        "quote": "reduces tumor growth",
        "start": 12,
        "end": 32,
        "source": "pubmed",
        "url": "https://example.org/9",
    }
    store.add_claim_evidence(
        run.id,
        "hyp-1",
        "A supported claim.",
        "supports",
        [span],
        [],
        "llm:deepseek/deepseek-chat",
        db_path=isolated_db,
    )
    edges = store.list_claim_evidence(run.id, db_path=isolated_db)
    assert edges[0]["supporting"] == [span]
    assert edges[0]["assessor"] == "llm:deepseek/deepseek-chat"
