# Implementation prompt: closest achievable Google Co-Scientist replica

You are working in `/Users/guy/Code/Co-Scientist`. Transform the current
Co-Scientist-inspired prototype into the closest evidence-bounded 1:1 replica of
Google DeepMind Co-Scientist and the current Google Labs Hypothesis Generation
product in one comprehensive implementation pass.

Do not repeat the fidelity audit. This prompt is self-contained and is the
implementation specification. The companion
`docs/audits/google-co-scientist-implementation/2026-07-12/FIDELITY-DIFF.md` is optional
traceability material for canonical finding IDs, evidence, and exact verification
locations; completing this work must not depend on re-auditing the target.
Inspect the implementation before editing, preserve unrelated user changes, and
commit at natural checkpoints using `<type>(<scope>): <subject>`. Do not mention
any AI tool in commits, pull requests, or git history.

## Governing fidelity rules

1. Implement only behavior supported by primary Google evidence or explicitly
   mark it as a reconstruction. The authoritative sources are:
   - current Google Hypothesis Generation Help:
     `https://support.google.com/hypothesis-generation/answer/17106281?hl=en`;
   - Google Labs Science Intended Use Policy:
     `https://support.google.com/hypothesis-generation/answer/17106905`;
   - Gottweis et al., *Accelerating scientific discovery with Co-Scientist*,
     Nature 655, 487–496 (2026), its supplement, and arXiv 2502.18864v2;
   - Google DeepMind's 2026 Co-Scientist publication;
   - Google's 2026 Gemini for Science/Hypothesis Generation publication;
   - the captured target product and extracted paper artifacts under
     `references/core/google-co-scientist/`.
2. Reproduce verified target behavior exactly. Put proprietary or inferred
   parameters behind typed, documented configuration and emit them in a run's
   provenance as `reconstructed`, never `verified_google`.
3. Do not count names, enums, schemas, prompts, mocks, comments, API routes, or
   shells as complete until the behavior is reachable, durable, tested, and
   visible through the same product journey as Google.
4. Treat additions and substitutions as fidelity violations. Provide a default
   `faithful` product mode that hides all unsupported extensions. Put developer
   diagnostics and compatibility features behind an explicit non-faithful mode.
5. Never use `mock_workflow.py`, seeded examples, fixed demonstrations, or
   hard-coded output to satisfy an acceptance test. Mark demonstrations clearly
   and keep them separate from user research.
6. Preserve the useful substrate already present—SQLite event provenance,
   checkpoints, SSE replay, lineage, Elo updates, APIs, tests—where it is
   semantically compatible. Replace behavior that conflicts with the target.
7. Use Google-style code conventions already documented in `AGENTS.md`. Add
   inline comments that describe what the code does. Read
   `app/frontend/DESIGN.md`, but replace its Gemini Enterprise product authority
   with evidence from the current Hypothesis Generation captures.
8. Verify all frontend work visually and interactively in the built-in browser
   at desktop 1440×720 or another 2:1/16:9 viewport and mobile 390×780 or another
   1:2 viewport. A responsive page must remain usable, not merely avoid a
   horizontal scrollbar.

## Non-negotiable outcome

Deliver an end-to-end scientist journey:

1. A scientist enters a research challenge and completes a real iterative Agent
   interview.
2. The system produces an editable Research Challenge, Focus Area, Preferences,
   and optional Title.
3. The scientist starts exactly a Standard Run or Advanced Run.
4. A durable, asynchronous Supervisor continuously allocates concurrent tasks to
   the disclosed specialist coalition, incorporates feedback, and can safely run
   for hours, recover, pause, resume, cancel, and terminate on explicit budgets
   and convergence/evidence conditions.
5. Retrieval and verification ground every material scientific claim. No final
   report can complete with unsupported material claims stated categorically.
6. The live run surface truthfully exposes executing work, progress, time,
   sources, ideas, and activity.
7. The completed Goal Report contains Ideas, Knowledge Base, Summary, and Run
   Specifications; its proposals, reviews, citations, rankings, and synthesis are
   generated from the actual run.
