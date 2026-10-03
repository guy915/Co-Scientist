from __future__ import annotations

import asyncio
from typing import Any

import pytest
from co_scientist.agents import evolution, ranking, reflection
from co_scientist.models import Hypothesis, HypothesisOrigin, HypothesisReview
from co_scientist.state import WorkflowState

from app import store, task_worker
from app.config import settings
from tests._client import make_client
from tests._outcome_refinement_api_support import (
    MESELSON_STAHL_OUTCOME_FIELDS,
)
from tests.test_outcome_refinement_executor import _setup_action


@pytest.fixture(autouse=True)
def _disable_embedded_provider_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_mode", "compatibility")
    monkeypatch.setattr(settings, "auth_secret", "outcome-executor-test")
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)


class _OfflineGateStubs:
    def __init__(self, parent_id: str, sibling_id: str) -> None:
        self.parent_id = parent_id
        self.sibling_id = sibling_id
        self.matchups: list[tuple[str, str]] = []
        self.mature_review_calls: list[tuple[str, str]] = []
        self.verification_calls: list[str] = []
        self.judging_calls = 0

    async def evolve(
        self,
        parent: Hypothesis,
        _context: Any,
        _outcome_context: str,
        validation_hypotheses: list[Hypothesis],
    ) -> tuple[Hypothesis, dict[str, Any]]:
        assert parent.id == self.parent_id
        assert self.sibling_id in {
            hypothesis.id for hypothesis in validation_hypotheses
        }
        return (
            Hypothesis(
                id="gate-tested-child",
                text="A targeted child hypothesis about pathway A.",
                title="Targeted child",
                parent_id=parent.id,
                parent_ids=[parent.id],
                generation=parent.generation + 1,
                origin=HypothesisOrigin.EVOLUTION,
            ),
            {},
        )

    async def review(self, **_: Any) -> HypothesisReview:
        return HypothesisReview(
            review_summary="Offline review supports further study.",
            scores={
                "scientific_soundness": 8,
                "novelty": 8,
                "relevance": 8,
                "feasibility": 8,
                "testability": 8,
                "safety": 8,
            },
            safety_ethical_concerns="None identified.",
            detailed_feedback={},
            constructive_feedback="Proceed to testing.",
            overall_score=8.0,
        )

    async def mature_review(
        self,
        _state: WorkflowState,
        hypothesis: Hypothesis,
        mode: reflection.ReviewType,
    ) -> reflection.ReviewRun:
        self.mature_review_calls.append((hypothesis.id, mode.value))
        verdict = "sound" if mode is reflection.ReviewType.FULL else "holds"
        return reflection.ReviewRun(mode, {"verdict": verdict}, None)

    async def verify(
        self, _state: WorkflowState, hypothesis: Hypothesis
    ) -> dict[str, Any]:
        self.verification_calls.append(hypothesis.id)
        return {"verdict": "holds", "probes": []}

    async def judge(
        self,
        pair: tuple[Hypothesis, Hypothesis],
        _context: ranking.RankingJudgingContext,
        _matchup_index: int,
    ) -> ranking.RankingJudgement:
        self.judging_calls += 1
        self.matchups.append((pair[0].id, pair[1].id))
        return ranking.RankingJudgement(
            winner="a",
            response={
                "decision_summary": "Deterministic offline judgment.",
                "judgment_explanation": {},
                "confidence_level": "medium",
                "debate_turns": 1,
            },
            budgeted_turns=1,
        )


def _install_deterministic_gate_stubs(
    monkeypatch: pytest.MonkeyPatch, parent_id: str, sibling_id: str
) -> _OfflineGateStubs:
    from co_scientist.agents.reflection import review as review_module

    stubs = _OfflineGateStubs(parent_id, sibling_id)
    monkeypatch.setattr(
        evolution,
        "evolve_single_hypothesis_from_outcome",
        stubs.evolve,
    )
    monkeypatch.setattr(review_module, "review_single_hypothesis", stubs.review)
    monkeypatch.setattr(reflection, "review_hypothesis", stubs.mature_review)
    monkeypatch.setattr(reflection, "verify_hypothesis", stubs.verify)
    monkeypatch.setattr(ranking, "judge_ranking_matchup", stubs.judge)
    return stubs


