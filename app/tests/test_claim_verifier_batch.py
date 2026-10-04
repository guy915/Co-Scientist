from __future__ import annotations

import logging
from typing import Any

import pytest

from app.claims import EntailmentLabel, EvidencePassage, assess_claims_batch
from app.claims.verifier import make_llm_assessor, make_llm_batch_assessor

from ._llm_fake_backend import (
    completion_response,
    fake_completion,
    install_completion_backend,
)

pytestmark = pytest.mark.usefixtures("claim_llm_cache_disabled")


_PASSAGE = EvidencePassage(
    evidence_id="ev-1",
    text="Kinase X inhibition reduces tumor growth in AML cell lines.",
    source="pubmed",
    url="https://example.org/1",
)


def test_batch_assessor_id_matches_the_single_claim_assessor() -> None:
    # Batch and per-claim modes share the underlying judge, so their assessor
    # identity is the same.
    _, single_id = make_llm_assessor("deepseek/deepseek-chat")
    _, batch_id = make_llm_batch_assessor("deepseek/deepseek-chat")
    assert single_id == batch_id == "llm:deepseek/deepseek-chat"


def test_batch_verdicts_map_back_to_claims_by_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_completion_backend(
        monkeypatch,
        fake_completion(
            '{"verdicts": ['
            '{"index": 2, "label": "supports", "supporting": '
            '[{"passage": 1, "quote": "reduces tumor growth"}], '
            '"contradicting": []},'
            '{"index": 1, "label": "insufficient", "supporting": [], '
            '"contradicting": []}'
            "]}"
        ),
    )
    batch_assessor, assessor_id = make_llm_batch_assessor(
        "deepseek/deepseek-chat"
    )
    results = assess_claims_batch(
        ["Some unrelated claim.", "Kinase X inhibition reduces tumor growth."],
        [_PASSAGE],
        batch_assessor=batch_assessor,
        assessor_id=assessor_id,
    )
    assert results[0].label is EntailmentLabel.INSUFFICIENT
    assert results[1].label is EntailmentLabel.SUPPORTS
    assert results[1].verification_method == "model_primary"
    span = results[1].supporting_passages[0]
    assert span.evidence_id == "ev-1"
    assert span.quote == "reduces tumor growth"


def test_batch_missing_index_falls_back_to_deterministic_for_that_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_completion_backend(
        monkeypatch,
        fake_completion(
            '{"verdicts": ['
            '{"index": 1, "label": "supports", "supporting": '
            '[{"passage": 1, "quote": "reduces tumor growth"}], '
            '"contradicting": []}'
            "]}"
        ),
    )
    batch_assessor, assessor_id = make_llm_batch_assessor(
        "deepseek/deepseek-chat"
    )
    results = assess_claims_batch(
        [
            "Kinase X inhibition reduces tumor growth.",
            "Kinase X inhibition reduces tumor growth in AML.",
        ],
        [_PASSAGE],
        batch_assessor=batch_assessor,
        assessor_id=assessor_id,
    )
    assert results[0].label is EntailmentLabel.SUPPORTS
    # Fallback retains the assessor id; its method separately identifies the
    # deterministic fallback.
    assert results[1].label is EntailmentLabel.SUPPORTS
    assert results[1].assessor == assessor_id
    assert results[1].verification_method == "deterministic_lexical"


def test_batch_provider_error_falls_back_every_claim_in_the_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    async def _raising(**_kwargs: Any) -> Any:
        raise RuntimeError("provider down")

    install_completion_backend(monkeypatch, _raising)
    batch_assessor, assessor_id = make_llm_batch_assessor(
        "deepseek/deepseek-chat"
    )
    results = assess_claims_batch(
        ["Kinase X inhibition reduces tumor growth in AML."],
        [_PASSAGE],
        batch_assessor=batch_assessor,
        assessor_id=assessor_id,
    )
    assert results[0].label is EntailmentLabel.SUPPORTS
    assert results[0].supporting_passages


