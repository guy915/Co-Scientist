# Optimization findings

The audit record for `docs/OPTIMIZATION.md`. Each finding names its evidence,
its impact (H/M/L), effort (S/M/L) and risk (low/med/high), and is ranked by
impact for effort and risk within its area. "Unmeasured" marks an estimate.
Folder ownership and timing follow `docs/CAMPAIGNS.md`: a finding in a folder
waits for that folder's cuts.

**Status:** audit done 6 October 2026 (backend, frontend, infrastructure, CI,
launch readiness). Fixes are listed under Progress; findings judged not worth
their risk are at the end with the reason.

## Order of work

1. CI speed (C1–C4), first, because every campaign waits on CI.
2. Launch-readiness files (L1–L4), new files only.
3. Infrastructure quick wins in files this campaign owns (I3–I6).
4. Backend and frontend fixes, folder by folder after their cuts.
5. Model lane, after the engine cuts merge.

## Progress

| Finding | PR | Result |
|---|---|---|
| C1–C3 | #247 | CI wall 5:51 → 3:49 |
| C4 | #279 | e2e as three parallel jobs; CI wall 3:40 → 2:54 |
| L3, L4 | #244 | `SECURITY.md`, `CONTRIBUTING.md`, code of conduct, issue forms, README quick start |
| L5 | #289 | Unlicensed Google Sans Text files removed; OFL Google Sans serves body text |
| L9 | #290 | Broken MCP README link and stale default-model comments fixed |
| L10 | — | Gone: the cuts removed the results file |
| L2 | — | Gone: the cuts removed the log-report email setting |
| I7 | — | Gone: the cuts made JSON the only log format |
| I2 | #265, #286, #287 | Monitoring guide; API and frontend error tracking, off without a DSN |
| I3, I6, I12 | #268 | API image rebuild after a source edit 18 s → 8 s; graceful shutdown; unbuffered logs |
| I4 | #254 | MCP image −374 MB |
| I5 | #255 | Vercel immutable asset cache and security headers |
| B1, B3 | #273 | Run delete 1133 → 25 ms |
| B2 | #278 | `GET /api/runs` 187 → 20 ms at 3,000 runs |
| B4 | #292 | Idle claim write transactions 145/s → 0; write p99 24 → 9 ms while idle |
| B6 | #296 | Trivial-request latency under 8 readers p50 35 → 5 ms; with a held write lock p99 250 → 7 ms |
| B5 | #284 | Checkpoint guard 0.91 → 0.004 ms per commit |
| B7 | #280 | Upload loop stall 350 → 24 ms |
| B8 | #285 | Run detail 2.19 → 0.81 ms (finished runs) |
| B9 | #293 | Keepalive every 15 s; stream polling off the event loop |
| B10 | #288 | Report 185 → 19 KB on the wire |
| B13 | #291 | Status polls 381 → 0 ms after the first |
| F2 | #303 | Entry script 80.8 → 63.4 KB gzip; throttled LCP 4.32 → 3.94 s |
| F3 | #313, #315 | Keystroke to frame at 4× CPU: home page p50 66–76 → 48–51 ms; 60-turn chat 276–293 → 27–28 ms |
| F1, F4 | #274 | Markdown chunk 103 → 70 KB gzip; stale-chunk reload |
| F5 | #297 | API refusals shown as their message, not `409 {"detail":…}` |
| F6 | #294 | Closed mobile drawer out of the tab order; one `main` landmark |
| F8 | #298 | Re-download after an app-only deploy 161 → 79 KB gzip |
| F10 | #311 | Light-mode muted text 4.10:1 → at least 4.5:1 on every surface it sits on |
| F11 | #312 | Keyboard focus stops without a visible ring 10 → 3 (two textareas with a caret, one iframe) |
| M1 | #243 | Benchmark retrieval enabled |
| M10 | #302 | Searches against an unregistered MCP tool fail once: 135 wasted calls and about 118 s of backoff per Express run → 0 |

## CI and development

