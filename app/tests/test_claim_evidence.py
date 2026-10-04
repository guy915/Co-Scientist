from __future__ import annotations

import logging
from collections.abc import Sequence

import pytest

from app.claims import (
    AssessorDraft,
    ClaimAssessment,
    EntailmentLabel,
    EvidencePassage,
    GateDecision,
    _locate_all,
    as_passages,
    assess_claim,
    assess_claims_batch,
    deterministic_assessor,
    publication_gate,
)
from app.claims.assessor import _CONTRADICTION_MARKERS
from app.evidence_chunking import (
    CHUNK_MAX_CHARS,
    CHUNK_OVERLAP_CHARS,
    chunk_evidence_passage,
    parent_evidence_id,
)

# Verbatim production pairs exposed whole-passage negation paired with unrelated
# or confirming quotes.

# Greek letters are verbatim source data and must not be transliterated.
# ruff: noqa: RUF001


# Negation in abstract boilerplate must not contradict an unrelated cited
# sentence.
_UNRELATED_NEGATION = "Body weight did not differ between groups."


def _passage(*sentences: str) -> EvidencePassage:
    return EvidencePassage(
        evidence_id="e1",
        text=" ".join(sentences),
        source="pubmed",
        url="https://example.org/1",
    )


def _quotes(spans: Sequence[object]) -> list[str]:
    return [getattr(span, "quote", "") for span in spans]


def _carries_a_marker(quote: str) -> bool:
    lowered = quote.lower()
    return any(marker in lowered for marker in _CONTRADICTION_MARKERS)


_REDUCTION_CLAIM = (
    "Together, these actions reduce collagen synthesis and α-SMA "
    "expression, attenuating the fibrotic phenotype."
)
_REDUCTION_QUOTE = (
    "Treatment with LGK-974 significantly reduced both α-SMA and "
    "collagen type I expression, whereas ETC-159 selectively decreased "
    "collagen type I."
)


def test_confirmatory_quote_is_not_a_contradiction() -> None:
    passage = _passage(
        "Wnt inhibition and the fibrotic phenotype in cardiac fibroblasts.",
        _REDUCTION_QUOTE,
        _UNRELATED_NEGATION,
    )
    result = assess_claim(_REDUCTION_CLAIM, [passage])
    assert result.label is not EntailmentLabel.CONTRADICTS
    assert _REDUCTION_QUOTE not in _quotes(result.contradicting_passages)


_METFORMIN_CLAIM = (
    "Metformin activates AMPK in human cardiac fibroblasts, leading to "
    "inhibitory phosphorylation of Smad3 (Ser203/207) and suppression of "
    "HIF-1α-mediated glycolysis, thereby blocking TGF-β-induced "
    "myofibroblast transition and collagen deposition."
)
_PIRFENIDONE_QUOTE = (
    "Furthermore, pirfenidone attenuated TGF-β1- and CTHRC1-induced "
    "fibroblast activity, upregulation of bone morphogenic protein-4"
    "(BMP-4)/Gremlin1, and downregulation of α-smooth muscle actin, "
    "fibronectin, and FHL2, similar to that observed post-CTHRC1 inhibition."
)


def test_off_drug_quote_is_not_a_contradiction() -> None:
    # On-topic padding makes the old whole-passage contradiction branch fire;
    # otherwise both paths pass.
    passage = _passage(
        "Pirfenidone attenuates lung fibrotic fibroblast responses to "
        "transforming growth factor-β1.",
        _PIRFENIDONE_QUOTE,
        "Myofibroblast transition and collagen deposition were assessed in "
        "human cardiac fibroblasts after TGF-β1 stimulation.",
        "AMPK phosphorylation, Smad3 phosphorylation and glycolysis were "
        "measured; HIF-1α protein was quantified.",
        _UNRELATED_NEGATION,
    )
    result = assess_claim(_METFORMIN_CLAIM, [passage])
    assert result.label is not EntailmentLabel.CONTRADICTS
    assert _PIRFENIDONE_QUOTE not in _quotes(result.contradicting_passages)


_AMPK_CLAIM = (
    "Metformin enters cardiac fibroblasts and activates AMPK via LKB1."
)
_GLUCOSE_QUOTE = (
    "We found that glucose starvation transiently activates AMPK, whereas "
    "changes in glucagon and insulin levels had no impact on AMPK."
)


