# ADR: Remove computational discovery

**Status:** Accepted · 2026-08-26
**Removes:** the discovery run mode, shipped 2026-08-19
(`768616df`..`6a1e6be5`), documented in the now-deleted `docs/DISCOVERY.md`

## Context

Computational discovery was a second run mode. A `discovery` key in a run's
config made the run evolve a *program* against a measured objective instead of
generating hypotheses: a seed program, an LLM-proposed V4A patch per
generation, a sandboxed evaluation cascade, Pareto scoring across several
objectives, and a MAP-Elites archive that selected parents by behavioural
niche rather than by score. It reused the durable task queue, the safety gate
and the run lifecycle, and reached users through three entry points — a
`discovery` object on `POST /api/runs`, `cosci runs create --discovery`, and
an "Or evolve a program against a measured objective" button under the
workbench composer.

It was well built and it worked. It was also a second product sharing only
infrastructure with the first: no hypothesis, no literature, no tournament,
no report field in common. Every surface that touched a run had to ask which
kind of run it was — the tab nav, the recents card, the live metrics row, the
report view, the completion email's deep link, resume, and startup
reconciliation. That branching is the cost the feature charged whether or not
anyone started a discovery run.

## Decision

Remove it. The product generates and ranks scientific hypotheses.

## What went

- Engine: `agents/code_evolve/` (archive, grid, behaviour, fingerprint,
  tessellation, proposal, context) and `code_eval/` (runner, spec, Pareto).
- App: `discovery_spec.py`, `discovery_dataset.py`, `discovery_execution.py`,
  `discovery_report.py`, `engine_tasks_variants.py`,
  `engine_tasks_variants_schedule.py`, `store/code_variants.py`,
  `store/schema_code_variants.py`, and the three
  `engine.fanout.variant.*` task types.
- API: `GET /api/runs/{id}/variants`, `GET /api/runs/{id}/variants/{vid}`, the
  `discovery` field on `POST /api/runs`, the `code_execution_available` field
  on `/status`, and the CLI's `--discovery` flag.
- Frontend: the composer entry point and its dialog, the Variants tab and its
  plot and trade-off views, the discovery report view, the recents-card
  attempt/best-score summary, and the objective sign-correction helper.
- The per-run branching every one of those forced: `tabsForRun`, the live
  view's run-kind metrics, `_resume_detail`, `has_resumable_discovery_work`,
  and the completion email's tab choice all collapse back to one path.

## What stayed, and why

`sandbox/`, `workspace/` and `patch/` are **not** discovery code. Reflection's
simulation review runs real programs through them, and the generation agent's
drafting skills run commands through them. They are load-bearing on the
hypothesis path and are untouched.

## Existing data

No `DROP TABLE` migration ships with this change. A database created before it
keeps its `code_variants`, `code_variant_state`, `code_variant_metrics`,
`code_variant_artifacts` and `code_datasets` tables as orphans; nothing reads
or writes them. A fresh database never creates them. Dropping tables is a
destructive migration whose only benefit is tidiness, and a volume in
production is the wrong place to buy tidiness. Offline compaction can reclaim
the space by hand against a stopped database if it ever matters.

A discovery run already in the store still lists and opens: its run row,
events and report are ordinary rows, and the surfaces that used to branch on
its config key now render it as an ordinary run — its tabs are the hypothesis
tabs, which are empty for it.

## Consequences

- A queued `engine.fanout.variant.*` task left in a database by an
  interrupted run is now an unknown task type. It still carries the `engine.`
  prefix, so the worker routes it to the engine dispatcher, finds no handler,
  and raises a plain `ValueError` — which is *not* `UnsupportedTaskError`, so
  it spends its three attempts before settling as `failed`. Three instant
  failures, not a retry loop, and no run that was still generating
  hypotheses is affected. This was measured rather than assumed: the
  dispatcher's fallthrough raises `ValueError`, and only
  `UnsupportedTaskError` is a permanent task failure.
- Two entries left the root `AGENTS.md` gotcha list with the code they
  described: the multi-objective/Pareto rule and the crashing-variant rule.
  Both were true and both are now only reachable through this ADR and the
  deleted files' history.
