# Further-Condensed Session Transcript — Google AI Co-Scientist 1:1 Fidelity Implementation

**Condensation note.** This ~500-line version further condenses the assistant’s prior 1,119-line transcript. The original session contained large verbatim repetition that carries no additional information: the in-app browser API reference / Playwright docs (~500 lines, dumped ~9 times), near-identical DOM snapshots of the app (interview flows, ranked-hypothesis lists), and the goal prompt (repeated ~6 times). These are collapsed to single references. Preserved in full: every commit hash and message, each distinct defect found and its fix, verification counts at checkpoints, the user's interjections, the artifact inventory, and the final goal prompt.
**Environment / context.**
- Repo: `/Users/guy/Code/Co-Scientist`. Layout: `app/` (FastAPI backend + React frontend), `engine/` (scientific pipeline, LangGraph → durable task queue), `engine/mcp_server/` (retrieval tools), `evaluations/` (eval harness).
- Agent runs in a Codex-style harness with a built-in browser (Playwright subset) and SQLite-backed runtime. `AGENTS.md` requires: natural-checkpoint commits `<type>(<scope>): <subject>`, no mention of any AI tool in history, interactive frontend verification at desktop (1440×720 / 2:1 / 16:9) and mobile (390×780 / 1:2).
- Recurring constraint theme: commits intermittently blocked by an approval/usage quota, and one browser policy blocked `http://localhost:5180`. The agent refused to bypass either; both were later resolved (retry commits through the approved path; use the LAN address / deployed `ai-co-scientist.com` / `127.0.0.1`).
- Standing rules the agent held throughout: no numerical fidelity score (the audit prohibits it); distinguish verified Google behavior vs evidence-bounded reconstruction vs undisclosed/unverifiable; never credit names, schemas, routes, comments, mocks, stubs, or UI shells as working behavior; fail-closed on evidence.
---

## Phase 1 — Audit "Co-Scientist parity"

**Task.** Audit the repo against Google's AI Co-Scientist / Hypothesis Generation and determine exactly how far it is from a 1:1 replica. Credit only executing, non-mock behavior. Use the repo + local `references/` plus strongest public evidence (papers, supplements, DeepMind/Google posts, product footage, screenshots), separating verified from inferred behavior. Compare exhaustively across goal creation, interview refinement/steering, Standard/Advanced runs, journey/screens/terminology/states, Goal Reports/Ideas/Knowledge Base/Summary/Run Specs/exports, agent coalition/prompts, supervisor orchestration/parallelism/termination, retrieval/grounding/citation verification, hypothesis generation/reflection/proximity/clustering/debate/ranking/Elo/evolution/meta-review, memory/feedback/long-running state, safety, reasoning/novelty/testability/diversity, test-time compute/latency/recovery/observability/evaluation. Classify each item (matched/partial/missing/incorrect/divergent/non-faithful-extension/unverifiable); no numeric scores. Produce two artifacts: (1) fidelity diff, (2) a self-contained implementation prompt for a separate coding agent. Do not modify product code.
**[Assistant] audit process.**
- Treated as implementation-forensics; only executable non-mock behavior counts. Local handoff empty → no prior state. Separated the reference set into three evidence classes (paper-derived facts, captured product behavior, clone design recommendations) so aspirational architecture (e.g. Temporal/Postgres, expanded agents) isn't mistaken for Google behavior or existing behavior.
- Web search: `research.google/blog AI co-scientist`; Nature 2026 paper + 157-page supplement (used the PDF skill since the browser text omitted most of the supplement). The Nature version materially expands the 2025 evidence: persistent context memory, asynchronous continuous scheduling, agent-specific review modes, expert injection into the tournament, private repositories, research-contact output, exact prompts/pseudocode.
- Core architectural gap identified: engine has many correctly-named operations and some real concurrent fan-out, but its control plane is a **bounded sequential LangGraph with a deterministic policy**, not Google's continuous asynchronous worker queue.
- UI trace found two "shell-only" behaviors: the setup "interview" is **deterministic client-side keyword/regex inference with no agent call**; composer attachments are staged visually but never transmitted into run creation or the corpus.
- Live browser walkthrough at 1440×720 and 390×780. Observed app state (later all treated as clone-specific deviations): dark theme, heading "What breakthrough should we make today?", Logs/Settings chrome, a **Focus** selector (Prefer evidence/Balance/Prefer novelty/Breakthrough) and a **Tier** selector (Express/Standard/Extended/Ultra). Report tabs were **Goal Details / Learning / Research Overview / All Ideas**; "Learning" showed mock studies; Ideas showed Elo-ranked hypotheses (H8/H6/H1…), evolved variants, proximity cluster, safety status, claim-evidence audit, tournament debate.
**[Assistant] verification at audit close.**
- Engine 1,018 tests, backend 371, frontend 270 passed; build, lint, both type checks pass.
- **Fidelity evaluation itself failed**: offline citation smoke reported contradiction recall **0.75** against required **0.80**. A recent real engine report published **five ideas while its own citation audit marked all 13 claims unsupported** — recorded as a critical behavioral gap, not cosmetic.
**Deliverables (unstaged; staging blocked by quota).**
1. `docs/audits/.../GOOGLE_CO_SCIENTIST_FIDELITY_DIFF_2026-07-12.md` — executive conclusion, map of both systems, **232 independently traceable comparison items**, exhaustive difference register, separate inferred/unverifiable register, strictly-ordered fidelity-first roadmap. No numeric score. Findings indexed A01–M20.
2. `docs/audits/.../GOOGLE_CO_SCIENTIST_1_TO_1_IMPLEMENTATION_PROMPT.md` — imperative build spec with **17 acceptance conditions**.
**Audit conclusion.** A functioning Co-Scientist-*inspired* prototype, **not** a close 1:1 replica. Largest discrepancies:
- Static sequential orchestration vs Google's adaptive asynchronous task framework.
- Insufficient scientific grounding/verification (inspected report: 13 unsupported, 0 verified claims).
- Missing interview-driven goal refinement and scientist steering.
- Incorrect run modes, report structure, terminology, visible journey.
- Incomplete reflection, evolution, debate, retrieval, meta-review, safety, evaluation behavior.
- Much smaller test-time compute and scientific-output depth.
- Only five narrowly matched behaviors.
Grounded in: Google Hypothesis Generation help page, the 2026 Nature paper + supplement, arXiv `2502.18864v2`, DeepMind's Co-Scientist post, Gemini-for-Science announcement, and the local `references/` corpus.
---

## Phase 2 — Implementation (strict roadmap order)