def test_off_stimulus_quote_is_not_a_contradiction() -> None:
    passage = _passage(
        "AMPK activation in fibroblasts under nutrient stress.",
        _GLUCOSE_QUOTE,
        _UNRELATED_NEGATION,
    )
    result = assess_claim(_AMPK_CLAIM, [passage])
    assert result.label is not EntailmentLabel.CONTRADICTS
    assert _GLUCOSE_QUOTE not in _quotes(result.contradicting_passages)


_ON_SUBJECT_NEGATION = (
    "Metformin did not reduce collagen I expression in human cardiac "
    "fibroblasts."
)


def test_on_subject_negation_still_contradicts() -> None:
    claim = (
        "Metformin reduces collagen I expression in human cardiac fibroblasts."
    )
    passage = _passage(
        "Metformin and collagen I expression in human cardiac fibroblasts.",
        "Cells were treated for 48 hours.",
        _ON_SUBJECT_NEGATION,
    )
    result = assess_claim(claim, [passage])
    assert result.label is EntailmentLabel.CONTRADICTS
    assert _ON_SUBJECT_NEGATION in _quotes(result.contradicting_passages)


def test_cited_contradiction_quote_carries_the_negation() -> None:
    # The best-matching sentence may confirm the claim while another negates it;
    # cite the actual opposing quote.
    claim = (
        "Metformin reduces collagen I expression in human cardiac fibroblasts."
    )
    passage = _passage(
        "Metformin reduces collagen I expression in human cardiac "
        "fibroblasts, we hypothesized.",
        _ON_SUBJECT_NEGATION,
    )
    draft = deterministic_assessor(claim, [passage])
    assert draft.label is EntailmentLabel.CONTRADICTS
    for _, quote in draft.contradicting:
        assert _carries_a_marker(quote)


def test_llm_assessor_fallback_cannot_yield_an_unfounded_contradiction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Provider failures retain llm provenance on deterministic fallbacks; those
    # verdicts need grounding guards too.
    from app.claims import verifier as claim_verifier

    monkeypatch.setattr(
        claim_verifier, "_call_claim_json", lambda *a, **k: None
    )
    assessor, assessor_id = claim_verifier.make_llm_assessor("m")
    passage = _passage(
        "Wnt inhibition and the fibrotic phenotype in cardiac fibroblasts.",
        _REDUCTION_QUOTE,
        _UNRELATED_NEGATION,
    )
    draft = assessor(_REDUCTION_CLAIM, [passage])
    assert assessor_id == "llm:m"
    assert draft.label is not EntailmentLabel.CONTRADICTS


@pytest.mark.parametrize("batch", [False, True])
def test_prompt_render_failure_keeps_deterministic_fallback(
    monkeypatch: pytest.MonkeyPatch, batch: bool
) -> None:
    from app.claims import verifier

    rendered: list[bool] = []

    def broken_prompt(*_args: object) -> str:
        rendered.append(True)
        raise ValueError("unrenderable evidence")

    monkeypatch.setattr(
        verifier,
        "_batch_entailment_prompt" if batch else "_entailment_prompt",
        broken_prompt,
    )
    passage = _passage(_REDUCTION_QUOTE)
    if batch:
        assessor, assessor_id = verifier.make_llm_batch_assessor("m")
        result = assess_claims_batch(
            [_REDUCTION_CLAIM],
            [passage],
            batch_assessor=assessor,
            assessor_id=assessor_id,
        )[0]
    else:
        single, assessor_id = verifier.make_llm_assessor("m")
        result = assess_claim(
            _REDUCTION_CLAIM,
            [passage],
            assessor=single,
            assessor_id=assessor_id,
        )
    expected = deterministic_assessor(_REDUCTION_CLAIM, [passage])
    assert rendered == [True]
    assert result.label is expected.label


def test_batch_fallback_cannot_yield_an_unfounded_contradiction() -> None:
    # Per-claim fallback in a batch retains the batch assessor id even though
    # the method is deterministic.
    passage = _passage(
        "Wnt inhibition and the fibrotic phenotype in cardiac fibroblasts.",
        _REDUCTION_QUOTE,
        _UNRELATED_NEGATION,
    )
    (result,) = assess_claims_batch(
        [_REDUCTION_CLAIM],
        [passage],
        batch_assessor=lambda claims, _: [None] * len(claims),
        assessor_id="llm:m",
    )
    assert result.assessor == "llm:m"
    assert result.label is not EntailmentLabel.CONTRADICTS
    assert _REDUCTION_QUOTE not in _quotes(result.contradicting_passages)


