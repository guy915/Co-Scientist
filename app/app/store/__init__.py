"""SQLite-backed persistence for runs, hypotheses, evidence, and reports.

Design choices:

- Pure stdlib `sqlite3` so the app picks up no new runtime deps.
- WAL mode + per-thread connections via a context manager.
- The event log is append-only and is the canonical timeline reopened on
  refresh / restart.
- Hypotheses are append-only: `evolve` writes new rows with `parent_id` set;
  no row is ever mutated in place. Updates that *are* allowed (Elo, status,
  scores) live in `hypothesis_state`, keyed by hypothesis id, leaving the
  original row untouched.
- Reports are stored both as a structured JSON blob and a rendered Markdown
  artifact on disk (path tracked in the row).

The package is split by concern: ``db`` (connections, schema, migrations),
``models`` (row dataclasses and enums), ``runs`` (run CRUD and lifecycle),
``events`` (append-only event log), ``hypotheses``, ``records`` (evidence,
citations, reviews, matches, safety), ``reports``, and ``messages``. This
module re-exports the public API so callers keep using ``from app import
store`` / ``from app.store import ...`` unchanged.
"""

from __future__ import annotations

from app.store.checkpoints import (
    clear_checkpoints,
    get_latest_checkpoint,
    has_checkpoint,
    save_checkpoint,
)
from app.store.db import (
    checkpoint_wal,
    connect,
    transaction,
)
from app.store.events import append_event, latest_event_seq, list_events
from app.store.hypotheses import (
    add_hypothesis,
    get_hypothesis,
    list_hypotheses,
    redact_hypothesis_fields,
    update_hypothesis_state,
)
from app.store.interviews import (
    append_interview_turn,
    create_interview,
    get_interview,
    update_interview,
)
from app.store.messages import (
    append_message,
    get_pending_steering,
    list_messages,
    mark_steering_applied,
)
from app.store.metrics import (
    get_run_metrics,
    save_run_metrics,
)
from app.store.models import (
    DEMO_CLIENT_ID,
    TERMINAL_STATUSES,
    MessageRow,
    RunRow,
    RunStatus,
)
from app.store.records import (
    add_citation,
    add_claim_evidence,
    add_evidence,
    add_match,
    add_proximity_edge,
    add_review,
    add_safety_decision,
    list_citations,
    list_claim_evidence,
    list_evidence,
    list_matches,
    list_proximity_edges,
    list_reviews,
    list_safety_decisions,
    resolve_safety_decision,
    safety_stage_is_approved,
)
from app.store.reports import (
    get_latest_report,
    read_report_markdown,
    save_report,
)
from app.store.runs import (
    clear_publication_artifacts,
    clear_run_derived_data,
    create_run,
    get_run,
    list_runs,
    reconcile_interrupted_runs,
    reserve_run_capacity,
    run_exists,
    run_used_offline,
    set_run_llm_backend,
    set_run_title,
    summary_counts,
    update_run_status,
)
from app.store.shares import (
    create_report_share,
    list_report_shares,
    resolve_report_share,
    revoke_report_share,
)
from app.store.tasks import (
    ScientificTask,
    cancel_run_tasks,
    cancel_task,
    claim_task,
    complete_task,
    enqueue_task,
    fail_task,
    get_task,
    list_active_engine_task_run_ids,
    list_tasks,
    pause_run_tasks,
    renew_task_lease,
    reprioritize_task,
    resume_run_tasks,
    retry_task,
    task_progress,
)

__all__ = [
    "DEMO_CLIENT_ID",
    "TERMINAL_STATUSES",
    "MessageRow",
    "RunRow",
    "RunStatus",
    "ScientificTask",
    "add_citation",
    "add_claim_evidence",
    "add_evidence",
    "add_hypothesis",
    "add_match",
    "add_proximity_edge",
    "add_review",
    "add_safety_decision",
    "append_event",
    "append_interview_turn",
    "append_message",
    "cancel_run_tasks",
    "cancel_task",
    "checkpoint_wal",
    "claim_task",
    "clear_checkpoints",
    "clear_publication_artifacts",
    "clear_run_derived_data",
    "complete_task",
    "connect",
    "create_interview",
    "create_report_share",
    "create_run",
    "enqueue_task",
    "fail_task",
    "get_hypothesis",
    "get_interview",
    "get_latest_checkpoint",
    "get_latest_report",
    "get_pending_steering",
    "get_run",
    "get_run_metrics",
    "get_task",
    "has_checkpoint",
    "latest_event_seq",
    "list_active_engine_task_run_ids",
    "list_citations",
    "list_claim_evidence",
    "list_events",
    "list_evidence",
    "list_hypotheses",
    "list_matches",
    "list_messages",
    "list_proximity_edges",
    "list_report_shares",
    "list_reviews",
    "list_runs",
    "list_safety_decisions",
    "list_tasks",
    "mark_steering_applied",
    "pause_run_tasks",
    "read_report_markdown",
    "reconcile_interrupted_runs",
    "redact_hypothesis_fields",
    "renew_task_lease",
    "reprioritize_task",
    "reserve_run_capacity",
    "resolve_report_share",
    "resolve_safety_decision",
    "resume_run_tasks",
    "retry_task",
    "revoke_report_share",
    "run_exists",
    "run_used_offline",
    "safety_stage_is_approved",
    "save_checkpoint",
    "save_report",
    "save_run_metrics",
    "set_run_llm_backend",
    "set_run_title",
    "summary_counts",
    "task_progress",
    "transaction",
    "update_hypothesis_state",
    "update_interview",
    "update_run_status",
]
