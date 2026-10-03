"""Retry behavior for schema-invalid batched entailment responses."""

from __future__ import annotations

import types
from typing import Any

import pytest

from app.claims import EntailmentLabel, EvidencePassage, assess_claims_batch
from app.claims.verifier import make_llm_batch_assessor

from ._llm_fake_backend import install_completion_backend


@pytest.fixture(autouse=True)
def _disable_llm_response_cache() -> Any:
    from co_scientist.cache import scoped_cache_override

    with scoped_cache_override(False):
        yield


def _install_replies(
    monkeypatch: pytest.MonkeyPatch, contents: list[str]
) -> list[dict[str, Any]]:
    """Mock physical completions and retain their request arguments."""
    requests: list[dict[str, Any]] = []

    async def _completion(**kwargs: Any) -> Any:
        requests.append(kwargs)
        message = types.SimpleNamespace(content=contents[len(requests) - 1])
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)]
        )

    install_completion_backend(monkeypatch, _completion)
    return requests


def _mock_zero_price_promotion(monkeypatch: pytest.MonkeyPatch) -> None:
    from co_scientist.llm.admission import free_policy as free_catalog

    free_catalog.install_catalog_reader(
        free_catalog.CatalogReader(
            lambda: {
                "stealth/space-bunny-alpha": {
                    "pricing": {"prompt": "0", "completion": "0"},
                    "architecture": {
                        "input_modalities": ["text"],
                        "output_modalities": ["text"],
                    },
                }
            }
        )
    )


def _assert_zero_price_stealth_route(request: dict[str, Any]) -> None:
    provider = request["extra_body"]["provider"]
    assert request["model"] == "openrouter/stealth/space-bunny-alpha"
    assert request["api_base"] == "https://openrouter.ai/api/v1"
    assert provider["max_price"] == {
        "prompt": 0,
        "completion": 0,
        "request": 0,
    }
    assert provider["only"] == ["Stealth"]
    assert provider["allow_fallbacks"] is False
    assert provider["require_parameters"] is True


_PASSAGE = EvidencePassage(
    evidence_id="ev-1",
    text="Kinase X inhibition reduces tumor growth in AML cell lines.",
    source="pubmed",
    url="https://example.org/1",
)


def test_pruned_typo_retries_and_uses_valid_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_zero_price_promotion(monkeypatch)
    requests = _install_replies(
        monkeypatch,
        [
            '{"verdests": []}',
            '{"verdicts": [{"index": 1, "label": "supports", '
            '"supporting": [{"passage": 1, '
            '"quote": "reduces tumor growth"}], "contradicting": []}]}',
        ],
    )
    batch_assessor, assessor_id = make_llm_batch_assessor(
        "openrouter/stealth/space-bunny-alpha"
    )

    results = assess_claims_batch(
        ["Kinase X inhibition reduces tumor growth."],
        [_PASSAGE],
        batch_assessor=batch_assessor,
        assessor_id=assessor_id,
    )

    assert len(requests) == 2
    assert results[0].label is EntailmentLabel.SUPPORTS
    assert results[0].verification_method == "model_primary"
    for request in requests:
        _assert_zero_price_stealth_route(request)


@pytest.mark.parametrize("reply", ['{"verdests": []}', '{"verdicts": []}'])
def test_empty_batch_retries_three_times_then_falls_back(
    monkeypatch: pytest.MonkeyPatch, reply: str
) -> None:
    _mock_zero_price_promotion(monkeypatch)
    requests = _install_replies(monkeypatch, [reply] * 3)
    batch_assessor, assessor_id = make_llm_batch_assessor(
        "openrouter/stealth/space-bunny-alpha"
    )

    results = assess_claims_batch(
        ["Kinase X inhibition reduces tumor growth."],
        [_PASSAGE],
        batch_assessor=batch_assessor,
        assessor_id=assessor_id,
    )

    assert len(requests) == 3
    assert results[0].label is EntailmentLabel.SUPPORTS
    assert results[0].verification_method == "deterministic_lexical"
    for request in requests:
        _assert_zero_price_stealth_route(request)


def test_valid_sparse_batch_stays_single_call_with_per_index_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _install_replies(
        monkeypatch,
        [
            '{"verdicts": [{"index": 1, "label": "supports", '
            '"supporting": [{"passage": 1, '
            '"quote": "reduces tumor growth"}], "contradicting": []}]}',
        ],
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

    assert len(requests) == 1
    assert results[0].verification_method == "model_primary"
    assert results[1].verification_method == "deterministic_lexical"