_CONTRADICTED_CLAIM = "Kinase X inhibition reduces AML tumor growth."


def _contradicted_assessments() -> list[ClaimAssessment]:
    return [
        assess_claim(
            _CONTRADICTED_CLAIM,
            as_passages(
                ["Kinase X inhibition did not reduce AML tumor growth."]
            ),
        )
    ]


def test_gate_blocks_contradicted_hypothesis() -> None:
    assessments = _contradicted_assessments()
    result = publication_gate(assessments)
    assert result.decision is GateDecision.BLOCK
    assert result.contradicted_claims
    # Speculation permission must never soften categorical contradiction
    # blocking.
    loosened = publication_gate(
        assessments, allow_speculative=True, require_supported_claim=False
    )
    assert loosened.decision is GateDecision.BLOCK


def test_gate_allows_a_contradicted_claim_the_idea_only_proposes() -> None:
    # Only contradicted established facts block; contrary findings about
    # proposals must remain publishable.
    assessments = _contradicted_assessments()
    result = publication_gate(
        assessments,
        explicitly_speculative_claims={_CONTRADICTED_CLAIM},
    )
    assert result.decision is GateDecision.ALLOW
    assert result.contradicted_claims == (_CONTRADICTED_CLAIM,)
    assert "contradicted" in result.reason


def test_gate_blocks_a_categorical_contradiction_beside_a_speculative_one() -> (
    None
):
    grounding = "Kinase X inhibition reduces AML relapse rates."
    assessments = [
        *_contradicted_assessments(),
        assess_claim(
            grounding,
            as_passages(
                [
                    "Kinase X inhibition did not reduce AML relapse rates; "
                    "there was no significant effect on relapse."
                ]
            ),
        ),
    ]
    result = publication_gate(
        assessments,
        explicitly_speculative_claims={_CONTRADICTED_CLAIM},
    )
    assert result.decision is GateDecision.BLOCK
    assert result.failed_claims == (grounding,)


def test_gate_blocks_unsupported_unless_speculative_allowed() -> None:
    assessments = [
        assess_claim(
            "Kinase X inhibition reduces AML tumor growth.",
            as_passages(
                ["An unrelated passage about photosynthesis in plants."]
            ),
        )
    ]
    assert publication_gate(assessments).decision is GateDecision.BLOCK
    allowed = publication_gate(assessments, allow_speculative=True)
    assert allowed.decision is GateDecision.ALLOW
    assert allowed.unsupported_claims
    assert allowed.speculative_claims == allowed.unsupported_claims


def test_gate_allows_only_explicitly_speculative_insufficient_claims() -> None:
    proposed = assess_claim(
        "We hypothesize kinase X may alter neuronal recovery.",
        as_passages(["An unrelated passage about photosynthesis."]),
    )
    categorical = assess_claim(
        "Kinase X is established as the neuronal recovery controller.",
        as_passages(["An unrelated passage about photosynthesis."]),
    )

    blocked = publication_gate(
        [proposed, categorical],
        explicitly_speculative_claims={proposed.claim},
    )
    assert blocked.decision is GateDecision.BLOCK
    assert blocked.speculative_claims == (proposed.claim,)

    allowed = publication_gate(
        [proposed], explicitly_speculative_claims={proposed.claim}
    )
    assert allowed.decision is GateDecision.ALLOW
    assert allowed.speculative_claims == (proposed.claim,)

    ungrounded = publication_gate(
        [proposed],
        explicitly_speculative_claims={proposed.claim},
        require_supported_claim=True,
    )
    assert ungrounded.decision is GateDecision.BLOCK
    assert ungrounded.reason == "no evidence-supported contextual claim"


def test_gate_allows_supported_hypothesis() -> None:
    assessments = [
        assess_claim(
            "Kinase X inhibition reduces AML tumor growth.",
            as_passages(
                ["Kinase X inhibition reduces AML tumor growth in cell lines."]
            ),
        )
    ]
    result = publication_gate(assessments)
    assert result.decision is GateDecision.ALLOW


