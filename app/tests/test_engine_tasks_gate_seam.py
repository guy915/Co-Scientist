"""Pre-ranking evidence-gate rankability skip and engine-seam integration.

Split out of ``test_engine_tasks_gate.py`` to keep it within the module-
size budget. Covers two things the sibling file does not: which
hypotheses the gate skips assessing before spending a single provider
call (unrankable-forever vs. its own reversible ``evidence_blocked``),
and that its entailment calls -- now routed through the engine's
``call_llm_json`` seam (``app.claims.verifier``) -- are visible to the
run's LLM-call budget and telemetry the way any other engine call is.
"""

from __future__ import annotations

import types
from typing import Any

import pytest
from co_scientist.models import Article, Hypothesis

from app.config import settings
from app.engine_tasks import gate as engine_tasks_gate

from ._llm_fake_backend import install_completion_backend


def _install_counting_assessor(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, int]:
    """Patch build_assessor with a call-counting deterministic assessor."""
    from app.claims import deterministic_assessor
    from app.claims import grounding as claim_grounding

    calls = {"n": 0}

    def counting(claim: str, passages: Any) -> Any:
        calls["n"] += 1
        return deterministic_assessor(claim, passages)

    monkeypatch.setattr(
        claim_grounding,
        "build_assessor",
        lambda *_: (counting, "counting-v1"),
    )
    return calls


def _multi_claim_state() -> dict[str, Any]:
    """A viable two-claim hypothesis grounded by one supporting article."""
    hypothesis = Hypothesis(
        text=(
            "Astrocyte lactate accelerates synaptic ATP recovery. "
            "Neuronal mitochondria buffer the resulting calcium influx."
        ),
        literature_grounding=(
            "Astrocytes participate in neuronal energy support. "
            "Lactate shuttling is documented in cortical slices."
        ),
        explanation="Glycolytic flux rises before the ATP rebound.",
        experiment="Measure ATP recovery under lactate blockade.",
    )
    hypothesis.review_disposition = "viable"
    return {
        "hypotheses": [hypothesis],
        "articles": [
            Article(
                title="Astrocyte energetics",
                abstract="Astrocytes participate in neuronal energy support.",
            )
        ],
    }


@pytest.mark.asyncio
async def test_pre_ranking_gate_skips_hypotheses_review_already_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An idea the initial review gate already barred is never assessed.

    ``inaccurate``/``non_novel``/``unsafe`` can never reach the tournament
    (``Hypothesis.is_rankable``), and the initial review gate never
    reverses those verdicts -- so spending a wave of provider calls on
    their claims buys nothing. Only ``evidence_blocked`` (this gate's own,
    reversible verdict) must still be reassessed; see the sibling test.
    """
    calls = _install_counting_assessor(monkeypatch)
    rejected = Hypothesis(text="A rejected idea about lactate.")
    rejected.review_disposition = "inaccurate"
    state = {"hypotheses": [rejected], "articles": []}

    await engine_tasks_gate._apply_pre_ranking_evidence_gate(state)

    assert calls["n"] == 0
    assert "claim_gate" not in rejected.enrichments
    assert rejected.review_disposition == "inaccurate"


@pytest.mark.asyncio
async def test_pre_ranking_gate_reassesses_changed_evidence_blocked_idea(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A previously blocked idea is reassessed once its text changes.

    ``evidence_blocked`` is this gate's own verdict, not the initial
    review's, so an idea it blocked must stay reassessable -- unlike a
    disposition the initial review gate decided for good (the sibling
    test above). Revising the hypothesis's text changes its input
    fingerprint, so the fingerprint cache cannot be the reason it is
    skipped; only a disposition-based skip could wrongly bar it here.
    """
    calls = _install_counting_assessor(monkeypatch)
    hypothesis = Hypothesis(text="stale, previously-blocked text")
    hypothesis.review_disposition = "evidence_blocked"
    hypothesis.enrichments["claim_gate"] = {
        "decision": "block",
        "reason": "a prior contradicted claim",
        "assessor": "counting-v1",
        "input_fingerprint": "stale-fingerprint",
        "prior_review_disposition": "viable",
        "claims": [],
    }
    hypothesis.text = "Astrocyte lactate accelerates synaptic ATP recovery."
    state: dict[str, Any] = {
        "hypotheses": [hypothesis],
        "articles": [
            Article(
                title="Astrocyte energetics",
                abstract=(
                    "Astrocyte lactate accelerates synaptic ATP recovery."
                ),
            )
        ],
    }

    await engine_tasks_gate._apply_pre_ranking_evidence_gate(state)

    assert calls["n"] > 0
    assert hypothesis.review_disposition == "viable"