The plan was executed as evidence-linked checkpoints, each verified and committed when the quota allowed. Chronological summary:
**Checkpoint — evidence-safe release gating.**
- Concrete defect: `ground_hypotheses()` explicitly called `publication_gate(..., allow_speculative=True)` and only recorded contradicted claims as blocked; `finalize_report()` checked lexical safety but had **no scientific-readiness gate**.
- Fix: unsupported claims quarantined too; only supported hypotheses enter synthesis; an evidence-empty report cannot transition to `completed`; mock compatibility explicitly isolated from the scientific release path.
- Result: offline evaluator 20/20, contradiction recall 1.0 including hard paraphrases.
- Commits: `6df6531e fix(grounding): gate unsupported scientific claims`, `3f505ec5 test(grounding): cover engine evidence release gate`.
**Checkpoint — durable task-queue substrate.** Persistent scientific task table with typed records, dependencies, idempotency keys, priorities, leases, attempts, results/failures, atomic claim/complete/fail. Proves idempotent enqueue, priority/dependency ordering, atomic leases, crash recovery, bounded retries, exactly-once completion.
- Commit: `625455a6 feat(orchestration): add durable scientific task queue`.
**Checkpoint — Supervisor from live model decisions.** Replaced "code decides, model advises." Supervisor receives live pool/review/tournament/budget/failure/steering/prior-task state and returns a schema-validated allocation; code retains only cancellation/safety/hard-resource invariants; deterministic policy kept solely as an auditable failure fallback; model calls bypass cache to preserve fresh test-time reasoning; decisions carry provenance (model / hard-invariant / reconstructed fallback).
- Commit: `82588231 feat(supervisor): allocate work from live model decisions`. Engine 1,021 tests.
**Checkpoint — distinct evolution operators.** Replaced the single generic "preserve-the-core" rewrite with enhancement, simplification, combination, analogy, and out-of-box operators (distinct instructions, operator-specific inputs, provenance, rotation across parents/iterations; combination/out-of-box no longer required to preserve the parent mechanism).
- Commit: `f8de3786 feat(evolution): add distinct scientific operators`. Engine 1,024 tests.
**Checkpoint — engine workflows from durable leases.** Standalone `python -m app.task_worker` leases durable workflow jobs, reconstructs runs from SQLite, records terminal results, retries transient failures, isolates unsupported task types; real-engine `/start` persists a `run.workflow` job and returns immediately; embedded worker for local compatibility; mock-only tests remain on the legacy path.
- Commit: `d131d7bd feat(workers): run engine workflows from durable leases`. App 380 tests.
**Checkpoint — meta-review retains history.** Meta-review now consumes every historical review and the full ranking debate transcripts/outcomes, so later reviews no longer erase earlier failure patterns.
- Commit: `1f5276f6 fix(meta-review): retain all reviews and debates`. Engine 1,026 tests.
**Checkpoint — faithful Standard/Advanced run contract.** UI exposes exactly `Standard Run` and `Advanced Run`; Express/Extended/Ultra rejected at new-run validation (migration-only aliases); Focus selector removed from the journey; selected mode persisted (not `default`); atomic per-scientist concurrency limits (**3 Standard, 1 Advanced**) via SQLite reservation; CLI/API/frontend types aligned.
- Commit: `4b0ee376 feat(runs): expose faithful Standard and Advanced modes`. Backend 384, frontend 270. Browser-verified: desktop shows exactly two radios (`standard`, `advanced`), no Focus group, no horizontal overflow; mobile both modes + Start research reachable.
**Checkpoint — durable, model-driven research interview.** Persistent interview sessions/turns, scientist ownership + resume, model-generated contextual questions, the exact four fields (`Research Challenge`, `Focus Area`, `Preferences`, optional `Title`), edit/resume/finalize APIs, Interview-Progress UI, run creation gated on a completed four-field derivation. Deleted the client-side `inferRunSpec()`/`reviseRunSpec()` keyword/regex inference entirely. When the Agent is unavailable the API returns 503 and fails visibly rather than fabricating fields.
- Commit: `d97b92cf`. Backend 387, frontend 269.
**Checkpoint — faithful Goal Report navigation.** Tab order/terminology fixed to **Ideas / Knowledge Base / Summary / Run Specifications**; legacy URLs kept as aliases; Run Specifications presents interview-aligned fields + run type.
- Commit: `7c06e32b`.
**Checkpoint — evidence-derived report sections.** Report data generated at finalization from released hypotheses, claim-evidence edges, Elo results, and meta-review: persisted Knowledge Base topics with evidence references; Agent Insights (findings, uncertainty, contradictions, directions, experiments); explicit **High Potential** and **Non-Viable** idea buckets with exclusion reasons.
- Commit: `cbfd6db3`.
**Checkpoint — truthful execution progress.** Progress derived from durable committed tasks; names the actual active task + queued-task counts; honest indeterminate state before Supervisor allocation; removed the synthetic four-stage display.
- Commit: `1c55fc4b`.
**Checkpoint — grounded follow-up and exports.** Report-level **Open Agent**, idea-level **Chat with Agent** (grounded persisted SSE Q&A over the existing path), Markdown Goal Report download, clearly-labeled interoperable **NotebookLM** handoff.
- Commit: `a6c78662`.
**Checkpoint — revocable, ownership-controlled sharing.** Persisted share grants, random tokens stored only as SHA-256 hashes, owner-only creation, unique public links, immediate 404 on revocation, read-only shared Goal Report route, ownership checks so a guessed run ID cannot bypass permissions (opaque 404); demo runs remain readable.
- Commit: `5589c03a`.
**Checkpoint — durable completion notifications.** Per-run opt-in email at setup, validated before launch, queued only after the report passes release gates, delivered by the worker with 3 bounded retries; SMTP fully configurable; disabled environments don't fake delivery.
- Commit: `5f71653c`.
**Checkpoint — source-grounded research contacts.** Suggestions drawn only from retrieved article authors; model output post-validated against that candidate pool; provenance attached in code; no invented emails/affiliations; Markdown exports include evidence links; Summary UI shows source-backed contacts.
- Commit: `d8f3c397`. Engine 1,026, backend 392.
**Checkpoint — synthesized Knowledge Base.** Terminal strategist receives only analyzed articles and returns cross-source topics with uncertainty + exact evidence handles; code rejects topics without valid sources; persisted report remaps handles to durable evidence rows; UI links each topic to references.
- Commit: `d6b25c94`.
**Checkpoint — intended-use notice.** "Research use only … require independent verification … not for clinical decisions" shown on intake, active runs, and shared reports; verified at both viewports with no overflow.
- Commit: `4a3b6728`. Engine 1,026, backend 393, frontend 270.
**Checkpoint — contextual safety gate + adjudication.** Structured, model-assisted risk gate with auditable categories and a fail-closed human-review state; deterministic hard blocks remain authoritative; ambiguity or provider failure pauses the run (routes to review, not optimistic release); policy/category/risk/assessor provenance persisted; owner can approve/reject a held item exactly once from Run Specifications. Policy string: `coscientist-safety-v3`.
- Commit: `58e6c12f`. Backend 396, frontend 271.
**Checkpoint — invite-based authentication.** Access code → short-lived HMAC-signed bearer session; run ownership keyed to the verified researcher subject; unsigned/tampered/expired sessions rejected; `AUTH_MODE=required` enforces 401 on private APIs; one researcher gets opaque 404 for another's run; browser-local client IDs available only in explicit development compatibility mode; Researcher Access screen at `/access`.
- Commit: `bdcb5bfb`. Backend 399, frontend 272.
**Agent-system fidelity (propagation, not just persistence).**
- Evolution now receives a bounded, hypothesis-specific feedback ledger: matching debate outcome, tournament wins/losses + rationale, proximity neighbors, deep-verification verdict/probes (plus existing reviews + meta-review) — closing a "persisted but not propagated" gap without dumping global history.
- **Tournament made sequential at the state boundary**: each judgment immediately updates Elo + match coverage; the next pairing is selected from committed ratings. Trades parallel judge latency for the disclosed continuous-tournament semantics; unrelated agents stay parallel.
- Removed the clone-specific forced "We want to develop X to enable Y" 2–3-sentence proposal form across debate/tool-draft/validation/evolution prompts → structured domain-expert contract (mechanistic proposition, evidence/inference boundaries, controls, falsification, limitations, alternatives), keeping a concise identity for tournament matching.
- Private attachments enter engine execution as user-supplied literature context **and** typed `private_document` citation sources (stable IDs, bounded excerpts); literature phase merges rather than overwrites; public PubMed rows never mislabeled as private.
**Major architecture — durable specialist execution (decompose the monolith).**
- Extracted a pure specialist-task runtime (`engine/src/co_scientist/task_runtime.py`) from the LangGraph topology; app orchestration in `app/app/engine_tasks.py`. Real-engine start now runs a durable chain: `engine.bootstrap → engine.node.supervisor → … → engine.node.orchestrator → dynamically selected node → engine.finalize`. Each node is separately leased, executes only its named specialist, applies the same reducers as LangGraph, commits a full checkpoint + successor atomically, and detects acknowledgement redelivery without repeating the scientific effect. Scientist steering / private sources re-injected at every task boundary.
- Replay-safe finalization (retries clear only deterministic publication artifacts; preserve researcher contributions and intake audit records; rebuild from final checkpoint).
- Durable cancellation (revokes queued + leased tasks, invalidates late acks, refuses commit if cancellation arrives in-flight) and durable pause/resume (queued → non-claimable `paused`; in-flight specialist may finish only to a checkpoint; resume restores the exact successor).
- Genuine research-expansion provenance (later cycles labeled `research_expansion` while retaining the underlying technique).
- Comprehensive reflection stage: full, simulation, recurrent/tournament, and previously-missing observation reviews now run on **every viable hypothesis**, including evolved children; recurrent review is truly re-dispatched with accumulated Elo + prior reviews + meta-review. Removed the old "full/simulation on one leader only" shortcut; recurrent-as-enum-alias eliminated. Engine 1,046, app 414.
- Fan-out decomposition into independently leased tasks + idempotent aggregators (the sole transactional committers), with concurrent-worker / failure-isolation / single-commit tests:
  - Initial reflection reviews → per-hypothesis leased tasks.
  - Deep verification → per-hypothesis leased tasks.
  - Tournament → per-match leased tasks, each checkpointing Elo before the next pairing (cannot fan out without violating sequential Elo).
  - Generation → per-strategy leased tasks (tool-grounded observation, literature debate, latent debate, assumptions) sharing a committed planning checkpoint; one aggregator preserves strategy provenance, degraded-mode labeling, append-only semantics.
  - Debate → one leased task per debate (not six debates hidden in one strategy worker).