def test_gate_counts_partial_as_a_supported_claim() -> None:
    # Partial support is relevant and consistent, so it satisfies the
    # minimum-support gate.
    partial = assess_claim(
        "Inhibiting kinase X reduces tumor growth in AML cells.",
        as_passages(
            [
                "Kinase enzymes regulate cellular growth under diverse "
                "metabolic conditions across many organisms."
            ]
        ),
    )
    assert partial.label is EntailmentLabel.PARTIAL
    result = publication_gate([partial], require_supported_claim=True)
    assert result.decision is GateDecision.ALLOW


def test_gate_blocks_hypothesis_with_no_claims() -> None:
    assert publication_gate([]).decision is GateDecision.BLOCK


def test_revision_is_reassessed() -> None:
    claim = "Kinase X inhibition reduces AML tumor growth."
    contradicted = assess_claim(
        claim,
        as_passages(["Kinase X inhibition did not reduce AML tumor growth."]),
    )
    assert contradicted.label is EntailmentLabel.CONTRADICTS

    revised = "Combined kinase X and cofactor W inhibition reduces AML growth."
    supported = assess_claim(
        revised,
        as_passages(
            [
                "Combined kinase X and cofactor W inhibition reduces AML "
                "growth durably in patient-derived cells."
            ]
        ),
    )
    assert supported.label is EntailmentLabel.SUPPORTS


# Accept passage numbers and legacy ids while requiring verbatim quotes in
# evidence actually shown.


_PASSAGES = (
    EvidencePassage(
        evidence_id="7f1c9a20-1b2e-4f3a-9c8d-0a1b2c3d4e5f#0",
        text=(
            "Fasudil could down-regulate RhoA, GEF-H1, and phosphorylated "
            "GEF-H1 to inhibit ROCK signaling and further reduce Col I "
            "expression and the myofibroblast proportion."
        ),
        source="pubmed",
        url="https://example.org/fasudil",
    ),
    EvidencePassage(
        evidence_id="2b8e4d11-5c6f-4a7b-8d9e-1f2a3b4c5d6e#1",
        text=(
            "Verteporfin has been shown to effectively inhibit YAP-TEAD "
            "function in vivo in cardiac fibroblasts."
        ),
        source="web",
        url="https://example.org/verteporfin",
    ),
)

_CLAIM = "Fasudil reduces collagen I expression in cardiac fibroblasts."


def test_citation_by_passage_number_resolves() -> None:
    # Bracketed passage numbers are valid citations because they are exactly
    # what the prompt shows.
    spans = _locate_all(
        (("1", "reduce Col I expression and the myofibroblast proportion"),),
        _PASSAGES,
    )
    assert [s.evidence_id for s in spans] == [_PASSAGES[0].evidence_id]
    assert spans[0].source == "pubmed"


def test_numeric_evidence_id_cannot_shadow_a_passage_number() -> None:
    passages = (
        EvidencePassage("other", "The first passage has this claim quote."),
        EvidencePassage("1", "The second passage is unrelated."),
    )
    spans = _locate_all((("1", "claim quote"),), passages)
    assert [s.evidence_id for s in spans] == ["other"]


def test_internal_numeric_evidence_id_is_not_a_passage_number() -> None:
    passages = (
        EvidencePassage("other", "The first passage is unrelated."),
        EvidencePassage("1", "The second passage has this claim quote."),
    )
    spans = _locate_all(
        (("1", "claim quote"),), passages, cites_evidence_ids=True
    )
    assert [s.evidence_id for s in spans] == ["1"]


def test_out_of_range_number_cannot_resolve_as_an_evidence_id() -> None:
    passages = (EvidencePassage("99", "This quote is from another article."),)
    assert _locate_all((("99", "another article"),), passages) == []


def test_deterministic_assessment_keeps_numeric_evidence_id() -> None:
    passage = EvidencePassage(
        "12345", "Fasudil reduces collagen I expression in cardiac fibroblasts."
    )
    result = assess_claim(_CLAIM, [passage])
    assert result.label is EntailmentLabel.SUPPORTS
    assert [s.evidence_id for s in result.supporting_passages] == ["12345"]