def test_batch_call_counter_increments_once_per_actual_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No-evidence groups make no provider call; telemetry must report actual
    # spend.
    install_completion_backend(
        monkeypatch,
        fake_completion('{"verdicts": []}'),
    )
    counter: list[int] = [0]
    batch_assessor, assessor_id = make_llm_batch_assessor(
        "deepseek/deepseek-chat", call_counter=counter
    )
    assess_claims_batch(
        ["An unrelated claim about nothing in the pool."],
        [],
        batch_assessor=batch_assessor,
        assessor_id=assessor_id,
    )
    assert counter[0] == 0

    assess_claims_batch(
        ["Kinase X inhibition reduces tumor growth."],
        [_PASSAGE],
        batch_assessor=batch_assessor,
        assessor_id=assessor_id,
    )
    assert counter[0] == 1


def test_batch_splits_hypotheses_with_many_claims_into_two_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Split claim-dense hypotheses so one reply cannot grow beyond the provider
    # output budget.
    install_completion_backend(monkeypatch, fake_completion('{"verdicts": []}'))
    counter: list[int] = [0]
    batch_assessor, assessor_id = make_llm_batch_assessor(
        "deepseek/deepseek-chat", call_counter=counter
    )
    claims = [
        f"Kinase X inhibition reduces tumor growth claim number {i}."
        for i in range(25)
    ]
    results = assess_claims_batch(
        claims,
        [_PASSAGE],
        batch_assessor=batch_assessor,
        assessor_id=assessor_id,
    )
    assert len(results) == 25
    assert counter[0] == 2