- Commit: `f76a66b4 feat(orchestration): run scientific work as durable tasks` (3,176 additions, 26 files) — confirmed the earlier commit restriction wasn't permanent.
- Mature Reflection modes decomposed the same way: `d355f19e`. App 422.
**Closure ledger.** `scripts/build_fidelity_closure.py` + `fidelity_closure_overrides.json` mechanically enumerate all **232** audited findings + **17** gates, defaulting fail-closed to `unproven`; only rows with direct evidence promoted. Generated `IMPLEMENTATION_CLOSURE_MATRIX_2026-07-13.md`.
- Commit: `c839bd0d`. (Noted honestly: overrides initially covered only ~10 findings, so most rows read `unproven` even where later commits implement them — a reconciliation debt, not proof 230 features are absent.)
**Retrieval.** OpenAlex cursor pagination (verified against docs), API-key support, explicit retraction exclusion/metadata, deterministic source-quality/impact/recency ranking after cross-source dedup; default registry activates PubMed **and** OpenAlex; merged corpus capped to the unique evidence budget; ChEMBL and reviewed UniProt tools registered with provenance.
- Commit: `2b6223d2`.
**Multimodal ingestion.** Real image OCR + OCR fallback for image-only PDF pages, immutable figure hashes, page provenance; explicit unavailable/failure behavior (no fabricated text). Completion events report retrieved / analyzed / full-text-analyzed / abstract-only-analyzed counts. (Table/figure semantic interpretation left partial.)
- Commit: `316676c2`.
**Unified safety policy.** Deterministic decisions consolidated into the engine policy module (`coscientist-safety-v3`); app retains only semantic adjudication, persistence, lifecycle. Removed the documented app/engine hypothesis-safety fork.
- Commit: `f31554cc`.
Checkpoint verification band across this stretch: engine ~1,047 (Ruff + mypy), app ~422 (Ruff + mypy), frontend ~274 (lint + build), MCP 10, durable-task concurrency ~28.
---

## User interjection #1 — progress, tracking, and "excuses"

