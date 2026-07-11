# Final Report: Google-Style Comments and Docstrings Pass

## Summary

The stated goal was to add Google-style inline comments and docstrings across
the listed Co-Scientist areas. On inspection, **every listed area had already
received a comprehensive, high-quality Google-style commenting pass** (committed
on `main` before this branch was cut): WHY-comments for intent, invariants,
contracts, and trade-offs; Google-format docstrings with `Args:`/`Returns:`/
`Raises:`; JSDoc on exported symbols; `//` implementation notes. Adding more
comments to those files would have violated the goal's own rule against noise
("never restatements of the code").

The work this branch therefore contributes is the part of the goal that was
still genuinely outstanding: **verifying coverage area by area (by reading each
target module in full) and fixing the stale comments and malformed TODOs that
the earlier pass had left behind.** Five such defects were found and fixed —
four in the engine, one in the app store. The diff is strictly
comment/docstring lines — zero behavior changes.

## Files changed

| File | Fix |
|---|---|
| `engine/src/co_scientist/nodes/ranking.py` | `ranking_node` docstring was stale on three counts: it described "random pairwise matchups" (pairing is now weighted proximity-/recency-/rank-aware matchmaking), claimed "Tournament rounds = len(hypotheses) * 1" (rounds now come from the run tier's `tournament_pairs` setting), and omitted the multi-turn debate behavior. Also had an uncapitalized, non-sentence paragraph ("deterministic seeding: ..."), contrary to pyguide §3.8 punctuation rules. Rewritten to match the code. |
| `engine/src/co_scientist/nodes/evolve.py` (`_select_evolution_pool`) | A block comment justified the clamp by citing a "Keep ONLY the evolved hypotheses" behavior in `_finalize_evolve_result` that no longer exists (children are now appended; the pool no longer shrinks). Replaced with the actual reason the clamp matters (progress reporting counts real attempts). |
| `engine/src/co_scientist/nodes/evolve.py` (`evolve_node`) | Docstring claimed "each LLM call knows what all other hypotheses are"; the code passes a strategically sampled subset (top-Elo plus random, capped at 15). Corrected. |
| `engine/src/co_scientist/nodes/evolve_context.py` | Malformed bare `TODO:` (no link/context, contrary to pyguide §3.7 and the goal's TODO format) inside `calculate_text_similarity`'s docstring. Reworded as prose; updated the inline comment that cross-referenced it. |
| `app/app/store/hypotheses.py` | The `_HYP_SELECT` comment claimed "the joined columns are COALESCE'd to their column defaults and consumers can rely on them being non-null" — but only `elo_rating`/`win_count`/`loss_count` are COALESCE'd; the other six joined state columns (`novelty_score`, `plausibility_score`, `testability_score`, `safety_status`, `status`, `cluster_id`) are selected raw and are genuinely nullable (consumers such as `report_render._exclude_unsafe_hypotheses` do handle None). Corrected to scope the non-null guarantee to the three counters. |

Commits: `docs(engine): fix stale ranking and evolve docstrings`,
`docs(store): correct COALESCE nullability note on hypothesis projection`.

## Coverage verification (files read in full, found already compliant)

Kinds of comments already present are noted per area: **intent** (why the code
does what it does), **invariant** (what must stay true), **contract** (what
callers/callees may rely on), **trade-off** (why this approach over another).

### Engine
- `nodes/ranking.py`, `nodes/ranking_elo.py`, `nodes/ranking_matchmaking.py`,
  `nodes/ranking_prompt.py`, `nodes/ranking_results.py` — Elo math derivation
  (intent), deterministic seeding via hashlib rather than `hash()` (invariant),
  sequential Elo application after concurrent judging (ordering contract),
  upset-priority tier classification (intent), duplicate-avoidance reset ladder
  in matchmaking (invariant/trade-off).
- `nodes/evolve.py`, `evolve_context.py`, `evolve_prompt.py`,
  `evolve_results.py` — parent-never-mutated child construction (paper
  invariant), rejection sentinels `(None, None)` (contract), bounded token
  budget for sampled context (trade-off), diversity-instruction rationale
  (intent).
- `nodes/proximity.py`, `nodes/proximity_graph.py` — text-prefix rematching
  robustness (trade-off), first-match-wins degree assignment (invariant),
  graceful skip on malformed LLM output (intent), documented clone-default
  degree→weight mapping (trade-off).
- `state.py` — the `deduplicate_hypotheses` reducer's REPLACE vs. APPEND
  semantics, the empty-list-means-no-change sentinel (invariant), and why an
  evolved child coexists with its parent (contract).
- `cache.py`, `cache_llm.py`, `cache_nodes.py`, `cache_storage.py` — cache-key
  composition folding response-format shape into the key (invariant),
  first-call-wins env memoization (ordering constraint), `NullCache` rationale
  for diversity-critical calls (trade-off), atomic temp-file-then-rename writes
  and self-healing corrupt-entry reads (intent).
- `checkpoint.py` — versioned fail-closed restore (contract), exclusion sets
  with a "do not clean up" warning (protection against a future fix),
  wall-clock rebasing of `start_time` (invariant).

### App backend
- `store/db.py` — WAL/pragma setup, double-checked locking for schema init,
  the per-connection `foreign_keys` pragma caveat (invariant with downstream
  consequences), one-time client-isolation purge guard (protection against a
  future fix).
- `store/events.py` — single-statement seq assignment covering both the
  `run_events` max and the checkpoint `last_event_seq` high-water mark
  (invariant).
- `store/runs.py` — startup reconciliation of interrupted runs, resumable vs.
  failed split (intent), human-contribution preservation across resume
  (invariant), explicit child-table deletes because cascades are not enforced
  (contract).
- `store/checkpoints.py`, `store/hypotheses.py`, `store/messages.py`,
  `store/records.py`, `store/reports.py`, `store/models.py`,
  `store/__init__.py` — verified compliant (checkpoints read in full; the rest
  audited for staleness/gaps).
- `engine_adapter/provider.py` — sys.path injection rationale, `find_spec`
  probe trade-off, provider-selection ladder.
- `engine_adapter/engine_stream.py` — final-state merge semantics,
  pause-vs-cancel terminal status (intent), persisted RUNNING status
  (protection against regression).
- `engine_adapter/workflow.py` — shared intake-gate boundary (contract).
- `engine_adapter/drain.py` — parents-before-children insert order (ordering
  constraint), pruned-parent lineage fallback (invariant), single-transaction
  batching (trade-off).
- `runs_events.py` — SSE replay-then-tail structure, `_terminal` synthetic
  frame (contract), tick-skip heuristic with every-10th-tick safety net
  (invariant), PAUSED ending the stream without being a terminal run status
  (intent).
- `safety.py` — deliberately narrow block patterns (trade-off), intake
  redacting only under strict mode vs. final always flagging (intent),
  first-match-only diagnostics (contract).
- `elo.py` — engine-parity mirroring (contract), falsy-rating sort fallback
  (invariant).
- `citations.py`, `claims.py`, `claim_grounding.py` — four-state
  classification thresholds, lexical-similarity-is-not-verification (invariant),
  contradiction-dominates ordering (contract), publication-gate speculation
  policy (trade-off).

### Frontend
- `hooks/use_run_stream.ts` — event batching per macrotask (trade-off),
  `_terminal` sentinel consumption (contract), cancel-vs-flush cleanup
  semantics (invariant).
- `lib/theme.ts` — MD3 seed derivation and the no-hardcoded-tokens rule
  (contract), `brightnessSuffix` choice (intent).
- `workbench/hooks/*` (chat session state/handlers/start-run/helpers,
  global shortcuts, run history, toast, is-mobile, debounced callback) —
  verified compliant (handlers read in full; the rest audited for
  staleness/gaps); timeline-ordering epsilon offsets, deps-bag pattern
  rationale, and lifecycle sentinels are all documented.

## Stale comments fixed

Five (see "Files changed" above): two stale docstrings, two stale block
comments (one referencing removed behavior, one overclaiming a nullability
guarantee), and one malformed TODO (plus its cross-reference).

## Deliberately skipped under the refactor-not-comment rule

- `app/app/elo.py` `_first()` already documents why it exists (lizard
  complexity accounting); no additional comment needed and inlining it would
  be a refactor.
- `engine/src/co_scientist/nodes/ranking.py`'s long re-export import block
  (a module-split compatibility seam) is covered by the repo-wide convention
  recorded in project memory (splits keep module namespaces for monkeypatch
  seams); annotating every alias would be noise.
- No other candidate sites were found where the honest options were
  "refactor or stay silent."

## Verification

All commands run from the worktree root
(branch `docs/google-style-comments`).

| Check | Result |
|---|---|
| `make lint` | PASS ("All checks passed!" for engine, app, frontend/gts) |
| `make test-all` | PASS — engine 961 passed; app 231 passed, 1 warning |
| `cd engine && ../.venv/bin/python -m mypy .` | PASS — "Success: no issues found in 197 source files" |
| `cd engine && ../.venv/bin/python -m pytest -q` | PASS — 961 passed |
| `cd app && ../.venv/bin/python -m mypy app/` | PASS — "Success: no issues found in 43 source files" |
| `cd app && ../.venv/bin/python -m pytest -q` | PASS — 231 passed, 1 warning |
| `cd app/frontend && bun run lint` | PASS — gts lint clean |
| `cd app/frontend && bun run test` | PASS — 39 files, 254 tests passed |
| `cd app/frontend && bun run build` | PASS — tsc + vite build succeeded |
| `git diff` sanity | PASS — diff vs. `main` is comment/docstring lines only (4 files; every hunk is inside a comment or docstring) |

## Unresolved blockers

None.