8. Open Agent, idea-level follow-up, NotebookLM handoff, public sharing,
   download/export, scientist steering, attachments, manual ideas, and reviews
   work through the UI and durably affect or expose the run as appropriate.

## Implement in this strict order

### 1. Evidence-safe scientific claims

Replace post-hoc citation decoration with a claim-grounding pipeline that runs
before a hypothesis enters decisive ranking and again before publication.

- Extract stable, addressable claims from hypothesis text, rationale,
  experiments, reviews, meta-review, overview, Knowledge Base, and final report.
- Retrieve candidate support across the enabled sources, preserving source ID,
  URL/DOI/PMID, title, date, authors, source type, retrieval query, tool, timestamp,
  document version, exact support span, and surrounding context.
- Use semantic entailment and contradiction classification with calibrated
  thresholds. Treat lexical overlap only as a retrieval feature, never proof.
- Detect hard paraphrases, negation, numeric/unit conflicts, species/model
  mismatches, temporal mismatches, and a source that merely mentions a topic.
- Classify every material claim as verified, partial, contradicted, unsupported,
  unavailable, or explicitly speculative. Attach citations at claim level.
- Require independent corroboration for strong novelty, causality, clinical,
  safety, or quantitative claims where the scientific domain warrants it.
- Prevent contradicted or unsupported material claims from entering categorical
  proposal prose. Revise, hedge, quarantine, or abstain and explain why.
- Block `completed` report emission until the evidence policy passes. Do not let
  an audit footer legitimize unsupported prose.
- Make readiness gates configurable and provenance-labeled, but set faithful
  defaults conservatively.
- Fix the current offline citation smoke failure: contradiction recall must be at
  least 0.80, then raise the suite so hard-paraphrase accuracy, contradiction
  recall, and overall accuracy meet explicit production gates on a substantially
  larger human-audited panel.

### 2. Asynchronous Supervisor and global task framework

Replace the sequential static LangGraph pipeline and deterministic alternating
scheduler with the architecture disclosed in the 2026 paper and pseudocode.

- Define durable typed tasks for generation strategies, literature retrieval,
  reflection modes, debate, ranking matches, proximity/clustering, evolution
  operators, meta-review, deep verification, synthesis, and report preparation.
- Add a persistent global priority queue. Record task inputs, dependencies,
  priority, budget, attempt, lease, worker, status, timestamps, result, failure,
  and provenance.
- Make the Supervisor a real planning agent that sees the Research Plan, shared
  memory, idea/review/match/tool state, budget, convergence signals, failures,
  scientist feedback, and current queue. Let it propose, reprioritize, cancel,
  retry, and create follow-up tasks.
- Validate Supervisor decisions against safety, invariants, budgets, idempotency,
  and task schemas; code enforces safety and durability but must not secretly
  replace model planning with a fixed pipeline.
- Run independent tasks concurrently through durable workers. Use leases and
  idempotency keys so restart cannot duplicate scientific state.
- Isolate an item or worker failure. One failed review must not abort unrelated
  work. Retry transient provider/tool failures with bounded backoff and preserve
  failed-task evidence for the Supervisor.
- Allocate most mature-run compute to verification, consistent with Google's
  current description, while retaining configurable reconstructed weights.
- Terminate through explicit disclosed conditions: idea budget, matches per idea,
  compute/time/credit budget, top-set stability, verification sufficiency, safety,
  and scientist cancellation. Log every decision and whether its basis is
  verified or reconstructed.
- Preserve node/task checkpoints, append-only events, resume, and SSE replay.
  Move work out of FastAPI process-local background tasks into durable workers.

### 3. Full specialist coalition and scientific strategies

Implement the behavior of each published role, not just its name.

- **Generation:** dispatch distinct observation, assumption, research expansion,
  and debate-driven generation strategies. Observation must use retrieved
  evidence; assumption must explicitly challenge accepted premises; research
  expansion must pursue underexplored evidence-backed branches; debate must
  produce new hypotheses from disagreements. Track strategy provenance.
