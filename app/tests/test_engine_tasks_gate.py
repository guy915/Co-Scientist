"""Pre-ranking evidence-gate and semantic-audit tests for the executor."""

import threading
import time
from typing import Any

import pytest
from co_scientist.models import (
    Article,
    Hypothesis,
)

from app import claim_grounding, engine_tasks
from app.claims import (
    AssessorDraft,
    EntailmentLabel,
    deterministic_assessor,
)
from app.config import settings


def _private_corpus_source() -> dict[str, Any]:
    """An uploaded private document that grounds the hypothesis's claim."""
    return {
        "display": (
            "Private scientist source 'Lab notes': Astrocyte lactate "
            "accelerates synaptic ATP recovery."
        ),
        "source_type": "private_document",
        "data": {
            "document_id": "doc-1",
            "title": "Lab notes",
            "excerpt": ("Astrocyte lactate accelerates synaptic ATP recovery."),
            "private": True,
        },
    }


def _install_counting_assessor(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, int]:
    """Patch build_assessor with a call-counting deterministic assessor."""
    calls = {"n": 0}

    def counting(claim: str, passages: Any) -> Any:
        calls["n"] += 1
        return deterministic_assessor(claim, passages)

    monkeypatch.setattr(
        claim_grounding,
        "build_assessor",
        lambda *_: (counting, "counting-v1"),
    )
    return calls


def _install_peak_assessor(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, int]:
    """Patch build_assessor to record peak concurrent claim assessments."""
    state = {"active": 0, "peak": 0}
    lock = threading.Lock()

    def _slow_assessor(claim: str, passages: Any) -> AssessorDraft:
        """Record how many assessments overlap, then stall like a call."""
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(0.05)
        with lock:
            state["active"] -= 1
        return AssessorDraft(label=EntailmentLabel.INSUFFICIENT)

    monkeypatch.setattr(
        claim_grounding,
        "build_assessor",
        lambda *_: (_slow_assessor, "slow-v1"),
    )
    monkeypatch.setattr(settings, "claim_assessor", "llm")
    return state


def _install_overlap_assessor(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, bool]:
    """Patch build_assessor to flag overlap between two hypotheses' claims."""
    in_flight: set[str] = set()
    flags = {"overlapped": False}
    lock = threading.Lock()

    def _slow_assessor(claim: str, passages: Any) -> AssessorDraft:
        """Flag whenever two different hypotheses' claims overlap."""
        owner = "alpha" if "alpha" in claim else "beta"
        with lock:
            in_flight.add(owner)
            if len(in_flight) > 1:
                flags["overlapped"] = True
        time.sleep(0.05)
        with lock:
            in_flight.discard(owner)
        return AssessorDraft(label=EntailmentLabel.INSUFFICIENT)

    monkeypatch.setattr(
        claim_grounding,
        "build_assessor",
        lambda *_: (_slow_assessor, "slow-v1"),
    )
    monkeypatch.setattr(settings, "claim_assessor", "llm")
    return flags


def _multi_claim_state() -> dict[str, Any]:
    """A viable two-claim hypothesis grounded by one supporting article."""
    hypothesis = Hypothesis(
        text=(
            "Astrocyte lactate accelerates synaptic ATP recovery. "
            "Neuronal mitochondria buffer the resulting calcium influx."
        ),
        literature_grounding=(
            "Astrocytes participate in neuronal energy support. "
            "Lactate shuttling is documented in cortical slices."
        ),
        explanation="Glycolytic flux rises before the ATP rebound.",
        experiment="Measure ATP recovery under lactate blockade.",
    )
    hypothesis.review_disposition = "viable"
    return {
        "hypotheses": [hypothesis],
        "articles": [
            Article(
                title="Astrocyte energetics",
                abstract="Astrocytes participate in neuronal energy support.",
            )
        ],
    }


