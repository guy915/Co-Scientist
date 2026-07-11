"""Deterministic mock workflow used when no LLM provider is configured.

It emits the full agent-equivalent sequence the real engine produces — so the
backend, persistence layer, SSE stream, and frontend can be exercised end-to-end
without any external API calls.

Intake safety screening runs upstream at the shared workflow boundary
(``engine_adapter.run_workflow``) before this generator, so it is not emitted
here. Stages emitted (in order):
1. status: running
2. supervisor.plan       — research plan + agent DAG
3. literature_review     — retrieved evidence list
4. generate              — initial hypotheses (initial_count)
5. reflection            — per-hypothesis reflection notes
6. proximity             — clusters
7. ranking               — Elo tournament across pairs
8. evolve                — mutate top-k → child hypotheses (parent_id set)
9. ranking (post-evolve) — second round of Elo updates
10. meta_review          — synthesis critique
11. deep_verification    — probing Q&A + verdict on top-k by Elo (reviews)
12. citation_audit       — classify each citation
13. research_overview    — research overview + NIH Specific Aims (report)
14. safety.final         — final-output gate
15. report               — assembled report
16. status: completed

The output is fully deterministic given (research_goal, run mode, config). This
matters: tests assert against the workflow's behaviour, not flaky LLM output.

The implementation is split across focused modules:

- ``mock_workflow_seeds`` — pure, deterministic content generators.
- ``mock_workflow_phases`` — sync persistence helpers for each numbered phase.
- ``mock_workflow_stages`` — async stage generators that emit the events.

This module keeps only the ``run_mock_workflow`` entry point both providers
and the tests consume.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from app.mock_workflow_phases import _seed_tournament_round
from app.mock_workflow_seeds import _seeded_rng
from app.mock_workflow_stages import (
    _is_cancelled,
    _run_seed_stages,
    _run_tournament_and_finalize,
)
from app.report_render import make_emitter
from app.run_modes import CANONICAL_RUN_MODE


async def run_mock_workflow(
    run_id: str,
    research_goal: str,
    config: dict[str, Any],
    *,
    db_path: str | None = None,
    cancelled: asyncio.Event | None = None,
    sleep_seconds: float = 0.05,
) -> AsyncIterator[dict[str, Any]]:
    """Execute the deterministic mock workflow and yield events as they happen.

    Intake safety screening is applied upstream at the shared workflow boundary
    (``engine_adapter.run_workflow``); this generator assumes intake passed.
    ``config`` must already be resolved via ``resolved_run_config`` — the
    shared boundary does this for every provider.
    """
    run_mode = CANONICAL_RUN_MODE
    cfg = config
    rng = _seeded_rng("mock", run_id, research_goal, run_mode)
    emit = make_emitter(run_id, db_path=db_path, sleep_seconds=sleep_seconds)

    # ---- 1-6. Mark running through proximity/clustering ----
    evidence_payload: list[dict[str, Any]] = []
    hyp_ids: list[str] = []
    hyp_payloads: list[dict[str, Any]] = []
    async for event in _run_seed_stages(
        run_id,
        research_goal,
        db_path,
        rng,
        cfg,
        run_mode,
        cancelled=cancelled,
        emit=emit,
        evidence_payload=evidence_payload,
        hyp_ids=hyp_ids,
        hyp_payloads=hyp_payloads,
    ):
        yield event
    if _is_cancelled(cancelled):
        # _run_seed_stages already emitted the "cancelled" status event; skip
        # ranking/evolution/finalization on a cancelled run.
        return

    # ---- 7. First ranking round ----
    elo_state, title_by_id, pairs = _seed_tournament_round(
        hyp_ids, hyp_payloads, rng, cfg["tournament_pairs"]
    )

    # ---- 8-14. Ranking/evolve/meta-review iterations, then finalization ----
    async for event in _run_tournament_and_finalize(
        run_id,
        research_goal,
        run_mode,
        db_path,
        rng,
        cfg,
        pairs,
        elo_state,
        title_by_id,
        hyp_ids,
        evidence_payload,
        cancelled=cancelled,
        emit=emit,
    ):
        yield event