- **Reflection:** implement initial, observation, deep verification, recurrent,
  full, and simulation review tasks. Apply them based on maturity and uncertainty,
  not once to a hard-coded subset. Full/simulation reviews must use tools and
  evaluate executable experimental logic.
- **Ranking:** conduct auditable multi-party pairwise scientific debates, then a
  judge decision with tie/invalid-output handling. Select new-vs-old, near-ranked,
  uncertain, and top candidates according to disclosed tournament goals. Update
  Elo sequentially from committed outcomes; never update a concurrent round from
  stale shared ratings.
- **Proximity:** use robust semantic representations and explainable similarity,
  support real clusters, and avoid brittle title-prefix matching. Preserve
  diversity while removing only demonstrable redundancy.
- **Evolution:** implement enhancement, simplification, combination, analogy, and
  out-of-box operators with distinct prompts and inputs. Do not force every
  operator to preserve the core idea. Use all relevant reviews, debates,
  evidence, failures, and meta-review advice. Preserve immutable parent lineage.
- **Meta-review:** periodically inspect all reviews and debate transcripts,
  identify recurring errors and successful patterns, and feed concrete guidance
  back into Supervisor allocation and every relevant worker.
- **Deep verification:** create probing questions, execute retrieval/tool tasks for
  them, and resolve or expose uncertainty rather than producing latent-only prose.
- **Research overview:** synthesize the mature top set, evidence, disagreements,
  roadmap, contacts when evidenced, limitations, and recommended experiments. It
  must not see only hypothesis text and Elo.
- Use the eight published prompts and extracted artifacts as behavioral anchors,
  but adapt with explicit provenance when current product evidence supersedes
  them. Do not retain the clone-only forced sentence pattern or terse 2–3 sentence
  ceiling.

### 4. Retrieval, tools, and scientific inputs

Build a provider-neutral scientific retrieval and tool registry.

- Support current web literature and PubMed plus the publicly named ChEMBL and
  UniProt sources. Preserve the reference MCP path and allow domain-specific
  databases through typed adapters.
- Implement ranked retrieval, query expansion, pagination, deduplication, source
  quality, recency, retraction/correction awareness, and evidence caching with
  freshness rules. Do not take the first N records as the corpus.
- Accept large PDFs and private research repositories with durable ingestion,
  access control, chunk/span provenance, tables, figures, and multimodal content.
  A filename-only attachment is not an upload.
- Make tools available to the Supervisor, Generation, Reflection, Deep
  Verification, and Evolution tasks where scientifically appropriate.
- Add optional specialist integrations such as structure prediction only where
  public evidence supports the workflow and the service is genuinely available.
  Return `unavailable`, never a fabricated result.
- Generate research-contact suggestions only from verifiable evidence and label
  them as suggestions, not endorsements.

### 5. Exact research-goal interview and steering

Replace the local regex-derived setup flow with the current product journey.

- Reproduce the target intake heading `What's your research challenge?` and the
  evidenced shell, instructions, examples, and disclaimer.
- Build the `Agent` interview screen with close control, feedback controls,
  question/answer composer, `Interview Progress`, and the four evidenced fields:
  Research Challenge, Focus Area, Preferences, and optional Title.
- Ask context-sensitive follow-up questions until the plan is adequately scoped.
  Persist the transcript and structured derivation. Allow the scientist to edit
  answers and resume the interview.
- Elicit domain, desired outcome, constraints, available models/data/tools,
  novelty boundary, feasibility constraints, exclusions, and preferred output
  depth. Do not invent lab capabilities.
- Surface existing API capabilities for messages, human hypotheses, human
  reviews, attachments, pause, resume, cancellation, and Q&A through faithful UI.
- Route steering into shared memory and create or reprioritize tasks. Add
  end-to-end tests proving a steering message changes later task allocation or
  output rather than merely being stored.

### 6. Standard and Advanced runs

- In faithful mode expose exactly `Standard Run` and `Advanced Run`. Remove or
  hide Express, Extended, Ultra, the clone-only four-way focus selector, and the
  `default` canonical mode.
- Reproduce the currently documented concurrent-run limits: three Standard and
  one Advanced. Enforce the constraints server-side, not only in UI.