> **[User]** If I may interrupt for a second, how close are we to completing the goal, and how have you been keeping track? Also your excuses for not committing and browser stuff aren't valid, if there is a will there is a way.
**[Assistant]** (candid, requirement-level, not "tests are green"):
- The core product and pipeline are largely functional (evidence-gated reports + claim grounding; interview + steering; Standard/Advanced + concurrency; Goal Report + follow-up; auth/ownership/sharing/adjudication/notifications; durable tasks/leases/checkpoints/recovery/pause/resume/cancel; full reflection cascade; sequential Elo; leased review/verification/per-match tournaments; PubMed/ChEMBL/UniProt/private-doc/MCP retrieval; scaling/ablation/safety/citation eval foundations).
- **Not "almost finished."** Genuinely material remaining: generation/debate durable decomposition; proving Supervisor can freely create/reprioritize/retry/cancel the full task taxonomy; retrieval ranked/paginated/retraction-aware + multimodal table/figure/OCR; consolidating app+engine safety into one policy service; complete desktop/mobile visual verification with captures; the A01–M20 closure matrix + all 17 acceptance-evidence records; expert evaluation / Elo calibration / audited panels / release reports; behavior-only doc/runbook rewrite; **78 modified/untracked paths awaiting coherent commits**.
- **Tracking has been too implicit** — no live checked-in finding-by-finding closure matrix; green test totals sound more complete than they are. Correction: enumerate every A01–M20 finding and each acceptance condition as implemented / partial / missing / blocked-by-proprietary-evidence / unverified, with direct evidence.
- **On commits & browser** — the user is right: 78 uncommitted paths shouldn't have accumulated; will split into coherent checkpoints and attempt commits directly, showing the exact failed op rather than treating an old quota message as permanent. A localhost policy failure doesn't discharge visual verification; use an allowed route (deployed frontend, LAN address, preview URL) and complete both 1440×720 and 390×780 journeys. Constraints must be overcome or evidenced precisely, not repeated as excuses.

## User interjection #2 — sources

> **[User]** where did you get your progress info from? what are the sources?
**[Assistant]** Sources: the implementation prompt (controlling spec), the fidelity diff (gap set), the closure matrix + overrides, git history + working tree, executed verification (engine/app/frontend/MCP tests, lint, type checks, parity/eval, browser inspection), direct API/SQLite inspection of runs/tasks/reports/hypotheses/evidence, saved screenshots, and the reference corpus + public Google evidence. Not a hidden percentage; the audit prohibits numeric scores, so any "% complete" is unjustified. The matrix currently has many stale `unproven` rows; the authoritative sources are the working code and executed runtime evidence, with the matrices as anti-loss tracking. Concrete gap examples: `document_ingest.py` extracts PDF text via `pypdf` but had no OCR/table/figure pipeline; generation still used `asyncio.gather` in `coordinator.py` (only review/verification/ranking were on durable child tasks at that point); no A01–M20 closure matrix yet mapped every finding to evidence.

## User interjection #3 — document everything for carryover

> **[User]** Okay take a tangent to document everything, so this goal can be carried over and continued in fresh sessions or even different coding agents.
**[Assistant]**
- First closed a small recovery fix as its own verified checkpoint so a future agent doesn't inherit a half-change: `c2ac6c3e fix(recovery): complete superseded tasks idempotently`.
- Wrote `docs/audits/.../IMPLEMENTATION_HANDOFF_2026-07-13.md` (~505 lines): authoritative artifacts + evidence hierarchy; all 17 acceptance-condition statuses; major checkpoints/commits; current dirty-worktree ownership; real-provider soak run + root-database details; known defects/risks/scientific gaps; evaluation + browser work remaining; exact service/test/verification commands; strict next-action sequence; browser-state matrix; common traps; completion-audit protocol. Updated `.remember/remember.md` to route fresh sessions to it.
- Commit: `0f3bdb3e docs(fidelity): add implementation continuation handoff`. The four pre-existing in-progress files preserved and documented separately.
---

## Real-provider runtime verification (interleaved with the above) and the defects it exposed

Across many turns the agent ran the API from current `HEAD` against the root SQLite DB with the real engine provider (DeepSeek model, live MCP endpoint) and drove full journeys in the built-in browser. This surfaced runtime-only defects that unit tests missed; each was fixed rather than worked around:
- **`crypto.randomUUID` unavailable** in the non-secure LAN browser context crashed goal submission → secure-capable fallback in `client_id.ts` (+ regression test).
- **Interview 503 stranded the scientist.** Added a deterministic, resumable interview fallback that keeps the four fields editable without fabricating scientific output. Verified end-to-end: challenge → focus → preferences → four-field research plan → exactly two run choices → Start research.
- **Live steering was unreachable from the UI.** "Open Agent" always used post-report Q&A even during active runs. Rewired: during active states it queues scientist guidance ("Guidance queued. The Supervisor will incorporate it at the next safe task boundary."); after completion it's grounded Q&A. Distinct copy + tests.
- **"Parallel" fan-out was serialized** — the default deployed API consumed the durable queue with one embedded worker. Added a bounded worker cohort maintained through fan-out creation (+ timing/overlap test).
- **Control-plane freeze** — FastAPI executed the worker cohort on its request event loop; a long provider call made the API stop answering health/run requests. Moved the cohort onto FastAPI's threadpool boundary while keeping leases in SQLite.
- **Forced restart = real crash/restart recovery test.** After restart, startup found the checkpoint, resumed the interrupted run, kept the API responsive, marked the queued scientist guidance `applied=1`, and the Supervisor's next decision explicitly referenced that steering.
- **Active-run screen honesty** — report/export/share controls now hidden until a report exists; progress honestly indeterminate for a dynamic plan; active task, committed idea/source counts, elapsed time, and activity events are real.
- **Ranking bug** — durable peer reviews were attached but `overall_score` was never copied onto hypotheses, so ranking logged a top review score of `0.00`; fixed the aggregate commit (+ regression).
- **Supervisor queue actions** — added bounded, auditable reprioritize / cancel / retry validated against same-run task state (selected next specialist remains the creation action). Engine 1,048, app 433, frontend 279, MCP 10, parity 64 rows, eval smoke.
- **E2E (Playwright, 5 journeys).** Fixed a genuine cross-origin `POST …/start` preflight 404 at the ownership middleware (`77837111`); updated stale specs (they required demo runs in Recents, one-message interview completion, and the removed `ultra` tier); demo fixtures now accessed only via their explicit fixture API. Unsandboxed launch needed (macOS Mach-port sandbox denial killed Chromium before page creation).
- **Mock contamination in Recents** — mock/demo runs entered through both the demo endpoint and the owner-history endpoint; tightened the boundary to exclude every mock-provider run in faithful mode (committed).
- **Process-boundary durability** — proved exactly-once effects across process crash/redelivery using independent child interpreters (the semaphore-backed process pool was environment-restricted).
- **Responsive home evidence** `2352aef7`; then fixed a mobile workspace collapse (the section shrank to ~a quarter viewport).
- **Proximity landscape** — persisted the engine's weighted similarity graph, exposed via API, rendered as an interactive Idea Landscape. Runtime network log then showed the proximity request omitted ownership headers and silently degraded to an empty graph → fixed.
- **Attachment control was preview-only** — selected `File` objects were discarded before a run existed. Wired staged files through session state; upload + extract + index after draft creation but before execution; 25 MB cap, SHA-256/version/MIME/size/extractor provenance; unsupported image/OCR fails explicitly.
- **Runaway budget** — a Standard run expanded from 8 ideas to **86**; `current_iteration` stuck at `0` so the two-iteration budget never terminated. Fixed the supervisor iteration counter (`dfb22531 feat: steering + budget`). A stale API process had run pre-fix code; restart doubled as recovery evidence.
- **Evidence-safety, pre-tournament** — deep verification now precedes Elo; claims assessed against retrieved articles; unsupported/contradicted (`undermined`) ideas excluded from matches but retained for Non-Viable/audit; exact spans + assessor provenance in checkpointed state; failure reason fed to evolution so a later child can repair it; a new source can release a previously blocked idea (`15c5be25`). Parity ledger updated to drop stale "missing" claims.
- **Retrieval defects (root causes, in order found):**
  - Bundled multi-source registry defined PubMed + OpenAlex but a config-less run discarded it and fell back to PubMed-only → made the bundled registry the actual default (single-source only as explicit legacy fallback).
  - Node cache keyed only on goal text → replayed a stale PubMed-only entry even after model/budget/registry/guidance changed → versioned the cache contract, keyed on every material retrieval input.
  - **OpenAlex "Extra data" JSON failure**: the search builder always supplied `slug`, `ToolConfig.map_parameters()` preserved unmapped fields, both OpenAlex configs omitted `slug: null`, so the MCP server returned a Pydantic string beginning `1 validation error…` → fixed the tool contract so the request is exactly `{query, max_papers, recency_years, run_id}` (`7741a1ad`). A separate transient malformed transport response is now retried twice with the original diagnostic preserved (`01879fbe`).
  - PubMed "fulltext" adapter discarded every abstract-only result (8-paper target collapsed to 1) → prefer PMC full text, fill with ranked PubMed abstracts, keep honest metadata.
  - Cross-query overlap collapsed 8 sources to 4 → over-fetch each expanded query, dedup + rank globally, then enforce the unique evidence budget.
  - Abstract-index sources were retained as citations but excluded from analysis → they now participate with a visible full-text vs abstract-only distinction; metadata-only records can't inflate the analyzed count.
