from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import litellm
import pytest
from co_scientist.cache import scoped_cache_override
from co_scientist.llm import scoped_telemetry
from co_scientist.models import ExecutionMetrics

from app.claims import (
    AssessorDraft,
    EntailmentLabel,
    EvidencePassage,
    as_passages,
    assess_claim,
    assess_claims_batch,
    extract_atomic_claims,
    locate_span,
    retrieve_passages,
)
from app.claims.grounding import (
    AssessorSpec,
    ClaimRecord,
    GroundingResult,
    assess_hypothesis_claims,
    build_assessor,
    claim_fingerprint,
    evidence_passages,
    persist_grounding,
    reusable_assessments,
)
from app.claims.verifier import make_llm_assessor, make_llm_batch_assessor
from app.engine_tasks import gate as engine_tasks_gate
from app.evidence_chunking import chunk_evidence_passage, parent_evidence_id
from app.store import hypotheses
from app.store import records as store
from app.store.hypotheses import NewHypothesis
from app.store.records import NewEvidence
from tests._drain_helpers import _build_report
from tests._store_helpers import _add, seed_run

from ._llm_fake_backend import completion_response, install_completion_backend

_KINASE_PASSAGE = EvidencePassage(
    evidence_id="one",
    text="Kinase X inhibition reduces tumor growth in AML cell lines.",
)


@pytest.mark.parametrize("failure", [True, False])
def test_claim_provider_records_only_deterministic_substitution(
    monkeypatch: pytest.MonkeyPatch, failure: bool
) -> None:
    async def provider(**kwargs: Any) -> Any:
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

    install_completion_backend(monkeypatch, provider)
    assessor, identity = make_llm_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False), scoped_telemetry("claims") as usage:
        result = assess_claim(
            "Kinase X inhibition reduces tumor growth.",
            [_KINASE_PASSAGE],
            assessor=assessor,
            assessor_id=identity,
        )
    assert result.label is EntailmentLabel.SUPPORTS
    row = usage.snapshot()["claims::deepseek/deepseek-chat"]
    assert row["deterministic_fallbacks"] == (
        {"claim_single": 1} if failure else {}
    )


@pytest.mark.parametrize("has_evidence", [True, False])
def test_batch_fallback_counts_claims_only_after_judging(
    monkeypatch: pytest.MonkeyPatch, has_evidence: bool
) -> None:
    async def unavailable(**kwargs: Any) -> Any:
        raise RuntimeError("offline test provider failure")

    install_completion_backend(monkeypatch, unavailable)
    assessor, identity = make_llm_batch_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False), scoped_telemetry("claims") as usage:
        assess_claims_batch(
            ["Kinase X inhibition reduces tumor growth."],
            [_KINASE_PASSAGE] if has_evidence else [],
            batch_assessor=assessor,
            assessor_id=identity,
        )
    if has_evidence:
        row = usage.snapshot()["claims::deepseek/deepseek-chat"]
        assert row["deterministic_fallbacks"] == {"claim_batch": 1}
    else:
        assert usage.snapshot() == {}


@pytest.mark.parametrize("calls", [25, 0])
def test_gate_telemetry_is_folded_into_the_run_metrics(calls: int) -> None:
    state: dict[str, Any] = {"metrics": ExecutionMetrics(llm_calls=7)}
    usage = (
        {"claim_gate::llm:test-model": {"calls": 25, "prompt_tokens": 100}}
        if calls
        else {}
    )

    engine_tasks_gate._fold_gate_telemetry(state, usage)

    assert state["metrics"].llm_calls == 7 + calls
    assert bool(state["metrics"].model_usage) is bool(calls)


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


