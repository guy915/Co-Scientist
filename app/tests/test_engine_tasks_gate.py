"""Pre-ranking evidence-gate and semantic-audit tests for the executor."""

from typing import Any

import pytest
from co_scientist.models import (
    Article,
    Hypothesis,
)

from app import engine_tasks
from app.config import settings


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

    state["context_enrichment_sources"] = [
        {
            "display": (
                "Private scientist source 'Lab notes': Astrocyte lactate "
                "accelerates synaptic ATP recovery."
            ),
            "source_type": "private_document",
            "data": {
                "document_id": "doc-1",
                "title": "Lab notes",
                "excerpt": (
                    "Astrocyte lactate accelerates synaptic ATP recovery."
                ),
                "private": True,
            },
        }
    ]
    await engine_tasks._apply_pre_ranking_evidence_gate(state)

    assert hypothesis.review_disposition == "viable"
    assert hypothesis.enrichments["claim_gate"]["decision"] == "allow"


@pytest.mark.asyncio
async def test_pre_ranking_gate_reuses_unchanged_semantic_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated tournaments do not repay for identical claim assessments."""
    from app import claim_grounding
    from app.claims import deterministic_assessor

    calls = 0

    def counting_assessor(claim: str, passages: Any) -> Any:
        nonlocal calls
        calls += 1
        return deterministic_assessor(claim, passages)

    monkeypatch.setattr(
        claim_grounding,
        "build_assessor",
        lambda *_: (counting_assessor, "counting-v1"),
    )
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
    first_call_count = calls
    await engine_tasks._apply_pre_ranking_evidence_gate(state)

    assert first_call_count > 0
    assert calls == first_call_count
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
    import threading
    import time as _time

    from app import claim_grounding
    from app.claims import AssessorDraft, EntailmentLabel

    active = 0
    peak = 0
    lock = threading.Lock()

    def _slow_assessor(claim: str, passages: Any) -> AssessorDraft:
        """Record how many assessments overlap, then stall like a call."""
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        _time.sleep(0.05)
        with lock:
            active -= 1
        return AssessorDraft(label=EntailmentLabel.INSUFFICIENT)

    monkeypatch.setattr(
        claim_grounding,
        "build_assessor",
        lambda *_: (_slow_assessor, "slow-v1"),
    )
    monkeypatch.setattr(settings, "claim_assessor", "llm")
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

    assert len(hypothesis.enrichments["claim_gate"]["claims"]) > 1
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
    import threading
    import time as _time

    from app import claim_grounding
    from app.claims import AssessorDraft, EntailmentLabel

    in_flight: set[str] = set()
    overlapped = False
    lock = threading.Lock()

    def _slow_assessor(claim: str, passages: Any) -> AssessorDraft:
        """Flag whenever two different hypotheses' claims overlap."""
        nonlocal overlapped
        owner = "alpha" if "alpha" in claim else "beta"
        with lock:
            in_flight.add(owner)
            if len(in_flight) > 1:
                overlapped = True
        _time.sleep(0.05)
        with lock:
            in_flight.discard(owner)
        return AssessorDraft(label=EntailmentLabel.INSUFFICIENT)

    monkeypatch.setattr(
        claim_grounding,
        "build_assessor",
        lambda *_: (_slow_assessor, "slow-v1"),
    )
    monkeypatch.setattr(settings, "claim_assessor", "llm")
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
    assert overlapped, "hypotheses were assessed one after another"