- **Elo K-factor ignored** — the UI/API exposed a configurable K but real runs always used 24 → threaded the recorded run spec through checkpoints and durable ranking.
- **Positional judge bias** — malformed judge output was silently awarded to slot A; top-tier debates now alternate presentation order, normalize votes to stable hypothesis identities, and decide by the full debate.
- **MCP readiness race** — recovered reflection workers began retrieval before the shared MCP registry finished initializing (`mcp client not initialized`) → serialized readiness so workers can't race the tool client (+ concurrent-init test).
- **Proximity-pruned parents discarded** → forced evolved children to be stored as lineage roots. Fixed by retaining pruned hypotheses as rejected/non-viable **archive** records, preserving lineage and historical match resolution without returning duplicates to active ranking.
- **Claim roles** — the publication policy conflated unsupported categorical background with genuinely proposed hypothesis content, making an honest novel hypothesis unpublishable. Implemented roles end-to-end: categorical context stays fail-closed; explicitly speculative hypothesis/prediction claims may remain "insufficient" only when labeled ("Speculative — evidence insufficient"); contradictions block every role; at least one supported contextual claim required for ranking/reporting. Added a `claim_role` column (migration).
- **Deep verification did no new retrieval** for its probe questions → now prioritizes fundamental probes, performs fresh literature searches, re-adjudicates against new sources, persists them, records the extra model call.
- **Grounding default** — real runs defaulted to lexical overlap despite the spec mandating semantic entailment → semantic-by-default for real runs; deterministic mode pinned only in offline tests/mocks.
- **Claim-audit recomputation** — every ranking cycle re-paid for every semantic assessment even when nothing changed → added a provenance fingerprint (assessor + claim roles + exact evidence passages); unchanged audits reuse their verdict, new evidence invalidates it.
- **Report export** — structured report payload and Markdown export now carry each released hypothesis's claim graph, rendering every claim as supported / contradicted / speculative-insufficient / unsupported categorical with exact supporting/contradicting spans + source titles/URLs (backend/serialization/Markdown/frontend-type tests). Verified in the live report; unsupported categorical claims stay fail-closed.
- **Planner observability** — after the first tournament the model correctly chose another exploration pass but its displayed rationale falsely said "no hypotheses" while reporting a pool of 8 → user-facing/task-history rationale is now a deterministic summary of live counts; raw planner text retained under `planner_reason` for audit.
- **Mobile Ideas detail pane** — selecting an idea left the whole detail (including evidence labels) inside a **79 px** nested scroller with a 2,098 px inner region. Fixed the responsive flex-height/overflow contract; re-verified: mobile expands full content with no horizontal overflow; desktop keeps the three-column split (`384px 712px 272px`) with independent detail scrolling.
**Evaluation artifacts (honest, bounded).** Offline citation smoke green (contradiction recall 1.0) but explicitly only a 20-case synthetic panel — does **not** close the larger human-audited requirement. Semantic citation eval on the DeepSeek provider: 20/20, contradiction recall 1.0, hard-paraphrase accuracy 1.0, per-label confusion recorded. Safety eval: 13 hand-written adversarial cases, 0 false positives/negatives across prohibited/dual-use/ethical/obfuscation/report-leakage/benign-near-miss; metadata states it does not reproduce Google's private 1,200-goal benchmark. Expert-review schema versioned to **six mandatory axes** (novelty, plausibility, impact, alignment, testability, safety) with per-axis 95% intervals + Wilson inter-rater agreement; an explicit "not run" readiness report checked in (no ratings invented). NotebookLM handoff verified to perform a real Markdown download (not a plain navigation).
Representative real-run terminal states observed: one soak completed 192 durable tasks, 21 ideas, 12 sources, 29 reviews, 12 final matches but was **correctly blocked** from publishing because no idea had an evidence-supported contextual claim (fail-closed integrity, not success); the claim graph showed 86 ideas / 1,175 claim edges / 0 retrieved evidence, tracing to the unavailable retrieval service — used as diagnostic evidence, not counted as done.
---

## User interjection #4 — how many artifacts?

