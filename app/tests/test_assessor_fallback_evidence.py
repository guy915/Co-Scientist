"""Claim fallback decisions remain visible in evaluation telemetry."""

from typing import Any

import litellm
import pytest
from co_scientist.cache import scoped_cache_override
from co_scientist.llm import scoped_telemetry

from app.claims import EvidencePassage, assess_claim
from app.claims.verifier import make_llm_assessor

from ._llm_fake_backend import install_completion_backend


@pytest.mark.parametrize("failure", [True, False])
def test_claim_provider_records_only_deterministic_substitution(
    monkeypatch: pytest.MonkeyPatch,
    failure: bool,
) -> None:
    async def unavailable(**kwargs: Any) -> Any:
        if failure:
            raise RuntimeError("offline test provider failure")
        return litellm.ModelResponse(
            model="deepseek/deepseek-chat",
            choices=[
                {
                    "message": {
                        "role": "assistant",
                        "content": (
                            '{"label":"supports","supporting":[{"passage":1,'
                            '"quote":"reduces tumor growth"}],'
                            '"contradicting":[]}'
                        ),
                    },
                    "finish_reason": "stop",
                }
            ],
        )

    install_completion_backend(monkeypatch, unavailable)
    assessor, identity = make_llm_assessor("deepseek/deepseek-chat")
    with scoped_cache_override(False), scoped_telemetry("claims") as usage:
        result = assess_claim(
            "Kinase X inhibition reduces tumor growth.",
            [
                EvidencePassage(
                    evidence_id="one",
                    text=(
                        "Kinase X inhibition reduces tumor growth "
                        "in AML cell lines."
                    ),
                )
            ],
            assessor=assessor,
            assessor_id=identity,
        )
    assert result.label.value == "supports"
    row = usage.snapshot()["claims::deepseek/deepseek-chat"]
    assert row["deterministic_fallbacks"] == (
        {"claim_single": 1} if failure else {}
    )


@pytest.mark.parametrize("has_evidence", [True, False])
def test_batch_fallback_counts_claims_only_after_judging(
    monkeypatch: pytest.MonkeyPatch,
    has_evidence: bool,
) -> None:
    from app.claims import assess_claims_batch
    from app.claims.verifier_batch import make_llm_batch_assessor

    async def unavailable(**kwargs: Any) -> Any:
        raise RuntimeError("offline test provider failure")

    install_completion_backend(monkeypatch, unavailable)
    assessor, identity = make_llm_batch_assessor("deepseek/deepseek-chat")
    passages = (
        [
            EvidencePassage(
                evidence_id="one",
                text=(
                    "Kinase X inhibition reduces tumor growth "
                    "in AML cell lines."
                ),
            )
        ]
        if has_evidence
        else []
    )
    with scoped_cache_override(False), scoped_telemetry("claims") as usage:
        assess_claims_batch(
            ["Kinase X inhibition reduces tumor growth."],
            passages,
            batch_assessor=assessor,
            assessor_id=identity,
        )
    if has_evidence:
        row = usage.snapshot()["claims::deepseek/deepseek-chat"]
        assert row["deterministic_fallbacks"] == {"claim_batch": 1}
    else:
        assert usage.snapshot() == {}
