# Verbatim production examples contain off-target or confirmatory quotes;
# neither can justify contradiction.

from __future__ import annotations

import types
from typing import Any

import pytest

from app.claims import EntailmentLabel, EvidencePassage, assess_claim
from app.claims.verifier import make_llm_assessor

from ._llm_fake_backend import install_completion_backend


@pytest.fixture(autouse=True)
def _disable_llm_response_cache() -> Any:
    # Repeated claims use different fake replies; cache isolation prevents
    # replaying an earlier test verdict.
    from co_scientist.cache import scoped_cache_override

    with scoped_cache_override(False):
        yield


def _fake_completion(content: str) -> Any:

    async def _completion(**_kwargs: Any) -> Any:
        message = types.SimpleNamespace(content=content)
        choice = types.SimpleNamespace(message=message)
        return types.SimpleNamespace(choices=[choice])

    return _completion


def _install(monkeypatch: pytest.MonkeyPatch, completion: Any) -> None:
    install_completion_backend(monkeypatch, completion)


def test_offtarget_quote_does_not_yield_contradiction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # This verbatim production quote concerns a different ligand and target, not
    # the asserted claim.
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
    # This verbatim production quote confirms the mechanism without negating it.
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
    # A genuine on-topic negation must survive the guard; downgrading every
    # contradiction would fail open.
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
