"""Tests for the LLM (NLI) entailment assessor (app/claim_verifier.py).

The assessor is exercised end-to-end against a real provider by the golden run;
here the litellm boundary is faked so the prompt/parse/guard behavior is proven
offline: a valid verdict with a real quote yields a located support span, a
hallucinated quote is downgraded, and any provider/parse failure falls back to
the deterministic assessor rather than breaking grounding.
"""

from __future__ import annotations

import types
from typing import Any

import pytest

from app.claim_verifier import make_llm_assessor
from app.claims import (
    EntailmentLabel,
    EvidencePassage,
    assess_claim,
)


def _fake_completion(content: str) -> Any:
    """Return a stand-in for litellm.completion yielding ``content``."""

    def _completion(**_kwargs: Any) -> Any:
        message = types.SimpleNamespace(content=content)
        choice = types.SimpleNamespace(message=message)
        return types.SimpleNamespace(choices=[choice])

    return _completion


def _install(monkeypatch: pytest.MonkeyPatch, completion: Any) -> None:
    import litellm

    monkeypatch.setattr(litellm, "completion", completion)


_PASSAGE = EvidencePassage(
    evidence_id="ev-1",
    text="Kinase X inhibition reduces tumor growth in AML cell lines.",
    source="pubmed",
    url="https://example.org/1",
)


def test_assessor_id_names_the_model() -> None:
    _, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    assert assessor_id == "llm:deepseek/deepseek-chat"


def test_valid_supports_verdict_locates_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A supports verdict citing a real quote yields a located support span."""
    _install(
        monkeypatch,
        _fake_completion(
            '{"label": "supports", "supporting": '
            '[{"evidence_id": "ev-1", "quote": "reduces tumor growth"}], '
            '"contradicting": []}'
        ),
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    result = assess_claim(
        "Kinase X inhibition reduces tumor growth.",
        [_PASSAGE],
        assessor=assessor,
        assessor_id=assessor_id,
    )
    assert result.label is EntailmentLabel.SUPPORTS
    span = result.supporting_passages[0]
    assert span.evidence_id == "ev-1"
    assert (
        _PASSAGE.text[span.start : span.end]
        == span.quote
        == "reduces tumor growth"
    )


def test_partial_verdict_locates_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial verdict citing a real quote yields a located support span."""
    _install(
        monkeypatch,
        _fake_completion(
            '{"label": "partial", "supporting": '
            '[{"evidence_id": "ev-1", "quote": "reduces tumor growth"}], '
            '"contradicting": []}'
        ),
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    result = assess_claim(
        "Kinase X inhibition halts tumor growth entirely.",
        [_PASSAGE],
        assessor=assessor,
        assessor_id=assessor_id,
    )
    assert result.label is EntailmentLabel.PARTIAL
    span = result.supporting_passages[0]
    assert _PASSAGE.text[span.start : span.end] == span.quote


def test_hallucinated_quote_downgraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A supports verdict whose quote is absent becomes insufficient."""
    _install(
        monkeypatch,
        _fake_completion(
            '{"label": "supports", "supporting": '
            '[{"evidence_id": "ev-1", "quote": "cures every disease"}], '
            '"contradicting": []}'
        ),
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    result = assess_claim(
        "Kinase X inhibition reduces tumor growth.",
        [_PASSAGE],
        assessor=assessor,
        assessor_id=assessor_id,
    )
    assert result.label is EntailmentLabel.INSUFFICIENT
    assert result.supporting_passages == ()


def test_provider_error_falls_back_to_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raising provider falls back to the deterministic assessor."""

    def _raising(**_kwargs: Any) -> Any:
        raise RuntimeError("provider down")

    _install(monkeypatch, _raising)
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    # The deterministic fallback still finds strong topical support here.
    result = assess_claim(
        "Kinase X inhibition reduces tumor growth in AML.",
        [_PASSAGE],
        assessor=assessor,
        assessor_id=assessor_id,
    )
    assert result.label is EntailmentLabel.SUPPORTS
    assert result.supporting_passages  # deterministic located a span


def test_malformed_json_falls_back_to_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unparseable model output falls back rather than trusting a bad parse."""
    _install(monkeypatch, _fake_completion("not json at all"))
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    result = assess_claim(
        "Kinase X inhibition reduces tumor growth in AML.",
        [_PASSAGE],
        assessor=assessor,
        assessor_id=assessor_id,
    )
    # Falls back; deterministic finds support for this overlapping pair.
    assert result.label is EntailmentLabel.SUPPORTS


def test_no_passages_is_insufficient_without_calling_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no candidate passages the assessor short-circuits."""

    def _should_not_be_called(**_kwargs: Any) -> Any:
        raise AssertionError("litellm.completion must not be called")

    _install(monkeypatch, _should_not_be_called)
    assessor, _ = make_llm_assessor("deepseek/deepseek-chat")
    draft = assessor("some claim", [])
    assert draft.label is EntailmentLabel.INSUFFICIENT


def test_verdict_call_thinks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The entailment judge reasons, like every other app call.

    Thinking is requested explicitly rather than left to the provider's
    default, which is not ours to rely on: an omitted field is how a judge
    ends up reasoning locally and silently not reasoning in production.
    """
    seen: dict[str, Any] = {}

    def _capturing_completion(**kwargs: Any) -> Any:
        seen.update(kwargs)
        message = types.SimpleNamespace(
            content='{"label": "insufficient", "supporting": [], '
            '"contradicting": []}'
        )
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)]
        )

    _install(monkeypatch, _capturing_completion)
    assessor, _ = make_llm_assessor("deepseek/deepseek-v4-flash")
    assessor("some claim", [_PASSAGE])

    assert seen["extra_body"] == {"thinking": {"type": "enabled"}}
    assert seen["reasoning_effort"] == "high"