> **[User]** so how many artifacts are there for this, there was an original diff document, and implementation prompt, some matrix, the handoff, probably other ones I'm missing?
**[Assistant]** Core implementation-control artifacts (5):
1. `GOOGLE_CO_SCIENTIST_FIDELITY_DIFF_2026-07-12.md` — 232-item audit, uncertainty + difference registers, roadmap.
2. `GOOGLE_CO_SCIENTIST_1_TO_1_IMPLEMENTATION_PROMPT.md` — imperative spec + 17 acceptance conditions.
3. `fidelity_closure_overrides.json` — machine-readable evidence + status.
4. `IMPLEMENTATION_CLOSURE_MATRIX_2026-07-13.md` — generated status of all 232 findings.
5. `IMPLEMENTATION_HANDOFF_2026-07-13.md` — operational continuation guide.
Related but separate (5): `docs/PARITY.md` (machine-checked, predates the exhaustive audit), `docs/FIDELITY.md` (narrative, partly stale), `docs/PARITY-VERIFICATION.md` (July 10 report, stale counts), `docs/ui-fidelity.md` (earlier UI/UX audit), `.remember/remember.md` (entry pointer). Evidence outputs: 4 dated screenshots in `docs/assets/`, 10 eval JSONs in `evaluations/results/`.
Counts: **5 core + 5 related/pointer + 14 evidence = 24** (excluding `references/`, tests, scripts, source, DB). Reading order for a fresh agent: **handoff → fidelity diff → implementation prompt → closure overrides/matrix → parity ledger**.

## User interjection #5 — consolidate the five

> **[User]** the latter 5 are unrelated, can you put the former five in a single directory.
**[Assistant]** Isolated the five under `docs/audits/google-co-scientist-implementation/`; updated all path references, the matrix generator default, and the `.remember` pointer; verified clean git renames; generator rebuilt all 232 findings; parity checker passed.
- Commit: `ca5ff444 docs(fidelity): group implementation artifacts`.

## User interjection #6 — update the goal prompt

> **[User]** great can you help me update the goal prompt then
**[Assistant]** Produced an updated goal prompt (iterated across turns; final block below).

## User interjection #7 — how close again?

> **[User]** how close are we again?
**[Assistant]** Acceptance ledger: **6 of 17 implemented, 8 partial, 3 unproven.** Core system substantially built, but not close to complete because verification-heavy requirements remain: citation/publication-gate proof at scale, complete Goal Report/share/export/follow-up browser journey, real-provider proof for every scientist-input path, full safety/adversarial evaluation, large/private/structured-corpus evidence, missing Elo/expert-review/recovery/scaling/safety reports, all-state desktop/mobile verification, reconciliation of all 232 findings, and a final full-suite + requirement-by-requirement audit. No reliable percentage should be inferred from the condition count.

## User interjection #8 — goal prompt in a block

> **[User]** can you put the goal prompt in a block
**[Assistant]** Final carryover goal prompt:

```text
Complete the Google AI Co-Scientist fidelity implementation in the current repository.
Begin by reading every file in `docs/audits/google-co-scientist-implementation/` in this order:
1. `IMPLEMENTATION_HANDOFF_2026-07-13.md`
2. `GOOGLE_CO_SCIENTIST_FIDELITY_DIFF_2026-07-12.md`
3. `GOOGLE_CO_SCIENTIST_1_TO_1_IMPLEMENTATION_PROMPT.md`
4. `fidelity_closure_overrides.json`
5. `IMPLEMENTATION_CLOSURE_MATRIX_2026-07-13.md`
Treat the fidelity diff and implementation prompt as the authoritative scope. Use the handoff to resume from the current implementation and runtime state without repeating completed work. Treat the closure files as evidence trackers, not as substitutes for inspecting executable behavior.
Implement every actionable gap identified by the diff and prompt. Assess and credit only behavior that actually works in the current product. Do not count plans, comments, component names, schemas, routes, prompts, mocks, stubs, demonstrations, or superficial UI as completed behavior.
Preserve all existing user changes. Follow `AGENTS.md`, commit at natural checkpoints, and verify frontend behavior visually and interactively with the built-in browser at desktop and mobile viewports.
Maintain evidence traceability throughout:
- Link each closed finding to exact files, symbols, tests, runtime evidence, or browser artifacts.
- Update `fidelity_closure_overrides.json` only when direct evidence supports the new status.
- Regenerate the closure matrix with `python3 docs/audits/google-co-scientist-implementation/build_fidelity_closure.py`.
- Keep `docs/PARITY.md` consistent with actual behavior.
- Clearly mark proprietary or insufficiently evidenced Google behavior as inferred or unverifiable.
- Do not assign a numerical fidelity score or claim literal parity where Google’s implementation is undisclosed.
Continue autonomously through implementation, real-provider runtime verification, evaluation artifacts, complete desktop/mobile browser verification, documentation reconciliation, and final quality gates. Diagnose and fix failures rather than narrowing the requested scope.
The goal is complete only when all 17 acceptance conditions in the implementation prompt and every actionable finding in the 232-row fidelity diff have current, direct evidence; all required evaluation reports are checked in with honest methodologies and limitations; all automated, safety, provenance, runtime, and browser gates pass; the closure matrix and parity documentation match the final implementation; and no required work remains.
Do not mark the goal complete based on intent, historical test results, partial progress, or an absence of obvious failures. Perform a final requirement-by-requirement completion audit against the final worktree before declaring completion.
```

---

## Detailed evidence and checkpoint ledger retained from the 1,119-line version

### Audit evidence hierarchy

The audit treated evidence in this order:
1. Executing repository behavior and live runtime results.
2. Exact local reference captures and product specifications.
3. Official Google/DeepMind product documentation.
4. The 2026 Nature paper and 157-page supplement.
5. Public screenshots, demonstrations, reports, and case studies.
6. Evidence-bounded reconstruction where Google internals are undisclosed.
No capability was credited from a matching component name, route, schema, prompt, test fixture, or mock output alone.
The initial walkthrough verified that the visible setup “interview” was client-side inference rather than agent behavior and that uploaded files were discarded before corpus ingestion.
The initial engine had genuine node checkpoints and named agent modes, but its control plane remained a bounded LangGraph traversal with deterministic policy rather than a continuously scheduled asynchronous task market.
The original fidelity artifacts passed structural checks:
- All 232 canonical rows were present.
- Five narrowly matched behaviors were explicitly bounded.
- Every difference and uncertainty was indexed into the roadmap.
- The implementation prompt preserved 17 acceptance conditions.

### Exact early verification baseline

At audit close:
- Engine: 1,018 passing tests.
- Backend: 371 passing tests.
- Frontend: 270 passing tests.
- Frontend build and lint: passing.
- Ruff and strict mypy: passing.
- Evaluation unit tests: 36 passing.
- Citation smoke: failing correctly because contradiction recall was 0.75 against a required 0.80.
The evidence-release fix changed a lifecycle invariant rather than merely adjusting scoring: a report with no scientifically releasable hypothesis could no longer become `completed`.
The mock path remained explicitly exempt for fixture compatibility, preventing mock completion from being used as evidence of faithful scientific release behavior.

### Commit-level implementation evidence

