# Production shrink

Bring the code that stays after `docs/PROD-CUTS.md` down to the size its
features need. Behavior does not change; only how the code is written does.
The owner approved every lever below on 6 October 2026.

**Status:** not started. Work on a folder starts once that folder's cuts in
`docs/PROD-CUTS.md` are merged; the whole cuts plan leaves about 96k lines.
The expected result is about 80k, plus about 4k from the line-length change,
reported separately.

## Why the code is large

Literal copy-paste is small (about 1.5k lines). The size comes from habits:

- **Lint limits that force splitting.** An 80-column limit, cyclomatic
  complexity 10 and 8 arguments per function produced about 340 one-line
  wrapper functions (`_run_and_log_x` → `_run_x` → `_phase_x`) and many
  argument-carrier `NamedTuple`s and dataclasses.
- **Untyped data.** About 2,400 `dict[str, Any]`, 2,100 `.get(` calls,
  500 `isinstance` checks and 220 `parse_`/`normalize_`/`coerce_` helpers:
  every layer re-checks data the previous layer already checked.
- **One pattern written five times.** Generation, review, verification, mature
  reflection and ranking each hand-write their own item tasks and aggregate
  task in `app/app/engine_tasks/`.
- **Connection plumbing.** `db_path=None, conn=None` is declared about 290
  times and passed along about 330 times in `app/app/`.
- **Three styling systems** in the frontend: Tailwind, 209 `*_CLASSES`
  constants and 4.8k lines of custom CSS.
- **Two packages with a translation layer.** The engine is internal, but it is
  still a separate package with its own config, Python 3.10 support and an
  adapter in the app.

## What changes

| # | Change | ≈ Lines | Risk |
|---|---|---:|---|
| 1 | Lint: allow 100 columns, raise mccabe to 15, drop `PLR0913`. One formatting PR, nothing else in it | 4.4k (reported separately) | Low |
| 2 | Inline one-line wrappers and argument-carrier types into their callers | 2–4k | Low per change |
| 3 | One generic fan-out primitive (enqueue items, run item, merge) for the five phases | 1.5k | Medium |
| 4 | Scope the SQLite connection with a context variable; drop `db_path`/`conn` parameters | 0.8k | Low |
| 5 | Remove literal duplicates found by the clone scan | 0.7k | Low |
| 6 | Merge the LLM retry, escalation and JSON-attempt paths | 1k | Medium |
| 7 | Frontend: inline `*_CLASSES` constants and move custom CSS to Tailwind | 1.5–2.5k | Medium |
| 8 | Frontend: generate API types from the backend OpenAPI schema | 0.5k | Low |
| 9 | Frontend: replace hand-written fetching, polling and rehydration with a data-fetching library | ~1k | Medium |
| 10 | Typed models end to end for hypotheses, reviews, evidence, matches and claims; delete the normalizers they make redundant | 3–5k | High |
| 11 | Move the engine into the app as one package; drop Python 3.10 and the adapter layer | 1–2k | High |

## Order

Folder by folder, as the cuts finish each folder, so shrinking never touches
code that is about to be deleted:

1. **Engine and MCP server**, once their cuts merge: 5, 2, 6.
2. **App backend**, once its cuts merge: 4, 3, 5, 2.
3. **Frontend**, once its cuts merge: 8, 7, 9.
4. **Last, with no other campaign PR open:** the engine merge (11), then typed
   models (10) one concept per PR, then the lint and format change (1) alone.
   These touch nearly every file, so they run when nothing else is in flight.

Because the 80-column limit and complexity rules stay until step 4, inline
wrappers (2) only where the result still passes the current lint.

## Rules

- **Behavior stays identical.** Tests that pass before a PR pass after it,
  unchanged except for imports and renamed internals.
- **Invariants hold.** Read `docs/OPERATIONS.md` before touching durable
  tasks, the store or the LLM stack: idempotency, leases, retry budgets,
  bounded calls, spend caps, evidence gates and append-only lineage.
- **Real cuts only.** No moving logic into JSON, YAML or Markdown, and no
  formatting tricks beyond change 1. Report line counts with and without it.
- **UI.** Changes 7 and 9 keep the look and behavior: compare screenshots in
  light and dark themes before and after, and run `make e2e`.
- **Dependencies.** A new library must remove more code than it adds and pass
  `make audit-deps`; regenerate locks with the repo tooling.
- **Data.** Typed models (10) keep the stored formats; a model reads what the
  database already holds.
- **One theme per PR.** Run `make lint`, `make typecheck`, `make test-all` and
  `make e2e` before each. After each merge, check production health.
- **Docs in the same PR,** including `AGENTS.md` files when structure or
  commands change.
