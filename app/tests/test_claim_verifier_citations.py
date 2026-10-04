from __future__ import annotations

import logging

import pytest

from app.claims import (
    EntailmentLabel,
    EvidencePassage,
    _locate_all,
    assess_claim,
)
from app.claims.verifier import make_llm_assessor

from ._llm_fake_backend import fake_completion, install_completion_backend

pytestmark = pytest.mark.usefixtures("claim_llm_cache_disabled")


_PASSAGE = EvidencePassage(
    evidence_id="ev-1",
    text="Kinase X inhibition reduces tumor growth in AML cell lines.",
    source="pubmed",
    url="https://example.org/1",
)


def test_citation_by_passage_number_resolves_to_that_passage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_completion_backend(
        monkeypatch,
        fake_completion(
            '{"label": "supports", "supporting": '
            '[{"passage": "3", "quote": "reduces tumor growth"}], '
            '"contradicting": []}'
        ),
    )
    passages = [
        EvidencePassage(evidence_id="ev-a", text="Unrelated filler one."),
        EvidencePassage(evidence_id="ev-b", text="Unrelated filler two."),
        _PASSAGE,
    ]
    assessor, _ = make_llm_assessor("deepseek/deepseek-chat")
    draft = assessor(
        "Kinase X inhibition reduces tumor growth.",
        passages,
    )
    spans = _locate_all(draft.supporting, passages)
    assert [s.evidence_id for s in spans] == [_PASSAGE.evidence_id]


def test_out_of_range_passage_number_is_dropped_and_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    install_completion_backend(
        monkeypatch,
        fake_completion(
            '{"label": "supports", "supporting": '
            '[{"passage": 9, "quote": "cures every disease"}], '
            '"contradicting": []}'
        ),
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    with caplog.at_level(logging.WARNING, logger="app.claims"):
        result = assess_claim(
            "Kinase X inhibition reduces tumor growth.",
            [_PASSAGE],
            assessor=assessor,
            assessor_id=assessor_id,
        )
    assert result.label is EntailmentLabel.INSUFFICIENT
    assert result.supporting_passages == ()
    assert "could not be located" in caplog.text
