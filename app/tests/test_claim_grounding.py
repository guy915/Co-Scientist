"""Tests for claim grounding 1."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import litellm
import pytest
from co_scientist.cache import scoped_cache_override
from co_scientist.llm import scoped_telemetry

from app import store
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
from tests._drain_helpers import _build_report
from tests._store_helpers import _add

from ._llm_fake_backend import install_completion_backend

# Claim fallback decisions remain visible in evaluation telemetry.


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


# Reusing claim verdicts whose assessment inputs have not moved.
#
# The pre-ranking gate and the final drain assess the same hypotheses. These
# tests pin what makes carrying a verdict across safe: a claim's verdict
# depends only on itself and the passages it retrieves, so evidence that
# never reaches it cannot make it stale, and a claim whose own evidence
# moved must be re-assessed.


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
    """Build evidence passages from raw text, one per supplied string."""
    return as_passages(list(texts))


def _hypothesis(hyp_id: str = "h1") -> dict[str, Any]:
    """A persisted-row-shaped hypothesis carrying one claim per field."""
    return {"id": hyp_id, "statement": _CLAIM, "mechanism": _OTHER}


def _counting_assessor() -> tuple[Any, list[str]]:
    """An assessor that records every claim it is asked to judge."""
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
    """A stored gate verdict over (claim, role, fingerprint) triples."""
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
    """Evidence a claim never retrieves cannot make its verdict stale.

    The assessor is only ever shown the claim's top-k passages, so
    fingerprinting the whole pool would invalidate every stored verdict
    whenever any article arrived -- and the drain runs after a run has
    finished retrieving, so it would reuse nothing.
    """
    record = ClaimRecord(_CLAIM, "speculative")

    before = claim_fingerprint(record, _passages(_RELEVANT), "test-v1")
    after = claim_fingerprint(
        record, _passages(_RELEVANT, _UNRELATED), "test-v1"
    )

    assert before == after


def test_changed_relevant_evidence_changes_the_fingerprint() -> None:
    """Evidence the claim does retrieve is a new input to its verdict."""
    record = ClaimRecord(_CLAIM, "speculative")

    before = claim_fingerprint(record, _passages(_RELEVANT), "test-v1")
    after = claim_fingerprint(record, _passages(), "test-v1")

    assert before != after


def test_a_different_assessor_invalidates_a_stored_verdict() -> None:
    """A verdict from another assessor is not carried over as current."""
    record = ClaimRecord(_CLAIM, "speculative")
    passages = _passages(_RELEVANT)

    assert claim_fingerprint(record, passages, "test-v1") != (
        claim_fingerprint(record, passages, "other-v2")
    )


def test_matching_claims_skip_the_assessor() -> None:
    """A claim the gate already judged on these inputs is not re-judged."""
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

    # The statement's claim was reused; the mechanism's was not stored.
    assert _CLAIM not in seen
    assert _OTHER in seen
    claims = [assessment.claim for assessment, _role in result[0][1]]
    assert claims == [_CLAIM, _OTHER]


def test_reuse_preserves_claim_order_and_roles() -> None:
    """Persistence walks these positionally, so reuse must not reorder."""
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
    # The reused verdict kept the label the gate recorded, not a fresh one.
    assert result[0][1][1][0].label is EntailmentLabel.SUPPORTS


def test_a_record_without_a_fingerprint_is_never_reused() -> None:
    """A verdict predating fingerprints has no recorded inputs to trust."""
    record = _gate_record([(_CLAIM, "speculative", "")])

    assert reusable_assessments(record) == {}


def test_no_gate_record_assesses_everything() -> None:
    """Absent history, every claim goes to the assessor as before."""
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
    """Grounding's provider calls must count against a run's telemetry.

    Entailment calls route through the engine's ``call_llm_json`` seam
    (``app.claims.verifier``), so ``scoped_telemetry`` already captures
    their tokens/cost/call count per (phase, model); this only has to fold
    that snapshot into the run's live metrics, the same reducer every
    engine node commit uses.
    """
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
    """A fully-reused gate pass must not manufacture a metrics key."""
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


# The claim gate's log lines agree with the report's verified count.
#
# The gate fails a hypothesis for any unsupported categorical claim, while the
# report badges it "Unverified" only when no claim at all has support. The log
# used to call every gate failure "published unverified", so one run logged
# "2 of 5 hypotheses published unverified" beside a report with
# ``verified_count=5`` (run 34b29088, 2026-09-27).


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
    run = store.create_run("gate wording", "standard", "engine", {})
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


# Claim-level grounding pipeline wiring (Milestone 5 / M9).
#
# Covers claim assessment and persistence: they must retain the
# claim-evidence graph, block a hypothesis whose claim is contradicted by the
# evidence, leave a supported/insufficient hypothesis eligible, and drive the
# report's publication-gate exclusion end-to-end.


# A claim whose evidence flatly contradicts it (negation marker + shared terms).
_CONTRADICTED = (
    "Inhibiting kinase X reduces melanoma tumor growth in mouse models."
)
_CONTRADICTING_EVIDENCE = (
    "In mouse models, inhibiting kinase X did not reduce melanoma tumor "
    "growth; there was no significant effect on tumor growth."
)
# A benign claim the same evidence pool neither contradicts.
_GROUNDING_SUPPORTED = (
    "A dietary change improves cardiovascular outcomes in adults."
)
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
    ok_id = _add(run.id, "Benign", _GROUNDING_SUPPORTED, isolated_db)

    result = persist_grounding(
        run.id,
        _grounding_assess_hypothesis_claims(
            store.list_hypotheses(run.id),
            as_passages([_CONTRADICTING_EVIDENCE]),
        ),
        db_path=isolated_db,
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

    result = persist_grounding(
        run.id,
        _grounding_assess_hypothesis_claims(
            store.list_hypotheses(run.id, db_path=isolated_db),
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
    ok_id = _add(run.id, "Benign", _GROUNDING_SUPPORTED, db_path)
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
    persist_grounding(
        run.id,
        _grounding_assess_hypothesis_claims(
            store.list_hypotheses(run.id),
            evidence_passages(run.id, db_path=db_path),
        ),
        db_path=db_path,
    )
    return run, bad_id, ok_id


async def test_contradicted_hypothesis_excluded_from_report(
    isolated_db: str,
) -> None:
    """End-to-end: a contradicted established-fact claim leaves the report."""
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

    payload, _markdown = await _build_report(run, isolated_db)

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
    persist_grounding(
        run.id,
        _grounding_assess_hypothesis_claims(
            store.list_hypotheses(run.id, db_path=db_path),
            evidence_passages(run.id, db_path=db_path),
        ),
        db_path=db_path,
    )
    return run, hypothesis_id


async def test_speculative_insufficient_hypothesis_remains_visible(
    isolated_db: str,
) -> None:
    """Novel proposal text publishes as speculation, never as a finding."""
    run, hypothesis_id = _seed_speculative_run(isolated_db)

    # The claim-evidence status/quote text checked below is part of the
    # full per-hypothesis write-up ("Top hypotheses").
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
    """The store round-trips claim-evidence edges with legacy string passages.

    Bare-string passages (the pre-P0.5 shape) still round-trip, so a store
    holding old rows keeps decoding cleanly.
    """
    run = store.create_run("grounding goal", "standard", "mock", {})
    hyp_id = _add(run.id, "Supported", _GROUNDING_SUPPORTED, isolated_db)
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


# Assessor selection, LLM provenance, and assessment concurrency (M5).
#
# Split out of ``test_claim_grounding.py`` when that file passed the
# module-size budget. That file covers what grounding *persists and gates*;
# this one covers *which assessor runs and how* -- the deterministic/LLM
# choice, the provenance spans an LLM assessor's own quotes produce, and the
# two properties that keep assessment off the SQLite writer: it holds no
# connection, and it overlaps its per-claim provider calls.


# A claim the seeded pubmed abstract supports, so a run's verdict turns on
# which assessor produced it rather than on whether the evidence bears out.
_ASSESSOR_SUPPORTED = (
    "A dietary change improves cardiovascular outcomes in adults."
)


def _may_call_out(monkeypatch: Any) -> None:
    """Put the process in the state where a provider call is permissible."""
    monkeypatch.delenv("COSCIENTIST_FORCE_OFFLINE", raising=False)
    monkeypatch.delenv("COSCIENTIST_FORCE_MOCK", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-not-called-by-this-test")


def test_build_assessor_selects_by_mode(monkeypatch: Any) -> None:
    """`build_assessor` returns the deterministic or LLM assessor by mode.

    Explicit about the process state because mode is no longer the only
    input: an offline process takes the deterministic assessor whatever the
    mode says, which the test below covers.
    """
    _may_call_out(monkeypatch)

    _, det_id = build_assessor("deterministic", "unused")
    assert det_id == "deterministic-v1"
    _, llm_id = build_assessor("llm", "deepseek/deepseek-chat")
    assert llm_id == "llm:deepseek/deepseek-chat"


def test_offline_never_builds_the_assessor_that_calls_a_provider(
    monkeypatch: Any,
) -> None:
    # A credential previously let this app-side path bypass offline mode.

    monkeypatch.setenv("COSCIENTIST_FORCE_OFFLINE", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-would-have-been-billed")

    _, assessor_id = build_assessor("llm", "deepseek/deepseek-chat")

    assert assessor_id == "deterministic-v1"


def _ev_completion(ev_id: str) -> Any:
    """A faked provider answer citing ``ev_id`` so its span locates.

    Cites the legacy id form under the new ``passage`` field (a model
    citing an id rather than the number it was shown is still a
    supported fallback, not the primary contract -- see
    ``claims.verifier._CITATION_ITEM``) to prove the persisted span still
    resolves end to end.
    """
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
    """Seed a supported hypothesis + a pubmed evidence row for LLM grounding."""
    run = store.create_run("grounding goal", "standard", "engine", {})
    hyp_id = _add(
        run.id,
        "Supported",
        "Inhibiting kinase X reduces melanoma tumor growth in mouse models.",
        db_path,
    )
    ev_id = store.add_evidence(
        store.NewEvidence(
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
    """Grounding with the LLM assessor (faked) persists llm-tagged spans."""
    from co_scientist.cache import scoped_cache_override

    _may_call_out(monkeypatch)
    run, hyp_id, ev_id = _seed_llm_assessor(isolated_db)
    # The faked model cites the real evidence id so the span locates.
    install_completion_backend(monkeypatch, _ev_completion(ev_id))

    assessor, assessor_id = build_assessor("llm", "deepseek/deepseek-chat")
    with scoped_cache_override(False):
        persist_grounding(
            run.id,
            _assessor_assess_hypothesis_claims(
                store.list_hypotheses(run.id),
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
    """A provenance-stamped support span round-trips through the store."""
    run = store.create_run("grounding goal", "standard", "mock", {})
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
        store.NewClaimEvidence(
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
    """Assessing claims must be possible without touching the database.

    The assessor can be an LLM, and in production one synchronous call per
    claim ran inside the drain's single write transaction -- so the process
    held SQLite's one write lock across minutes of provider I/O. Everything
    else starved: run creation returned 500 with "database is locked" while
    the database itself sat idle, and a stack dump found the finalize task
    parked in ssl.read with the lock in hand.

    Separating assessment from persistence is what lets the drain do the
    provider work before it opens a transaction.
    """
    import sqlite3

    from app.claims.grounding import assess_hypothesis_claims

    hyp = {
        "id": "h1",
        "title": "Kinase X inhibition",
        "statement": _ASSESSOR_SUPPORTED,
    }

    # Hold the write lock for the whole assessment; it must not care.
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
    """Claims must be assessed in parallel, not one provider call at a time.

    Every claim of every hypothesis is assessed independently, and with the
    LLM assessor each is a synchronous provider call. Run serially that is
    the longest phase of a finished run -- a stack dump caught finalize
    sitting in it for hours. The provider is not the constraint: measured on
    the production model, twenty-four concurrent completions return in the
    same wall clock as four. Assessments are independent, so overlapping
    them changes nothing about the verdicts.
    """
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
    """13 hypotheses of ~17 claims each cost 13 calls, not 218.

    Regression for the production measurement (ultra run b82f9162): the
    per-claim path issued one provider call per atomic claim (218 calls
    across 13 hypotheses in a single pass); the batch path costs one call
    per hypothesis instead.
    """
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
    """One hypothesis with 25 claims costs two calls, not one giant call."""
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


# Short scientific terms must reach assessment without implying entailment.


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


# Tests for claim extraction, entailment, and provenance (M5).
#
# Proves the M5 invariants: an unsupported citation cannot become "verified"
# through word overlap (INSUFFICIENT, not SUPPORTS on weak overlap),
# contradiction dominates other verdicts, and resolvability is judged apart
# from support. Also proves the P0.5 additions: claim-specific retrieval,
# provenance-stamped support spans with exact offsets, a swappable assessor,
# and the anti-hallucination guard that downgrades a verdict whose cited quote
# is not present in the evidence.
#
# What the *gate* then does with these verdicts is ``test_claims_gate.py``,
# split off when this file passed the module-size budget.


# --- Atomic claim extraction ------------------------------------------------


def test_extracts_atomic_claims_and_drops_fragments() -> None:
    """Sentences become claims; short fragments and duplicates are dropped."""
    text = (
        "Inhibiting kinase X reduces tumor growth in AML cells. "
        "Ok. "  # too short -> dropped
        "The mechanism involves downstream apoptosis signaling. "
        "Inhibiting kinase X reduces tumor growth in AML cells."  # duplicate
    )
    claims = extract_atomic_claims(text)
    assert claims == [
        "Inhibiting kinase X reduces tumor growth in AML cells.",
        "The mechanism involves downstream apoptosis signaling.",
    ]


def test_extraction_drops_sentences_asserting_an_evidence_gap() -> None:
    """Novelty statements about the corpus are not empirical claims.

    A sentence asserting that prior work is absent is a negative existential
    over the very corpus the assessor entails against: no passage can confirm
    it, and any topical passage reads as contradicting it. Every example here
    is verbatim from a run whose ideas were withheld on exactly one such
    sentence apiece.
    """
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
    """The same negative existential, in the wordings runs really produce.

    Every sentence here is verbatim from a production run (bc77950f and
    d1273490, 2026-09-07/08) where it survived the filter, became a
    *categorical* claim -- the literature-grounding paragraph's claims must
    be evidence-backed -- and was then counted against its hypothesis as
    "categorical claim(s) lack support". They differ from the wordings
    already covered only in inflection: "did not find any source" rather
    than "no source", "unreported" rather than "not reported",
    "under-explored" rather than "unexplored".
    """
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


# A full-length title+abstract -- the shape an EvidencePassage carries in a run
# (claims.grounding.evidence_passages joins an evidence row's title and
# abstract). The length is the point: a one-sentence claim against a passage
# many times its size is the asymmetry a union-denominated metric caps, and at
# claim size Jaccard and coverage agree, so no assertion below could tell a
# capped metric from a working one. It restates the claim in other words --
# never saying "inhibit" -- so it is a paraphrase, not a copy.
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


# --- Entailment: lexical overlap is not "verified" --------------------------


def test_weak_overlap_is_insufficient_not_supported() -> None:
    """A passage merely sharing a couple of words does not SUPPORT the claim."""
    passages = as_passages(
        ["This unrelated review discusses cardiac tissue growth."]
    )
    result = assess_claim(_KINASE_CLAIM, passages)
    assert result.label is EntailmentLabel.INSUFFICIENT
    assert result.supporting_passages == ()


def test_strong_topical_overlap_supports_with_located_span() -> None:
    """A restating full-length abstract SUPPORTS; the span cites the source."""
    passage = EvidencePassage(
        evidence_id="ev-1",
        text=_SUPPORTING_ABSTRACT,
        source="pubmed",
        url="https://example.org/1",
    )
    # Guard the fixture, not just the verdict: shrink this passage back to the
    # size of the claim and the assertion below passes under a union-
    # denominated metric too, which is how the cap survived here once already.
    assert len(passage.text.split()) > 8 * len(_KINASE_CLAIM.split())

    result = assess_claim(_KINASE_CLAIM, [passage])
    assert result.label is EntailmentLabel.SUPPORTS
    assert len(result.supporting_passages) == 1
    span = result.supporting_passages[0]
    assert span.evidence_id == "ev-1"
    assert span.url == "https://example.org/1"
    # The offsets index into the exact passage text.
    assert passage.text[span.start : span.end] == span.quote
    assert "curtailed tumor proliferation" in span.quote.lower()
    assert result.assessor  # provenance recorded


def test_passage_quoting_the_claim_verbatim_reaches_the_top_band() -> None:
    """A source literally containing the claim must reach SUPPORTS.

    The sanity check ``citations._token_overlap`` prescribes for any new
    similarity threshold: feed it a document containing the claim word for
    word. If that cannot reach the top state the threshold is unreachable and
    every real citation collapses into the bottom one -- which is what a
    union-denominated score does here, scoring 0.071 and missing even partial.
    """
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
    # The located span is the claim sentence itself, verbatim from the source.
    assert span.quote == _KINASE_CLAIM
    assert passage.text[span.start : span.end] == span.quote


def test_contradiction_dominates_over_support() -> None:
    """A contradicting passage yields CONTRADICTS even amid supporting text."""
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
    """A near-miss passage (on-topic, not entailing) is PARTIAL, not INSUFF.

    Its span is still cited as supporting evidence, so a reader can open the
    exact passage behind the partial verdict and the badge can credit it.
    """
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
    """A fully-entailing passage wins SUPPORTS even alongside a partial one."""
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
    """A PARTIAL verdict whose cited quote is absent becomes INSUFFICIENT."""

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


# --- Claim-specific retrieval -----------------------------------------------


def test_retrieval_ranks_relevant_passages_and_drops_unrelated() -> None:
    """Retrieval returns the most relevant; zero-overlap are dropped."""
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
    # The unrelated salinity passage is dropped entirely (zero overlap).
    assert all("salinity" not in p.text for p in ranked)


def test_retrieval_bounds_the_assessed_pool() -> None:
    """Only the top_k retrieved passages reach the assessor."""
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
    """Evidence buried deep in a long, chunked article is still located.

    Regression for whole-article-as-passage grounding: chunking must not
    cost retrieval its ability to find and cite text far from an article's
    start, and the located span must still map back to the parent article.
    """
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
    assert len(chunks) > 1  # the chunking actually happened

    claim = "Kinase X inhibition reduces tumor growth in AML cell lines."
    result = assess_claim(claim, chunks, top_k=3)
    assert result.label is EntailmentLabel.SUPPORTS
    span = result.supporting_passages[0]
    assert needle in span.quote or span.quote in needle
    assert parent_evidence_id(span.evidence_id) == "article-99"


# --- Provenance / span location ---------------------------------------------


def test_locate_span_is_whitespace_and_case_tolerant() -> None:
    """A quote with altered whitespace/casing still locates an exact span."""
    passage = EvidencePassage(
        evidence_id="ev-1",
        text="Kinase X   inhibition reduces tumor growth markedly.",
    )
    span = locate_span(passage, "kinase x inhibition REDUCES tumor growth")
    assert span is not None
    # Offsets index into the original (multi-space) text verbatim.
    assert passage.text[span.start : span.end] == span.quote
    assert span.quote.startswith("Kinase X")


def test_locate_span_returns_none_for_absent_quote() -> None:
    """A quote not present in the passage cannot be located."""
    passage = EvidencePassage(evidence_id="ev-1", text="Some evidence text.")
    assert locate_span(passage, "a quote that does not appear") is None


def test_hallucinated_support_quote_is_downgraded_to_insufficient() -> None:
    """A SUPPORTS verdict whose quote is absent from the passage is unproven."""

    def _hallucinating_assessor(
        claim: str, passages: list[EvidencePassage]
    ) -> AssessorDraft:
        # Cites a quote that does not appear in the passage.
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
    """A swappable assessor citing a real quote yields a located span."""

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


# --- Resolvability separate from support ------------------------------------


def test_resolvability_is_independent_of_support() -> None:
    """Retraction/reachability is judged apart from claim support."""
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
    """A live resolver can be injected in place of the offline default."""

    def _live_resolver(meta: CitationMetadata) -> Resolvability:
        # Pretend a lookup found the DOI retracted despite a reachable URL.
        return Resolvability.RETRACTED

    verdict = assess_resolvability(
        CitationMetadata(url="http://x", doi="10.1/abc", available=True),
        resolver=_live_resolver,
    )
    assert verdict is Resolvability.RETRACTED
