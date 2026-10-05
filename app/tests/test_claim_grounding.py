from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import litellm
import pytest
from co_scientist.cache import scoped_cache_override
from co_scientist.llm import scoped_telemetry

from app.citations import (
    CitationMetadata,
    Resolvability,
    assess_resolvability,
)
from app.claims import (
    AssessorDraft,
    ClaimAssessment,
    EntailmentLabel,
    EvidencePassage,
    as_passages,
    assess_claim,
    extract_atomic_claims,
    locate_span,
    retrieve_passages,
)
from app.claims.grounding import (
    AssessorSpec as AssessorAssessorSpec,
)
from app.claims.grounding import AssessorSpec as FreshnessAssessorSpec
from app.claims.grounding import (
    ClaimRecord,
    GroundingResult,
    build_assessor,
    claim_fingerprint,
    evidence_passages,
    persist_grounding,
    reusable_assessments,
)
from app.claims.grounding import (
    assess_hypothesis_claims as _assessor_assess_hypothesis_claims,
)
from app.claims.grounding import (
    assess_hypothesis_claims as _freshness_assess_hypothesis_claims,
)
from app.claims.grounding import (
    assess_hypothesis_claims as _grounding_assess_hypothesis_claims,
)
from app.claims.verifier import make_llm_assessor
from app.store import hypotheses
from app.store import records as store
from app.store.hypotheses import NewHypothesis
from app.store.records import NewClaimEvidence, NewEvidence
from tests._drain_helpers import _build_report
from tests._store_helpers import _add, seed_run

from ._llm_fake_backend import install_completion_backend


@pytest.mark.parametrize("failure", [True, False])
def test_claim_provider_records_only_deterministic_substitution(
    monkeypatch: pytest.MonkeyPatch,
    failure: bool,
) -> None:
    async def unavailable(**kwargs: Any) -> Any:
        if failure:
            raise RuntimeError("offline test provider failure")
        return litellm.ModelResponse(
            model="deepseek/deepseek-chat",
            choices=[
                {
                    "message": {
                        "role": "assistant",
                        "content": (
                            '{"label":"supports","supporting":[{"passage":1,'
                            '"quote":"reduces tumor growth"}],'
                            '"contradicting":[]}'
                        ),
                    },
                    "finish_reason": "stop",
                }
            ],
        )

    install_completion_backend(monkeypatch, unavailable)
    assessor, identity = make_llm_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False), scoped_telemetry("claims") as usage:
        result = assess_claim(
            "Kinase X inhibition reduces tumor growth.",
            [
                EvidencePassage(
                    evidence_id="one",
                    text=(
                        "Kinase X inhibition reduces tumor growth "
                        "in AML cell lines."
                    ),
                )
            ],
            assessor=assessor,
            assessor_id=identity,
        )
    assert result.label.value == "supports"
    row = usage.snapshot()["claims::deepseek/deepseek-chat"]
    assert row["deterministic_fallbacks"] == (
        {"claim_single": 1} if failure else {}
    )


@pytest.mark.parametrize("has_evidence", [True, False])
def test_batch_fallback_counts_claims_only_after_judging(
    monkeypatch: pytest.MonkeyPatch,
    has_evidence: bool,
) -> None:
    from app.claims import assess_claims_batch
    from app.claims.verifier import make_llm_batch_assessor

    async def unavailable(**kwargs: Any) -> Any:
        raise RuntimeError("offline test provider failure")

    install_completion_backend(monkeypatch, unavailable)
    assessor, identity = make_llm_batch_assessor("deepseek/deepseek-chat")
    passages = (
        [
            EvidencePassage(
                evidence_id="one",
                text=(
                    "Kinase X inhibition reduces tumor growth "
                    "in AML cell lines."
                ),
            )
        ]
        if has_evidence
        else []
    )
    with scoped_cache_override(False), scoped_telemetry("claims") as usage:
        assess_claims_batch(
            ["Kinase X inhibition reduces tumor growth."],
            passages,
            batch_assessor=assessor,
            assessor_id=identity,
        )
    if has_evidence:
        row = usage.snapshot()["claims::deepseek/deepseek-chat"]
        assert row["deterministic_fallbacks"] == {"claim_batch": 1}
    else:
        assert usage.snapshot() == {}


# Verdicts depend on the claim and retrieved passages; unrelated arrivals must
# not invalidate reuse.


_CLAIM = "Inhibiting kinase X reduces melanoma tumor growth in mouse models."
_OTHER = "A dietary change improves cardiovascular outcomes in adults."

_RELEVANT = (
    "In mouse models, inhibiting kinase X reduced melanoma tumor growth "
    "substantially across every cohort."
)
_UNRELATED = (
    "Sediment cores from the Baltic show a shift in diatom assemblages "
    "during the mid-Holocene."
)


def _passages(*texts: str) -> Any:
    return as_passages(list(texts))


def _hypothesis(hyp_id: str = "h1") -> dict[str, Any]:
    return {"id": hyp_id, "statement": _CLAIM, "mechanism": _OTHER}


def _counting_assessor() -> tuple[Any, list[str]]:
    seen: list[str] = []

    def _assessor(claim: str, _passages: Any) -> AssessorDraft:
        seen.append(claim)
        return AssessorDraft(
            label=EntailmentLabel.INSUFFICIENT,
            supporting=(),
            contradicting=(),
        )

    return _assessor, seen


