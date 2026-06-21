# ADR: Restart-safe research runs

**Status:** Accepted · 2026-06-21
**Drains reference:** `references/core/coding-agent-harness/`

Captures what we take from the "serious, restart-safe, repository-native
coding-agent harness" survey so the report can be deleted. Stands alone.

## Context

The survey argues a long-running agent harness should be **composed** from
best-of-class layers — OpenHands (agent shell), Temporal/Trigger.dev (durable
orchestration), Daytona (sandboxed execution), Dagger (hermetic CI),
Langfuse/Phoenix (observability) — and that its core transferable *patterns*
are: durability & restart-safety, resumable/checkpointed long runs,
sandboxed/safe execution, observability/tracing/evals, and human-in-the-loop
waitpoints.

Co-Scientist already realizes the most important pattern: an **append-only
event log with SSE replay**, so a completed run reopens after a browser refresh
or backend restart. Runs execute as FastAPI background tasks over a LangGraph
engine, persisting to SQLite (WAL).

**Co-Scientist is the main character.** This reference is secondary, and most of
its surface is *coding-agent specific* — repository sandboxing, GitHub-issue
intake, LSP/Git tool exposure, SWE-bench evaluation. Those fail the
main-character test (we run research, not code edits) and are declined.

## Decisions

1. **Keep the stack** (FastAPI + LangGraph + SQLite). We do **not** adopt
   Temporal, Trigger.dev, Daytona, Dagger, or Langfuse/Phoenix. We take the
   *patterns*, not the products — a durable-orchestration platform would be a
   large rewrite that the research workload does not justify.

2. **Adopt restart-safety for long research runs** — the survey's #1 pattern.
   Three concrete fixes (built; see below): reconcile interrupted runs on
   startup, checkpoint the WAL on shutdown, and make the client-isolation purge
   one-time so runs do not vanish on restart.

3. **Decline coding-agent-specific surface:** per-task sandboxing/isolation,
   GitHub-native task intake, LSP/Git tool exposure, SWE-bench-style external
   benchmarking. Not applicable to a hypothesis-generation research product.

4. **Defer (not now):** resume-from-checkpoint (re-enter a partially-completed
   workflow rather than re-running) is a genuinely useful but large change to
   the engine's streaming contract; recorded as future work, not built here.

## What was built

- **Interrupted-run reconciliation** (`store.reconcile_interrupted_runs`, called
  in `main.py` lifespan startup). A fresh process has no workflow tasks running,
  so any run still `queued`/`running`/`synthesizing` was interrupted; it is
  transitioned to `failed` ("Run interrupted by a server restart.") with a
  status event, instead of being stuck in-progress forever (and un-startable,
  since `start_run` rejects in-progress runs). Reconciled runs are re-startable.
- **WAL checkpoint on shutdown** (`store.checkpoint_wal`, lifespan shutdown) so a
  clean stop leaves committed data in the main DB file, not a `-wal` sidecar.
- **One-time client-isolation purge** (`store._run_migrations`). The
  `DELETE FROM runs WHERE client_id = ''` ran on **every** startup, silently
  deleting every header-less (no `X-Client-ID`) run on each restart. Moved
  inside the column-added guard so it runs once. **This was the actual cause of
  the "completed run vanished after restart" symptom** seen in testing — not a
  WAL durability defect. Production was never affected (the frontend always
  sends a client id; prod also uses an absolute `COSCIENTIST_DB_PATH`).

## Consequences

- A research run survives a backend restart: it is either reopened (terminal)
  or cleanly marked interrupted+failed (and re-startable), never silently lost
  or stuck "running" forever.
- No new infrastructure or dependencies.
- Resume-from-checkpoint and the coding-agent-specific surface are explicitly
  out of scope; the report can be deleted at cleanup.
