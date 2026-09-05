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


@pytest.fixture(autouse=True)
def _disable_llm_response_cache() -> Any:
    """Force every call in this file to miss the engine's response cache.

    ``claim_verifier`` now routes through ``call_llm_json`` with caching
    on (by design -- see its module docstring), and several tests here
    reuse the exact same claim/passage pair with a *different* faked
    reply to prove a different code path. Without this, the second such
    test would silently replay the first test's cached response instead
    of calling the fake at all.
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
    """Patch the engine's completion boundary (``litellm.acompletion``).

    ``app.claim_verifier`` routes through ``co_scientist.llm.call_llm_json``
    now (see the module docstring), so the boundary to fake is the
    engine's own -- exactly what every other engine LLM test patches.
    """
    import litellm

    monkeypatch.setattr(litellm, "acompletion", completion)


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


def test_supporting_as_single_object_not_wrapped_in_list_still_locates_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A "supporting" object, not wrapped in a list, still yields a span.

    ``json_object`` mode (no schema enforcement) lets a model plausibly
    write the single supporting citation directly rather than wrapping it
    in a one-element array; the entailment call must recover it rather
    than silently treating the claim as having no supporting evidence.
    """
    _install(
        monkeypatch,
        _fake_completion(
            '{"label": "supports", "supporting": '
            '{"evidence_id": "ev-1", "quote": "reduces tumor growth"}, '
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
    assert span.quote == "reduces tumor growth"


def test_provider_error_falls_back_to_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raising provider falls back to the deterministic assessor."""

    async def _raising(**_kwargs: Any) -> Any:
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

    async def _should_not_be_called(**_kwargs: Any) -> Any:
        raise AssertionError("litellm.acompletion must not be called")

    _install(monkeypatch, _should_not_be_called)
    assessor, _ = make_llm_assessor("deepseek/deepseek-chat")
    draft = assessor("some claim", [])
    assert draft.label is EntailmentLabel.INSUFFICIENT


def test_call_reaches_the_engine_completion_boundary_with_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The assessor's call is sent to the resolved model via the engine seam.

    Thinking/reasoning-argument shaping is the engine's own responsibility
    now (``co_scientist.llm_thinking``, exercised by the engine's own
    tests) -- this only pins that this module's call reaches that seam at
    all, with the model this assessor was built for.
    """
    seen: dict[str, Any] = {}

    async def _capturing_completion(**kwargs: Any) -> Any:
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

    assert seen["model"] == "deepseek/deepseek-v4-flash"
