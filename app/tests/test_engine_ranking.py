from __future__ import annotations

import types
from typing import Any

import pytest
from co_scientist.domains.research_state.claims import (
    ClaimAssessment,
    EntailmentLabel,
    deterministic_assessor,
)
from co_scientist.domains.research_state.claims import grounding as claim_grounding
from co_scientist.domains.research_state.claims.gate import SupportSpan
from co_scientist.domains.research_state.models import Hypothesis
from co_scientist.orchestration.engine_tasks import gate as engine_tasks_gate
from co_scientist.orchestration.engine_tasks import ranking as engine_tasks_ranking
from co_scientist.orchestration.engine_tasks import support as engine_tasks_support
from co_scientist.orchestration.engine_tasks.gate import (
    _apply_gate_verdict,
    _GatePlan,
)
from co_scientist.orchestration.repository import runs, tasks
from co_scientist.platform.db.models import RunStatus
from co_scientist.platform.retrieval.article import Article

from tests._client import create_run as _create_run
from tests._client import make_client
from tests._engine_tasks_helpers import (
    _add_fixture_review,
    _install_plain_fake_judge,
    _RankingSeed,
    _run_ranking_node,
    _seed_ranking_node,
)
from tests._store_helpers import seed_run

from ._llm_fake_backend import install_completion_backend


def _private_corpus_source() -> dict[str, Any]:
    return {
        "display": (
            "Private scientist source 'Lab notes': Astrocyte lactate "
            "accelerates synaptic ATP recovery."
        ),
        "source_type": "private_document",
        "data": {
            "document_id": "doc-1",
            "title": "Lab notes",
            "excerpt": ("Astrocyte lactate accelerates synaptic ATP recovery."),
            "private": True,
        },
    }


def _tasks_gate_install_counting_assessor(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, int]:
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


def _tasks_gate_multi_claim_state() -> dict[str, Any]:
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
async def test_pre_ranking_gate_grounds_claims_in_private_corpus() -> None:
    hypothesis = Hypothesis(
        text="Astrocyte lactate accelerates synaptic ATP recovery.",
        literature_grounding=("Astrocyte lactate accelerates synaptic ATP recovery."),
    )
    hypothesis.review_disposition = "viable"
    state: dict[str, Any] = {"hypotheses": [hypothesis], "articles": []}
    await engine_tasks_gate._apply_pre_ranking_evidence_gate(state)
    assert hypothesis.review_disposition == "viable"

    state["context_enrichment_sources"] = [_private_corpus_source()]
    await engine_tasks_gate._apply_pre_ranking_evidence_gate(state)

    assert hypothesis.review_disposition == "viable"
    assert hypothesis.enrichments["claim_gate"]["decision"] == "allow"


@pytest.mark.asyncio
async def test_pre_ranking_gate_reuses_unchanged_semantic_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _tasks_gate_install_counting_assessor(monkeypatch)
    hypothesis = Hypothesis(
        text="We hypothesize lactate may accelerate ATP recovery.",
        literature_grounding="Astrocyte lactate accelerates ATP recovery.",
    )
    hypothesis.review_disposition = "viable"
    state = {
        "hypotheses": [hypothesis],
        "articles": [
            Article(
                title="Astrocyte energetics",
                abstract="Astrocyte lactate accelerates ATP recovery.",
                source_id="PMID-1",
            )
        ],
    }

    await engine_tasks_gate._apply_pre_ranking_evidence_gate(state)
    first_call_count = calls["n"]
    await engine_tasks_gate._apply_pre_ranking_evidence_gate(state)

    assert first_call_count > 0
    assert calls["n"] == first_call_count
    assert hypothesis.enrichments["claim_gate"]["input_fingerprint"]


@pytest.mark.asyncio
async def test_pre_ranking_gate_ignores_contradicted_go_no_go() -> None:
    # Pilot-plan Go/No-Go thresholds are speculative and cannot gate publication
    # even when contradicted.
    hypothesis = Hypothesis(
        text="Inhibiting the target restores homeostasis in the model.",
        experiment=(
            "1. Run the pilot assay in the xenograft model.\n"
            "**Go:** Tumor regression exceeds fifty percent in the"
            " xenograft model.\n"
            "**No-Go:** Tumor regression remains below ten percent in the"
            " xenograft model."
        ),
    )
    hypothesis.review_disposition = "viable"
    state = {
        "hypotheses": [hypothesis],
        "articles": [
            Article(
                title="Xenograft regression trial",
                abstract=(
                    "Tumor regression did not exceed fifty percent in the"
                    " xenograft model in this trial."
                ),
            )
        ],
    }

    await engine_tasks_gate._apply_pre_ranking_evidence_gate(state)

    assert hypothesis.review_disposition == "viable"
    gate = hypothesis.enrichments["claim_gate"]
    assert gate["decision"] == "allow"
    go_no_go_claims = [claim for claim in gate["claims"] if "**Go:**" in claim["claim"]]
    assert go_no_go_claims, "the Go/No-Go claim was not extracted at all"
    assert all(claim["role"] == "speculative" for claim in go_no_go_claims)
    assert any(claim["label"] == "contradicts" for claim in go_no_go_claims), (
        "test setup did not actually produce a contradiction to be excused"
    )