def _gate_record(
    claims: list[tuple[str, str, str]], assessor_id: str = "test-v1"
) -> dict[str, Any]:
    return {
        "assessor": assessor_id,
        "claims": [
            {
                "claim": claim,
                "role": role,
                "fingerprint": fingerprint,
                "label": EntailmentLabel.SUPPORTS.value,
                "supporting_passages": [],
                "contradicting_passages": [],
            }
            for claim, role, fingerprint in claims
        ],
    }


def test_unrelated_evidence_does_not_change_a_claim_fingerprint() -> None:
    # Only retrieved passages affect a claim's verdict; pool-wide fingerprints
    # invalidate unrelated verdicts.
    record = ClaimRecord(_CLAIM, "speculative")

    before = claim_fingerprint(record, _passages(_RELEVANT), "test-v1")
    after = claim_fingerprint(
        record, _passages(_RELEVANT, _UNRELATED), "test-v1"
    )

    assert before == after


def test_changed_relevant_evidence_changes_the_fingerprint() -> None:
    record = ClaimRecord(_CLAIM, "speculative")

    before = claim_fingerprint(record, _passages(_RELEVANT), "test-v1")
    after = claim_fingerprint(record, _passages(), "test-v1")

    assert before != after


def test_a_different_assessor_invalidates_a_stored_verdict() -> None:
    record = ClaimRecord(_CLAIM, "speculative")
    passages = _passages(_RELEVANT)

    assert claim_fingerprint(record, passages, "test-v1") != (
        claim_fingerprint(record, passages, "other-v2")
    )


def test_matching_claims_skip_the_assessor() -> None:
    passages = _passages(_RELEVANT)
    assessor, seen = _counting_assessor()
    fingerprint = claim_fingerprint(
        ClaimRecord(_CLAIM, "speculative"), passages, "test-v1"
    )

    result = _freshness_assess_hypothesis_claims(
        [_hypothesis()],
        passages,
        FreshnessAssessorSpec(assessor, "test-v1"),
        reuse={
            "h1": reusable_assessments(
                _gate_record([(_CLAIM, "speculative", fingerprint)])
            )
        },
    )

    assert _CLAIM not in seen
    assert _OTHER in seen
    claims = [assessment.claim for assessment, _role in result[0][1]]
    assert claims == [_CLAIM, _OTHER]


def test_reuse_preserves_claim_order_and_roles() -> None:
    passages = _passages(_RELEVANT)
    assessor, _seen = _counting_assessor()
    fingerprint = claim_fingerprint(
        ClaimRecord(_OTHER, "categorical"), passages, "test-v1"
    )

    result = _freshness_assess_hypothesis_claims(
        [_hypothesis()],
        passages,
        FreshnessAssessorSpec(assessor, "test-v1"),
        reuse={
            "h1": reusable_assessments(
                _gate_record([(_OTHER, "categorical", fingerprint)])
            )
        },
    )

    pairs = [(a.claim, role) for a, role in result[0][1]]
    assert pairs == [(_CLAIM, "speculative"), (_OTHER, "categorical")]
    assert result[0][1][1][0].label is EntailmentLabel.SUPPORTS


def test_a_record_without_a_fingerprint_is_never_reused() -> None:
    record = _gate_record([(_CLAIM, "speculative", "")])

    assert reusable_assessments(record) == {}


def test_no_gate_record_assesses_everything() -> None:
    passages = _passages(_RELEVANT)
    assessor, seen = _counting_assessor()

    _freshness_assess_hypothesis_claims(
        [_hypothesis()],
        passages,
        FreshnessAssessorSpec(assessor, "test-v1"),
        reuse={},
    )

    assert sorted(seen) == sorted([_CLAIM, _OTHER])


def test_gate_telemetry_is_folded_into_the_run_metrics() -> None:
    from co_scientist.models import ExecutionMetrics

    from app.engine_tasks import gate as engine_tasks_gate

    state: dict[str, Any] = {"metrics": ExecutionMetrics(llm_calls=7)}
    usage = {"claim_gate::llm:test-model": {"calls": 25, "prompt_tokens": 100}}

    engine_tasks_gate._fold_gate_telemetry(state, usage)

    entry = state["metrics"].model_usage["claim_gate::llm:test-model"]
    assert entry["calls"] == 25
    assert entry["prompt_tokens"] == 100
    assert state["metrics"].llm_calls == 32


def test_a_gate_pass_that_made_no_calls_charges_nothing() -> None:
    from co_scientist.models import ExecutionMetrics

    from app.engine_tasks import gate as engine_tasks_gate

    state: dict[str, Any] = {"metrics": ExecutionMetrics(llm_calls=7)}

    engine_tasks_gate._fold_gate_telemetry(state, {})

    assert state["metrics"].llm_calls == 7
    assert state["metrics"].model_usage == {}


def test_reused_assessment_preserves_verification_method() -> None:
    record = _gate_record([(_CLAIM, "speculative", "fixed-fingerprint")])
    record["claims"][0]["verification_method"] = "model_opposition_verified"
    restored = reusable_assessments(record)
    assert (
        restored["fixed-fingerprint"].verification_method
        == "model_opposition_verified"
    )


def test_legacy_reused_assessment_has_unknown_method() -> None:
    record = _gate_record([(_CLAIM, "speculative", "fixed-fingerprint")])
    assert (
        reusable_assessments(record)["fixed-fingerprint"].verification_method
        == "legacy_unknown"
    )


# Gate failures and report Unverified badges use different support rules; their
# counts cannot be conflated.


