"""Tests for the batched LLM entailment assessor (app/claim_verifier_batch.py).

Split out of ``test_claim_verifier.py`` when that file passed the
module-size budget. Covers ``make_llm_batch_assessor``: verdicts mapping
back to claims by index, a missing index falling back to the
deterministic assessor for just that claim, a whole-batch provider
failure, the call counter, the claim-count split, and span location
against chunked evidence.
"""

from __future__ import annotations

import types
from typing import Any

import pytest

from app.claim_verifier import make_llm_assessor
from app.claim_verifier_batch import make_llm_batch_assessor
from app.claims import EntailmentLabel, EvidencePassage, assess_claims_batch


@pytest.fixture(autouse=True)
def _disable_llm_response_cache() -> Any:
    """Force every call in this file to miss the engine's response cache.

    ``claim_verifier_batch`` routes through ``call_llm_json`` with caching
    on, and several tests here reuse the exact same claims/passages with a
    *different* faked reply to prove a different code path. Without this,
    the second such test would silently replay the first test's cached
    response instead of calling the fake at all.
    """
    from co_scientist.cache import scoped_cache_override

    with scoped_cache_override(False):
        yield


def _fake_completion(content: str) -> Any:
    """Return a stand-in for litellm.acompletion yielding ``content``."""

    async def _completion(**_kwargs: Any) -> Any:
        message = types.SimpleNamespace(content=content)
        choice = types.SimpleNamespace(message=message)
        return types.SimpleNamespace(choices=[choice])

    return _completion


def _install(monkeypatch: pytest.MonkeyPatch, completion: Any) -> None:
    """Patch the engine's completion boundary (``litellm.acompletion``)."""
    import litellm

    monkeypatch.setattr(litellm, "acompletion", completion)


_PASSAGE = EvidencePassage(
    evidence_id="ev-1",
    text="Kinase X inhibition reduces tumor growth in AML cell lines.",
    source="pubmed",
    url="https://example.org/1",
)


def test_batch_assessor_id_matches_the_single_claim_assessor() -> None:
    """The batch and per-claim assessors for the same model share an id.

    They are the same underlying judge; only the call shape differs.
    """
    _, single_id = make_llm_assessor("deepseek/deepseek-chat")
    _, batch_id = make_llm_batch_assessor("deepseek/deepseek-chat")
    assert single_id == batch_id == "llm:deepseek/deepseek-chat"


def test_batch_verdicts_map_back_to_claims_by_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A batch reply's verdicts land on the right claim, by 1-based index."""
    _install(
        monkeypatch,
        _fake_completion(
            '{"verdicts": ['
            '{"index": 2, "label": "supports", "supporting": '
            '[{"evidence_id": "ev-1", "quote": "reduces tumor growth"}], '
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
    span = results[1].supporting_passages[0]
    assert span.evidence_id == "ev-1"
    assert span.quote == "reduces tumor growth"


def test_batch_missing_index_falls_back_to_deterministic_for_that_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A verdict missing from the reply falls only that claim back.

    The other claim in the same batch keeps its real LLM verdict -- one bad
    index must not cost the whole group its assessment.
    """
    _install(
        monkeypatch,
        _fake_completion(
            '{"verdicts": ['
            '{"index": 1, "label": "supports", "supporting": '
            '[{"evidence_id": "ev-1", "quote": "reduces tumor growth"}], '
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
    # The deterministic fallback still finds strong topical support here,
    # and the fallback verdict is stamped with the caller's own assessor
    # id -- the fallback is an implementation detail of this assessor's
    # best-effort contract, not a different provenance.
    assert results[1].label is EntailmentLabel.SUPPORTS
    assert results[1].assessor == assessor_id


def test_batch_provider_error_falls_back_every_claim_in_the_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raising provider falls the whole batch back to deterministic."""

    async def _raising(**_kwargs: Any) -> Any:
        raise RuntimeError("provider down")

    _install(monkeypatch, _raising)
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
    """The optional call counter counts real provider calls, not groups.

    A group whose claims retrieve no evidence never reaches the provider,
    so the counter must not tick for it -- this is what lets
    ``engine_tasks_gate``'s ``entailment_calls=`` log line report actual
    spend rather than an upper bound.
    """
    _install(
        monkeypatch,
        _fake_completion('{"verdicts": []}'),
    )
    counter: list[int] = [0]
    batch_assessor, assessor_id = make_llm_batch_assessor(
        "deepseek/deepseek-chat", call_counter=counter
    )
    # No evidence at all: assess_claims_batch must not call the assessor.
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
    """A hypothesis with more than the split threshold costs two calls.

    Keeps a single reply's length from scaling badly with an unusually
    claim-dense hypothesis (see the 46-hypothesis proximity incident this
    guards against in the root AGENTS.md).
    """
    _install(monkeypatch, _fake_completion('{"verdicts": []}'))
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
    """A batched verdict citing a chunk id still locates a real span.

    Chunked passages carry the chunk's own id (``<article>#<index>``, see
    ``app.evidence_chunking``); the batched path must resolve a citation
    against exactly the chunk the union sent, the same as the per-claim
    path does.
    """
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
    _install(
        monkeypatch,
        _fake_completion(
            '{"verdicts": [{"index": 1, "label": "supports", "supporting": '
            f'[{{"evidence_id": "{chunk.evidence_id}", '
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
    assert "#" in span.evidence_id  # a chunk id, not the bare article id
