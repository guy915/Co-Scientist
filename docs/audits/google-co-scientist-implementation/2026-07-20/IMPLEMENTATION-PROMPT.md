# Implementation prompt: evidence-bounded Google Co-Scientist / Hypothesis Generation reconstruction

Use this self-contained prompt as the governing instruction for the implementation effort, together with the repository's `AGENTS.md`. The companion `FIDELITY-DIFF.md` supplies row-level evidence and reproduction detail, but this prompt does not depend on it to define the required outcome, work, or acceptance conditions. Do not treat an older fidelity, parity, closure, handoff, plan, mock, demo, or test-name claim as truth when it conflicts with current source, runtime behavior, or primary Google evidence.

## Mission

Transform the repository from a hybrid Co-Scientist-inspired workbench into the closest publicly defensible reconstruction of:

1. the current Google Labs Hypothesis Generation product journey; and
2. the peer-reviewed Google Co-Scientist research architecture.

Do not claim literal production or source-code parity. Google's complete source, current model routing, hidden prompts, Supervisor policy, retrieval stack, safety classifiers, tier budgets and infrastructure are proprietary. The correct outcome is an **evidence-bounded reconstruction** that:

- exactly matches every verified current Labs behavior and non-conflicting visible state;
- materially implements every published architecture invariant;
- labels every local algorithm, constant and extension as reconstructed;
- never publishes blocked, retracted, unsupported or private working material through another channel;
- exposes only working functionality—no shells, dormant controls, fixture science or optimistic copy; and
- leaves external/proprietary validation items explicitly open until real evidence exists.

Do not stop after visual similarity, endpoint creation, schema changes, or unit tests. Complete each vertical slice from user interaction through authorization, persistence, task execution, checkpoint/event, scientific artifact, report/Q&A/share/export/delete, and recovery.

## Evidence boundary

Use these sources in this order:

1. Current [Google Help: How to research with Hypothesis Generation](https://support.google.com/hypothesis-generation/answer/17106281?hl=en) for current product terminology, Standard/Advanced, quotas, report tabs and actions.
2. Current [feedback](https://support.google.com/hypothesis-generation/answer/17105610), [data/deletion](https://support.google.com/hypothesis-generation/answer/17107198?hl=en), and [intended-use](https://support.google.com/hypothesis-generation/answer/17106905?hl=en-IN) Help pages.
3. The [2026 Nature paper](https://www.nature.com/articles/s41586-026-10644-y) and [Supplementary Information](https://static-content.springer.com/esm/art%3A10.1038%2Fs41586-026-10644-y/MediaObjects/41586_2026_10644_MOESM1_ESM.pdf) for research architecture, disclosed prompts/pseudocode, safety, evaluation and limitations.
4. Current [DeepMind architecture description](https://deepmind.google/blog/co-scientist-a-multi-agent-ai-partner-to-accelerate-research/).
5. Direct local footage/captures under `references/core/google-co-scientist/media/hypothesis-generation/` for visible layout, motion and interactions not contradicted by current Help.
6. Local extracted paper/supplement artifacts for examples and disclosed prompt shapes.
7. Gemini Enterprise Idea Generation references only as secondary low-level component guidance. Never let that separate product define the Labs information architecture.

Apply one scope label to every requirement and implementation decision:

- `LABS`: verified current product behavior.
- `ARCH`: verified research-system architecture/capability; it may not be a current Labs control.
- `LOCAL`: useful implementation/operations extension whose Google equivalent is unknown.
- `UNKNOWN`: proprietary or inferred detail; reconstruct only as configurable/versioned local behavior.

Current Help wins over older footage for labels and operational behavior. Direct footage wins for visible states not contradicted by Help. The current final tab label is **Run Specifications** plural. The verified conceptual roster is one Supervisor plus six specialist roles: Generation, Reflection, Ranking, Evolution, Proximity and Meta-review. Intake, literature, safety, citation, reporting and chat can remain supporting services, but do not call them additional Google peer agents.

## Definition of working behavior

Credit a feature only when a normal user can reach it from the shipped product and it operates on real persisted artifacts. Do not close work with:

- deterministic offline output, seeded demos, mocks or pseudo-scientific phrase banks;
- uncalled API clients/endpoints, hidden routes or retired components;
- hard-coded suggestions, reports, graphs, counters, citations or diagrams;
- comments, prompts, schemas or test names without a live consumer;
- a frontend that claims an operation succeeded before durable backend completion;
- a unit fixture shaped differently from live structured output;
- a safety label that does not change downstream behavior;
- post-filtering a synthesis already generated from blocked material; or
- a passing local test while the aggregate, E2E, deployment or evidence gate is red.

Keep deterministic offline mode only as an explicitly labelled development/test aid. It must make zero external provider/tool requests and must never be shown as verified science or mixed into personal history.

## Non-negotiable engineering constraints

1. Preserve unrelated user changes. Use forward-only migrations; never destroy a working database to simplify implementation.
2. Add code comments that describe **what** a non-obvious block does. Keep comments factual and current.
3. Keep every unknown model, prompt, threshold, budget, retry, cache and scheduler choice configurable, versioned and recorded in per-run provenance.
4. Use one canonical publishability/release policy across every consumer.
5. Keep private scientific audit provenance access-controlled. Do not expose raw chain-of-thought; show concise safe progress/explanations instead.
6. Build on the existing durable store, events/checkpoints, Elo core, immutable evolution lineage, server interview and real report data plumbing unless a finding requires replacement.
7. Contain `LOCAL` diagnostics/admin/expert controls behind an explicit authenticated workbench/admin boundary. The default user journey must be the `LABS` surface.
8. Match the direct visual source after structural/functionality parity. Do not invent a new design language.
9. Commit at natural checkpoints using `<type>(<scope>): <subject>` and a branch named `<type>/<description>`. Do not mention an AI tool in git history.

## Implementation sequence

Execute the phases in order. Do not begin visual polish or declare an earlier implementable phase complete while its acceptance tests are red. Proprietary and external-validation boundaries are carried as open evidence items, not converted into code-completion claims.

### Phase 0 — Canonical scientific release, privacy, redaction and deletion

Close `EB-026`, `EB-029-032`, `EB-035-036`, `EB-046`, `EB-048-052`, `F-KB-02-05`, `F-SUMMARY-01-03`, `F-SHARE-02`, and `OP-008-009,024-025,041,045,047-050`.

#### 0.1 Create the canonical release contract

Introduce a versioned persisted `PublishabilityDecision` (or equivalently named domain object) computed from:

- source retraction/correction/withdrawal status;
- initial and mature review dispositions;
- deep-verification verdict and explicit unverified/error state;
- atomic claim support, contradiction and abstention/insufficient state;
- candidate safety status and policy version;
- human adjudication/resolution;
- requested redaction transformations; and
- provenance/version of every evaluator.

Make one service/function the only authority for whether an idea/source/claim may enter:

- ranking and matchmaking;
- Evolution parent/context selection;
- Proximity/dedup release decisions;
- Meta-review and research-overview prompts;
- leaderboard and High Potential/Non-Viable buckets;
- Knowledge Base and citations;
- expert-contact suggestions;
- Agent/Q&A context;
- completion notifications;
- report JSON/Markdown;
- download/export and NotebookLM handoff;
- public share; and
- any user-readable log/event payload.

Do not copy the predicate into each layer. All consumers must call the same versioned policy or consume its persisted decision. Store why an item is included/excluded, but expose restricted reasons only to authorized reviewers when safety/privacy requires it.

#### 0.2 Fix evidence quarantine and provenance

- Reject retracted/withdrawn sources before reservation, budget selection, analysis, `used_in_analysis`, grounding, synthesis, contact extraction and sharing. Treat correction/erratum state explicitly rather than silently accepting it.
- Add canonical DOI/PMID/URL/source identity, availability, retrieval time/version, exact passage/page/section and correction status.
- Fix actual claim-edge consumers: supporting/contradicting IDs are inside passage arrays, not a nonexistent edge-level field. Use the persisted `claim` field, not nonexistent `claim_text`/`claim_id`.
- Atomize claims. Keep `supports`, `contradicts`, `insufficient/abstain` distinct and calibrated.
- Never equate “source resolved” with “claim verified.”
- Filter overview inputs before model invocation. Regenerate an overview after any publishability change.
- Validate upload signatures independently of caller MIME, scan/quarantine malicious/archive-bomb inputs, disclose which configured provider receives private text, and provide per-document deletion. Keep encryption/at-rest and retention guarantees truthful.
- Treat audience/corpus selection as personalization unless it is protected by real authorization. Add per-document license/provenance metadata before any corpus is described as private or restricted.

#### 0.3 Make redaction real

Implement deterministic, testable transformations for every `redact` outcome before persistence or emission. Apply them to goals, hypotheses, passages, report payload/Markdown, Q&A, events/logs, exports, shares and notification text. Retain a restricted original only when explicitly required for audit, with separate authorization and retention. A redaction label accompanying original content is a failed implementation.

#### 0.4 Fix report truth

- Remove the UI Knowledge Base synthesis fallback. If no persisted synthesis exists, render a clearly labelled raw-evidence state.
- Use globally consistent reference IDs/numbers and exact passage/source links.
- Compute Verified ideas from the defined evidence/verification policy, never from High Potential count.
- Render actual High Potential/Non-Viable members. Render persisted explanatory reasons only as a grounded, labelled local enhancement.
- Make report/share/Q&A/export values derive from one sanitized report contract.

#### 0.5 Secure sharing and data lifecycle

- Keep revocable, expiring, hashed share capabilities or use authenticated sharing, but return only the sanitized/versioned report artifact. Never include raw run config, completion email, uploaded document content, all hypotheses, blocked ideas or unrestricted evidence tables.
- Add UI and API to create, list, copy and revoke shares; show scope/expiry and audit access without leaking reader identity unnecessarily.
- Add permanent run deletion from Runs -> More -> Delete. Delete or explicitly tombstone every run-scoped derivative: hypotheses/state, reviews, matches, evidence, citations, claims, proximity, metrics, events, tasks, checkpoints, reports, attachments/files, shares, messages, safety decisions, notifications, run-scoped logs and cache artifacts.
- Define retention and legal/audit exceptions explicitly. Test that deleted content cannot be recovered through ordinary API, share, search, cache or file paths.
- Provide an evidence-bounded data-access adaptation. If exact Google back-office behavior cannot be cloned, expose a truthful local archive/request workflow and label it `LOCAL`; do not pretend to send a Google request.
- Give feedback records an accountable admin/triage owner, privacy notice, optional screenshot, retention and deletion. Do not operate a write-only personal-data sink.

#### Phase 0 acceptance

Before proceeding, add live-shape integration tests that inject each of the following and assert absence from ranking, Evolution, overview prompt, report, Q&A, download, NotebookLM artifact, share and notification: retracted source; contradicted claim; insufficient categorical claim; initial-review rejection; fatal mature review; undermined/unverified deep review; safety block; unresolved hold. Prove redacted original text is inaccessible from public/user channels. Prove delete/revoke cascades. Run the tests against real store rows and actual response schemas, not hand-authored lookalikes.

### Phase 1 — Durable human input, safety adjudication and side effects

Close `EB-002-004`, `EB-012`, `EB-015-018`, `F-INTERVIEW-04-06,12`, `F-RUN-05-07`, `F-AGENT-02-03`, `F-STATE-01-04`, and `OP-004,013,023,035,044`.

#### 1.1 Repair run/task state machines

- On exhausted or unsupported work, atomically mark the task and run failed, persist structured error/provenance, emit one terminal event and make API/SSE/CLI settle consistently.
- Represent safety `hold` as a waiting state/task, not a successfully completed boundary. Approval must enqueue a new unique successor and resume to completion; rejection must settle blocked. Test intake and final holds independently.
- Enable SQLite foreign keys on every connection. Ship validation/repair migrations for orphan/legacy rows before enforcing constraints.
- Invalidate/recompile cached graphs and availability when model/tool/MCP/topology configuration changes.
- Make checkpoint/event/task finalization idempotent under retries and concurrency.

#### 1.2 Repair scientist contributions and steering

- Upsert/merge manual hypotheses without inserting the same primary key twice. Preserve author, origin, stable ID, lineage, review/safety state and independent Elo lifecycle.
- Preserve human review identity, rubric and score semantics. Do not infer 20/60/90 from summary words or persist a duplicate generic agent review.
- Mark steering applied only in the same transaction that commits the consuming successor checkpoint. A crash before commit must replay it; a crash after commit must not duplicate it.
- Allow ARCH steering to refine constraints, publications, directions and resource allocation, not only force a Generation call.

#### 1.3 Recover interviews and start operations

- Give each interview a route/recoverable ID. Load it with `getInterview` on reload/history and restore turns, fields, draft, attachments and plan state.
- Wire structured field editing and Agent regeneration to real server operations. Retry must make a new Agent call and retain provenance.
- Attach/index documents before or during interview so questions and the plan actually use them.
- Treat create/upload/start as one recoverable user operation. On partial failure, show the durable draft and exact failed step with Retry/Cancel; never hide an orphan or discard confirmed setup.

#### 1.4 Make side effects reliable

- Completion email, upload processing, feedback, share creation/revocation and deletion must have idempotency keys, retry state and visible failure/recovery.
- Validate SMTP delivery in a configured test transport; record delivery state without exposing the email in shares/logs.
- Forced offline mode must short-circuit interview and every other provider/tool call before network access.
- Replace timing-sensitive subprocess tests with explicit process readiness/handshake and bounded eventual assertions.

#### Phase 1 acceptance

Force crashes at every acknowledgment/commit boundary. Demonstrate exactly-once steering and side effects, manual idea/review completion without collisions/duplicates, intake/final hold approve/reject, terminal retry exhaustion, interview reload/edit/retry, attachment-grounded plan and recoverable partial start. No nonterminal run may have zero claimable/running work without an explicit waiting reason.

### Phase 2 — Published asynchronous Supervisor coalition

Close `EB-007-011`, `EB-019-021`, `EB-039`, `EB-044-045`, `EB-051`, `EB-059-062` and the execution semantics behind `F-RUN-02-06`.

#### 2.1 Replace phase routing with queueable scientific tasks

Refactor the fixed serial bootstrap and one-next-specialist scheduler into dependency-aware tasks for:

- Generation strategies and debate;
- initial/full/observation/simulation/recurrent/deep Reflection;
- candidate safety;
- Ranking comparisons/debates;
- each Evolution strategy;
- Proximity updates/dedup;
- Meta-review; and
- periodic/final research overview.

Allow independent tasks across specialist roles to run concurrently within explicit resource/safety bounds. Keep item-level idempotency and durable checkpoints. A successful sibling must commit even if another item fails.

#### 2.2 Give Supervisor a real allocation contract

Remove the prompt instruction that forbids workflow planning. Give Supervisor a versioned ResearchPlan and live observations including:

- idea count, novelty/diversity and publishable pool;
- review/verification/safety backlog;
- weighted Proximity graph and tournament coverage;
- per-agent success, scientific yield, latency, tokens/cost, failures/retries;
- Generation versus Evolution marginal yield;
- user steering/constraints/publication restrictions;
- Meta-review feedback and safety alerts;
- remaining resources and convergence evidence.

Return a bounded portfolio of task allocations with dependencies, priorities, resource limits and reasons—not one enum. Persist decisions and terminal rationale. Keep the local policy configurable and labelled reconstructed because Google's formula is unknown.

#### 2.3 Make feedback and safety continuous

Append current Meta-review feedback to every applicable subsequent specialist context, including Supervisor, literature retrieval, Proximity and safety. Allow Meta-review to emit a safety alert that pauses/reprioritizes work for authorized review. Do not expose hidden reasoning; persist safe scientific rationale, prompt/tool provenance and structured outcomes.

#### 2.4 Instrument truthful compute and progress

Record every model/tool/cache call with run/task/agent, model, prompt/schema/policy/tool/source versions, tokens, cost, latency, retries, errors, cache state and item yield. Enforce budgets from these actual records. Replace fixed percentages with durable queued/running/completed work and confidence/uncertainty; never move backward because a phase constant was reused. Derive ETA only from measured task classes and show an indeterminate/uncertain state when insufficient.

#### Phase 2 acceptance

Run an integration scenario where Supervisor enqueues multiple independent specialist tasks, observes a controlled failure/yield difference, changes allocation, incorporates scientist steering and Meta-review, then terminates with a persisted evidence-based reason. Assert metrics equal independently counted invocations and hard budgets stop at the same count. Assert progress remains semantically honest through iterative cycles.

### Phase 3 — Material scientific reasoning, retrieval and verification

Close `EB-019-028`, `EB-033-047`, `EB-063`, `F-HOME-05-06`, `F-IDEAS-01,05-07,11`, `F-KB-01,04-05`, `F-SUMMARY-05`, and `OP-037,047,050`. Preserve the core Elo behavior (`EB-037`) and immutable evolved descendants (`EB-042`).

#### 3.1 Build evaluated retrieval and private-corpus grounding

- Implement hybrid lexical/vector/scientific-entity retrieval with query relevance, quality, recency, correction/retraction and diversity.
- Persist every score, rationale, model/index version and retrieval timestamp.
- Scale private-corpus indexing beyond bounded prompt snippets; preserve exact page/section/figure/table locations.
- Use true multimodal model inspection for figures/images when supported. If unavailable, label extracted OCR/text limitations honestly.
- Add evidenced specialist tool classes such as AlphaFold where domain-appropriate; keep allowlists, authentication and provenance.
- Do not silently fall back from required literature grounding to an ungrounded model. Emit explicit degraded/unavailable state and adjust publishability.

#### 3.2 Materially implement disclosed techniques

- Persist iterative assumption/sub-assumption trees with repeated expansion.
- Run bounded multi-role debates as auditable tasks with evidence access, convergence criteria and transcript/rationale artifacts.
- Make every Reflection mode produce a canonical disposition. Fatal full/simulation/observation/recurrent/deep results must change rankability/release.
- Deep-verify meaningful post-ranking leaders and reverify after material evidence/text/context changes. Provider failure becomes `unverified`, never pass.
- Fix live Proximity `{index, similarity_degree}` resolution, persist weighted edges and use them in both dedup/diversity and matchmaking.
- Implement grounding, feasibility, inspiration, combination, simplification and out-of-box Evolution as separate operators. Seed randomness, isolate child failures and preserve parent/child/fresh Elo.
- Keep Elo 1200/logistic pairwise core; label K-factor/tie/debate/match schedule local and configurable.

#### 3.3 Ground Q&A and report synthesis

Feed exact evidence passages—not titles/status only—into Q&A, reviews, verification and synthesis. Resolve every citation to the same stored source/span. Refuse/abstain when the released context cannot answer. Offline Q&A must be explicitly fixture-only and answer the actual question shape in tests without masquerading as evidence.

#### Phase 3 acceptance

Use a human-audited representative corpus to show semantic relevance above lexical baseline, retraction/correction exclusion, exact span traceability and calibrated support/contradiction/abstention. A live schema-valid Proximity response must create non-empty weighted edges and alter selected matches. Every Reflection outcome must have tested eligibility consequences. A document-grounded interview/run must visibly change when the source set changes.

### Phase 4 — Rebuild the default product as current Hypothesis Generation

Implement every `F-ENTRY-*`, `F-HOME-*`, `F-INTERVIEW-*`, `F-RUN-01,03-04`, `F-REPORT-*`, `F-IDEAS-02-04,07,10-12`, `F-KB-03-04`, `F-SPEC-*`, `F-AGENT-*`, `F-SHARE-*`, `F-EXPORT-*`, `F-EXT-*`, `OP-001-009,031,038,040,046-050,054-055`, and the surface/API aspects of `EB-001,005-006,032,047,054-058`. Do not implement `F-IDEAS-13` as Labs parity; contain annotations/collaboration with `U19` as an optional local/non-Labs surface.

#### 4.1 Establish the correct shell and entry journey

- Make the green/lime Hypothesis Generation experience in the direct source media the default product surface. Reproduce the opening identity/Create a run/research-challenge sequence and current disclaimer.
- Use the existing design-system tokens where they can express the source, but do not preserve the Gemini Enterprise shell merely because it is already polished.
- Remove the automatic Affiliation dialog from the default journey. Move Google-team/SBI/pilot outreach, author notes and alternate suggestions into an explicit local/admin environment.
- Remove Logs, Offline mode and static Proposals from end-user chrome. Keep diagnostics in an authenticated operator route/tool.
- Remove the dead browser DeepSeek key control or implement a real authenticated BYOK backend with secret-safe storage/routing and clear provider provenance. Do not leave a “saved” no-op.
- Separate demonstrations from owned history, label them prominently and make them read-only. Do not seed them into production/private history by default.

#### 4.2 Implement the verified interview/configuration contract

- Render a persistent right-side Interview Progress document with Research Challenge, Focus Area(s), Preferences and optional Title. Show completion/provenance and update it from durable server fields.
- Support semantic field editing/reopening and interview resume after reload/navigation.
- Display a concise Thinking/progress state only. Never render provider chain-of-thought or continuously announce it through a live region.
- Show the research-tool/inaccuracy/medical-advice disclaimer from the visible target and intended-use boundary.
- Configure exactly **Standard** and **Advanced**. Enforce at most three Standard and one Advanced in progress per account. Migrate legacy Express/Extended/Ultra records forward without rewriting historical provenance; present them read-only with a clear legacy label.
- Keep exact internal budgets configurable/versioned as `LOCAL/UNKNOWN`; do not invent Google cycle/idea/match counts in copy.
- Implement the verified completion notification only after delivery/retry/failure behavior works. Treat any enable checkbox or custom-recipient field as a labelled local adaptation because public evidence does not establish that configuration UI.
- Preserve the verified Labs fields—Research Challenge, Focus Area(s), Preferences and optional Title—on the default surface and ensure they reach the run. Put the ARCH evaluation rubric and local execution knobs in a clearly labelled advanced provenance/configuration layer; do not present them as verified Labs-native fields.

#### 4.3 Implement the verified execution surface

- Use Idea Tournament framing, real progress, Time remaining or honest uncertainty, Sources Analyzed, Ideas Explored and high-level scientific activity.
- Do not show internal node keys/raw graph events as the primary narrative.
- Show live/reconnecting/stale/failed stream state and actionable recovery.
- Implement verified ARCH scientist steering in a clearly labelled workbench layer. Keep pause/resume/cancel/early-stop controls local because current Labs Help does not verify their exact placement.
- Render dedicated draft, failed, blocked and cancelled states. For Failed, provide actionable status-refresh guidance and a support path. If the reconstruction has no credit system, state that plainly; do not invent Google's refund rules or promise credits. Never route a non-completed run into a completed Goal Report shell.

#### 4.4 Restore the exact current Goal Report

Use these visible tabs in this exact order:

1. **Ideas**
2. **Knowledge Base**
3. **Summary**
4. **Run Specifications**

Land completed runs on Ideas. Keep current Help's plural label even though earlier footage used singular.

Ideas must include real Agent Insights and statistics; real High Potential and Non-Viable groups/members; the full Elo-ordered idea set; and a rich selected idea artifact. Show explanatory reasons only when they are grounded and labelled as a local enhancement because direct evidence establishes the buckets, not the exact reason presentation. Render every relevant persisted review/verification result rather than the first review and latest match only. Support real generated diagrams/media when produced—never placeholders or handcrafted fake assets. Add idea-scoped Chat with Agent. Place numeric Elo, match transcripts, claim spans, safety details, cluster IDs and lineage in an optional advanced provenance layer because Labs visibility is unverified.

Knowledge Base must render persisted synthesized technical topics, outline/navigation, uncertainty, globally stable numbered references, exact evidence context and availability. It must never fabricate a synthesis from evidence rows.

Summary must render the released overview/directions/experiments/aims/contacts and actual bucket rationale. Link winning ideas to their detail. Do not call High Potential “Verified.”

Run Specifications must show the exact verified challenge, focus, preferences and optional title that drove the run. A labelled advanced provenance/configuration layer must expose the ARCH rubric and versioned local execution choices without implying those fields are visible in Labs. Move safety adjudication/private-source administration out of the normal report.

#### 4.5 Wire every verified post-run action

- Add Open/Chat with Agent at run and idea scope using sanitized passage-grounded Q&A.
- Add share create/list/copy/revoke through the safe contract.
- Add Download. Public evidence does not specify format; choose a truthful supported local format, label it, and do not claim a Google format matrix.
- Implement Open in NotebookLM using a current supported public handoff/import mechanism. If no programmatic import exists, provide a truthful user-mediated export/open flow; never show success without an importable artifact.
- Add More -> Product Feedback with optional screenshot and the human-review privacy notice. Keep SBI pilot feedback separate.
- Add More -> Delete with permanent cascade confirmation.
- Route the post-start composer either to the appropriate Agent/steering operation or make it read-only. Never send messages into a completed interview.

#### 4.6 Secure access and quota

Use a production-safe tenant identity. Do not trust caller-supplied `X-Client-ID` as authentication or share a blank subject. Configure explicit CORS origins; never `*` with credentials. Preserve limited/invite access semantics without pretending to clone Google's proprietary account system. Ensure demos and shares cannot be mutated by unauthorized callers.

Do not put bearer tokens in query strings for SSE/download. Use secure same-site cookies or short-lived path/audience-bound tickets. Apply deployment-wide/provider-wide and verified-subject rate, concurrency and spend ceilings; quotas must not multiply by rotating identity or legacy tier. Make log/feedback/interview/upload/share limits shared across replicas and evict rate-state safely. Protect status/OpenAPI/internal tool/model/key diagnostics behind operator authorization.

#### Phase 4 acceptance

Starting from a fresh authenticated browser, complete: Create a run -> multi-turn interview -> reload/resume/edit -> inspect specifications -> select Standard/Advanced with 3/1 quota -> start -> Idea Tournament -> completed Ideas-first report -> inspect categories/rich idea/Knowledge Base/Summary/Specifications -> Agent Q&A -> NotebookLM handoff -> share/revoke -> download -> feedback -> delete. Also force a failed run and verify actionable Failed-state support/status guidance without invented credit promises. Every visible count/content/action must derive from persisted real artifacts. Assert exact current labels and absence of Affiliation, raw reasoning, unlabeled demos, dead BYOK, Logs/Offline/Proposals and dormant primary controls from the default journey.

### Phase 5 — Responsive, accessible and visual fidelity

Implement `F-RESP-01,03`, every `F-A11Y-*`, `F-IDEAS-08-10`, `OP-040,042` and the visual aspects of entry/interview/report findings. Treat `F-RESP-02`/`U18` as local responsive acceptance only; Labs mobile pixel parity remains open without direct source evidence.

1. Fix the exact 720 CSS-pixel/DPR boundary so the full report works at both required desktop ratios. Do not test only a convenient 2:1 viewport.
2. Add a visible, keyboard- and screen-reader-named Back action from mobile idea detail to list. Preserve focus/scroll/selection.
3. Announce selected idea with correct listbox/navigation semantics. Make the detail relationship explicit.
4. Implement modal/drawer focus trap, inert background, Escape, opener restoration and correct dialog/menu/region roles. Remove `role=status` from interactive popovers.
5. Choose either page-navigation or tab semantics for report navigation and implement it completely, including keyboard behavior.
6. Keep streaming status concise and avoid a continuously changing raw-reasoning live region.
7. Make shortcuts discoverable or remove them; do not intercept normal arrows unexpectedly.
8. Verify zoom/reflow, contrast, targets, reduced motion and keyboard-only completion. Do not claim WCAG conformance from source inspection or an automated scan alone.
9. Use the built-in browser interactively at desktop 2:1, desktop 16:9 and mobile 1:2. Capture the same target/current states at the same CSS viewport/DPR. Review the reference and implementation together and fix all observable crop, overflow, padding, typography, border, radius, motion and state differences.

#### Phase 5 acceptance

The entire Phase 4 journey must work locally at all three required viewports without horizontal clipping, hidden actions or navigation traps. Keyboard-only use must complete it; focus must remain contained/restored; screen-reader output must expose selection/state without raw reasoning noise. Attach dated source/current comparison captures to the acceptance record, while leaving Labs mobile pixel parity explicitly open.

### Phase 6 — Packaging, CI, deployment and evaluation truth

Implement `EB-070`, `OP-010-018,021-023,026,028-045,051-054` and all test/build remedies. `EB-022` and `EB-064-069` remain open until representative external evidence actually exists; this phase must build/run the evidence program without pretending code or synthetic fixtures close those claims.

#### 6.1 Repair supported environments

- Install the app from its declared dependency metadata instead of `--no-deps` plus a hand-maintained subset. Require `pip check` in setup and CI.
- Test real `pypdf` parsing without module fakes. Install and smoke Tesseract (or remove/disable OCR truthfully) in every API image that advertises image ingestion.
- Make root/app `.env` loading consistent. Remove retired mock-mode copy and document the actual forced-offline behavior.
- Add forward-only migration tests from representative legacy DB snapshots, including schema/report version and orphan repair.
- Fix `engine/mcp_server` package discovery so an editable/wheel install imports and starts from outside the repository. Remove cwd-shadow workarounds and add out-of-tree install/import/start tests.
- Pin/lock base images and dependencies sufficiently for reproducible artifacts. Run API/MCP as nonroot, add accurate healthchecks, declare persistent paths and record image/dependency digests in run/evaluation provenance.
- Repair both Compose paths: correct the MCP health URL, remove required untracked-env assumptions, persist SQLite/cache/report state, keep MCP private/authenticated, avoid reload/mutable cloning for release-like use, and make tool config domain-appropriate.
- Commit and document one supported API/worker topology. If using a separate worker, disable the embedded production worker and monitor/restart the worker explicitly; if using SQLite, declare supported replica/writer limits, backups and restore drills.

#### 6.2 Make one truthful aggregate gate

Redefine `make test-all` to include, or rename it and introduce a true gate for:

- engine tests;
- app tests;
- frontend tests;
- MCP server tests;
- evaluation truth/smoke tests;
- lint and typecheck for every package;
- frontend production build;
- API/MCP Docker builds and compose smoke;
- migration/clean-install/pip-check tests;
- security/tenant/share/delete tests; and
- full browser E2E.

Expand CI path filters so root Makefiles, Dockerfiles, Vercel/Railway config, schemas/migrations, docs affecting contracts, corpus/tool config and lock/dependency files trigger the relevant gates. Reconcile unit and E2E expectations; do not simultaneously assert report controls absent and required. Replace fixed startup timeouts with readiness protocols.

Technically block external network in offline jobs; do not rely on comments. Make E2E run required desktop 2:1/16:9 and mobile 1:2 projects, use the offline responder immediately, and write screenshots to temporary test results rather than tracked audit assets. Maintain one authoritative Vercel config and add appropriate CSP, nosniff, referrer and permissions policies after validating required origins/resources.

#### 6.3 Verify deployment without leaking secrets

Against an authorized staging/production-like deployment, smoke:

- secure auth/ownership/CORS;
- provider/model selection and forced-offline isolation;
- MCP/tool reachability;
- authorized `TOOLS_CONFIG`/enabled-tool behavior rather than registration-only probes;
- persistent volume, migration and restart;
- explicit API/worker replica topology, deploy SHA/image digest, health/restart state and backups;
- SMTP delivery/retry;
- sanitized share/revocation;
- upload/PDF/OCR;
- deletion/retention; and
- browser journey from Phase 4.

Do not expose keys, goals, private documents or raw provider traces in logs/artifacts.

#### 6.4 Build meaningful evaluation evidence

- Repair the parity checker so `verified` requires a passing executable semantic/live-shape test or dated external artifact, not a file/test name.
- Reproduce Elo-versus-correctness calibration on a legally usable expert question set.
- Run controlled multi-budget scaling and mechanism ablations with cost, uncertainty and data provenance.
- Build a large diverse adversarial/safe suite, not rules mirrored by 13 fixtures.
- Calibrate citation support/contradiction/abstention on representative human-audited scientific claims.
- Run a blinded multi-rater expert comparison and report confidence intervals/inter-rater agreement.
- Keep wet-lab/case-study validation open until actually performed. Never convert synthetic/offline/golden artifacts into external validation.

#### Phase 6 acceptance

All clean-install, aggregate, CI, container and browser gates pass deterministically. A deployed smoke passes in an authorized environment. Evaluation artifacts are reproducible, dated, provider/model/tool/prompt/versioned and appropriately qualified. No parity row cites a missing symbol or a test that does not establish the claimed semantics.

### Phase 7 — Documentation, provenance and extension containment

Implement/document `EB-005`, `EB-014`, `EB-053`, `EB-055-060`, `EB-063,070`, `F-ENTRY-04-05`, `F-IDEAS-12`, `F-SUMMARY-04`, `F-SPEC-04-05`, `F-STATE-05-06`, `F-EXT-*`, and `OP-019-020,027,036,053,056`. Contain `F-IDEAS-13` under `U19`. Keep every `U-*`, `F-RESP-02`, `EB-022`, and `EB-064-069` open until the required primary or external evidence exists.

1. Rewrite README, architecture, design/fidelity/parity, env/setup, API/CLI, deployment and operator docs from current executable behavior.
2. Maintain a generated/checked evidence ledger with `LABS`, `ARCH`, `LOCAL`, `UNKNOWN`, source date/link, implementation path, test/artifact and open limitation.
3. Expose per-run provenance for model, prompt, schema, policy, tool/source, cache and reconstructed parameters. Keep private scientific traces access-controlled.
4. Describe exactly Supervisor plus six specialist roles. Map supporting services beneath them.
5. Keep CLI, detailed provenance, pause/cancel, safety admin, pilot feedback, logs, themes and other unevidenced features explicitly local and outside the default faithful surface.
6. Preserve the proprietary/inference register. Contain and document unknowns; never mark exact Google budgets, prompts, policies, models, retrieval algorithms, safety classifiers, mobile layout, export formats or infrastructure matched without new primary evidence.
7. Remove or update stale closure/final-status files. Preserve historical audit dates; do not rewrite history as if old claims were true.

#### Phase 7 acceptance

A reviewer can trace every visible/system claim to current primary evidence and passing executable behavior, and can distinguish a Labs requirement from an architecture requirement or local extension. No documentation claims “1:1 complete,” “deeply verified,” clinical validity or external parity while proprietary/external items remain open.

## Required migrations and compatibility strategy

Before schema/API changes, inventory current databases and clients. Implement forward-only migrations for at least:

- canonical publishability/release decisions and versions;
- source identity/correction/retraction and exact evidence spans;
- canonical review/deep-verification dispositions;
- safe report/share schema version;
- durable safety waiting/adjudication successor state;
- interview route/recovery and attachment linkage;
- true task allocations/Supervisor decisions/metrics;
- notification/side-effect delivery state;
- deletion/tombstone/retention state; and
- canonical Standard/Advanced plus legacy local-tier provenance.

Validate/repair existing foreign-key orphans before enabling enforcement. Never map an old Ultra result to a claimed Google Advanced result; preserve the original local profile and show it as legacy. Keep old report/share tokens read-only only if they can be sanitized; otherwise revoke them explicitly and explain why. Version API/report payloads and update frontend/CLI atomically.

## Required test matrix

Every row below must have a live-path test. Use actual schemas/store rows, not mock shapes.

| Gate | Required proof |
|---|---|
| Publishability | Every blocked/retracted/unsupported/rejected/unverified/safety-held item is absent from every downstream/public channel. |
| Redaction | Original sensitive text cannot be read through DB-backed user API, SSE, log, Q&A, report, export or share. |
| Overview | Prompt inputs are canonical-releasable before generation; policy change regenerates synthesis. |
| Proximity | Live index schema creates weighted edges; edges influence dedup and a chosen match. |
| Manual input | Scientist idea/review completes ranking/final drain once with preserved identity and no duplicates. |
| Safety hold | Intake/final approve resumes to completion; reject settles blocked; replay is idempotent. |
| Retry exhaustion | Task and run settle failed once across DB/API/SSE/CLI. |
| Steering | Forced crash before/after commit yields exactly-once visible consumption. |
| Interview | Multi-turn state, progress, structured edits, regeneration, attachments and reload all work. |
| Quota | Fourth Standard and second Advanced are rejected/queued accurately; other mode remains available. |
| Email | Configured delivery, retry, idempotency, failure visibility and privacy pass. |
| Share | Create/list/read/revoke works; only sanitized versioned report is returned; tenants are isolated. |
| Delete | Every scoped derivative/file/cache/share becomes inaccessible; retention exceptions are explicit. |
| Agent | Run/idea questions use released exact passages, cite them and abstain when unsupported. |
| NotebookLM/download | User obtains a real importable/downloaded sanitized artifact; no no-op control. |
| Supervisor | Concurrent portfolio allocation changes from measured outcome and records terminal reason. |
| Metrics/budget | Stored totals equal independently observed model/tool/cache events and enforce limits exactly. |
| Retrieval | Human-audited relevance, identity, retraction and exact-span tests beat baseline. |
| Reflection/Evolution | Every disposition affects eligibility; each operator creates immutable fresh descendants; item failures isolate. |
| Accessibility | Keyboard/focus/selection/live-region/zoom/reflow checks complete the full journey. |
| Responsive/visual | Same-state source/current comparisons pass at desktop 2:1, desktop 16:9 and mobile 1:2. |
| Clean install/deploy | Declared dependencies, `pip check`, PDF/OCR, Docker/compose, migrations and authorized deployed smoke pass. |
| Evaluation truth | No verified ledger row lacks a passing semantic test or dated external artifact. |

## Verification commands

Use repository-supported commands, but repair the aggregate gate first. At minimum record exact outputs for:

```bash
make setup
make test-all
make lint
make typecheck
make build
make eval-smoke
```

Also run package-level engine/app/MCP/frontend/evaluation suites, clean-install `pip check`, Docker/compose smoke, migration/restart/crash tests and browser E2E. Use Bun for the frontend. Do not dismiss a timeout as harmless until repeated isolated and CI runs establish the cause and make the gate deterministic.

For a real scientific smoke, use an authorized provider and live literature/tool path with a non-sensitive goal. Record provider/model/tool/prompt/policy/schema versions and cost without recording secrets. Offline runs are not substitutes.

## Required deliverables

Deliver all of the following:

1. Working product/engine/backend/operations changes with forward migrations.
2. New/updated unit, integration, crash, security, migration, E2E, accessibility and visual regression tests.
3. Dated same-viewport source/current screenshots at 2:1, 16:9 and 1:2.
4. A sanitized real-provider/tool end-to-end run artifact and exact verification log.
5. Updated source-of-truth docs and evidence ledger using `LABS/ARCH/LOCAL/UNKNOWN`.
6. A status matrix mapping every `F-*`, `EB-*`, `OP-*` and `U-*` item to code, test/artifact and `implemented`, `contained`, or `open-evidence` status.
7. A remaining-open register for proprietary Google details, external scientific validation and any permissioned production check not performed.
8. Natural checkpoint commits with conventional messages and no unrelated changes.

## Completion rule

Do not declare completion because the UI looks close, all named modules exist, unit tests pass, or an offline demonstration finishes. Completion requires:

- all implementable `F-*`, `EB-*` and `OP-*` findings implemented with live-path evidence;
- every aggregate/local/deployed gate green and deterministic;
- no blocked/private/retracted/unsupported content can cross the canonical release boundary;
- the current Labs journey is reachable and interactive end to end;
- the published asynchronous Supervisor coalition operates materially rather than nominally;
- every visible scientific claim/count/reference is derived from persisted released artifacts;
- every local extension is contained and labelled; and
- every `UNKNOWN` or external validation item remains explicitly open unless new primary evidence or actual validation closes it.

The final product may be the closest publicly defensible reconstruction. It still must not be called a literal 1:1 copy of proprietary Google production.