def _assessment(claim: str, label: EntailmentLabel) -> ClaimAssessment:
    return ClaimAssessment(
        claim=claim,
        label=label,
        supporting_passages=(),
        contradicting_passages=(),
        assessor="deterministic",
    )


def test_partly_supported_failure_is_not_logged_as_unverified(
    isolated_db: str, caplog: pytest.LogCaptureFixture
) -> None:
    run = seed_run("gate wording")
    partly = _add(run.id, "Partly supported", "A causes B.", isolated_db)
    bare = _add(run.id, "Unsupported", "C causes D.", isolated_db)
    caplog.set_level(logging.INFO, logger="app.claims.grounding")

    result = persist_grounding(
        run.id,
        [
            (
                partly,
                [
                    (_assessment("A binds X.", EntailmentLabel.SUPPORTS), ""),
                    (
                        _assessment(
                            "A causes B.", EntailmentLabel.INSUFFICIENT
                        ),
                        "",
                    ),
                ],
            ),
            (
                bare,
                [
                    (
                        _assessment(
                            "C causes D.", EntailmentLabel.INSUFFICIENT
                        ),
                        "",
                    )
                ],
            ),
        ],
        db_path=isolated_db,
    )

    assert result.blocked_ids == {partly, bare}
    assert (
        f"Hypothesis {partly} did not clear the claim gate "
        "(published with unsupported claims flagged)"
    ) in caplog.text
    assert (
        f"Hypothesis {bare} did not clear the claim gate (published unverified)"
    ) in caplog.text
    assert "2 of 2 hypotheses failed (1 published unverified" in caplog.text
    assert "No hypothesis cleared the claim gate" not in caplog.text


_CONTRADICTED = (
    "Inhibiting kinase X reduces melanoma tumor growth in mouse models."
)
_CONTRADICTING_EVIDENCE = (
    "In mouse models, inhibiting kinase X did not reduce melanoma tumor "
    "growth; there was no significant effect on tumor growth."
)
_GROUNDING_SUPPORTED = (
    "A dietary change improves cardiovascular outcomes in adults."
)
_NO_CLAIM = "Kinase X trial."


def _add_categorical(run_id: str, title: str, claim: str, db: str) -> str:
    # Mechanism carries established-fact claims; the fixture must state the role
    # that controls blocking.
    return _add(run_id, title, _NO_CLAIM, db, mechanism=claim)


def _assert_contradicted_graph(
    run_id: str, bad_id: str, ok_id: str, db_path: str
) -> None:
    edges = store.list_claim_evidence(run_id, db_path=db_path)
    labels = {e["hypothesis_id"]: e["label"] for e in edges}
    assert labels.get(bad_id) == "contradicts"
    contradicted_edge = next(e for e in edges if e["hypothesis_id"] == bad_id)
    assert contradicted_edge["claim_role"] == "categorical"
    spans = contradicted_edge["contradicting"]
    assert spans
    span = spans[0]
    assert span["evidence_id"] == "passage-0"
    assert span["quote"] and span["end"] > span["start"] >= 0
    assert contradicted_edge["assessor"]
    speculative_edge = next(e for e in edges if e["hypothesis_id"] == ok_id)
    assert speculative_edge["label"] == "insufficient"
    assert speculative_edge["claim_role"] == "speculative"


def test_ground_persists_graph_and_blocks_contradicted(
    isolated_db: str,
) -> None:
    run = seed_run("grounding goal", provider="mock")
    bad_id = _add_categorical(
        run.id, "Contradicted", _CONTRADICTED, isolated_db
    )
    ok_id = _add(run.id, "Benign", _GROUNDING_SUPPORTED, isolated_db)

    result = persist_grounding(
        run.id,
        _grounding_assess_hypothesis_claims(
            hypotheses.list_hypotheses(run.id),
            as_passages([_CONTRADICTING_EVIDENCE]),
        ),
        db_path=isolated_db,
    )

    assert isinstance(result, GroundingResult)
    assert result.blocked_ids == frozenset({bad_id, ok_id})

    _assert_contradicted_graph(run.id, bad_id, ok_id, isolated_db)

    decisions = store.list_safety_decisions(run.id, db_path=isolated_db)
    assert any(
        d["stage"] == "claim_gate" and d["decision"] == "block"
        for d in decisions
    )


def test_unsupported_categorical_rationale_is_quarantined(
    isolated_db: str,
) -> None:
    run = seed_run("grounding goal")
    hypothesis_id = hypotheses.add_hypothesis(
        NewHypothesis(
            run_id=run.id,
            title="Unsupported rationale",
            statement="We hypothesize kinase X may alter neuronal recovery.",
            mechanism="Kinase X is established as the recovery controller.",
        ),
        db_path=isolated_db,
    )

    result = persist_grounding(
        run.id,
        _grounding_assess_hypothesis_claims(
            hypotheses.list_hypotheses(run.id, db_path=isolated_db),
            as_passages(
                ["An unrelated passage about photosynthesis in plants."]
            ),
        ),
        db_path=isolated_db,
    )

    assert result.blocked_ids == frozenset({hypothesis_id})
    edges = store.list_claim_evidence(run.id, db_path=isolated_db)
    by_role = {edge["claim_role"]: edge for edge in edges}
    assert by_role["speculative"]["label"] == "insufficient"
    assert by_role["categorical"]["label"] == "insufficient"