@pytest.mark.asyncio
async def test_pre_ranking_gate_labels_novel_proposal_as_speculative() -> None:
    """A grounded proposal may rank with its novel claim made explicit."""
    hypothesis = Hypothesis(
        text="We hypothesize astrocyte channel X may accelerate ATP recovery.",
        literature_grounding=(
            "Astrocytes participate in neuronal energy support."
        ),
    )
    hypothesis.review_disposition = "viable"
    state = {
        "hypotheses": [hypothesis],
        "articles": [
            Article(
                title="Astrocyte energetics",
                abstract="Astrocytes participate in neuronal energy support.",
            )
        ],
    }

    await engine_tasks._apply_pre_ranking_evidence_gate(state)

    assert hypothesis.review_disposition == "viable"
    gate = hypothesis.enrichments["claim_gate"]
    assert gate["decision"] == "allow"
    speculative = next(
        claim for claim in gate["claims"] if claim["role"] == "speculative"
    )
    assert speculative["label"] == "insufficient"


@pytest.mark.asyncio
async def test_pre_ranking_gate_grounds_claims_in_private_corpus() -> None:
    """A scientist's uploaded document is admissible grounding evidence.

    The private corpus (``context_enrichment_sources``) must count toward the
    pre-ranking evidence gate, not only retrieved literature, so uploaded
    an uploaded supporting document verifies an otherwise-unsupported idea —
    matching the disclosed private-repository behavior (the idea ranks
    throughout; the corpus adds a supports edge).
    """
    hypothesis = Hypothesis(
        text="Astrocyte lactate accelerates synaptic ATP recovery.",
        literature_grounding=(
            "Astrocyte lactate accelerates synaptic ATP recovery."
        ),
    )
    hypothesis.review_disposition = "viable"
    state: dict[str, Any] = {"hypotheses": [hypothesis], "articles": []}
    await engine_tasks._apply_pre_ranking_evidence_gate(state)
    assert hypothesis.review_disposition == "viable"

    state["context_enrichment_sources"] = [_private_corpus_source()]
    await engine_tasks._apply_pre_ranking_evidence_gate(state)

    assert hypothesis.review_disposition == "viable"
    assert hypothesis.enrichments["claim_gate"]["decision"] == "allow"


@pytest.mark.asyncio
async def test_pre_ranking_gate_reuses_unchanged_semantic_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated tournaments do not repay for identical claim assessments."""
    calls = _install_counting_assessor(monkeypatch)
    hypothesis = Hypothesis(
        text="We hypothesize lactate may accelerate ATP recovery.",
        literature_grounding="Astrocyte lactate accelerates ATP recovery.",
    )
    hypothesis.review_disposition = "viable"
    state = {
        "hypotheses": [hypothesis],
        "articles": [
            Article(
                title="Astrocyte energetics",
                abstract="Astrocyte lactate accelerates ATP recovery.",
                source_id="PMID-1",
            )
        ],
    }

    await engine_tasks._apply_pre_ranking_evidence_gate(state)
    first_call_count = calls["n"]
    await engine_tasks._apply_pre_ranking_evidence_gate(state)

    assert first_call_count > 0
    assert calls["n"] == first_call_count
    assert hypothesis.enrichments["claim_gate"]["input_fingerprint"]


@pytest.mark.asyncio
async def test_pre_ranking_gate_assesses_literature_rationale() -> None:
    """Records each claim's label; an unsupported rationale stays rankable."""
    hypothesis = Hypothesis(
        text="Astrocyte lactate accelerates synaptic ATP recovery.",
        literature_grounding=(
            "A fictional kinase completely reverses neuronal aging."
        ),
    )
    hypothesis.review_disposition = "viable"
    state = {
        "hypotheses": [hypothesis],
        "articles": [
            Article(
                title="Astrocyte energetics",
                abstract=(
                    "Astrocyte lactate accelerates synaptic ATP recovery."
                ),
            )
        ],
    }

    await engine_tasks._apply_pre_ranking_evidence_gate(state)

    assert hypothesis.review_disposition == "viable"
    claims = hypothesis.enrichments["claim_gate"]["claims"]
    assert [claim["label"] for claim in claims] == [
        "supports",
        "insufficient",
    ]