def test_custom_assessor_keeps_numeric_evidence_id_by_default() -> None:
    passage = EvidencePassage(
        "12345", "Fasudil reduces collagen I expression in cardiac fibroblasts."
    )
    draft = AssessorDraft(
        EntailmentLabel.SUPPORTS,
        supporting=(("12345", "reduces collagen I expression"),),
    )
    result = assess_claim(
        _CLAIM, [passage], assessor=lambda _claim, _shown: draft
    )
    assert result.label is EntailmentLabel.SUPPORTS
    assert [s.evidence_id for s in result.supporting_passages] == ["12345"]


def test_batch_fallback_keeps_numeric_evidence_id() -> None:
    passage = EvidencePassage(
        "12345", "Fasudil reduces collagen I expression in cardiac fibroblasts."
    )
    result = assess_claims_batch(
        [_CLAIM],
        [passage],
        batch_assessor=lambda _claims, _shown: [None],
        assessor_id="llm:test",
    )[0]
    assert result.label is EntailmentLabel.SUPPORTS
    assert [s.evidence_id for s in result.supporting_passages] == ["12345"]


def test_internal_numeric_parent_id_resolves_later_chunk() -> None:
    passages = (
        EvidencePassage("12345#0", "First article chunk."),
        EvidencePassage("12345#1", "Later article chunk has the claim quote."),
    )
    spans = _locate_all(
        (("12345", "claim quote"),),
        passages,
        cites_evidence_ids=True,
    )
    assert [s.evidence_id for s in spans] == ["12345#1"]


def test_citation_dropping_the_chunk_suffix_resolves() -> None:
    spans = _locate_all(
        (
            (
                "7f1c9a20-1b2e-4f3a-9c8d-0a1b2c3d4e5f",
                "inhibit ROCK signaling",
            ),
        ),
        _PASSAGES,
    )
    assert [s.evidence_id for s in spans] == [_PASSAGES[0].evidence_id]


def test_parent_id_resolves_quote_in_later_chunk() -> None:
    later = EvidencePassage(
        evidence_id="7f1c9a20-1b2e-4f3a-9c8d-0a1b2c3d4e5f#1",
        text="A later chunk describes a separate measured endpoint.",
    )
    spans = _locate_all(
        (
            (
                "7f1c9a20-1b2e-4f3a-9c8d-0a1b2c3d4e5f",
                "separate measured endpoint",
            ),
        ),
        (*_PASSAGES, later),
    )
    assert [s.evidence_id for s in spans] == [later.evidence_id]


def test_verbatim_quote_under_a_different_known_id_is_dropped() -> None:
    spans = _locate_all(
        ((_PASSAGES[0].evidence_id, "inhibit YAP-TEAD function in vivo"),),
        _PASSAGES,
    )
    assert spans == []


def test_verbatim_quote_under_an_unknown_id_is_dropped() -> None:
    spans = _locate_all(
        (("unrecognized-legacy-id", "inhibit YAP-TEAD function in vivo"),),
        _PASSAGES,
    )
    assert spans == []


def test_batch_unknown_key_cannot_borrow_another_shown_passage() -> None:
    passages = (
        EvidencePassage("ev-0", "Kinase X inhibition reduces tumor growth."),
        EvidencePassage("ev-1", "The response occurred in AML cell lines."),
    )
    draft = AssessorDraft(
        EntailmentLabel.SUPPORTS,
        supporting=(("99", "in AML cell lines"),),
        cites_evidence_ids=False,
    )
    results = assess_claims_batch(
        ["Kinase X inhibition reduces tumor growth."],
        passages,
        batch_assessor=lambda _claims, _shown: [draft],
        assessor_id="llm:test",
    )
    assert results[0].label is EntailmentLabel.INSUFFICIENT
    assert results[0].supporting_passages == ()


def test_quote_in_no_shown_passage_is_still_dropped() -> None:
    assert (
        _locate_all(
            ((_PASSAGES[0].evidence_id, "olaparib cures cardiac fibrosis"),),
            _PASSAGES,
        )
        == []
    )


def test_dropped_citations_are_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Discarded citations need diagnostics or insufficient verdicts become
    # impossible to explain.
    with caplog.at_level(logging.INFO, logger="app.claims"):
        _locate_all(
            (
                (_PASSAGES[0].evidence_id, "quote that is nowhere"),
                (_PASSAGES[0].evidence_id, "inhibit ROCK signaling"),
            ),
            _PASSAGES,
        )
    assert "1" in caplog.text
    assert "could not be located" in caplog.text