def _seed_contradiction_report_run(
    db_path: str, bad_claim_is_categorical: bool
) -> tuple[Any, str, str]:
    # A contradicted established fact withholds the idea; a contradicted
    # proposal remains publishable.
    run = seed_run("grounding goal")
    bad_id = (
        _add_categorical(run.id, "Contradicted", _CONTRADICTED, db_path)
        if bad_claim_is_categorical
        else _add(run.id, "Contradicted", _CONTRADICTED, db_path)
    )
    ok_id = _add(run.id, "Benign", _GROUNDING_SUPPORTED, db_path)
    store.add_evidence(
        NewEvidence(
            run_id=run.id,
            title="Kinase X mouse study",
            abstract=_CONTRADICTING_EVIDENCE,
        ),
        db_path=db_path,
    )
    store.add_evidence(
        NewEvidence(
            run_id=run.id,
            title="Cardiovascular diet study",
            abstract=(
                "A dietary change improves cardiovascular outcomes in adults."
            ),
        ),
        db_path=db_path,
    )

    persist_grounding(
        run.id,
        _grounding_assess_hypothesis_claims(
            hypotheses.list_hypotheses(run.id),
            evidence_passages(run.id, db_path=db_path),
        ),
        db_path=db_path,
    )
    return run, bad_id, ok_id


async def test_contradicted_hypothesis_excluded_from_report(
    isolated_db: str,
) -> None:
    run, bad_id, ok_id = _seed_contradiction_report_run(
        isolated_db, bad_claim_is_categorical=True
    )

    payload, markdown = await _build_report(run, isolated_db)

    leaderboard_ids = {row["id"] for row in payload["leaderboard"]}
    assert bad_id not in leaderboard_ids
    assert ok_id in leaderboard_ids
    assert "kinase X reduces melanoma" not in markdown


async def test_a_contradicted_proposal_still_reaches_the_report(
    isolated_db: str,
) -> None:
    # Evidence against a proposal is a finding owed to the reader, not a reason
    # to hide the proposal.
    run, bad_id, ok_id = _seed_contradiction_report_run(
        isolated_db, bad_claim_is_categorical=False
    )

    payload, _markdown = await _build_report(run, isolated_db)

    leaderboard_ids = {row["id"] for row in payload["leaderboard"]}
    assert bad_id in leaderboard_ids
    assert ok_id in leaderboard_ids