- Represent credits, reservation, consumption, failure refund, queueing, and
  completion notification consistently with the public product. Keep billing
  integration replaceable when real Google Labs credits are not available.
- Make the unknown Standard/Advanced compute envelopes typed configuration. Set
  defensible defaults based on public behavior, mark them reconstructed in run
  provenance, and never expose fabricated Google numbers.
- Runs must support several-hour execution, clean restart, pause/resume/cancel,
  and a consistent terminal state.

### 7. Truthful execution screen

- Reproduce the evidenced run screen: title, executing phase, linear progress or
  an honest indeterminate state, time, source count, idea count, and live activity
  log.
- Derive progress from committed task budgets and remaining work. Remove fixed,
  non-monotonic constants such as 84→75 and the static four-step recent card.
- Show which agent/task is active, without leaking hidden chain-of-thought. Use
  concise event summaries and explicit retry, paused, queued, failed, cancelled,
  and completed states.
- Stream real events and metrics. Do not render mock phases for real runs.
- Send a configurable email completion notification with tested retry and opt-out.

### 8. Complete Goal Report and follow-up product

Reproduce the exact report information architecture and controls.

- Use exactly `Ideas`, `Knowledge Base`, `Summary`, and `Run Specifications` in
  the evidenced order and terminology. Remove Goal Details, Learning, Research
  Overview, and All Ideas as primary faithful-mode tabs.
- **Ideas:** show the full Elo leaderboard and distinct High Potential and
  Non-Viable sections with reasons. Cards and detail views must expose the
  proposal, rationale, evidence-linked mechanism, experiments, limitations,
  reviews, debate/ranking history, lineage, citations, diagram when produced, and
  `Chat with Agent`/idea-level follow-up.
- **Knowledge Base:** synthesize named technical topics from the run corpus. Do
  not title-case paper titles and dump the first three abstracts. Include
  openable references and claim-level citation spans.
- **Summary:** reproduce Agent Insights and evidenced statistics, key findings,
  uncertainties, contradictions, recommended directions, and next experiments
  from actual run state.
- **Run Specifications:** show the final Research Challenge, Focus Area,
  Preferences, Title, mode, and reconstruction provenance.
- Produce dense, domain-expert outputs comparable in structure—not copied
  content—to the extracted Google examples: introductions, recent findings,
  mechanistic rationale, detailed validation, controls, falsification criteria,
  limitations, alternatives, contacts where supported, and research overview.
- Implement `Open Agent`, idea-level and goal-level follow-up, NotebookLM handoff,
  public sharing with permissions/revocation, and downloads/exports of the
  evidenced report formats. If a Google-specific integration is unavailable,
  provide a clearly labeled interoperable handoff without pretending it is the
  proprietary integration.
- Persist the generated report and export inputs. Large reports must render and
  download without truncation.

### 9. Visual and interaction fidelity

- Replace the Gemini Enterprise Idea Generation assumptions in
  `app/frontend/DESIGN.md` with tokens, layouts, copy, states, controls, and
  rationale derived from the current Hypothesis Generation footage and captures.
- Reproduce the light green science-Labs product shell and captured typography,
  spacing, navigation, cards, tabs, chips, icons, control placement, and copy.
  Do not infer unsupported dark-mode behavior in faithful mode.
- Reproduce intake, interview, executing, report, idea detail, Knowledge Base,
  Summary, Run Specifications, loading, empty, queued, paused, failed, cancelled,
  and completion states.
- Hide Logs, API-key inputs, diagnostics, keyboard-only technical navigation,
  model controls, extra themes, and internal anchors in faithful mode. Preserve
  them only in explicit developer mode.
- Separate case studies/demonstrations from user recents. Label deterministic or
  mock data visibly and never mix it into a live goal's evidence.
- Fix mobile clipping. Interactively verify every critical journey at desktop
  1440×720 and mobile 390×780; record screenshots in `docs/assets/` and add
  browser-level assertions for accessibility, focus, keyboard behavior, scroll,
  and primary actions.

### 10. Persistent context and durable recovery