@pytest.mark.asyncio
async def test_pre_ranking_gate_assesses_claims_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate must assess a run's claims in parallel, not one at a time.

    Every claim is assessed independently, so overlapping them changes no
    verdict -- only how long the phase takes. With the LLM assessor each is a
    synchronous provider call, and run one at a time this node was the
    longest serial stretch of a finished run: measured in production,
    ``engine.node.ranking`` was 26% of an express run's wall clock, nearly
    all of it this gate. The provider is not the constraint -- twenty-four
    concurrent completions return in the same wall clock as four.
    """
    probe = _install_peak_assessor(monkeypatch)
    state = _multi_claim_state()

    await engine_tasks._apply_pre_ranking_evidence_gate(state)

    claims = state["hypotheses"][0].enrichments["claim_gate"]["claims"]
    assert len(claims) > 1
    peak = probe["peak"]
    assert peak > 1, f"claims were assessed serially (peak concurrency {peak})"


@pytest.mark.asyncio
async def test_pre_ranking_gate_overlaps_claims_across_hypotheses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole run's claims are in flight together, not one idea at a time.

    Measured in production a hypothesis carries 7-25 atomic claims and a run
    reaches this gate with dozens, so assessing one hypothesis to completion
    before starting the next leaves most of the wave idle. Claims are
    independent across hypotheses as well as within one, so the gate flattens
    them into a single bounded wave.
    """
    flags = _install_overlap_assessor(monkeypatch)
    first = Hypothesis(
        text=(
            "Alpha lactate accelerates alpha ATP recovery. "
            "Alpha mitochondria buffer the alpha calcium influx."
        ),
        literature_grounding="Alpha astrocytes support alpha metabolism.",
    )
    second = Hypothesis(
        text=(
            "Beta lactate accelerates beta ATP recovery. "
            "Beta mitochondria buffer the beta calcium influx."
        ),
        literature_grounding="Beta astrocytes support beta metabolism.",
    )
    for hypothesis in (first, second):
        hypothesis.review_disposition = "viable"
    state = {"hypotheses": [first, second], "articles": []}

    await engine_tasks._apply_pre_ranking_evidence_gate(state)

    assert first.enrichments["claim_gate"]["claims"]
    assert second.enrichments["claim_gate"]["claims"]
    assert flags["overlapped"], "hypotheses were assessed one after another"