def _seed_speculative_run(db_path: str) -> tuple[Any, str]:
    run = seed_run("novel proposal")
    hypothesis_id = hypotheses.add_hypothesis(
        NewHypothesis(
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
        NewEvidence(
            run_id=run.id,
            title="General energetics review",
            abstract="Astrocytes contribute to neuronal energy metabolism.",
        ),
        db_path=db_path,
    )
    persist_grounding(
        run.id,
        _grounding_assess_hypothesis_claims(
            hypotheses.list_hypotheses(run.id, db_path=db_path),
            evidence_passages(run.id, db_path=db_path),
        ),
        db_path=db_path,
    )
    return run, hypothesis_id


async def test_speculative_insufficient_hypothesis_remains_visible(
    isolated_db: str,
) -> None:
    run, hypothesis_id = _seed_speculative_run(isolated_db)

    payload, markdown = await _build_report(run, isolated_db)

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
    # Old stored support passages are bare strings and must keep decoding.
    run = seed_run("grounding goal", provider="mock")
    hyp_id = _add(run.id, "Supported", _GROUNDING_SUPPORTED, isolated_db)
    store.add_claim_evidence(
        NewClaimEvidence(
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
    run = seed_run("grounding goal")
    current_id = store.add_evidence(
        NewEvidence(
            run_id=run.id,
            title="Current publication",
            url="https://example.org/current",
            abstract="A current result supports the proposed mechanism.",
            available=True,
        ),
        db_path=isolated_db,
    )
    store.add_evidence(
        NewEvidence(
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


_ASSESSOR_SUPPORTED = (
    "A dietary change improves cardiovascular outcomes in adults."
)


def _may_call_out(monkeypatch: Any) -> None:
    monkeypatch.delenv("COSCIENTIST_FORCE_OFFLINE", raising=False)
    monkeypatch.delenv("COSCIENTIST_FORCE_MOCK", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-not-called-by-this-test")


def test_build_assessor_selects_by_mode(monkeypatch: Any) -> None:
    _may_call_out(monkeypatch)

    _, det_id = build_assessor("deterministic", "unused")
    assert det_id == "deterministic-v1"
    _, llm_id = build_assessor("llm", "deepseek/deepseek-chat")
    assert llm_id == "llm:deepseek/deepseek-chat"


def test_offline_never_builds_the_assessor_that_calls_a_provider(
    monkeypatch: Any,
) -> None:

    monkeypatch.setenv("COSCIENTIST_FORCE_OFFLINE", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-would-have-been-billed")

    _, assessor_id = build_assessor("llm", "deepseek/deepseek-chat")

    assert assessor_id == "deterministic-v1"


def _ev_completion(ev_id: str) -> Any:
    # Legacy evidence-id citations remain accepted even though prompts request
    # passage numbers.
    import types

    async def _completion(**_kwargs: Any) -> Any:
        content = (
            '{"label": "supports", "supporting": '
            f'[{{"passage": "{ev_id}", '
            '"quote": "reduces melanoma tumor growth"}], '
            '"contradicting": []}'
        )
        message = types.SimpleNamespace(content=content)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)]
        )

    return _completion


def _seed_llm_assessor(db_path: str) -> tuple[Any, str, str]:
    run = seed_run("grounding goal")
    hyp_id = _add(
        run.id,
        "Supported",
        "Inhibiting kinase X reduces melanoma tumor growth in mouse models.",
        db_path,
    )
    ev_id = store.add_evidence(
        NewEvidence(
            run_id=run.id,
            title="Kinase X melanoma study",
            source="pubmed",
            url="https://example.org/ev",
            abstract=(
                "Kinase X inhibition reduces melanoma tumor growth markedly."
            ),
        ),
        db_path=db_path,
    )
    return run, hyp_id, ev_id


def test_ground_with_llm_assessor_persists_provenance(
    isolated_db: str, monkeypatch: Any
) -> None:
    from co_scientist.cache import scoped_cache_override

    _may_call_out(monkeypatch)
    run, hyp_id, ev_id = _seed_llm_assessor(isolated_db)
    install_completion_backend(monkeypatch, _ev_completion(ev_id))

    assessor, assessor_id = build_assessor("llm", "deepseek/deepseek-chat")
    with scoped_cache_override(False):
        persist_grounding(
            run.id,
            _assessor_assess_hypothesis_claims(
                hypotheses.list_hypotheses(run.id),
                evidence_passages(run.id, db_path=isolated_db),
                AssessorAssessorSpec(assessor, assessor_id),
            ),
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
    run = seed_run("grounding goal", provider="mock")
    hyp_id = _add(run.id, "Supported", _ASSESSOR_SUPPORTED, isolated_db)
    span = {
        "evidence_id": "ev-9",
        "quote": "reduces tumor growth",
        "start": 12,
        "end": 32,
        "source": "pubmed",
        "url": "https://example.org/9",
    }
    store.add_claim_evidence(
        NewClaimEvidence(
            run_id=run.id,
            hypothesis_id=hyp_id,
            claim="A supported claim.",
            label="supports",
            supporting=[span],
            contradicting=[],
            assessor="llm:deepseek/deepseek-chat",
        ),
        db_path=isolated_db,
    )
    edges = store.list_claim_evidence(run.id, db_path=isolated_db)
    assert edges[0]["supporting"] == [span]
    assert edges[0]["assessor"] == "llm:deepseek/deepseek-chat"


def test_claim_assessment_holds_no_database_connection(
    isolated_db: str,
) -> None:
    # Provider assessment must precede persistence so SQLite write locks never
    # span network I/O.
    import sqlite3

    from app.claims.grounding import assess_hypothesis_claims

    hyp = {
        "id": "h1",
        "title": "Kinase X inhibition",
        "statement": _ASSESSOR_SUPPORTED,
    }

    blocker = sqlite3.connect(isolated_db, timeout=0.5, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        assessed = assess_hypothesis_claims(
            [hyp], as_passages([_ASSESSOR_SUPPORTED])
        )
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()

    assert [hyp_id for hyp_id, _ in assessed] == ["h1"]
    assert all(claims for _, claims in assessed)


def test_claim_assessment_runs_concurrently(isolated_db: str) -> None:
    # Independent assessments can overlap; serial provider calls make
    # finalization unboundedly slow.
    import threading
    import time as _time

    from app.claims.grounding import assess_hypothesis_claims

    active = 0
    peak = 0
    lock = threading.Lock()

    def _slow_assessor(claim: str, passages: Any) -> Any:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        _time.sleep(0.05)
        with lock:
            active -= 1
        return AssessorDraft(label=EntailmentLabel.INSUFFICIENT)

    hyps = [
        {"id": f"h{i}", "title": f"H{i}", "statement": _ASSESSOR_SUPPORTED}
        for i in range(8)
    ]
    from app.claims.grounding import AssessorSpec

    assess_hypothesis_claims(
        hyps, as_passages([_ASSESSOR_SUPPORTED]), AssessorSpec(_slow_assessor)
    )

    assert peak > 1, f"claims were assessed serially (peak concurrency {peak})"


def test_batch_assessor_costs_one_call_per_hypothesis(isolated_db: str) -> None:
    # Batching by hypothesis avoids one provider call per atomic claim.
    calls = {"n": 0}

    from app.claims.grounding import assess_hypothesis_claims

    def _batch(claims: Any, passages: Any) -> Any:
        calls["n"] += 1
        return [AssessorDraft(label=EntailmentLabel.INSUFFICIENT)] * len(claims)

    statement = " ".join(
        f"Claim number {i} about a dietary change improving outcomes."
        for i in range(17)
    )
    hyps = [
        {"id": f"h{i}", "title": f"H{i}", "statement": statement}
        for i in range(13)
    ]

    assessed = assess_hypothesis_claims(
        hyps,
        as_passages([_ASSESSOR_SUPPORTED]),
        AssessorAssessorSpec(
            assessor_id="llm:test-model", batch_assessor=_batch
        ),
    )

    assert calls["n"] == 13
    assert len(assessed) == 13
    assert all(len(claims) == 17 for _, claims in assessed)


def test_batch_assessor_splits_a_claim_dense_hypothesis(
    isolated_db: str,
) -> None:
    calls = {"n": 0}

    from app.claims.grounding import assess_hypothesis_claims

    def _batch(claims: Any, passages: Any) -> Any:
        calls["n"] += 1
        return [AssessorDraft(label=EntailmentLabel.INSUFFICIENT)] * len(claims)

    statement = " ".join(
        f"Claim number {i} about a dietary change improving outcomes."
        for i in range(25)
    )
    hyps = [{"id": "h0", "title": "H0", "statement": statement}]

    assessed = assess_hypothesis_claims(
        hyps,
        as_passages([_ASSESSOR_SUPPORTED]),
        AssessorAssessorSpec(
            assessor_id="llm:test-model", batch_assessor=_batch
        ),
    )

    assert calls["n"] == 2
    assert len(assessed[0][1]) == 25


@pytest.mark.parametrize(
    "claim, passage",
    [
        ("p53 inhibits cancer invasion.", "p53 curbs cellular migration."),
        (
            "DNA contains hereditary information.",
            "DNA encodes inherited instructions.",
        ),
        (
            "Protein H folds cooperatively.",
            "H adopts native structure through a concerted transition.",
        ),
        ("Locus J/K predicts trait Z.", "J and K cosegregate with Z."),
    ],
)
def test_short_identifier_passage_reaches_semantic_assessment(
    claim: str,
    passage: str,
) -> None:
    seen: list[EvidencePassage] = []

    def assess(
        _claim: str, passages: Sequence[EvidencePassage]
    ) -> AssessorDraft:
        seen.extend(passages)
        return AssessorDraft(EntailmentLabel.INSUFFICIENT)

    result = assess_claim(claim, as_passages([passage]), assessor=assess)
    assert [p.text for p in seen] == [passage]
    assert result.label is EntailmentLabel.INSUFFICIENT


def test_identifier_only_overlap_does_not_establish_support() -> None:
    result = assess_claim(
        "p53 inhibits cancer invasion.",
        as_passages(["p53 curbs cellular migration."]),
    )
    assert result.label is EntailmentLabel.INSUFFICIENT
    assert result.supporting_passages == ()
    assert result.contradicting_passages == ()


def test_shared_function_words_do_not_admit_unrelated_evidence() -> None:
    from app.claims import retrieve_passages

    assert (
        retrieve_passages(
            "The cat sat on a rug.",
            as_passages(["The jet flew on a sunny day."]),
        )
        == []
    )


def test_short_term_retrieval_keeps_rank_limit_and_stable_ties() -> None:
    from app.claims import retrieve_passages

    passages = as_passages(
        [
            "DNA encodes inherited instructions.",
            "DNA supplies cellular blueprints.",
            "DNA contains hereditary information.",
        ]
    )
    ranked = retrieve_passages(
        "DNA contains hereditary information.", passages, top_k=2
    )
    assert [p.evidence_id for p in ranked] == ["passage-2", "passage-0"]
    assert (
        retrieve_passages(
            "DNA contains hereditary information.", passages, top_k=0
        )
        == []
    )


def test_new_identifier_evidence_invalidates_reused_assessment() -> None:
    from app.claims.grounding import ClaimRecord, claim_fingerprint

    claim = ClaimRecord("Protein H folds cooperatively.", "categorical")
    empty = claim_fingerprint(claim, [], "llm:test")
    unrelated = as_passages(["Ocean salinity varies seasonally."])
    assert claim_fingerprint(claim, unrelated, "llm:test") == empty
    relevant = EvidencePassage(
        "protein-study",
        "H adopts native structure through a concerted transition.",
    )
    assert claim_fingerprint(claim, [*unrelated, relevant], "llm:test") != empty


def test_long_function_words_do_not_supply_retrieval_overlap() -> None:
    from app.claims import retrieve_passages

    assert (
        retrieve_passages(
            "This protein folds with cooperative kinetics.",
            as_passages(["This ocean circulates with seasonal currents."]),
        )
        == []
    )


def test_extracts_atomic_claims_and_drops_fragments() -> None:
    text = (
        "Inhibiting kinase X reduces tumor growth in AML cells. "
        "Ok. "
        "The mechanism involves downstream apoptosis signaling. "
        "Inhibiting kinase X reduces tumor growth in AML cells."
    )
    claims = extract_atomic_claims(text)
    assert claims == [
        "Inhibiting kinase X reduces tumor growth in AML cells.",
        "The mechanism involves downstream apoptosis signaling.",
    ]


def test_extraction_drops_sentences_asserting_an_evidence_gap() -> None:
    # Corpus-absence novelty statements are negative existentials no retrieved
    # passage can confirm.
    text = (
        "Menin inhibition destabilizes c-Myc in KMT2A-rearranged AML. "
        "Within the retrieved literature, no source tests whether PI3K "
        "inhibition alone reactivates the composite program. "
        "This interaction appears unexplored in the retrieved literature. "
        "This hypothesis is formulated without access to a literature "
        "review; no citation keys are available. "
        "The apoptotic mechanism is not systematically characterized. "
        "Dual blockade has not been tested in this subtype."
    )
    assert extract_atomic_claims(text) == [
        "Menin inhibition destabilizes c-Myc in KMT2A-rearranged AML."
    ]


def test_extraction_drops_the_gap_phrasings_production_actually_used() -> None:
    # These verbatim production wordings became unsupported categorical claims
    # without inflection-aware filtering.
    text = (
        "We did not find any source in the provided literature directly "
        "testing CDK4/6 inhibitors in human cardiac fibroblasts. "
        "Direct testing of niclosamide in primary HCF under Wnt-active "
        "conditions appears unreported. "
        "The meta-review notes under-explored cytoskeletal control "
        "mechanisms. "
        "Fasudil inhibits ROCK1 and ROCK2 in cardiac fibroblasts."
    )
    assert extract_atomic_claims(text) == [
        "Fasudil inhibits ROCK1 and ROCK2 in cardiac fibroblasts."
    ]


# Long passages expose union-denominator caps hidden by one-sentence fixtures;
# this text paraphrases the claim.
_SUPPORTING_ABSTRACT = (
    "Selective kinase X blockade in acute myeloid leukemia: preclinical "
    "evidence across patient-derived models. "
    "Acute myeloid leukemia remains difficult to treat, and the contribution "
    "of kinase X to disease maintenance has not been established in primary "
    "material. We profiled expression across sixty-one primary specimens and "
    "eleven established lines, then applied a selective small-molecule "
    "antagonist alongside cytarabine and an isotype-matched vehicle control. "
    "Target engagement was verified by phosphoproteomic readout at three "
    "separate residues. Blocking the kinase curtailed tumor "
    "proliferation in every AML model tested, with cell-cycle arrest at the "
    "G1 checkpoint and induction of apoptosis in treated cells within "
    "forty-eight hours. Colony formation from healthy donor progenitors was "
    "unaffected at equivalent concentrations, suggesting a usable "
    "therapeutic window. Transcriptional profiling implicated downstream "
    "signaling through the canonical survival axis rather than off-target "
    "activity. These results support further evaluation of this strategy in "
    "acute myeloid leukemia."
)

_KINASE_CLAIM = "Inhibiting kinase X reduces tumor growth in AML cells."


def test_weak_overlap_is_insufficient_not_supported() -> None:
    passages = as_passages(
        ["This unrelated review discusses cardiac tissue growth."]
    )
    result = assess_claim(_KINASE_CLAIM, passages)
    assert result.label is EntailmentLabel.INSUFFICIENT
    assert result.supporting_passages == ()


def test_strong_topical_overlap_supports_with_located_span() -> None:
    passage = EvidencePassage(
        evidence_id="ev-1",
        text=_SUPPORTING_ABSTRACT,
        source="pubmed",
        url="https://example.org/1",
    )
    assert len(passage.text.split()) > 8 * len(_KINASE_CLAIM.split())

    result = assess_claim(_KINASE_CLAIM, [passage])
    assert result.label is EntailmentLabel.SUPPORTS
    assert len(result.supporting_passages) == 1
    span = result.supporting_passages[0]
    assert span.evidence_id == "ev-1"
    assert span.url == "https://example.org/1"
    assert passage.text[span.start : span.end] == span.quote
    assert "curtailed tumor proliferation" in span.quote.lower()
    assert result.assessor


def test_passage_quoting_the_claim_verbatim_reaches_the_top_band() -> None:
    # Literal containment must reach SUPPORTS; union-denominated overlap caps
    # long passages below that threshold.
    passage = EvidencePassage(
        evidence_id="ev-1",
        text=_SUPPORTING_ABSTRACT.replace(
            "These results support",
            f"{_KINASE_CLAIM} These results support",
        ),
        source="pubmed",
        url="https://example.org/1",
    )
    result = assess_claim(_KINASE_CLAIM, [passage])
    assert result.label is EntailmentLabel.SUPPORTS
    span = result.supporting_passages[0]
    assert span.quote == _KINASE_CLAIM
    assert passage.text[span.start : span.end] == span.quote


def test_contradiction_dominates_over_support() -> None:
    claim = "Inhibiting kinase X reduces tumor growth in AML cells."
    passages = as_passages(
        [
            "Kinase X inhibition reduces tumor growth in AML cells.",
            "Kinase X inhibition did not reduce tumor growth in AML cells.",
        ]
    )
    result = assess_claim(claim, passages)
    assert result.label is EntailmentLabel.CONTRADICTS
    assert result.contradicting_passages
    assert result.is_fundamental_failure


def test_midband_overlap_is_partial_support_with_located_span() -> None:
    # Partial verdicts still require located support so readers can inspect
    # their evidence.
    claim = "Inhibiting kinase X reduces tumor growth in AML cells."
    passage = EvidencePassage(
        evidence_id="ev-1",
        text="Kinase enzymes regulate cellular growth under diverse "
        "metabolic conditions across many organisms.",
        source="pubmed",
        url="https://example.org/1",
    )
    result = assess_claim(claim, [passage])
    assert result.label is EntailmentLabel.PARTIAL
    assert len(result.supporting_passages) == 1
    span = result.supporting_passages[0]
    assert passage.text[span.start : span.end] == span.quote


def test_full_support_beats_a_partial_near_miss() -> None:
    claim = "Inhibiting kinase X reduces tumor growth in AML cells."
    passages = as_passages(
        [
            "Kinase enzymes regulate cellular growth under diverse "
            "metabolic conditions across many organisms.",
            "Kinase X inhibition reduces tumor growth across several AML "
            "cells.",
        ]
    )
    result = assess_claim(claim, passages)
    assert result.label is EntailmentLabel.SUPPORTS


def test_partial_without_locatable_span_downgraded() -> None:

    def _fabricating_assessor(
        claim: str, passages: list[EvidencePassage]
    ) -> AssessorDraft:
        return AssessorDraft(
            label=EntailmentLabel.PARTIAL,
            supporting=(("ev-1", "a quote that is nowhere in the passage"),),
        )

    result = assess_claim(
        "Kinase X inhibition reduces tumor growth.",
        [EvidencePassage(evidence_id="ev-1", text="Unrelated passage text.")],
        assessor=_fabricating_assessor,  # type: ignore[arg-type]
    )
    assert result.label is EntailmentLabel.INSUFFICIENT
    assert result.supporting_passages == ()


def test_retrieval_ranks_relevant_passages_and_drops_unrelated() -> None:
    claim = "Kinase X inhibition reduces AML tumor growth."
    passages = as_passages(
        [
            "A completely unrelated study of ocean salinity gradients.",
            "Kinase X inhibition reduces AML tumor growth in cell lines.",
            "Tumor growth kinase inhibition AML reduction discussed here.",
        ]
    )
    ranked = retrieve_passages(claim, passages, top_k=2)
    assert len(ranked) == 2
    assert all("salinity" not in p.text for p in ranked)


def test_retrieval_bounds_the_assessed_pool() -> None:
    seen: list[int] = []

    def _counting_assessor(
        claim: str, passages: list[EvidencePassage]
    ) -> AssessorDraft:
        seen.append(len(passages))
        return AssessorDraft(label=EntailmentLabel.INSUFFICIENT)

    passages = as_passages(
        [f"kinase inhibition tumor growth variant {i}" for i in range(10)]
    )
    assess_claim(
        "kinase inhibition reduces tumor growth",
        passages,
        assessor=_counting_assessor,  # type: ignore[arg-type]
        top_k=3,
    )
    assert seen == [3]


def test_deep_supporting_sentence_in_a_chunked_article_is_located() -> None:
    # Chunk offsets must map deep article quotes back to their parent evidence
    # record.
    from app.evidence_chunking import chunk_evidence_passage, parent_evidence_id

    filler = "Unrelated background discussion sentence about other topics. "
    needle = "Kinase X inhibition reduces tumor growth in AML cell lines."
    body = (filler * 300) + needle + (" " + filler * 300)
    chunks = chunk_evidence_passage(
        "article-99",
        head_text="Title only, no abstract.",
        body_text=body,
        source="pubmed",
        url="https://example.org/99",
    )
    assert len(chunks) > 1

    claim = "Kinase X inhibition reduces tumor growth in AML cell lines."
    result = assess_claim(claim, chunks, top_k=3)
    assert result.label is EntailmentLabel.SUPPORTS
    span = result.supporting_passages[0]
    assert needle in span.quote or span.quote in needle
    assert parent_evidence_id(span.evidence_id) == "article-99"


def test_locate_span_is_whitespace_and_case_tolerant() -> None:
    passage = EvidencePassage(
        evidence_id="ev-1",
        text="Kinase X   inhibition reduces tumor growth markedly.",
    )
    span = locate_span(passage, "kinase x inhibition REDUCES tumor growth")
    assert span is not None
    assert passage.text[span.start : span.end] == span.quote
    assert span.quote.startswith("Kinase X")


def test_locate_span_returns_none_for_absent_quote() -> None:
    passage = EvidencePassage(evidence_id="ev-1", text="Some evidence text.")
    assert locate_span(passage, "a quote that does not appear") is None


def test_hallucinated_support_quote_is_downgraded_to_insufficient() -> None:

    def _hallucinating_assessor(
        claim: str, passages: list[EvidencePassage]
    ) -> AssessorDraft:
        return AssessorDraft(
            label=EntailmentLabel.SUPPORTS,
            supporting=(("ev-1", "text that is not in the evidence"),),
        )

    passages = [
        EvidencePassage(evidence_id="ev-1", text="Real evidence about kinases.")
    ]
    result = assess_claim(
        "kinase claim",
        passages,
        assessor=_hallucinating_assessor,  # type: ignore[arg-type]
    )
    assert result.label is EntailmentLabel.INSUFFICIENT
    assert result.supporting_passages == ()


def test_supported_verdict_keeps_located_span_from_swappable_assessor() -> None:

    def _quote_assessor(
        claim: str, passages: list[EvidencePassage]
    ) -> AssessorDraft:
        return AssessorDraft(
            label=EntailmentLabel.SUPPORTS,
            supporting=(("ev-1", "reduces tumor growth"),),
        )

    passage = EvidencePassage(
        evidence_id="ev-1",
        text="Kinase X inhibition reduces tumor growth in AML.",
        url="https://example.org/1",
    )
    result = assess_claim(
        "kinase claim",
        [passage],
        assessor=_quote_assessor,  # type: ignore[arg-type]
        assessor_id="llm:test",
    )
    assert result.label is EntailmentLabel.SUPPORTS
    assert result.assessor == "llm:test"
    span = result.supporting_passages[0]
    assert (
        passage.text[span.start : span.end]
        == span.quote
        == "reduces tumor growth"
    )


def test_resolvability_is_independent_of_support() -> None:
    assert (
        assess_resolvability(CitationMetadata(url="http://x", retracted=True))
        is Resolvability.RETRACTED
    )
    assert (
        assess_resolvability(CitationMetadata(url="", available=True))
        is Resolvability.UNRESOLVABLE
    )
    assert (
        assess_resolvability(CitationMetadata(url="http://x", available=True))
        is Resolvability.RESOLVABLE
    )


def test_resolvability_uses_swappable_resolver() -> None:

    def _live_resolver(meta: CitationMetadata) -> Resolvability:
        return Resolvability.RETRACTED

    verdict = assess_resolvability(
        CitationMetadata(url="http://x", doi="10.1/abc", available=True),
        resolver=_live_resolver,
    )
    assert verdict is Resolvability.RETRACTED
