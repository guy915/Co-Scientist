from __future__ import annotations

import threading
import time
import types
from typing import Any

import pytest
from co_scientist.models import (
    Article,
    Hypothesis,
)

import app.engine_tasks.ranking as engine_tasks_ranking_wave
from app.claims import (
    AssessorDraft,
    ClaimAssessment,
    EntailmentLabel,
    deterministic_assessor,
)
from app.claims import grounding as claim_grounding
from app.claims.gate import SupportSpan
from app.config import settings
from app.engine_tasks import gate as engine_tasks_gate
from app.engine_tasks import ranking as engine_tasks_ranking
from app.engine_tasks import support as engine_tasks_support
from app.engine_tasks.gate import (
    _apply_gate_verdict,
    _GatePlan,
)
from app.store import checkpoints, runs, tasks
from app.store import tasks_lifecycle as lifecycle
from app.store.models import RunStatus
from tests._client import create_run as _create_run
from tests._client import make_client
from tests._engine_tasks_helpers import (
    _add_fixture_review,
    _drain_ranking_matches,
    _install_concurrency_tracking_judge,
    _install_plain_fake_judge,
    _RankingSeed,
    _run_ranking_node,
    _running_ranking_events,
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


def _install_overlap_assessor(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, bool]:
    in_flight: set[str] = set()
    flags = {"overlapped": False}
    lock = threading.Lock()

    def _slow_assessor(claim: str, passages: Any) -> AssessorDraft:
        owner = "alpha" if "alpha" in claim else "beta"
        with lock:
            in_flight.add(owner)
            if len(in_flight) > 1:
                flags["overlapped"] = True
        time.sleep(0.05)
        with lock:
            in_flight.discard(owner)
        return AssessorDraft(label=EntailmentLabel.INSUFFICIENT)

    monkeypatch.setattr(
        claim_grounding,
        "build_assessor",
        lambda *_: (_slow_assessor, "slow-v1"),
    )
    monkeypatch.setattr(settings, "claim_assessor", "llm")
    return flags


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
        literature_grounding=(
            "Astrocyte lactate accelerates synaptic ATP recovery."
        ),
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
async def test_pre_ranking_gate_assesses_literature_rationale() -> None:
    hypothesis = Hypothesis(
        text="Astrocyte lactate accelerates synaptic ATP recovery.",
        literature_grounding=(
            "A fictional kinase completely reverses neuronal aging."
        ),
    )
    hypothesis.review_disposition = "viable"
    state = {
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

    assert hypothesis.review_disposition == "viable"
    claims = hypothesis.enrichments["claim_gate"]["claims"]
    assert [claim["label"] for claim in claims] == [
        "supports",
        "insufficient",
    ]
    assert [claim["verification_method"] for claim in claims] == [
        "deterministic_lexical",
        "no_evidence",
    ]


@pytest.mark.asyncio
async def test_pre_ranking_gate_overlaps_claims_across_hypotheses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Bound one wave across hypotheses; serializing by idea leaves most
    # assessment capacity idle.
    flags = _install_overlap_assessor(monkeypatch)
    first = Hypothesis(
        text=(
            "Alpha lactate accelerates alpha ATP recovery. "
            "Alpha mitochondria buffer the alpha calcium influx."
        ),
        literature_grounding="Alpha astrocytes support alpha metabolism.",
    )
    second = Hypothesis(
        text=(
            "Beta lactate accelerates beta ATP recovery. "
            "Beta mitochondria buffer the beta calcium influx."
        ),
        literature_grounding="Beta astrocytes support beta metabolism.",
    )
    for hypothesis in (first, second):
        hypothesis.review_disposition = "viable"
    state = {"hypotheses": [first, second], "articles": []}

    await engine_tasks_gate._apply_pre_ranking_evidence_gate(state)

    assert first.enrichments["claim_gate"]["claims"]
    assert second.enrichments["claim_gate"]["claims"]
    assert flags["overlapped"], "hypotheses were assessed one after another"


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
    go_no_go_claims = [
        claim for claim in gate["claims"] if "**Go:**" in claim["claim"]
    ]
    assert go_no_go_claims, "the Go/No-Go claim was not extracted at all"
    assert all(claim["role"] == "speculative" for claim in go_no_go_claims)
    assert any(claim["label"] == "contradicts" for claim in go_no_go_claims), (
        "test setup did not actually produce a contradiction to be excused"
    )


@pytest.mark.parametrize(
    ("role", "disposition"),
    [("categorical", "evidence_blocked"), ("speculative", "viable")],
)
def test_gate_verdict_blocks_only_a_categorical_contradiction(
    role: str, disposition: str
) -> None:
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

    async def _fake_acompletion(**_kwargs: Any) -> Any:
        message = types.SimpleNamespace(content='{"verdicts": []}')
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)]
        )

    install_completion_backend(monkeypatch, _fake_acompletion)
    monkeypatch.setattr(settings, "claim_assessor", "llm")
    monkeypatch.delenv("COSCIENTIST_FORCE_OFFLINE", raising=False)
    monkeypatch.delenv("COSCIENTIST_FORCE_MOCK", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-not-called-by-this-test")


@pytest.mark.asyncio
async def test_pre_ranking_gate_calls_are_visible_to_the_run_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Entailment must use the engine admission seam so its provider calls
    # consume the run ceiling.
    from co_scientist.cache import scoped_cache_override
    from co_scientist.exceptions import LLMCallBudgetExceededError
    from co_scientist.llm import scoped_llm_call_budget

    _install_fake_acompletion(monkeypatch)
    state = _tasks_gate_multi_claim_state()

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
    # Engine telemetry is the only call-count source; manual additions
    # double-charge spend.
    from co_scientist.cache import scoped_cache_override

    _install_fake_acompletion(monkeypatch)
    state = _tasks_gate_multi_claim_state()

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
async def test_long_tournament_reports_progress_between_its_matches(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Periodic progress prevents long healthy tournaments looking frozen without
    # flooding the activity feed.
    run = seed_run("Task-level science")
    runs.update_run_status(run.id, RunStatus.RUNNING, db_path=isolated_db)
    _seed_ranking_node(
        run.id,
        monkeypatch,
        _RankingSeed(
            hypothesis_count=4,
            tournament_pairs=12,
            idempotency_key="ranking-node",
        ),
        isolated_db,
    )
    _install_plain_fake_judge(monkeypatch)

    scheduled = await _run_ranking_node(run.id, isolated_db)
    rounds = int(scheduled["tournament_rounds"])
    assert rounds > engine_tasks_support.RANKING_PROGRESS_EVERY

    matches = await _drain_ranking_matches(run.id, isolated_db)

    progress = _running_ranking_events(run.id, isolated_db)
    assert progress, "a long tournament emitted no progress at all"
    assert len(progress) < matches
    every = engine_tasks_support.RANKING_PROGRESS_EVERY
    assert progress[0]["payload"]["message"] == (
        f"Tournament match {every} of {rounds}"
    )


@pytest.mark.asyncio
async def test_tournament_judges_a_full_wave_of_matchups_concurrently(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Parallel judging must use the engine semaphore, and candidate supply must
    # reach wave size, or tournaments silently serialize.
    run = seed_run("Wave science")
    _seed_ranking_node(
        run.id,
        monkeypatch,
        _RankingSeed(
            hypothesis_count=8,
            tournament_pairs=20,
            idempotency_key="wave-ranking-node",
        ),
        isolated_db,
    )
    tracker = _install_concurrency_tracking_judge(monkeypatch)

    scheduled = await _run_ranking_node(run.id, isolated_db)
    assert (
        int(scheduled["tournament_rounds"])
        >= engine_tasks_ranking_wave.RANKING_WAVE_SIZE
    )

    match = tasks.claim_task("w", run_id=run.id, db_path=isolated_db)
    assert match is not None
    assert match.task_type == engine_tasks_support.RANKING_MATCH_TASK
    result = await engine_tasks_ranking.execute_ranking_match(
        match, db_path=isolated_db
    )

    assert tracker["peak"] > 1, "matchups in a wave must be judged concurrently"
    assert (
        result["matches_committed"]
        == engine_tasks_ranking_wave.RANKING_WAVE_SIZE
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pairs", "consumed", "rounds_left"), [(6, 12, None), (12, 9, 3)]
)
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


def test_wave_elo_is_applied_sequentially_within_the_round() -> None:
    # Judging overlaps, but Elo applies in wave order so each match sees earlier
    # committed ratings.
    from co_scientist.agents.ranking import RankingJudgement
    from co_scientist.models import Hypothesis

    from app.engine_tasks.ranking import _apply_wave_elo

    hyp_a = Hypothesis(text="shared A")
    hyp_b = Hypothesis(text="opponent B")
    hyp_c = Hypothesis(text="opponent C")
    wave = [(hyp_a, hyp_b), (hyp_a, hyp_c)]
    verdict = {"decision_summary": "A wins.", "confidence_level": "High"}
    judged = [
        RankingJudgement("a", dict(verdict, debate_turns=1), 1),
        RankingJudgement("a", dict(verdict, debate_turns=1), 1),
    ]

    details, _, _ = _apply_wave_elo(wave, judged, {"current_iteration": 2})

    first, second = details
    assert [d["iteration"] for d in details] == [2, 2]
    assert first["winner_elo_before"] == 1200
    assert first["winner_elo_after"] == 1212
    assert second["winner_elo_before"] == first["winner_elo_after"]
    assert second["winner_elo_after"] == 1223
    assert hyp_a.total_matches == 2


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


@pytest.mark.asyncio
async def test_paused_ranking_match_resumes_its_exact_successor(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "coscientist_embedded_worker", False)
    client, run_id = _owned_running_run(isolated_db)
    monkeypatch.setattr(engine_tasks_ranking_wave, "_wave_size", lambda: 3)
    _seed_ranking_node(
        run_id,
        monkeypatch,
        _RankingSeed(
            hypothesis_count=4,
            tournament_pairs=12,
            idempotency_key="pause-ranking-node",
            criteria=["retained scientist criterion"],
            preferences="durable preference stays omitted",
        ),
        isolated_db,
    )
    scheduled = await _run_ranking_node(run_id, isolated_db)

    import co_scientist.agents.ranking.operations as ranking_module

    paused = False
    judge_inputs: list[Any] = []

    async def pause_during_judging(
        ctx: Any, **kwargs: Any
    ) -> tuple[str, dict[str, Any]]:
        nonlocal paused
        judge_inputs.append(ctx)
        if not paused:
            unauthorized = client.post(
                f"/api/runs/{run_id}/pause",
                headers={"X-Client-ID": "ranking-pause-other-owner"},
            )
            assert unauthorized.status_code == 404
            still_running = runs.get_run(run_id, db_path=isolated_db)
            assert still_running is not None
            assert still_running.status == RunStatus.RUNNING.value
            response = client.post(f"/api/runs/{run_id}/pause", headers=_OWNER)
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "paused"
            paused = True
        return "a", {
            "decision_summary": "A is stronger",
            "confidence_level": "high",
            "debate_turns": int(kwargs["debate_turns"]),
            "debate_transcript": [],
            "judge_model": "fixture",
        }

    monkeypatch.setattr(ranking_module, "judge_matchup", pause_during_judging)
    match = tasks.claim_task(
        "ranking-match", run_id=run_id, db_path=isolated_db
    )
    assert match is not None
    assert match.task_type == engine_tasks_support.RANKING_MATCH_TASK
    result = await engine_tasks_ranking.execute_ranking_match(
        match, db_path=isolated_db
    )
    assert paused
    assert lifecycle.complete_task(
        match.id, "ranking-match", result, db_path=isolated_db
    )

    checkpoint = checkpoints.get_latest_checkpoint(run_id, db_path=isolated_db)
    assert checkpoint is not None
    assert checkpoint["seq"] == int(scheduled["checkpoint_seq"]) + 1
    assert checkpoint["stage"] == f"engine_task:{match.id}"
    from co_scientist.checkpoint import restore_workflow_state

    state = restore_workflow_state(checkpoint["state"])
    details = state["pending_ranking_matchups"]
    assert len(details) == result["matches_committed"] == 3
    assert (
        sum(hypothesis.total_matches for hypothesis in state["hypotheses"]) == 6
    )
    assert any(
        hypothesis.elo_rating != 1200 for hypothesis in state["hypotheses"]
    )

    successor = tasks.get_task(result["successor_task_id"], db_path=isolated_db)
    assert successor is not None
    assert successor.task_type == engine_tasks_support.RANKING_MATCH_TASK
    assert successor.status == "queued"
    assert successor.inputs["checkpoint_seq"] == checkpoint["seq"]
    assert successor.dependencies == (match.id,)
    assert (
        successor.provenance["scheduled_by"]
        == engine_tasks_support.RANKING_MATCH_TASK
    )
    paused_run = runs.get_run(run_id, db_path=isolated_db)
    assert paused_run is not None
    assert paused_run.status == RunStatus.PAUSED.value
    assert (
        tasks.claim_task("before-resume", run_id=run_id, db_path=isolated_db)
        is None
    )

    resumed = client.post(f"/api/runs/{run_id}/resume", headers=_OWNER)
    assert resumed.status_code == 200, resumed.text
    resumed_task = tasks.get_task(successor.id, db_path=isolated_db)
    assert resumed_task is not None and resumed_task.status == "queued"
    claim = tasks.claim_task("after-resume", run_id=run_id, db_path=isolated_db)
    assert claim is not None
    assert claim.id == successor.id
    assert claim.task_type == engine_tasks_support.RANKING_MATCH_TASK
    resumed_result = await engine_tasks_ranking.execute_ranking_match(
        claim, db_path=isolated_db
    )
    assert resumed_result["matches_committed"] == 6
    assert [ctx.matchup_index for ctx in judge_inputs] == list(range(6))
    assert all(
        ctx.criteria == ["retained scientist criterion"]
        and ctx.preferences is None
        for ctx in judge_inputs
    )