- Use a shared-memory model that durably stores Research Plan, interview,
  scientist feedback, hypotheses, evidence, claims, reviews, debates, rankings,
  clusters, tool results, tasks, budgets, meta-review advice, safety decisions,
  and report provenance.
- Give each task the minimum necessary context plus stable references. Do not
  repeatedly copy a lossy latest-only summary when full history is required.
- Ensure all reviews and debate outcomes can influence later generation,
  evolution, ranking, and verification.
- Implement transactional checkpoint/task commits and reconciliation on worker
  restart. Prove exactly-once scientific effects under duplicate delivery.
- Do not silently introduce cross-goal memory. If retained as an optional
  extension, make it explicit, consented, isolated, and disabled in faithful mode.

### 11. Safety, access, and intended use

- Consolidate app and engine safety logic into one versioned policy service.
- Replace narrow regex-only gates with semantic, contextual screening at intake,
  task/tool use, hypothesis admission, experimental-protocol output, and final
  publication. Keep deterministic high-precision rules as one signal.
- Preserve prohibited, ethical-concern, uncertain/held, redacted, and allowed
  outcomes. Build a human adjudication UI and audit log for held items.
- Control dual-use operational detail without disguising the decision. Never let
  a harmless title bypass a harmful protocol.
- Reproduce the public intended-use message: the system is for scientific
  researchers, output is a starting point, independent verification is required,
  and it must not be relied on for clinical decisions or human-risk applications.
- Add real authentication, authorization, per-user ownership, researcher-access
  policy, secure upload/download, share permissions, revocation, and audit logs.
  Browser-local client IDs are not authentication.
- Expand safety evaluation toward the published 1,200-goal, 40-topic scope using
  legally and ethically suitable independently curated cases. Report that it is
  a reconstruction, not Google's private benchmark.

### 12. Evaluation and release gates

Build a reproducible evidence package proving material behavior.

- Keep all current unit, integration, lint, typecheck, and build checks green.
- Add end-to-end tests for the full interview → run → recovery → report →
  follow-up/export journey with real task semantics and deterministic provider
  fixtures that preserve behavior without hard-coded reports.
- Add controlled ablations for every generation strategy, search, debate,
  evolution operator, proximity, meta-review, and evidence gate.
- Measure test-time scaling across increasing compute budgets using best-Elo and
  top-set expert quality, diversity, verified-claim ratio, cost, and latency.
- Calibrate Elo-quality concordance using a licensed GPQA-equivalent benchmark
  and blinded domain-expert review. Do not fabricate access to unavailable data.
- Run human evaluation on alignment, plausibility, novelty, testability, and
  safety. Include inter-rater agreement and confidence intervals.
- Build substantially larger human-audited citation entailment, contradiction,
  source-quality, novelty, and safety panels. Include hard paraphrases, numeric
  conflicts, retractions, species/model mismatches, and unavailable evidence.
- Test crash/restart, duplicate delivery, partial provider/tool failure,
  cancellation, pause/resume, queue limits, authorization, and export/share
  revocation.
- Use the strongest disclosed Gemini configuration for faithful real-provider
  evaluation. Keep LiteLLM/DeepSeek and other providers as visibly labeled
  compatibility mode; never claim their output is current Google-model parity.
- Do not release a run report if scientific gates fail. A software-green build is
  insufficient when citation, contradiction, safety, or provenance gates fail.

## Explicit reconstructed boundaries

The following are not publicly knowable. Implement configurable, auditable
reconstructions and document uncertainty; do not block the rest of the work and
do not claim exact parity:

- Standard/Advanced task, time, token, credit, and verification budgets;
- production scheduler weights, fairness, judge count, tie policy, and retry
  parameters;
- evolution-strategy and generation-strategy sampling weights;
- proprietary Google Search/scientific services and internal databases;
- exact model mixture and model revisions;
- classifier implementations, thresholds, abuse monitoring, and human review;
- production latency, accelerator allocation, queue topology, and SLOs;
- uncaptured tooltips, errors, animation timing, and microcopy;
- cross-goal memory, which must remain off unless new evidence supports it;
- the unbiased distribution of Google's production output quality.