def test_a_claim_fingerprint_tracks_only_its_own_evidence_and_assessor() -> (
    None
):
    record = ClaimRecord(_CLAIM, "speculative")
    relevant = as_passages([_RELEVANT])

    base = claim_fingerprint(record, relevant, "test-v1")

    unrelated = as_passages([_RELEVANT, _UNRELATED])
    assert claim_fingerprint(record, unrelated, "test-v1") == base
    assert claim_fingerprint(record, as_passages([]), "test-v1") != base
    assert claim_fingerprint(record, relevant, "other-v2") != base

    identifier_claim = ClaimRecord("Protein H folds cooperatively.", "x")
    empty = claim_fingerprint(identifier_claim, [], "llm:test")
    new_evidence = EvidencePassage(
        "protein-study",
        "H adopts native structure through a concerted transition.",
    )
    assert (
        claim_fingerprint(identifier_claim, [new_evidence], "llm:test") != empty
    )


def test_a_stored_verdict_is_reused_only_when_its_fingerprint_matches() -> None:
    passages = as_passages([_RELEVANT])
    seen: list[str] = []

    def assessor(claim: str, _passages: Any) -> AssessorDraft:
        seen.append(claim)
        return AssessorDraft(EntailmentLabel.INSUFFICIENT)

    fingerprint = claim_fingerprint(
        ClaimRecord(_OTHER, "categorical"), passages, "test-v1"
    )
    hypothesis = {"id": "h1", "statement": _CLAIM, "mechanism": _OTHER}
    spec = AssessorSpec(assessor, "test-v1")

    reused = assess_hypothesis_claims(
        [hypothesis],
        passages,
        spec,
        reuse={
            "h1": reusable_assessments(
                _gate_record([(_OTHER, "categorical", fingerprint)])
            )
        },
    )
    assert seen == [_CLAIM]
    pairs = [(a.claim, role) for a, role in reused[0][1]]
    assert pairs == [(_CLAIM, "speculative"), (_OTHER, "categorical")]
    assert reused[0][1][1][0].label is EntailmentLabel.SUPPORTS

    seen.clear()
    assess_hypothesis_claims([hypothesis], passages, spec, reuse={})
    assert sorted(seen) == sorted([_CLAIM, _OTHER])
    assert (
        reusable_assessments(_gate_record([(_CLAIM, "speculative", "")])) == {}
    )


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("model_opposition_verified", "model_opposition_verified"),
        (None, "legacy_unknown"),
    ],
)
def test_a_reused_verdict_keeps_its_verification_method(
    method: str | None, expected: str
) -> None:
    record = _gate_record([(_CLAIM, "speculative", "fixed-fingerprint")])
    if method:
        record["claims"][0]["verification_method"] = method

    restored = reusable_assessments(record)

    assert restored["fixed-fingerprint"].verification_method == expected


# Hypotheses persist their claim graph; the gate decides publication from it.

_CONTRADICTED = (
    "Inhibiting kinase X reduces melanoma tumor growth in mouse models."
)
_CONTRADICTING_EVIDENCE = (
    "In mouse models, inhibiting kinase X did not reduce melanoma tumor "
    "growth; there was no significant effect on tumor growth."
)
_SUPPORTED = "A dietary change improves cardiovascular outcomes in adults."
_NO_CLAIM = "Kinase X trial."


def _add_categorical(run_id: str, title: str, claim: str, db: str) -> str:
    # Mechanism carries established-fact claims; the fixture must state the role
    # that controls blocking.
    return _add(run_id, title, _NO_CLAIM, db, mechanism=claim)


