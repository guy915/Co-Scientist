# Production shrink

Bring the code that stays after `docs/PROD-CUTS.md` down to the size its
features need. Behavior does not change; only how the code is written does.
The owner approved every lever below on 6 October 2026.

**Status (7 October 2026): done for v0.** Every lever is merged, deferred or
reported as not worth its risk; board #240 holds each decision and its
evidence. The format change removed 7,510 lines, reported separately. The
levers removed 3,729 more: 884 in Python and 2,845 in the frontend, net of
the markup the styling moves added.

| # | Result | PRs | Net lines |
|---|---|---|---:|
| 1 | Merged | #239 | −7,510 |
| 2 | Merged; the durable-task commit path stays as is | #269, #275, #281 | −642 |
| 3 | Not worth its risk: the five phases already share their machinery | — | — |
| 4 | Reduced: never-passed store parameters removed; an ambient connection is not worth its risk | #282 | −114 |
| 5 | Merged (app groups land inside #281); test-fixture clones are left | #276 | −43 |
| 6 | Merged outside the benchmark-hashed files; `log_failures` and `_JsonCallSpec` wait for the model lane | #320 | −85 |
| 7 | Merged; the remaining `index.css` tidy is not worth its own PR | #277, #299, #301, #305–#308, #317, #318 | −2,845 |
| 8 | Already done before the campaign | — | 0 |
| 9 | Not worth its risk (library weight and a dropped-reload hazard) | — | — |
| 10 | Deferred to after v0: unchanged tests force a dict adapter, so the pilot grew | — | — |
| 11 | Not worth its risk for v0 | — | — |

Every styling PR was checked against its base with a computed-style and
screenshot comparison in light and dark, at the breakpoint edges each one
touches.

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

The format change goes first. Then the shrink works folder by folder as the
cuts finish each folder, so it never touches code that is about to be
deleted. Levers that touch nearly every file run in the short windows
`docs/CAMPAIGNS.md` schedules.

1. **Day 1, first and alone:** the lint and format change (1), as the only
   open PR that changes Python files. Every later PR in every campaign is
   written to the new limits, so wrapper inlining (2) can go further.
2. **Engine and MCP server**, once their cuts merge: 5, 2, then 6 after the
   model-usage work in `docs/OPTIMIZATION.md` releases the LLM stack.
3. **App backend**, once its cuts merge: 4, 3, 5, 2.
4. **Frontend**, once its cuts merge: 8, 7, 9.
5. **In windows:** the engine move (11), then typed models (10), one PR per
   concept; concepts whose files do not overlap run at once. If time runs
   short, typed models move to after v0.

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
