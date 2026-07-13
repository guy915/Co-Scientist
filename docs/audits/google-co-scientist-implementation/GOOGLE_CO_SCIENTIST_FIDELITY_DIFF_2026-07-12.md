# Google Co-Scientist fidelity diff

**Audit date:** 2026-07-12  
**Repository:** `/Users/guy/Code/Co-Scientist`  
**Target:** Google DeepMind Co-Scientist and the current Google Labs Hypothesis Generation product  
**Question:** How far is the working implementation from a 1:1 replica?

## Executive conclusion

The repository contains a real, runnable Co-Scientist-inspired system, not merely a static demonstration. The engine can generate hypotheses with live models, retrieve PubMed material through MCP, run reviews and Elo matches, append evolution children, checkpoint and resume, persist a run to SQLite, and render a React report. Those facts are verified by source inspection, passing executable tests, the live local service, and a recent real-provider run.

It is nevertheless **not a 1:1 replica, and it is not close enough to be described as the same product or the same computation with a different implementation**. It is a bounded LangGraph research workflow wrapped in a polished Gemini-Enterprise-inspired UI. Google's disclosed system is a continuously operating asynchronous task framework in which a freeform Supervisor dynamically weights and samples specialized workers, spends most computation on verification, explores potentially thousands of directions, repeatedly propagates all-review/all-debate feedback, and supports rich scientist steering and large multimodal private corpora. The current implementation executes one graph node at a time through a deterministic code scheduler, normally creates 4–16 initial ideas and 1–4 work iterations, retrieves a small PubMed-centred corpus, uses only partial versions of several review/evolution strategies, and terminates into a much smaller report.

The public product mismatch is even larger. Google's current journey is a conversational interview with an `Interview Progress` panel, `Research Challenge` / `Focus Area` / `Preferences` / optional `Title`, exactly `Standard Run` and `Advanced Run`, a live several-hour execution surface, and a Goal Report with `Ideas`, `Knowledge Base`, `Summary`, and `Run Specifications`, plus `Open Agent`, NotebookLM, public sharing, and downloads. The clone substitutes local keyword rules for the interview, exposes `Express` / `Standard` / `Extended` / `Ultra` plus a four-way focus selector, uses `Goal Details` / `Learning` / `Research Overview` / `All Ideas`, and has no working product UI for most scientist-in-the-loop, export, sharing, or follow-up actions. API-only routes do not make those product behaviors implemented.

The most serious scientific-fidelity failure is evidence handling. Google's current product is presented as deeply verifying claims with clickable citations and Google's 2026 system description says most compute is spent on verification. The latest inspected real clone report had three PubMed records, five published ideas, and a citation audit of **0 verified, 0 partial, 13 unsupported**. The report still stated the mechanisms as facts. The repository's own offline evaluation fails its citation gate because contradiction recall is 0.75, below 0.80. Passing unit tests therefore establish implementation consistency, not Google-equivalent scientific behavior.

A literal 1:1 replica cannot be proven from public information. Google's production models, prompt revisions, scheduling weights, termination thresholds, safety classifiers, proprietary infrastructure, Standard/Advanced compute envelopes, and exact citation-verification stack are not public. The closest achievable target is an evidence-bounded reconstruction that exactly matches every verified public behavior, isolates all remaining inferred choices behind configuration, and never presents inferred internals as verified Google behavior.

## Audit rules and classifications

This audit credits only behavior reachable in the current engine-provider code or live frontend. It does not credit:

- `mock_workflow.py`, seeded demo runs, mock evidence, or mock reports;
- interfaces without a frontend path or another demonstrated consumer;
- enums, schemas, prompts, comments, or tests that name a behavior without executing its material semantics;
- local roadmap/specification claims that are not corroborated by implementation or primary Google evidence;
- example YAML files whose tools are not enabled in the inspected runtime;
- aspirational parity documents (`docs/FIDELITY.md`, `docs/PARITY.md`, `docs/PARITY-VERIFICATION.md`, `docs/ui-fidelity.md`).

Classifications:

| Class | Meaning |
|---|---|
| `matched` | The material observable behavior matches the disclosed Google behavior. |
| `partial` | A working subset exists, but an important semantic, scale, or product element differs. |
| `missing` | No working implementation is reachable. |
| `incorrect` | The implementation claims or presents the target behavior but does something materially wrong. |
| `divergent` | A deliberate substitute implements a different product or architecture. |
| `non-faithful extension` | Working behavior exists but is not evidenced as Google behavior and changes the 1:1 surface. |
| `unverifiable` | Google's exact behavior is not public enough for a defensible comparison. |

## Evidence hierarchy and examined material

### Primary Google evidence