def _install_fake_acompletion(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install a fake engine completion backend that replies with a batch.

    An empty ``verdicts`` array is a valid (if uninformative) batch reply --
    every claim falls back to the deterministic assessor for want of a
    verdict at its index, which these two tests do not care about; they
    only need the call to actually reach the boundary.
    """

    async def _fake_acompletion(**_kwargs: Any) -> Any:
        message = types.SimpleNamespace(content='{"verdicts": []}')
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)]
        )

    install_completion_backend(monkeypatch, _fake_acompletion)
    monkeypatch.setattr(settings, "claim_assessor", "llm")
    # build_assessor takes the deterministic assessor whatever the mode
    # says while the process looks offline -- put it in the state where a
    # provider call is permissible, like the LLM-assessor tests above.
    monkeypatch.delenv("COSCIENTIST_FORCE_OFFLINE", raising=False)
    monkeypatch.delenv("COSCIENTIST_FORCE_MOCK", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-not-called-by-this-test")


@pytest.mark.asyncio
async def test_pre_ranking_gate_calls_are_visible_to_the_run_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate's entailment calls now count against a run's LLM-call ceiling.

    Before routing through the engine seam these calls were invisible to
    ``co_scientist.llm.admission.call_budget`` -- a production run spent $4.70
    over ~1,000 provider requests against a 2500-call ceiling that never saw
    them. Batching judges this hypothesis's several claims in a single call (see
    ``app.claims.assess_claims_batch``), so a ceiling of 0 -- not 1 -- is what
    the very first call must already exceed to prove the ceiling sees this
    gate's calls at all.
    """
    from co_scientist.cache import scoped_cache_override
    from co_scientist.exceptions import LLMCallBudgetExceededError
    from co_scientist.llm import scoped_llm_call_budget

    _install_fake_acompletion(monkeypatch)
    state = _multi_claim_state()

    with (
        pytest.raises(LLMCallBudgetExceededError),
        scoped_cache_override(False),
        scoped_llm_call_budget("gate-budget-test-run", 0),
    ):
        await engine_tasks_gate._apply_pre_ranking_evidence_gate(state)


@pytest.mark.asyncio
async def test_pre_ranking_gate_telemetry_is_attributed_and_not_double_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate's calls land in ``claim_gate`` telemetry exactly once.

    Telemetry (``model_usage``) now carries these calls, replacing the old
    manual ``llm_calls`` charge (``_charge_entailment_calls``, removed) --
    ``llm_calls`` equalling the summed ``model_usage`` call count (not
    double that) proves the seam's own count is the only source, with
    nothing added on top of it.
    """
    from co_scientist.cache import scoped_cache_override

    _install_fake_acompletion(monkeypatch)
    state = _multi_claim_state()

    with scoped_cache_override(False):
        await engine_tasks_gate._apply_pre_ranking_evidence_gate(state)

    metrics = state["metrics"]
    gate_usage = {
        key: entry
        for key, entry in metrics.model_usage.items()
        if key.startswith("claim_gate::")
    }
    assert gate_usage, (
        f"no claim_gate telemetry recorded: {metrics.model_usage}"
    )
    total_calls = sum(entry["calls"] for entry in gate_usage.values())
    assert total_calls >= 1
    assert metrics.llm_calls == total_calls
