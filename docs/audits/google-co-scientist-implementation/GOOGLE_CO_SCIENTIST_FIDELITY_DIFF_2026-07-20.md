# Google AI Co-Scientist / Hypothesis Generation fidelity diff

**Audit date:** 2026-07-20
**Repository revision:** `11a310825f9fc53afb6e9cbbb443514e5db1fc84`
**Target:** the current Google Labs Hypothesis Generation product and the peer-reviewed Google Co-Scientist research system
**Question:** does the working repository reproduce the target 1:1?

## Executive conclusion

No. The repository is a substantial, runnable Co-Scientist-inspired research workbench, but it is not a 1:1 replica of either Google's current Labs product or the published research system.

The strongest implemented foundations are real: a model-driven server-side interview, persisted runs and checkpoints, several distinct scientific review paths, pairwise Elo initialized at 1200, immutable evolved descendants, a durable task queue, real literature/tool adapters, claim-evidence records, safety decisions, reports, SSE, CLI access, and a React application that reads persisted run artifacts. Those behaviors receive credit below.

The defining Google architecture is nevertheless different. Google describes a continuously operating asynchronous coalition in which a freeform Supervisor allocates a portfolio of tasks and resources across six specialist roles from live run statistics. This repository begins with a fixed serial graph, and its Supervisor prompt explicitly says it must not plan execution. A later heuristic scheduler chooses one next specialist boundary at a time. Phase-local fan-out does not make that the disclosed asynchronous coalition.

The current product surface is also a different product. The directly evidenced Labs journey is a green Hypothesis Generation experience: Create a run, conversational Agent interview with a persistent Interview Progress rail, Standard or Advanced configuration, an hours-long Idea Tournament, and a Goal Report ordered Ideas, Knowledge Base, Summary, Run Specifications, with post-run Agent discussion, NotebookLM, public sharing, download, feedback, and deletion. The live repository instead opens in a Gemini Enterprise-inspired Co-Scientist shell, interrupts first use with an Affiliation dialog, exposes Express/Standard/Extended/Ultra plus a separate focus selector, lands completed runs on Goal Details, and labels the remaining tabs Learning, Research Overview, and All Ideas. Several backend clients for Agent Q&A, steering, human contributions, sharing, and export have no reachable UI.

The largest release-blocking defects are scientific and safety failures, not styling differences. Direct reproductions at this revision established that:

- a schema-valid Proximity response produces an empty weighted graph;
- claim-gate-blocked hypotheses remain active and can be released into the final leaderboard, idea buckets, and report;
- fresh Standard and Ultra offline runs completed despite all 6 and all 10 hypotheses respectively failing the claim gate and all 30 and 50 claim assessments being `insufficient`;
- a retracted source can be reserved, selected, analyzed, and synthesized;
- a research overview can be generated from rejected or safety-blocked ideas;
- a scientist-submitted hypothesis can collide with itself during final persistence;
- approved intake and final safety holds have no claimable successor task;
- an exhausted task can leave its owning run permanently `running`;
- a `redact` safety decision records a label but persists the original content; and
- a public share returns raw hypotheses/evidence rather than only the filtered release artifact.

The repository therefore fails both necessary fidelity tests: it does not reproduce the observable product contract, and it does not preserve several published architectural and safety invariants. Existing parity/closure documents are implementation claims, not proof; multiple claims are stale or contradicted by the current runtime. No numerical fidelity score is assigned.

A literal production-identical clone is also not provable from public evidence. Google's models, prompts beyond the disclosed set, Supervisor policy, queues, tool infrastructure, safety classifiers, tier budgets, and production source code remain proprietary. The defensible endpoint is an evidence-bounded reconstruction that exactly implements every verified public behavior, labels every local choice, and does not call proprietary unknowns “matched.”

## Audit rules

Only reachable, working behavior receives implementation credit. The audit does not credit names, comments, plans, schemas without consumers, dormant API clients, unused UI, seeded demonstrations, deterministic offline fixtures, hard-coded suggestions, mocks, or passing unit tests that exercise a shape different from production.

| Class | Meaning |
|---|---|
| `matched` | The material, observable behavior matches verified public evidence. |
| `partial` | A working subset exists, but an important semantic, scale, safety, or surface element differs. |
| `missing` | No working reachable implementation exists. |
| `incorrect` | The product claims or attempts the behavior but materially violates its contract. |
| `divergent` | A working substitute implements a different product or architecture. |
| `non-faithful extension` | Working behavior is useful but is not evidenced as Google behavior and changes a strict 1:1 surface. |
| `unverifiable` | Google's exact behavior is not public enough for a defensible comparison. |

Intentional extensions remain fidelity differences. Paper architecture, current Labs UI, Gemini Enterprise Idea Generation, and repository-authored reconstruction documents are kept separate throughout.

## Evidence register

### Primary external evidence

All current web sources below were checked on 2026-07-20. The Nature article was published 19 May 2026; the intended-use Help page identifies a 28 April 2026 modification date.