def test_batch_locates_span_in_the_chunked_parent_article(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Legacy chunk-id citations must resolve only against chunks the batch
    # actually showed.
    from app.evidence_chunking import chunk_evidence_passage

    passages = chunk_evidence_passage(
        "article-1",
        head_text="",
        body_text=(
            "Unrelated filler sentence about something else entirely. "
            "Kinase X inhibition reduces tumor growth in AML cell lines. "
        )
        * 40,
        source="pubmed",
        url="https://example.org/article-1",
    )
    chunk = next(p for p in passages if "reduces tumor growth" in p.text)
    install_completion_backend(
        monkeypatch,
        fake_completion(
            '{"verdicts": [{"index": 1, "label": "supports", "supporting": '
            f'[{{"passage": "{chunk.evidence_id}", '
            '"quote": "reduces tumor growth in AML cell lines"}], '
            '"contradicting": []}]}'
        ),
    )
    batch_assessor, assessor_id = make_llm_batch_assessor(
        "deepseek/deepseek-chat"
    )
    results = assess_claims_batch(
        ["Kinase X inhibition reduces tumor growth in AML cell lines."],
        passages,
        batch_assessor=batch_assessor,
        assessor_id=assessor_id,
    )
    assert results[0].label is EntailmentLabel.SUPPORTS
    span = results[0].supporting_passages[0]
    assert span.evidence_id == chunk.evidence_id
    assert "#" in span.evidence_id


def test_batch_entailment_call_disables_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Classification reasoning can exhaust the answer budget; disable it from
    # the first attempt.
    seen: dict[str, Any] = {}

    async def _capturing_completion(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return completion_response('{"verdicts": []}')

    install_completion_backend(monkeypatch, _capturing_completion)
    batch_assessor, _ = make_llm_batch_assessor("deepseek/deepseek-v4-flash")
    batch_assessor(["some claim"], [_PASSAGE])

    assert seen["extra_body"] == {"thinking": {"type": "disabled"}}


def test_batch_answerless_first_attempt_still_yields_a_real_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    async def _flaky_completion(**_kwargs: Any) -> Any:
        calls["n"] += 1
        content = (
            "not valid json"
            if calls["n"] == 1
            else '{"verdicts": [{"index": 1, "label": "supports", '
            '"supporting": [{"passage": 1, '
            '"quote": "reduces tumor growth"}], "contradicting": []}]}'
        )
        return completion_response(content)

    install_completion_backend(monkeypatch, _flaky_completion)
    batch_assessor, assessor_id = make_llm_batch_assessor(
        "deepseek/deepseek-chat"
    )
    results = assess_claims_batch(
        ["Kinase X inhibition reduces tumor growth."],
        [_PASSAGE],
        batch_assessor=batch_assessor,
        assessor_id=assessor_id,
    )
    assert calls["n"] == 2
    assert results[0].label is EntailmentLabel.SUPPORTS
    assert results[0].assessor == assessor_id


def test_batch_offtarget_contradiction_is_downgraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The verbatim off-target quote must be downgraded through batch and
    # per-claim paths alike.
    passage = EvidencePassage(
        evidence_id="ev-1",
        text=(
            "The same ligand is ineffective at blocking wild-type NaVs and "
            "does not disrupt action potential signals in neuronal cells or "
            "brain tissue at working concentrations."
        ),
    )
    claim = (
        "Donepezil, at clinically achievable human brain free "
        "concentrations of 10-30 nM, occupies sigma-1R (Ki ~14 nM) at the "
        "ER-mitochondria contact site."
    )
    install_completion_backend(
        monkeypatch,
        fake_completion(
            '{"verdicts": [{"index": 1, "label": "contradicts", '
            '"supporting": [], "contradicting": [{"passage": 1, '
            '"quote": "The same ligand is ineffective at blocking '
            "wild-type NaVs and does not disrupt action potential signals "
            'in neuronal cells or brain tissue at working concentrations."'
            "}]}]}"
        ),
    )
    batch_assessor, assessor_id = make_llm_batch_assessor(
        "deepseek/deepseek-chat"
    )
    results = assess_claims_batch(
        [claim],
        [passage],
        batch_assessor=batch_assessor,
        assessor_id=assessor_id,
    )
    assert results[0].label is EntailmentLabel.INSUFFICIENT
    assert results[0].contradicting_passages == ()


def test_batch_citation_by_passage_number_resolves_to_that_passage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Equal lexical scores keep fixture order stable so passage 2 matches the
    # cited number.
    other = EvidencePassage(
        evidence_id="ev-0",
        text="Kinase X inhibition reduces tumor growth in a different model.",
    )
    install_completion_backend(
        monkeypatch,
        fake_completion(
            '{"verdicts": [{"index": 1, "label": "supports", '
            '"supporting": [{"passage": "2", '
            '"quote": "reduces tumor growth"}], "contradicting": []}]}'
        ),
    )
    batch_assessor, assessor_id = make_llm_batch_assessor(
        "deepseek/deepseek-chat"
    )
    results = assess_claims_batch(
        ["Kinase X inhibition reduces tumor growth."],
        [other, _PASSAGE],
        batch_assessor=batch_assessor,
        assessor_id=assessor_id,
    )
    assert results[0].label is EntailmentLabel.SUPPORTS
    assert results[0].supporting_passages[0].evidence_id == _PASSAGE.evidence_id


def test_batch_support_quote_from_a_different_named_passage_is_unproven(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    other = EvidencePassage(
        evidence_id="ev-0",
        text="Kinase X inhibition reduces tumor growth in a different model.",
    )
    install_completion_backend(
        monkeypatch,
        fake_completion(
            '{"verdicts": [{"index": 1, "label": "supports", '
            '"supporting": [{"passage": 1, '
            '"quote": "in AML cell lines"}], "contradicting": []}]}'
        ),
    )
    batch_assessor, assessor_id = make_llm_batch_assessor(
        "deepseek/deepseek-chat"
    )
    results = assess_claims_batch(
        ["Kinase X inhibition reduces tumor growth."],
        [other, _PASSAGE],
        batch_assessor=batch_assessor,
        assessor_id=assessor_id,
    )
    assert results[0].label is EntailmentLabel.INSUFFICIENT
    assert results[0].supporting_passages == ()


def test_batch_out_of_range_passage_number_is_dropped_and_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    install_completion_backend(
        monkeypatch,
        fake_completion(
            '{"verdicts": [{"index": 1, "label": "supports", '
            '"supporting": [{"passage": 9, '
            '"quote": "cures every disease"}], "contradicting": []}]}'
        ),
    )
    batch_assessor, assessor_id = make_llm_batch_assessor(
        "deepseek/deepseek-chat"
    )
    with caplog.at_level(logging.WARNING, logger="app.claims"):
        results = assess_claims_batch(
            ["Kinase X inhibition reduces tumor growth."],
            [_PASSAGE],
            batch_assessor=batch_assessor,
            assessor_id=assessor_id,
        )
    assert results[0].label is EntailmentLabel.INSUFFICIENT
    assert results[0].supporting_passages == ()
    assert "could not be located" in caplog.text