Emit these choices in a machine-readable `fidelity_provenance` section on every
run and include an operator-facing page that distinguishes `verified`,
`inferred`, `reconstructed`, `extension`, and `unavailable` behavior.

## Required migrations and compatibility

- Add forward-only migrations for task queue, leases, claim evidence, source
  spans, interview state, shared memory, safety adjudication, access control,
  sharing, notifications, and fidelity provenance.
- Preserve existing runs as legacy read-only records. Do not silently reinterpret
  mock or old report data as faithful output.
- Version prompts, policies, retrieval adapters, task schemas, model settings,
  report schemas, and evaluation datasets in run provenance.
- Update the API contract and frontend types together. Remove dead aliases after
  migrating routes; do not leave duplicate names that imply parity.
- Update `README.md`, `docs/ARCHITECTURE.md`, fidelity documentation, deployment
  configuration, environment examples, and operator runbooks to describe only
  behavior that works.

## Acceptance conditions

Do not declare completion until all conditions below are demonstrated.

1. A fresh scientist can complete the evidenced Agent interview and see exactly
   the four research-plan fields.
2. Faithful mode exposes only Standard Run and Advanced Run and enforces three
   Standard/one Advanced concurrency server-side.
3. The Supervisor demonstrably creates and reprioritizes diverse durable tasks in
   response to scientific state and user feedback; execution is not a disguised
   static pipeline.
4. Independent tasks run concurrently, survive API/worker restart, and have
   exactly-once scientific effects under redelivery.
5. Every disclosed generation, reflection, ranking/debate, proximity, evolution,
   meta-review, and verification strategy has an end-to-end behavioral test.
6. Retrieval uses multiple enabled sources, ranks/deduplicates results, handles
   large/private/multimodal inputs, and preserves exact provenance.
7. Every material final claim has a visible claim-level evidence status and
   support span. Contradicted/unsupported claims cannot be stated categorically
   or pass the report-completion gate.
8. The citation evaluation is green, including contradiction recall ≥0.80 as an
   immediate floor, and the new larger panel has documented production gates.
9. Progress is monotonic or honestly indeterminate and is derived from committed
   work; the activity log, source count, idea count, and elapsed time are real.
10. Goal Report tabs, labels, primary controls, idea buckets, leaderboard,
    Knowledge Base, Agent Insights, Run Specifications, Open Agent, sharing,
    download, and NotebookLM-compatible handoff are functional.
11. A steering message, manual hypothesis, human review, and uploaded scientific
    resource each demonstrably alter or inform subsequent tasks/output.
12. Safety is coherent across layers, held items can be adjudicated, intended-use
    limitations are visible, and authorization protects every private resource.
13. Seeded/mock runs are visually separated and cannot contaminate live evidence,
    evaluation, recents, or report claims.
14. Desktop and mobile browser verification covers the entire critical journey;
    390×780 has no clipped or unreachable setup/report content.
15. Engine tests, app tests, frontend tests, Ruff, mypy, frontend lint/build,
    end-to-end tests, evaluation smoke, safety gates, and provenance validation
    all pass. Record exact commands and results.
16. Ablation, scaling, Elo calibration, expert-review, citation, safety, and
    failure-recovery reports are checked in with methods, limitations, and source
    data references.
17. The final documentation identifies every remaining proprietary uncertainty
    and never calls the result a literal 1:1 implementation where public evidence
    cannot support that claim.

## Final handoff

At each natural checkpoint, commit a coherent, tested slice. In the final handoff
provide:

- a concise outcome summary;
- a finding-ID closure matrix for A01–M20 showing implemented, evidence-bounded
  reconstruction, intentionally quarantined extension, or still blocked;
- migrations and compatibility notes;
- exact verification commands/results;
- desktop and mobile screenshot links;
- evaluation artifact links and scientific release-gate results;
- the remaining proprietary/unverifiable boundaries;
- no claim of completion for any behavior reachable only through a mock, stub,
  hard-coded demonstration, unconsumed API, or superficial UI shell.