def _run_until_ranking_finalized(run_id: str, db_path: str) -> list[str]:
    completed_types: list[str] = []
    for _ in range(100):
        task = store.claim_task(
            "offline-gates-worker", run_id=run_id, db_path=db_path
        )
        if task is None:
            break
        result = asyncio.run(
            task_worker._execute_task_payload(task, db_path=db_path)
        )
        task_worker._record_success(
            task, "offline-gates-worker", result, db_path
        )
        completed_types.append(task.task_type)
        if task.task_type == "engine.ranking.finalize":
            break
    else:
        pytest.fail(
            "the deterministic gate workflow did not reach finalization"
        )
    return completed_types


def test_targeted_child_traverses_standard_review_safety_claim_and_elo_gates(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "claim_assessor", "deterministic")
    client = make_client()
    run_id, parent_id, sibling_id, action_id = _setup_action(
        client, isolated_db
    )
    stubs = _install_deterministic_gate_stubs(
        monkeypatch, parent_id, sibling_id
    )
    completed_types = _run_until_ranking_finalized(run_id, isolated_db)

    assert ("gate-tested-child", "full") in stubs.mature_review_calls
    assert ("gate-tested-child", "simulation") in stubs.mature_review_calls
    assert "gate-tested-child" in stubs.verification_calls
    assert stubs.judging_calls > 0
    assert "engine.node.review" in completed_types
    assert "engine.fanout.review.item" in completed_types
    assert "engine.fanout.review.aggregate" in completed_types
    assert "engine.node.comprehensive_reflection" in completed_types
    assert "engine.fanout.reflection.item" in completed_types
    assert "engine.fanout.reflection.aggregate" in completed_types
    assert "engine.node.safety_screen" in completed_types
    assert "engine.node.deep_verification" in completed_types
    assert "engine.fanout.verification.item" in completed_types
    assert "engine.fanout.verification.aggregate" in completed_types
    assert "engine.node.ranking" in completed_types
    assert "engine.ranking.match" in completed_types
    assert "engine.ranking.finalize" in completed_types

    checkpoint = store.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    state = checkpoint["state"]["state"]
    hypotheses = [
        Hypothesis.from_dict(hypothesis) for hypothesis in state["hypotheses"]
    ]
    child = next(
        hypothesis
        for hypothesis in hypotheses
        if hypothesis.id == "gate-tested-child"
    )
    assert child.parent_id == parent_id
    assert child.review_disposition == "viable"
    assert child.safety_status == "allow"
    assert child.deep_verification_verdict == "holds"
    assert child.enrichments["claim_gate"]["claims"]
    assert child.total_matches > 0
    assert any("gate-tested-child" in matchup for matchup in stubs.matchups)
    assert "outcome_refinement" not in child.enrichments

    action = store.get_outcome_refinement_action(
        run_id, action_id, db_path=isolated_db
    )
    assert action is not None and action["child_hypothesis_id"] == child.id
    assert (
        MESELSON_STAHL_OUTCOME_FIELDS["measured_observation"]
        in action["context_snapshot"]
    )
    assert parent_id in {hypothesis.id for hypothesis in hypotheses}
    assert sibling_id in {hypothesis.id for hypothesis in hypotheses}
    tasks = store.list_tasks(run_id, db_path=isolated_db)
    assert not any(
        task.task_type in {"engine.node.orchestrator", "engine.node.evolve"}
        and task.status in {"queued", "leased", "completed"}
        for task in tasks
    )
    events = store.list_events(run_id, db_path=isolated_db)
    assert MESELSON_STAHL_OUTCOME_FIELDS["measured_observation"] not in str(
        events
    )
    client.close()