def test_ground_persists_graph_and_blocks_contradicted(
    isolated_db: str,
) -> None:
    run = seed_run("grounding goal", provider="mock")
    bad_id = _add_categorical(
        run.id, "Contradicted", _CONTRADICTED, isolated_db
    )
    ok_id = _add(run.id, "Benign", _SUPPORTED, isolated_db)

    result = persist_grounding(
        run.id,
        assess_hypothesis_claims(
            hypotheses.list_hypotheses(run.id),
            as_passages([_CONTRADICTING_EVIDENCE]),
        ),
        db_path=isolated_db,
    )

    assert isinstance(result, GroundingResult)
    assert result.blocked_ids == frozenset({bad_id, ok_id})
    edges = store.list_claim_evidence(run.id, db_path=isolated_db)
    contradicted = next(e for e in edges if e["hypothesis_id"] == bad_id)
    assert contradicted["label"] == "contradicts"
    assert contradicted["claim_role"] == "categorical"
    assert contradicted["assessor"]
    span = contradicted["contradicting"][0]
    assert span["evidence_id"] == "passage-0"
    assert span["quote"] and span["end"] > span["start"] >= 0
    speculative = next(e for e in edges if e["hypothesis_id"] == ok_id)
    assert speculative["label"] == "insufficient"
    assert speculative["claim_role"] == "speculative"
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
        assess_hypothesis_claims(
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
    ok_id = _add(run.id, "Benign", _SUPPORTED, db_path)
    for title, abstract in (
        ("Kinase X mouse study", _CONTRADICTING_EVIDENCE),
        ("Cardiovascular diet study", _SUPPORTED),
    ):
        store.add_evidence(
            NewEvidence(run_id=run.id, title=title, abstract=abstract),
            db_path=db_path,
        )
    persist_grounding(
        run.id,
        assess_hypothesis_claims(
            hypotheses.list_hypotheses(run.id),
            evidence_passages(run.id, db_path=db_path),
        ),
        db_path=db_path,
    )
    return run, bad_id, ok_id


@pytest.mark.parametrize(
    ("categorical", "bad_reaches_the_report"), [(True, False), (False, True)]
)
async def test_only_a_contradicted_established_fact_is_withheld_from_the_report(
    isolated_db: str, categorical: bool, bad_reaches_the_report: bool
) -> None:
    # Evidence against a proposal is a finding owed to the reader, not a reason
    # to hide the proposal.
    run, bad_id, ok_id = _seed_contradiction_report_run(
        isolated_db, bad_claim_is_categorical=categorical
    )

    payload, markdown = await _build_report(run, isolated_db)

    leaderboard_ids = {row["id"] for row in payload["leaderboard"]}
    assert (bad_id in leaderboard_ids) is bad_reaches_the_report
    assert ok_id in leaderboard_ids
    if not bad_reaches_the_report:
        assert "kinase X reduces melanoma" not in markdown


async def test_speculative_insufficient_hypothesis_remains_visible(
    isolated_db: str,
) -> None:
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
        db_path=isolated_db,
    )
    store.add_evidence(
        NewEvidence(
            run_id=run.id,
            title="General energetics review",
            abstract="Astrocytes contribute to neuronal energy metabolism.",
        ),
        db_path=isolated_db,
    )
    persist_grounding(
        run.id,
        assess_hypothesis_claims(
            hypotheses.list_hypotheses(run.id, db_path=isolated_db),
            evidence_passages(run.id, db_path=isolated_db),
        ),
        db_path=isolated_db,
    )

    payload, markdown = await _build_report(run, isolated_db)

    assert hypothesis_id in {row["id"] for row in payload["leaderboard"]}
    edge = next(
        edge
        for edge in store.list_claim_evidence(run.id, db_path=isolated_db)
        if edge["claim_role"] == "speculative"
    )
    assert edge["label"] == "insufficient"
    report_edges = payload["claim_evidence"]
    assert {item["hypothesis_id"] for item in report_edges} == {hypothesis_id}
    supported = next(
        item for item in report_edges if item["label"] == "supports"
    )
    assert supported["supporting"][0]["source_title"] == (
        "General energetics review"
    )
    assert "**Supported · categorical**" in markdown
    assert "**Speculative — evidence insufficient · speculative**" in markdown


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


