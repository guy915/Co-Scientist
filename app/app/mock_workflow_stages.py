"""Async stage generators that drive and emit the mock workflow.

These coroutines orchestrate the numbered mock-workflow stages: they call the
sync persistence helpers in ``mock_workflow_phases``, draw pure content from
``mock_workflow_seeds``, and ``yield`` the emitted event for each stage. The
top-level ``run_mock_workflow`` entry point (in ``mock_workflow``) composes them
into the full run, and each generator propagates cancellation so a cancelled run
stops emitting after its terminal ``"cancelled"`` status event.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator
from typing import Any

from app import store
from app.claim_grounding import evidence_passages, ground_hypotheses
from app.hypothesis_screening import screen_hypotheses
from app.mock_workflow_phases import (
    _apply_pending_steering,
    _fetch_top_hypotheses,
    _persist_citation_audit,
    _persist_deep_verification,
    _persist_generation,
    _persist_literature_review,
    _persist_meta_review_round,
    _persist_mock_metrics,
    _persist_proximity,
    _persist_reflection,
    _run_evolve_round,
    _run_ranking_round,
)
from app.mock_workflow_seeds import (
    _MOCK_SUMMARY,
    DEEP_VERIFICATION_TOP_K,
    _build_supervisor_plan,
    _ranking_round_payload,
    _research_overview_seed,
)
from app.report_render import (
    EmitFn,
    article_stub,
    emit_cancel_or_pause,
    finalize_report,
    hypothesis_stub,
)
from app.run_modes import CANONICAL_RUN_MODE
from app.store import RunStatus


async def _run_evolve_and_meta_review_round(
    run_id: str,
    research_goal: str,
    db_path: str | None,
    rng: random.Random,
    hyp_ids: list[str],
    elo_state: dict[str, int],
    evolution_max_count: int,
    itr: int,
    emit: EmitFn,
) -> AsyncIterator[dict[str, Any]]:
    """Evolve the top-k hypotheses and persist the per-iteration meta-review.

    Mutates `hyp_ids` and `elo_state` in place via `_run_evolve_round`.
    """
    # ---- 8. Evolve top-k ----
    top_k, children = _run_evolve_round(
        run_id,
        db_path,
        rng,
        research_goal,
        hyp_ids,
        elo_state,
        evolution_max_count,
    )
    # Safety review after material evolution (SSR §4): screen each new child
    # and drop any blocked one from the tournament pool before it re-ranks.
    result = screen_hypotheses(run_id, children, db_path=db_path)
    children = _drop_blocked_children(
        children, hyp_ids, elo_state, result.blocked_ids
    )
    yield await emit(
        "evolve",
        {
            "children": [hypothesis_stub(c) for c in children],
            "iteration": itr,
        },
    )

    # ---- 9. Meta-review (per iteration) ----
    mr_critique = _persist_meta_review_round(
        run_id, db_path, itr, top_k, hyp_ids
    )
    yield await emit(
        "meta_review",
        {
            "iteration": itr,
            "critique": mr_critique,
            "top_k_ids": [t[0] for t in top_k],
        },
    )


def _is_cancelled(cancelled: asyncio.Event | None) -> bool:
    """True if a cancellation event has been set."""
    return bool(cancelled and cancelled.is_set())


async def _emit_cancelled_if_set(
    run_id: str,
    db_path: str | None,
    cancelled: asyncio.Event | None,
    emit: EmitFn,
) -> dict[str, Any] | None:
    """If the stop signal is set, persist and emit the closing status event.

    Returns the emitted status event, or None if no stop was requested.
    """
    if not _is_cancelled(cancelled):
        return None
    return await emit_cancel_or_pause(run_id, db_path, emit)


# Version of the app-level (envelope) checkpoint the mock writes at iteration
# boundaries. Bumped only if the envelope shape below changes.
APP_CHECKPOINT_SCHEMA_VERSION = 1


def _save_iteration_checkpoint(
    run_id: str, db_path: str | None, cfg: dict[str, Any], iteration: int
) -> None:
    """Persist an envelope checkpoint at a mock iteration boundary.

    The envelope carries just enough to relaunch a deterministic reconstruction
    (config + run mode + iteration reached); the mock re-derives all artifacts
    from the run's stable seed, so no engine state is captured here.
    """
    store.save_checkpoint(
        run_id,
        stage=f"iteration_{iteration}",
        schema_version=APP_CHECKPOINT_SCHEMA_VERSION,
        last_event_seq=store.latest_event_seq(run_id, db_path=db_path),
        state={
            "provider": "mock",
            "run_mode": CANONICAL_RUN_MODE,
            "iteration": iteration,
            "config": cfg,
        },
        db_path=db_path,
    )


async def _run_tournament_iterations(
    run_id: str,
    research_goal: str,
    db_path: str | None,
    rng: random.Random,
    cfg: dict[str, Any],
    pairs: list[tuple[str, str]],
    elo_state: dict[str, int],
    title_by_id: dict[str, str],
    hyp_ids: list[str],
    *,
    cancelled: asyncio.Event | None,
    emit: EmitFn,
) -> AsyncIterator[dict[str, Any]]:
    """Run the ranking/evolve/meta-review iteration loop, emitting per round.

    Runs ``max_iterations`` rounds that each include evolve/meta, plus one
    trailing ranking-only pass over the evolved population before final
    reporting (``+2``, not ``+1``, in the range below). Mutates `elo_state`
    and `hyp_ids` in place via `_run_ranking_round` /
    `_run_evolve_and_meta_review_round`. On cancellation, yields a final
    "cancelled" status event and returns early; the caller checks
    `cancelled.is_set()` once this generator is exhausted to distinguish
    that from a natural finish.
    """
    for itr in range(1, cfg["max_iterations"] + 2):
        _apply_pending_steering(run_id, db_path, itr)
        round_matches = _run_ranking_round(
            run_id, db_path, itr, pairs, elo_state, title_by_id, cfg["k_factor"]
        )
        yield await emit("ranking", _ranking_round_payload(itr, round_matches))

        # Durable checkpoint at the iteration boundary (Milestone 4): a run
        # interrupted or paused after this point is resumable from here.
        _save_iteration_checkpoint(run_id, db_path, cfg, itr)

        cancelled_event = await _emit_cancelled_if_set(
            run_id, db_path, cancelled, emit
        )
        if cancelled_event is not None:
            yield cancelled_event
            return

        # Only run evolve/meta inside iterations, not after the final
        # ranking pass.
        if itr <= cfg["max_iterations"]:
            async for event in _run_evolve_and_meta_review_round(
                run_id,
                research_goal,
                db_path,
                rng,
                hyp_ids,
                elo_state,
                cfg["evolution_max_count"],
                itr,
                emit,
            ):
                yield event


async def _finalize_mock_run(
    run_id: str,
    research_goal: str,
    run_mode: str,
    db_path: str | None,
    rng: random.Random,
    hyp_ids: list[str],
    elo_state: dict[str, int],
    evidence_payload: list[dict[str, Any]],
    emit: EmitFn,
) -> AsyncIterator[dict[str, Any]]:
    """Run deep verification, citation audit, and the final report.

    Covers stages 10-14: probing the top-k hypotheses by Elo, auditing
    citations, building the research overview, and handing off to the shared
    finalize path (final safety gate + report persistence/emission).
    """
    # ---- 10. Deep verification (top-k by Elo) ----
    leaderboard_ids = [
        hid for hid, _ in sorted(elo_state.items(), key=lambda kv: -kv[1])
    ]
    dv_entries = _persist_deep_verification(
        run_id, db_path, rng, leaderboard_ids, DEEP_VERIFICATION_TOP_K
    )
    yield await emit(
        "deep_verification",
        {
            "verified": len(dv_entries),
            "probes": dv_entries,
        },
    )

    # ---- 11. Citation audit ----
    cit_summary = _persist_citation_audit(
        run_id, db_path, hyp_ids, evidence_payload
    )
    yield await emit("citation_audit", cit_summary)

    # ---- 12. Final safety + report ----
    top_hypotheses = _fetch_top_hypotheses(db_path, leaderboard_ids, 5)

    # ---- 13. Research overview + NIH Specific Aims ----
    research_overview = _research_overview_seed(
        rng, research_goal, [h["title"] for h in top_hypotheses]
    )
    yield await emit(
        "research_overview", {"research_overview": research_overview}
    )

    # Deterministic engine-shaped execution metrics, persisted at the same
    # boundary where the engine adapter persists the real ones.
    _persist_mock_metrics(run_id, db_path)

    # ---- 14. Final safety + report, via the shared finalize path ----
    async for event in finalize_report(
        run_id=run_id,
        research_goal=research_goal,
        run_mode=run_mode,
        provider="mock",
        citation_summary=cit_summary,
        meta_review=None,
        research_overview=research_overview,
        emit=emit,
        summary=_MOCK_SUMMARY,
        db_path=db_path,
    ):
        yield event


async def _run_intake_stage(
    run_id: str,
    db_path: str | None,
    cfg: dict[str, Any],
    run_mode: str,
    *,
    cancelled: asyncio.Event | None,
    emit: EmitFn,
) -> AsyncIterator[dict[str, Any]]:
    """Mark the run running and emit the supervisor plan (stages 1-2).

    On cancellation right after the plan is emitted, also yields the
    terminal "cancelled" status event; the caller checks `cancelled.is_set()`
    once this generator is exhausted to distinguish that from a natural
    finish.
    """
    # ---- 1. Mark running (intake screening runs at the shared boundary) ----
    store.update_run_status(run_id, RunStatus.RUNNING, db_path=db_path)
    yield await emit("status", {"status": "running"})

    # ---- 2. Supervisor plan ----
    plan = _build_supervisor_plan(cfg, run_mode)
    yield await emit("supervisor.plan", plan)
    if _is_cancelled(cancelled):
        store.update_run_status(run_id, RunStatus.CANCELLED, db_path=db_path)
        yield await emit("status", {"status": "cancelled"})


async def _run_literature_and_generation(
    run_id: str,
    research_goal: str,
    db_path: str | None,
    rng: random.Random,
    cfg: dict[str, Any],
    emit: EmitFn,
    evidence_payload: list[dict[str, Any]],
    hyp_ids: list[str],
    hyp_payloads: list[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    """Seed and emit the literature review and initial generation.

    Covers stages 3-4. Mutates `evidence_payload`, `hyp_ids`, and
    `hyp_payloads` in place so the caller can use them once this generator is
    exhausted.
    """
    # ---- 3. Literature review ----
    evidence_payload.extend(
        _persist_literature_review(
            run_id, db_path, rng, research_goal, cfg["evidence_count"]
        )
    )
    yield await emit(
        "literature_review",
        {
            "count": len(evidence_payload),
            "evidence": [article_stub(e) for e in evidence_payload],
        },
    )

    # ---- 4. Generation ----
    generated_ids, generated_payloads = _persist_generation(
        run_id, db_path, rng, research_goal, cfg["initial_hypotheses_count"]
    )
    hyp_ids.extend(generated_ids)
    hyp_payloads.extend(generated_payloads)
    yield await emit(
        "generate",
        {
            "count": len(hyp_payloads),
            "hypotheses": [hypothesis_stub(h) for h in hyp_payloads],
        },
    )


async def _run_reflection_and_proximity(
    run_id: str,
    db_path: str | None,
    rng: random.Random,
    cfg: dict[str, Any],
    emit: EmitFn,
    hyp_ids: list[str],
    hyp_payloads: list[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    """Seed and emit reflection, safety, claim grounding, and proximity.

    Covers stages 5-6, with the pre-tournament reviews between them:
    reflection's preliminary safety screen (SSR §4, §10) and claim-level
    grounding + the publication gate (SSR §6, §7) both run before ranking, so a
    blocked or contradicted hypothesis never enters ranking or synthesis.
    """
    # ---- 5. Reflection ----
    _persist_reflection(
        run_id, db_path, rng, hyp_ids, hyp_payloads, cfg["evidence_count"]
    )
    yield await emit("reflection", {"reviewed": len(hyp_ids)})

    # ---- 5b. Per-hypothesis safety screen (before tournament entry) ----
    result = screen_hypotheses(run_id, hyp_payloads, db_path=db_path)
    _drop_blocked_hypotheses(hyp_ids, hyp_payloads, result.blocked_ids)
    yield await emit(
        "safety.hypothesis",
        {
            "screened": result.screened_count,
            "blocked": result.blocked_count,
            "eligible": len(hyp_ids),
        },
    )

    # ---- 5c. Claim grounding + publication gate (before tournament entry) --
    passages = evidence_passages(run_id, db_path=db_path)
    grounding = ground_hypotheses(
        run_id,
        hyp_payloads,
        passages,
        allow_speculative=True,
        db_path=db_path,
    )
    _drop_blocked_hypotheses(hyp_ids, hyp_payloads, grounding.blocked_ids)
    yield await emit(
        "citation.grounding",
        {
            "grounded": len(grounding.reason_by_id),
            "blocked": grounding.blocked_count,
            "eligible": len(hyp_ids),
        },
    )

    # ---- 6. Proximity / clustering ----
    clusters = _persist_proximity(db_path, hyp_ids)
    yield await emit(
        "proximity", {"clusters": {k: len(v) for k, v in clusters.items()}}
    )


def _drop_blocked_hypotheses(
    hyp_ids: list[str],
    hyp_payloads: list[dict[str, Any]],
    blocked_ids: frozenset[str],
) -> None:
    """Remove safety-blocked hypotheses from the tournament pool in place."""
    if not blocked_ids:
        return
    hyp_ids[:] = [hid for hid in hyp_ids if hid not in blocked_ids]
    hyp_payloads[:] = [
        h for h in hyp_payloads if str(h.get("id") or "") not in blocked_ids
    ]


def _drop_blocked_children(
    children: list[dict[str, Any]],
    hyp_ids: list[str],
    elo_state: dict[str, int],
    blocked_ids: frozenset[str],
) -> list[dict[str, Any]]:
    """Remove safety-blocked evolved children from the pool and Elo state.

    The child rows stay persisted (with their blocked ``safety_status``) so the
    UI can show them as blocked; they are only removed from the tournament pool
    (`hyp_ids`, `elo_state`). Returns the eligible children for the event.
    """
    if not blocked_ids:
        return children
    hyp_ids[:] = [hid for hid in hyp_ids if hid not in blocked_ids]
    for blocked_id in blocked_ids:
        elo_state.pop(blocked_id, None)
    return [c for c in children if str(c.get("id") or "") not in blocked_ids]


async def _run_seed_stages(
    run_id: str,
    research_goal: str,
    db_path: str | None,
    rng: random.Random,
    cfg: dict[str, Any],
    run_mode: str,
    *,
    cancelled: asyncio.Event | None,
    emit: EmitFn,
    evidence_payload: list[dict[str, Any]],
    hyp_ids: list[str],
    hyp_payloads: list[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    """Run stages 1-6 (mark running through proximity), emitting per stage.

    Marks the run running, emits the supervisor plan, then seeds and emits
    literature review, generation, reflection, and proximity results.
    Mutates `evidence_payload`, `hyp_ids`, and `hyp_payloads` in place so the
    caller can use them once this generator is exhausted. Cancellation is
    checked once, right after the supervisor plan is emitted; on
    cancellation, yields a final "cancelled" status event and returns early.
    The caller checks `cancelled.is_set()` once this generator is exhausted
    to distinguish that from a natural finish.
    """
    async for event in _run_intake_stage(
        run_id, db_path, cfg, run_mode, cancelled=cancelled, emit=emit
    ):
        yield event
    if _is_cancelled(cancelled):
        return

    async for event in _run_literature_and_generation(
        run_id,
        research_goal,
        db_path,
        rng,
        cfg,
        emit,
        evidence_payload,
        hyp_ids,
        hyp_payloads,
    ):
        yield event

    async for event in _run_reflection_and_proximity(
        run_id, db_path, rng, cfg, emit, hyp_ids, hyp_payloads
    ):
        yield event


async def _run_tournament_and_finalize(
    run_id: str,
    research_goal: str,
    run_mode: str,
    db_path: str | None,
    rng: random.Random,
    cfg: dict[str, Any],
    pairs: list[tuple[str, str]],
    elo_state: dict[str, int],
    title_by_id: dict[str, str],
    hyp_ids: list[str],
    evidence_payload: list[dict[str, Any]],
    *,
    cancelled: asyncio.Event | None,
    emit: EmitFn,
) -> AsyncIterator[dict[str, Any]]:
    """Run the tournament iterations, then finalize unless cancelled midway.

    Skips finalization entirely if cancellation is set once the tournament
    iterations finish; `_run_tournament_iterations` already emitted its own
    terminal "cancelled" status event in that case.
    """
    async for event in _run_tournament_iterations(
        run_id,
        research_goal,
        db_path,
        rng,
        cfg,
        pairs,
        elo_state,
        title_by_id,
        hyp_ids,
        cancelled=cancelled,
        emit=emit,
    ):
        yield event
    if _is_cancelled(cancelled):
        return

    # ---- 10-14. Deep verification, citation audit, and final report ----
    async for event in _finalize_mock_run(
        run_id,
        research_goal,
        run_mode,
        db_path,
        rng,
        hyp_ids,
        elo_state,
        evidence_payload,
        emit,
    ):
        yield event
