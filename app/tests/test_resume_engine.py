"""App-level REAL-engine checkpoint + resume (P0.7).

Unlike ``test_resume.py`` (mock provider, deterministic re-derive), these drive
the *real* ``HypothesisGenerator`` through the app engine adapter with only the
LLM boundary faked. They prove the engine provider truly resumes from a
persisted ``WorkflowState`` — completed nodes are not re-run — rather than the
old behavior of clearing derived data and re-running from the goal (a retry
from zero that discarded all completed LLM/tool work).

Acceptance (P0.7): kill the run after a node, resume, and (a) do not repeat
completed LLM/tool calls, (b) preserve the checkpointed hypotheses, (c) produce
exactly one report with unique, monotonic event seqs.
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest

from app import engine_adapter, store
from app.run_modes import resolved_run_config

# Load the engine's LLM fake by file path: it lives under engine/tests, which
# is not importable as a package from the app's own ``tests`` namespace.
_ENGINE_FAKE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "engine"
    / "tests"
    / "_llm_fake.py"
)


def _load_engine_fake() -> Any:
    spec = importlib.util.spec_from_file_location(
        "engine_llm_fake", _ENGINE_FAKE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _install_fake_engine_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake the engine's LLM boundary and force literature review off."""
    _load_engine_fake().install_fake_llm(monkeypatch)
    # Hard kill switch: never probe the (possibly live) local MCP server.
    monkeypatch.setenv("FORCE_LITERATURE_REVIEW", "0")
    # These tests exercise engine resume, not the safety gate; keep the
    # app-level semantic screen offline (it makes a real provider call) so a
    # rate-limited or degraded assessment cannot spuriously hold the run.
    from app.config import settings

    monkeypatch.setattr(settings, "semantic_safety_enabled", False)