1. [Google Hypothesis Generation Help — How to research](https://support.google.com/hypothesis-generation/answer/17106281?hl=en), current product terminology, journey, run types, concurrency limits, report tabs, agent access, NotebookLM, sharing, and download behavior.
2. [Google Labs Science Intended Use Policy](https://support.google.com/hypothesis-generation/answer/17106905), last modified 2026-04-28, for scope, required human review, validation, and clinical-use limitations.
3. [Gottweis et al., *Accelerating scientific discovery with Co-Scientist*, Nature 655, 487–496 (2026)](https://www.nature.com/articles/s41586-026-10644-y), including the 115-page supplementary information and published pseudocode, prompts, examples, evaluations, and ablations.
4. [arXiv 2502.18864v2](https://arxiv.org/abs/2502.18864), submitted 2026-06-29, 157 pages; the PDF was extracted and its pseudocode, prompt, safety, and output-example pages were visually checked.
5. [Google DeepMind, “Co-Scientist: A multi-agent AI partner to accelerate research”](https://deepmind.google/blog/co-scientist-a-multi-agent-ai-partner-to-accelerate-research/), 2026-05-19, for the current coalition, parallel freeform Supervisor, verification emphasis, named databases, AlphaFold, scale, and case studies.
6. [Google, “Gemini for Science: AI experiments and tools for a new era of discovery”](https://blog.google/innovation-and-ai/technology/research/gemini-for-science-io-2026/), for the current Hypothesis Generation description and “deeply verified” clickable-citation claim.
7. [Google Research, 2025 Co-Scientist announcement](https://research.google/blog/accelerating-scientific-breakthroughs-with-an-ai-co-scientist/), used only where the 2026 paper/product evidence does not supersede it.

### Local Google evidence

The complete canonical corpus under `references/core/google-co-scientist/` was inventoried. The source-system reference, architecture, coalition, tournament, retrieval, memory, prompting, build-methodology, and product-UX documents were compared with the primary sources. Clone-design recommendations in those documents were treated as reconstruction proposals, not facts about Google. Particularly probative local evidence includes:

- `references/core/google-co-scientist/research/extracted-artifacts/prompts/`:
  all eight published Google prompts;
- `references/core/google-co-scientist/research/extracted-artifacts/pseudocode/`:
  Supervisor and six agent listings;
- `references/core/google-co-scientist/research/extracted-artifacts/outputs/`:
  research-plan configs, hypotheses, every published review type example,
  ranking debates, meta-review critique, research overviews, research contacts,
  Specific Aims, AlphaFold tool use, and validated KIRA6 output;
- `references/core/google-co-scientist/media/hypothesis-generation/`: product
  intake, interview, run progress, Ideas, Knowledge Base, Summary/Agent Insights,
  and detailed-idea captures;
- `references/core/google-co-scientist/media/live-footage/`: MASH goal setup and
  run footage;
- current Nature supplement markdown and domain case-study supplements.

The local extracted outputs demonstrate an important scale/shape difference: Google examples include multi-thousand-word research overviews, complete review stacks, research contacts, dense proposal detail, and a MASH export exceeding 60,000 words. They also contain errors; they are evidence of output structure and depth, not proof that every Google claim is correct.

### Current repository evidence

All implementation-bearing surfaces under `engine/`, `engine/mcp_server/`, `app/app/`, `app/frontend/src/`, `evaluations/`, root build files, migrations/schema, prompts, configs, tests, and live docs were inventoried and searched. The highest-value implementation evidence is cited inline by path and symbol. The local services were exercised at `http://localhost:5173` and `http://localhost:8008`.

Verification on 2026-07-12:

| Check | Result |
|---|---|
| Engine tests | `1018 passed` |
| App tests | `371 passed`, one Starlette deprecation warning |
| Frontend tests | `270 passed` across 41 files |
| Frontend production build | Passed |
| Frontend lint | Passed |
| Ruff, engine/app/evaluations | Passed using `/opt/homebrew/bin/ruff` |
| Mypy, engine | Passed, 202 source files |
| Mypy, app | Passed, 105 source files |
| Offline evaluation smoke | **Failed:** citation contradiction recall 0.75 < 0.80 |
| Live status | engine provider; MCP and PubMed up; model and Supervisor `deepseek/deepseek-chat`; `tools_config=null` |

The UI was inspected interactively at 1440×720 (2:1 desktop) and 390×780 (1:2 mobile). Desktop intake, deterministic setup, run detail, all four tabs, and seeded demo content were inspected. The mobile setup view clipped content while reporting no horizontal overflow, making part of the setup inaccessible.

Path shorthands used in the comparison resolve as follows. A basename plus symbol
in a row is an exact citation within the applicable root, not a reference to a
plan or similarly named file elsewhere.

| Shorthand surface | Repository root |
|---|---|
| Engine modules and prompts | `engine/src/co_scientist/` |
| Engine tests | `engine/tests/` |
| MCP server | `engine/mcp_server/` |
| App backend modules | `app/app/` |
| App tests | `app/tests/` |
| Frontend components and hooks | `app/frontend/src/` |
| Evaluation code and result artifacts | `evaluations/` |
| Google reference corpus | `references/core/google-co-scientist/` |

## Map of the two systems

### Verified Google product flow

```text
Research challenge
  → conversational interview + right-side Interview Progress
  → finalized goal specification (Challenge, Focus Area, Preferences, Title)
  → Configure Run (Standard or Advanced)
  → several-hour run + email completion
  → Goal Report
       Ideas | Knowledge Base | Summary | Run Specifications
  → Open Agent / NotebookLM / Share / Download
```

### Current implemented product flow

```text
Single prompt
  → client-side keyword rules create a fixed setup immediately
  → optional free-text note + Focus and Tier radio cards
  → create draft + start background task
  → four-step recent-run indicator / run detail
  → clone report
       Goal Details | Learning | Research Overview | All Ideas
  → no report-level agent, NotebookLM, public share, or download UI
```

### Verified Google technical loop

```text
Natural-language/multimodal goal → parsed ResearchPlan in shared memory
  → global asynchronous task queue
  → Supervisor dynamically weights/samples worker tasks from live statistics
  → Generation / Reflection / Ranking / Proximity / Evolution / Meta-review
     run continuously and in parallel, create follow-up tasks, and feed memory
  → tournament continues while idea/match budgets permit
  → periodic all-review/all-debate meta-feedback appended to later prompts
  → final top hypotheses + comprehensive research overview/contact/output format
```

### Current implemented technical loop

```text
Text goal + deterministic client setup
  → one initial Supervisor guidance call
  → static LangGraph entry
  → optional literature review → generate → reflection → review → safety
  → ranking → deep verification → deterministic orchestrator
  → one routed task at a time (generate/evolve/proximity/rank/review/terminate)
  → terminal research-overview call
  → final drain, claim audit, regex safety gate, SQLite report
```

Concurrency exists *inside* several nodes through `asyncio.gather`, but there is no global multi-worker task queue, no concurrent specialist workers across phases, and no model-directed resource allocation.

## Complete evidence-backed comparison

The tables below are the canonical comparison. Each row is independently testable and deliberately does not infer fidelity from shared names.

### A. Research-goal creation, interview, and scientist steering

| ID | Class | Google behavior | Current behavior and exact difference | Evidence | Fidelity consequence |
|---|---|---|---|---|---|
| A01 | `partial` | Accepts a natural-language challenge or hypothesis. | A text composer accepts a goal and passes it to `CreateRunRequest.research_goal`. This narrow entry behavior matches. | Google Help §§“Start a new research goal”; `app/frontend/src/workbench/pages/chat_composer.tsx`; `app/app/runs_models.py::CreateRunRequest`. | The initial text affordance matches, but not the goal-building process around it. |
| A02 | `missing` | Conducts a real conversational interview with the Hypothesis Generation agent. | `submitComposerMessage()` calls local `inferRunSpec()` immediately; no model/API interview occurs. Subsequent messages call `reviseRunSpec()`. | Google Help lines 45–49; local `agent-interview-*.jpg`; `chat_session_handlers.ts:69-112`; `run_spec.ts:121-178`. | The defining collaborative scoping behavior is absent. |
| A03 | `missing` | Shows right-side `Interview Progress`. | No interview progress state or component exists. | Google Help lines 45–48; local interview capture; frontend route/component inventory. | Users cannot see or complete the verified goal elements. |
| A04 | `incorrect` | Goal elements are `Research Challenge`, `Focus Area`, `Preferences`, optional `Title`. | Client rules output `requirements`, `attributes`, `criteria`, `focus`, and `tier`; the semantic grouping and labels are different. | Google Help lines 61–75; `run_spec.ts::InferredRunSpec`; `chat_timeline_run_spec_card.tsx`. | The clone produces a different specification contract. |
| A05 | `incorrect` | The agent iteratively extracts the scientist's meaning and asks targeted questions. | `inferRunSpec()` applies static default arrays and seven regex keyword rules. It can generate the same plan for materially different goals sharing keywords. | `run_spec.ts:93-249`; live desktop submission. | The UI presents deterministic templating as agent understanding. |
| A06 | `incorrect` | Natural-language corrections update the appropriate structured goal element. | Only `/change\|update\|set ... goal to\|as/` replaces the goal; all other input becomes the literal requirement `Apply steering note: ...`. | `run_spec.ts:143-177`. | Normal conversational refinements are not parsed or validated. |
| A07 | `partial` | Produces a structured research plan with preferences, attributes, and constraints. | Backend persists a setup block and the engine makes one Supervisor plan call. However, the client pre-fills invented defaults, and several Supervisor fields are never consumed. | Nature §“Co-Scientist overview”; supplement §10.1; `run_modes.py::setup_config`; `supervisor.py`; `schemas/planning.py`. | A real plan object exists, but it is not the same goal parser or control contract. |
| A08 | `incorrect` | Custom evaluation criteria are used during auto-evaluation, debates, and self-improvement. | User `criteria` become setup prompt text, but ranking has its own fixed seven criteria; `workflow_plan.ranking_phase` has no reader and `config_synthesis` is read only by review. | Nature lines 308–312; `ranking.md`; `schemas/planning.py:61-62,153-157`. | Scientist criteria do not consistently govern the whole run. |
| A09 | `missing` | Can take extensive documents, other relevant data, and hundreds of PDFs as part of the research goal. | Frontend stages local files only in component state and never sends them. API attachments accept at most 200,000 characters of plain text; no binary/PDF/multimodal ingestion is wired to the UI. | Nature lines 308–310; `chat_composer_attachments.tsx`; `chat_composer.tsx`; `runs_models.py::HumanAttachmentRequest`; `runs.py::attach_document`. | Large private/multimodal goal context is absent. |
| A10 | `missing` | Scientist-provided private publications/experimental data are indexed and searchable by agents. | A text-only attachment/search API exists, but the main frontend never calls it and the engine workflow does not consume the run corpus as its private repository. | Nature lines 401–403; `app/app/run_corpus.py`; `runs.py:704-751`; frontend API inventory. | This is an API stub/extension, not working product grounding. |
| A11 | `missing` | Scientists can refine the goal during computation in light of hypotheses and overview. | Steering message APIs exist, but no frontend control calls them. The engine's orchestrator only sees a Boolean `pending_steering`; the app drains text into options, but the product path exposes none of it. | Nature lines 392–397; `runs.py:785-832`; `scheduling/policy.py:195-200`; frontend API inventory. | Verified mid-run scientist steering is not available to users. |
| A12 | `missing` | Scientists can submit their own hypotheses for tournament inclusion. | The backend endpoint persists and screens a manual hypothesis, but there is no frontend path. | Nature lines 396–398; `runs.py::add_human_hypothesis`; `human_input.py`; frontend API inventory. | An unreachable API does not reproduce the UI behavior. |
| A13 | `missing` | Scientists can provide manual reviews that guide ranking and improvement. | Backend accepts human reviews, but ranking does not distinguish or weight them as scientist input and the frontend cannot submit them. | Nature lines 396–397; `runs.py::add_human_review`; `human_input.py`; `ranking_prompt.py`; frontend API inventory. | Human evaluation is not in the implemented product loop. |
| A14 | `missing` | Right-side `Open Agent` supports deeper questions/trade-offs on report content. | A Q&A streaming endpoint/CLI exists, but no report UI invokes it and no right-side agent is rendered. | Google Help line 115; `runs.py::ask_run`; `qa.py`; frontend API inventory; live report. | Follow-up collaboration is absent from the product. |
| A15 | `non-faithful extension` | Current public evidence does not show a four-way evidence/novelty focus selector. | The clone adds `Prefer evidence`, `Balance`, `Prefer novelty`, and `Breakthrough`. | `run_spec.ts::FOCUS_OPTIONS`; `run_modes.py::RUN_FOCUS_VALUES`. | An extra control changes the target's visible and prompt behavior. |

### B. Run types, configuration, execution, and lifecycle

| ID | Class | Google behavior | Current behavior and exact difference | Evidence | Fidelity consequence |
|---|---|---|---|---|---|
| B01 | `incorrect` | Exactly `Standard Run` and `Advanced Run`. | UI and API expose `Express`, `Standard`, `Extended`, and `Ultra`; historical standard/advanced profile labels normalize to one stored `default` mode. | Google Help lines 77–87; `run_spec.ts::TIER_OPTIONS`; `run_modes.py:1-29`. | The primary run choice is visibly and behaviorally wrong. |
| B02 | `unverifiable` | Standard is quicker for testing/refinement; Advanced is more comprehensive, nuanced, and diverse. Exact budgets are not public. | Clone hard-codes tier budgets: initial ideas 4/8/12/16, iterations 1/2/3/4, matches 6/12/20/32, evidence 4/8/12/16. | Google Help lines 79–87; `run_modes.py::RUN_TIER_DEFAULTS`. | The clone's numerical semantics cannot be called Google-equivalent. |
| B03 | `incorrect` | Advanced is a distinct product mode. | Every new run stores `profile="default"`; tier is a numeric preset inside JSON. | `runs.py::create_run`; `run_modes.py::CANONICAL_RUN_MODE`. | Product analytics, labels, and execution cannot reproduce the two Google modes. |
| B04 | `missing` | Limits concurrent work to three Standard and one Advanced run. | Only per-run duplicate-start protection exists; no per-user mode quota is enforced. | Google Help line 79; `runs.py::_reserve_active_slot`. | Compute governance and visible availability differ. |
| B05 | `missing` | Failed runs may refund AI credits; credits are part of the run contract. | No credit, charge, refund, or account ledger exists. | Google Help lines 88–94; repository search. | Failure semantics and user expectations differ. |
| B06 | `missing` | Sends an email when a report is ready. | No completion email or notification service exists. | Google Help lines 85–87; repository search. | Long-running completion handoff is absent. |
| B07 | `divergent` | Runs may take several hours and current descriptions emphasize large compute. | The clone presents small bounded tiers; local real runs contain 5–18 surviving ideas and 9–12 matches. There is no several-hour product contract. | Google Help line 87; DeepMind lines 168–176; `RUN_TIER_DEFAULTS`; SQLite inspection; golden-run artifact. | Test-time-compute scale and user journey are materially different. |
| B08 | `partial` | Long-running computation persists state and restarts after component failure. | Real engine state is serialized after every node and resume re-enters at the orchestrator. This materially matches restartability, though granularity is node-level and not a distributed worker queue. | Nature lines 313–314; `checkpoint.py`; `engine_adapter/engine_stream.py::_make_engine_checkpoint_callback`; `generator/graph.py::_resume_router`. | Genuine partial match. |
| B09 | `non-faithful extension` | Public product documentation does not expose pause/resume or rollback controls. | Backend implements pause/resume/cancel, but frontend exposes none. Pause occurs only after a node boundary; an early pause may create a minimal marker checkpoint. | `runs.py::pause_run`, `resume_run`, `_ensure_resumable_checkpoint`; frontend API inventory. | API behavior exceeds the evidenced product and is not an exact UI match. |
| B10 | `partial` | Visible states include draft, in-progress, failed, completed; Google sync may lag. | Store supports draft, queued, running, paused, synthesizing, completed, failed, cancelled, blocked. Some are visible in history, but there is no faithful Google state presentation. | Google Help lines 90–105; `app/store/models.py::RunStatus`; frontend status helpers. | Core lifecycle exists with different state vocabulary and controls. |
| B11 | `partial` | Intensive literature review, idea tournament, and synthesis occur after start. | Those phases execute for the engine provider, but literature may be disabled/degraded and the graph normally uses very small pools/budgets. | Google Help lines 95–97; `generator/graph.py`; `coordinator_strategy.py`. | Nominal phase match does not imply depth or robustness match. |
| B12 | `incorrect` | `Configure Run` is a product action at the goal's top right. | Tier/focus cards are embedded inside a generated setup document in the chat timeline. | Google Help lines 80–85; local goal screenshots; `chat_timeline_run_spec_card.tsx`; live UI. | Screen placement and interaction sequence differ. |
| B13 | `missing` | Run type selection is tied to access/credit availability and reports an appropriate compute choice. | No estimated time, credit cost, eligibility, or availability appears in setup. | Google Help; repository search; live setup. | Users cannot make the same run decision. |
| B14 | `partial` | Scientist can inspect prior draft, in-progress, and completed goals with dates. | A recent-run list exists and persists dates/status. It merges globally seeded demo runs into personal history. | Google Help lines 98–105; `runs.ts::loadRunHistory`; `home_recents.tsx`. | History partially matches, but demos contaminate the product record. |
| B15 | `incorrect` | Past research is the scientist's own goal history. | Seeded deterministic mock runs are displayed alongside real runs without a consistently prominent mock designation. | `runs.ts:200-227`; `seed.py`; live home and Learning tab. | Mock content can be mistaken for implemented scientific output. |

### C. Active-run monitoring and progress presentation

| ID | Class | Google behavior | Current behavior and exact difference | Evidence | Fidelity consequence |
|---|---|---|---|---|---|
| C01 | `partial` | Shows active execution state and idea-tournament progress. | Home recents render four fixed steps driven by the last event type. | Local `esn-run-executing-idea-tournament.jpg`; `home_recents_run_steps.tsx`; `home_recents_data.ts`. | A coarse progress indicator exists. |
| C02 | `missing` | Shows time remaining. | No ETA is calculated or rendered. | Local run screenshot; frontend search. | A visible Google field is absent. |
| C03 | `missing` | Shows `Sources Analyzed`. | Evidence counts exist in data/report, but the active-run surface does not render Google's metric. | Local run screenshot; `home_recents_run_steps.tsx`; live UI. | Active monitoring does not match. |
| C04 | `missing` | Shows `Ideas explored`. | Hypothesis counts exist, but the active progress card does not render the metric. | Local run screenshot; same implementation evidence. | Active monitoring does not match. |
| C05 | `missing` | Shows an activity log with tasks and statuses. | Backend persists SSE events and a developer Logs/diagnostics panel, but the user-facing run progress is not Google's scientific activity list. | Local run screenshot; `layout_diagnostics.tsx`; `engine_adapter/events.py`. | Internal diagnostics are not a faithful activity surface. |
| C06 | `incorrect` | Progress represents a continuously evolving multi-agent tournament. | Four UI steps collapse literature into Generation and proximity/evolution/meta/deep verification into Tournament. | `STAGE_STEP_INDEX` in `home_recents_data.ts`. | The displayed phase model misstates the actual and target processes. |
| C07 | `incorrect` | Progress should not move backward. | Engine constants explicitly permit deep verification 81–84 followed by proximity 75–85. | `engine/constants.py:124-148`. | Raw progress consumers can regress visibly. |
| C08 | `missing` | Current footage exposes coherent executing tasks, not merely a spinner. | Run-detail tabs show partial artifacts, but no dedicated execution page combines live task, sources, idea count, and remaining time. | Local footage/screenshots; `run_detail.tsx`; live UI. | The central long-running screen is absent. |
| C09 | `non-faithful extension` | Public evidence does not expose developer diagnostics/model logs in the main research shell. | Clone has a Logs panel and settings for a client-side key. | `layout_diagnostics.tsx`; `settings_dialog.tsx`. | Developer controls change the 1:1 product surface. |
| C10 | `partial` | Users can revisit and see live/replayed updates. | SSE event log replays from sequence zero and refetches touched collections. | `use_run_stream.ts`; `run_detail_data.ts`; `runs.py::stream_events`. | Real live updating exists, at a different granularity and presentation. |

### D. Goal Report, Ideas, Knowledge Base, Summary, specifications, and exports

| ID | Class | Google behavior | Current behavior and exact difference | Evidence | Fidelity consequence |
|---|---|---|---|---|---|
| D01 | `incorrect` | Tabs are ordered `Ideas`, `Knowledge Base`, `Summary`, `Run Specifications`. | Tabs are ordered `Goal Details`, `Learning`, `Research Overview`, `All Ideas`. | Google Help lines 106–115; local captures; `run_tabs.ts`; `run_detail_shell.tsx::TAB_LABELS`. | The main deliverable's information architecture is wrong. |
| D02 | `partial` | Ideas shows the full Elo-ranked proposal leaderboard. | `IdeasTab` sorts all fetched hypotheses by Elo and renders scores. | Google Help lines 108–111; `ideas_tab.tsx`; live desktop. | Core leaderboard behavior matches. |
| D03 | `missing` | Ideas separates `High Potential` and `Non-Viable`. | Clone renders one ranked list; no product bucket model or labels exist. | Google Help line 111; local Ideas capture; `ideas_tab.tsx`. | A primary decision aid is absent. |
| D04 | `missing` | Ideas summary shows Agent Insights and counts such as high-potential, non-viable, verified ideas, sources analysed. | Clone's Ideas page has no Agent Insights summary/stat row. | Local `esn-ideas-agent-insights*.jpg`; live UI. | Report overview and target terminology are missing. |
| D05 | `partial` | A proposal opens to detailed rationale and evidence; current product examples can include a generated diagram and `Chat with Agent`. | Clone detail shows statement, mechanism/effect, review, lineage, safety, claim edges, and latest match; it has no generated diagram or proposal-scoped agent. | Local `esn-high-potential-*` and detail captures; `ideas_detail_pane.tsx`. | Useful detail exists but not the target detail surface. |
| D06 | `non-faithful extension` | Google does not publicly show clone-specific provenance/safety/claim-edge panels in this exact form. | Clone adds origin, lineage, safety status, claim-edge summary, and debate-depth labels. | `ideas_detail_pane.tsx`. | These additions alter the visible 1:1 surface. |
| D07 | `incorrect` | Knowledge Base is centralized technical documentation and detailed data for rapid reference. | `LearningView` mechanically converts at most the first three evidence abstracts into title/summary/detail sections. | Google Help line 112; local Knowledge Base capture; `run_detail_learning.tsx::learningSections`. | This is an abstract viewer, not Google's Knowledge Base. |
| D08 | `incorrect` | Knowledge Base content is a synthesized result of the run. | With no evidence, `LearningView` displays a hard-coded “Co-Scientist is assembling…” placeholder and generic source attribution. | `run_detail_learning.tsx:322-360`. | A shell can appear populated without learned content. |
| D09 | `partial` | Knowledge Base has searchable references with openable citations. | Clone filters title/source/authors by substring and provides an Open link when URL exists. | Local Knowledge Base capture; `run_detail_learning.tsx::ReferencesBlock`. | Narrow reference-list behavior matches. |
| D10 | `incorrect` | Summary is a synthesized overview of the entire research effort. | `Research Overview` presents engine overview, Specific Aims, top ideas, and a generic match-count sentence; it is not the target Summary/Agent Insights composition. | Google Help line 113; local Summary capture; `run_detail_overview.tsx`. | Summary semantics and presentation differ. |
| D11 | `incorrect` | Run Specifications displays the exact finalized challenge, focus areas, preferences, and run parameters. | `Goal Details` displays client-generated requirements/attributes/criteria and tier/focus. | Google Help line 114; `run_detail.tsx::GoalDetailsView`. | It preserves the clone's wrong plan contract. |
| D12 | `missing` | Report-level `Open Agent` supports follow-up. | No frontend component or API client method is present. | Google Help line 115; frontend search. | Follow-up is absent. |
| D13 | `missing` | `Open in NotebookLM`. | Explicitly absent; a layout test asserts `NotebookLM` is not rendered. | Google Help lines 119–126; `layout.test.tsx:122`. | Verified export/integration is missing. |
| D14 | `missing` | Public sharing can be enabled and a unique link copied. | No sharing state, route, access token, or UI. | Google Help lines 127–136; repository search. | Collaboration/share behavior is missing. |
| D15 | `missing` | Download menu offers report download options. | Backend exposes JSON and Markdown endpoints and CLI download; frontend has no report download action. “Download response” only downloads chat-card text. | Google Help lines 137–145; `runs.py::get_report_markdown`; `chat_timeline_message_actions.tsx`; live UI. | Product export is missing despite an API representation. |
| D16 | `missing` | Report citations are clickable and claims are deeply verified. | Evidence links are clickable, but hypothesis/report claims do not map cleanly to verified inline sources; latest real report marked all 13 claims unsupported. | Google I/O line 315; SQLite report and citations; `report_markdown.py`. | The report fails the target's strongest current output promise. |
| D17 | `incorrect` | Non-viable ideas remain explicitly categorized for scientist inspection. | Proximity deletes all but one high-similarity hypothesis per cluster; safety/contradiction gates remove others; the UI lacks an excluded/non-viable archive. | Google Help line 111; `proximity.py::_resolve_cluster_duplicates`; `safety_screen.py`; `report_render.py`. | The clone loses or hides ideas Google presents as an actionable bucket. |
| D18 | `partial` | Reports contain detailed proposals, experiments, literature, and synthesis. | Engine hypotheses include mechanism, explanation, experiment and a terminal overview/NIH aims. | Nature supplement examples; `models.py::Hypothesis`; `research_overview.py`; latest real report. | Structural subset exists but is much smaller and less grounded. |
| D19 | `divergent` | Meta-review produces the final comprehensive research overview. | A separate terminal `research_overview` node receives only top idea text/Elo plus compact meta-review, not all underlying artifacts. | Nature lines 322–323; supplement pseudocode; `research_overview.py::_summarize_top_hypotheses`. | Final synthesis has different responsibility and information. |
| D20 | `missing` | Published examples include research-contact suggestions with justification. | No contact schema, prompt, model, store field, or UI exists. | Nature supplement §10.12; local `als-research-overview-and-contact.md`; `research_overview.md` schema/template. | A disclosed Meta-review output is absent. |
| D21 | `partial` | Can format output as NIH Specific Aims. | Terminal node always emits an NIH aims object rather than making output format a scientist preference. | Nature paper; local Specific Aims artifacts; `research_overview.py`. | Format exists but selection and breadth differ. |
| D22 | `incorrect` | Current detailed product examples use polished long-form scientific prose and numerous linked references. | Local real report had five ideas, three evidence records, ~21k characters, and definitive statements despite zero supported citation states. | Local extracted output word counts; SQLite inspection; report excerpt. | Output depth and evidentiary discipline are far below the demonstrated target. |
| D23 | `partial` | Elo/win-loss details are observable. | Clone shows Elo and win/loss summary and latest match. | Nature ranking description; `ideas_detail_pane.tsx`. | Material tournament transparency partially matches. |
| D24 | `missing` | Product footage shows per-idea `Chat with Agent`. | No idea-scoped follow-up action exists. | Local high-potential capture; frontend search. | Iterative proposal refinement is missing. |
| D25 | `incorrect` | Google calls the deliverable a Goal Report and its canonical terms are stable. | UI mixes “session,” “run,” “Goal Details,” “Learning,” “Research Overview,” and “All Ideas.” | Google Help; `settings_dialog.tsx`; `run_detail_shell.tsx`; live UI. | Minor terminology drift compounds the information-architecture mismatch. |

### E. Agent coalition, responsibilities, prompts, inputs, and outputs

| ID | Class | Google behavior | Current behavior and exact difference | Evidence | Fidelity consequence |
|---|---|---|---|---|---|
| E01 | `matched` | Canonical coalition is Supervisor plus Generation, Reflection, Ranking, Proximity, Evolution, and Meta-review. | All seven roles execute as named engine nodes/functions. | Nature lines 315–325; `generator/graph.py::_add_workflow_nodes`. | Roster naming and broad decomposition match. |
| E02 | `divergent` | Supervisor is an adaptive planner that breaks the goal into tasks and allocates worker resources. | `supervisor_node` is one initial domain-guidance call. Its own prompt says the pipeline is fixed and it must not plan execution. | DeepMind lines 149–164; supplement pseudocode; `supervisor.md`; `supervisor.py`. | The most important agent has a different job. |
| E03 | `partial` | Supervisor computes comprehensive statistics periodically. | `orchestrator_node::_compute_stats` computes pool/review/match/Elo/yield/budget flags after work phases. | Nature lines 313–327; `orchestrator.py:112-157`. | The statistics subset is real. |
| E04 | `divergent` | Supervisor strategically weights and samples specialist workers. | Pure `decide_next_task()` applies fixed precedence and alternates generate/evolve on equal count yield. The code explicitly says “the code decides, the model only advises.” | Nature lines 326–329; `scheduling/policy.py:1-15,142-272`. | No model-driven allocation or sampling exists. |
| E05 | `partial` | Generation uses literature exploration. | Tool-based generation can search configured MCP sources, draft gaps, and validate. Default inspected runtime uses PubMed; without tools it silently degrades to latent knowledge. | Nature lines 333–338; `generation/literature_tools/`; `coordinator_strategy.py`. | Working but source-limited and optional. |
| E06 | `partial` | Generation uses multi-turn simulated scientific debate, typically 3–5 turns and max 10. | Debate generation runs up to `DEBATE_MAX_TURNS=5`, with multiple debates in parallel. | Supplement prompt; `generation/debate.py`; `constants.py`. | Material technique matches. |
| E07 | `partial` | Generation iteratively identifies assumptions and subassumptions. | An assumptions prompt/path exists only in no-literature degraded mode and receives one quarter of ideas for pools ≥4. It is not used alongside grounded generation. | Nature line 336; `generation/assumptions.py`; `coordinator_strategy.py:144-155`. | Technique exists under the wrong allocation conditions and depth. |
| E08 | `incorrect` | Research expansion explicitly examines existing hypotheses plus prior overview/feedback for unexplored space. | `RESEARCH_EXPANSION` is an enum and shares a debate prompt; no task records that method and no dedicated expansion selection/coverage analysis runs. | Nature line 337; `generation/techniques.py`; repository search for `RESEARCH_EXPANSION`. | A name/re-entry convention is being treated as a full technique. |
| E09 | `partial` | Reflection initial review is fast, tool-free, and filters flawed/non-novel/unsafe work. | `review_node` produces generic scored reviews and a later regex safety node filters. It does not implement the disclosed pass-then-full-review cascade for every hypothesis. | Nature lines 339–343; `review.py`; `safety_screen.py`. | Initial review semantics and filtering order differ. |
| E10 | `incorrect` | Full review uses external tools/web search and literature to test correctness, quality, and novelty. | Full review runs on only one current leader, with `domain_context=""` and `tool_instructions=""`; no live retrieval occurs in `_apply_extra_review_types`. | Nature lines 343–344; `deep_verification.py:126-167,204-207`; `full_review.md`. | A critical verified review mode is tokenized, not materially reproduced. |
| E11 | `partial` | Deep verification recursively decomposes assumptions/subassumptions, decontextualizes them, independently evaluates correctness, and distinguishes fundamental errors. | Top three ideas receive one LLM call returning probes and a fundamental flag/verdict. The prompt does not recursively decompose every assumption or retrieve evidence. | Nature lines 345–347; supplement examples; `deep_verification.py`; `deep_verification.md`. | The concept is present at much lower rigor. |
| E12 | `partial` | Observation review searches long-tail observations and judges superior explanation. | When literature review is enabled, initial generated hypotheses are classified against one shared literature synthesis; evolved children bypass this node. | Nature lines 348–349; `reflection.py::_build_analysis_tasks`; graph evolve edge. | Only initial ideas receive a limited observation review. |
| E13 | `incorrect` | Simulation review is a regular Reflection strategy covering mechanisms/experiments. | It runs only on one leader after deep verification and uses no external context. | Nature line 350; `deep_verification.py::_EXTRA_REVIEW_TYPES`; `simulation_review.md`. | Merely exercising a prompt is not behavior parity. |
| E14 | `incorrect` | Recurrent/tournament review adapts full reviews using growing knowledge and tournament results. | `ReviewType.RECURRENT` maps to `meta_review`; no recurrent per-hypothesis review is dispatched. Existing hypotheses are intentionally not re-reviewed. | Nature lines 351–352; `review_types.py`; `review.py:334-345`. | The sixth review mode is mislabeled rather than implemented. |
| E15 | `partial` | Ranking uses Elo 1200 and pairwise scientific comparison. | New hypotheses start at 1200 and judged matches update Elo. | Nature Ranking section; `constants.py::INITIAL_ELO_RATING`; `ranking_elo.py`. | Core invariant matches. |
| E16 | `partial` | Top proposals use multi-turn scientific debate; lower proposals use single-turn comparison. | At least one contender at/above median gets exactly three repeated judge calls; both below median get one. | Nature Ranking; `ranking.py::_matchup_debate_turns`; `constants.py`. | Broad allocation matches; top threshold/turn count are clone-defined. |
| E17 | `incorrect` | Scientific debate is a dialogue in which competing positions are developed before a verdict. | The same judge re-runs the same prompt with prior verdict summaries; there are no distinct advocate/opponent/debater roles. | Published ranking-debate prompt/artifact; `ranking.py::judge_matchup`, `_append_debate_context`. | Repeated judgments are not the published debate mechanic. |
| E18 | `incorrect` | Ranking accuracy work explicitly reduces positional bias. | Invalid/off-schema winners silently default to contender A. | Nature ablation line 410; `ranking.py::_parse_matchup_winner`. | The fallback introduces deterministic A-side bias. |
| E19 | `matched` | Pairing prioritizes similar, newer, and top-ranked ideas. | `build_weighted_pairings()` uses proximity cluster, match count/recency proxy, and Elo weighting. | Nature Ranking section; `ranking_matchmaking.py`; `ranking.py::_build_tournament_pairings`. | The disclosed matching priorities are materially present. |
| E20 | `partial` | Proximity asynchronously builds a goal-aware proximity graph for clustering, deduplication, and exploration. | One LLM call clusters the whole pool and persists qualitative edges. It receives Supervisor guidance but the prompt's goal awareness is indirect; the graph is not computed asynchronously beside other agents. | Nature line 320; `proximity.py::_fetch_similarity_clusters`; `proximity_graph.py`. | Graph functionality exists, architecture and metric differ. |
| E21 | `incorrect` | Proximity supports deduplication while preserving tournament/exploration context. | Every high-similarity member except the current best is deleted from the active pool based on a fragile 100-character text-prefix rematch. | `proximity.py::_match_hypothesis_to_cluster`, `_resolve_cluster_duplicates`. | Potentially valuable alternatives disappear and matches cannot revisit them. |
| E22 | `unverifiable` | Google does not publish its exact proximity metric or embedding model. | Clone maps high/medium/low to 1.0/0.6/0.3 and labels the method `llm-cluster`. | `proximity_graph.py:10-33`. | Clone-specific values must remain marked inferred. |
| E23 | `matched` | Evolution creates new hypotheses without replacing parents; children re-enter the tournament. | Immutable children are appended and parents remain active. | Nature Evolution; `evolve.py`; `evolve_results.py`. | Critical invariant matches. |
| E24 | `partial` | Evolution includes grounding, coherence/practicality/feasibility, inspiration, combination, simplification, and out-of-box operators. | One generic “refine and preserve core concept” prompt runs per top idea. It omits explicit combination and out-of-box strategy selection and does not call retrieval tools during evolution. | Nature Evolution; published evolution prompts; `evolution.md`; `evolve.py`. | Most of the strategy library is collapsed into generic rewriting. |
| E25 | `incorrect` | Evolution can synthesize one or several top hypotheses and deliberately diverge. | Context is sampled only from other leaders being evolved and the prompt explicitly forbids borrowing/replacement, making true combination/out-of-box evolution unlikely. | Nature line 321; `evolve.py::_build_evolution_tasks`; `evolution.md`. | Prompt policy conflicts with disclosed operators. |
| E26 | `partial` | Meta-review synthesizes recurring insights and guides later work. | It synthesizes strengths, weaknesses, themes, recommendations and feeds review/ranking/evolve/generation prompt helpers. | Nature lines 322, 328–329; `meta_review.py`; prompt formatting helpers. | Core feedback idea exists. |
| E27 | `incorrect` | Meta-review reads **all reviews and debate transcripts**. | `_collect_review_summaries()` keeps only the latest generic review per hypothesis and omits debate transcripts. | Supplement pseudocode; `meta_review.py:205-241`. | The learning signal lacks most target evidence. |
| E28 | `incorrect` | Meta-review feedback is simply appended to every other agent's next prompt; Generation uses it selectively. | Feedback is threaded to several prompts, but initial-only reflection never receives later feedback; proximity gets only Supervisor guidance; deep/full/simulation omit it; research overview is separate. | Nature lines 328–329; graph topology; prompt call sites. | The global feedback invariant is only partially wired. |
| E29 | `incorrect` | Meta-review also generates the final overview and research contacts. | `meta_review_node` returns only a compact critique. Separate `research_overview_node` produces overview/aims and no contacts. | Nature lines 322–323; `meta_review.py::_build_meta_review`; `research_overview.py`. | Agent responsibility and output contract differ. |
| E30 | `incorrect` | Published prompts are detailed but domain-general scientific prompts. | Local generation/evolution forces every hypothesis into the software-like sentence “We want to develop [X] to enable [Y]” and limits it to 2–3 sentences. | Official supplement §9.1; local published prompts; `generation_*.md`; `evolution.md`. | The clone distorts biomedical/mechanistic hypotheses and compresses proposal content. |
| E31 | `partial` | Published eight prompts cover generation ×2, observation reflection, ranking ×2, evolution ×2, meta-review. | Several local templates derive from those prompts, but JSON constraints, forced format, extra criteria, and collapsed strategies make them non-verbatim. | `research/extracted-artifacts/prompts/`; engine prompt templates. | Prompt ancestry exists; behavior is not prompt-identical. |
| E32 | `incorrect` | Supervisor plan fields should drive later decisions. | `ranking_phase` has no reader; performance assessment, adjustment recommendations, and output preparation are stored but never reread; generation does not read synthesized preferences. | `schemas/planning.py` comments at 61–62, 153–157, 217–220. | Large parts of the expensive plan are dead output. |

### F. Supervisor orchestration, parallelism, task allocation, and termination

| ID | Class | Google behavior | Current behavior and exact difference | Evidence | Fidelity consequence |
|---|---|---|---|---|---|
| F01 | `divergent` | Global asynchronous task queue with specialized worker processes. | Static LangGraph has a single conditional loop point and executes one specialist node at a time. | Nature abstract/lines 139, 157, 313–327; `generator/graph.py`. | The execution substrate is fundamentally different. |
| F02 | `partial` | Agents/tasks can run in parallel. | Per-hypothesis generation, review, ranking, verification, and evolution calls use `asyncio.gather`, often capped at five. Cross-agent phases do not overlap. | DeepMind line 163; call sites in `coordinator.py`, `ranking.py`, `deep_verification.py`, `evolve.py`. | Local fan-out matches only intra-node parallelism. |
| F03 | `missing` | Agent results create follow-up tasks in the global queue. | Graph edges predetermine follow-ups; result types do not enqueue arbitrary tasks. | Supplement Supervisor pseudocode; `graph.py::_add_workflow_edges`. | Emergent task allocation is absent. |
| F04 | `divergent` | Freeform Supervisor can choose any appropriate specialist based on state. | `_TASK_ROUTES` allows six fixed loop task types and maps evolve to mandatory meta-review. | DeepMind line 163; `graph.py::_TASK_ROUTES`. | The model cannot formulate or allocate new work. |
| F05 | `incorrect` | Supervisor considers relative effectiveness of generation methods and evolution. | Clone defines yield as net pool-size delta attributed to the last generate/evolve task. It does not measure hypothesis quality gain or individual generation-method effectiveness. | Nature line 326; `orchestrator.py::_yields`. | Resource allocation optimizes count, not disclosed effectiveness. |
| F06 | `unverifiable` | Exact Google termination predicates and weights are private. Published pseudocode uses MaxIdeas and MatchesPerIdea plus Supervisor terminal decisions. | Clone uses min average match coverage 1.0, top-Elo stability two cycles, minimum two work cycles, iteration/call/task/wall-clock budgets. | Supplement pseudocode; `scheduling/policy.py::MIN_*`, `Budget`. | Termination cannot be claimed as matched. |
| F07 | `incorrect` | Tournament can continuously add fresh knowledge and improve without observed saturation. | Default engine max iteration is one; product tiers cap at four. Generation and evolution alternate deterministically. | DeepMind line 176; Nature scaling; `constants.py`; `run_modes.py`. | Test-time compute scaling is truncated before target behavior emerges. |
| F08 | `partial` | Persistent state permits recovery. | Node snapshots serialize hypotheses, metrics, task history, proximity graph, safety and other state. | Nature line 314; `checkpoint.py`; `state.py`. | State durability is a genuine match at single-service scale. |
| F09 | `incorrect` | Independent worker failures should be retried/managed without losing the long run. | Some per-item calls are isolated, others make `asyncio.gather` abort the whole batch; app catches the workflow exception and marks run failed. Scheduler retry fields are not populated from real node failures. | `review.py:106-110`; `runs.py::_mark_workflow_failed`; `SchedulerStats` construction. | Fault isolation is inconsistent and not worker-durable. |
| F10 | `non-faithful extension` | Exact production observability is undisclosed. | Clone exposes detailed SSE event types, developer logs, prompt saving, and metrics. | `engine_adapter/events.py`; `layout_diagnostics.tsx`; `models.py::ExecutionMetrics`. | Useful but not evidenced as a 1:1 product surface. |
| F11 | `incorrect` | Continuous computation can spend majority compute on verification. | Initial/generation and generic review calls dominate small runs; deep verification covers top three, and full/simulation only one. | DeepMind line 169; `DEEP_VERIFICATION_TOP_K`; `deep_verification.py`. | Compute allocation conflicts with the current Google emphasis. |
| F12 | `partial` | State is periodically fed back into subsequent work. | Meta-review, prior ideas, removed duplicates, and review context feed selected prompts. | Nature lines 313–329; engine prompt call sites. | Feedback exists but is incomplete and compressed. |
| F13 | `incorrect` | Meta-review and overview may run periodically during the long computation. | Meta-review only heads the evolve branch; overview only runs terminally. | Supplement pseudocode `DecideNextSteps`; `graph.py`. | Periodic synthesis/exploration feedback is absent. |
| F14 | `missing` | Multiple workers can operate on different queued tasks and resources simultaneously. | No worker lease, process pool, durable task table, or distributed executor exists. FastAPI `BackgroundTasks` runs each workflow in the API process. | Nature architecture; `runs.py::_run_workflow_task`; store schema. | Scaling and crash isolation cannot match. |
| F15 | `partial` | New and changed ideas are reviewed/ranked as the run grows. | Appended children receive generic review, safety, ranking, and deep verification if they enter top K. | Graph evolve branch; `review.py`; `ranking.py`. | Core loop continuity exists. |

### G. Retrieval, tools, grounding, evidence, and citation verification

| ID | Class | Google behavior | Current behavior and exact difference | Evidence | Fidelity consequence |
|---|---|---|---|---|---|
| G01 | `missing` | Web search and retrieval are primary tools for current, grounded knowledge. | Default runtime has no general web-search tool. It uses PubMed/PMC through the reference MCP. | Nature lines 401–403; DeepMind line 169; `config/tools.yaml`; live `/status`. | General and non-biomedical coverage is far narrower. |
| G02 | `partial` | Uses scientific literature search/retrieval extensively. | PubMed metadata/full text works and was live during audit. A recent golden run retrieved six real PubMed records. | `engine/mcp_server/tools/lit_review/`; `/status`; `golden-run-indra-2026-07-12.json`. | Genuine but small, domain-specific match. |
| G03 | `missing` | Current Google disclosure names ChEMBL. | No ChEMBL MCP implementation or enabled config exists in the repository. | DeepMind line 169; MCP tool inventory. | Named production database is missing. |
| G04 | `missing` | Current Google disclosure names UniProt. | No UniProt MCP implementation or enabled config exists. | DeepMind line 169; MCP tool inventory. | Named production database is missing. |
| G05 | `missing` | AlphaFold can be invoked as a specialized model in selected workflows. | Local references include a Google AlphaFold example, but the engine has no AlphaFold client/tool. | Nature line 403; DeepMind line 170; MCP inventory; extracted tool-use artifact. | Disclosed specialized-model behavior is absent. |
| G06 | `partial` | Domain-specific databases constrain a search space. | INDRA CoGEx tools support statements, associations, drug/trial, pathways, subnetworks, and enrichment when a specific YAML is enabled. Runtime `tools_config=null`, so default live run did not enable them; golden run did. | Nature line 402; `engine/mcp_server/tools/indra_cogex/`; configs; live status. | Capability exists but is not the canonical runtime and does not match named Google DBs. |
| G07 | `partial` | Can search across broad scientific domains. | OpenAlex tool code exists, and example configs mention arXiv/Scholar, but default config is PubMed. The external arXiv/Scholar server is not in this repo/runtime. | `openalex_search.py`; config examples; `config/tools.yaml`. | Code/config presence does not yield broad product behavior. |
| G08 | `incorrect` | Grounded review quality depends on search; missing search reduces novelty/correctness and should be visible as degradation. | Engine can disable the literature/reflection nodes and generate from latent model knowledge. Runs can still complete and publish reports with zero evidence. | Nature ablation lines 408–409; `coordinator_strategy.py`; SQLite real runs with evidence=0. | The system can present ungrounded completion as ordinary success. |
| G09 | `incorrect` | Literature is gathered iteratively as agents generate, review, rank, and evolve. | One initial literature-review synthesis is reused. Full/simulation/evolution/ranking do not perform live search, and subsequent `generate` routes skip the literature-review node. | Nature agent descriptions; graph topology; tool call sites. | Knowledge does not continuously refresh with the tournament. |
| G10 | `partial` | Claims cite relevant literature. | Hypotheses can carry `[C*]` keys mapped to article metadata; citations are classified and persisted. | `generation/citations.py`; `app/citations.py`; store schema. | Citation plumbing exists. |
| G11 | `incorrect` | Current product promises deeply verified claims with clickable citations. | Clone allows speculative/insufficient claims to publish. The latest inspected real report had 13 unsupported citations and no verified/partial citations. | Google I/O line 315; `claim_grounding.py:177-180`; SQLite report/citations. | This is a direct contradiction of the target's current product claim. |
| G12 | `incorrect` | Verification should establish claim-source support, not merely source existence or token overlap. | Default deterministic assessor uses Jaccard overlap plus negation markers; LLM failures silently fall back to it. | `claims.py::deterministic_assessor`; `claim_verifier.py:11-18,152-166`. | Weak fallback can determine scientific publication state. |
| G13 | `incorrect` | A publication-quality verifier should handle paraphrases and contradictions robustly. | Repository eval accuracy is 0.75; every hard-paraphrase case scores 0; contradiction recall is 0.75. | `citation-entailment-deterministic-2026-07-12.json`; failed `evaluations.smoke`. | Known verifier weakness remains above the publish path. |
| G14 | `partial` | Clickable evidence should resolve to the source and ideally the supporting context. | Claim edges store exact quotes, offsets, evidence ID, URL and assessor; source links open. | `claims.py::SupportSpan`, `assess_claim`; `ideas_detail_pane.tsx`. | Strong provenance primitive exists. |
| G15 | `incorrect` | Unsupported content should be clearly bounded by uncertainty and not masquerade as verified. | The report has a citation-audit footer but states unsupported mechanistic claims declaratively; `allow_speculative=True` is global and not reflected inline. | Latest real report; `claim_grounding.py`; `report_markdown.py`. | Readers can mistake speculation for evidence-backed findings. |
| G16 | `incorrect` | Contradiction/verification feedback should refine hypotheses during the tournament. | App-side claim grounding occurs during final engine drain, after the engine tournament has completed; comments claiming “pre-tournament” are only true for the mock path. | `engine_adapter/engine_stream.py::_persist_and_report`; `engine_adapter/drain.py`; `claim_grounding.py` comments. | Real engine ranking never sees claim-verifier results. |
| G17 | `incorrect` | A contradicted idea should not rank/publish. | Final drain excludes contradicted hypotheses from stored app results/report, but the engine may already have ranked/evolved them. | `report_render.py::_contradicted_hypothesis_ids`; engine drain order. | Safety at publication does not repair contaminated tournament state. |
| G18 | `partial` | Full texts and PDFs may be retrieved. | Literature node can discover/fetch PDFs when configured; default PubMed full-text tool retrieves PMC content. | `literature_review/content.py`; `pubmed_search_with_fulltext.py`. | Retrieval primitive exists. |
| G19 | `missing` | Hundreds of scientist-supplied PDFs and other data can condition a goal. | No product ingestion pipeline, document chunk index, multimodal parser, or scale test exists. | Nature lines 308–310; frontend attachment flow; store attachment schema. | Context scale is orders of magnitude smaller. |
| G20 | `missing` | Private publication/experimental repository is searchable by the agents. | Text attachment rows use basic keyword search and are not bound into engine tool calls. | Nature line 403; `run_corpus.py`; engine options. | Private grounding is absent. |
| G21 | `unverifiable` | Exact current Google citation verifier, retrieval ranking, source count, and retraction policy are undisclosed. | Clone uses its own citation-state resolver and claim NLI. | Google sources; `app/citations.py`; `claims.py`. | These mechanics cannot be called matched even where sensible. |
| G22 | `partial` | Literature review generates a knowledge base of scientific facts/gaps. | Engine produces `articles_with_reasoning` and article metadata, but there is no durable structured fact/contradiction knowledge base. | Nature line 334; `literature_review/node.py`; `state.py`. | Synthesis exists; knowledge representation does not. |
| G23 | `incorrect` | Source availability limitations are a disclosed system limitation, not a reason to invent certainty. | Failure sentinel causes a latent-knowledge fallback and the UI does not force a conspicuous ungrounded-run state. | Nature limitations; `LITERATURE_REVIEW_FAILED`; `coordinator_strategy.py`. | Degraded scientific validity is under-signalled. |
| G24 | `non-faithful extension` | Exact production claim graph is undisclosed. | Clone adds sentence-split atomic claims, exact spans, and claim-edge UI. | `claims.py`; `ideas_detail_pane.tsx`. | Valuable extension, but not proven Google parity. |

### H. Hypothesis lifecycle, debate, ranking, evolution, and diversity

| ID | Class | Google behavior | Current behavior and exact difference | Evidence | Fidelity consequence |
|---|---|---|---|---|---|
| H01 | `matched` | Every new idea starts at Elo 1200. | `INITIAL_ELO_RATING=1200`. | Nature supplement; `constants.py`. | Exact invariant match. |
| H02 | `partial` | Tournament evaluates and ranks all ideas continuously. | Clone runs configured pair counts per ranking node; ideas may have only one average match before termination. | Supplement pseudocode; `policy.py::MIN_MATCH_COVERAGE_DEFAULT`; run artifacts. | Tournament exists at much lower coverage. |
| H03 | `unverifiable` | Google K-factor is unpublished. | Clone uses constant engine K=24; app has a separate default K. | `constants.py::ELO_K_FACTOR`; `app/elo.py`. | Cannot claim Elo dynamics match. |
| H04 | `incorrect` | Elo updates should follow sequential match state or a disclosed concurrent policy. | Match judgments are computed concurrently from pre-round ratings, then applied; later match prompts cannot observe earlier same-round Elo changes. | `ranking.py::_run_tournament_matchups`; `ranking_results.py`. | Tournament dynamics differ from a continuous live tournament. |
| H05 | `partial` | Debate rationale and transcripts inform later work. | Transcripts are persisted and shown for matches, but Meta-review omits them and each turn is a judge refinement. | `ranking.py`; `meta_review.py`; store matches. | Observable transcript exists without target learning semantics. |
| H06 | `partial` | Proximity supports diversity and efficient comparison. | Cluster-aware pairing exists, and generation prompts emphasize diversity. | `ranking_matchmaking.py`; `generation_*.md`. | Some diversity pressure is real. |
| H07 | `incorrect` | Proximity graph is a maintained landscape used for scientist exploration. | UI has no graph/cluster exploration, and the engine replaces graph members with one survivor for high-similarity clusters. | Nature line 320; `proximity_graph.py`; frontend inventory. | Landscape behavior is absent. |
| H08 | `matched` | Evolution produces immutable children with lineage. | Parent IDs, generation depth, origin and children are persisted; parents remain. | `models.py::Hypothesis`; `evolve_results.py`; store drain; UI lineage. | Material match. |
| H09 | `incorrect` | Evolution continually improves top ideas with several distinct operators. | Fixed top-K generic refinements are run once per selected parent per evolve phase. No operator success statistics guide future allocation. | Nature Evolution; `evolve.py`; `orchestrator.py::_yields`. | Evolution is shallow and homogeneous. |
| H10 | `partial` | Hypotheses are reviewed for default alignment/plausibility/novelty/testability/safety. | Generic review schema now emits corresponding scores (`relevance` stands for alignment), plus extra axes. | Nature default criteria; `output_criteria_real_review.json`; review schemas. | Score fields match, but downstream use and evidence quality do not. |
| H11 | `incorrect` | Reviews should filter inaccurate or stipulated non-novel ideas. | Generic score reviews are attached but do not directly filter low-score hypotheses; safety and explicit contradictions filter. Low-quality ideas can remain and publish. | Nature Reflection; `review.py`; graph/store drain. | Evaluation does not enforce the disclosed filter. |
| H12 | `incorrect` | Tournament selection should combine review knowledge, debate, evidence and evolving feedback. | Ranking prompt sees generic latest review/reflection/deep summary and meta-review, not full review stacks or fresh tools. | `ranking_prompt.py`; `ranking.md`. | Pairwise decisions have a much thinner evidence state. |
| H13 | `partial` | New hypotheses compete rather than inherit superiority. | Children initialize at 1200 and re-enter ranking. | `evolve_results.py`; `constants.py`. | Critical behavior matches. |
| H14 | `incorrect` | Long compute explores broad directions and can avoid premature convergence. | Pool sizes and hard iteration caps are small; exact-text and high-similarity deletion plus forced common sentence format increase convergence. | DeepMind line 168; run tiers; generation prompts; proximity. | Diversity and test-time scaling are constrained. |
| H15 | `incorrect` | Hypothesis outputs are detailed domain-expert proposals. | Generation debate forces 2–3 sentence action-oriented “develop X to enable Y” ideas; explanation/experiment are later schema fields. | Official prompt §9.1; local `generation_after_debate.md`. | Form and reasoning density differ from published outputs. |
| H16 | `partial` | Ideas include mechanisms and experiments for validation. | `Hypothesis` has explanation, experiment, novelty and grounding fields; real reports render mechanisms/effects. | `models.py`; latest real report. | Structural match, with weaker grounding. |
| H17 | `incorrect` | Observation positives may be appended to hypotheses. | Reflection notes are stored separately and not appended as positive observations to the hypothesis content. | Nature line 349; `reflection.py::_apply_reflection_results`. | The disclosed enrichment behavior is absent. |
| H18 | `incorrect` | Incorrect non-fundamental assumptions feed refinement rather than necessarily invalidating the core. | Deep-verification verdict is prompt context for ranking; evolution uses generic review/meta summaries, with no explicit fundamental-error repair contract. | Nature lines 345–346; `deep_verification.py`; `evolve_prompt.py`. | Error severity is not reliably propagated into repair. |
| H19 | `partial` | Human ideas can be combined with generated ideas. | API stores manual ideas in the same table, but UI is absent and evolution context selection only includes top leaders. | Nature expert-in-loop; `human_input.py`; `evolve.py`. | Backend substrate only. |
| H20 | `incorrect` | Meta-feedback should improve generation/reviews over repeated compute. | Reviews are incremental and do not revisit existing hypotheses; observation review is initial-only; no measured across-cycle review quality feedback controls scheduling. | Nature Meta-review ablation; `review.py`; `reflection.py`; `orchestrator.py`. | Self-improvement is much weaker than the named loop suggests. |

### I. Persistent context, memory, feedback propagation, and long-running state

| ID | Class | Google behavior | Current behavior and exact difference | Evidence | Fidelity consequence |
|---|---|---|---|---|---|
| I01 | `partial` | Persistent context memory stores system/agent state and supports restart. | Versioned serialized `WorkflowState` plus SQLite checkpoints preserve post-node state. | Nature lines 313–314; `checkpoint.py`; store checkpoint schema. | Genuine run-local memory match. |
| I02 | `divergent` | Shared memory and global task queue mediate asynchronous worker state. | One TypedDict snapshot is merged through LangGraph and serialized as JSON. | Supplement pseudocode; `state.py`; `checkpoint.py`. | Memory architecture and concurrency semantics differ. |
| I03 | `partial` | Tournament/review knowledge feeds later prompts. | Latest reviews, meta-review, prior ideas, literature synthesis, and removed duplicates feed selected nodes. | Prompt call sites; `state.py`. | Some cross-step memory exists. |
| I04 | `incorrect` | Meta-review uses all reviews/debates and propagates lessons globally. | It sees one latest review per idea and no debate transcripts; several agents never receive the critique. | `meta_review.py`; graph/prompt call sites. | Core learning channel is lossy. |
| I05 | `missing` | Scientist feedback is incorporated into the live system through the designated UI. | API message rows exist; frontend and most agent-specific feedback semantics are missing. | Nature lines 138, 142, 392–398; frontend inventory. | Human memory/steering is not a product behavior. |
| I06 | `missing` | Large scientist-provided corpus remains available throughout the run. | Attachments are a separate SQLite keyword corpus not injected into engine state/tools. | `run_corpus.py`; engine opts. | Private context does not persist into reasoning. |
| I07 | `partial` | State grows over long compute. | Hypotheses, matches, reviews, articles, meta-review, proximity graph and metrics accumulate within one run. | `state.py`; `models.py`; app schema. | Important run-local artifacts persist. |
| I08 | `missing` | Product supports continuing from report through an agent and new constraints. | Q&A is API/CLI-only and does not mutate/restart/branch the research plan. | Google Help `Open Agent`; `qa.py`; frontend inventory. | Post-report continuity is absent. |
| I09 | `non-faithful extension` | Cross-run memory behavior is not publicly disclosed. | Clone has no learned cross-run scientific memory; only history and response cache. | `cache.py`; store. | Must remain unverifiable rather than treated as a gap to a known Google feature. |
| I10 | `incorrect` | More compute should produce new reasoning rather than replay cached model outputs. | Raw-response/node caching is enabled by default, keyed to inputs. Repeated equivalent work may reuse outputs. | `constants.py::DEFAULT_CACHE_ENABLED`; `cache.py`. | Cache can mute stochastic test-time exploration and scaling. |
| I11 | `partial` | Resume should avoid repeating completed work. | Engine resumes at orchestrator after the last completed node; mock instead re-derives. | `engine_stream.py::_engine_node_stream`; `runs.py::_launch_resume`. | Real-provider resume matches the intent. |
| I12 | `incorrect` | Recovery should not fabricate resumability. | Pausing before an engine checkpoint writes a minimal envelope that is not an engine state; resume then re-derives/clears like mock. | `runs.py::_ensure_resumable_checkpoint`, `_launch_resume`. | Early pause can mean restart rather than true continuation. |

### J. Safety behavior and scientific misuse controls

| ID | Class | Google behavior | Current behavior and exact difference | Evidence | Fidelity consequence |
|---|---|---|---|---|---|
| J01 | `partial` | Scientific safety is a default evaluation criterion and unsafe goals are rejected. | Clone screens intake, each hypothesis, and the final report and can block/redact/hold. | Nature safety sections; `app/safety.py`; `engine/safety.py`; `safety_screen.py`. | Multi-stage gating is materially present. |
| J02 | `unverifiable` | Google's exact product classifiers, policies, and enforcement thresholds are private. | Clone uses narrow deterministic regex sets and a standard/strict mode. | `app/safety.py`; `engine/safety.py`; Google Intended Use Policy. | Exact safety fidelity cannot be established. |
| J03 | `incorrect` | Google's published preliminary eval rejected 1,200 adversarial goals across 40 topics. | Clone regression set has 13 cases; its result explicitly says it does not reproduce Google's private benchmark. | Nature supplement safety; `hypothesis-safety-2026-07-10.json`; dataset. | Evidence is far too small to claim comparable safety. |
| J04 | `incorrect` | Safety should understand scientific misuse context, not just key phrases. | Intake hard blocks five narrow regex combinations and defaults to allow. Per-idea filter uses similarly small patterns. | `app/safety.py::_BLOCK_PATTERNS`; `engine/safety.py`. | Obfuscated or novel misuse can bypass lexical rules. |
| J05 | `partial` | Uncertain/unsafe hypotheses should not enter ranking/output. | `prohibited`, `ethical_concern`, and `uncertain` are removed; uncertain ideas are stored for manual review. | `safety_screen.py`; `engine/safety.py::BLOCKING_OUTCOMES`. | Strong structural invariant exists. |
| J06 | `incorrect` | Held items require a human adjudication path. | State stores `held_for_review`, but no frontend/manual release or rejection workflow exists. | `safety_screen.py`; frontend inventory. | Safe abstention is terminal and invisible to scientists. |
| J07 | `partial` | Dual-use content should be controlled and operational detail withheld. | Clone preserves the high-level hypothesis and replaces explanation/experiment with a redaction placeholder. | `engine/safety.py::redact_hypothesis_fields`. | Redaction behavior is concrete, though policy equivalence is unknown. |
| J08 | `incorrect` | The product should communicate intended use: starting point, independent verification, no clinical use/human-risk reliance. | No equivalent persistent report/home disclaimer matching the 2026 Intended Use Policy was found; an interview capture's “AI can be inaccurate” line is not reproduced consistently. | Google Intended Use Policy; local interview capture; frontend search. | Users lack target-level risk framing. |
| J09 | `incorrect` | Safety policy should be one coherent system. | App and engine carry parallel regex implementations; app comments acknowledge they should be consolidated. | `app/hypothesis_safety.py`; `engine/safety.py:12-14`. | Policy drift can change decisions between layers. |
| J10 | `partial` | Safety decisions should be auditable. | Decisions and matched substrings/policy version are stored and exposed by an API. | store schema; `runs.py::get_safety`; safety dataclasses. | Auditability exists, with no faithful product presentation. |
| J11 | `missing` | Intended-use access is limited to scientific researchers and governed by Labs access. | No authentication, authorization, researcher eligibility, or access controls exist; client ID is browser-local scoping, explicitly not auth. | Google Help lines 25–37; `runs.py` client-ID comment; `main.py` CORS. | Access and misuse boundary differs materially. |
| J12 | `incorrect` | Safety should cover final scientific claims and protocols semantically. | Final gate runs regex over Markdown; unsupported but benign-looking protocols pass. | `app/safety.py::screen_final`; `report_render.py::finalize_report`. | Final scientific-risk assessment is lexical, not substantive. |

### K. Scientific reasoning, novelty, testability, diversity, and output quality

| ID | Class | Google behavior | Current behavior and exact difference | Evidence | Fidelity consequence |
|---|---|---|---|---|---|
| K01 | `partial` | Hypotheses should be aligned, plausible, novel, testable, and safe. | Review schema scores all five (alignment as relevance), and hypotheses include experiment fields. | Nature default criteria; `output_criteria_real_review.json`; models/schemas. | Formal criteria coverage exists. |
| K02 | `incorrect` | Review correctness/novelty gains depend on search and deep verification. | Most review modes do not call search; full/simulation cover one idea; reports can complete with zero evidence. | Nature ablations; graph/tool call sites; SQLite runs. | Score fields are not equivalent to evidence-backed evaluation. |
| K03 | `incorrect` | Co-Scientist aims to generate new knowledge, not merely plausible prose. | Recent real TB report asserted entirely novel molecular interactions while its audit marked all claims unsupported. | Nature framing; latest SQLite report. | The system demonstrates speculative fluency, not verified novelty. |
| K04 | `partial` | Experiments should be concrete and falsifiable. | Prompts request models, metrics, controls, and validation; real ideas include detailed experimental designs. | generation/evolution prompts; latest report. | Testability is often present in form. |
| K05 | `incorrect` | Feasibility should reflect the scientist's lab constraints. | Intake does not elicit lab/model/resource constraints; generic prompts invent feasible-looking methods. | Google interview/product evidence; `run_spec.ts`; prompts. | Feasibility is not personalized or reliably grounded. |
| K06 | `partial` | Diversity should cover different scientific approaches. | Multiple generation paths, high-temperature generation, diversity prompts, and cluster-aware pairing exist. | coordinator; prompts; proximity. | Real diversity mechanisms exist. |
| K07 | `incorrect` | Evolution should both improve and diversify through combinations/analogies/out-of-box operators. | Generic preserve-the-core prompt discourages combining or replacing ideas. | Nature Evolution; `evolution.md`. | Diversity operators conflict with the implementation prompt. |
| K08 | `incorrect` | Novelty claims should be verified against a broad, current corpus. | Small PubMed samples and optional latent fallback cannot establish global novelty; current real output still uses definitive novelty language. | Nature ablation; tool config; reports. | Novelty calibration is weak. |
| K09 | `partial` | Final output should acknowledge uncertainty/limitations. | Reviews and meta-review list weaknesses; reports include citation audit. | `meta_review.md`; `report_markdown.py`; latest report. | Some uncertainty is visible. |
| K10 | `incorrect` | Unsupported claims should be plainly labeled at claim level. | Unsupported totals appear only in audit summary; proposal prose remains categorical. | latest report; claim graph/report renderer. | Scientific uncertainty is not attached to the claim readers act on. |
| K11 | `divergent` | Published Google examples use long, domain-expert proposals with introductions, recent findings, rationale, detailed validation and large syntheses. | Clone templates force terse statements and top-five Markdown report sections; overview only sees top text/Elo. | extracted ALS/KIRA6/MASH/protein artifacts; engine prompts; `report_render.py`. | Output shape and information density are not comparable. |
| K12 | `missing` | Current product can generate proposal diagrams (visible example) and uses specialist models in some collaborations. | No diagram generation or scientific visualization path exists. | local high-potential capture; DeepMind AlphaFold statement; frontend/engine inventory. | Multimodal scientific output is absent. |
| K13 | `partial` | Output can surface non-viable/weak directions. | Low Elo ideas remain in All Ideas unless dedup/safety/contradiction removes them, but no explicit non-viable rationale/bucket exists. | Google Help; Ideas UI. | Raw rank is not the target decision taxonomy. |
| K14 | `incorrect` | Meta-review quality improves with recurring error patterns. | Meta-review's latest-only summaries discard earlier critiques and debates, and it is not periodically applied to all agents. | Nature ablation; `meta_review.py`. | The claimed self-improving mechanism is substantially weakened. |
| K15 | `unverifiable` | Exact current product output quality distribution is not public. | Local examples and case studies show structure and selected validated successes, not an unbiased production sample. | Official paper limitations and case studies. | No universal quality equivalence can be claimed in either direction. |

### L. Test-time compute, latency, recovery, observability, and evaluation

| ID | Class | Google behavior | Current behavior and exact difference | Evidence | Fidelity consequence |
|---|---|---|---|---|---|
| L01 | `divergent` | Flexible test-time compute scaling via asynchronous task execution. | Four small static tiers and deterministic iteration caps govern a sequential graph. | Nature abstract; `run_modes.py`; `graph.py`. | The defining scaling architecture is absent. |
| L02 | `incorrect` | Evaluations show best Elo/top-10 quality improving across temporal compute buckets with no observed saturation. | No real-provider scaling curve across increasing budgets exists in current results. | Nature test-time scaling; `evaluations/README.md`; results inventory. | The clone has not demonstrated its central claimed benefit. |
| L03 | `missing` | Paper validates Elo-quality concordance on GPQA and reports top-1 behavior. | Evaluation README says GPQA/provider benchmark remains an external gap; no licensed dataset run exists. | Nature evaluation; `evaluations/README.md`. | Elo is uncalibrated as a quality proxy here. |
| L04 | `missing` | Google runs ablations for generation strategies, search, debate, evolution, proximity, and meta-review. | Clone has isolated real-call artifacts and unit tests, not controlled end-to-end ablations with comparable metrics. | Nature lines 404–416; evaluation results. | Agent names cannot be tied to measured value. |
| L05 | `partial` | System records progress and supports recovery. | Append-only events, metrics, node checkpoints, SSE replay, and run status are implemented. | store schema; `engine_stream.py`; frontend hooks. | Strong engineering substrate match. |
| L06 | `incorrect` | Long-run progress should correspond to compute completed. | Fixed non-monotonic percentage constants and a four-step mapping do not reflect loop count or remaining budget. | `constants.py`; `home_recents_data.ts`. | ETA/progress cannot be trusted. |
| L07 | `partial` | Failures should be recoverable. | Provider/model retries, per-item isolation in some nodes, app failure state, and resume exist. | `llm_json.py`; node try/excepts; checkpoints. | Real recovery features exist. |
| L08 | `incorrect` | Failed specialist tasks should not necessarily abort unrelated work. | Review `asyncio.gather` intentionally aborts the full batch on one failure; Supervisor retry bookkeeping is disconnected from node exceptions. | `review.py:106-110`; `orchestrator.py::_compute_stats`. | Reliability is lower than worker-queue design. |
| L09 | `partial` | Observability should capture agent/task progress. | ExecutionMetrics, prompt metadata, event logs, diagnostics, and tool call counts exist. | `models.py::ExecutionMetrics`; event/store modules; golden run. | Operational visibility is good but not Google-product-equivalent. |
| L10 | `incorrect` | Scientific verification metrics should gate readiness. | Unit/type/lint/build all pass while the evaluation smoke fails, and unsupported reports still complete. | verification results; `evaluations/smoke.py`; report state. | Software health is decoupled from scientific release quality. |
| L11 | `incorrect` | Evaluation should use representative, human-audited scientific samples. | Citation eval uses 20 synthetic examples and safety uses 13; result files explicitly record missing panels/private benchmark. | evaluation JSON files. | Current evidence cannot establish target reliability. |
| L12 | `missing` | Google reports expert evaluation and multiple wet-lab validations. | Clone has no blinded domain-expert study or independent wet-lab validation of its outputs. | Nature results; evaluations inventory. | Scientific outcome fidelity is unvalidated. |
| L13 | `unverifiable` | Current product latency/cost and exact infrastructure are proprietary. | Clone exposes local wall time and model/API settings but not comparable production measures. | official sources; app metrics/config. | Must remain unverified. |
| L14 | `incorrect` | Fresh compute should expand the hypothesis space. | Default cache may return identical model/node results on equivalent inputs, reducing fresh exploration. | `cache.py`; constants. | Compute count can overstate new reasoning. |
| L15 | `partial` | Multiple directions can be processed concurrently. | Per-call semaphores support up to five in-flight ranking/verification/generation calls. | `MAX_CONCURRENT_LLM_CALLS`; call sites. | Local parallelism is real, but not distributed coalition scaling. |
| L16 | `incorrect` | Current Google system is built with Gemini. | Inspected runtime and production documentation use `deepseek/deepseek-chat` for both worker and Supervisor. | DeepMind/Nature; live `/status`; `AGENTS.md` production vars. | Model behavior and long-context/tool characteristics differ materially. |
| L17 | `unverifiable` | Google notes framework portability, while current product/model revisions are not fully disclosed. | LiteLLM makes the clone model-agnostic. | Nature line 330; `llm.py`. | Portability matches an architectural aspiration, not current 1:1 behavior. |

### M. User journey, terminology, visual presentation, responsiveness, and minor interaction deviations

| ID | Class | Google behavior | Current behavior and exact difference | Evidence | Fidelity consequence |
|---|---|---|---|---|---|
| M01 | `divergent` | Current Hypothesis Generation uses a light green science-Labs visual system visible in the local official footage/captures. | Clone defaults to a Gemini Enterprise shell with its own teal/green MD3 runtime palette and also supports dark mode. | local product captures; `frontend/DESIGN.md`; live UI. | It resembles Google styling but not the same product shell. |
| M02 | `incorrect` | Intake screen says “What’s your research challenge?” | Clone says “What breakthrough should we make today?” and “Start a new research goal to begin.” | local intake capture; `chat_home_stage.tsx`; `chat_composer.tsx`. | Minor but explicit copy mismatch. |
| M03 | `incorrect` | Interview panel is labelled `Agent` and includes a close control, feedback buttons, question, response composer, disclaimer, and progress rail. | Clone jumps to a run-spec document and never renders the interview layout. | local interview capture; live UI; component inventory. | Whole screen and interaction state are absent. |
| M04 | `incorrect` | Product progress screen shows title, executing phase, linear progress, time/sources/ideas metrics, and activity log. | Clone uses a recent-run card with four icon steps. | local run capture; `home_recents_run_steps.tsx`. | Major screen-layout mismatch. |
| M05 | `incorrect` | Goal Report tab order and labels match the official product. | Clone's tab labels/order are different and aliases only hide route differences. | local report captures; `run_tabs.ts`; `run_detail_shell.tsx`. | Exact visual/text fidelity fails. |
| M06 | `incorrect` | Ideas cards visibly label `HIGH POTENTIAL`/non-viable and offer `Chat with Agent`. | Clone uses rank/Elo chips and technical detail sections without those labels/actions. | local Ideas captures; `ideas_tab.tsx`; `ideas_detail_pane.tsx`. | Proposal presentation differs. |
| M07 | `incorrect` | Knowledge Base presents synthesized named technical sections with references. | Clone titles sections by title-casing paper titles and shows raw abstracts. | local Knowledge Base captures; `learningSections()`. | Superficial visual similarity masks different content behavior. |
| M08 | `incorrect` | Summary has `Agent Insights` plus product-specific stat cards. | Clone Research Overview has directions, aims, winners, and a tournament sentence. | local Summary capture; `run_detail_overview.tsx`. | Summary composition differs. |
| M09 | `non-faithful extension` | Current product evidence does not establish an end-user dark theme for Hypothesis Generation. | Clone offers light/dark/system theme controls and different dark accent colors. | `theme_context.tsx`; settings dialog. | Extra appearance states prevent strict 1:1. |
| M10 | `incorrect` | Best experience is desktop Chrome; the public site still presents coherent responsive content. | At 390×780 the clone setup overflowed/clipped while `scrollWidth==clientWidth`, leaving content inaccessible rather than horizontally scrollable. | Interactive browser inspection; CSS mobile overflow rules. | Mobile product is functionally broken, not merely non-identical. |
| M11 | `partial` | Product uses Google-style typography/icons/surfaces. | Clone bundles Google Sans files, Material Symbols SVGs, MD3-like radii and tonal surfaces. | build output; `DESIGN.md`; `Icon` component. | Visual family partially matches. |
| M12 | `incorrect` | The target is Hypothesis Generation. | Design authority names and optimizes for `Gemini Enterprise Idea Generation`, a different reference product. | `frontend/DESIGN.md:1-4,310-318`. | The wrong visual/product source is authoritative. |
| M13 | `divergent` | Exact current intake composition is evidenced by local footage. | Design document explicitly records deliberate green/purple, centered-greeting, and omitted-eyebrow deviations from its own reference. | `DESIGN.md:337`. | Intentional deviations remain fidelity violations even if attractive. |
| M14 | `non-faithful extension` | Product evidence does not show clone's diagnostic/settings/navigation affordances. | Clone adds collapsible rail, Logs, settings, API-key input, keyboard tab cycling, and technical detail anchors. | layout/settings/shortcut components. | Extra chrome changes the screen and interaction model. |
| M15 | `incorrect` | User-created research and case studies are distinct. | Recents merges mock demo runs into the same list; mock Learning content appears as ordinary references. | `runs.ts::loadRunHistory`; live demo tabs. | Product truthfulness and visual fidelity suffer. |
| M16 | `partial` | Report uses openable reference links. | Clone renders numbered references with Open pills. | local Knowledge Base capture; `run_detail_learning.tsx`. | Minor visual/interaction match. |
| M17 | `incorrect` | Current product uses `Run Specification`/`Run Specifications` terminology. | Clone uses `Goal Details`; its local design document codifies the wrong term. | Google Help/local captures; `DESIGN.md:503`. | Minor textual deviation with navigation impact. |
| M18 | `missing` | Top-right NotebookLM, Share, Download controls are part of the report. | No corresponding controls exist. | Google Help/local product; run-detail shell. | Visible primary actions are missing. |
| M19 | `partial` | Recent research shows status and can open a goal. | Clone has openable recent cards and live state. | Google Help; `home_recents.tsx`. | Basic journey match. |
| M20 | `incorrect` | Case-study prompts are references for structuring goals, not hard-coded evidence of system behavior. | Clone includes three fixed suggested prompts and seeded deterministic demo outputs. | Google Help lines 43, 50–56; `chat_home_stage.tsx`; `seed.py`. | Suggestions are acceptable, but demo outputs must not be credited and should be clearly separated. |

## Material matches that survive behavior-level verification

The matching names are far more numerous than the matching behaviors. These are
the narrow behaviors that do survive implementation-level verification:

| ID | Verified match | Important boundary |
|---|---|---|
| E01 | The working engine has the disclosed Supervisor, Generation, Reflection, Ranking, Proximity, Evolution, and Meta-review roles. | The orchestration and several role semantics differ, as E02–E32 document. |
| E19 | Elo ratings are persistently updated from pairwise comparisons. | Pair selection, judging, debate, scale, and product presentation differ. |
| E23 | Evolution creates immutable child hypotheses with lineage rather than overwriting parents. | Its operator and feedback inputs are incomplete. |
| H01 | Generation produces structured scientific hypotheses with rationales and experiments. | The prompt, scale, depth, and evidence basis differ. |
| H08 | Proximity can remove a redundant lower-ranked idea before output. | Its similarity measurement, clustering behavior, and scheduling differ. |

These matches do not imply system-level parity. Each is a shared primitive inside
a materially different product and execution framework.

## Exhaustive difference register

The comparison tables A–M are the canonical difference register: every row
contains target behavior, actual behavior, exact delta, evidence, consequence,
and verification locations. The index below makes the full gap set traceable to
the implementation roadmap without weakening or merging those individual rows.
`E01`, `E19`, `E23`, `H01`, and `H08` are the only rows excluded as
material matches; every other row remains a fidelity gap or a boundary that must
remain explicitly unverified.

| Surface | Canonical difference IDs | Roadmap priority |
|---|---|---|
| Research-goal creation and interview | A01, A02, A03, A04, A05, A06, A07, A08, A09, A10, A11, A12, A13, A14, A15 | 6, 7, 10, 14 |
| Run modes and execution | B01, B02, B03, B04, B05, B06, B07, B08, B09, B10, B11, B12, B13, B14, B15 | 2, 7, 11, 13, 14 |
| Active-run monitoring | C01, C02, C03, C04, C05, C06, C07, C08, C09, C10 | 3, 9, 11, 13 |
| Goal Report and follow-up | D01, D02, D03, D04, D05, D06, D07, D08, D09, D10, D11, D12, D13, D14, D15, D16, D17, D18, D19, D20, D21, D22, D23, D24, D25 | 1, 8, 10, 13, 14 |
| Agent coalition | E02, E03, E04, E05, E06, E07, E08, E09, E10, E11, E12, E13, E14, E15, E16, E17, E18, E20, E21, E22, E24, E25, E26, E27, E28, E29, E30, E31, E32 | 2, 4, 5, 15 |
| Supervisor and orchestration | F01, F02, F03, F04, F05, F06, F07, F08, F09, F10, F11, F12, F13, F14, F15 | 2, 11, 15 |
| Retrieval, grounding, citations | G01, G02, G03, G04, G05, G06, G07, G08, G09, G10, G11, G12, G13, G14, G15, G16, G17, G18, G19, G20, G21, G22, G23, G24 | 1, 5, 14, 15 |
| Hypothesis lifecycle | H02, H03, H04, H05, H06, H07, H09, H10, H11, H12, H13, H14, H15, H16, H17, H18, H19, H20 | 4, 5, 10, 15 |
| Memory and feedback | I01, I02, I03, I04, I05, I06, I07, I08, I09, I10, I11, I12 | 2, 5, 10, 11, 14, 15 |
| Safety and misuse | J01, J02, J03, J04, J05, J06, J07, J08, J09, J10, J11, J12 | 1, 12, 13, 15 |
| Scientific quality | K01, K02, K03, K04, K05, K06, K07, K08, K09, K10, K11, K12, K13, K14, K15 | 1, 4, 5, 8, 10, 12, 15 |
| Scaling, recovery, evaluation | L01, L02, L03, L04, L05, L06, L07, L08, L09, L10, L11, L12, L13, L14, L15, L16, L17 | 1, 2, 3, 11, 12, 15 |
| Journey and visual presentation | M01, M02, M03, M04, M05, M06, M07, M08, M09, M10, M11, M12, M13, M14, M15, M16, M17, M18, M19, M20 | 6, 8, 9, 13, 14 |

## Inferred and unverifiable Google behavior register

This register is deliberately separate from verified behavior. None of these
claims should be hard-coded as “what Google does” without new primary evidence.

| ID | Status | Most likely behavior and basis | Confidence | Required treatment |
|---|---|---|---|---|
| B02 | Inferred | `Advanced Run` almost certainly raises one or more task/compute budgets and verification depth because it consumes more credits and time. Google does not disclose its exact envelope. | High that it is larger; low on parameters. | Match only the visible two-mode contract; keep internals configurable and label reconstructed. |
| E22 | Inferred | Evolution likely uses a portfolio of combination, simplification, analogy, and out-of-box operators because the paper names these strategies, but current sampling weights are private. | High on operator set; low on weights. | Implement all disclosed operators; expose weights as evidence-bounded configuration. |
| F06 | Inferred | Current production likely uses learned or model-advised task priorities over a durable queue, following the published Supervisor pseudocode and freeform description. Exact fairness and retry rules are private. | Medium-high. | Reconstruct the disclosed queue semantics; do not claim exact scheduler parity. |
| G21 | Inferred | The current product likely has additional internal Google Search/scientific retrieval services beyond the named public databases. The product's clickable web citations and Google's infrastructure make this likely. | Medium. | Build a provider-neutral retrieval registry; mark undisclosed sources unavailable rather than fabricating them. |
| H03 | Inferred | Production likely mixes the disclosed generation strategies dynamically according to Supervisor feedback. Exact per-run mixture is not published. | Medium-high. | Implement strategy-specific tasks and adaptive weighting, with auditable decisions. |
| I09 | Inferred | Cross-run memory is probably limited to explicitly reopened goals or linked user resources; no primary source proves silent global memory across goals. | Low-medium. | Do not add cross-goal memory unless new evidence appears; isolate it as an optional extension. |
| J02 | Unverifiable | Production classifiers, policy taxonomies, thresholds, redaction behavior, and human-review escalation are private. | N/A. | Match the public intended-use outcomes and publish the reconstruction's own policy version; never assert classifier parity. |
| K15 | Unverifiable | Selected case studies show high-quality outcomes, but no unbiased distribution of production idea quality is public. | N/A. | Evaluate with blinded experts and report uncertainty; do not infer average parity from showcase outputs. |
| L13 | Unverifiable | Exact latency, cost, accelerator allocation, queue topology, and service-level objectives are proprietary. | N/A. | Match visible states and several-hour expectations; report local measures separately. |
| L17 | Inferred | The framework is described as model-portable, but the current product uses Gemini and its exact model mixture/revisions are not fully disclosed. | High on portability; low on model mix. | Default the replica to the strongest disclosed Gemini configuration while preserving a clearly non-faithful compatibility mode. |
| Product copy below captured screens | Unverifiable | Help text and captures establish primary labels and controls, not every tooltip, empty state, error message, or animation. | N/A. | Copy captured states exactly; record uncaptured microcopy as reconstruction. |
| Standard/Advanced termination | Inferred | Runs likely stop on a combination of compute budget, top-idea stability, and verification sufficiency, consistent with the paper pseudocode and several-hour product behavior. | Medium. | Use disclosed loop conditions plus configurable stability/evidence gates; retain a decision log. |
| Ranking judge protocol | Inferred | Published prompts and examples establish pairwise scientific debate and Elo updates, but production judge count, tie policy, and repeated-match sampling are not current public facts. | Medium. | Reproduce disclosed prompts/roles and validate judge calibration; keep sampling parameters configurable. |
| Proprietary safety and abuse monitoring | Unverifiable | Public policy establishes outcomes and prohibited reliance, not operational monitoring. | N/A. | Implement defensible independent controls and label them reconstruction-specific. |

## Fidelity-first roadmap

The order is strict. Later work should not be used to claim progress toward 1:1
while an earlier fidelity layer is still absent. Each priority maps to all of its
canonical difference IDs in the register above.

1. **Make scientific claims evidence-safe.** Replace post-hoc lexical citation decoration with claim-level retrieval, entailment/contradiction checks, source-quality and recency checks, citation-span provenance, abstention, and blocking release gates. A report must not complete while material claims remain unsupported. Fix the failing contradiction-recall gate before adding features. This closes the most harmful parts of D16, D22, G08–G17, G23, J12, K02, K03, K08, K10, L10, and L11.
2. **Replace the static graph with the disclosed asynchronous Supervisor/task framework.** Introduce a durable global task queue, typed worker tasks, adaptive priorities, freeform next-step decisions, concurrent workers, feedback-driven resource allocation, task-level retry/isolation, budget accounting, and disclosed termination conditions. Preserve resumability. This covers B07, E02–E04, F01–F07, F11, F13, F14, I01–I04, L01, L08, L14, and L15.
3. **Build truthful long-running execution and progress.** Implement task/worker events, verification-vs-generation compute accounting, phase/activity logs, truthful source/idea/time metrics, monotonic progress or indeterminate states, email completion, and the exact executing screen. Cover B08, B10, B11, C01–C10, L06, L07, and L09.
4. **Implement every disclosed scientific reasoning strategy materially.** Add distinct observation, assumption, research-expansion, debate, deep-verification, recurrent, full, and simulation tasks; all evolution operators; recurring meta-review; real multi-party debates; robust semantic proximity/clustering; and tournament scheduling across fresh/new/top candidates. Feed every critique and debate into future work. Cover E05–E18, E20–E32, H02–H18, K01, K04, K06, K07, K09, K13, and K14.
5. **Reach the disclosed retrieval and scientific-input surface.** Support web literature, PubMed, ChEMBL, UniProt, configurable domain databases, large PDFs, private repositories, multimodal images/tables, and tool-aware specialist tasks; deduplicate and rank evidence rather than slicing the first records. Add domain-expert/contact and optional AlphaFold-style tool paths only where supported. Cover A09, A10, E25, G01–G07, G09, G18–G22, H19, I06, K05, and K12.
6. **Reproduce the current interview exactly.** Build the `Agent` interview, `Interview Progress`, Research Challenge, Focus Area, Preferences, optional Title, feedback controls, close/disclaimer behavior, resumable answers, and iterative clarification. Delete keyword-based fake refinement. Cover A01–A08 and M02–M03.
7. **Expose exactly Standard and Advanced runs.** Remove Express/Extended/Ultra and the unsupported focus selector from the faithful mode; reproduce current credit, concurrency, refund, start/queue, and visible configuration semantics. Keep unknown compute envelopes configurable and identified as inferred. Cover B01–B06, B12, and B13.
8. **Reproduce the complete Goal Report and output depth.** Implement Ideas with High Potential/Non-Viable buckets and full leaderboard; synthesized Knowledge Base; Summary/Agent Insights; Run Specifications; rich proposal/review/debate/meta-review/overview content; contacts; diagrams where evidenced; Open Agent; NotebookLM; share; download; export; and faithful large-document rendering. Cover D01–D25, K11–K13, M05–M08, M16–M18.
9. **Match the live product's visual states.** Replace the Gemini Enterprise design authority with the current Hypothesis Generation evidence, then reproduce intake, interview, execution, report, loading, empty, failure, cancel, queue, and completion states at desktop and functional mobile sizes. Cover B14, B15, M01–M13 and M17–M19.
10. **Make scientist steering first-class and causally effective.** Surface messages, manual hypotheses, reviews, attachments, pause/resume/cancel, follow-up Agent chat, and per-idea chat; route them through shared memory and scheduling; prove they alter later tasks and outputs. Cover A11–A14, D12, D24, H19, I05, I08, I10–I12, and K05.
11. **Harden durable execution.** Move run work out of process-local background tasks into durable workers; atomically persist task and scientific state; resume without duplicating work; isolate item failures; reconcile after crashes; and preserve append-only provenance. Cover B08–B11, F08–F10, F12, F15, I02–I04, I07, L07–L09.
12. **Rebuild and validate scientific safety.** Consolidate app/engine policy, replace narrow regexes with semantic and tool-aware screening, add held-item adjudication, reproduce public intended-use messaging, require independent verification, control dual-use operational detail, and expand adversarial evaluation toward the disclosed 1,200-goal/40-topic scope. Cover J01–J12.
13. **Correct access and product boundaries.** Add real authentication, authorization, researcher eligibility, per-user ownership, sharing permissions, secure uploads, and completion notification. Separate product goals from case-study demonstrations. Cover B04, C10, J11, M15, and M20.
14. **Remove or quarantine non-faithful extensions.** In faithful mode hide local diagnostics, Logs, API-key/settings chrome, extra theme states, technical internals, seeded demos, mock evidence, extra run tiers, cross-goal memory, and API-only product concepts not supported by Google evidence. Keep developer functionality behind an explicit non-faithful mode. Cover A15, B09, C09, D06, G24, I09, M09, M14, M15, and M20.
15. **Prove behavior with evaluation, not nomenclature.** Add strategy/tool/meta-review ablations, real-provider test-time scaling curves, GPQA/Elo calibration, human blinded ratings on all five criteria, citation and contradiction panels, failure/recovery tests, safety benchmarks, and independent scientific validation. Use Gemini for faithful production evaluation and label other providers compatibility mode. Cover B02, E22, F06, G21, H03, J02, K15, L02–L04, L12, L13, L16, L17, and every inferred register item.

## Final fidelity determination

The repository has a credible research-workflow prototype and several correctly
implemented primitives, but its present user journey, orchestration model,
scientific strategies, retrieval breadth, verification rigor, output surface,
safety evidence, and compute scale all differ materially from Google's disclosed
system. The greatest distance is not visual polish or missing labels: it is the
absence of Google's asynchronous feedback-driven compute framework and the
ability to publish scientifically categorical reports despite zero verified
claims. Until priorities 1–5 are complete and externally validated, the system
should be described as “inspired by Google Co-Scientist,” not a behavioral
replica. Even after all public behavior is reproduced, proprietary items in the
inference register prevent a provable literal 1:1 claim.

## Reproduction notes

- Repository state was inspected without modifying product code.
- Public claims are linked to primary Google, DeepMind, Nature, or arXiv sources.
- Local path citations are relative to the repository root unless an absolute
  path is shown.
- Runtime findings are dated because provider availability, product UI, and
  public documentation can change.
- Mock runs were inspected only to identify misleading surface behavior and were
  never credited as engine capability.