@pytest.mark.parametrize(
    ("role", "disposition"),
    [("categorical", "evidence_blocked"), ("speculative", "viable")],
)
def test_gate_verdict_blocks_only_a_categorical_contradiction(role: str, disposition: str) -> None:
    claim = "Kinase X inhibition reduces AML relapse rates."
    hypothesis = Hypothesis(text=claim)
    hypothesis.review_disposition = "viable"
    span = SupportSpan(evidence_id="e1", quote="no effect", start=0, end=9)
    assessment = ClaimAssessment(
        claim=claim,
        label=EntailmentLabel.CONTRADICTS,
        supporting_passages=(),
        contradicting_passages=(span,),
        assessor="test",
    )
    plan = _GatePlan(
        hypothesis=hypothesis,
        claims=(claim,),
        roles={claim: role},
        fingerprint="f",
        claim_fingerprints={claim: "f"},
        prior_disposition="viable",
    )

    _apply_gate_verdict(plan, [assessment], "test")

    assert hypothesis.review_disposition == disposition


@pytest.mark.asyncio
async def test_pre_ranking_gate_skips_hypotheses_review_already_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Permanent review rejection needs no further provider calls;
    # evidence_blocked remains reassessable.
    calls = _tasks_gate_install_counting_assessor(monkeypatch)
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
    # Evidence-blocked is reversible after text/evidence changes, unlike
    # permanent review dispositions.
    calls = _tasks_gate_install_counting_assessor(monkeypatch)
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
                abstract=("Astrocyte lactate accelerates synaptic ATP recovery."),
            )
        ],
    }

    await engine_tasks_gate._apply_pre_ranking_evidence_gate(state)

    assert calls["n"] > 0
    assert hypothesis.review_disposition == "viable"


def _install_fake_acompletion(monkeypatch: pytest.MonkeyPatch) -> None:

    async def _fake_acompletion(**_kwargs: Any) -> Any:
        message = types.SimpleNamespace(content='{"verdicts": []}')
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    install_completion_backend(monkeypatch, _fake_acompletion)
    monkeypatch.delenv("COSCIENTIST_FORCE_OFFLINE", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-not-called-by-this-test")


@pytest.mark.asyncio
async def test_pre_ranking_gate_calls_are_visible_to_the_run_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Entailment must use the engine admission seam so its provider calls
    # consume the run ceiling.
    from co_scientist.core.exceptions import LLMCallBudgetExceededError
    from co_scientist.platform.llm import scoped_llm_call_budget

    _install_fake_acompletion(monkeypatch)
    state = _tasks_gate_multi_claim_state()

    with (
        pytest.raises(LLMCallBudgetExceededError),
        scoped_llm_call_budget("gate-budget-test-run", 0),
    ):
        await engine_tasks_gate._apply_pre_ranking_evidence_gate(state)


@pytest.mark.asyncio
async def test_pre_ranking_gate_telemetry_is_attributed_and_not_double_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Engine telemetry is the only call-count source; manual additions
    # double-charge spend.

    _install_fake_acompletion(monkeypatch)
    state = _tasks_gate_multi_claim_state()

    await engine_tasks_gate._apply_pre_ranking_evidence_gate(state)

    metrics = state["metrics"]
    gate_usage = {
        key: entry for key, entry in metrics.model_usage.items() if key.startswith("claim_gate::")
    }
    assert gate_usage, f"no claim_gate telemetry recorded: {metrics.model_usage}"
    total_calls = sum(entry["calls"] for entry in gate_usage.values())
    assert total_calls >= 1
    assert metrics.llm_calls == total_calls


def test_evidence_blocked_idea_is_excluded_from_ranking() -> None:
    # Blocked ideas must leave the tournament before their claims can shift peer
    # Elo.
    supported = _add_fixture_review(Hypothesis(text="Supported idea."))
    supported.review_disposition = "viable"
    blocked = _add_fixture_review(Hypothesis(text="Unsupported idea."))
    blocked.review_disposition = "evidence_blocked"
    # Deep-verification doubt demotes rather than withholds; rankability must
    # follow the engine predicate.
    undermined = _add_fixture_review(Hypothesis(text="Undermined idea."))
    undermined.review_disposition = "viable"
    undermined.deep_verification_verdict = "undermined"

    eligible = engine_tasks_ranking._ranking_eligible(
        {"hypotheses": [supported, blocked, undermined]}
    )

    assert supported in eligible
    assert blocked not in eligible
    assert undermined in eligible


@pytest.mark.asyncio
@pytest.mark.parametrize(("pairs", "consumed", "rounds_left"), [(6, 12, None), (12, 9, 3)])
async def test_budget_left_decides_the_scheduled_tournament(
    isolated_db: str,
    monkeypatch: pytest.MonkeyPatch,
    pairs: int,
    consumed: int,
    rounds_left: int | None,
) -> None:
    # Opening an empty tournament erases prior matches, so a spent budget must
    # preserve judged work and a partial one schedules only what is left.
    run = seed_run("Budget science")
    _seed_ranking_node(
        run.id,
        monkeypatch,
        _RankingSeed(
            hypothesis_count=8,
            tournament_pairs=pairs,
            idempotency_key="budget-ranking-node",
            consumed_rounds=consumed,
            played=True,
        ),
        isolated_db,
    )
    _install_plain_fake_judge(monkeypatch)

    scheduled = await _run_ranking_node(run.id, isolated_db)

    if rounds_left is None:
        assert scheduled.get("tournament_rounds") is None
        successor = tasks.claim_task("w", run_id=run.id, db_path=isolated_db)
        assert successor is not None
        assert successor.task_type != engine_tasks_support.RANKING_MATCH_TASK
    else:
        assert int(scheduled["tournament_rounds"]) == rounds_left


_OWNER = {"X-Client-ID": "ranking-pause-owner"}


def _owned_running_run(db_path: str) -> tuple[Any, str]:
    client = make_client()
    created = _create_run(
        client,
        "Pause during a durable ranking match",
        headers=_OWNER,
        tier="standard",
    )
    assert created.status_code == 200, created.text
    run_id = str(created.json()["id"])
    runs.update_run_status(run_id, RunStatus.RUNNING, db_path=db_path)
    return client, run_id