`6df6531e` changed unsupported claims from permitted speculation into quarantined material and prevented them from entering final synthesis.
`3f505ec5` added regression coverage for contradiction handling, unsupported-claim quarantine, and evidence-empty release blocking.
`625455a6` introduced the durable scientific queue with typed tasks, dependency ordering, idempotency, atomic leasing, retries, and exactly-once completion semantics.
`82588231` made live model allocation the normal Supervisor path and retained deterministic policy only as a provenance-labelled failure fallback.
`f8de3786` separated enhancement, simplification, combination, analogy, and out-of-box evolution into behaviorally distinct operators.
`d131d7bd` moved real-engine starts onto durable workflow jobs and added the standalone `app.task_worker` process.
`1f5276f6` ensured meta-review receives all historical reviews and full debate transcripts instead of only the latest summaries.
`4b0ee376` replaced the four clone tiers and Focus selector with the verified Standard/Advanced contract and atomic three-Standard/one-Advanced quotas.
`d97b92cf` removed the client keyword/regex research-plan generator and introduced persistent, resumable model-driven interview sessions.
`7c06e32b` established the report navigation contract: Ideas, Knowledge Base, Summary, and Run Specifications.
`cbfd6db3` generated Knowledge Base topics, Agent Insights, High Potential ideas, and Non-Viable ideas from final scientific state rather than placeholders.
`1c55fc4b` replaced synthetic progress with committed-task progress, actual active work, queue counts, and honest indeterminate states.
`a6c78662` added grounded Open Agent, idea chat, Markdown export, and the NotebookLM interoperability handoff.

`5589c03a` introduced owner-controlled, revocable, hash-token sharing and opaque access failures for private runs.

`5f71653c` added durable post-release email notifications with bounded retry and explicit disabled-environment behavior.

`d8f3c397` limited research-contact suggestions to authors found in retrieved sources and prevented invented contact details.

`d6b25c94` created source-validated cross-document Knowledge Base synthesis with uncertainty and durable evidence handles.

`4a3b6728` added the research-use-only notice to intake, active execution, and shared reports.

`58e6c12f` introduced the `coscientist-safety-v3` contextual risk gate and exactly-once human adjudication.

`bdcb5bfb` introduced invite-based researcher authentication, signed sessions, required-auth mode, and cross-user ownership isolation.

`f76a66b4` was the major durable-orchestration checkpoint, adding separately leased specialists, strategy generation, individual debates, review fan-out, verification fan-out, sequential Elo tasks, and aggregators.

`d355f19e` applied the same durable decomposition to mature Reflection modes and evolved hypotheses.

`c839bd0d` added the fail-closed 232-finding/17-gate closure generator and generated matrix.

`2b6223d2` added ranked, paginated, retraction-aware OpenAlex retrieval and enabled PubMed plus OpenAlex by default.

`316676c2` added OCR, image-only PDF fallback, immutable figure hashes, and page-level extraction provenance.

`f31554cc` consolidated deterministic safety policy into the engine instead of maintaining divergent app and engine policy forks.

`c2ac6c3e` made superseded recovery tasks finish idempotently rather than fail after a newer checkpoint had already won.

`0f3bdb3e` added the detailed continuation handoff and routed `.remember/remember.md` to it.

`ca5ff444` consolidated the five authoritative implementation artifacts into one directory and updated generators and pointers.

### Run-mode and interview verification details

The Standard/Advanced checkpoint was tested across API, CLI, frontend types, persistence, and simultaneous start requests.

Desktop verification at 1440×720 showed exactly two radios, no Focus group, no horizontal overflow, and working Advanced selection.

Mobile verification at 390×780 showed both run modes and Start research reachable through the real timeline scroll container.

The interview API persisted sessions and turns, enforced scientist ownership, supported resume/edit/finalize, and required the four-field derivation before run creation.

When the model was unavailable, the faithful path returned an explicit Agent-unavailable failure instead of silently reconstructing fields from keywords.

Later runtime work added a resumable deterministic field-edit fallback to avoid stranding users, while still refusing to fabricate scientific hypotheses or evidence.

### Goal Report and follow-up verification details

Report finalization draws its sections from released hypotheses, claim-evidence edges, Elo outcomes, and meta-review.

The Knowledge Base stores evidence-linked topics rather than copying abstracts into a “Learning” page.

Summary Agent Insights include findings, uncertainties, contradictions, future directions, and discriminating experiments.

Ideas are explicitly divided into High Potential and Non-Viable groups with exclusion reasons preserved for audit.

Open Agent and Chat with Agent reuse the grounded persisted SSE path; they are not separate ungrounded chat demonstrations.

The Markdown export was later expanded to include each released hypothesis’s claim graph, evidence status, exact supporting or contradicting spans, titles, and URLs.

The NotebookLM action was later corrected to trigger a real Markdown download before opening NotebookLM, rather than merely navigating through a synthetic anchor.

### Durable specialist execution details

The durable runtime separates pure engine specialist execution from app-level queue orchestration.

Each task receives a committed checkpoint, executes one specialist, and atomically writes the next checkpoint and successor task.

Redelivery after acknowledgement does not repeat the scientific effect.

Scientist steering and private-source context are re-injected at each durable task boundary.

Pause changes queued work into non-claimable paused state; an in-flight specialist may finish only to a checkpoint.

Resume restores the exact recorded successor instead of restarting the graph from a broad phase boundary.

Cancellation revokes queued and leased tasks, rejects late acknowledgements, and prevents an in-flight result from committing after cancellation.

Finalization is replay-safe: deterministic publication artifacts are rebuilt while researcher contributions and intake audit records remain preserved.

Initial review and deep verification use one leased child task per hypothesis and one idempotent aggregator as the sole state committer.

Generation uses separate tasks for tool-grounded observation, literature debate, latent debate, and assumptions, followed by a provenance-preserving aggregator.

Each scientific debate is its own leased task; multiple debates are not hidden inside a single “debate strategy” worker.

Tournament matches remain sequential because the next pairing must observe the Elo ratings and match coverage committed by the previous judgment.

### Reflection and feedback propagation details

The original full and simulation reviews applied only to one leading hypothesis; recurrent review was effectively an enum alias.

The replacement comprehensive-reflection stage applies observation, full, simulation, and recurrent/tournament review to every viable hypothesis.

Evolved children receive the same review cascade rather than bypassing observation review.

Recurrent review is actually re-dispatched with current Elo state, prior reviews, debate outcomes, and meta-review guidance.

Evolution receives hypothesis-specific evidence rather than a global history dump: matching debate outcome, wins/losses, rationale, proximity neighbors, verification probes, reviews, and meta-review.

The forced two-to-three-sentence “We want to develop X to enable Y” clone format was removed in favor of mechanistic, falsifiable, evidence-bounded scientific proposals.

### Retrieval and evidence details