Measured on main run [37534456734](https://github.com/guy915/Co-Scientist/actions/runs/37534456734)
(6 min 14 s wall) and locally on 4 cores.

| # | Finding | Evidence | Impact | Effort | Risk |
|---|---|---|---|---|---|
| C1 | App tests are one serial job on the critical path | Job 5 min 41 s: 31 s setup, 5 min 05 s pytest. Locally 873 tests: serial 369 s; `pytest-xdist` `-n 2` 197 s, `-n 4` 158 s, `-n 8` 133 s, all passing. Two notification tests take 28 s each | H | S | low |
| C2 | Backend setup costs about 30 s per job | `setup-backend` pip installs take 31–32 s in typecheck, app tests and evaluations; engine jobs 30 s; `make setup` 37–64 s | M | S | low |
| C3 | Root config repeats typecheck | `root-config` runs `make typecheck` (1 min 43 s) after the `typecheck` job ran the same three mypy commands (2 min 23 s) | M (runner time) | S | low |
| C4 | e2e is the next critical path | 4 min 38 s: `make setup` 64 s, Chromium 24 s, suite 2 min 23 s, production suite 28 s | M | M | low |
| C5 | mypy has no cache | `typecheck` spends 1 min 47 s in mypy from cold every run | L | S | low |
| C6 | Docker builds have no layer cache | `docker-build` rebuilds from scratch (2 min) | L | S | low |

## Backend (`app/app`)

From a read-only audit against a synthetic SQLite store (300 runs, 12k
hypotheses, 360k events, 120k tasks) built with the real schema. Absolute
times are relative; the scaling is structural.

| # | Finding | Evidence | Impact | Effort | Risk |
|---|---|---|---|---|---|
| B1 | Unindexed cascade foreign keys | `proximity_edges.source_hypothesis_id`, `.target_hypothesis_id`, `citations.evidence_id` have no index. `DELETE FROM runs` 1775 ms → 32 ms with indexes; hypotheses 749 → 9 ms; evidence 897 → 3 ms. Holds the writer lock in delete, replay, finalize and retention paths | H | S | low |
| B2 | `GET /api/runs` scales with the whole database | `store/runs_views.py:268-292` materializes MAX(elo) over every hypothesis; `_latest_stage_by_run` windows all events; `_runs_payload` calls `task_progress` per run. 69 ms through ASGI; rewritten SQL 1.4 ms and 0.22 ms with identical output | H | S | low |
| B3 | Missing composite indexes | `runs(client_id, created_at)`: 15 ms → 0.02 ms. `scientific_tasks(run_id, status, task_type)`: `cohort_poll` 14.2 → 0.62 ms | H | S | low |
| B4 | Idle workers take the write lock every 50 ms | `cohort_poll` ignores dependencies, so `claim_task` opens `BEGIN IMMEDIATE` for unclaimable tasks: 147 attempts/s, 0.46 core per run; ordinary write p99 1.8 → 11.2 ms | H | M | med (leases, idempotency, "never write on a poll tick") |
| B5 | Checkpoint commits parse and serialize under the lock | `engine_tasks/support.py:207,439,510` load the full checkpoint for its `seq`; `json.dumps` runs inside the transaction. About 6 ms per MB of state per commit | M | S | low |
| B6 | Blocking SQLite on the event loop | Most handlers are `async def` calling sync store code; ownership middleware and handlers each open 2–3 connections; Q&A context gathering runs on the loop | H (tail latency) | M | low-med (ownership 404 behavior) |
| B7 | PDF and OCR extraction on the event loop | `document_ingest.extract_upload` runs pypdf and per-figure tesseract (60 s timeout each) synchronously | H (p99, rare) | S | low |
| B8 | Run detail parses the checkpoint on every poll | `runs/crud.py:690-712` loads the full checkpoint for two counts | M | S-M | low-med |
| B9 | SSE replays from zero, ends silently, no keepalive | `runs/events.py:84` stops after about 83 min with no frame; payloads decoded and re-encoded | M | S-M | low |
| B10 | No response compression; unused payload fields | No GZip middleware; report 105 KB → 19 KB gzipped; `markdown_text`, `passage_text`, debate transcripts sent but unread | M | S (gzip) / M (fields) | low / med (API shape) |
| B11 | Cold start dominated by litellm | `import app.main` 4.7 s, `import litellm` about 3 s; `LITELLM_LOCAL_MODEL_COST_MAP` unset saves about 0.7 s and a boot-time network fetch | M | S | low-med (price/capability lookups) |
| B12 | One write transaction per log record | `_StoreWriteHandler.emit` commits each record (2.6 ms), including access lines | L-M | S-M | low |
| B13 | `/status` probe cache has no single flight | First caller after the 30 s TTL waits up to 3 s | L-M | S | low |
| B14 | Connection per call, no mmap | 0.67 ms per open on the real schema; mmap 256 MB −21% on reads | L-M | M | med (snapshot pinning) |
| B15 | Interview list parses every run's config | `store/interviews.py:96-113` | L-M | S-M | low-med |
| B16 | Retention is never scheduled | `retention.sweep_all` only runs by hand | M (over time) | S | med (deletes data; owner confirms) |
| B17 | Per-task full state restore | Each fan-out task restores the whole checkpoint and builds a generator (37 ms). Possible memory-peak source; instrument first | ? | M-L | high |
| B18 | `BaseHTTPMiddleware` on every request | `main.py:302` | L | S-M | low-med |

## Frontend (`app/frontend`)

From a production build (Vite, 627 modules) with sourcemap attribution and
stubbed-package counterfactual builds. JS total 968 KB raw, 299 KB gzip.

| # | Finding | Evidence | Impact | Effort | Risk |
|---|---|---|---|---|---|
| F1 | highlight.js loads about 37 languages | `markdown_message_renderer.tsx:10,16`; stubbing it cut the markdown chunk 103 → 49 KB gzip; this chunk loads with the first chat message | H | S | low |
| F2 | Runtime Material color utilities | `theme_context.tsx` computes the theme at load; 18 KB gzip of the 165 KB main chunk | H | M | med (theme parity) |
| F3 | Typing re-renders and re-parses the whole timeline | Composer `input` in session state; unmemoized `buildTimelineItems`, bubbles and `splitMarkdownIntoBlocks`. Cost grows with transcript length (unmeasured) | H | S-M | low-med |
| F4 | No recovery from stale chunks after a deploy | No `vite:preloadError` handler; the top error boundary replaces the app | M | S | low |
| F5 | Raw backend text as user errors | `api/runs.ts:540-553` shows `404 {"detail":…}`; error boundary shows stacks | M | S-M | low |
| F6 | Closed mobile drawer stays focusable; nested `<main>` | `shell_surface.css:1026-1040`; `layout.tsx:189` plus page mains | M | S | low |
| F7 | Cold-load waterfall | No modulepreload or font preload; hero `helix.webp` 134 KB; landing chunk lazy behind the main chunk | M | M | low |
| F8 | No vendor chunk; eager dialogs | react, react-dom, router (252 KB raw) re-downloaded every deploy; settings and run-spec code eager | M | S-M | low |
| F9 | Landing CSS ships everywhere | One 123 KB render-blocking sheet | L-M | S | low-med |
| F10 | Low-contrast text tokens | `--cosci-muted` on panel 4.10:1; accent 3.72:1 | M | S | low |
| F11 | Weak focus indicators | Composer buttons and textarea `outline-none` | M | S | low |
| F12 | Polling and streaming costs | 10 s run-list poll and 60 s status poll ignore hidden tabs; stream replays from zero | M | M | med — shrink lever 9 |
| F13 | Idea list rows not memoized | `ideas_tab.tsx:220,248` | L-M | S | low |
| F14 | Pre-hydration shell and meta colors | `index.html` skeleton paints the landing for every URL | L | S | low |

## Infrastructure

From the Dockerfiles, `vercel.json` and Railway documentation. Image sizes are
unmeasured.

| # | Finding | Evidence | Impact | Effort | Risk | Owner action |
|---|---|---|---|---|---|---|
| I1 | ~~Every push redeploys api and mcp~~ | Not reproduced: Railway marked the api and mcp deployments for docs- and workflow-only merges (#241, #242, #243) `SKIPPED`, so watch paths already exist | — | — | — | — |
| I2 | No error tracking or uptime check | No Sentry/GlitchTip/uptime config; `/health` returns 200 when degraded | H | M | low | Accounts, DSNs, monitors |
| I3 | `Dockerfile.api` layer order | Skills venv, `chown -R` and smoke test rebuild after any source change | M | S | low-med (non-root image path) | — |
| I4 | `build-essential` in the mcp image | `Dockerfile.mcp:12`, after the only wheel install, so it cannot help | M | S | low | — |
| I5 | No cache or security headers on Vercel | `vercel.json` has no `headers` | M | S (CSP M) | low (CSP report-only first) | — |
| I6 | No graceful shutdown | uvicorn without `--timeout-graceful-shutdown`; Railway draining 0 s | M | S | low | `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` |
| I7 | Text logs in production | `log_format` defaults to text (the cuts make JSON the only format) | M | S | low | — (after the cut) |
| I8 | litellm cost-map fetch at boot | See B11 | M | S | low-med | — |
| I9 | Build context and CI image cache | `.dockerignore` lets tests and frontend through; see C6 | L | S | low | — |
| I10 | tesseract recommends | `Dockerfile.api:13-14` | L | S | low-med (OCR must keep working) | — |
| I11 | Heavy transitive dependencies | `watchfiles` from `uvicorn[standard]`; hf-hub, tokenizers, grpcio | L-M | M | med-high (lock regeneration) | — |
| I12 | Memory limit and unbuffered output | No `PYTHONUNBUFFERED` in `Dockerfile.api` | L | S | low | Railway memory cap |
| I13 | Healthcheck settings undocumented | Railway healthcheck path and timeout not recorded | L-M | S | none | Read the dashboard |

## Launch readiness

Tracked files only; git history is out of scope (it will be reset).

| # | Finding | Evidence | Impact | Effort | Risk |
|---|---|---|---|---|---|
| L1 | No secrets in the tree | Regex scan of `git ls-files` for provider keys, tokens, PEM, JWT, credentialed URLs; only test placeholders found. Only `.env.example` files are tracked, all empty | — | — | — |
| L2 | Personal email as a default | `app/app/config.py:145` defaults `log_report_email` to a personal address; self-hosters would send diagnostics to it. The log-report email is cut by `PROD-CUTS.md` | H | S | low |
| L3 | Missing `SECURITY.md`, `CONTRIBUTING.md`, code of conduct, issue templates, CODEOWNERS | `git ls-files` | H | S | none |
| L4 | README gaps for a newcomer | No clone step, platform support, Bun pin install hint, or warning that `make start` kills processes on its ports | M | S | none |
| L5 | Font licensing | `app/frontend/src/assets/fonts/google-sans-text-*.woff2` have no provenance or NOTICE entry | H | S-M | med (visual change) |
| L6 | Media provenance | Landing webp images, social card, docs assets not recorded | M | S | none |
| L7 | Links that break after the history reset | Pinned-commit links in `AGENTS.md`, `docs/README.md`, `docs/LAUNCH.md`, `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, `evaluations/README.md` and code comments | H (at publication) | M | low |
| L8 | Unclaimed PyPI name | `app/pyproject.toml` depends on unpublished `co-scientist-engine` (dependency confusion once public) | M | S | low |
| L9 | Stale docs | Broken `engine/mcp_server/README.md:61` link; stale paths in `app/README.md`; `.env.example` comments still name Nemotron as default | L-M | S | none |
| L10 | Local path in a results file | `evaluations/results/baseline-2026-07-10.json:9` | L | S | none |
| L11 | Licenses compatible | LICENSE/NOTICE copies byte-identical; no GPL/AGPL/SSPL in the Python locks (178 pins) or `bun.lock` (569 packages); MPL-2.0 only as dependencies | — | — | — |

## Model usage

Two Express baselines on `main` at `df08134` (Ling 3.1 Flash default):
[37532257388](https://github.com/guy915/Co-Scientist/actions/runs/37532257388) and
[37532261948](https://github.com/guy915/Co-Scientist/actions/runs/37532261948).

| | Express 1 | Express 2 |
|---|---|---|
| Wall time | 39.6 min | 44.2 min |
| Physical calls | 95 | 98 |
| Prompt / completion tokens | 377k / 438k | 411k / 498k |
| Reasoning share of completion | 72% | 70% |
| Cached prompt tokens | 5.1k (1.4%) | 5.5k (1.3%) |
| Calls served by Ling | 39 (41%) | 35 (36%) |
| Retries / errors | 1 / 0 | 1 / 0 |
| Claims supported | 0 of 49 | 0 of 40 |

| # | Finding | Evidence | Impact | Effort | Risk |
|---|---|---|---|---|---|
| M1 | The benchmark ran without literature retrieval | Free runs execute in campaign mode, which requires `COSCIENTIST_CAMPAIGN_MCP_URL` and a shared secret; the workflow set neither. Log: "campaign MCP requires one explicitly qualified endpoint … generating hypotheses from model latent knowledge only". No literature, reflection or claim-verifier calls; 49/49 claims unsupported (rate 1.0), so the metric could not move. Fixed in #243; both Express baselines are re-run | H (benchmark validity) | S | none |
| M2 | About 60% of calls are served by the Nemotron fallbacks, not Ling | The same call type lands on either model across runs (deep_verification: 0/7 on Ling in run 1, 4/8 in run 2), and parallel fan-outs fall back most (comprehensive_reflection 1/31 on Ling). Ling has one free endpoint (Novita); the pattern fits rate limiting or errors there, not a parameter mismatch. Per-call reasoning differs by model (Ling medium 5–9k, Nemotron 1–4k), so the mix adds run-to-run variance. Measure the fallback reason before changing anything; the model choice itself is the owner's | H (variance, quality) | M | med |
| M3 | Reasoning dominates output | 72% of completion tokens are reasoning; Ling medium spends 5.6k (review), 6.1k (ranking), 9.4k (evolve) and 13.7k (overview) reasoning tokens per call | H (time) | S-M | med (answer-changing) |
| M4 | Almost no prompt caching | 5.1k of 377k prompt tokens cached (1.4%), all on ranking | M | M | low |
| M5 | Ling is slow per call | Ranking: Ling 61 s/call (6.4k completion), Nemotron Super 13 s/call (1.4k), Ultra 87 s/call; per-token rate about 105 tok/s on both Ling and Super, so time follows tokens | M | — | — |
| M6 | Ling's output cap is 32,768 tokens | Endpoint `max_completion_tokens` 32,768; the largest engine budget is 24k (`BUDGET_ESCALATION_MAX_TOKENS`), so escalation stays within it | — | — | — |
| M10 | Searches retry a tool the server never registered | Without a web-search key the MCP server has no `search_web`; the engine retried it as transient, four attempts with backoff per search (Express r2: 135 wasted calls). Production registers it | M (benchmark, self-hosting) | S | none |
| M11 | Most fallbacks land on the slowest route | Ling's chain tries Nemotron Ultra before Super. Express r2 ([37558737903](https://github.com/guy915/Co-Scientist/actions/runs/37558737903)): Ultra served 71 of 150 calls at 104 s each (37 tok/s), 63% of all call time; Super 41 s (120 tok/s). Batch 1 tried Super first and was rejected (below) | H (time) | S | med (answer-changing; benchmarked) |
| M12 | Ling ignores the minimal-reasoning cap | Claim checks request reasoning off; Ling gets a 2,048-token cap but reasoned 15.4k tokens per claim-gate call (154 s), exhausted its budget and retried 12 times, and 5 of 63 claims fell back to the lexical assessor. Super honors the cap (2.0k). Batches 2 and 3 (the low effort tier, then a 30k budget) were rejected (below) | M (time, quality) | S | med (answer-changing; benchmarked) |
| M14 | OpenAlex refuses searches in long benchmarks | OpenAlex's keyless budget is shared per IP; GitHub runners exhausted it during the Standard baseline (16 refused searches). Production showed none. A free key as a repository secret is an owner action (on the board) | M (benchmark validity) | S | none |

With retrieval on (#243), Express
[37540122229](https://github.com/guy915/Co-Scientist/actions/runs/37540122229)
at `bb27400`: 49.5 min, 86 physical calls, 568k prompt / 359k completion
tokens (64% reasoning), 13.0k cached (2.3%), Ling served 19 of 86 calls (22%),
28 claims with 10 supported (unsupported rate 0.64), unverified idea rate
0.33. Literature review, reflection, claim gate and claim grounding calls now
appear. Ling retried and then fell back on comprehensive reflection, claim
gate, directions and ranking, which supports M2.

Starting evidence re-check (measured on Nemotron): the tool-loop and
reasoning-exhaustion findings need a run with retrieval on (M1) before they
can be confirmed on Ling; each run had one retry. Caching remains near
zero (M4).

M2–M6 describe the routes rather than defects with a fix of their own: M2's
fallback pattern is measured as M11, M3's reasoning share is what the batches
change, M4 is answered by M7 below, and M5 and M6 are properties of the free
endpoint.

Baselines at `a82eed8` with every fan-out stage timed: Express r2
([37558737903](https://github.com/guy915/Co-Scientist/actions/runs/37558737903))
and Standard
([37558735897](https://github.com/guy915/Co-Scientist/actions/runs/37558735897):
157 min, 283 calls, 19 ideas, unsupported claim rate 0.84, unverified idea
rate 0.67). Model batches, each one Express run against r2:

| | r2 | Batch 1: Super before Ultra (M11) | Batch 2: Ling's low tier for claim checks (M12) | Batch 3: a 30k budget for claim checks (M12) |
|---|---|---|---|---|
| Run | [37558737903](https://github.com/guy915/Co-Scientist/actions/runs/37558737903) | [37566987457](https://github.com/guy915/Co-Scientist/actions/runs/37566987457) | [37572259558](https://github.com/guy915/Co-Scientist/actions/runs/37572259558) | [37598146898](https://github.com/guy915/Co-Scientist/actions/runs/37598146898) |
| Wall time | 92.3 min | 77.2 min | 135.1 min | 77.8 min |
| Unsupported claim rate | 0.76 | 0.97 | 0.76 | 1.00 |
| Unverified idea rate | 0.20 | 0.83 | 0.20 | 1.00 |
| Claim checks on the lexical fallback | 5 | 11 | 20 | 24 |

All three batches are rejected, and `main` keeps its configuration. Each trades
claim verification for speed, a quality loss far beyond what a speed gain may
cost:

- Batch 1 is 16% faster, but the unsupported claim rate rises outside the
  r1–r2 noise (0.64–0.76).
- Batch 2 is slower: Ling still reasoned 15.4k tokens per claim check at the
  low tier, and Super's rose from 2.0k to 11.2k.
- Batch 3 gives Ling the budget it ignores the cap for. Ling then wrote its
  reasoning into the answer, so 24 claim batches failed to parse, and none of
  62 claims was supported.

## Not worth the risk

| # | Change | Why not |
|---|---|---|
| M7 | Stable-first prompt order (ranking, review, evolution) for prefix caching | The routes are free, so cached tokens save no money, and the daily cap counts requests, not tokens. Wall time is generation-bound: 5–9k reasoning tokens per call at about 105 tok/s is 50 s or more, while prefill of a 3–4k-token prompt is under 1 s. Reordering prompt text can change answers |
| M8 | Compact JSON schemas and move the debate angle line | Same reason as M7: prefill-only savings on free routes, at the risk of changing answers |
| M9 | Stop echoing `reasoning_content` back for non-DeepSeek models | Prefill-only saving; some OpenRouter providers need reasoning continuity across tool calls, so dropping it risks breaking tool loops |
| B12 | Batch the persisted-log writes | Records are already written on a background `QueueListener` thread, off the request path; batching would rework that thread's drain and shutdown for a few milliseconds of writer time per second |
| I10 | `--no-install-recommends` for tesseract | `tesseract-ocr` has no Recommends of its own in Debian; only transitive font recommends could drop, and OCR must keep working |
| B11/I8 | `LITELLM_LOCAL_MODEL_COST_MAP=True` (0.9 s faster import, no boot fetch) | litellm's bundled map has 2,426 entries against 4,481 remote; six newer BYOK models (Gemini 3.x, GPT-6) lose `json_schema` support under it, changing their structured-output path |
| B14 | One connection per thread, mmap | 0.67 ms per open, two or three per request, now off the event loop (#296); a shared connection changes snapshot and transaction scope across the store |
| B15 | Resolve interview links in SQL | 4.1 → 0.33 ms at 200 runs, about 0.4 ms for a typical client with under 20 runs, and off the event loop since #296 |
| B18 | Replace the `@app.middleware` ownership check with pure ASGI | Its per-request overhead is a fraction of a millisecond, and its store lookup already runs off the loop (#296); a rewrite risks the ownership 404/403 paths |
| B16 | Schedule retention | It deletes researcher data; whether and when is the owner's decision (on the board) |
| B17 | Restore less state per fan-out task | High risk on the commit path, and its memory effect is unmeasured; instrument first |
| C5, C6 | mypy and Docker layer caches in CI | Not on the critical path: e2e shard 1 takes 2:28 of a 2:43 CI wall, typecheck 1:55 and Docker 1:43 run beside it |
| I9 | Trim the Docker build context | Every `COPY` is explicit; excluding tests and frontend sources would only shrink an 11 MB context upload by 3 MB |
| F13 | Memoize idea list rows | Runs hold a few dozen ideas at most and each row is cheap; lever 7 is restyling the file |
| F5 (stack) | Hide the error boundary's component stack | It is collapsed behind `<details>` and is what a researcher pastes into a bug report |
| F7 | Preload the body font and landing chunk | Throttled cold load (1.6 Mbps, 150 ms RTT, median of 5): preloading the 400 font moved FCP 3,736 → 3,828 ms and LCP 4,332 → 4,500 ms. On a bandwidth-bound link the font competes with the entry scripts, and LCP is text, so the hero image is not on the critical path |
| F14 | A URL-aware pre-hydration skeleton | A deep link shows a landing-shaped placeholder until React mounts; fixing it is a visual change in lever 7's area for a brief placeholder |
| I11 | Drop heavy transitive dependencies | `grpcio`, `tokenizers`, `huggingface-hub` and `hf-xet` are litellm's own requirements; only `watchfiles` (via `uvicorn[standard]`, used by `--reload`) could go: a few MB for a rewritten extras list and a regenerated hash-pinned lock |
| F9 | Split the landing stylesheet out of the entry CSS | After shrink #308 the whole sheet is 117 KB (22.5 KB gzip), of which the landing's own rules are 5.3 KB gzip. The home route, where most visits start, needs them anyway, so splitting adds a render-blocking request there to save 5 KB elsewhere; lever 7 keeps moving these rules to utilities |
| F12 | Pause polling in hidden tabs and resume streams mid-way | The campaigns leave frontend fetching and polling to shrink lever 9, which judged its rework not worth the risk (board #240) |
| M13 | Run proximity beside the research overview | The overview does not read proximity's output, but the workflow commits one node per checkpoint; running two nodes at once means concurrent checkpoint writers for one run, an invariant change in `docs/OPERATIONS.md`, to save about 4 minutes of an Express run |
| M15 | Count tool schemas and echoed reasoning in the tool-loop transcript budget | `transcript_tokens` counts message text and tool calls only, so an offline simulation sent 22% more than it counted (up to 64% if a route echoes reasoning). The 300k budget never binds: no loop reached it in the Express r2 or Standard job logs, whose largest call prompt was about 53k tokens. Counting more would only move when loops wrap up, which can change answers, for no measured gain |