| Key | Source | What it can verify |
|---|---|---|
| `G1` | [Nature: Accelerating scientific discovery with Co-Scientist](https://www.nature.com/articles/s41586-026-10644-y) (2026) | Canonical architecture, agent roles, evaluation, case-study and limitation claims. |
| `G2` | [Nature Supplementary Information](https://static-content.springer.com/esm/art%3A10.1038%2Fs41586-026-10644-y/MediaObjects/41586_2026_10644_MOESM1_ESM.pdf) | Schematic pseudocode, eight disclosed prompts, worked outputs, safety and ablations. |
| `G3` | [Google Help: How to research with Hypothesis Generation](https://support.google.com/hypothesis-generation/answer/17106281?hl=en) | Current Labs interview, fields, Standard/Advanced, quotas, report tabs, Agent, NotebookLM, sharing and download. |
| `G4` | [Google Help: Give feedback](https://support.google.com/hypothesis-generation/answer/17105610) | Product Feedback path and optional screenshot. |
| `G5` | [Google Help: data and deletion](https://support.google.com/hypothesis-generation/answer/17107198?hl=en) | Data requests and permanent run deletion. |
| `G6` | [Google Help: intended use and limitations](https://support.google.com/hypothesis-generation/answer/17106905?hl=en-IN) | Starting-point framing, human verification and medical/human-risk restrictions. |
| `G7` | [Google DeepMind: Co-Scientist](https://deepmind.google/blog/co-scientist-a-multi-agent-ai-partner-to-accelerate-research/) | Current freeform parallel Supervisor description, tools and partner context. |
| `G8` | [Google Labs Science](https://labs.google/science/) | Current experiment entry point and product boundary. |
| `G9` | [Google Cloud: Co-Scientist agent](https://docs.cloud.google.com/gemini/enterprise/docs/co-scientist-and-alphaevolve?hl=en) | Related enterprise architecture/product evidence; not authority for Labs UI. |
| `G10` | [Official Hypothesis Generation video](https://www.youtube.com/watch?v=-nmisG2OTKY) | Visible sequence, Interview Progress, execution counters, report composition, idea diagram and Chat with Agent. |

The 2026 Nature version of record supersedes the 2025 preprint where they differ. Current Help supersedes promotional footage for current wording such as `Run Specifications` plural. Marketing does not override the paper's explicit hallucination, citation-recall, provenance, bias, literature-access and preliminary-validation limitations.

### Local Google/reference evidence

- `references/core/google-co-scientist/research/papers/accelerating-scientific-discovery-with-co-scientist.md`
- `references/core/google-co-scientist/research/supplements/`
- `references/core/google-co-scientist/research/extracted-artifacts/`
- `references/core/google-co-scientist/media/hypothesis-generation/`
- `references/core/google-co-scientist/source-system-reference.md`
- `references/ui-ux/idea-generator/` — a secondary Gemini Enterprise product twin, never treated as the Labs target.

Repository-authored `product-surface-and-ux.md`, `agent-coalition-specifications.md`, `docs/FIDELITY.md`, `docs/PARITY.md`, `docs/ui-fidelity.md`, and earlier dated audits are leads and implementation intent only. In particular, the local 12-agent roster is a clone decomposition, not Google's verified Supervisor-plus-six roster, and `docs/ui-fidelity.md` cites newer MASH footage files that do not exist in the current tree.

### Executed repository and runtime evidence

The audit inspected all implementation-bearing engine, app, frontend, evaluation, deployment, documentation, and reference surfaces. It exercised isolated services with an isolated SQLite database and forced offline model backend; offline output was used only to test control flow, persistence, release gates, and presentation, never as evidence of scientific quality.

| Key | Observation |
|---|---|
| `R1` | Standard run `d58f0e54-…`: completed, 6 hypotheses, 0 evidence, 12 matches, 6 claim-gate blocks, 30 insufficient claims, 5 High Potential entries. |
| `R2` | Ultra run `e09f380d-…`: completed in 95.1 s, 10 hypotheses, 0 evidence, 32 matches, 10 claim-gate blocks, 50 insufficient claims, 5 High Potential entries. |
| `R3` | Both runs stored intake `allow`, final `allow`, hypothesis status `active`/safety `allow`; the blocking claim decisions did not prevent publication. |
| `R4` | Live-shape Proximity input `{index, similarity_degree}` returned zero weighted edges. |
| `R5` | Manual-hypothesis final drain raised `UNIQUE constraint failed: hypotheses.id`. |
| `R6` | Approved intake/final holds left completed tasks and `claimable=None`; an exhausted unsupported task left `task=failed`, `run=running`. |
| `R7` | Browser comparison at desktop 2:1, desktop 16:9 and mobile 1:2; the 16:9 report clipped horizontally and mobile idea detail had no visible return action. |
| `R8` | First-turn interview reached the server and persisted turns, but frontend interview state itself was not reloadable; an observed fetch failure had weak recovery. |

`R1-R3` were produced on 2026-07-20 with `COSCIENTIST_FORCE_OFFLINE=1`, an isolated database and cache under `/tmp/cosci-fidelity-audit.PVBi1v/`, and the API bound to loopback. Exact launch/create/start requests, client IDs, persisted configs, times, aggregate results, report hashes and reconciliation queries are preserved in `docs/audits/google-co-scientist-implementation/RUNTIME_EVIDENCE_2026-07-20.md`. These runs establish control-flow and release behavior only; the temporary database and pseudo-scientific raw reports are deliberately not treated as scientific artifacts.

Visual captures are under `docs/assets/fidelity-audit-2026-07-20/`. The most probative comparisons are `02-home-desktop-16x9.jpg`, `04-interview-question-desktop-16x9.jpg`, `06-goal-details-desktop-16x9.jpg`, `07-knowledge-base-desktop-16x9.jpg`, `08-research-overview-desktop-16x9.jpg`, `10-all-ideas-desktop-2x1.jpg`, `11-all-ideas-mobile-1x2.jpg`, `12-idea-detail-mobile-1x2.jpg`, and `13-home-mobile-1x2.jpg`. `14` and `15` are retained as diagnostic captures but are not used as primary fidelity proof because access/origin state affected those sessions.

### Verification state at audit time

| Check | Result |
|---|---|
| Engine tests | Root `make test-all` engine stage: `1,141 passed in 50.47s`. |
| App full suite | The same 2026-07-20 `make test-all` run reached `631 passed, 3 failed, 32 errors in 941.96s`; the three failures were 10-second multiprocessing lease tests and the 32 errors were CLI fixture startup failures while concurrent audit services were active. The gate is red and load-sensitive, without enough evidence to call every error a deterministic product defect. |
| Frontend build | Passed; main minified JS chunk 503.79 kB, over Vite's 500 kB warning threshold. |
| Frontend lint | Passed. |
| Frontend tests | `423 passed, 1 failed`; the `/proposals` responsive-layout test timed out at 5 s. |
| Evaluation truth gate | Failed: two parity-ledger tests cite three nonexistent test symbols while marking rows verified. |
| Evaluation smoke | Passed, but executes only synthetic safety and citation fixtures and never the scientific engine. |
| MCP package smoke | Editable install exited successfully, but `find_spec('mcp_server')` from outside the repository returned `None`. |
| Root setup | Completed, but omitted the app's required `pypdf` dependency, leaving local PDF ingestion unavailable in that environment. |

Passing tests prove exercised code behavior, not parity. Repeated timeouts and a red truth gate are themselves operational gaps.

## System maps

### Verified current Labs journey

```text
Limited-access researcher on desktop/Chrome
  -> Create a run / research challenge
  -> conversational Agent interview
       Research Challenge | Focus Area | Preferences | optional Title
       persistent right-side Interview Progress
  -> inspect specifications
  -> Configure Run: Standard or Advanced
  -> hours-scale Idea Tournament + email completion
       time remaining | sources analyzed | ideas explored | high-level activity
  -> Goal Report
       Ideas | Knowledge Base | Summary | Run Specifications
  -> Open/Chat with Agent | NotebookLM | public link | download
  -> Product Feedback | permanent run deletion/data request
```

### Current reachable product journey

```text
Compatibility identity / optional invite access
  -> first-load Affiliation modal
  -> Gemini-style Co-Scientist home + hard-coded prompts + demo history
  -> model-backed four-field interview held only in React route state
       attachments preview locally but do not ground the interview
       raw provider reasoning is streamed visibly
  -> hybrid configuration
       Express | Standard | Extended | Ultra
       evidence/balance/novelty/breakthrough focus
  -> create -> upload -> start (non-transactional)
  -> active detail with synthesized ETA and internal stage narrative
  -> completed run lands on Goal Details
       Goal Details | Learning | Research Overview | All Ideas
  -> no reachable report Agent, steering, human contribution, share creation,
     report download, NotebookLM, general feedback, or run deletion
```

### Verified research-system loop

```text
ResearchPlan in shared persistent context
  -> continuously running asynchronous task queue
  -> freeform Supervisor observes run statistics and allocates resources
  -> Generation / Reflection / Ranking / Evolution / Proximity / Meta-review
     execute and create follow-up work, with candidate safety throughout
  -> pairwise Elo tournament + semantic proximity + immutable descendants
  -> recurring meta-review feedback appended to later agents
  -> terminal safe ideas + research overview + human selection/validation
```

### Current engine/backend loop

```text
Interview/API setup -> SQLite run + scientific task
  -> intake safety
  -> fixed serial bootstrap:
       Supervisor guidance -> literature? -> generation -> reflection -> review
       -> comprehensive reflection -> hypothesis safety -> deep verification
       -> ranking
  -> heuristic orchestrator chooses exactly one next specialist boundary
  -> phase-local item fan-out and durable checkpoint/task drain
  -> claim audit + overview/report helpers + final safety label
  -> SQLite report/SSE/API/CLI
```

## Credited working foundations

These are real executable foundations worth preserving. Some align narrowly with verified Google behavior; others are useful local strengths. None is a blanket fidelity match or cancels a difference elsewhere.

| ID | Credited working foundation | Evidence and boundary |
|---|---|---|
| `M01` | Natural-language goal input and server-side conversational interview turns are real. | `app/app/interviews.py`, `app/frontend/src/workbench/hooks/chat_session_handlers.ts`; missing progress/resume/document grounding remains partial. |
| `M02` | Run state, events, checkpoints and item tasks are durably persisted per run. | `app/app/store/`, `engine/src/co_scientist/checkpoint.py`; exact Google infrastructure is unknown. |
| `M03` | Pairwise Elo uses a 1200 initial rating and canonical logistic update. | `engine/src/co_scientist/agents/ranking/`; higher-level matchmaking/debate constants remain local choices. |
| `M04` | Evolution creates a new child with a new ID, parent link and fresh Elo; it does not overwrite the parent. | `engine/src/co_scientist/agents/evolution/evolve_results.py`. |
| `M05` | Multiple reflection concepts exist as executable paths, including initial, full, simulation, recurrent, observation and deep verification. | `engine/src/co_scientist/agents/reflection/`; their dispositions are not consistently release-enforcing. |
| `M06` | Meta-review consumes review history and tournament debate transcripts and a final overview can include directions, experiments, Specific Aims and contacts. | `engine/src/co_scientist/agents/meta_review/`; feedback coverage and release filtering are incomplete. |
| `M07` | Real configurable literature/tool paths, private-document ingestion, evidence, citations and claim edges exist. | engine generation/literature tools and app ingestion/store; semantic relevance, scale, multimodality and quarantine remain deficient. |
| `M08` | The frontend reads real hypotheses, reviews, matches, evidence, safety, claim edges, report payloads and run events. | `app/frontend/src/api/runs.ts` and run-detail components; numerous defined clients remain unused. |
| `M09` | Active execution shows real idea/source counts and real high-level run events. | `run_detail_active.tsx`; ETA and narrative semantics differ. |
| `M10` | Persisted Knowledge Base topics and references render when they actually exist. | `run_detail_learning.tsx`; the fallback fabricates synthesis and link shaping is wrong. |
| `M11` | Share capabilities are high-entropy, hash-at-rest, owner-created, listable without disclosing the token and revocable. | `app/app/store/shares.py`; payload minimization/expiry/audit remain critically wrong. |
| `M12` | Upload rows record SHA-256, MIME, byte size, document version and extraction tool. | `app/app/runs.py:968-1002`; file validation, malware, lifecycle and provider disclosure remain incomplete. |
| `M13` | The observed production CORS policy allowlisted the real frontend and rejected an arbitrary origin. | Read-only preflight on 2026-07-20; this is deployed evidence even though code defaults are permissive. |
| `M14` | Observed production health/store/engine and MCP/PubMed/literature/web probes were up. | Read-only production `/health` and `/status`; specialized `TOOLS_CONFIG` was still null and control-plane state unavailable. |
| `M15` | Log ingestion collapses control characters, scopes ordinary readers, caps stored rows and avoids `/api/logs` self-amplification. | `logs_api.py`/store/logging; caller-controlled rate identities and end-user visibility remain defects. |

## Exhaustive product-surface and frontend comparison

Each row records the target behavior, the working behavior, the exact gap, consequence, and both external/repository evidence. `G#` and `R#` resolve through the registers above.

### Entry, home, and goal composition

| ID | Class | Google behavior | Current working behavior | Exact gap and consequence | Evidence / locations |
|---|---|---|---|---|---|
| `F-ENTRY-01` | `incorrect` | Green/lime Hypothesis Generation identity with an opening Create a run state. | Dark/system Gemini-style Co-Scientist shell titled “What breakthrough should we make today?”. | The first observable state is a different product; ribbon art, product name and transition are absent. | `G3`, `G10`; `feature-overview-splash-screen.jpg`; `chat_home_stage.tsx:224-256`; `R7/02`. |
| `F-ENTRY-02` | `divergent` | Start the research flow after obtaining Labs access. | `AudienceGate` automatically opens Settings/Affiliation on first private visit. | An unevidenced organization chooser blocks the core journey and reveals clone-specific context. | `G3`; `audience_gate.tsx:15-53`, `audience_content.ts`; `R7/01`. |
| `F-ENTRY-03` | `divergent` | Labs uses the captured full-canvas green product frame. | Persistent rail, Co-Scientist brand, chat history, Logs, Offline and theme/settings chrome. | The shell follows the secondary Gemini Enterprise twin, not the direct Labs surface. | `G10`; `references/ui-ux/idea-generator/`; `workbench_layout.tsx`. |
| `F-ENTRY-04` | `non-faithful extension` | No public evidence of audience-specific scientific products. | Google-team, SBI/UCD and General affiliations change copy, suggestions, corpus and feedback. | Project outreach/pilot states alter target behavior and should be outside the fidelity path. | `audience_content.ts:6-146`. |
| `F-ENTRY-05` | `non-faithful extension` | Access is invitation-based, but the exact access UI is undisclosed. | Custom `/access` code/request flow. | A local access mechanism may be useful but cannot be called a visual or behavioral match. | `G3`; `access_page.tsx`, `workbench_app.tsx`. |
| `F-ENTRY-06` | `partial` | Recent research groups the user's drafts, active runs and past work with dates. | Real history/cards exist, but `loadRunHistory` merges public demos by default and cards do not label `is_demo`. | Deterministic fixtures can look like the scientist's own work, corrupting provenance. | `G3`; `api/runs.ts:371-393`, `run_history_context.tsx`; `app/app/seed.py`. |
| `F-HOME-01` | `incorrect` | Create a run then answer “What's your research challenge?”. | Invented three-step home onboarding and breakthrough headline. | Copy and sequence match neither Labs nor the exact Gemini Idea Generation twin. | `G10`; `chat_home_stage.tsx:90-112,224-256`; `R7/02`. |
| `F-HOME-02` | `divergent` | Goal suggestions/templates are not established by current public evidence. | Three hard-coded biomedical prompts; SBI mode substitutes another fixed set. | Static fixtures dominate entry and must not be credited as personalized Agent behavior. | `chat_home_stage.tsx:45-79`, `audience_content.ts`. |
| `F-HOME-03` | `partial` | A scientist submits a natural-language research challenge. | Working multiline, auto-growing, keyboard-accessible composer with attachments and source toggles. | The core text input works, but label, sequence and surrounding product contract differ. | `G3`; `chat_composer.tsx:66-352`. |
| `F-HOME-04` | `missing` | Visible warning that AI may be inaccurate, claims need checking and medical advice requires a professional. | No equivalent disclaimer beneath the composer. | A directly visible fidelity and safety boundary is absent. | `G6`, `G10`; repository search and `R7/02,04`. |
| `F-HOME-05` | `partial` | Paper system can use large/multimodal private inputs; current Labs upload UX is not verified. | File previews work, but files only upload after a run is created and never inform interview turns or the plan. | The UI implies grounded interview context that it does not supply; failures can occur after plan confirmation. | `G1`; `chat_composer_attachments.tsx`, `hooks/chat_session_handlers.ts:57-62`, `hooks/chat_session_start_run.ts:43-70`. |
| `F-HOME-06` | `partial` | Web/public literature and selected scientific sources support research. | Connector menu is live, but all literature rows share one PubMed Boolean while web/lab are separate. | Per-source presentation overstates actual granularity; exact Labs connector UI remains unknown. | `G1`, `G7`; `chat_composer_connectors.tsx:175-267`. |
| `F-HOME-07` | `incorrect` | No verified browser-local DeepSeek BYOK control. | Settings stores a DeepSeek key locally and confirms success; no request or backend reads it. | Dead UI claims a capability it cannot exercise. | `settings_dialog.tsx:113-164`, `lib/api_key.ts:1-3`. |

### Agent interview and configuration

| ID | Class | Google behavior | Current working behavior | Exact gap and consequence | Evidence / locations |
|---|---|---|---|---|---|
| `F-INTERVIEW-01` | `partial` | Conversational Agent refines the goal into research specifications. | `createInterview`/`addInterviewTurn` call a server model and persist turns/fields. | This is a real material match, but surrounding progress, recovery, grounding and editing are incomplete. | `G3`; `interviews.py`, `hooks/chat_session_handlers.ts:17-118`; `R8`. |
| `F-INTERVIEW-02` | `missing` | Persistent right-side Interview Progress shows Research Challenge, Focus Area(s) and Preferences. | Only chat timeline and composer render. | Users cannot see completion, provenance or changing structured fields. | `G3`, `G10`; `agent-interview-*.jpg`; frontend component inventory. |
| `F-INTERVIEW-03` | `divergent` | Footage shows a Thinking status, not private raw reasoning. | API forwards provider `reasoning`; `AgentThinking` renders the full stream in an `aria-live` box. | Raw chain-of-thought leaks sensitive/private model process and can overwhelm assistive technology. | `G10`; `chat_workspace_timeline.tsx:96-127`, interview streaming code. |
| `F-INTERVIEW-04` | `missing` | Long multi-turn setup should remain available as part of the durable research journey. | Backend has `getInterview`, but no live caller; route state is React `useState`. | Reload/navigation loses the interview UI although the server still has it. | `api/runs.ts`, `chat_session_state.ts:18-118`. |
| `F-INTERVIEW-05` | `incorrect` | Scientist can inspect and refine the specifications. | “Edit research plan” merely re-stages the same spec and focuses the composer; `editInterviewFields` is unused. | Read-only fields and post-completion chat do not perform structured editing despite the affordance. | `G3`; `hooks/chat_session_handlers.ts:147-165`, `api/runs.ts`. |
| `F-INTERVIEW-06` | `incorrect` | Retry should re-run the Agent operation. | Retry duplicates the same assistant string or re-stages the same draft. | UI promises regeneration without making a model call. | `hooks/chat_session_handlers.ts:212-237`. |
| `F-INTERVIEW-07` | `partial` | Plan includes Challenge, Focus Area, Preferences and optional Title. | Completed interview maps those four real fields into a displayed spec. | Core mapping matches, but downstream config and criteria depart. | `G3`; `run_spec.ts:17-30`, `chat_timeline_run_spec_card.tsx:256-265`. |
| `F-INTERVIEW-08` | `incorrect` | Configure exactly Standard or Advanced. | Visible cards expose Express, Standard, Extended, Ultra plus four evidence/novelty focuses. | A cross-product/local taxonomy changes both UI and compute contract; unused types still contain Standard/Advanced. | `G3`; `run_spec.ts:51-106`, `run_types.ts:12-16`, `run_modes.py`. |
| `F-INTERVIEW-09` | `missing` | ARCH verifies a customizable evaluation rubric with Alignment, Plausibility, Novelty, Testability and Safety defaults; Labs directly verifies a Preferences field, not a separate criteria editor. | Mapper hard-codes `criteria: []`; no canonical rubric governs the run or appears in an advanced provenance view. | The scientific system cannot truthfully configure or audit its disclosed rubric; this is an ARCH/provenance gap, not evidence for another Labs field. | `G1`, `G2`, `G3`; `run_spec.ts:25`, `run_detail_specifications.tsx`. |
| `F-INTERVIEW-10` | `partial` | Current Labs sends a completion email after hours-long runs. | A custom-recipient checkbox validates an address and the backend can send a completion notification when SMTP is configured. | Notification is verified, but checkbox/recipient configuration is a local adaptation; configured delivery, retry, failure visibility and recipient privacy were not verified end to end. | `G3`; `chat_timeline_run_spec_card.tsx`, `app/app/notifications.py`, `config.py`. |
| `F-INTERVIEW-11` | `incorrect` | Labs finalizes a plan and creates the run; the related enterprise twin starts a read-only session. | Current card says Start research and later says users can “view and interact,” though no scientific interaction exists on the run page. | Sequence/copy satisfies neither verified product and overpromises interaction. | `G3`, `G10`; `chat_session_start_run.ts`, `chat_timeline_started_card.tsx`. |
| `F-INTERVIEW-12` | `incorrect` | Starting a run should settle to a recoverable run or a clear failure. | Create commits before sequential uploads/start; failure neither deletes nor surfaces the orphan draft. | Partial failure can lose the user's confirmed setup and leave hidden state. | `chat_session_start_run.ts:43-110`. |

### Active execution and report shell

| ID | Class | Google behavior | Current working behavior | Exact gap and consequence | Evidence / locations |
|---|---|---|---|---|---|
| `F-RUN-01` | `partial` | Idea Tournament progress shows time, Sources Analyzed, Ideas Explored and high-level activity. | Dedicated active page reads real persisted/streamed counters and events. | Structure is meaningful, but ETA, narrative and controls differ. | `G10`; `run_detail.tsx`, `run_detail_active.tsx`; `R7`. |
| `F-RUN-02` | `incorrect` | Time remaining is presented as product run state. | Browser linearly extrapolates elapsed time from task fraction. | Uneven scientific tasks make the displayed ETA misleading rather than authoritative. | `run_detail_active.tsx:23-31`. |
| `F-RUN-03` | `divergent` | Activity Log uses concise scientific task/status summaries. | “Live activity” exposes internal supervisor/orchestrator/safety/meta/proximity stage names and details. | Developer graph telemetry replaces the target research narrative. | `G10`; `run_detail_active.tsx:100-223`. |
| `F-RUN-04` | `missing` | ARCH verifies scientist steering through feedback and contributed hypotheses/reviews. | No live scientist control appears during execution, though dormant clients/endpoints exist. | Verified expert-in-loop architecture is not reachable. Exact Labs placement and pause/resume/cancel/early-stop controls remain separate unknowns under `U14`. | `G1`; unused `sendRunSteering`, `addScientistHypothesis`, `addScientistReview`; `U14`. |
| `F-RUN-05` | `missing` | A long-running live surface must distinguish current from stale state, even though exact Google UI is undisclosed. | SSE silently reconnects; no live/reconnecting/stale/failure indicator. | A frozen page can appear healthy and recovery is not actionable. | `use_run_stream.ts`, run-detail components. |
| `F-RUN-06` | `incorrect` | Progress should represent current/high-level completed work honestly. | Home retains the furthest seen phase with `Math.max` even when adaptive cycles return to Generation. | A later step looks current when the engine is doing earlier work. | `home_recents_run_steps.tsx:23-43`. |
| `F-RUN-07` | `partial` | Labs exposes draft/in-progress/past/completed/failed concepts. | Durable draft/queued/running/synthesizing/completed/failed/blocked/cancelled states exist; no paused UI state. | Lifecycle is broad, but non-complete terminal states fall into a report shell and product vocabulary differs. | `G3`; `run_types.ts`, `run_detail.tsx`. |
| `F-REPORT-01` | `incorrect` | Visible report tabs are Ideas, Knowledge Base, Summary, Run Specifications. | Goal Details, Learning, Research Overview, All Ideas. | The primary information architecture directly contradicts current Help and footage. | `G3`, `G10`; `run_detail_shell.tsx:9-14`; `R7/06-10`. |
| `F-REPORT-02` | `incorrect` | Completed research opens on Ideas/Agent Insights. | `/runs/:id` redirects to `details` and prioritizes configuration. | Scientists land on settings instead of scientific results. | `G10`; `run_detail.tsx`, route aliases. |
| `F-REPORT-03` | `missing` | Open/Chat with Agent, NotebookLM, public share and download are reachable report actions. | Title bar has only Back and title. | Core post-run continuation and portability are absent despite some backend APIs. | `G3`; `run_detail_shell.tsx`, unused API clients. |
| `F-REPORT-04` | `partial` | Goal Report contains ranked ideas, knowledge, synthesis and specifications. | Frontend reads a broad real payload: leaderboard, knowledge base, insights, buckets, claims, overview, aims, contacts and counts. | Real data plumbing is a strong foundation, but helpers and presentation are not the target contract. | `run_types.ts:288-375`, report components; `R1-R3`. |

### Ideas, Knowledge Base, Summary, and specifications

| ID | Class | Google behavior | Current working behavior | Exact gap and consequence | Evidence / locations |
|---|---|---|---|---|---|
| `F-IDEAS-01` | `partial` | Full leaderboard is Elo-ranked and ideas are inspectable. | Real list sorts by Elo and detail reads hypothesis, review, match, lineage, safety and claims. | Core data is real, but detail breadth and category presentation are incomplete. | `G3`; `ideas_tab.tsx:96-155,253-299`, `ideas_detail_pane.tsx`. |
| `F-IDEAS-02` | `divergent` | Direct Labs view begins with Agent Insights and categorized idea cards/details. | Fixed three-column list/document/Sections rail closely copies Gemini Enterprise Idea Generation. | A polished clone of the secondary twin is still the wrong product composition. | `G10`; `references/ui-ux/idea-generator/ideas-results/`; `ideas_tab.tsx`. |
| `F-IDEAS-03` | `incorrect` | Labs idea artifact and related enterprise twin use their documented section names. | Adds Hypothesis overview, Provenance & lineage and Match summary while changing the twin's “Idea overview.” | The document matches neither source; useful provenance is an extension, not direct parity. | `ideas_detail_pane.tsx:63-81`; local media. |
| `F-IDEAS-04` | `missing` | Individual ideas may contain a rich generated diagram and Chat with Agent. | Text concatenation only; no generated diagram/media or hypothesis-scoped Agent. | A conspicuous target artifact and its collaborative follow-up are absent. | `G3`, `G10`; `esn-poma-hub-...diagram.jpg`; `ideas_detail_pane.tsx`. |
| `F-IDEAS-05` | `incorrect` | Reflection is multi-strategy and report should not label one critique as the full review stack. | `findHypothesisReview()` uses `find()` and displays one row as “Full review.” | Independent/full/comprehensive/deep results are hidden, misrepresenting verification depth. | `G1`; `ideas_detail_data.ts:9-16`; reviews API/store. |
| `F-IDEAS-06` | `partial` | Ranking uses pairwise tournament/debate; exact bracket/transcript UI is unverified. | Shows aggregate wins/losses and only the latest match rationale. | Users cannot inspect match history/opponents/Elo deltas/debates; do not claim a full tournament view. | `G1`, `G2`; `ideas_detail_data.ts:18-27,104-120`. |
| `F-IDEAS-07` | `missing` | Ideas are grouped High Potential and Non-Viable with reasons. | Payload has entries/reasons, but Ideas omits groups and Summary collapses them to counts. | Users cannot see why ideas were promoted or rejected. | `G3`, `G10`; report payload; Ideas/Summary components. |
| `F-IDEAS-08` | `incorrect` | Selected idea should be perceivable to all users. | Selection is CSS-only; buttons lack selected/current/pressed/listbox semantics. | Screen-reader users cannot identify which row controls the detail pane. | `ideas_tab.tsx:253-299`. |
| `F-IDEAS-09` | `incorrect` | Mobile master/detail needs an explicit return path. | Selecting an idea removes the list; only re-tapping the already-active All Ideas tab resets it. | Hidden navigation traps mobile and keyboard users. | `ideas_tab.tsx:168-205`, `run_detail_shell.tsx:69-79`; `R7/12`. |
| `F-IDEAS-10` | `partial` | Related enterprise Sections rail marks current section. | Anchor links smooth-scroll but have no observer/active state. | Navigation works, but context does not update as the document scrolls. | `ideas_detail_pane.tsx:340-379`; measured twin reference. |
| `F-IDEAS-11` | `incorrect` | Origin labels should be user-safe terms if exposed. | Mapper recognizes `generation`/`evolution`, while engine values may be `generate`/`evolve`; unknowns leak raw keys. | Internal implementation names can appear in the scientific report. | `ideas_detail_data.ts:29-40`, engine origin types. |
| `F-IDEAS-12` | `non-faithful extension` | Current Labs evidence does not expose claim spans, cluster IDs, safety internals or lineage blocks. | Those real audit fields visibly reshape the detail. | Useful transparency should be secondary/advanced, not claimed as 1:1 Labs surface. | `G3`; `ideas_detail_pane.tsx`. |
| `F-IDEAS-13` | `unverifiable` | Gemini Enterprise twin exposes annotations/export, but current Labs proof is insufficient. | No idea annotation/export. | This is a secondary-product gap, not a defensible Labs requirement. | Idea Generator HAR and captures; frontend search. |
| `F-KB-01` | `partial` | Knowledge Base contains synthesized technical documents and numbered openable references. | Persisted topics render title, summary, detail, uncertainty and searchable/openable evidence. | Material behavior exists when data is real; navigation/provenance are thinner. | `G3`, `G10`; `run_detail_learning.tsx:102-386`. |
| `F-KB-02` | `incorrect` | Knowledge Base is Agent synthesis, not presentation-generated filler. | When no synthesis exists, UI turns the first three evidence rows into generic “learning” sections. | Fabricated synthesis can be mistaken for an engine result. | `run_detail_learning.tsx:367-416`. |
| `F-KB-03` | `incorrect` | Reference numbers should resolve globally and consistently. | Each topic renumbers `referenceIds` from 1 while linking to global evidence rows. | A shown `[1]` can jump to `[5]`, breaking traceability. | `run_detail_learning.tsx:164-173`. |
| `F-KB-04` | `partial` | Footage shows technical document outline, context and reference navigation. | Linear topic stack followed by references. | Missing outline/relationships/context passages makes the knowledge artifact materially shallower. | `G10`; `esn-knowledge-base-*.jpg`; learning component. |
| `F-KB-05` | `partial` | References are numbered, searchable and openable; availability must be understood. | Search and Open work, but `Evidence.available` is not visible. | Unavailable/unverified sources look equivalent to accessed sources. | `G10`; `run_detail_learning.tsx`. |
| `F-SUMMARY-01` | `partial` | Summary synthesizes research and supports human interpretation. | Real insights, directions, experiments, Specific Aims, contacts, winners and match count render. | Broad synthesis exists, but release filtering and category truth are defective. | `G1-G3`; `run_detail_overview.tsx:107-355`; `EB-046`. |
| `F-SUMMARY-02` | `incorrect` | “Verified ideas” is distinct from High Potential. | Both metrics are assigned `highPotential`. | The UI makes a false verification claim. | `run_detail_overview.tsx:152-161`; `R1-R3`. |
| `F-SUMMARY-03` | `missing` | High Potential and Non-Viable groups include actual ideas and rationales. | Only counts render. | The main decision explanation is discarded. | `G3`, `G10`; `run_detail_overview.tsx`. |
| `F-SUMMARY-04` | `partial` | A concise outcome summary is useful; exact Labs placement is visual evidence only. | Idea-Generation-style sentence reports idea count, duration, top Elo and matches. | Real values are shown, but this copies the related enterprise twin and cannot establish Labs fidelity. | `run_detail_overview.tsx:362-425`; secondary reference. |
| `F-SUMMARY-05` | `partial` | Scientists should inspect the ideas behind the synthesis. | Winners render as read-only text and tournament as a count. | No navigation to the winning idea or rationale. | `run_detail_overview.tsx`. |
| `F-SPEC-01` | `incorrect` | Final tab is `Run Specifications` in current Help (`Run Specification` in older footage). | First tab is Goal Details; inner title says Run Specifications. | Name, position and default route are inconsistent with the target and with each other. | `G3`, `G10`; `run_detail_shell.tsx`, `run_detail_specifications.tsx`. |
| `F-SPEC-02` | `partial` | Report preserves the research contract. | Displays persisted challenge, focus area, preferences, title, local focus and tier. | Useful provenance works, but the local controls are themselves divergent. | specification component. |
| `F-SPEC-03` | `missing` | Labs verifies Challenge, Focus Area, Preferences and optional Title; ARCH verifies a customizable scientific rubric. | The visible tab omits parts of the verified product contract and provides no advanced provenance view for the rubric or local execution parameters. | Users cannot audit the verified specifications or the local/ARCH choices that produced rankings; those advanced fields must not masquerade as Labs-native UI. | `G1-G3`; `run_detail_specifications.tsx`, config JSON. |
| `F-SPEC-04` | `non-faithful extension` | No visible evidence places safety adjudication inside report specifications. | Run owner can approve/reject held safety decisions there. | An administrative control replaces target report content and weakens the reviewer boundary. | `run_detail_specifications.tsx`; `runs.py:690-729`. |
| `F-SPEC-05` | `non-faithful extension` | Post-run private-source upload is not verified. | Completed report accepts files but shows no durable list/status/removal and no reachable subsequent task uses them. | Copy promises future scientific use without an observable effect. | specification/upload components; attachment APIs. |

### Agent follow-up, sharing, state, and extensions

| ID | Class | Google behavior | Current working behavior | Exact gap and consequence | Evidence / locations |
|---|---|---|---|---|---|
| `F-AGENT-01` | `missing` | Open/Chat with Agent supports post-report questions and trade-offs. | `askRunQuestion` exists but has no live UI caller. | A verified core continuation is unreachable. | `G3`, `G10`; `api/runs.ts`; report component inventory. |
| `F-AGENT-02` | `incorrect` | Related enterprise session becomes read-only; Labs uses a distinct post-run Agent. | Home composer remains active after start and continues calling `addInterviewTurn` on the completed interview. | Misleading control satisfies neither product and can error. | `chat_workspace.tsx:126-139`, `hooks/chat_session_handlers.ts:75-77`. |
| `F-AGENT-03` | `missing` | Research system accepts scientist steering, ideas and reviews; current Labs placement is not documented. | Endpoints/clients exist, but no reachable frontend invokes them and backend composition has manual/steering defects. | An uncalled client/endpoint is not product behavior; expert-in-loop is absent from the reachable system. | `G1`; `api/runs.ts`, `runs.py`; `EB-002-004`, `U14`. |
| `F-SHARE-01` | `missing` | User can enable sharing and create a unique public link. | `/shared/:token` reads an existing token, but create/list/revoke clients are unused. | Users cannot initiate sharing through the product. | `G3`; `api/runs.ts`, shared route. |
| `F-SHARE-02` | `incorrect` | Shared output should be the intentionally released result. | Minimal static digest omits rich report; backend token also returns raw complete hypotheses/evidence. | Both fidelity and privacy fail: output is too thin while leaked working memory is too broad. | `G3`; shared page, `app/app/shares.py:52-68`; `EB-052`. |
| `F-EXPORT-01` | `missing` | User can download the result; exact format is undisclosed. | `reportMarkdownUrl` is unused; no report export/copy/PDF action. | Verified portability is absent; message-card downloads are not report export. | `G3`; `api/runs.ts`, report shell. |
| `F-STATE-01` | `missing` | Pre-run conversational work is part of the user's durable journey. | Active interview/plan/confirmation only live in component memory. | Reload discards the setup surface and there is no interview recovery route/list. | `chat_session_state.ts`, unused `getInterview`. |
| `F-STATE-02` | `partial` | Draft, active and past runs remain discoverable. | Once a run exists, history/detail refresh and persistence work. | Genuine durable behavior, weakened by demo mixing and hidden partial-start drafts. | `G3`; history context and runs API. |
| `F-STATE-03` | `incorrect` | Failed/cancelled/blocked work should not masquerade as a complete Goal Report. | Only active statuses get ActiveRunView; other terminal/non-start states render report tabs. | Page architecture implies completed artifacts even when none exist. | `run_detail.tsx`. |
| `F-STATE-04` | `partial` | Failures should be clear and recoverable. | Raw chat/start errors and fixed report alert appear; no report retry, silent SSE retry, ErrorBoundary exposes component stack. | Visibility exists, but recovery and user-safe error presentation are weak. | error boundary, stream hook, run-detail loader. |
| `F-STATE-05` | `non-faithful extension` | Labs end-user UI does not expose app-wide backend/browser diagnostics. | Logs pill polls, copies and clears persistent server/UI event stream. | Operator telemetry can expose goals/internals and visually dominates target chrome. | `logs_popover.tsx`, `ui_logging.ts`, `logs_api.py`. |
| `F-STATE-06` | `non-faithful extension` | Offline backend status is not a research control. | Header displays Offline mode. | Development/provider detail changes the target surface and can legitimize fixture science. | layout diagnostics/status code. |
| `F-EXT-01` | `non-faithful extension` | No target route shows a hard-coded product-critique graph. | `/proposals` renders static personal/project proposals; actual proximity API is unused. | Static content can be mistaken for scientific idea landscape behavior. | `workbench/proposals/`, unused `getProximity`. |
| `F-EXT-02` | `non-faithful extension` | General Product Feedback is under More; no team-author note is evidenced. | Feedback is SBI-only and Google mode shows an author/contact note. | Outreach features replace the verified general feedback path. | `G4`; audience/feedback components. |
| `F-EXT-03` | `unverifiable` | Direct Labs evidence does not establish this exact light/dark/system selector. | Functional three-way theme support. | It matches the secondary twin, but is neutral/negative for strict Labs fidelity. | theme context; secondary captures. |

### Responsive and accessibility behavior

| ID | Class | Google behavior | Current working behavior | Exact gap and consequence | Evidence / locations |
|---|---|---|---|---|---|
| `F-RESP-01` | `incorrect` | Supported desktop experience must fit normal desktop/Chrome. | At the required 16:9 capture, report tabs/content clip horizontally; 2:1 is coherent. | A supported desktop aspect ratio is unusable, independent of pixel styling. | `G3`; `R7/06-09` versus `R7/10`; responsive CSS. |
| `F-RESP-02` | `unverifiable` | Current public Help recommends desktop; direct mobile UI is not established. | 390×780 home/list generally fit with a bespoke mobile adaptation. | Usability exists, but mobile parity cannot be claimed. | `G3`; `R7/11-13`. |
| `F-RESP-03` | `incorrect` | Mobile detail requires discoverable return navigation. | No visible Back; user must re-tap active tab. | Core master/detail journey traps users. | `R7/12`; `ideas_tab.tsx`. |
| `F-A11Y-01` | `partial` | No exact Google accessibility implementation is public; product must remain operable. | Many native controls, labels, ARIA progress/loading states and reduced-motion paths work. | Preserve these strengths while fixing overlay, selection and navigation semantics. | component inspection. |
| `F-A11Y-02` | `incorrect` | Modal overlays should contain focus and restore it on close. | Settings/drawer support Escape but do not trap focus, inert the background or restore opener focus. | Keyboard users can move behind the overlay and lose position. | `settings_dialog.tsx:274-293,395-425`, mobile drawer. |
| `F-A11Y-03` | `incorrect` | Menus/dialogs need semantics matching their interaction. | Generic `ShellPopover` applies `role=status` to menus, logs and forms. | Large interactive regions become noisy live announcements. | `layout_primitives.tsx:18-29`. |
| `F-A11Y-04` | `incorrect` | Selected idea must be announced. | CSS selection only. | Assistive technology cannot relate list selection to detail. | Same evidence as `F-IDEAS-08`. |
| `F-A11Y-05` | `incorrect` | Return navigation must be explicit and named. | Hidden active-tab re-tap convention. | No accessible instruction or semantic control exposes the action. | Same evidence as `F-IDEAS-09`. |
| `F-A11Y-06` | `partial` | Navigation or tabs should use one coherent semantic model. | `<nav>` buttons use `aria-current=page`; no full tablist/tabpanel keyboard pattern. | Defensible as page navigation, but visual tab behavior and semantics are mixed. | `run_detail_shell.tsx`. |
| `F-A11Y-07` | `incorrect` | A Thinking indicator should not expose/announce raw private reasoning. | Continuously growing reasoning is `aria-live=polite`. | Disclosure and repeated announcements compound the interview defect. | `chat_workspace_timeline.tsx:96-127`. |
| `F-A11Y-08` | `divergent` | No public evidence of hidden global shortcuts. | `g n` and arrow navigation exist without discoverable help. | Unevidenced shortcuts may intercept expected scrolling/navigation. | `use_global_shortcuts.ts`. |

## Exhaustive engine, backend, persistence, and evaluation comparison

### Goal, scientist input, coalition, and durable state

| ID | Class | Google behavior | Current working behavior | Exact gap and consequence | Evidence / locations |
|---|---|---|---|---|---|
| `EB-001` | `partial` | Natural-language goals are refined and parsed into a configurable ResearchPlan, potentially from very large inputs. | API/interview persists four field buckets and direct create accepts setup lists/counts. | Fallback maps answers by turn order; plan depth, scale and semantic validation are not reproduced. | `G1-G3`; `app/app/interviews.py:324-363`, `runs.py:159-243`. |
| `EB-002` | `incorrect` | ARCH scientists can refine goals, directions and publications during work. | Messages queue and force a Generation boundary. | Messages are marked applied before the consuming checkpoint and cannot reallocate a worker portfolio; crash can lose acknowledged steering. | `G1`; `engine_adapter/opts.py:55-129`, `scheduling/policy.py:195-200`. |
| `EB-003` | `incorrect` | Scientist ideas enter the same tournament with preserved identity. | Manual idea is merged with `SCIENTIST_MANUAL` and same ID. | Final replay preserves the DB row then inserts it again, causing a UNIQUE collision and preventing completion. | `G1`; `engine_tasks.py:108-166`, `store/runs.py:520-621`, `engine_adapter/drain.py:157-201`; `R5`. |
| `EB-004` | `incorrect` | Scientist reviews guide work with their authorship/meaning intact. | Human review is merged, but score is reconstructed as 20/60/90 from summary words and drained again as generic `review`. | Audit identity and semantics are lost/duplicated. | `G1`; `engine_tasks.py:136-165`, `engine_adapter/drain.py:210-227`. |
| `EB-005` | `divergent` | Labs exposes Standard and Advanced; exact internal budgets are unpublished. | Four modes with clone-defined idea/iteration/match/evidence/LLM ceilings; legacy advanced maps to ultra. | Visible contract is wrong and numerical parity cannot be claimed. | `G3`; `app/app/run_modes.py:10-110`. |
| `EB-006` | `partial` | Default criteria are Alignment, Plausibility, Novelty, Testability and Safety, with customization. | Several prompts cover overlapping qualities; run defaults emphasize soundness, novelty, design and feasibility. | No canonical five-criterion rubric governs every review/ranking/evolution decision. | `G1-G2`; `run_modes.py:28-43`, prompt templates. |
| `EB-007` | `divergent` | Continuously running asynchronous specialists consume Supervisor-managed tasks. | Fixed serial bootstrap followed by one selected successor; app only fans out items inside phases. | The defining coalition execution model is absent. | `G1`, `G7`; `generator/graph.py:125-180`, `task_runtime.py:78-121`. |
| `EB-008` | `divergent` | Supervisor plans, allocates resources, monitors statistics and terminates. | Initial Supervisor writes guidance; prompt states execution is fixed and it is “NOT to plan the workflow execution.” | The published role is deliberately replaced by static topology and single-task routing. | `G1-G2`; `prompts/templates/supervisor.md:7-57`. |
| `EB-009` | `partial` | Supervisor adaptively weights/samples work from live effectiveness and backlog. | Heuristic policy considers budgets, coverage, convergence, backlog, steering and coarse generation/evolution yield. | Returns one enum, not allocations; retry state is not normally populated and yields are coarse. | `scheduling/policy.py`. |
| `EB-010` | `partial` | Specialists run asynchronously with flexible compute. | Concurrency bound, several `gather` paths and app ranking waves of five work. | Bounds/failure isolation vary, some batches abort wholesale, library ranking is serial and phases cannot overlap. | generation/reflection/ranking code; `constants.py:85-89`, `engine_tasks.py:1652-1800`. |
| `EB-011` | `partial` | More test-time compute improves internal Elo in the measured range; exact termination is private. | Configurable iterations, pool/coverage/convergence and LLM ceilings. | Defaults are small, accounting is false/incomplete and no controlled scaling curve proves behavior. | `G1-G2`; `constants.py:91-105`, `generator/core.py`; `EB-061,065`. |
| `EB-012` | `incorrect` | A long-running reusable system must reflect current capabilities/configuration. | Public generator caches compiled graph and MCP availability. | Config/tool availability changes do not invalidate topology, silently executing a stale graph. | `generator/core.py:185-195`. |
| `EB-013` | `partial` | Persistent context/checkpoints support restart. | Rich state, versioned checkpoints, append-only events, leases and latest-successor resume work per run. | Per-run restart concept matches; Google's exact queue/checkpoint implementation and any cross-run scientific memory remain unresolved under `U06` and `U16`. | `G1-G2`; `state.py`, `checkpoint.py`, `app/app/store/`; `U06`, `U16`. |
| `EB-014` | `non-faithful extension` | Exact Google queue/lease/database implementation is proprietary. | SQLite leases, heartbeats, idempotency, dependency/priority, pause/cancel/retry and CAS checkpoints. | Valuable infrastructure receives no 1:1 credit and must be judged only for correctness. | `app/app/store/tasks.py`, `task_worker.py`. |
| `EB-015` | `incorrect` | Terminally exhausted work must settle the run. | Worker marks task failed and logs it. | Run status remains `running` with no ready successor, stranding API/SSE/CLI forever. | `task_worker.py:245-265`; direct reproduction `R6`. |
| `EB-016` | `incorrect` | Human safety review must approve/reject and resume/settle durably. | Intake/final holds pause and record decisions; owner can adjudicate. | Holding task is already succeeded; approval reuses completed idempotency key or has no resumable task. | `engine_tasks.py:680-703`, `store/tasks.py:493-549`; `R6`. |
| `EB-017` | `incorrect` | Acknowledged steering must survive restart exactly once. | Message is applied while options are built. | Applied flag and consuming successor checkpoint are not transactional. | Same locations as `EB-002`. |
| `EB-018` | `incorrect` | Durable relationships must remain internally consistent. | Tables declare foreign keys and replay explicitly deletes children. | `PRAGMA foreign_keys=ON` runs only during initialization, not ordinary connections; orphan state can be accepted. | `app/app/store/db.py`, acknowledgement in `store/runs.py:577-581`. |

### Generation, retrieval, evidence, and release grounding

| ID | Class | Google behavior | Current working behavior | Exact gap and consequence | Evidence / locations |
|---|---|---|---|---|---|
| `EB-019` | `partial` | Generation combines literature, debate, assumptions and feedback to explore distinct ideas. | Coordinator allocates literature-tool, debate and assumption strategies; prompts receive prior ideas, guidance and meta context. | Fixed heuristics replace Supervisor allocation; one exception can abort a batch and one general model supplies every role. | `G1-G2`; `agents/generation/coordinator.py` and strategy modules. |
| `EB-020` | `partial` | Multi-turn scientific debate contributes hypotheses. | Up to five same-model self-dialogue turns execute in parallel. | Reconstructed protocol and same-model roles do not establish independent expert-agent behavior. | `G1-G2`; `agents/generation/debate.py`. |
| `EB-021` | `partial` | Generation iteratively expands assumptions and sub-assumptions. | One structured assumptions generation call. | No persisted iterative assumption tree or repeated expansion loop. | `G1`; assumptions strategy/prompt. |
| `EB-022` | `unverifiable` | Outputs should be scientifically novel, plausible, testable and useful, with human validation. | Structured hypotheses, experiments, reviews, Elo and reports exist. | Code shape/offline fixtures cannot prove scientific-quality parity; no representative blinded comparison exists. | `G1-G2`, `G6`; engine schemas, missing expert artifacts. |
| `EB-023` | `partial` | Web, scientific databases, private repositories and specialized tools can ground work. | MCP/config supports PubMed, OpenAlex, ChEMBL, UniProt, optional web/private paper and URL reading. | No shipped AlphaFold integration; MCP loss falls back to LLM-only and source breadth is narrower. | `G1`, `G7`; `engine/src/co_scientist/config/tools.yaml`, literature-review package. |
| `EB-024` | `divergent` | Exact Google ranking is private, but a credible stack must select goal-relevant science. | Metadata source/citation/recency score, exact-title dedup and keyword selection. | No query-semantic term, vector/hybrid retriever, scientific entity resolution or learned reranking; irrelevant recent/high-citation work can win. | retrieval/search support and `app/app/run_corpus.py`. |
| `EB-025` | `partial` | ARCH accepts very large private, multimodal inputs. | PDF/text/image upload, extraction/OCR, hash/provenance and bounded prompt selection (max 20 docs, about 6,000 chars each). | No vector index or model inspection of figures/tables; no hundreds-of-PDF/tens-of-thousands-token demonstrated behavior. | `G1`; `document_ingest.py`, `run_corpus.py`. |
| `EB-026` | `incorrect` | Scientific evidence must not treat retracted work as valid grounding. | Retrieval score penalizes retractions; later review filters some. | Reserved/underfilled selection still chooses them; analysis marks them used and synthesis can consume them. | `literature_review/search_support.py:313-470`, `article_support.py:152-224`, `analysis.py:88-118`. |
| `EB-027` | `partial` | Clickable references must be traceable and independently checked. | `[P#]/[KG#]` keys resolve to source metadata and citation classifier states. | Syntactic source mapping is not identity/reachability/claim entailment; no canonical DOI resolver. | `G3`, `G6`; generation citation code, `app/app/citations.py`. |
| `EB-028` | `partial` | Claims should be grounded with visible uncertainty and contradiction. | Sentence claims, lexical passage retrieval, optional semantic classifier, quote validation, contradiction rows and deterministic fallback. | Claims are not atomized; top-five lexical retrieval is brittle; fallback scored 0.17 accuracy/0 contradiction recall on the synthetic challenge. | claim grounding/evaluations; `evaluations/README.md`. |
| `EB-029` | `incorrect` | Unsafe/unsupported candidates must be excluded before ranking, development and user output. | Claim gate writes blocking decisions and omits blocked IDs from immediate ranking. | It never changes canonical hypothesis state; final filter ignores claim-gate decisions and republishes the idea. | `G1-G2`; `claim_grounding.py:280-336`, `report_render.py:316-385`; `R1-R3`. |
| `EB-030` | `incorrect` | Knowledge Base references should resolve to actual stored evidence. | Helper intends to attach evidence IDs from claim edges. | Reads nonexistent edge-level `evidence_id`; stored IDs live inside supporting/contradicting passage arrays, so links are usually empty. | `app/app/report_render.py:46-60`, claim-evidence schema. |
| `EB-031` | `incorrect` | Contradiction insights should identify the contradicted claim and source. | `_agent_insights` attempts a contradiction summary. | Reads nonexistent `claim_text`/`claim_id` instead of persisted `claim`, producing blank/untraceable content. | `report_render.py:128-148`. |
| `EB-032` | `partial` | Post-run Agent should discuss ideas/trade-offs grounded in the run. | Streaming Q&A includes top hypotheses, recent reviews/matches/messages and about 12 evidence titles/states. | It omits evidence passages yet requests citations; unsupported sources enter context, and offline answer ignores the question. | `G3`; `app/app/qa.py:308-359`. |

### Reflection, ranking, proximity, evolution, meta-review, and safety

| ID | Class | Google behavior | Current working behavior | Exact gap and consequence | Evidence / locations |
|---|---|---|---|---|---|
| `EB-033` | `partial` | Reflection includes initial, full grounded, deep verification, observation, simulation, recurrent and manual review. | Executable paths exist for each named concept and some use targeted retrieval. | Prompts/protocols are reconstructed and downstream enforcement is inconsistent. | `G1-G2`; `engine/src/co_scientist/agents/reflection/`. |
| `EB-034` | `incorrect` | Early review should gate unsound/unoriginal candidates reliably. | Soundness/novelty <=3 sets blocking disposition. | Schema has no 1..5 bounds, batch association depends on order and one exception can abort a large batch. | `agents/reflection/review.py:58-74`, `schemas/review.py:28-33`. |
| `EB-035` | `incorrect` | Material full/simulation/recurrent findings must affect further development/release. | Mature reviews are stored in enrichments. | Even fatal mature findings do not change disposition, score or rankability; advisory text can be ignored by tournament/report. | `comprehensive_reflection.py:205-236`. |
| `EB-036` | `incorrect` | Deep verification probes assumptions and should gate undermined/unverified ideas. | Top three receive questions/retrieval/verdict; `undermined` blocks. | It runs before first ranking (all Elo ties) and provider failure fails open, leaving idea rankable. | `deep_verification.py:208-278`, `generator/graph.py:145-148`. |
| `EB-037` | `partial` | Pairwise tournament initializes ideas at Elo 1200 and updates ratings. | Canonical logistic update, winner/loser history and fresh evolved-child rating work. | K=24, debate turns, tie policy, top rule and schedules are local; all first-round ties take expensive path. | `G1-G2`; ranking package, `constants.py:32-41`. |
| `EB-038` | `partial` | Matchmaking prioritizes similar, new and leading ideas. | Mixes leaders/new ideas and cluster IDs with deterministic weighting. | Similarity uses coarse cluster ID, not weighted graph; exact Google weights are unknown. | `G1-G2`; ranking matchmaking; `EB-040`. |
| `EB-039` | `partial` | Ranking can run asynchronously within resource bounds. | App performs stable waves of five; public library loops sequentially despite semaphore. | Two entry points have materially different latency/failure semantics and neither overlaps specialists. | `agents/ranking/ranking.py:421-505`, `engine_tasks.py:1652-1800`. |
| `EB-040` | `incorrect` | Proximity creates a weighted goal-conditioned similarity graph used for diversity/dedup/matchmaking. | Prompt/schema emits `{index, similarity_degree}`, but graph resolver reads `member.text`. | Every live-shape member fails resolution, producing an empty graph; tests use the obsolete text fixture. | `G1-G2`; `schemas/ranking.py:92-110`, `proximity_graph.py:66-82`; `R4`. |
| `EB-041` | `partial` | Evolution includes grounding, feasibility, inspiration, combination, simplification and out-of-box strategies. | Enhancement, simplification, combination, analogy and out-of-box operators. | Similar repertoire, but named strategies/protocol are not the disclosed set and exact behavior is local. | `G1-G2`; `evolution_operators.py`. |
| `EB-042` | `matched` | Evolved ideas are immutable new descendants; parents remain. | New ID, parent ID, generation/history and fresh 1200/zero matches; parent retained. | Core invariant matches; final drain may drop parent edge if parent was pruned. | `G1-G2`; `evolve_results.py:50-96`, `engine_adapter/drain.py:163-186`. |
| `EB-043` | `incorrect` | Evolution should preserve diversity and resiliently create descendants. | Selects top Elo plus Jaccard diversity and multiple operators. | Diversity is only within selected top-k, randomness unseeded, one provider failure aborts node and no durable per-child fan-out exists. | evolution package. |
| `EB-044` | `partial` | Meta-review synthesizes recurring patterns from reviews/debates, not individual re-review. | Receives full review histories/debate transcripts and strategic model prompt. | Real mechanism exists, but prompt/quality parity is unvalidated. | `G1-G2`; meta-review package. |
| `EB-045` | `partial` | Meta-review feedback is appended to all applicable agents in later work. | Generation, review, ranking, evolution and deep verification receive context. | Literature, proximity, safety and Supervisor do not, so “all agents” invariant is incomplete. | `G1`; context builders across agents. |
| `EB-046` | `incorrect` | Final overview must synthesize only releasable candidate science. | Sorts all hypotheses by Elo and sends top ten to overview LLM. | Does not filter review disposition, deep verdict, claim/safety gates or `is_rankable`; rejected content contaminates published prose. | `research_overview.py:71-88`, report path. |
| `EB-047` | `partial` | Meta-review examples can suggest expert contacts grounded in sources. | Candidates come from authors of used evidence and IDs validate to candidates. | Identity/contact resolution is weak and “used” sources can include retractions. | `G1-G2`; research overview/contact helpers; `EB-026`. |
| `EB-048` | `partial` | Intake and final output receive layered safety review with human oversight. | Regex policy plus contextual escalation for real-backed runs, persisted decisions and hold/block states. | Offline skips semantic escalation; rules are narrow and approval continuation is broken. | `G1-G2`; `app/app/safety.py:260-348`; `EB-016`. |
| `EB-049` | `partial` | Every candidate is screened and unsafe ideas stay out of tournament/development/output. | Engine regex classifier records status and blocks prohibited/ethical/uncertain items from ranking/report. | Non-null status prevents re-screening after context changes; candidate screen is not contextual and whole-output semantic gate is too late. | `G1-G2`; `agents/safety/safety_screen.py`. |
| `EB-050` | `incorrect` | A redaction decision must remove/replace sensitive content before persistence/output. | Safety can return and store `redact`. | Gate proceeds with the same goal/report Markdown; label has no transformation effect. | `app/app/safety.py:278-348`, `report_render.py:526-588`. |
| `EB-051` | `missing` | Meta-review continuously monitors safety and alerts Supervisor. | Safety is a separate fixed phase. | No meta-review safety alert feeds planning/resource allocation. | `G1-G2`; meta-review/scheduler inspection. |
| `EB-052` | `incorrect` | Labs public sharing must expose only the intentionally released report. | Hashed revocable token returns report plus raw full hypothesis and evidence tables. | Bypasses publishability and can leak blocked ideas, private document text and recipient/run config. | `G3`; `app/app/shares.py:52-68`. |
| `EB-053` | `incorrect` | Google auth internals are unknown; limited access and tenant privacy are verified expectations. | Optional invite/bearer auth; default compatibility trusts caller-selected `X-Client-ID`, absent header is shared empty subject, CORS defaults `*` with credentials. | Default identity is spoofable and production privacy depends on non-default deployment configuration. | `G3`; `config.py:115-121`, `auth.py:100-129`, `main.py:280-292`. |

### Reports, API/CLI, observability, metrics, and evaluation

| ID | Class | Google behavior | Current working behavior | Exact gap and consequence | Evidence / locations |
|---|---|---|---|---|---|
| `EB-054` | `partial` | Goal Report contains Ideas, Knowledge Base, Summary and Run Specifications. | Durable JSON/Markdown includes summary, filtered leaderboard, citations, KB, overview, meta-review, buckets, insights and timing. | Rich payload exists, but release/shape helpers are wrong and output quality/contract is unvalidated. | `G3`; `app/app/report_render.py`; `EB-029-031,046`. |
| `EB-055` | `non-faithful extension` | Exact Google HTTP API is proprietary. | Broad lifecycle, artifact, safety, message, interview, share, auth and log API is live. | Route breadth is valuable local infrastructure, not parity, and several composition paths are broken. | `app/app/runs.py`, other routers. |
| `EB-056` | `non-faithful extension` | No public Google operator CLI is established. | `cosci` handles lifecycle, SSE reconnect, reads, steering/Q&A and logs. | Local control plane omits interview/manual input/attachments/share/adjudication and receives no fidelity credit. | `app/app/cli/`. |
| `EB-057` | `non-faithful extension` | Google product does not use deterministic pseudo-science fixtures. | Offline backend intercepts model calls and emits phrase-bank/schema fillers; startup seeds three curated demo goals. | Useful test/demo system proves navigation only and must never count as scientific capability. | `engine/offline_llm.py`, `app/app/seed.py`. |
| `EB-058` | `divergent` | Published system uses Gemini-family/proprietary infrastructure; exact current routing is private. | LiteLLM with arbitrary general/supervisor/chat models; production docs configure DeepSeek. | Model capabilities, hidden prompts, context, safety and tool policy differ fundamentally. | `G1`, `G7`; `llm.py`, settings/deployment docs. |
| `EB-059` | `non-faithful extension` | ARCH cites complete internal logging, not a public raw-log product. | Durable queue-based root/uvicorn/frontend log with run IDs, caps, filters and CLI follow. | Strong operations but compact/noise-filtered rows are not a complete scientific trace and user-facing exposure is divergent. | `G1-G2`; `logging_setup.py`, `logs_api.py`. |
| `EB-060` | `missing` | Access-controlled reasoning/tool trace supports safety audit; raw chain-of-thought need not be shown to users. | Some prompts, cached responses, debates/reviews/checkpoints persist; interview reasoning streams but is not persisted. | No normalized complete per-run prompt/response/tool/evidence audit, while the wrong portion is exposed publicly. | `G1-G2`; prompt save/cache code; `F-INTERVIEW-03`. |
| `EB-061` | `incorrect` | Supervisor resource allocation/test-time scaling depends on truthful compute/statistics. | Metrics include total/phase time and selected counts/calls. | Literature, reflection, Supervisor and multiple generation calls are omitted; no tokens/cost/tool latency/errors/cache/yield, so LLM budget uses a false denominator. | `models.py:324-336`, node accounting. |
| `EB-062` | `incorrect` | Progress should remain honest across adaptive cycles. | Fixed phase percentages emit events. | Deep verification reports 81-84 then Proximity can report 75-85; loops revisit fixed values, so progress moves backward. | `constants.py:124-148`. |
| `EB-063` | `incorrect` | Reproducible scientific work must identify/freshen model/tool/prompt/source state. | Response/node caches default on and checkpoints version state. | No TTL/robust model-prompt-tool-source version invalidation; pickle trust and unseeded evolution risk stale/non-reproducible results. | `cache.py`, evolution sampling. |
| `EB-064` | `missing` | Published evaluation calibrates Elo against known-answer correctness. | No GPQA-equivalent data/result. | Internal Elo has no demonstrated objective-correctness calibration. | `G1-G2`; `evaluations/README.md`. |
| `EB-065` | `missing` | Published 203-goal compute study shows improving Elo in the measured range. | Scaling evaluator can consume a supplied artifact. | No controlled representative dataset/result exists; adjustable budgets do not prove scaling. | `G1-G2`; `evaluations/scaling_eval.py`, README. |
| `EB-066` | `missing` | Published work includes small blinded expert studies; real quality needs expert review. | Export/import and inter-rater statistics code exists. | No recruited/rated panel artifact. | `G1`; evaluation code/README. |
| `EB-067` | `partial` | Google reports 1,200 adversarial goals across 40 topics plus >2,000 safe goals. | 13-item handcrafted synthetic safety dataset scores its aligned rules. | Scale/diversity and independent robustness evidence are absent. | `G2`; safety evaluation dataset/results. |
| `EB-068` | `partial` | Citation evaluation should measure support, contradiction, abstention and provenance on representative data. | 20 lexical and 30 synthetic semantic items; one stored provider result 0.90 accuracy/1.00 contradiction recall. | Small unaudited synthetic panels and deterministic collapse do not establish scientific citation performance. | claim-grounding evaluation/README. |
| `EB-069` | `missing` | Published claims include selected wet-lab/case validation with explicit limitations. | No reproduced fibrosis/AMR/other experimental study. | Real discovery impact is external and unproven; offline/golden fixtures cannot close it. | `G1`, partner papers; evaluations README. |
| `EB-070` | `incorrect` | A fidelity ledger should close only with executable supporting evidence. | `docs/PARITY.md` marks rows verified and checker validates reference names. | Three cited test symbols do not exist; evaluation truth gate fails two tests and does not prove semantic behavior. | `evaluations/tests`, `docs/PARITY.md`. |

## Exhaustive product operations, privacy, packaging, documentation, and deployment comparison

| ID | Class | Google behavior or fidelity obligation | Current working behavior | Exact gap and consequence | Evidence / locations |
|---|---|---|---|---|---|
| `OP-001` | `incorrect` | Labs access is invitation-limited and research data must be tenant-isolated. | Invite/bearer mode exists, but default `compatibility` mode trusts a caller-selected client ID. | The default running product is spoofable and no-header callers share one subject; access UI does not establish privacy. | `G3`; `app/app/config.py:115-121`, `auth.py:100-129`. |
| `OP-002` | `incorrect` | One account may run at most three Standard and one Advanced run concurrently. | Backend uses one configurable aggregate `max_concurrent_runs` ceiling across local tiers. | Verified per-mode availability/queueing contract is not implemented. | `G3`; settings/run reservation code. |
| `OP-003` | `partial` | Failed Labs runs have a documented Failed state, possible credit refund/support path and sometimes delayed status synchronization. | Durable terminal failed status/error and failed-run rendering exist; no credit ledger/refund, support path or status-delay guidance exists. | The core state is implemented, but recovery messaging differs. Google's credit mechanics are unknown and must not be invented; the local no-credit adaptation must be explicit. | `G3`; run lifecycle/store/frontend errors; `U22`. |
| `OP-004` | `partial` | Completion report is emailed. | SMTP-capable notification task and a local custom-recipient checkbox exist. | No audited configured delivery/retry/dead-letter/user-visible failure/de-duplication path; checkbox/recipient choice is local, and exact production delivery behavior is unproven. | `G3`; `app/app/notifications.py`, config/tests. |
| `OP-005` | `missing` | User can open the completed output in NotebookLM. | No component, client or handoff route. | A verified top-level report continuation is absent. | `G3`; repository search; E2E expectation. |
| `OP-006` | `missing` | User can download the result; public evidence does not specify format. | Markdown report endpoint exists, but shipped UI has no action. | Backend-only URL is not reachable behavior; do not substitute invented format matrices. | `G3`; report route, unused `reportMarkdownUrl`. |
| `OP-007` | `incorrect` | More -> Product Feedback supports optional screenshot and warns that feedback/context may be human reviewed. | SBI/UCD pilot form persists local DB feedback; General audience receives no target flow. | Wrong audience/placement/privacy notice and no demonstrated Google delivery. | `G4`; audience feedback components, `app/app/feedback.py`. |
| `OP-008` | `missing` | Runs can be permanently deleted, including ideas, literature reviews and summaries. | No run/report/document deletion API or reachable UI; only logs/share revocation have delete behavior. | Users cannot exercise a verified data-lifecycle right; private artifacts, attachments and derived output persist. | `G5`; router/store search. |
| `OP-009` | `missing` | User can request all or date-ranged data; Google usually provides JSON/PDF within its stated process. | No account/run archive request/export workflow. | Product does not reproduce the documented data-access path; exact Google back-office process need not be cloned, but an adaptation must be explicit. | `G5`; repository search. |
| `OP-010` | `incorrect` | Declared runtime dependencies must be installed by the supported setup path. | App declares `pypdf` and `python-multipart`; root setup/CI composite install app `--no-deps` then an incomplete manual subset. | Fresh setup fails `pip check` for `pypdf` and cannot guarantee upload parsing despite “setup” succeeding. | root `Makefile:41-52`, `.github/actions/setup-backend/action.yml:19-28`, `app/pyproject.toml:11-24`; local setup. |
| `OP-011` | `incorrect` | Exposed PDF/image ingestion must work in shipped development/production images. | Tests fake `pypdf`; API Dockerfiles do not install Tesseract. | Gates miss the missing package, and image OCR cannot work in the container. | `app/tests/test_document_upload.py:51-85`, `Dockerfile.api`, `app/Dockerfile*`. |
| `OP-012` | `incorrect` | Supported setup should write configuration where the app reads it. | Root setup writes root `.env`; `make dev-api` changes to `app/`, whose settings loads cwd `.env`. | Setup-generated provider/tool configuration can be silently ignored. | root `Makefile`, `app/app/config.py`; developer workflow. |
| `OP-013` | `incorrect` | Forced offline mode should not contact an external provider. | Engine model calls are offline, but interview first attempts configured remote chat model and falls back after error/timeout. | “Offline” can leak goal text, incur latency, or surprise operators. | `app/app/interviews.py:242-321`, offline settings. |
| `OP-014` | `incorrect` | Demonstrations must be isolated/read-only/labeled, not treated as owned scientific history. | Startup always seeds three phrase-bank demos; ownership middleware exempts demo runs from ownership checks. | Any caller can see and potentially mutate shared demos, while the UI blends them with personal history. | `engine/offline_llm.py`, `app/app/seed.py:19-42`, `main.py:247-249,320-323`; `F-ENTRY-06`. |
| `OP-015` | `incorrect` | An aggregate verification command should mean what its name/documentation says. | `make test-all` runs engine/app only. | Frontend, E2E, MCP, evaluation smoke, lint, typecheck, build and packaging are excluded, so “all” can pass with major surfaces broken. | root `Makefile`. |
| `OP-016` | `incorrect` | CI should rerun substantive gates when deploy/build/config sources change. | Path filters omit root Makefiles/Dockerfiles, Vercel config, docs and corpus from relevant jobs. | Release-affecting changes can merge without exercising the system they alter. | `.github/workflows/`, composite actions. |
| `OP-017` | `missing` | Deployable artifacts should be built/smoked before release. | No CI Docker build, compose smoke, Vercel/Railway deployment verification or migration-on-volume gate. | Packaging/runtime drift such as missing OCR/dependencies can reach production undetected. | CI workflow inventory, Dockerfiles, deployment docs. |
| `OP-018` | `incorrect` | E2E acceptance should describe the same reachable product as unit tests/current code. | Unit test asserts NotebookLM/Download controls are absent; E2E requires NotebookLM, Download, Open Agent and Share. | Test contracts contradict HEAD and cannot jointly pass, so neither is a reliable closure oracle. | `run_detail.test.tsx:143-144`, `e2e/tests/06_visual_acceptance.spec.ts`, `07_report_controls.spec.ts`. |
| `OP-019` | `incorrect` | Documentation must describe current working behavior and evidence boundaries. | README/app README describe retired tabs/controls; `docs/FIDELITY.md` claims implemented auth/uploads/durable workers are absent and retains obsolete defaults/grounding. | Stale docs can misdirect implementation and falsely support or deny fidelity. | README files, `docs/FIDELITY.md`, current source. |
| `OP-020` | `incorrect` | A parity truth gate must prove cited behavior. | `docs/PARITY.md` has 64 rows; checker mostly verifies file/test names exist and its own tests intentionally narrow scope. | Undefined symbols make the gate red, and existing names would still not prove live semantics. | `docs/PARITY.md`, `evaluations/tests`, `EB-070`. |
| `OP-021` | `partial` | Evaluation should use representative, independently meaningful evidence. | Eval smoke can pass synthetic safety/citation fixtures. | Fixture-aligned results are regression checks, not Google-scale safety/citation/scientific fidelity. | evaluation datasets/results; `EB-064-069`. |
| `OP-022` | `missing` | A release claim needs one real end-to-end scientific journey. | Separate unit paths, offline browser runs and dormant endpoints were exercised. | No current durable interview -> grounded real-provider/tool run -> safe report -> Agent -> share/download -> delete journey exists or passes. | Whole-repository/runtime trace; external validations remain open. |
| `OP-023` | `incorrect` | Core concurrency tests should be deterministic under supported CI load. | App full run failed three 10-second subprocess lease tests; focused runs alternately passed all 15 and failed the same three. Frontend had one 5-second layout timeout. | Fixed timing thresholds make the green/red signal load-dependent. | audit verification table; `app/tests/test_task_queue.py`, proposals layout test. |
| `OP-024` | `incorrect` | Public release, Q&A, export, notification and sharing must consume one sanitized artifact contract. | Each path assembles/returns its own payload; share includes raw tables, overview predates filtering and UI fabricates KB/verified values. | Scientific truth and privacy differ by channel; blocking in one path does not prevent another from publishing it. | `EB-029-032,046,050,052`; `F-KB-02`, `F-SUMMARY-02`, `F-SHARE-02`. |
| `OP-025` | `missing` | Data deletion/retention should cover every derivative consistently. | No retention policy or cascade workflow across events, tasks, checkpoints, reports, attachments, shares, logs, caches and notification data. | Even a future row delete could leave sensitive derivatives; migration and erasure semantics are unspecified. | `G5`; store/schema/router inventory. |
| `OP-026` | `unverifiable` | Production deployment must actually enforce the intended provider, auth, CORS, MCP, persistence, SMTP and secrets boundary. | Deployment manifests/docs exist for Vercel/Railway, but this audit did not mutate or smoke production. | Production fidelity/security remains unverified; local code/config cannot be treated as deployed behavior. | `Dockerfile.api`, `Dockerfile.mcp`, `vercel.json`, production docs. |
| `OP-027` | `incorrect` | Environment templates should enumerate current security/provider/worker/tool settings accurately. | Root template describes retired Mock Mode/old model and omits most current settings; app template omits auth, SMTP, quota and worker controls. | Operators cannot discover or safely configure deployed behavior. | root `.env.example:1-45`, `app/.env.example`, `app/app/config.py`. |
| `OP-028` | `incorrect` | A declared separately installable MCP package must import/start outside its source cwd. | Editable install succeeds but setuptools discovers no package; Make/CI change cwd to `engine` to shadow the defect. | Tests/development validate repository path leakage, not deployable package behavior. | `engine/mcp_server/pyproject.toml:38-43`, root `Makefile:148-167`, CI; out-of-tree reproduction. |
| `OP-029` | `incorrect` | Reproducible scientific artifacts require reproducible builds. | Floating Python base tags, broad unpinned ranges, mutable major Action tags and non-frozen Bun install outside CI. | Identical source can resolve different images/dependencies, invalidating historical provenance. | root Dockerfiles, pyprojects, `vercel.json`, `Makefile`, CI. |
| `OP-030` | `incorrect` | A supported all-services path should preserve runs and expose the configured domain safely. | Dev Compose lacks explicit SQLite volume/path, clones/installs mutable engine at startup, uses reload, host-publishes MCP and hard-codes cancer tools. | Container replacement can lose state; behavior depends on mutable inputs and one domain; MCP is unnecessarily exposed. | `app/docker-compose.yml`, `app/docker/entrypoint.sh`. |
| `OP-031` | `incorrect` | Scientific tool service should be authenticated/authorized/rate-limited at any untrusted boundary. | MCP allows wildcard origins/headers/methods with credentials and no auth, relying on a trusted network; dev publishes port 8888. | Host-network callers can consume external quotas/resources; URL guards are not tenancy. | `engine/mcp_server/server.py:144-154`, app Compose. |
| `OP-032` | `incorrect` | Documented Compose healthcheck must match a real endpoint. | Engine Compose probes `/health`; server defines `/` plus MCP mount and requires an absent local `.env`. | Healthy MCP is marked unhealthy and the clean documented Compose route does not configure. | `engine/docker-compose.yml`, `engine/mcp_server/server.py:157-188`; `docker compose config` reproduction. |
| `OP-033` | `incorrect` | Production images should declare health/persistence and least privilege. | API/MCP run as root; API lacks `HEALTHCHECK` and explicit persistent paths; base images are unpinned. | Platform must silently supply essential behavior and container compromise has excess privilege. | `Dockerfile.api`, `Dockerfile.mcp`. |
| `OP-034` | `partial` | Long scientific tasks need an explicit monitored worker topology. | API embeds the worker by default; code comments recommend separate production worker, but deployed docs list only API+MCP. | API restarts/contention can interrupt work; replica/worker/volume reality is unverified. | `app/app/runs.py:360-373`, production docs, unavailable Railway control plane. |
| `OP-035` | `divergent` | Exact Google storage is unknown, but the chosen topology must meet its own durability/concurrency claims. | SQLite WAL/NORMAL with one writer and up to eight workers/run; comments note lock saturation and foreign keys are init-only. | Multi-replica/worker support is undefined and recent commits may be lost on OS/power failure; not all state is reconstructible. | `config.py:86-100`, `store/db.py:62-165`, `store/runs.py`. |
| `OP-036` | `incorrect` | Documentation should disclose actual registered tool surface and boundaries. | MCP registers PubMed/OpenAlex/private/web/read_url/ChEMBL/UniProt/INDRA-related tools, while package docs describe a narrower surface. | Operators cannot reason about data egress, credentials, quotas or scientific reach. | `engine/mcp_server/server.py:88-113`, MCP README/pyproject. |
| `OP-037` | `partial` | Registered and engine-authorized tools must not be conflated. | Production `/status` reported MCP/PubMed/literature/web up but `tools_config=null`, `enabled_tools=null`. | Specialized registered tools are not authorized in live engine runs; tool-rich local artifacts are not production proof. | Read-only production `/status` on audit date; `docs/PARITY.md`. |
| `OP-038` | `incorrect` | Diagnostics should be operator-scoped and data-minimized. | Public MCP/API status/root/OpenAPI reveal internal hostname, models, provider-key presence, tool names/config and external-provider details. | Unauthenticated infrastructure/capability enumeration increases attack surface and is not Labs UI behavior. | `engine/mcp_server/server.py:157-181`, API status routes. |
| `OP-039` | `partial` | Release gates should include real provider/tool contract tests. | MCP CI uses fake HTTP clients; root `test-all` omits MCP; no live PubMed/OpenAlex/INDRA/rate-limit/deployed contract smoke. | External API drift is found only manually or in production. | CI MCP job, `docs/CI.md`, root `Makefile`. |
| `OP-040` | `incorrect` | One authoritative edge config should provide current routing and basic browser security headers. | Root Vercel config is a universal rewrite; stale frontend config includes removed demo routes/noindex/fallback. Production response lacked CSP, nosniff, referrer and permissions policies. | Root-directory/config discovery can silently change behavior; localStorage secret exposure is worsened. | `vercel.json`, `app/frontend/vercel.json`; read-only public response headers. |
| `OP-041` | `incorrect` | Fixture/offline science must obey the same release-readiness boundary if shown as a report. | Seed uses Express/no literature/phrase bank, and finalizer exempts offline runs from empty-leaderboard scientific-readiness blocking. | Demos are not only fabricated; they pass a weaker publication condition, teaching/validating the wrong release behavior. | `app/app/seed.py`, `engine/offline_llm.py`, `report_render.py:556-568`. |
| `OP-042` | `incorrect` | Browser acceptance should cover required viewports without mutating source evidence. | E2E has one desktop Chromium project, uses offline phrase-bank science and writes screenshots directly into tracked `docs/assets`. | It neither tests required mobile/16:9 behavior nor preserves audit artifacts; running tests can overwrite evidence. | `e2e/playwright.config.ts`, `e2e/tests/06_visual_acceptance.spec.ts`. |
| `OP-043` | `incorrect` | Evaluation artifacts need source/environment/model/tool/prompt/seed/cost/raw-trace provenance. | Golden run reads a secret from an absolute developer path, monkeypatches MCP counters and stores aggregates without SHA/lock/image/prompt/seed/cost; old paths are stale. | Historical JSON cannot be reproduced or establish HEAD behavior. | `evaluations/golden_run.py`, `evaluations/results/golden-run-indra-2026-07-12.json`, `real_engine_baseline.json`. |
| `OP-044` | `incorrect` | Current recovery claims require a current controlled run. | Dated recovery report says scenarios pass; the same first three tests fail in one current aggregate and focused run while another focused run passed. | Historical success cannot waive present load sensitivity; current status is not deterministically green. | `evaluations/results/failure-recovery-2026-07-14.md`, current test ledger. |
| `OP-045` | `incorrect` | An evaluation release gate must be wired to the production finalizer to prove production semantics. | `scientific_release_gate` exists only under evaluation code/tests; live finalization uses different rules. | Passing evaluator tests does not prove live publication enforcement. | `evaluations/release_gate.py`, `app/app/report_render.py:539-615`. |
| `OP-046` | `incorrect` | Bearer credentials should not appear in URLs. | Backend accepts `access_token` query parameter; frontend appends it to direct download/SSE URLs. | Tokens can leak through history, copied URLs, screenshots, proxy/access logs and referrers. | `app/app/auth.py:100-108`, `app/frontend/src/api/runs.ts:84-94`. |
| `OP-047` | `incorrect` | Private uploads need type/signature validation, malware/quarantine controls, provider disclosure and deletion/retention. | Caller-supplied MIME, up to 25 MB parsing/OCR, SHA/provenance and consent-to-index; no signature/malware/archive policy, per-doc delete or at-rest encryption. | Researchers cannot know/control which provider receives text or how to remove it; malicious files and long-lived plaintext are risks. | `document_ingest.py`, `runs.py:946-1003`, `run_corpus.py:133-169`. |
| `OP-048` | `incorrect` | Feedback flow needs privacy notice, optional screenshot, operational ownership and lifecycle. | API stores client ID/audience/category/message/time and echoes it; deliberately no read/admin/triage, screenshot, retention or deletion path. | Sensitive research/personal data enters a write-only sink with no accountable process. | `G4`; `app/app/feedback.py`, `store/feedback.py`. |
| `OP-049` | `incorrect` | Ingestion limits must be tied to verified identity and work across replicas. | In-process per-scope log rate map never evicts; compatibility IDs are caller-controlled; up to 50 rows/request. | Rotating IDs bypass limits and grow memory; limits are not shared, while SQLite write pressure remains. | `app/app/logs_api.py:75-92,180-222`. |
| `OP-050` | `incorrect` | A private/audience corpus boundary must be real authorization with licensing/provenance. | Audience is self-declared; publicly selectable SBI/UCD mode sends committed “sanitized” paper text to every model surface; catalog lacks per-doc license manifest. | Personalization is mislabeled as access control and may disclose unreviewed contact/license content. | `corpus/README.md`, `app/app/audience.py`, `audience_content.ts`. |
| `OP-051` | `incorrect` | CI “hermetic/no network” must be enforced technically. | Comments/docs assert hermeticity, but no network isolation exists and E2E interview can call the real model path. | Leaked credentials turn tests billable/nondeterministic and may transmit fixture goals. | `.github/workflows/ci.yml:8-10`, `docs/CI.md`, `interviews.py`. |
| `OP-052` | `incorrect` | Root lint/typecheck commands should cover what help/docs call backend/all. | Root lint omits frontend GTS; typecheck omits engine mypy; `test-all` omits major packages. | Developers can pass named gates with unchecked product surfaces. | root `Makefile:181-229`. |
| `OP-053` | `incorrect` | CI docs/test counts should describe current gates. | `docs/CI.md` and `PARITY-VERIFICATION` report obsolete counts/timing/all-green status. | Reviewers are directed to historical health rather than current red/load-sensitive state. | `docs/CI.md`, `docs/PARITY-VERIFICATION.md`, current results. |
| `OP-054` | `incorrect` | Resource governance must be bound to verified subjects and a deployment-wide/provider budget. | Uniform limit 10 is counted per caller-selected ID *and* each of four profiles; one ID can reserve 40 and IDs can rotate; each run may start eight workers. | Verified Labs 3/1 quota is absent and the current check is ineffective against spend/DoS. | `config.py:78-100`, `runs.py:97-111`, `store/runs.py:197-240`; production auth observation. |
| `OP-055` | `incorrect` | Demo templates should be immutable or cloned per user. | Ownership middleware exempts demo runs and normal mutation routes rely on that guard. | Callers can append steering/messages/manual ideas/reviews/attachments to globally visible demo state. | `app/app/main.py:317-327`, run mutation routes. |
| `OP-056` | `incorrect` | Documentation should disclose durable browser storage accurately. | Architecture says no durable browser state; app stores client ID, theme/audience/API key in localStorage and auth token in sessionStorage. | Privacy/session/reset expectations are false. | `docs/ARCHITECTURE.md`, `lib/client_id.ts`, API-key/theme/audience/auth storage. |
### Operations source-ID crosswalk

This crosswalk preserves traceability from the independent operations audit's source IDs to the normalized `OP-*` register. Multiple source findings can support one canonical row, and one source can expose more than one canonical gap.

| Source family | Source ID -> canonical ID |
|---|---|
| Install/package | `OPS-INSTALL-001->OP-010`; `OPS-INSTALL-002->OP-011`; `OPS-INSTALL-003->OP-012`; `OPS-INSTALL-004->OP-027`; `OPS-PKG-001->OP-028`; `OPS-MCP-PKG-001->OP-028`; `OPS-PKG-002->OP-029` |
| Runtime/deployment | `OPS-PROD-001->OP-026`; `OPS-DOCKER-001->OP-030`; `SEC-MCP-001->OP-031`; `OPS-DOCKER-002->OP-032`; `OPS-DOCKER-003->OP-033`; `OPS-WORKER-001->OP-034`; `OPS-SQLITE-001->OP-035`; `MCP-CAP-001->OP-036`; `MCP-CAP-002->OP-037`; `MCP-CAP-003->OP-038`; `MCP-TEST-001->OP-039`; `OPS-VERCEL-001->OP-040`; `OPS-NOTIFY-001->OP-004` |
| CI/E2E/evaluation | `OPS-TEST-001->OP-023`; `OPS-PARITY-001->OP-020`; `EVAL-PARITY-001->OP-020`; `OPS-CI-001->OP-016`; `OPS-CI-002->OP-015,OP-052`; `OPS-CI-003->OP-051`; `OPS-CI-004->OP-017`; `OPS-CI-005->OP-053`; `OPS-E2E-001->OP-005,OP-006,OP-018`; `OPS-E2E-002->OP-013,OP-051`; `E2E-NONCREDIT-001->OP-042`; `OFFLINE-NONCREDIT-001->OP-041`; `DEMO-NONCREDIT-001->OP-014,OP-041`; `OPS-DEMO-001->OP-041`; `DEMO-SEC-001->OP-014,OP-055`; `EVAL-SCI-001->OP-021`; `EVAL-SCI-002->OP-022`; `EVAL-PROV-001->OP-043`; `EVAL-RECOVERY-001->OP-044`; `EVAL-RELEASE-001->OP-045` |
| Security/privacy/lifecycle | `SEC-AUTH-001->OP-001`; `SEC-QUOTA-001->OP-002,OP-054`; `SEC-AUTH-002->OP-046`; `SEC-SHARE-001->OP-024`; `PRIV-UPLOAD-001->OP-047`; `PRIV-LIFECYCLE-001->OP-008,OP-009,OP-025`; `PRIV-FEEDBACK-001->OP-007,OP-048`; `SEC-LOG-001->OP-049`; `PRIV-CORPUS-001->OP-050` |
| Documentation | `DOC-TRUTH-001->OP-019`; `DOC-TRUTH-002->OP-019`; `DOC-TRUTH-003->OP-053`; `DOC-TRUTH-004->OP-019`; `DOC-TRUTH-005->OP-056`; `DOC-TRUTH-006->OP-019` |

`OP-003` comes directly from current Google Help/product evidence. `SEC-KEY-001` maps to `F-HOME-07` (with its CSP consequence also reflected in `OP-040`), and `SEC-REASONING-001` maps to `F-INTERVIEW-03`; neither is silently dropped merely because it belongs to a product-surface row.

## Uncredited shells, fixtures, dormant clients, and stale claims

The following exist in the repository but receive no positive implementation credit:

| Item | Why it is not credited |
|---|---|
| Deterministic offline hypotheses/reviews/reports and the three startup demo runs | They are phrase-bank/schema fixtures designed for repeatable navigation and tests, not scientific reasoning or retrieval. |
| `getInterview`, `editInterviewFields`, `getProximity`, `addScientistHypothesis`, `addScientistReview`, `reportMarkdownUrl`, `askRunQuestion`, `sendRunSteering`, `createReportShare`, `listReportShares`, `revokeReportShare`, and `getRunEvents` in the frontend client | No live non-test component calls them. Backend reachability is recorded separately; they are missing product behaviors. |
| `/shared/:token` without a share-creation UI | Manual URL consumption is not a user-reachable sharing journey, and the payload is unsafe. |
| Retired tab components and pre-refactor workbench copies under `references/ui-ux/legacy-workbench-ui/` | They are deliberately unmounted reference code. |
| `/proposals` static graph | It is hard-coded product planning content, not scientific Proximity output. |
| Schemas/prompts/tests named after Google techniques | A name proves neither execution nor semantics. Live-shape defects in Proximity and the parity ledger demonstrate the risk. |
| `docs/FIDELITY.md`, `docs/PARITY.md`, prior closure matrices and dated “final status” files | They are stale self-assessments. Current source/runtime and primary evidence override them. |
| E2E specifications for absent report controls | Desired test text does not make NotebookLM, Agent, Share or Download reachable. |
| Evaluation harnesses without representative artifacts | Code capable of scoring GPQA/scaling/expert results is not the missing experiment. |
| Local 12-agent coalition descriptions | Supporting modules can be useful, but public evidence verifies one Supervisor plus six specialist roles. |

## Verified, inferred, and proprietary behavior register

This register prevents implementation choices from becoming invented Google facts. Confidence describes the evidence for the stated boundary, not a fidelity score.

| ID | Behavior/detail | Scope and status | Basis | Confidence | Audit treatment |
|---|---|---|---|---|---|
| `U01` | Full production source and literal 1:1 behavior | `UNKNOWN` / proprietary | Google states the full system depends on proprietary infrastructure, compute and safety controls; only schematic code/prompts are public. | High | Never claim literal source parity; close only observable/invariant behavior. |
| `U02` | Standard/Advanced cycle, idea, match, token, cost and latency budgets | `UNKNOWN` | `G3` describes relative depth and 3/1 quota, not numerical envelopes. | High | Keep reconstructed budgets configurable/versioned and visibly local. |
| `U03` | Production model identities/routing/temperatures/context sizes | `UNKNOWN` | Paper/product name Gemini-family systems; internal current routing is undisclosed. | High | DeepSeek/LiteLLM behavior is divergent/local, not an equivalent substitute. |
| `U04` | Complete prompt library | `UNKNOWN` | `G2` discloses eight templates only; no complete Supervisor, Proximity, safety, interview, retrieval-query, report or chat set. | High | Label all other prompts clone-authored; do not call recovered Google prompts. |
| `U05` | Exact Supervisor features, reward/effectiveness model, portfolio size and sampling formula | `UNKNOWN` | ARCH verifies adaptive allocation and example statistics, not formulas. | High | Implement published semantics with configurable policy and recorded rationale. |
| `U06` | Queue, worker lease, heartbeat, retry, DB and checkpoint implementation | `LOCAL/UNKNOWN` | ARCH verifies async tasks/persistence/restart, not technology. | High | Judge local design for durability, not 1:1 storage parity. |
| `U07` | Proximity embedding/model/distance/threshold/index/cadence | `UNKNOWN` | ARCH verifies goal-conditioned semantic graph and uses embeddings only as an example. | High | Require working semantic purpose; document local algorithm. |
| `U08` | Elo K-factor, ties, confidence, floors, exact pair schedule | `UNKNOWN` | 1200 initialization and pairwise Elo are disclosed; higher constants are not. | High | Preserve core and label/configure all constants. |
| `U09` | Numeric Elo, bracket, match history and debate transcripts in Labs UI | `UNKNOWN` | `G3` verifies ranking by Elo, not numeric/internal UI. | High | Keep as optional provenance, not primary Labs surface. |
| `U10` | Complete retrieval providers, APIs, reranker, source weights and per-tier budgets | `UNKNOWN` | Web/database/private/specialist tool classes are verified, internals are not. | High | Implement credible traceable retrieval without claiming Google's stack. |
| `U11` | Citation schema, DOI reconciliation and claim-entailment model | `UNKNOWN` | Clickable references and human verification are verified; exact classifier is not. | High | Local labels/models must be calibrated and versioned. |
| `U12` | Safety classifiers, thresholds, taxonomy, blocked-topic list and redaction wording | `UNKNOWN` | Layered gates/exclusion/oversight are verified; details/dataset withheld. | High | Match invariant and auditability, never invent Google policy parity. |
| `U13` | Exact run progress and ETA computation | `UNKNOWN` | Footage shows values but not computation. | High | Do not present clone extrapolation as Google-equivalent; expose uncertainty. |
| `U14` | Pause, resume, cancel, early stop, live parameter edit or mid-run Labs controls | `UNKNOWN` for Labs | Current Help does not document them; ARCH verifies scientist steering and durable restart, not these exact controls. | High | Keep operational controls local; require ARCH steering without asserting placement. |
| `U15` | Current Labs file-upload interaction/limits | `UNKNOWN` for Labs; verified ARCH capability | Paper supports huge private/multimodal input, Help does not document upload UI. | High | Exposed upload is a local realization and must truthfully ground the plan/run. |
| `U16` | Cross-run personalized scientific memory | `UNKNOWN` | Persistent context is verified, but scope may be per run. | Medium | Do not add/claim cross-run memory without consent and new evidence. |
| `U17` | Download file format(s) | `UNKNOWN` | `G3` says download only. | High | Implement at least one truthful format; do not claim Google supports a format matrix. |
| `U18` | Mobile Labs layout and support | `UNKNOWN` | Help recommends desktop/Chrome; no direct mobile capture. | High | Make local mobile usable/accessibile but do not call pixel parity. |
| `U19` | Collaboration, annotations, branching/version restore and team notes in Labs | `UNKNOWN` | Related Gemini Enterprise evidence does not establish Labs behavior. | High | Optional extensions only, isolated from faithful surface. |
| `U20` | Exact report JSON/Markdown/API/share-token/storage schema | `UNKNOWN` | Tabs/actions/artifact concepts are public, infrastructure is not. | High | Define one safe local contract and version it. |
| `U21` | Frequency/algorithm of generated idea diagrams | `UNKNOWN` | Footage proves at least that an idea can include a diagram. | Medium | Support real generated artifacts without promising every idea or a particular method. |
| `U22` | Production latency, uptime, compute credits and monetary cost | Partly verified product behavior, exact values `UNKNOWN` | Several-hour runs and possible failed-run credit refund are documented; amounts/SLOs are not. | High | Match truthful state/messaging, not invented numbers. |
| `U23` | “Complete reasoning trace” as public chain-of-thought | Rejected inference | ARCH safety describes internal trace/logging; footage shows only Thinking. | High | Maintain access-controlled audit provenance; never stream raw CoT to end users. |
| `U24` | Separate Google agents for intake, literature, citation, safety, report and chat | Rejected inference | Canonical roster is Supervisor + six specialists. | High | Map these as supporting services/subtasks, not peer Google agents. |
| `U25` | Durable/idempotent restart and canonical release policy | Supported implementation inference | Required to realize verified persistent restart and exclusion across a distributed product, though exact mechanics are not published. | High | Treat as necessary local engineering obligation, not Google implementation detail. |
| `U26` | Semantic/hybrid retrieval | Supported quality inference | Exact Google stack unknown, but current lexical-only selection cannot credibly realize goal-relevant large-corpus grounding. | Medium | Require evaluated semantic relevance and provenance while labeling algorithm local. |
| `U27` | WCAG conformance level of Google product | `UNKNOWN` | Public evidence used here does not state it. | High | Fix observable accessibility failures and test local compliance; do not claim Google-equivalent internals. |

## Difference-register index

The detailed tables above are the canonical exhaustive difference register at this revision. They contain 90 frontend/product findings (`F-*`, including eight `F-A11Y-*` rows), 70 engine/backend findings (`EB-*`), and 56 operations/privacy/deployment findings (`OP-*`), plus 15 credited working foundations and 27 inference/proprietary boundaries. Counts are inventory aids, not a score.

| Area | Finding ranges |
|---|---|
| Entry, home, interview and setup | `F-ENTRY-*`, `F-HOME-*`, `F-INTERVIEW-*`, `EB-001-006` |
| Active run and report UI | `F-RUN-*`, `F-REPORT-*`, `F-IDEAS-*`, `F-KB-*`, `F-SUMMARY-*`, `F-SPEC-*` |
| Agent follow-up, sharing, state and extensions | `F-AGENT-*`, `F-SHARE-*`, `F-EXPORT-*`, `F-STATE-*`, `F-EXT-*` |
| Responsive/accessibility | `F-RESP-*`, `F-A11Y-*` |
| Coalition, scheduling and durability | `EB-007-018` |
| Generation, retrieval and grounding | `EB-019-032` |
| Reflection, ranking, proximity, evolution, meta-review and safety | `EB-033-053` |
| Reports/API/CLI/metrics/evaluation | `EB-054-070` |
| Access, quota, data lifecycle, packaging, CI, documentation and deployment | `OP-001-056` |

## Fidelity-first roadmap

This order is governed by scientific harm, privacy, recoverability and architectural causality. It is not an estimate of coding effort.

### P0 — Establish one safe scientific release boundary

**Implementation targets:** `EB-026`, `EB-029-032`, `EB-035-036`, `EB-046`, `EB-048-052`, `F-KB-02-05`, `F-SUMMARY-01-03`, `F-SHARE-02`, `OP-008-009`, `OP-024-025`, `OP-041`, `OP-045`, `OP-047-050`.

1. Define one canonical, persisted publishability decision that includes retraction/correction state, review disposition, deep-verification state, claim support/contradiction/abstention, candidate safety, human adjudication and redaction.
2. Require ranking eligibility, evolution parent selection, matchmaking, Meta-review/overview inputs, leaderboard, idea buckets, Knowledge Base, Agent/Q&A context, contacts, notification, download/export, public share and deletion/export archives to consume that decision—not separate filters.
3. Quarantine retracted/withdrawn/corrected sources at ingestion and every consumer, including reserved-slot, underfilled-budget and contact paths.
4. Filter overview inputs before the LLM call. Never post-filter prose already synthesized from blocked ideas.
5. Make `redact` transform content before any durable/public artifact. Preserve a restricted audit record without leaking it to ordinary users.
6. Correct live claim/evidence field shapes, exact span/source resolution, Knowledge Base links/global numbering and contradiction insights.
7. Replace the UI-generated Knowledge Base fallback with an honest raw-evidence state and calculate Verified only from defined evidence/verification state.
8. Restrict sharing to the versioned sanitized report contract; prove tenant isolation, revocation and absence of raw private/blocked artifacts.
9. Add permanent deletion and data-access/export semantics across all derivatives, with explicit cache/log/notification/share handling.

**Closure proof:** integration tests inject a retracted source and each kind of blocked idea, then assert absence from every internal/public consumer; a redaction fixture proves original text cannot be read through DB/API/SSE/log/share/export; a deletion test proves every scoped derivative is gone or retained only under an explicitly documented legal/audit rule.

### P1 — Make runs, safety review, and human actions durably correct

**Implementation targets:** `EB-002-004`, `EB-012`, `EB-015-018`, `F-INTERVIEW-04-06`, `F-INTERVIEW-12`, `F-RUN-05-07`, `F-AGENT-02-03`, `F-STATE-01-04`, `OP-004`, `OP-013`, `OP-023`, `OP-035`, `OP-044`.

1. Upsert/merge scientist hypotheses and reviews without collisions/duplicate semantics while preserving ID, author, provenance, lineage and safety state.
2. Commit steering consumption and its successor checkpoint atomically; crash/replay must consume exactly once.
3. Represent safety hold as an explicit durable waiting task/state. Approval creates a unique successor; rejection settles blocked. Test intake and final hold both ways.
4. Transactionally settle exhausted/unsupported tasks to failed run + terminal event + API/SSE/CLI error.
5. Enable foreign keys for every connection; ship forward-only validation/repair migrations for existing orphan/legacy/demo rows.
6. Invalidate/rebuild graph and tool availability when material configuration changes.
7. Persist/recover interviews by route/ID; make structured field editing and retry genuine server operations.
8. Make create/upload/start recoverable as one user transaction: resume the draft or cleanly roll back after any partial failure.
9. Make upload, email, feedback, share and other side effects idempotent/retryable with visible failure state.
10. Ensure forced offline mode makes no external model/tool request.
11. Replace fixed process-startup timing assumptions with deterministic readiness/lease tests.

**Closure proof:** forced-crash tests cover each transaction boundary; no run can remain nonterminal with no claimable work; manual input completes through final report; held runs approve/reject end to end; reload resumes interview; repeated side-effect workers do not duplicate delivery.

### P2 — Implement the published adaptive asynchronous coalition

**Implementation targets:** `EB-007-011`, `EB-019-021`, `EB-039`, `EB-044-045`, `EB-051`, `EB-059-062`, related `F-RUN-02-06`.

1. Replace the fixed serial scientific spine and single-successor enum with dependency-aware queueable tasks for Generation, each Reflection mode, Ranking, Evolution strategies, Proximity, Meta-review and candidate safety.
2. Give Supervisor an actual resource-allocation contract that can enqueue a bounded portfolio of independent tasks, observe queue/backlog and measured agent yield, and reprioritize at safe boundaries.
3. Remove the prompt instruction forbidding workflow planning. Persist ResearchPlan, allocations, observations, feedback and terminal rationale.
4. Instrument every model/tool/cache operation with agent/task/model/prompt/tool/schema/policy version, tokens, cost, latency, retries, errors, cache state, item yield and evidence provenance.
5. Allocate/terminate from truthful counters, novelty/diversity gain, review backlog, tournament coverage, failures, safety, steering and convergence.
6. Append Meta-review feedback to every applicable later agent, including Supervisor, retrieval, Proximity and safety; feed safety alerts back to Supervisor.
7. Bound every fan-out, isolate per-item failures and commit successful siblings.
8. Derive progress from durable completed/queued work and show uncertainty rather than non-monotonic fixed percentages or synthetic ETA.

**Closure proof:** a run demonstrates simultaneous independent specialist leases, a Supervisor decision changes the task portfolio after measured yield/failure, Meta-review reaches every declared consumer, actual invocation counts equal metrics, and a recorded evidence-based terminal decision ends the run.

### P3 — Make the scientific techniques and grounding material

**Implementation targets:** `EB-019-028`, `EB-033-047`, `EB-063`, `F-HOME-05-06`, `F-IDEAS-01,05-07,11`, `F-KB-01,04-05`, `F-SUMMARY-05`, `OP-037`, `OP-047`, `OP-050` while preserving `EB-037` and `EB-042`.

1. Add hybrid lexical/vector/scientific-entity retrieval with query relevance, source identity/quality/recency, correction/retraction status and diversity. Persist scores/rationale/version.
2. Index large private corpora and preserve page/section/figure/table locations; add true multimodal model inspection when supported. Make attachments ground interview/plan before run creation.
3. Add canonical DOI/PMID/URL identity, availability checks, retrieval timestamp/version and exact stored passages.
4. Atomize scientific claims and calibrate support/contradiction/abstention on representative human-audited data; fail closed when evidence is unavailable/retracted.
5. Feed actual passages to Q&A, reviews, verification, reports and citations.
6. Implement iterative assumption/sub-assumption trees and bounded auditable debate tasks.
7. Make initial/full/simulation/observation/recurrent/deep review dispositions canonical and release-enforcing; provider failure becomes explicit unverified, never implicit pass.
8. Deep-verify meaningful post-tournament leaders and reverify after material evidence/text changes.
9. Fix live Proximity schema, persist non-empty weighted edges and use them for both dedup/diversity and matchmaking.
10. Implement the disclosed Evolution families separately—grounding, feasibility, inspiration, combination, simplification and out-of-box—while retaining immutable parent/child state, fresh Elo and deterministic seeds.

**Closure proof:** a live-schema Proximity response creates weighted edges that alter a selected matchup; representative retrieval beats lexical baseline; exact passages support/contradict atomic claims; every review disposition changes eligibility as specified; a multi-document interview/plan visibly changes from its sources.

### P4 — Realign the product to current Labs evidence

**Implementation targets:** all `F-ENTRY-*`, `F-HOME-*`, `F-INTERVIEW-*`, `F-RUN-01,03-04`, `F-REPORT-*`, `F-IDEAS-02-04,07,10-12`, `F-KB-03-04`, `F-SPEC-*`, `F-AGENT-*`, `F-SHARE-*`, `F-EXPORT-*`, `F-EXT-*`, `OP-001-009`, `OP-031`, `OP-038`, `OP-040`, `OP-046-050`, `OP-054-055`, and surface aspects of `EB-001,005-006,032,047,054-058`. `F-IDEAS-13` is not a Labs implementation requirement; contain it with `U19` in P7.

1. Establish current Labs Help as the source for present terminology/actions and the direct green footage as the source for non-conflicting visible states. Treat Gemini Enterprise Idea Generation as secondary only.
2. Build the green Hypothesis Generation entry/Create a run/research-challenge journey and remove Affiliation, project outreach, developer logs/offline chip and static proposals from the default fidelity surface.
3. Add durable right-side Interview Progress, editable fields and a safe Thinking status; never expose raw chain-of-thought.
4. Expose exactly Standard and Advanced and enforce three Standard + one Advanced in-progress per account. Keep budgets local/configurable/provenanced.
5. Use honest plan review/start language and visible completion-email delivery/failure state. Treat any checkbox or custom-recipient choice as a labelled local adaptation, not verified Labs behavior.
6. Build the high-level Idea Tournament execution view with real counts, honest ETA/uncertainty and user-safe activity; keep ARCH expert steering in a clearly labeled workbench layer if not evidenced in Labs.
7. Restore report order and exact current labels: Ideas, Knowledge Base, Summary, Run Specifications. Land completed runs on Ideas.
8. Render real Agent Insights, statistics and verified High Potential/Non-Viable groups and members, plus rich idea documents/real diagrams and the full relevant review/verification stack. Show explanatory reasons only when grounded and labelled as a local enhancement. Put numeric Elo, internal matches, lineage, claims and safety behind an optional provenance layer.
9. Give Failed runs a dedicated actionable state, status-refresh guidance and a support path. If the reconstruction has no credit system, say so; do not invent Google's refund rules or promise credits.
10. Wire run/idea Chat with Agent to safely grounded Q&A; route or disable the old composer correctly after start.
11. Make NotebookLM, share create/list/revoke, download, Product Feedback with privacy notice, notification and permanent deletion reachable end to end.
12. Label/isolate demonstrations and make them read-only; remove dead BYOK or implement it through an authenticated, secret-safe backend.

**Closure proof:** a fresh account completes the current Help journey without clone-specific gates; every control invokes a live backend operation; exact tab/mode/quota/action strings are asserted; there is no raw reasoning, fixture provenance ambiguity, dormant primary action or unsafe share.

### P5 — Fix responsive, accessible, and visual fidelity

**Implementation targets:** `F-RESP-01,03`, all `F-A11Y-*`, `F-IDEAS-08-10`, `OP-040`, `OP-042`, plus visual portions of entry/interview/report findings. `F-RESP-02`/`U18` remains open as Labs parity; this phase establishes local responsive acceptance only.

1. Fix the exact 720-CSS-pixel/DPR boundary so both 16:9 and 2:1 desktop show all tabs/content without clipping.
2. Add an ordinary visible/semantic mobile Back action and announced master/detail selection.
3. Implement focus trap, inert background, opener restoration and correct dialog/menu/region semantics; remove `role=status` from interactive popovers.
4. Choose coherent page-navigation or tab semantics and implement its keyboard behavior.
5. Keep streaming status concise and non-live where repeated announcements would overwhelm users.
6. Make global shortcuts discoverable or remove them; test zoom/reflow, contrast, targets and keyboard-only completion.
7. Compare source and implementation in the same review input at desktop 2:1, desktop 16:9 and mobile 1:2 after structural fidelity is working.

**Acceptance proof:** interactive browser and accessibility checks complete the local core journey at every required viewport; reference/current captures show no crop, overflow or hidden navigation in the reconstruction, while mobile Labs pixel parity remains unclaimed without direct source evidence. Automated scans are supplemented by keyboard/focus/screen-reader checks.

### P6 — Make packaging, CI, deployment, and scientific evaluation truthful

**Implementation targets:** `EB-070`, `OP-010-018`, `OP-021-023`, `OP-026`, `OP-028-045`, `OP-051-054`, and `F-STATE-02` reliability claims. `EB-022` and `EB-064-069` are evidence-dependent and remain open until representative external artifacts actually exist; code and synthetic fixtures alone cannot close them.

1. Install the app from its declared dependency metadata; add `pip check`, real PDF parsing and OCR-capable container tests. Fix `.env` path/documentation.
2. Redefine `test-all` or rename it; create a real aggregate gate covering engine, app, frontend, MCP, evaluations, lint, typecheck, builds, migrations, security and E2E.
3. Expand CI path triggers and build/smoke API/MCP/UI containers/deploy artifacts.
4. Reconcile unit/E2E expectations with the current reachable surface; eliminate load-sensitive timeout gates.
5. Run a non-mutating deployed smoke of production auth/CORS/ownership, MCP, provider, persistent volume/migrations, SMTP and sanitized share before release.
6. Repair parity-ledger references and require executable live-shape evidence plus a passing test, not file-name existence.
7. Produce representative Elo-correctness calibration, controlled multi-budget scaling/ablations, large diverse safety evaluation, calibrated citation audit and blinded expert review with confidence intervals/cost/provenance.
8. Keep wet-lab/case-study fidelity open until actually reproduced; never substitute fixtures or marketing anecdotes.

**Acceptance proof:** every declared implementable gate is green in a clean environment and in CI; container/deployed smoke passes; evaluation artifacts are dated, reproducible and appropriately qualified; no evidence row cites a missing/non-semantic test. Any unperformed expert, case-study, wet-lab or proprietary comparison remains explicitly open.

### P7 — Lock documentation, provenance, and extensions to the evidence boundary

**Implementation/documentation targets:** `EB-005`, `EB-014`, `EB-053`, `EB-055-060`, `EB-063`, `EB-070`, `F-ENTRY-04-05`, `F-IDEAS-12`, `F-SUMMARY-04`, `F-SPEC-04-05`, `F-STATE-05-06`, `F-EXT-*`, `OP-019-020`, `OP-027`, `OP-036`, `OP-053`, and `OP-056`. Contain `F-IDEAS-13` under `U19`. All `U-*`, `F-RESP-02`, `EB-022`, and `EB-064-069` remain open until their required primary or external evidence exists.

1. Rewrite README, architecture, fidelity/parity, env, setup, deployment and operator docs from current executable evidence.
2. Version and expose local provenance: model, prompt, schema, policy, tool/source, cache and reconstructed parameter versions, plus provider/offline status.
3. Describe the conceptual roster as Supervisor plus six specialists; map supporting local services without inventing Google agents.
4. Keep operator CLI, detailed provenance, pause/cancel, local safety admin, pilot feedback, logs, themes and other extensions explicitly `LOCAL` and outside the default faithful surface.
5. Maintain the dated `UNKNOWN` register. Contain and document proprietary/external items; mark one resolved only when new primary evidence or actual external validation appears.

**Closure proof:** documentation claims are machine-linked to passing executable evidence where possible; a reviewer can distinguish `LABS`, `ARCH`, `LOCAL` and `UNKNOWN` in every feature/decision; no “1:1 complete” statement survives while an unknown/external item remains.

## Roadmap coverage check

- P0 covers every scientific release, evidence, redaction, share and deletion finding.
- P1 covers every known durable-state, human-input, safety-review and transactional side-effect defect.
- P2 covers the architectural Supervisor/coalition/metrics gap.
- P3 covers every generation, retrieval, reflection, ranking, proximity, evolution and grounding gap while preserving the two strongest core matches.
- P4 covers every verified current Labs journey/action and contains research-only/local controls rather than conflating them.
- P5 covers local responsive/accessibility/visual acceptance while leaving `F-RESP-02`/`U18` open as Labs mobile parity.
- P6 covers all packaging, CI and deployment gaps and assigns evidence work to `EB-022`/`EB-064-069` without treating code as external validation.
- P7 covers every non-faithful extension and stale claim, and contains rather than closes proprietary/inference boundaries.

Every implementable finding has a remediation phase. Every unverifiable or external item has an evidence-acquisition or containment phase and remains open until that evidence exists; none is converted into a code task that could falsely “complete” it.

## Corrections to prior repository closure claims

This audit supersedes earlier implementation-status assertions without deleting their historical record.

| Prior/stale assertion | Current evidence-backed correction |
|---|---|
| Interview is a client-side keyword template. | The current interview is server/model driven and durable server-side, but frontend recovery/editing/progress/document grounding remain absent or incorrect. |
| Current product uses reconstructed four-tab names from newer MASH footage. | The cited MASH footage files are absent. Current Help verifies Ideas, Knowledge Base, Summary, Run Specifications; existing direct footage supplies the green composition. |
| Standard/Advanced parity is closed. | Current reachable UI/backend exposes Express/Standard/Extended/Ultra; public Labs contract is exactly Standard/Advanced with 3/1 concurrent limit. |
| Auth, uploads or durable worker infrastructure are absent. | They are implemented, but default auth, dependency packaging, interview grounding, OCR, privacy and durable composition contain serious defects. |
| Proximity weighted graph is fixed/verified. | Current live schema is index-shaped while the graph resolver expects text; direct valid input returns no edges. |
| Claim gate quarantines publication. | It blocks immediate ranking only; canonical state/report filter ignores the decision and fresh runs publish every blocked idea. |
| Evaluation/parity ledger is verified. | Its own truth tests fail because cited symbols do not exist; name existence would not prove semantics anyway. |
| “Final status” or closure matrices establish parity. | They predate current behavior and are implementation self-reports. Primary evidence, current source and runtime reproductions control. |

## Reproduction and visual appendix

### High-value source/current comparisons

| Target state | Direct source | Current capture | Observed delta |
|---|---|---|---|
| Research challenge entry | `references/core/google-co-scientist/media/hypothesis-generation/research-challenge-input-esn-phenotype.jpg` | `docs/assets/fidelity-audit-2026-07-20/02-home-desktop-16x9.jpg` | Green framed product prompt versus dark Gemini-style hero/rail/recents. |
| Interview | `references/core/google-co-scientist/media/hypothesis-generation/agent-interview-research-challenge-sars-cov-2.jpg` | `docs/assets/fidelity-audit-2026-07-20/04-interview-question-desktop-16x9.jpg` | Target persistent Interview Progress rail is absent; current exposes raw reasoning. |
| Idea insights | `references/core/google-co-scientist/media/hypothesis-generation/esn-ideas-agent-insights.jpg` | `docs/assets/fidelity-audit-2026-07-20/08-research-overview-desktop-16x9.jpg` and `docs/assets/fidelity-audit-2026-07-20/10-all-ideas-desktop-2x1.jpg` | Target insights/categories/statistics composition versus split four-tab/three-column hybrid. |
| Knowledge Base | `references/core/google-co-scientist/media/hypothesis-generation/esn-knowledge-base-analytical-pipelines.jpg` | `docs/assets/fidelity-audit-2026-07-20/07-knowledge-base-desktop-16x9.jpg` | Target compact technical document/outline/references versus clipped sparse/fallback content. |
| Idea detail | `references/core/google-co-scientist/media/hypothesis-generation/esn-poma-hub-hypothesis-full-detail-with-diagram.jpg` | `docs/assets/fidelity-audit-2026-07-20/10-all-ideas-desktop-2x1.jpg`, `docs/assets/fidelity-audit-2026-07-20/12-idea-detail-mobile-1x2.jpg` | Target rich artifact/diagram/Agent versus text-only detail; mobile lacks Back. |
| Execution | `.../esn-run-executing-idea-tournament.jpg` | active-run code and diagnostic captures `14/15` | Target ETA/counters/high-level tasks; current uses synthetic ETA/internal stages and diagnostic sessions had access/fetch confounds, so captures are secondary evidence only. |

The browser comparisons were made after placing target and current captures in the same visual review context. The 2:1 report can be coherent while the required 16:9 state is severely clipped; this is why viewport-specific captures, not a single screenshot, control `F-RESP-01`.

### Runtime database queries

The isolated database was queried directly after the two new runs. Relevant reproducible predicates were:

```sql
SELECT run_id, stage, decision, COUNT(*)
FROM safety_decisions
GROUP BY run_id, stage, decision;

SELECT run_id, label, claim_role, COUNT(*)
FROM claim_evidence
GROUP BY run_id, label, claim_role;

SELECT h.run_id, hs.status, hs.safety_status, COUNT(*)
FROM hypothesis_state AS hs
JOIN hypotheses AS h ON h.id = hs.hypothesis_id
GROUP BY h.run_id, hs.status, hs.safety_status;
```

The recorded results are in `R1-R3` and were cross-checked against report JSON counts and the safety table.

## Audit limits

- Production Vercel/Railway state was not mutated or relied upon as proof. Deployment behavior remains `OP-026` until a permissioned, secret-safe smoke is run.
- No configured SMTP delivery, NotebookLM handoff, Google feedback submission or data-request process was exercised because the first two are absent/unconfigured and the latter are external Google operations.
- Offline runs prove task composition, gates, persistence and presentation only. They do not prove scientific quality, model parity, literature coverage or real-provider reliability.
- Public evidence cannot reveal proprietary Google code, models, policies, budgets or exact algorithms. `U-*` items remain open even after all implementable roadmap work.
- Current Help and first-party sources were checked as of the audit date; a future product revision requires a new dated audit rather than silently reinterpreting this one.
- The browser's active-run diagnostic captures included origin/ownership/fetch confounds and are not used alone to prove a product defect. Source inspection, successful API persistence and the clean report/home captures support the findings that remain.

## Final fidelity determination

The current repository should be described as a **functioning local Co-Scientist-inspired research workbench with meaningful published-mechanism coverage and substantial non-faithful product/operations extensions**.

It must not be described as:

- a 1:1 Google AI Co-Scientist replica;
- the same asynchronous Supervisor coalition on different infrastructure;
- the current Hypothesis Generation product surface;
- deeply verified or safe-by-construction scientific output;
- a complete implementation of Google prompts/agents/tools;
- externally validated to Google's published evaluation or wet-lab level; or
- “closed” by the existing fidelity/parity ledgers.

The fastest defensible path is to fix P0/P1 truth, privacy and durability before changing appearance; then replace the serial architecture, make scientific grounding material, and finally rebuild the primary journey around current Labs evidence. Visual polish on the present hybrid shell would preserve the wrong product while unsafe publication paths remain underneath.