The source registry now supports PubMed, OpenAlex, ChEMBL, reviewed UniProt, MCP tools, and typed private documents.

OpenAlex supports cursor pagination, API keys, retraction metadata, deterministic source ranking, and cross-source deduplication.

The full-text PubMed adapter now prefers PMC content but fills the evidence budget with honestly labelled abstracts instead of dropping them.

Search over-fetches expanded queries, then deduplicates and ranks globally so an eight-source budget means up to eight unique sources.

Abstract-only records participate in analysis with an explicit abstract/full-text distinction; metadata-only rows cannot inflate analyzed counts.

The retrieval cache contract now includes every material input instead of keying only on the research goal.

The invalid OpenAlex `slug` parameter was removed, and malformed transport responses receive two bounded retries with original diagnostics retained.

Retractions and unavailable sources are quarantined before claim assessment; direct tests prove they cannot enter the evidence assessor.

Private uploads preserve SHA-256, MIME type, size, version, extractor identity, stable citation ID, page provenance, and bounded excerpts.

OCR failure or unsupported image processing is surfaced explicitly rather than replaced with invented text.

Table and figure semantic interpretation remained only partial at transcript end.

### Claim-grounding and ranking details

Deep verification was moved before Elo so unsupported or contradicted hypotheses cannot win tournaments merely through rhetorical quality.

Blocked hypotheses remain in Non-Viable/audit state and can seed a repaired evolved child.

Fresh evidence can invalidate an old assessment fingerprint and release a previously blocked hypothesis.

Claim roles distinguish supported contextual facts, contradicted claims, categorical unsupported claims, and explicitly speculative predictions.

Contradictions block every role; speculative predictions may remain only when clearly labelled evidence-insufficient.

At least one supported contextual claim is required before ranking and publication.

Real runs default to semantic entailment; lexical/deterministic assessment remains pinned to mocks and offline tests.

A provenance fingerprint over assessor, claim roles, and exact evidence passages prevents paying for unchanged semantic assessments each ranking cycle.

The configurable Elo K-factor is threaded from the recorded run specification into durable ranking.

Malformed judge output no longer defaults to slot A; top debates alternate presentation order and normalize results to stable hypothesis identities.

Pruned parents remain archived as non-viable records so lineage and historical matches do not disappear.

### Runtime recovery and observability details

A non-secure LAN browser exposed missing `crypto.randomUUID`; a secure-compatible fallback was added.

The embedded worker was discovered to serialize nominal fan-out, so a bounded worker cohort and overlap tests were added.

The worker cohort originally ran on the FastAPI event loop and froze health and run endpoints during long provider calls; it was moved to a threadpool boundary.

A forced restart recovered from the latest durable checkpoint and subsequently applied queued scientist guidance in the Supervisor’s next decision.

The API initially selected `app/coscientist.db` when launched from the app directory; runtime was pinned to the authoritative root database.

Duplicate mature-reflection aggregates could race after recovery; superseded checkpoint commits are now treated as idempotent success.

The active-run page hides report/share/export controls until a report actually exists and shows real active tasks, counts, elapsed time, and events.

The Supervisor can now issue bounded, auditable reprioritize, retry, and cancel actions validated against same-run tasks.

User-facing planner explanations are derived from live counts, while the raw model text remains stored as `planner_reason` for audit.

### Browser and end-to-end details

Five Playwright journeys exposed and fixed an ownership-middleware cross-origin preflight 404 on `POST .../start`.

The E2E fixtures were updated to stop assuming demo runs in Recents, one-message interview completion, or the removed Ultra tier.

Mock-provider runs are excluded from faithful-mode Recents regardless of whether they entered through demo or owner-history routes.

The proximity landscape persists the weighted similarity graph, exposes it through an ownership-aware API, and renders an interactive Idea Landscape.

A missing ownership header originally caused the graph request to degrade silently to empty; that request path was fixed.

The mobile Ideas detail pane originally measured only 79 pixels tall around a 2,098-pixel nested region.

The corrected mobile layout expands the full detail content without horizontal overflow; desktop retains the three-column split and independent detail scrolling.

### Evaluation details retained for honesty

The deterministic citation smoke and the live DeepSeek-compatible semantic panel both reported 20/20, contradiction recall 1.0, and hard-paraphrase accuracy 1.0.

Those panels remain synthetic and small; they do not constitute an independent representative scientific audit.

The safety artifact contains 13 independently written adversarial cases and recorded no observed false positives or false negatives.

Its metadata explicitly states that it does not reproduce Google’s private 1,200-goal benchmark.

The expert-review schema now requires novelty, plausibility, impact, alignment, testability, and safety.

Each rating is tied to a rater; duplicates fail closed; summaries include 95% intervals and exact/within-one-point agreement with Wilson intervals.

The checked-in expert-review readiness artifact explicitly records that no panel was run and invents no ratings.

### Progress-tracking caveat

The closure matrix and overrides prevent requirements from being lost, but they lagged behind later implementation commits.

A row marked `unproven` can therefore mean either missing behavior or missing direct evidence linkage; current code and runtime evidence remain authoritative.

Conversely, green tests and similarly named components do not prove Google fidelity unless the audited observable behavior and evidence contract match.

The last defensible status remained substantial implementation without completion proof, pending full reconciliation of every actionable finding and all 17 acceptance conditions.

## Status at end of transcript

- **Acceptance conditions:** 6/17 implemented, 8 partial, 3 unproven.
- **Verification band (current `HEAD`):** engine ~1,047–1,048 tests + Ruff + mypy; app ~422–433 tests + Ruff + mypy; frontend ~274–279 tests + lint + build; MCP 10; durable-task concurrency ~28; parity 64 rows; eval smoke green (bounded panels only).
- **Commit history (durable record):** the checkpoints above, most recently through the orchestration/retrieval/OCR/safety/recovery/consolidation commits (`c2ac6c3e`, `0f3bdb3e`, `ca5ff444`, plus the real-run defect fixes committed where quota allowed). Earlier baseline included `f76a66b4`, `d355f19e`, `c839bd0d`, `2b6223d2`, `316676c2`, `f31554cc`.
- **Remaining to reach completion:** finish generation/debate durable decomposition verification; prove the full Supervisor task-taxonomy control; large/human-audited citation + safety panels; complete report/share/export/follow-up browser journeys with saved captures; real-provider proof that every human-input path (steering, hypothesis, review, attachment) affects later scientific work; missing Elo-calibration / expert-review / recovery / scaling / safety reports with honest methodology; reconcile all 232 findings against the final worktree; behavior-only doc/runbook rewrite; final full-suite + requirement-by-requirement completion audit. The result may legitimately retain an explicit proprietary/unverifiable register — undisclosed Google internals must stay marked unverifiable rather than invented to claim literal parity.
