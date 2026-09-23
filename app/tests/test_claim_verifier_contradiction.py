"""Regression tests for unfounded CONTRADICTS verdicts (b82f9162).

Split out of ``test_claim_verifier.py`` when this file passed the module-size
budget. Measured on production ultra run b82f9162 (2026-09-06): 105 of 183
claim-evidence edges came back CONTRADICTS from the free-model LLM assessor,
including a quote about a different molecule/target and a quote that merely
confirmed the claim's own mechanism. Both real shapes are reproduced verbatim
in miniature below, proving ``claim_verifier_opposition.guard_contradictions``
downgrades them to INSUFFICIENT while a genuine, on-topic negation still
blocks.
"""

from __future__ import annotations

import types
from typing import Any

import pytest

from app.claim_verifier import make_llm_assessor
from app.claims import EntailmentLabel, EvidencePassage, assess_claim


@pytest.fixture(autouse=True)
def _disable_llm_response_cache() -> Any:
    """Force every call in this file to miss the engine's response cache.

    See ``test_claim_verifier.py``'s identical fixture for why.
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


def test_offtarget_quote_does_not_yield_contradiction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A quote about a different molecule/target cannot contradict a claim.

    Real example from run b82f9162: a claim about donepezil occupying
    sigma-1R was marked CONTRADICTS on a quote about a *different* ligand
    failing to block wild-type NaVs -- a different molecule, a different
    target, no negation of anything the claim actually asserts.
    """
    claim = (
        "Donepezil, at clinically achievable human brain free "
        "concentrations of 10-30 nM, occupies sigma-1R (Ki ~14 nM) at the "
        "ER-mitochondria contact site."
    )
    passage = EvidencePassage(
        evidence_id="ev-1",
        text=(
            "The same ligand is ineffective at blocking wild-type NaVs and "
            "does not disrupt action potential signals in neuronal cells or "
            "brain tissue at working concentrations."
        ),
    )
    _install(
        monkeypatch,
        _fake_completion(
            '{"label": "contradicts", "supporting": [], "contradicting": '
            '[{"passage": 1, "quote": "The same ligand is '
            "ineffective at blocking wild-type NaVs and does not disrupt "
            "action potential signals in neuronal cells or brain tissue at "
            'working concentrations."}]}'
        ),
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    result = assess_claim(
        claim, [passage], assessor=assessor, assessor_id=assessor_id
    )
    assert result.label is EntailmentLabel.INSUFFICIENT
    assert result.contradicting_passages == ()


def test_confirmatory_quote_does_not_yield_contradiction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A quote that states the claim's own mechanism cannot contradict it.

    Real example from run b82f9162: a claim about GBM cells engaging
    compensatory autophagy/glycolysis programs was marked CONTRADICTS on a
    quote that *describes that same compensatory interplay* -- on-topic,
    but carrying no negation at all.
    """
    claim = (
        "GBM cells engage compensatory stress-response programs "
        "(autophagy-glycolysis crosstalk) to survive metabolic stress."
    )
    passage = EvidencePassage(
        evidence_id="ev-1",
        text=(
            "These findings identify a novel and complex compensatory "
            "interplay between glycolysis, autophagy, and senescence that "
            "helps maintain stemness in heterogeneous GBM tumor "
            "subpopulations."
        ),
    )
    _install(
        monkeypatch,
        _fake_completion(
            '{"label": "contradicts", "supporting": [], "contradicting": '
            '[{"passage": 1, "quote": "These findings identify a '
            "novel and complex compensatory interplay between glycolysis, "
            "autophagy, and senescence that helps maintain stemness in "
            'heterogeneous GBM tumor subpopulations."}]}'
        ),
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    result = assess_claim(
        claim, [passage], assessor=assessor, assessor_id=assessor_id
    )
    assert result.label is EntailmentLabel.INSUFFICIENT
    assert result.contradicting_passages == ()


def test_genuine_negation_still_yields_contradiction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real, on-topic negation must still block -- the guard is not blanket.

    Same subject as the claim, and an explicit negation of it: this must
    keep clearing as CONTRADICTS despite the new subject/negation check.
    """
    claim = "Kinase X inhibition reduces tumor growth in AML cells."
    passage = EvidencePassage(
        evidence_id="ev-1",
        text="Kinase X inhibition did not reduce tumor growth in AML cells.",
    )
    _install(
        monkeypatch,
        _fake_completion(
            '{"label": "contradicts", "supporting": [], "contradicting": '
            '[{"passage": 1, "quote": "Kinase X inhibition did not '
            'reduce tumor growth in AML cells."}]}'
        ),
    )
    assessor, assessor_id = make_llm_assessor("deepseek/deepseek-chat")
    result = assess_claim(
        claim, [passage], assessor=assessor, assessor_id=assessor_id
    )
    assert result.label is EntailmentLabel.CONTRADICTS
    assert result.verification_method == "lexical_founded"
    assert result.contradicting_passages