@pytest.mark.asyncio
async def test_pre_ranking_gate_ignores_contradicted_go_no_go() -> None:
    """R14-20's Go/No-Go pilot-plan criteria can never block a hypothesis.

    ``_harvest_hypothesis_claims`` reads ``hypothesis.experiment`` -- which
    carries R14-20's ``**Go:**``/``**No-Go:**`` threshold lines -- as well as
    the statement/grounding/explanation fields, and tags every claim it
    finds there "speculative" (see the field-role tuple in
    ``_harvest_hypothesis_claims``). ``_apply_gate_verdict`` then calls
    ``publication_gate`` with ``allow_speculative=True`` and that same role
    map as ``explicitly_speculative_claims``, which excuses a speculative
    claim from blocking whether the evidence merely fails to support it
    (``allow_speculative``) or actively contradicts it (named in
    ``explicitly_speculative_claims`` -- the one exemption
    ``publication_gate`` grants a *contradicted* claim). This hypothesis's
    evidence pool is built to literally contradict its own Go/No-Go
    criteria, markdown markers and all -- the worst case a pilot-plan
    threshold statement can put in front of the assessor -- and the gate
    must still let it through, proving the threshold text cannot gate
    anything even when the evidence disagrees with it outright.

    The final, report-facing grounding pass
    (``claim_grounding_assess._CLAIM_FIELD_ROLES``) is a separate,
    independent guarantee: it never reads ``experiment`` at all, so this
    threshold text never reaches a persisted ``claim_evidence`` row or the
    "Unverified" badge either. This test covers the one path that does read
    it.
    """
    hypothesis = Hypothesis(
        text="Inhibiting the target restores homeostasis in the model.",
        experiment=(
            "1. Run the pilot assay in the xenograft model.\n"
            "**Go:** Tumor regression exceeds fifty percent in the"
            " xenograft model.\n"
            "**No-Go:** Tumor regression remains below ten percent in the"
            " xenograft model."
        ),
    )
    hypothesis.review_disposition = "viable"
    state = {
        "hypotheses": [hypothesis],
        "articles": [
            Article(
                title="Xenograft regression trial",
                abstract=(
                    "Tumor regression did not exceed fifty percent in the"
                    " xenograft model in this trial."
                ),
            )
        ],
    }

    await engine_tasks._apply_pre_ranking_evidence_gate(state)

    assert hypothesis.review_disposition == "viable"
    gate = hypothesis.enrichments["claim_gate"]
    assert gate["decision"] == "allow"
    go_no_go_claims = [
        claim for claim in gate["claims"] if "**Go:**" in claim["claim"]
    ]
    assert go_no_go_claims, "the Go/No-Go claim was not extracted at all"
    assert all(claim["role"] == "speculative" for claim in go_no_go_claims)
    assert any(claim["label"] == "contradicts" for claim in go_no_go_claims), (
        "test setup did not actually produce a contradiction to be excused"
    )


@pytest.mark.asyncio
async def test_pre_ranking_gate_skips_hypotheses_review_already_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An idea the initial review gate already barred is never assessed.

    ``inaccurate``/``non_novel``/``unsafe`` can never reach the tournament
    (``Hypothesis.is_rankable``), and the initial review gate never
    reverses those verdicts -- so spending a wave of provider calls on
    their claims buys nothing. Only ``evidence_blocked`` (this gate's own,
    reversible verdict) must still be reassessed; see the sibling test.
    """
    calls = _install_counting_assessor(monkeypatch)
    rejected = Hypothesis(text="A rejected idea about lactate.")
    rejected.review_disposition = "inaccurate"
    state = {"hypotheses": [rejected], "articles": []}

    await engine_tasks._apply_pre_ranking_evidence_gate(state)

    assert calls["n"] == 0
    assert "claim_gate" not in rejected.enrichments
    assert rejected.review_disposition == "inaccurate"


@pytest.mark.asyncio
async def test_pre_ranking_gate_reassesses_changed_evidence_blocked_idea(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A previously blocked idea is reassessed once its text changes.

    ``evidence_blocked`` is this gate's own verdict, not the initial
    review's, so an idea it blocked must stay reassessable -- unlike a
    disposition the initial review gate decided for good (the sibling
    test above). Revising the hypothesis's text changes its input
    fingerprint, so the fingerprint cache cannot be the reason it is
    skipped; only a disposition-based skip could wrongly bar it here.
    """
    calls = _install_counting_assessor(monkeypatch)
    hypothesis = Hypothesis(text="stale, previously-blocked text")
    hypothesis.review_disposition = "evidence_blocked"
    hypothesis.enrichments["claim_gate"] = {
        "decision": "block",
        "reason": "a prior contradicted claim",
        "assessor": "counting-v1",
        "input_fingerprint": "stale-fingerprint",
        "prior_review_disposition": "viable",
        "claims": [],
    }
    hypothesis.text = "Astrocyte lactate accelerates synaptic ATP recovery."
    state: dict[str, Any] = {
        "hypotheses": [hypothesis],
        "articles": [
            Article(
                title="Astrocyte energetics",
                abstract=(
                    "Astrocyte lactate accelerates synaptic ATP recovery."
                ),
            )
        ],
    }

    await engine_tasks._apply_pre_ranking_evidence_gate(state)

    assert calls["n"] > 0
    assert hypothesis.review_disposition == "viable"