@pytest.fixture(autouse=True)
def _fresh_ranking_semaphore(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rebind the engine's module-global ranking semaphore per test.

    The semaphore is created once at import and binds to the first event loop
    that acquires it. These tests each run on their own loop (and drive both an
    interrupted run and its resume on that one loop), so a fresh, still-unbound
    semaphore per test avoids a cross-test 'bound to a different event loop'
    error. Production runs every phase on the app's single persistent loop, so
    this is purely a test-isolation concern.
    """
    import asyncio as _asyncio

    from co_scientist.constants import MAX_CONCURRENT_LLM_CALLS
    from co_scientist.nodes import ranking

    monkeypatch.setattr(
        ranking,
        "_ranking_semaphore",
        _asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS),
    )


def _engine_cfg() -> dict[str, Any]:
    return resolved_run_config(
        {
            "max_iterations": 1,
            "initial_hypotheses_count": 2,
            "evolution_max_count": 2,
            "tournament_pairs": 2,
        }
    )


async def _drain_all(
    gen: AsyncIterator[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [e async for e in gen]


async def _drain_until(
    gen: AsyncIterator[dict[str, Any]],
    predicate: Callable[[list[dict[str, Any]]], bool],
) -> list[dict[str, Any]]:
    """Consume events until ``predicate`` holds, then abandon the stream.

    Abandoning the async generator suspends it permanently (a simulated
    process kill) — no terminal event is emitted, mirroring a crash.
    """
    seen: list[dict[str, Any]] = []
    async for event in gen:
        seen.append(event)
        if predicate(seen):
            break
    return seen


def _engine_stream(
    run_id: str, goal: str, cfg: dict[str, Any], *, resume: bool = False
) -> AsyncIterator[dict[str, Any]]:
    return engine_adapter.run_workflow(
        run_id,
        goal,
        cfg,
        force_provider="engine",
        sleep_seconds=0,
        resume=resume,
    )


async def test_engine_run_persists_real_state_checkpoints(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real engine run checkpoints its full WorkflowState, not an envelope."""
    _install_fake_engine_llm(monkeypatch)
    cfg = _engine_cfg()
    run = store.create_run("Engine checkpoint", "standard", "engine", {})

    await _drain_all(_engine_stream(run.id, run.research_goal, cfg))

    checkpoint = store.get_latest_checkpoint(run.id)
    assert checkpoint is not None
    envelope = checkpoint["state"]
    # An engine checkpoint carries a serialized WorkflowState, not the mock's
    # {provider, run_mode, iteration, config} envelope.
    assert envelope.get("provider") == "engine"
    assert "state" in envelope and "hypotheses" in envelope["state"]
    assert envelope["state"]["hypotheses"], "checkpoint has no hypotheses"
    # last_event_seq is a real high-water mark within the run's event log.
    assert 0 < checkpoint["last_event_seq"] <= store.latest_event_seq(run.id)


async def test_engine_resume_preserves_work_and_reports_once(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Interrupt a real engine run, resume, and finish without redoing work."""
    _install_fake_engine_llm(monkeypatch)
    cfg = _engine_cfg()
    run = store.create_run("Engine resume", "standard", "engine", {})

    # Interrupt once a safe checkpoint exists with reviewed hypotheses (the
    # engine's pre-orchestrator resume boundary).
    def _safe_boundary(_seen: list[dict[str, Any]]) -> bool:
        cp = store.get_latest_checkpoint(run.id)
        if cp is None:
            return False
        hyps = cp["state"].get("state", {}).get("hypotheses", [])
        return bool(hyps) and all(h.get("reviews") for h in hyps)

    await _drain_until(
        _engine_stream(run.id, run.research_goal, cfg), _safe_boundary
    )

    checkpoint = store.get_latest_checkpoint(run.id)
    assert checkpoint is not None
    checkpointed_ids = {
        h["id"] for h in checkpoint["state"]["state"]["hypotheses"]
    }
    assert checkpointed_ids
    assert store.get_latest_report(run.id) is None  # not finished yet
    high_water = checkpoint["last_event_seq"]

    # Resume: the engine restores the checkpoint and re-enters at the
    # orchestrator, streaming only remaining nodes.
    resume_events = await _drain_all(
        _engine_stream(run.id, run.research_goal, cfg, resume=True)
    )

    # This fixture intentionally disables literature retrieval, so the resumed
    # run finalizes with latent-only (unverified) hypotheses. Under the
    # rank-and-publish policy that is a completion: the ungrounded ideas are
    # ranked and published (badged "Unverified"), not withheld.
    report = store.get_latest_report(run.id)
    assert report is not None
    assert report["payload"]["leaderboard"]  # ranked ideas were published
    assert resume_events[-1]["payload"].get("status") == "completed"

    # Completed work preserved: every checkpointed hypothesis survives into
    # the final pool (resume did not discard it via a from-zero re-run).
    final_hyps = store.list_hypotheses(run.id)
    final_ids = {h["id"] for h in final_hyps}
    assert checkpointed_ids <= final_ids

    # Artifacts persisted exactly once (no duplication across the resume): the
    # engine persists only at the final drain, so ids must be unique.
    hyp_ids = [h["id"] for h in final_hyps]
    assert len(hyp_ids) == len(set(hyp_ids))
    match_ids = [m["id"] for m in store.list_matches(run.id)]
    assert len(match_ids) == len(set(match_ids))

    # No replay of the completed first pass: the resumed stream re-enters at
    # the orchestrator, so the supervisor never runs again. (The adaptive
    # orchestrator may schedule a *new* generate cycle as fresh work — that is
    # not a replay; the first pass's hypotheses are preserved, asserted above.)
    resumed_types = [e["type"] for e in resume_events]
    assert "supervisor.plan" not in resumed_types

    # Event seqs are globally unique and monotonic across the resume boundary.
    seqs = [e["seq"] for e in store.list_events(run.id)]
    assert len(seqs) == len(set(seqs))
    assert seqs == sorted(seqs)
    # Resumed events continue strictly above the checkpoint high-water mark.
    after_hw = store.list_events(run.id, after_seq=high_water)
    assert after_hw and min(e["seq"] for e in after_hw) > high_water


async def test_engine_resume_from_unreviewed_pool_self_heals(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resuming from a post-generate checkpoint schedules the missing review.

    Interrupting after ``generate`` (hypotheses present, none reviewed) is a
    different end-to-end composition than the post-review boundary: on resume
    the orchestrator must schedule REFLECT -> review -> safety_screen ->
    ranking to catch up, exercising the adaptive self-heal path from a restored
    checkpoint (not just the scheduler rules in isolation). It also proves the
    P0.4 pre-ranking safety screen still runs when resume drives the first
    review/rank.
    """
    _install_fake_engine_llm(monkeypatch)
    cfg = _engine_cfg()
    run = store.create_run("Engine resume unreviewed", "standard", "engine", {})

    # Interrupt at the post-generate checkpoint: hypotheses exist but none are
    # reviewed yet (the next node, review, has not run).
    def _post_generate(_seen: list[dict[str, Any]]) -> bool:
        cp = store.get_latest_checkpoint(run.id)
        if cp is None:
            return False
        hyps = cp["state"].get("state", {}).get("hypotheses", [])
        return bool(hyps) and all(not h.get("reviews") for h in hyps)

    await _drain_until(
        _engine_stream(run.id, run.research_goal, cfg), _post_generate
    )

    checkpoint = store.get_latest_checkpoint(run.id)
    assert checkpoint is not None
    checkpointed = checkpoint["state"]["state"]["hypotheses"]
    assert checkpointed and all(not h.get("reviews") for h in checkpointed)
    checkpointed_ids = {h["id"] for h in checkpointed}

    resume_events = await _drain_all(
        _engine_stream(run.id, run.research_goal, cfg, resume=True)
    )

    # The resume caught up: it ran review + the pre-ranking safety screen.
    resumed_types = [e["type"] for e in resume_events]
    assert "review" in resumed_types
    assert "safety_screen" in resumed_types
    assert "supervisor.plan" not in resumed_types  # supervisor never re-runs

    # Completed generation is preserved and the latent-only output is published:
    # rank-and-publish ranks the ungrounded ideas (badged "Unverified") rather
    # than withholding a report.
    report = store.get_latest_report(run.id)
    assert report is not None
    assert report["payload"]["leaderboard"]  # ranked ideas were published
    final_ids = {h["id"] for h in store.list_hypotheses(run.id)}
    assert checkpointed_ids <= final_ids
    assert resume_events[-1]["payload"].get("status") == "completed"


async def test_engine_resume_does_not_repeat_completed_llm_calls(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resuming makes fewer LLM calls than a full run (work is reused)."""
    _install_fake_engine_llm(monkeypatch)
    cfg = _engine_cfg()

    import litellm

    calls = {"n": 0}
    original = litellm.acompletion

    async def _counting(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(litellm, "acompletion", _counting)

    # Baseline: an uninterrupted run's total LLM-call count.
    full_run = store.create_run("Engine full", "standard", "engine", {})
    await _drain_all(_engine_stream(full_run.id, full_run.research_goal, cfg))
    full_run_calls = calls["n"]
    assert full_run_calls > 0

    # Interrupt a fresh run at the safe boundary, then resume.
    calls["n"] = 0
    run = store.create_run("Engine resume calls", "standard", "engine", {})

    def _safe_boundary(_seen: list[dict[str, Any]]) -> bool:
        cp = store.get_latest_checkpoint(run.id)
        if cp is None:
            return False
        hyps = cp["state"].get("state", {}).get("hypotheses", [])
        return bool(hyps) and all(h.get("reviews") for h in hyps)

    await _drain_until(
        _engine_stream(run.id, run.research_goal, cfg), _safe_boundary
    )
    calls_before_resume = calls["n"]

    await _drain_all(
        _engine_stream(run.id, run.research_goal, cfg, resume=True)
    )
    resume_calls = calls["n"] - calls_before_resume

    # A true resume re-enters at the orchestrator and re-runs only the
    # remaining nodes, so the resumed segment makes strictly fewer LLM calls
    # than a full run from the goal would. A from-zero re-run (the old
    # behavior) would instead repeat the entire first pass.
    assert 0 < resume_calls < full_run_calls


async def test_launch_resume_drives_engine_resume_end_to_end(
    isolated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The app's real resume launcher resumes an engine run from its checkpoint.

    Exercises ``runs._launch_resume`` (the endpoint's launcher) rather than the
    adapter seam directly, proving the engine branch does not clear derived
    data — the pre-interruption events survive — and drives a true resume.
    """
    import app.runs as runs_mod

    _install_fake_engine_llm(monkeypatch)
    cfg = _engine_cfg()
    run = store.create_run("Launch resume", "standard", "engine", {})

    def _safe_boundary(_seen: list[dict[str, Any]]) -> bool:
        cp = store.get_latest_checkpoint(run.id)
        if cp is None:
            return False
        hyps = cp["state"].get("state", {}).get("hypotheses", [])
        return bool(hyps) and all(h.get("reviews") for h in hyps)

    await _drain_until(
        _engine_stream(run.id, run.research_goal, cfg), _safe_boundary
    )
    pre_resume_seqs = {e["seq"] for e in store.list_events(run.id)}
    assert pre_resume_seqs  # supervisor..review events were persisted
    # An interrupted run is left non-terminal; the launcher requires that.
    store.update_run_status(run.id, store.RunStatus.RUNNING)

    await runs_mod._launch_resume(run.id)
    await asyncio.gather(*list(runs_mod._resume_tasks))

    # Engine checkpoint => derived data NOT cleared => pre-resume events kept.
    all_events = store.list_events(run.id)
    all_seqs = [e["seq"] for e in all_events]
    assert pre_resume_seqs <= set(all_seqs)
    assert len(all_seqs) == len(set(all_seqs))  # unique
    assert all_seqs == sorted(all_seqs)  # monotonic
    # The launcher reaches finalization exactly once. This fixture supplies no
    # evidence, so the ideas are latent-only (unverified); rank-and-publish
    # ranks and publishes them (badged "Unverified") rather than blocking.
    report = store.get_latest_report(run.id)
    assert report is not None
    assert report["payload"]["leaderboard"]  # ranked ideas were published
    final = store.get_run(run.id)
    assert final is not None
    assert final.status == store.RunStatus.COMPLETED.value
