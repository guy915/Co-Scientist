"""Supervisor plan and allocation-ledger persistence for the drain (E19).

Before this existed, the Supervisor's research plan, its per-cycle task
allocations, and its terminal termination rationale lived only inside the
workflow checkpoint blob, which is pruned down to the newest row -- so a
completed run could not answer "why did this run do that". This module
turns the relevant final-checkpoint-state fields into the durable
``supervisor_plan``/``supervisor_allocations`` rows (see
``app.store.supervisor_plan``).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app import store


def _persist_supervisor_plan(
    run_id: str, final_state: dict[str, Any], conn: sqlite3.Connection
) -> None:
    """Persist the Supervisor's plan and per-cycle allocation ledger.

    Pure DB work computed entirely from the final checkpoint state already
    in memory -- no network I/O -- so it belongs in the drain's first
    (pure-DB) transaction alongside evidence/hypothesis persistence (see
    AGENTS.md: never hold the write lock across network I/O).

    Args:
        run_id: Run the drained state belongs to.
        final_state: The engine's accumulated final workflow state.
        conn: Open connection of the caller's transaction.
    """
    store.save_supervisor_plan(
        store.NewSupervisorPlan(
            run_id=run_id,
            guidance=final_state.get("supervisor_guidance") or {},
            termination_reason=final_state.get("termination_reason"),
            decision_provenance=final_state.get(
                "supervisor_decision_provenance"
            ),
            orchestrator_state=final_state.get("orchestrator_state") or {},
        ),
        conn=conn,
    )
    store.replace_supervisor_allocations(
        run_id, final_state.get("task_history") or [], conn=conn
    )