def test_batched_verdict_citing_by_number_keeps_its_label() -> None:

    def _by_number_assessor(
        claims: Sequence[str], passages: Sequence[EvidencePassage]
    ) -> Sequence[AssessorDraft | None]:
        return [
            AssessorDraft(
                label=EntailmentLabel.SUPPORTS,
                supporting=(("[1]", "reduce Col I expression"),),
                cites_evidence_ids=False,
            )
            for _ in claims
        ]

    results: list[ClaimAssessment] = assess_claims_batch(
        [_CLAIM],
        list(_PASSAGES),
        batch_assessor=_by_number_assessor,
        assessor_id="llm:test",
    )
    assert results[0].label is EntailmentLabel.SUPPORTS
    assert results[0].supporting_passages[0].evidence_id == (
        _PASSAGES[0].evidence_id
    )


def test_single_claim_verdict_citing_by_number_keeps_its_label() -> None:

    def _by_number_assessor(
        claim: str, passages: Sequence[EvidencePassage]
    ) -> AssessorDraft:
        return AssessorDraft(
            label=EntailmentLabel.PARTIAL,
            supporting=(("passage 1", "reduce Col I expression"),),
            cites_evidence_ids=False,
        )

    result = assess_claim(
        _CLAIM,
        list(_PASSAGES),
        assessor=_by_number_assessor,
        assessor_id="llm:test",
    )
    assert result.label is EntailmentLabel.PARTIAL
    assert result.supporting_passages[0].evidence_id == (
        _PASSAGES[0].evidence_id
    )


# Whole-article grounding multiplies prompt cost; recurring evidence must
# precede variable claims for caching.


def test_long_body_yields_multiple_chunks_under_the_size_limit() -> None:
    paragraph = "Kinase X inhibition reduces tumor growth. " * 40
    body = "\n\n".join([paragraph] * 25)
    assert len(body) > 40_000

    passages = chunk_evidence_passage(
        "art-1",
        head_text="Title. Abstract sentence.",
        body_text=body,
        source="pubmed",
        url="https://example.org/1",
    )

    assert len(passages) > 1
    # Chunk ceilings include the overlap prefix and its joining space.
    bound = CHUNK_MAX_CHARS + CHUNK_OVERLAP_CHARS + 1
    for passage in passages:
        assert len(passage.text) <= bound


def test_chunks_carry_provenance_back_to_the_parent_article() -> None:
    body = ("Alpha sentence one. Beta sentence two.\n\n") * 200
    passages = chunk_evidence_passage(
        "pmid-42",
        head_text="Title only.",
        body_text=body,
        source="pubmed",
        url="https://example.org/42",
    )

    assert len(passages) > 1
    for passage in passages:
        assert passage.evidence_id.startswith("pmid-42#")
        assert parent_evidence_id(passage.evidence_id) == "pmid-42"


def test_abstract_only_article_is_unchanged() -> None:
    passages = chunk_evidence_passage(
        "pmid-7",
        head_text="Title. A short abstract about kinase inhibition.",
        body_text="",
        source="pubmed",
        url="https://example.org/7",
    )

    assert len(passages) == 1
    assert passages[0].evidence_id == "pmid-7"
    assert (
        passages[0].text == "Title. A short abstract about kinase inhibition."
    )


def test_parent_evidence_id_is_a_no_op_on_an_unchunked_id() -> None:
    assert parent_evidence_id("pmid-7") == "pmid-7"
    assert parent_evidence_id("private-document-with-a-hash#tag") == (
        "private-document-with-a-hash#tag"
    )


def test_a_deep_supporting_sentence_survives_chunking() -> None:
    filler = "Unrelated background discussion sentence number filler. "
    needle = "Kinase X inhibition reduces tumor growth in AML cell lines."
    body = (filler * 400) + needle + (" " + filler * 400)

    passages = chunk_evidence_passage(
        "art-deep",
        head_text="Title.",
        body_text=body,
        source="pubmed",
        url="https://example.org/deep",
    )

    assert any(needle in passage.text for passage in passages)