@pytest.mark.parametrize(
    ("force_offline", "mode", "expected"),
    [
        (False, "deterministic", "deterministic-v1"),
        (False, "llm", "llm:deepseek/deepseek-chat"),
        (True, "llm", "deterministic-v1"),
    ],
)
def test_offline_never_builds_the_assessor_that_calls_a_provider(
    monkeypatch: pytest.MonkeyPatch,
    force_offline: bool,
    mode: str,
    expected: str,
) -> None:
    monkeypatch.delenv("COSCIENTIST_FORCE_MOCK", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-not-called-by-this-test")
    if force_offline:
        monkeypatch.setenv("COSCIENTIST_FORCE_OFFLINE", "1")
    else:
        monkeypatch.delenv("COSCIENTIST_FORCE_OFFLINE", raising=False)

    _, assessor_id = build_assessor(mode, "deepseek/deepseek-chat")

    assert assessor_id == expected


def test_ground_with_llm_assessor_persists_provenance(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("COSCIENTIST_FORCE_OFFLINE", raising=False)
    monkeypatch.delenv("COSCIENTIST_FORCE_MOCK", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-not-called-by-this-test")
    run = seed_run("grounding goal")
    hyp_id = _add(run.id, "Supported", _CONTRADICTED, isolated_db)
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
        db_path=isolated_db,
    )

    async def completion(**_kwargs: Any) -> Any:
        # Legacy evidence-id citations remain accepted even though prompts
        # request passage numbers.
        return completion_response(
            '{"label": "supports", "supporting": '
            f'[{{"passage": "{ev_id}", '
            '"quote": "reduces melanoma tumor growth"}], '
            '"contradicting": []}'
        )

    install_completion_backend(monkeypatch, completion)
    assessor, assessor_id = build_assessor("llm", "deepseek/deepseek-chat")
    with scoped_cache_override(False):
        persist_grounding(
            run.id,
            assess_hypothesis_claims(
                hypotheses.list_hypotheses(run.id),
                evidence_passages(run.id, db_path=isolated_db),
                AssessorSpec(assessor, assessor_id),
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


def test_claim_assessment_holds_no_database_connection(
    isolated_db: str,
) -> None:
    # Provider assessment must precede persistence so SQLite write locks never
    # span network I/O.
    import sqlite3

    hyp = {"id": "h1", "title": "Kinase X inhibition", "statement": _SUPPORTED}

    blocker = sqlite3.connect(isolated_db, timeout=0.5, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        assessed = assess_hypothesis_claims([hyp], as_passages([_SUPPORTED]))
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
        {"id": f"h{i}", "title": f"H{i}", "statement": _SUPPORTED}
        for i in range(8)
    ]
    from app.claims.grounding import AssessorSpec

    assess_hypothesis_claims(
        hyps, as_passages([_SUPPORTED]), AssessorSpec(_slow_assessor)
    )

    assert peak > 1, f"claims were assessed serially (peak concurrency {peak})"


@pytest.mark.parametrize(
    ("hypothesis_count", "claims_each", "calls"), [(13, 17, 13), (1, 25, 2)]
)
def test_batch_assessor_costs_one_call_per_hypothesis_and_splits_dense_ones(
    hypothesis_count: int, claims_each: int, calls: int
) -> None:
    seen: list[int] = []

    def batch(claims: Any, passages: Any) -> Any:
        seen.append(len(claims))
        return [AssessorDraft(label=EntailmentLabel.INSUFFICIENT)] * len(claims)

    statement = " ".join(
        f"Claim number {i} about a dietary change improving outcomes."
        for i in range(claims_each)
    )
    hyps = [
        {"id": f"h{i}", "title": f"H{i}", "statement": statement}
        for i in range(hypothesis_count)
    ]

    assessed = assess_hypothesis_claims(
        hyps,
        as_passages([_SUPPORTED]),
        AssessorSpec(assessor_id="llm:test-model", batch_assessor=batch),
    )

    assert len(seen) == calls
    assert [len(claims) for _, claims in assessed] == [
        claims_each
    ] * hypothesis_count


@pytest.mark.parametrize(
    ("claim", "passage"),
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
    claim: str, passage: str
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


@pytest.mark.parametrize(
    ("claim", "passage"),
    [
        ("The cat sat on a rug.", "The jet flew on a sunny day."),
        (
            "This protein folds with cooperative kinetics.",
            "This ocean circulates with seasonal currents.",
        ),
    ],
)
def test_shared_function_words_do_not_admit_unrelated_evidence(
    claim: str, passage: str
) -> None:
    assert retrieve_passages(claim, as_passages([passage])) == []


def test_short_term_retrieval_keeps_rank_limit_and_stable_ties() -> None:
    passages = as_passages(
        [
            "DNA encodes inherited instructions.",
            "DNA supplies cellular blueprints.",
            "DNA contains hereditary information.",
        ]
    )
    claim = "DNA contains hereditary information."

    ranked = retrieve_passages(claim, passages, top_k=2)

    assert [p.evidence_id for p in ranked] == ["passage-2", "passage-0"]
    assert retrieve_passages(claim, passages, top_k=0) == []


def test_extracts_atomic_claims_and_drops_fragments() -> None:
    text = (
        "Inhibiting kinase X reduces tumor growth in AML cells. "
        "Ok. "
        "The mechanism involves downstream apoptosis signaling. "
        "Inhibiting kinase X reduces tumor growth in AML cells."
    )

    assert extract_atomic_claims(text) == [
        "Inhibiting kinase X reduces tumor growth in AML cells.",
        "The mechanism involves downstream apoptosis signaling.",
    ]


@pytest.mark.parametrize(
    ("gaps", "kept"),
    [
        (
            "Within the retrieved literature, no source tests whether PI3K "
            "inhibition alone reactivates the composite program. "
            "This interaction appears unexplored in the retrieved literature. "
            "This hypothesis is formulated without access to a literature "
            "review; no citation keys are available. "
            "The apoptotic mechanism is not systematically characterized. "
            "Dual blockade has not been tested in this subtype.",
            "Menin inhibition destabilizes c-Myc in KMT2A-rearranged AML.",
        ),
        (
            "We did not find any source in the provided literature directly "
            "testing CDK4/6 inhibitors in human cardiac fibroblasts. "
            "Direct testing of niclosamide in primary HCF under Wnt-active "
            "conditions appears unreported. "
            "The meta-review notes under-explored cytoskeletal control "
            "mechanisms.",
            "Fasudil inhibits ROCK1 and ROCK2 in cardiac fibroblasts.",
        ),
    ],
    ids=["synthetic-gaps", "production-wordings"],
)
def test_extraction_drops_sentences_asserting_an_evidence_gap(
    gaps: str, kept: str
) -> None:
    # Corpus-absence statements are negative existentials no retrieved passage
    # can confirm.
    assert extract_atomic_claims(f"{kept} {gaps}") == [kept]


# Long passages expose union-denominator caps hidden by one-sentence fixtures.
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
_MIDBAND = (
    "Kinase enzymes regulate cellular growth under diverse metabolic "
    "conditions across many organisms."
)


def _passage(text: str) -> EvidencePassage:
    return EvidencePassage("ev-1", text, source="pubmed", url="https://x.org/1")


@pytest.mark.parametrize(
    ("passages", "label", "quote"),
    [
        (
            [
                _passage(
                    "This unrelated review discusses cardiac tissue growth."
                )
            ],
            EntailmentLabel.INSUFFICIENT,
            None,
        ),
        (
            [_passage(_SUPPORTING_ABSTRACT)],
            EntailmentLabel.SUPPORTS,
            "curtailed tumor proliferation",
        ),
        (
            # Literal containment must reach SUPPORTS even in a long passage.
            [
                _passage(
                    _SUPPORTING_ABSTRACT.replace(
                        "These results support",
                        f"{_KINASE_CLAIM} These results support",
                    )
                )
            ],
            EntailmentLabel.SUPPORTS,
            _KINASE_CLAIM,
        ),
        (
            [_passage(_MIDBAND)],
            EntailmentLabel.PARTIAL,
            "kinase enzymes regulate",
        ),
        (
            [
                _passage(_MIDBAND),
                EvidencePassage(
                    "ev-2",
                    "Kinase X inhibition reduces tumor growth across "
                    "several AML cells.",
                ),
            ],
            EntailmentLabel.SUPPORTS,
            "kinase x inhibition reduces",
        ),
        (
            [
                _passage(
                    "Kinase X inhibition reduces tumor growth in AML cells."
                ),
                _passage(
                    "Kinase X inhibition did not reduce tumor growth in AML "
                    "cells."
                ),
            ],
            EntailmentLabel.CONTRADICTS,
            None,
        ),
    ],
    ids=[
        "weak-overlap",
        "strong-topical-overlap",
        "claim-quoted-verbatim",
        "mid-band-overlap",
        "full-support-beats-a-partial-near-miss",
        "contradiction-dominates-support",
    ],
)
def test_the_deterministic_assessor_labels_by_overlap_and_locates_support(
    passages: list[EvidencePassage], label: EntailmentLabel, quote: str | None
) -> None:
    result = assess_claim(_KINASE_CLAIM, passages)

    assert result.label is label
    assert result.assessor
    if label is EntailmentLabel.CONTRADICTS:
        assert result.contradicting_passages
        assert result.is_fundamental_failure
    if label is EntailmentLabel.INSUFFICIENT:
        assert result.supporting_passages == ()
    if quote:
        span = result.supporting_passages[0]
        by_id = {p.evidence_id: p for p in passages}
        assert by_id[span.evidence_id].text[span.start : span.end] == span.quote
        assert quote in span.quote.lower() or span.quote == quote


@pytest.mark.parametrize(
    "label", [EntailmentLabel.SUPPORTS, EntailmentLabel.PARTIAL]
)
def test_a_support_verdict_without_a_locatable_quote_is_downgraded(
    label: EntailmentLabel,
) -> None:
    def fabricating(
        claim: str, passages: list[EvidencePassage]
    ) -> AssessorDraft:
        return AssessorDraft(
            label=label, supporting=(("ev-1", "a quote that is nowhere"),)
        )

    result = assess_claim(
        "Kinase X inhibition reduces tumor growth.",
        [EvidencePassage("ev-1", "Unrelated passage text.")],
        assessor=fabricating,  # type: ignore[arg-type]
        assessor_id="llm:test",
    )

    assert result.label is EntailmentLabel.INSUFFICIENT
    assert result.supporting_passages == ()
    assert result.assessor == "llm:test"


def test_deep_supporting_sentence_in_a_chunked_article_is_located() -> None:
    # Chunk offsets must map deep article quotes back to their parent evidence
    # record.
    filler = "Unrelated background discussion sentence about other topics. "
    needle = "Kinase X inhibition reduces tumor growth in AML cell lines."
    chunks = chunk_evidence_passage(
        "article-99",
        head_text="Title only, no abstract.",
        body_text=(filler * 300) + needle + (" " + filler * 300),
        source="pubmed",
        url="https://example.org/99",
    )
    assert len(chunks) > 1

    result = assess_claim(needle, chunks, top_k=3)

    assert result.label is EntailmentLabel.SUPPORTS
    span = result.supporting_passages[0]
    assert needle in span.quote or span.quote in needle
    assert parent_evidence_id(span.evidence_id) == "article-99"


def test_locate_span_tolerates_whitespace_and_case_not_absent_quotes() -> None:
    passage = EvidencePassage(
        "ev-1", "Kinase X   inhibition reduces tumor growth markedly."
    )

    span = locate_span(passage, "kinase x inhibition REDUCES tumor growth")

    assert span is not None
    assert passage.text[span.start : span.end] == span.quote
    assert span.quote.startswith("Kinase X")
    assert locate_span(passage, "a quote that does not appear") is None
