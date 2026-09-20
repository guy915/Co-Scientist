# External Reference Campaign for Co-Scientist

Improve the existing Co-Scientist implementation by studying the nine specified repositories sequentially, adopting useful code or techniques, and verifying each improvement against the current product and published Google behavior. Done means every repository has a complete evidence-backed assessment, every accepted improvement is implemented and verified, each repository’s changes are merged and deployed, and retained documentation explains every adoption and rejection. Non-goals are replacing the current stack, adding a separate computational-discovery product, redesigning the workbench, claiming knowledge of Google’s private implementation, or incurring additional charges.

## Campaign contract

### Authority and boundaries

- Preserve documented Google behavior. External implementations provide hypotheses about improvements, not evidence of what Google built.
- Label findings **Google-backed requirement**, **external technique**, or **local design choice**.
- Retain FastAPI, React, LangGraph, SQLite, and the existing Vercel/Railway services. Allow justified libraries and optional adapters.
- Improve existing screens, reports, and workflows autonomously. Record new product modes and substantial redesigns as out of scope.
- Preserve append-only lineage, durable task recovery, authenticated event replay, evidence provenance, safety gates, and deployment invariants.
- Study all nine repositories in the listed order. Permit at most three additional repository investigations, each justified by a specific unresolved gap.
- Merge and deploy after each repository. If investigation produces no product changes, record that outcome and verify the current deployment; do not manufacture an improvement or force a redundant deployment.

### One repository at a time

Use one ignored checkout at `references/work/<slug>/`. Here, “fork” means a local working copy; creating GitHub forks is unnecessary unless maintaining an upstream modification becomes justified.

For each repository:

1. Pin its upstream URL and commit; inspect its actual license and relevant component licenses.
2. Map its substantive code, prompts, tests, documentation, and operational assumptions.
3. Compare mechanisms against the current local implementation, including improvements adopted earlier in this campaign.
4. Implement accepted findings, verify them, merge, and deploy.
5. Preserve the assessment, evidence, and attribution, then remove the temporary checkout before acquiring the next repository.

Do not execute upstream setup scripts or agent workflows before inspecting them. Run necessary upstream experiments in isolated environments without ambient credentials. Preserve adopted code in its proper maintained location with attribution; temporary reference checkouts must not become runtime dependencies.

### Persistent records

`PLAN.md` is the authoritative execution state. Supporting evidence lives under `references/external/`:

- `README.md`: source inventory, pinned revisions, assessment status, and links to dossiers.
- `campaign.md`: verification commands, fixed evaluation inputs, selected free models, baseline results, and operational procedures.
- One dossier per repository: architecture map, inspected areas, candidate decisions, source permalinks, local counterparts, experiments, adopted changes, and release evidence.

Each candidate receives a stable ID and records:

- The concrete gap and affected user or scientific behavior.
- Upstream evidence and corresponding local implementation.
- Fidelity classification and reuse approach: copy, adapt, independently implement, or use an existing dependency.
- Acceptance criteria, test boundary, evaluation results, and costs.
- Final disposition: adopted, already covered, rejected with evidence, or outside the authorized scope.

Promising but inconclusive candidates remain open. Rate limits, inconvenience, or the turn limit are not evidence for rejection.

### Zero additional spending

Before any campaign inference:

- Inspect current local and deployed model settings without exposing credentials.
- Select explicit OpenRouter models whose current applicable prices are zero. Include new or stealth models when available, but assess capability rather than assuming novelty implies quality.
- Test structured output, tool calling, streaming, long prompts, and reasoning-budget behavior through the project’s actual interfaces.
- Enforce zero-cost routing on campaign calls and system-default free-model paths, including retries, fallbacks, auxiliary models, embeddings, and evaluation runners. Disable paid plugins and metered tools for campaign experiments.
- Treat unknown prices or unverifiable billing paths as unavailable. Preserve users’ explicit BYOK behavior separately.
- Recheck prices and availability before live experiment batches. Record the model actually served.
- Honor rate limits and resume recorded experiments later. Never substitute a paid model, fabricate live results, or present offline output as live evidence.

Use a fixed selected model configuration for each baseline/candidate comparison. If it changes, rerun both sides. Do not automatically redeploy production whenever a new free model appears.

## Verification and release rules

### Acceptance evidence

**Correctness and reliability changes:** reproduce the defect, write a failing behavioral test, implement the smallest correction, and verify through the affected public interface.

**Scientific-quality changes:** declare the primary metric and non-regression criteria before implementation. Reuse the existing citation, claim-support, safety, ranking-concordance, retrieval, and ablation evaluators. Use frozen public inputs, isolated caches, identical model settings, and matched retrieval evidence where appropriate. Begin with three paired trials; require improvement on the declared metric without a material regression elsewhere. Treat inconsistent results as inconclusive and continue investigating.

A higher self-reported score or Elo rating alone does not establish improved scientific quality. Model judgments supplement observable evidence; they do not establish equivalence to expert or wet-lab validation.

**Tool additions:** verify a real response, parameter/error handling, provenance, and integration into a real workflow. A registered schema or mocked response alone is insufficient.

**UI changes:** exercise the affected flow in a browser, including loading, errors, refresh, and accessible interaction.

The authorized test boundaries are the API lifecycle and ownership interfaces, durable task execution/recovery, engine workflow outputs, LLM request boundary, retrieval/tool interfaces, report publication, and browser workflows. Record the applicable boundary for each candidate; no further interview is required.

### Required checks

Run targeted checks while developing. Before each code-bearing repository release, run:

```bash
make test-all
make lint
make typecheck
make build
make eval-smoke
(cd app/frontend && bun run test)
make e2e
```

Run `make test-sandbox-linux` when execution confinement or container behavior changes. Run applicable live evaluations with the verified free configuration. Reuse successful checks only when the relevant code, dependencies, configuration, and evaluation inputs are unchanged.

Do not weaken assertions, loosen evaluation thresholds, or add skips merely to obtain a passing release.

### Deployment

- Use a campaign milestone branch and commit after each completed item. Merge through a pull request after required checks pass; attach the PR to the task.
- Deploy only to the existing services. Record the commit, deployment IDs, non-secret configuration changes, and observed deployment status.
- Preserve the API’s single replica, required volume permissions, cache placement, and startup/recovery behavior.
- Use backward-compatible migrations. Verify a consistent backup before any migration touching persistent production data.
- Run the existing production smoke evaluator and exercise a campaign-owned public research goal through the deployed product.
- Disable notifications on campaign test runs. Do not alter other users’ runs or use their private documents as evaluation inputs.
- On failure, restore the last verified release and investigate. A rollback must retain the zero-cost configuration; never restore paid model settings as a recovery shortcut.
- Keep the release item open until the intended deployment is healthy and its required behavior has been observed.

## Cycle protocol

**Session orchestration decision (2026-09-20):** After M1 is complete and verified, the primary agent switches from implementer to orchestrator using `/Users/guy/.codex/skills/orchestrate/SKILL.md`. Delegate implementation to `gpt-5.6-luna` at `max` effort by default for light work, or `gpt-5.6-sol` at `medium` effort for heavy work. Specify model and effort explicitly on fresh-context dispatches. The coordinator owns scope, acceptance criteria, integration, verification, and the persistent `slice · owner · status · evidence · next` ledger; inspect worker diffs and independently verify results before accepting them. Preserve sequential repository investigation and the concurrency ceiling. This user instruction overrides earlier worker-model defaults; M1 remains under the current implementation approach until verified.

At the start of every turn, read `PLAN.md`, relevant project instructions, and the active dossier. Check the working tree and actual release state before acting.

Take the first unchecked item. Search the current codebase before implementing. Replace oversized implementation items with concrete candidate-ID checkboxes before starting them, preserving scope and acceptance criteria on disk.

Use `tdd` for behavioral changes and `ponytail` for minimal implementation. Commit after each item. Discovery and documentation items require concrete, checked evidence; implementation items require working behavior.

At milestone completion:

1. Run its `Done when` check.
2. Invoke the existing `end-of-work-cleanup` skill, including its scoped `deslop` pass and report-only UI scan where applicable.
3. Rerun checks affected by cleanup.
4. Append `— verified` to the milestone’s `Done when` line.
5. Add an architecture and release note to `## Log`.

A turn advances one milestone, or a few items within a large milestone. Resolve implementation ambiguities autonomously and log the options, choice, and reason. Do not reopen settled product decisions.

For transient limits, record the failed operation, reset/retry time, and remaining work. Continue independent work within the current milestone where possible. Never busy-loop requests or mark a blocked acceptance check complete.

End each execution turn with only the required status as its final content:

- Milestone table: name · done/open.
- Open-item count from a fresh grep.
- Next item, or the concrete blocker.

### Starting the loop

When implementation mode is enabled, save this plan as `PLAN.md`, commit it on the initial campaign branch, verify the fresh checkbox count, and return the goal prompt without starting the goal automatically.

This initial plan contains **60 open items**, giving **180 turns**. Recalculate before launch if the checklist changes. Subsequent discoveries may increase work; they do not silently increase the authorized turn limit.

```text
/goal `grep -cE '^[[:space:]]*- \[ \]' PLAN.md` prints 0 — every item in PLAN.md is checked and each milestone's "Done when" holds. Each turn, run /milestone. Stop after 180 turns.
```

## M1 — Free-model walking skeleton and trustworthy baseline

**Done when:** the existing research flow completes locally and in production using verified free models, required baseline checks pass, zero-cost enforcement covers campaign execution paths, and reproducible baseline artifacts are recorded.

- [x] M1-01: Establish campaign records, capture the starting commit and deployment state, and verify access to GitHub, Railway, Vercel, and OpenRouter without exposing credentials.
- [x] M1-02: Reproduce and correct the known disagreement between the live publication gate and release evaluator for speculative contradictions; add a behavioral regression test.
- [x] M1-03a1: Ensure catalogued zero-token-price OpenRouter routes carry zero prompt, completion and per-request price ceilings through the shared request builder, fallbacks and retries; preserve explicitly paid BYOK routing. Verify through the public LLM request boundary.
- [x] M1-03a2: Enforce fresh verified zero-cost eligibility at the shared LLM boundary, including unknown models, retries and fallbacks; preserve explicit BYOK. Reject paid/unknown/unverifiable campaign routes before transport, block charged add-ons, and verify eligible requests carry binding zero-price constraints. The static cap in M1-03a1 alone does not establish current free eligibility.
- [x] M1-03b1: Enforce shared zero-cost admission on app interview, Q&A, announcement, title and restatement completions and credential probes; verify outgoing requests, streaming/reasoning preservation and explicit BYOK isolation.
- [x] M1-03b2: Prevent campaign and credential-scoped executions from reading or writing shared node caches, including forced cache paths; verify isolation without changing ordinary cache behavior.
- [x] M1-03b3: Verify zero-cost admission and credential isolation through durable task execution/recovery and auxiliary engine calls; correct any bypass while preserving task lifecycle semantics.
- [x] M1-03c1: Map retrieval, tools, plugins, skills and embeddings to outbound paths and retained cost evidence; record concrete enforcement gaps and acceptance tests.
- [x] M1-03c2a: Prevent metered web-provider requests/fallbacks and credentialed OpenAlex billing in campaign mode at the standalone MCP provider boundary; preserve anonymous public retrieval and non-campaign behavior.
- [x] M1-03c2b: Qualify resolved MCP server/tool identities and enforce campaign restrictions on both direct and model-driven invocation paths, including custom configurations and availability probes.
- [x] M1-03c2c: Enforce campaign restrictions on workspace network execution and skill credential injection while preserving local computation; verify confinement including the Linux sandbox checks.
- [x] M1-03c3a: Correct the live-discovered PubMed availability mismatch: anonymous retrieval succeeds while the probe returns false before querying. Verify successful and failed actual reachability through the probe without treating a contact email as proof of availability.
- [x] M1-03c3: Verify real public-evidence retrieval through the guarded project interfaces using isolated credentials/configuration; record provenance, availability and rate limits without paid fallback.
- [x] M1-03c3b: Make Europe PMC and its preprint wrappers distinguish transport/parse failures from genuine empty searches through the public tool boundary; preserve failure provenance without paid fallback and verify existing callers handle it.
- [x] M1-03d0: Audit maintained live evaluation entry points, credential loading and evidence gaps; retain the concrete runner map and implementation boundaries.
- [x] M1-03d1: Isolate live scaling, ablation and claim-support runner configuration before app imports: require explicit free OpenRouter settings, prevent paid credential/default and dotenv loading, and verify fail-closed routing through the LLM boundary.
- [x] M1-03d2: Remove the golden runner’s paid configuration assumptions; preserve its INDRA-specific acceptance meaning and fail closed where campaign tool qualification cannot satisfy it. Provide the authorized public-evidence workflow for campaign acceptance without weakening the INDRA check.
- [x] M1-03d3a: Migrate live citation, citation-usefulness and Elo panels to explicit free configuration before app/engine imports; remove paid defaults and verify fail-closed admission without changing offline evaluation behavior.
- [x] M1-03d3b1: Preserve requested and observed model identity plus missing usage/pricing evidence in shared completion telemetry and durable metric merges; keep old checkpoints compatible.
- [x] M1-03d3b2a: Retain raw model telemetry and explicit unknown-cost/observed-model summaries in durable scaling, ablation, claim-support and golden artifacts without mistaking old zero estimates for verified costs.
- [x] M1-03d3b2b1: Capture direct citation/usefulness/Elo panel telemetry and explicit requested-live/offline modes; verify successful panel responses and observed usage through their public interfaces.
- [x] M1-03d3b2b2: Record explicit deterministic-fallback evidence for citation and ranking judgments in direct and durable artifacts, preserving legacy unknowns; verify fallback and no-fallback behavior without changing scientific decisions.
- [x] M1-03d4a: Persist reproducible per-arm identities for exact public inputs, resolved configuration, model roles, fallback/request policies and disabled response caches; retain them in comparison artifacts.
- [x] M1-03d4b: Enforce matched baseline/candidate identities across comparison consumers and direct panels, allowing only declared tier/ablation differences; reject missing or mismatched evidence or rerun both sides, and specify matched retrieval requirements.
- [x] M1-04a: Refresh the public OpenRouter catalog, verify zero-cost eligibility, and record a capability-based shortlist including available new releases and explicit exclusions.
- [x] M1-04a1: Reproduce the native structured-output schema envelope failure at the LLM request boundary, correct the shared envelope while preserving local schema validation and the json_object shim, then retry the live Nex probe.
- [x] M1-04b1a: Reproduce the markerless contradiction failure and implement a shared, bounded semantic verification candidate through single/batch public assessors; preserve located quotes, subject coverage, historical false-positive regressions, budget/parking behavior and verification-failure evidence. This establishes a tested candidate, not scientific acceptance.
- [x] M1-04b1b-r1: Correct the demonstrated short-identifier retrieval omission with a bounded, retrieval-only candidate; verify unseen identifier/paraphrase examples, unrelated-stopword exclusion, unchanged deterministic verdict thresholds, and freshness tracking. Treat scientific adoption as pending the matched live qualification item below.
- [x] M1-05a: Remove local dotenv/model-catalog dependence from mocked-provider app tests using synthetic catalog metadata; preserve production default routes and zero-cost admission, reproduce the isolated failures, and pass the serialized offline verification suite.
- [ ] M1-04b1b-s1: Clarify the primary single/batch partial-support contract for claim-defining scope without schema or runtime-gate changes; preserve same-scope partial support and broad claims through dedicated controls, then verify a fresh matched live candidate. Existing mismatch failures are the red behavioral evidence; prompt edits alone do not complete this item.
- [ ] M1-04b1b: Run three matched baseline/candidate live challenge trials and historical false-contradiction controls with fixed free-model settings and isolated caches. Require improved challenge accuracy/contradiction recall, unchanged .80 recall/.75 accuracy gates, and no material false-contradiction regression; resolve inconclusive results before adoption.
- [x] M1-04b1c: Before adopting semantic verification, persist per-assessment verification method with backward-compatible lineage/readback; distinguish lexical-founded, separately verified and legacy-unknown decisions. Confirm public assessment/report provenance without presenting a model judgment as scientific proof.
- [ ] M1-04b: Qualify shortlisted candidates through actual structured-output, tool-call, app streaming, long-prompt and reasoning-budget interfaces; retain served-model/usage/failure evidence and honor rate limits.
- [ ] M1-04c: Compare representative scientific panel results and select/document a primary and compatible free fallbacks; update configuration only from verified results, preserving BYOK behavior.
- [x] M1-09: Resolve the discovered release-evaluator safety gaps for absent/pending hypothesis statuses and final report screening: reproduce through publication interfaces, reuse live rules or enforce verified completed-artifact preconditions, and retain fail-closed safety behavior.
- [x] Run the baseline verification suite and browser flow; resolve failures that prevent trustworthy campaign evaluation.
- [ ] Complete a local live run with public evidence through interview, retrieval, durable execution, recovery/reopen, and report publication; retain sanitized artifacts.
- [ ] Merge and deploy the free-model configuration and necessary support changes; verify actual serving configuration, production smoke checks, and a campaign-owned live run.
- [ ] Freeze the post-switch baseline, evaluation inputs, model settings, cache-isolation procedure, and release/rollback procedure for subsequent comparisons.

## M2 — Kaimen-Inc/Co-Scientist

**Done when:** its substantive mechanisms have recorded dispositions, all accepted changes pass their criteria and are deployed, and its temporary checkout is removed.

- [ ] Acquire and pin [Kaimen’s repository](https://github.com/Kaimen-Inc/Co-Scientist); inspect implemented strategies, prompts, schemas, storage, tests, benchmarks, and licensing.
- [ ] Compare citation provenance, structured output, proximity, scheduling, model routing, and budget handling with current local behavior; distinguish shipped mechanisms from advertised or unfinished ones.
- [ ] Expand accepted candidates into concrete implementation items and complete them test-first, preserving the existing workflow and provider contracts.
- [ ] Run candidate evaluations, milestone verification, and cleanup; retain evidence for adoption, coverage, and rejection decisions.
- [ ] Merge, deploy, verify, complete the dossier and architecture log, and remove the temporary checkout.

## M3 — conradry/open-coscientist-agents

**Done when:** the archived implementation has been assessed against current code, justified improvements are verified and deployed, and its temporary checkout is removed.

- [ ] Acquire and pin [conradry’s repository](https://github.com/conradry/open-coscientist-agents); inspect the framework, supervisor, model pools, research integration, monitoring, and licensing.
- [ ] Assess specialist-model assignment, action history, research synthesis, tournament inspection, and visualization; account for synchronous execution, in-memory state, and stated evaluation limitations.
- [ ] Expand and implement accepted candidates without importing the prototype’s durability or concurrency limitations.
- [ ] Verify each change against the current baseline, run release checks and cleanup, and document covered or rejected mechanisms.
- [ ] Merge, deploy, verify, complete retained documentation, and remove the temporary checkout.

## M4 — LLNL/open-ai-co-scientist

**Done when:** claimed and implemented behavior are distinguished, accepted improvements are verified and deployed, and its temporary checkout is removed.

- [ ] Acquire and pin [LLNL’s repository](https://github.com/llnl/open-ai-co-scientist); inspect agent execution, UI lifecycle, artifacts, timeout handling, tests, and licensing.
- [ ] Compare failure visibility, cycle artifacts, model selection, hypothesis interchange, and scientific agent behavior; identify simplified or placeholder mechanisms.
- [ ] Expand and implement only candidates that improve a demonstrated local gap.
- [ ] Run behavioral and applicable live checks, release verification, and cleanup; preserve the assessment evidence.
- [ ] Merge, deploy, verify, finish the dossier and architecture log, and remove the temporary checkout.

## M5 — raktim-mondol/co-scientist

**Done when:** substantial scientific and operational mechanisms have recorded dispositions, accepted changes preserve Google-backed invariants and pass evaluation, and the release and cleanup are complete.

- [ ] Acquire and pin [raktim-mondol’s repository](https://github.com/raktim-mondol/co-scientist); inspect scheduling, research, evidence, reflection, ranking, proximity, feedback, experiment design, tests, and licensing.
- [ ] Compare ranking position bias, uncertainty-aware pairing, atomic rating updates, retrieval-failure handling, provenance, and review depth; explicitly assess differences from the paper-backed Elo system.
- [ ] Expand and implement accepted mechanisms while retaining documented Elo behavior and existing hypothesis lifecycle semantics.
- [ ] Run ranking, evidence, scheduling, and other affected evaluations; complete release checks and cleanup.
- [ ] Merge, deploy, verify, preserve decisions and architecture notes, and remove the temporary checkout.

## M6 — K-Dense-AI/scientific-agent-skills

**Done when:** the catalog has a documented coverage assessment, each selected skill works through the existing harness with appropriate attribution and bounded dependencies, and the release and cleanup are complete.

- [ ] Acquire and pin [K-Dense’s repository](https://github.com/K-Dense-AI/scientific-agent-skills); inventory skill families, scripts, dependencies, selection metadata, and component licenses.
- [ ] Compare coverage against existing MCP tools and the vendored Google DeepMind skills; identify concrete domain or workflow gaps without conflating the two bundles.
- [ ] Expand and integrate justified skills or techniques through the existing selection, workspace, and confinement mechanisms; avoid wholesale catalog installation.
- [ ] Verify useful execution, dependency availability, provenance, context overhead, and affected scientific behavior; run release checks and cleanup.
- [ ] Merge, deploy, verify, update attribution and retained findings, and remove the temporary checkout.

## M7 — SakanaAI/AI-Scientist

**Done when:** applicable novelty and review techniques have been evaluated, reuse complies with the pinned source’s terms, accepted changes are deployed, and the temporary checkout is removed.

- [ ] Acquire and pin [Sakana’s repository](https://github.com/SakanaAI/AI-Scientist); inspect novelty search, review ensembles, experiment feedback, evaluations, and the actual source license.
- [ ] Compare applicable techniques with existing novelty, reflection, simulation, and reporting behavior; separate them from autonomous paper production and the removed discovery product.
- [ ] Expand and implement justified techniques through a compatible reuse route; do not copy restricted code under an assumed permissive license.
- [ ] Evaluate novelty/review improvements against fixed evidence and existing baselines; complete release checks and cleanup.
- [ ] Merge, deploy, verify, record evidence and attribution, and remove the temporary checkout.

## M8 — synthetic-sciences/openscience

**Done when:** relevant workbench and runtime mechanisms are assessed, accepted changes improve existing flows without adding a second runtime, and the release and cleanup are complete.

- [ ] Acquire and pin [OpenScience](https://github.com/synthetic-sciences/openscience); inspect sessions, request admission, events, permissions, artifacts, provider handling, tests, and licensing.
- [ ] Compare request receipts, idempotency, cancellation, capability discovery, provenance, and reconnect behavior with current durable tasks and authenticated SSE.
- [ ] Expand and implement accepted improvements within existing API and UI flows, preserving ownership and restart behavior.
- [ ] Verify retries, cancellation races, reconnects, artifact visibility, and affected browser interactions; complete release checks and cleanup.
- [ ] Merge, deploy, verify, preserve the assessment and architecture notes, and remove the temporary checkout.

## M9 — mims-harvard/ToolUniverse

**Done when:** tool-system and catalog opportunities have recorded dispositions, accepted connectors or techniques work through the existing runtime, and the release and cleanup are complete.

- [ ] Acquire and pin [ToolUniverse](https://github.com/mims-harvard/ToolUniverse); map discovery, schemas, validation, errors, caching, composition, connectors, tests, and licenses.
- [ ] Compare its contracts and connector families with existing tools; inspect individual connectors where a concrete coverage or reliability gap exists.
- [ ] Expand and implement selected connectors or mechanisms without introducing a competing tool runtime; maintain free execution and explicit capability availability.
- [ ] Verify real connector behavior, failures, provenance, caching, and offline contracts; run applicable live checks, release checks, and cleanup.
- [ ] Merge, deploy, verify, preserve per-component attribution and findings, and remove the temporary checkout.

## M10 — Future-House/robin

**Done when:** applicable research-feedback mechanisms are evaluated, accepted improvements work without unauthorized paid dependencies, and the release and cleanup are complete.

- [ ] Acquire and pin [Robin](https://github.com/Future-House/robin); inspect candidate generation, trajectories, assay planning, analysis feedback, prompts, persistence, and licensing.
- [ ] Compare feedback from experimental findings, multi-trajectory synthesis, and experiment-design specificity with the existing hypothesis workflow; identify Edison-dependent behavior explicitly.
- [ ] Expand and implement justified mechanisms using existing compatible interfaces and available free services, without adding a separate experimental-execution product.
- [ ] Verify feedback propagation and affected scientific outputs with fixed public examples; complete release checks and cleanup.
- [ ] Merge, deploy, verify, preserve findings and architecture notes, and remove the temporary checkout.

## M11 — Select justified additional references

**Done when:** every proposed additional repository has a recorded selection decision, no more than three are selected, and each selected source has a complete sequential milestone before final acceptance.

- [ ] Review the follow-up register and identify specific unresolved gaps that the nine required repositories did not adequately address.
- [ ] Select zero to three additional repositories based on distinct relevant mechanisms, accessible evidence, reuse feasibility, and the campaign boundaries; document exclusions.
- [ ] Insert one five-stage milestone per selected repository using the same acquire, compare, implement, verify, and release/cleanup contract; renumber final acceptance and refresh the open-item count without extending the turn limit.

## M12 — Final integration and campaign acceptance

**Done when:** all required and selected repositories are closed, no accepted or promising candidate remains unresolved, all applicable checks pass, the final intended release is healthy, and a fresh grep reports zero open items.

- [ ] Reconcile every candidate, milestone, source reference, attribution record, and acceptance result; resolve gaps rather than relabeling unfinished work.
- [ ] Verify the combined system across research generation, evidence, ranking, recovery, tooling, reports, ownership, and browser behavior using the final code and free-model configuration.
- [ ] Confirm intended commits and configuration are deployed, run final production smoke and public-goal verification, and establish the final known-good rollback point.
- [ ] Complete the campaign report with adopted improvements, rejected mechanisms, measured outcomes and limits; remove temporary checkouts and scratch artifacts, perform final cleanup, commit the closing records, and verify the checklist count.

## Log

**Decisions established before execution**

- Fidelity-led improvement is the objective; external implementations do not establish Google behavior.
- Existing UI and report flows may change autonomously; major redesigns and separate product modes remain out of scope.
- The current stack and hosting structure remain.
- References are investigated locally, one at a time, with durable findings retained after checkout removal.
- The nine named sources are mandatory and ordered; at most three additional sources may be selected.
- Additional spending is prohibited; free-model compatibility and zero-cost enforcement precede live campaign work.
- Promising but inconclusive candidates stay open for further investigation.
- Verified changes are merged and deployed after each repository.
- A repository may legitimately produce no changes when the assessment supports that conclusion.
- The initial limit is 180 turns. Reaching it with open work is an incomplete campaign, not successful completion.

**Cycle entry format**

Date and cycle number; milestone and item IDs; starting and resulting commits; actions and evidence; decisions with alternatives and rationale; architecture changes and connections; PR/deployment identifiers; free-model configuration and rate-limit state; remaining work and next action. Do not put checkboxes in this log.

### 2026-09-19 — Cycle 1, M1 in progress

Started at `927d2bd3` on `feat/external-m01-free-baseline` (preserves the trust-boundary documentation added after plan commit `cd54b76c`). Previous preparation made progress by committing the approved plan; this is execution cycle 1 of 180.

M1-01 complete: created source inventory, campaign procedures and baseline dossier with sanitized access and deployment snapshots under `references/external/`. Ignored sequential work checkouts. GitHub, Railway, Vercel connector and authenticated OpenRouter metadata reads succeeded; API health is healthy. All three services still serve `7dce086d`. No inference or production mutations. Local model settings are paid-route names; production selects a free-suffix model whose current pricing and availability remain unverified. Use Vercel connector reads after CLI token failure; do not interpret platform READY/health as scientific workflow acceptance. Campaign deployment authorization remains in force under the task's precedence over general confirmation guidelines.

Architecture: records now connect the authoritative checklist to source inventory, operational procedures, and dated sanitized deployment evidence. No runtime change yet. Next: M1-02, reproduce evaluator drift and reuse the live claim-role-aware predicate. Independent read-only review supports this approach. Full baseline and zero-cost qualification remain open.

M1-01 committed as `765288a6`. M1-02 then reproduced the defect with a failing public evaluator test (`withhold` instead of `release`) and removed its duplicated contradiction predicate in favor of the live helper's supplied-edge interface. Verification: 10 evaluator tests and 44 app publication/grounding/drain tests pass offline; targeted Ruff lint/format and mypy pass. Cleanup/deslop removed the obsolete helper; no UI changed. The preexisting Starlette/httpx deprecation warning is recorded, not suppressed. Production is unchanged; no PR or deployment yet.

The source audit split the oversized zero-cost item into M1-03a–d without changing its scope. Review found a separate legacy safety-status mismatch, recorded as M1-09; it is not bundled silently into the contradiction fix. App direct completions already reuse the engine's thinking/gateway body builder, so investigate actual outgoing requests before adding any abstraction. Unknown/free static pricing currently omits a gateway price cap. No live batch is authorized to run until enforcement and fresh price qualification hold. Fresh open count is 62 after two completions, a four-way split and one discovered item; the limit remains 180 turns. Next cycle starts with M1-03a. M1 acceptance is not yet satisfied.

Final independent review found no M1-02 blocker and confirmed the obsolete helper is fully removed. It also noted that evaluator artifacts cannot currently reproduce final rendered-report safety screening; M1-09 now explicitly includes that preexisting gap. All 44 targeted app checks had passed before accepting M1-02. No additional cleanup changes were needed.

### 2026-09-19 — Cycle 2, M1-03a1

Previous turn: progress, with campaign records and the verified evaluator correction committed. Current start is `0e3ae327`, clean branch. Fresh Railway read confirms unchanged API/MCP SUCCESS deployments at `7dce086d`; no release action this cycle.

Split M1-03a into the bounded request-ceiling correction (a1) and fresh eligibility enforcement (a2), preserving all acceptance requirements. Official OpenRouter provider-routing documentation supports inclusive zero token and per-request ceilings. Chose to fix the existing shared builder, rather than introduce another routing abstraction. The former zero-price early return was reproduced as three failing public-boundary cases. Now free routes send zero prompt/completion/request ceilings, including JSON budget escalation and tool calls; paid BYOK retains its existing priced route. A real LiteLLM serialization test with HTTP transport mocked proves the wire JSON preserves the cap. This is offline request evidence, not live pricing/serving evidence.

Verification: 61 engine routing/reasoning/BYOK tests, 19 app model/thinking tests, targeted Ruff lint/format and mypy, and diff checks pass using the root `.venv` (LiteLLM 1.80.17, httpx 0.28.1, pytest 9.0.3). Scoped cleanup/deslop removed contradictory comments and retained no extra runtime abstraction. SDK Pydantic and async shutdown warnings remain unsuppressed; no assertion was weakened. No UI changed.

Review execution incident: the read-only reviewer invoked `uv run`, generating `engine/uv.lock` and syncing the separate preexisting `engine/.venv` (46 packages installed, 43 uninstalled). Removed its confirmed generated lock; did not guess the previous package set. Root `.venv` is separate and unchanged, and all reported acceptance checks use it. Future checks use the existing root runner, never dependency-manager commands for read-only review.

Architecture: one shared provider block now carries the zero ceiling across all callers that already use it. Full model eligibility, unknown/paid route rejection, charged add-on control, app/tool coverage, and live comparisons remain open. No provider inference, credentials changes, PR or deployment. Next: M1-03a2. Open count remains 62 (one split adds one; a1 completion removes one); the 180-turn limit is unchanged.

### 2026-09-19 — Cycle 3, finish M1-03a1 review and commit

The preceding prompt-only handoff made no execution progress. Revalidated the
pending work against disk: cycle 2's a1 changes were still uncommitted at
`0e3ae327`. Completed its review before starting the next dependent item.
Railway read confirms API `a6ddd7f0-3bb5-4ad1-bed8-14809846e88e` and MCP
`0d49864d-782b-421f-ab8b-02b608a9c5d4` remain SUCCESS at `7dce086d`.

Review corrections: removed stale uncapped-free-route claims from pricing
comments; expanded the catalog assertion to standalone routes; exercised a
real tool-result continuation in the offline public-boundary test. Reused the
existing queued completion fixtures instead of duplicating them. Root runner:
61 engine tests and 19 app tests pass again; Ruff lint/format, targeted mypy and
diff checks pass. Existing SDK warnings remain documented. No inference,
production change, migration, or new dependency. Fresh eligibility remains
M1-03a2; the static cap is not a current-price qualification. The architecture
and release state recorded in cycle 2 otherwise remain unchanged.

Final fresh-context read-only review found no blocker and confirmed the fixture
simplification. M1-03a1 is ready for its item commit; M1 remains open. The next
cycle starts at M1-03a2. Fresh open count: 62; authorized limit: 180 turns.

### 2026-09-19 — Cycle 4, M1-03a2

Previous turn: progress, committed M1-03a1 as `367d8a22`; this cycle began with
a clean tree. Fresh Railway status still shows API/MCP SUCCESS at `7dce086d`
with unchanged deployment IDs. No inference, production mutation or PR.

Implemented current-price admission at the shared physical-completion boundary,
before moving the existing provider counter there from its three callers.
Exact model/fallback entries are checked against public catalog data cached for
60 seconds; expired evidence cannot survive refresh failure. Decimal prices,
text-only request scope and binding zero-price ceilings enforce the selected
contract. Campaign mode applies even to explicit credentials; ordinary BYOK
remains separate. No paid substitute is attempted. Declared the already-installed
httpx 0.28.1 as a direct engine dependency; no environment was synchronized.

Decision: listed :free variants with explicit zero token prices can use the
provider's documented free-inference contract for omitted ancillary fields;
other zero-price promotions need explicit ancillary rates. A suffix or missing
price alone is insufficient. Nonempty conditional schedules are unqualified
until their applicability can be established; this is not a permanent candidate
rejection. All selected fallback routes must pass, rather than silently deleting
unavailable ones. Full policy and source links are in the baseline dossier.

Review uncovered two admission bypasses: old paid BYOK cache entries skipped the
transport seam, and LiteLLM global aliases/fallbacks could reroute later. Both
were reproduced before fixing. Chose campaign-only LLM cache disable over a
second pre-cache admission implementation; ordinary BYOK cache behavior stays
intact. Rejected SDK routing overrides without modifying shared globals.
Malformed request/catalog structures now produce terminal policy errors rather
than retries. The engine test catalog is a synthetic external-boundary fixture;
it never replaces the policy under test or makes live network calls.

Verification: six initial missing/paid-price cases failed before implementation;
three cache cases, two SDK-route cases, six malformed-container cases and three
malformed-modality cases also failed before their corrections. All 429 LLM tests
passed before the final malformed-structure tightening; all 109 affected policy,
wire-format, budget, cache and wrapper tests passed afterward. Targeted Ruff
lint/format and mypy pass; existing LiteLLM Pydantic/shutdown warnings remain
unsuppressed. Scoped cleanup/simplification reused the shared cache and counter
instead of adding parallel machinery. No UI changed.

A real credential-free catalog request and the actual admission function found
447 entries, 22 metadata-qualified routes, and the deployed primary absent.
Retained sanitized evidence in `openrouter-eligibility-2026-09-19.json`; this is
metadata evidence, not an inference or capability result. Current production is
unchanged and M1 is not accepted. Next: M1-03b, wire and verify the same admission
policy in streaming/auxiliary app paths and durable tasks. Open items: 61;
authorized turn limit remains 180.

Final independent read-only review found no remaining M1-03a2 blocker after
confirming the request/cache/SDK protections and strict modality validation.

### 2026-09-19 — Cycle 5, M1-03b1

Previous prompt-only turn made no execution progress. Revalidated pending b1
work at `56684cbb` and completed its verification. Split b into app admission
(b1) and durable execution/cache isolation (b2) to preserve concrete boundaries.
Six red tests demonstrated paid campaign requests reaching app transports.
One shared app wrapper now applies existing engine admission to interview, Q&A,
announcement, title, restatement and credential probes. It preserves streams,
reasoning and existing retry/fallback behavior. Review's unscoped BYOK-flag
bypass was reproduced before removing the flag; credential probes instead use
the existing scoped credential context. This avoids a second provenance scheme.

Verification uses the root virtual environment and synthetic provider/catalog
fixtures, never live inference. Q&A tool continuation and interview reasoning
retry exercise repeated admission; forced-offline tests include restatements
and announcements. Scoped cleanup/deslop reused existing QA fixtures and removed
the redundant override. No UI changed. Full app mypy reports 21 errors in three
unchanged safety modules around the HypothesisSafetyReview alias; keep baseline
verification open to resolve these, with no skipped assertions or weakened rules.

Fresh Railway read: API/MCP still SUCCESS at `7dce086d`, deployment IDs unchanged
from cycle 4. No PR, deployment, new model selection, spend or live evaluation.
App request-boundary tests do not establish scientific or production acceptance.
Next: M1-03b2 durable execution/recovery, auxiliary calls and node-cache isolation.
The 180-turn limit is unchanged; M1 remains open.

Final result: 103 targeted app tests pass; Ruff and diff checks pass. Existing
six dependency deprecation warnings remain unsuppressed. Independent final
read-only review found no remaining app-admission blocker. M1-03b1 is complete
at the request boundary; its item commit records these changes. Fresh open
count: 61.

### 2026-09-19 — Cycle 6, M1-03b2

Previous turn: progress, committed app admission as `f400defe`; began clean.
Split the remaining b2 scope into node-cache isolation (b2) and durable/auxiliary
execution verification (b3), preserving all criteria. Reproduced four shared
cache leaks for campaign/BYOK contexts with and without force. The cache now
ignores reads and writes in those contexts; ordinary behavior remains covered.
Chose the existing credential ContextVar and campaign flag over a new namespace
because old entries carry no experiment or credential provenance.

Architecture: whole-node reuse can no longer skip campaign execution or share
BYOK outputs across runs. This complements the earlier LLM response-cache guard.
A literature-node regression observes source failure rather than stale success.
Seventy cache/storage/generation/literature-node tests, targeted mypy, Ruff and
diff checks pass. Scoped cleanup found no redundant runtime abstraction or UI
change. No live inference, spending, dependency installation, PR or deployment.
Fresh Railway status confirms API/MCP SUCCESS at `7dce086d`.

Read-only review traced recovery and auxiliary credential flow; it found no
structural bypass. Evidence and next behavioral tests are retained in the
baseline dossier. M1-03b3 stays open until worker-level and auxiliary admission
checks pass. Open count remains 61 after splitting and completing one item;
turn limit remains 180. M1 acceptance is still unverified.

### 2026-09-19 — Cycle 7, M1-03b3

Previous turn made progress: node-cache isolation committed as `dc73a822`.
Started clean. Rechecked durable dispatch, recovery and auxiliary call sites;
all already share the intended credential and admission boundaries. Added
worker-level behavioral evidence rather than another runtime wrapper.

Eighteen new cases exercise persisted credential reload, fresh and reclaimed
leases, child tasks and the off-loop/async bridge, across claim, batched claim
and semantic safety calls. Paid campaign requests stop before transport;
synthetic qualified free requests carry zero ceilings and the run's key;
ordinary paid BYOK remains separate. Recovered tasks increment their attempt,
complete, and leave no credential context behind. Admitted transport calls stop
at a test sentinel, so this is request/lifecycle evidence, not live inference
or scientific-quality evidence. No defect required a new runtime correction.

Forty-five worker/recovery/BYOK/bridge tests pass, with six existing dependency
warnings. Scoped cleanup extracted repeated outgoing-request assertions and
kept the test within lint complexity limits; all 18 new cases pass afterward.
Ruff and diff checks pass. No UI, dependencies or production settings changed.
Fresh Railway read shows API/MCP SUCCESS at `7dce086d`; no PR/deployment or spend.
Next: M1-03c retrieval/tools/plugins/skills/embeddings audit and free retrieval
verification. Open count: 60. M1 acceptance and the 180-turn limit are unchanged.

Final read-only review added an explicit assertion that ordinary paid BYOK
requests do not carry the campaign zero-price cap. All 18 cases pass with that
assertion, and targeted lint/format checks remain clean.

### 2026-09-19 — Cycle 8, M1-03c1 cost-path audit

Previous turn made progress: durable admission tests committed as `a44fc721`.
Started clean. Split c into evidence-backed audit, implementation and live
retrieval acceptance; no scope removed. Recorded source paths, current official
pricing references, seven concrete findings and required boundary checks in
`references/external/baseline/retrieval-cost-audit.md`.

Findings: web provider credentials/fallbacks, optional OpenAlex credentials,
custom MCP servers and skill credential injection escape the model-only guard.
Whole-node cache isolation is already handled. No embedding API exists in the
maintained app/engine path; semantic retrieval and proximity use guarded LLMs.
Official OpenAlex and Tavily docs confirm free allowances can coexist with paid
usage; no account billing guarantee was inferred. The separate read-only audit
confirmed both MCP invocation paths and configuration override routes.

Decision: use the existing campaign flag across upcoming enforcement rather
than a second opt-in that can leave partial protection. Qualify actual server
and tool identities, not just advertised names/effect labels. Keep local
computation and useful public retrieval, and preserve non-campaign behavior.
Implementation choices remain c2 work, to be driven by failing boundary tests.

No runtime files changed; source inspection and official documentation reads
only. No model/retrieval experiment, spending, dependencies, PR or deployment.
Railway status returned API/MCP SUCCESS at `7dce086d`; CLI also warned that token
refresh persistence lacked filesystem permission, but its read succeeded.
No credentials were printed or changed. Scoped documentation cleanup distinguishes
inventory from qualification and records remaining implementation/live evidence.
Next: M1-03c2. Fresh open count: 61 (split adds two; audit completion removes one).
M1 remains open, and the limit remains 180 turns.

Final independent audit review corrected the network-enabled workspace source
to `open_draft_workspace` (review workspaces default to network disabled), and
clarified that configured web search is conditionally registered at runtime.
These corrections are retained in the audit; no enforcement is claimed.

### 2026-09-19 — Cycle 9, M1-03c2a

Previous turn: progress, audit committed as `a3541dd2`; started clean. Split
provider enforcement, custom MCP admission and workspace confinement into c2a,
c2b and c2c without removing acceptance criteria. Four red tests reproduced
metered direct transport, provider/fallback availability and OpenAlex host-key
attachment under campaign mode.

The standalone MCP package now enforces the existing strict campaign flag before
metered web transport and provider selection. OpenAlex uses anonymous requests
with environment proxy routing disabled; 429 remains unavailable and does not
retry with a host key. Chose a small independent parser because this server is
packaged/deployed without the engine; no dependency or alternate flag added.
No arbitrary local result cap was added: anonymous access is bounded by provider
quota, with rate limits surfaced rather than paid fallback. Deployment must
explicitly configure the MCP service too; caller environment is not inherited.

Eighty-seven targeted tests and strict mypy on four changed files pass. Extra
coverage checks actual server startup registration, invalid values, normal keys,
quota failure and HTTP request serialization. Scoped cleanup uses existing HTTP
fixtures; no UI changed. Live retrieval/model capability remains unverified.
Fresh Railway read shows API/MCP SUCCESS at `7dce086d`; the same nonfatal CLI
refresh-persistence warning appeared. No deployment, PR, inference, provider
search, dependency installation or spending. Next: M1-03c2b. Open count: 62;
M1 stays open and the 180-turn limit is unchanged.

Final independent read-only review found no c2a blocker. All 18 new cases pass
after the final proxy-setting assertion; the other provider checks are unchanged.

### 2026-09-19 — Cycle 10, M1-03c2b

Starting commit `d3ba165b`. The intervening goal-prompt reply made no repository
progress; revalidated the pending implementation and resumed its red tests.
Two stale-client schema/availability tests failed before adding discovery guards.
The original direct/model rejection tests also failed before admission existed.

The client now binds one explicit operator-qualified reference endpoint and its
reviewed public tool set before discovery, then rechecks serving policy and
configuration before both invocation paths. Custom transports, multiple servers,
redirects and environment proxies cannot change that route. Registered server
calls enforce the same allowlist even if registered before campaign mode.
The server package remains independent of the engine; a cross-package policy
contract test catches drift without creating a runtime dependency.

Decision: use the existing caller/server campaign flag plus an explicit endpoint
binding, rather than infer trust from familiar tool names or arbitrary server
metadata. Metadata checks compatibility, not source authenticity. Operators must
verify our deployed revision and trusted network/TLS route. Every call rechecks
policy rather than caching it across potential deployment changes. No new tool
runtime or dependency was introduced.

Verification: 75 engine MCP boundary tests and all 264 standalone MCP tests pass;
strict mypy passes for the two changed engine modules and all 70 server files.
Ruff lint/format and diff checks pass. Scoped cleanup retained the small duplicated
wire-protocol constants because packages deploy independently; no UI was changed.
Evidence is offline, not live retrieval. No inference, provider search, spending,
PR or deployment occurred. Fresh Railway state: API and MCP SUCCESS at
`7dce086dd483831b40a12532a84cf7321f058e52`, deployment IDs unchanged from cycle 9.
Next: workspace confinement and skill credentials (M1-03c2c); live retrieval and
all milestone acceptance/release checks remain open. The 180-turn limit remains.

Final independent read-only review found no concrete admission bypass. Item
M1-03c2b is complete locally; its implementation and evidence are committed with
this cycle. Fresh open count: 61. M1 acceptance remains unverified.

### 2026-09-19 — Cycle 11, M1-03c2c

Starting commit `407c3a04`; previous cycle made progress by committing MCP
admission. Re-read the first unchecked item, code paths and cost dossier.
Reproduced real network access after campaign mode on both bounded and persistent
workspace commands, then enforced offline OS confinement at both launch paths.
Two local computations and a live loopback connection control distinguish actual
network denial from a sandbox that cannot launch commands.

Decision: scope the policy to workspace execution, rather than globally changing
all sandbox wrapping. The global option would reject trusted Git snapshot calls
and damage provenance; those are host-owned local operations, not model-authored
commands. Custom full-access/external workspace policies fail closed. Schemas
use the effective policy too, including old sessions. Remote skill instructions
are withheld; drafting keeps qualified MCP retrieval. Campaign commands receive
no skill credentials and record no unperformed source-query attribution.
Independent review found two stale-provider gaps; reproduced each before closing
old read_skill dispatch and skill attribution in an offline command.

No new dependency, runtime, reference checkout, inference or provider search.
Docker Desktop was stopped and was started for required Linux verification.
The initial nested macOS sandbox could not launch; elevated local tests proved
real confinement instead of counting that launch failure as a passing denial.
Fresh Railway read: API/MCP remain SUCCESS at `7dce086d`; no deployment or PR.
Final validation and commit are recorded below. Next item is real guarded public
retrieval (M1-03c3); M1 acceptance and release remain open.

Final verification: 87 affected macOS checks pass; strict mypy covers seven
changed modules; Ruff lint/format and diff checks pass. `make test-sandbox-linux`
passes with preflight-confirmed Landlock (133 passed, 3 existing platform skips)
and bubblewrap (132 passed, 4 existing platform skips). All seven campaign tests
also pass against each backend with the final tool-dispatch module mounted;
none of the new campaign checks is skipped. The scoped cleanup/deslop pass found
no unused code or scratch files in the change; no UI changed. Final independent
read-only review reports no remaining bypass. M1-03c2c is complete locally;
commit contains its implementation and evidence. Open count: 60. No free-model
selection, live retrieval, production acceptance or deployment is claimed.


### 2026-09-19 — Cycle 12, M1-03c3a and live retrieval

Starting commit `3bd22758`; cycle 11 made progress by committing verified
workspace confinement. Isolated local MCP and engine-client processes used
empty environments, dotenv disabled, campaign mode enabled, no credentials or
proxies, and temporary caches. Real searches for PMID 22745249/the matching
paper title returned one record each from PubMed, Europe PMC and OpenAlex.
Both direct invocation and a model-shaped tool envelope were exercised without
any model inference. The initial PubMed canary falsely returned unavailable
solely because the contact-email variable was absent, while retrieval succeeded.

Added M1-03c3a before implementation. Two behavioral cases failed: anonymous
success and anonymous transport failure must both actually query the service.
Removed the email prerequisite while retaining the actual canary and its failure
handling, and corrected the startup diagnostic. After restarting our isolated
server, the live probe returned true; a paid web-tool attempt was rejected before
execution. All 266 standalone MCP tests pass, strict mypy passes 71 files, and
the two new regression cases pass after formatting. No dependency or UI changes.
Scoped cleanup removed the now-unused os import; no generic probe harness added.
This correction is committed separately from the retained retrieval evidence.


Live retrieval evidence is retained at
`references/external/baseline/retrieval-2026-09-19/`, including exact results,
source IDs, DOI, abstract hashes, input queries, durations, serving policy,
filtered source status logs and the isolated experiment script. Independent
review approved the PubMed correction and bounded retrieval acceptance.
M1-03c3 is verified locally; no model inference or spending occurred. Discovery
also exposed Europe PMC's service-error/empty-result ambiguity; added M1-03c3b
rather than silently treating it as covered. Rate limiting was not observed and
is not claimed tested live. Production API/MCP remain SUCCESS at `7dce086d`.
No PR or deployment. After the evidence commit, next item is M1-03c3b; fresh
open count is 60. M1 acceptance and the 180-turn limit remain unchanged.


### 2026-09-19 — Cycle 13, M1-03c3b

Starting commit `b6eba783`; previous cycle committed the PubMed correction and
real public retrieval evidence. Re-read the current plan and failure paths.
Nine failing server cases reproduced false-empty and malformed-response behavior
across Europe PMC and its wrappers. Two failing engine cases exposed the legacy
MCP error text returning an empty dictionary and SDK errors being re-requested.
A separate failing HTTP429 case pinned preservation of Retry-After.

Decision: reuse SDK ToolException at the existing search boundary rather than
add a parallel error protocol. Source-labelled server errors carry status/retry
hints in text because that is what survives MCP serialization. Reported failures
are not immediately retried or broadened; genuine transport/decoding transients
retain bounded retry. Existing per-source exception handling retains diagnostics
while allowing healthy sources to finish. No paid fallback or new dependency.

Actual local MCP transport with an injected 429 returned the expected exception
and preserved its retry hint after exactly one source attempt. This was local
fault injection, not a live public-service quota event; no inference or external
provider request occurred. The temporary server was stopped. Retained evidence:
`references/external/baseline/europepmc-errors-2026-09-19.json`.

Final verification: all 274 standalone MCP tests and 34 affected engine tests
pass; strict mypy passes all 71 MCP files and the changed engine module. Ruff
and diff checks pass. Scoped cleanup removed the false-empty helper and duplicate
error logging; no UI changed. Independent final review approved the behavior and
retained evidence. Fresh Railway status remains API/MCP SUCCESS at `7dce086d`;
no PR or deployment. Item complete locally. Next: M1-03d evaluation-runner
admission and served-model/cost evidence. Fresh open count: 59; M1 remains open.


### 2026-09-19 — Cycle 14, M1-03d0

Starting commit `5b39e218`; the intervening goal-prompt reply changed no campaign
state. Revalidated the clean worktree, runner source and Railway deployment
metadata. API/MCP remain SUCCESS at `7dce086d`; no inference or release occurred.
Read-only independent review and direct inspection identify two credential
loaders, three paid panel defaults, independent Pydantic dotenv loading, and
missing served-model/comparison evidence. Retained audit:
`references/external/baseline/evaluation-runner-audit.md`.

Split M1-03d into concrete implementation boundaries before edits. Audit complete;
all configuration, telemetry, comparison and live acceptance work remains open.
Reuse the existing transport admission and telemetry rather than another pricing
or routing system. Do not require a :free suffix alone: a freshly verified
zero-price promotional route can qualify under the existing policy. Preserve
unknown observed costs as unknown; estimated zero is not a billing receipt.
Golden run requires INDRA, which campaign MCP does not admit; preserve that
check and use the authorized public-evidence research flow for campaign acceptance.
No runtime changes, dependencies or new reference acquisitions in this cycle.
Next: M1-03d1. Turn limit remains 180.

Independent final review found no lost scope and corrected the audit wording:
only scaling/ablation live modes require the paid key; offline modes do not.
Scoped documentation cleanup also corrected stale campaign procedure statements
about already-verified local controls, without claiming production qualification.
No runtime code changed; source cross-check and `git diff --check` pass.
Fresh open count: 62 (three additional unchecked items from the explicit split).


### 2026-09-19 — Cycle 15, M1-03d1

Starting commit `a16e3458`; previous cycle completed the runner audit and
implementation split. Revalidated the worktree and live Railway metadata:
API/MCP remain SUCCESS at `7dce086d`. No campaign inference or deployment.

Reproduced absent free-mode enforcement through a fresh-process shared-runner
test. Removed the DeepSeek disk loader and obsolete CLI key gates. Scaling,
ablation and claim-support now require explicit OpenRouter MODEL_NAME and an
environment OpenRouter key before app imports. A shared evaluation helper pins
all model roles, enables existing physical request admission, strips other API
keys and disables dotenv; app Settings now honors that disable flag. A second
failing subprocess exposed case-insensitive credential loading; removal now
also handles lowercase keys. Calls after app settings load are rejected rather
than pretending an already-configured process has been isolated.

The public call_llm test supplies synthetic catalog/provider responses: paid
metadata is rejected before transport, while a zero-price response carries
zero prompt/completion/request ceilings. This is behavioral verification, not
live model qualification or billing evidence. dotenv restoration and auxiliary
model isolation are exercised in fresh subprocesses with synthetic credentials.
No additional dependencies or pricing implementation. Golden/direct-panel
migration and telemetry/comparison evidence remain M1-03d2–d4.

Verification: 19 targeted evaluation tests pass, including offline ablation,
scaling and claim-support flows. Five configuration tests pass again after the
case-insensitive credential fix. Strict evaluator mypy passes four changed
modules; app config typecheck passes. Ruff lint/format and diff checks pass.
Independent read-only approach and final reviews found no blocking issue;
scoped cleanup removed the obsolete credential loader without unrelated changes.
No UI changes. Next: M1-03d2. Fresh open count: 61; M1 remains unverified.


### 2026-09-19 — Cycle 16, M1-03d2

Starting commit `23cdf92f`; previous cycle committed verified shared-runner
isolation. Fresh Railway metadata still reports API/MCP SUCCESS at `7dce086d`.
No model inference, upstream acquisition or deployment occurred.

The golden runner still hard-coded a DeepSeek key loader and allowed implicit
model defaults. Its INDRA requirement cannot be satisfied by campaign public
tools. Independent approach review rejected making it an always-campaign runner,
which would disable its distinct noncampaign purpose. Decision: retain explicit
noncampaign INDRA acceptance; reject campaign invocation before configuration,
run persistence or execution. No campaign opt-out was added.

A failing public-run regression proved execution began before campaign admission.
The corrected path rejects with an INDRA-specific explanation. Noncampaign
configuration now requires an explicit model and matching environment credential,
pins all model roles and never loads keys from disk. A second regression exposed
LiteLLM's import-time dotenv loading; dotenv is now disabled before importing
the engine policy, not merely before app Settings. Tests use synthetic keys and
stop before any execution or network request.

Provided the public-evidence acceptance procedure in campaign.md using existing
browser/API, persisted-run claim-support scoring and production smoke interfaces.
It includes interview, retrieval provenance, local recovery, event replay, report
publication and production observation. This is an execution procedure, not live
acceptance evidence; the corresponding M1 live items remain open.

Verification: five golden/shared-runner tests pass, Ruff lint/format and strict
golden-runner mypy pass. AST comparison confirms INDRA acceptance, real-completion
predicates and run-persistence logic are unchanged. Scoped cleanup removed the
obsolete DeepSeek loader and stale reproduction instructions; no UI changed.
Next: M1-03d3 direct-panel admission and observed usage artifacts. Open count: 60.

Final independent review approved the runtime behavior and identified two stale
procedure details. Corrected the scaling/ablation key requirements in the
evaluator README and named COSCIENTIST_DB_PATH explicitly for persisted-run
scoring. No remaining review blocker; diff check passes.


### 2026-09-19 — Cycle 17, M1-03d3a

Starting commit `bc8b73ff`; previous cycle completed golden admission/configuration
and the public-evidence procedure. Fresh Railway status remains API/MCP SUCCESS
at `7dce086d`. No live inference, spending, deployment or reference checkout.

Split M1-03d3 before implementation: panel admission now; observed usage, unknown
costs, deterministic fallback and missing provider identity remain M1-03d3b.
Three failing subprocess cases reproduced implicit-model acceptance. Reused the
shared environment configurator, returning its validated model and allowing an
explicit model argument for citation usefulness. Removed panel paid defaults.
Elo imports production rating math lazily so live configuration precedes engine
imports; the formula and comparison thresholds are unchanged.

Independent review found citation run's arbitrary-assessor injection bypassed
the configured factory. Repository caller search found no external consumers
of that argument. A failing public-run regression preceded replacing it with
`use_llm=True`, which constructs the admitted assessor internally. CLI and
programmatic live calls now use that same path. Offline behavior stays default.

Verification: 32 targeted tests pass (six panel rejection/import cases, existing
citation/usefulness/Elo cases and shared configuration/public LLM admission
tests). Strict mypy passes four changed modules; Ruff and diff checks pass.
The shared physical-boundary test uses mocked catalog/completion responses;
no test is claimed as a live scientific result. Positive panel response and
fallback/served-model artifact evidence remain part of M1-03d3b. Scoped cleanup
removed obsolete model imports/defaults and updated usage documentation. No UI
changes. Next: M1-03d3b. Open count: 60; turn limit unchanged at 180.


### 2026-09-19 — Cycle 18, M1-03d3b1

Starting commit `a3bc5fc7`; prior cycle committed panel admission. Split remaining
evidence work into shared telemetry fidelity and evaluator artifact integration
before implementation. No live inference or deployment. Railway status snapshot
retained locally at `/tmp/coscientist-cycle18-release.json`; production acceptance
remains open.

A failing public call_llm test reproduced missing requested/observed identity
evidence. Added additive observed_model_calls, reported_usage_calls and
priced_usage_calls plus requested_models counts. Positive counters deliberately
leave old checkpoints without observation evidence; calls minus each counter
identifies missing evidence. cost_usd remains a static estimate for compatibility,
not a billing receipt. A priced call requires observed model identity, explicit
valid prompt/completion counts and a static pricing entry. Failure attempts
retain requested identity without claiming observed usage or known cost.

Durable merge uses the existing count-map helper for request identities and
errors. Tests cover observed fallback, absent/blank identity, absent usage, a
known-zero estimate, provider failure, fan-out/checkpoint aggregation and legacy
records. Independent review found whitespace-only model identities created
bogus aggregate keys; a failing regression preceded normalizing that field.
No LLM output, prompt content, credentials or per-call database writes added.

Scoped cleanup reused the existing map merger and corrected the misleading
claim that unscoped telemetry was captured. Artifact consumers still need scopes
and explicit uncertainty/fallback handling in M1-03d3b2; they must not interpret
old numeric zero as proof of zero billed cost. No UI changes. Next: M1-03d3b2.

Final validation: all 88 targeted engine telemetry/runtime/model tests pass;
strict mypy passes both changed source modules; Ruff lint/format and diff checks
pass. Production API/MCP remain SUCCESS at `7dce086d`. Fresh open count: 60;
no milestone acceptance or live scientific result is claimed.


### 2026-09-19 — Cycle 19, M1-03d3b2a

Starting commit `1a425c99`; previous cycle committed observation telemetry.
Split artifact integration into durable summaries now and direct panel scopes/
fallback disclosure next. Preserved all original acceptance requirements.
No live inference, release, spending or reference acquisition in this cycle.

Failing artifact tests reproduced loss of raw usage, missing model identity and
unknown-cost evidence in golden/arm reports and derived scaling points. Added
a shared summary retaining raw snapshots, requested model counts, observed
model names and missing-evidence counts. Complete static estimates are null
for missing/legacy/incomplete telemetry; billed_total_usd remains null because
no receipt has been observed. Legacy numeric cost is explicitly labeled a
partial static estimate. Known-zero complete estimates remain zero.

Golden, arm metrics, scaling points, ablation paired records/summary means and
claim-support artifacts now retain the evidence. Persisted claim scoring labels
the configured backend without claiming that configuration proves a live call.
A missing cost value and impossible evidence counters each produced a failing
regression before being made incomplete rather than a complete zero estimate.
Reused existing store and evaluator interfaces; no schema migration or dependency.

Independent review found no dropped durable evidence or compatibility blocker.
Scoped cleanup consolidated partial-cost summation in the shared helper. Direct
panel response capture and deterministic fallback reporting remain unchecked in
M1-03d3b2b; no scientific result or billing observation is claimed. No UI changes.
Next: M1-03d3b2b.

Validation: 31 targeted evaluator checks pass, including offline durable scaling/
ablation flows and golden admission; persisted-run scoring retains the same
evidence. Strict mypy passes six changed modules; Ruff lint/format and diff
checks pass. Production API/MCP remain SUCCESS at `7dce086d`. Fresh open count:
60; the campaign and M1 acceptance remain incomplete.


### 2026-09-19 — Cycle 20, M1-03d3b2b1

Starting commit `e522e5f1`. The intervening goal-prompt reply made no campaign
progress; resumed from the current uncommitted panel changes. Split direct
capture from fallback instrumentation before further implementation, preserving
both requirements. This cycle completes capture only; no live inference,
spending, deployment or reference acquisition.

The initial failing usefulness public-path test exposed absent execution mode
and usage evidence. Shared scoped capture now wraps the citation assessor,
citation-usefulness judge and Elo comparator. Reused the durable usage summary;
no second accounting representation. Offline paths explicitly report offline;
requested live mode is not proof of an observed provider response. Elo labels
its deterministic controls separately. Scientific metrics and gates unchanged.

Successful public-path tests verify requested versus observed route identity,
unknown pricing, physical call count and outgoing zero-price caps. Citation
crosses the actual synchronous-to-async bridge; Elo crosses its per-match event
loop. Provider/catalog responses are mocked, not live scientific evidence.
Fallback behavior remains unverified and open in M1-03d3b2b2: instrument single
and batch claim deterministic substitution and invalid/tied ranking judgments,
retain events through durable merges, and preserve legacy tracking unknowns.
Do not interpret absent fallback records as proof that no fallback occurred.

Validation: 38 targeted panel/admission/artifact tests pass; strict mypy passes
four changed source modules; Ruff lint/format passes. Scoped cleanup reused the
existing summary and normalized imports. No UI changes. Production API/MCP
latest deployments remain SUCCESS at `7dce086dd483831b40a12532a84cf7321f058e52`
(snapshot `/tmp/coscientist-cycle20-release.json`); campaign deployment acceptance
remains open. Next: M1-03d3b2b2. Open count: 60; turn limit remains 180.


### 2026-09-19 — Cycle 21, M1-03d3b2b2

Starting commit `92eb82aa`; preceding turn made progress by committing direct
panel capture. Reproduced absent fallback evidence through the public single
and batch claim interfaces and ranking judge, then added additive in-memory
substitution counts. Events use the requested model and do not create physical
calls or database writes. Single/batch claim judgments and invalid ranking
turns/tied vote resolutions retain their original decisions.

The shared metric reducer preserves event maps across fan-out/checkpoint JSON;
the evaluator summary retains recorded counts through direct panels and stored
run scoring. No-evidence batch skips and valid judgments emit no substitution.
Chose `recorded_events_only` rather than a completeness counter derived from
physical calls: several calls can produce one judgment, one batch can produce
several judgments, and old records have no tracking. Empty maps therefore
remain inconclusive, not proof of pure-model execution.

Public failed-citation panel test verifies that three failed physical attempts
produce one recorded substitution. Stored-run tests retain the same evidence
through arm metrics and claim-support scoring. Ranking tests cover valid JSON
without a prose verdict, malformed winner, and a position-balanced vote tie.
Independent approach/final review found no remaining disclosure blocker.

A pre-existing reasoning test failed admission because its mocked free model
had no qualifying metadata. Primary-only metadata also failed: admission checks
every fallback route. Reused the engine suite's synthetic full-route catalog
pattern, preserving the original reasoning assertions and avoiding live metadata.
No live model inference or scientific-quality claim. Scoped cleanup normalized
imports and count-map documentation; no UI or dependency changes.

Validation: 30 app and 32 engine targeted checks pass; 11 evaluator checks pass.
Engine changed-module type checks and evaluator type checks pass. App checking
still reports 19 existing safety type-alias errors in human_input.py and
hypothesis_screening.py, outside changed modules; baseline repair remains open.
Ruff and diff checks pass. Production state snapshot retained at
`/tmp/coscientist-cycle21-release.json`; no deployment performed. M1 acceptance
remains open. Next: M1-03d4, matched comparison identities. Open count: 59.


### 2026-09-19 — Cycle 22, M1-03d4a

Starting commit `933e459e`; preceding cycle made progress by committing fallback
disclosure. Split M1-03d4 into persistent identity capture and comparison
validation before implementation; no acceptance requirement removed.

Failing persisted-run and scaling-artifact tests reproduced absent frozen input
identities. Added one canonical manifest at persist_arm_run, shared by scaling,
ablation and claim-support. It contains exact goal identity, resolved config,
declared backend, configured model roles, production-rendered routing and
ordered fallbacks, request/reasoning policy source identities, selected process
flags and hashed tool settings. Deep-copied before attaching to run.config to
avoid circular/mutable records. Existing artifact provenance remains the source
for revision and prompt identities; observed models remain usage evidence.

Disabled response caching at comparison setup and scoped arm execution rather
than switching per-arm directories against a memoized singleton. Capture
rejects enabled caches. Tests verify stable repeated inputs, changed goals,
changed primary model and changed fallback list, rejection of enabled cache,
and persistence through real offline durable runs and artifact shaping.
Legacy scoring preserves missing identity as null. This does not prove matched
retrieval or comparable scientific results.

Independent approach/final review found no capture blocker. Scoped cleanup
corrected cache documentation and preserved score_run's missing-run behavior.
All targeted identity, scaling, ablation, environment, usage and claim-support
suites pass; strict mypy passes six changed source modules, Ruff/diff checks pass.
No live inference, external checkout, release or UI change. Production API/MCP
remain SUCCESS at `7dce086dd483831b40a12532a84cf7321f058e52` (snapshot
`/tmp/coscientist-cycle22-release.json`).

Next M1-03d4b must check manifest integrity, runtime drift and matched groups;
allow only declared tier/ablation differences; cover direct-panel dataset
identity and matched retrieval requirements. Missing or mismatched evidence
must prevent accepted comparisons. Open count: 59; turn limit unchanged.


### 2026-09-19 — Cycle 23, M1-03d4b (partial)

Starting commit `3fe71d5f`; prior cycle progressed through committed arm
identity capture. M1-03d4b remains unchecked: this cycle adds execution-boundary
drift checks, not cross-arm or direct-panel comparison acceptance.

Failing public-driver tests showed that missing/corrupt identities and changed
model settings still reached the worker. Added manifest version/digest validation
before scheduling and after completion. Reconstruction uses actual persisted
config, goal and backend, not the manifest's own frozen config. An independent
review caught that self-comparison risk before implementation. Repository search
confirmed durable execution does not write runtime config annotations: only the
identity field is excluded, so added/changed execution options cannot hide.
The original identity is held through execution, rejecting even a resealed
replacement. Boundary checks cannot detect a transient mutation restored before
the final check; observed usage remains separate evidence.

Tests exercise missing/corrupt identity and model/config drift before execution;
model/config/resealed-identity drift after the worker; and unchanged real offline
scaling/ablation workflows. No scientific decisions or thresholds changed.
Independent final review found no blocker. Scoped cleanup normalized imports and
formatting; no UI changes. Type checking of both changed source modules, Ruff
and diff checks pass. No inference, release or external checkout.

Production state snapshot: `/tmp/coscientist-cycle23-release.json`. Next remains
M1-03d4b: enforce cross-arm matching with declared tier/ablation differences,
cover direct-panel dataset identity and matched retrieval requirements, and
reject missing/mismatched comparison evidence. Open count: 59.


### 2026-09-19 — Cycle 24, M1-03d4b (partial)

Starting commit `448685c2`; prior cycle progressed by committing execution-boundary
drift checks. This cycle adds cross-arm validation; M1-03d4b stays unchecked
until direct-panel identities and matched retrieval requirements are handled.

Failing artifact-CLI tests reproduced acceptance of missing identities, different
goals and changed model roles. Added shared comparison validation used by scaling/
ablation drivers and the artifact CLI before results. Descriptors now retain
exact goal, tier and declared overrides. Shared model/routing/cache/policy
controls must match. Config differences must be the declared intervention;
scaling permits only the recorded tier profile. Froze baseline profiles and tier
field sets in the manifest instead of re-resolving old runs through today's
defaults, following independent review. Historical-profile tests verify this.

Review found duplicate arms could overweight aggregates and a baseline could
be relabeled as an intervention without applying its override. Both reproduced
in failing CLI tests before fixes. Validation now rejects duplicate goal/arm
entries, one goal under several labels, incomplete arm sets and unapplied or
unchanged declarations. Existing default ablations remain valid. No metric,
threshold or scientific gate was relaxed. The validation status explicitly says
matched declared inputs; retrieval remains not_verified. Repeated paired trials
use separate invocations, not invented independent-goal labels.

Validation includes group rejection/acceptance and historical-profile tests,
identity/drift regression suites and real offline scaling/ablation workflows.
Strict mypy passes six changed modules; Ruff and diff checks pass. Final review
found no further blocker. Scoped cleanup kept low-level metrics descriptive and
reused the canonical digest/manifest validator. No UI changes, model inference,
spending, checkout acquisition or deployment. Production latest API/MCP remain
SUCCESS at `7dce086dd483831b40a12532a84cf7321f058e52`, snapshot
`/tmp/coscientist-cycle24-release.json`.

Next: finish M1-03d4b direct-panel dataset/model identity and comparison checks,
and define/enforce matching retrieval evidence where required. Open count: 59.

### 2026-09-19 — Cycle 25, M1-03d4b (partial)

Starting commit `28c053f8`. Previous goal work made progress in cross-arm
validation; the intervening user-facing goal-prompt answer did not change
execution state. Resumed the existing panel capture changes and confirmed the
previous test process completed successfully rather than restarting it.

Direct citation, usefulness and Elo reports now freeze ordered datasets,
requested models, evaluation mode, cache policy, wrapper/request-policy hashes
and routing before evaluation, with a post-evaluation drift check. Cache use
is disabled in the panel scope. The new panel comparison CLI rejects missing,
incomplete, wrong-kind and mismatched identities or inconsistent modes.
Failing CLI tests preceded implementation, including a resealed incomplete
manifest regression. Successful validation claims matched declared inputs only;
scientific acceptance still requires metrics and physical usage/fallback review.

Independent review proposed hashing production assessor/ranking code as an
identical control. Rejected that option because this code can be the scientific
candidate itself; source commits are retained with trial records, while evaluator
rubrics and request policy remain matched controls. This is a local design
choice, not a claim about Google's implementation.

Panel admission/usage/comparison tests: 17 passed, with synthetic physical
provider responses only. Strict mypy passes five modules; Ruff and diff checks
pass. Scoped cleanup reuses the existing canonical manifest validator and usage
capture, and introduces no dependencies or UI changes. No campaign inference,
spending, reference checkout or deployment. Railway snapshot
`/tmp/coscientist-cycle25-release.json` reports latest API/MCP SUCCESS at
`7dce086dd483831b40a12532a84cf7321f058e52`.

M1-03d4b remains open: define/enforce matched retrieval requirements for whole-run
comparisons and finish any remaining comparison acceptance gaps. Open count: 59.

Final review found no further correctness blocker. The existing citation,
usefulness and Elo regressions plus the comparison CLI tests pass (29 tests).

### 2026-09-19 — Cycle 26, M1-03d4b complete

Starting commit `f757000b`; previous cycle made progress by committing direct
panel identity capture and comparison validation. Inspected current comparison
consumers and durable retrieval storage. Retrieval ledgers preserve queries,
ranked hits and admission decisions; stored evidence alone does not prove the
exact subset/order passed to a model. No new replay mechanism is implied.

Closed the remaining specification requirement with explicit matched retrieval
acceptance rules in `references/external/campaign.md`. Fixed-evidence changes
use equal frozen panel inputs and three paired trials. Retrieval interventions
freeze public questions, versioned source content and labels while treating
returned evidence as an output. Whole-run comparisons remain descriptive when
retrieval is not verified; isolated-effect claims require exact model-consumed
evidence mappings. Missing/mismatched evidence requires matched reruns of both
versions, not a rejection of a promising candidate. Claim-support single-run
metrics are explicitly descriptive unless wrapped in the same paired procedure.

Independent read-only review confirmed this closes the remaining specification
gap and identified the claim-support clarification, now recorded. Alternative
of implementing a generic whole-run retrieval replay now was rejected as
unspecified infrastructure: add concrete work only when an accepted candidate
needs that boundary. This does not weaken the campaign's scientific acceptance
requirements or claim a live result.

Validation reuses the unchanged comparison CLI, direct-panel and runtime drift
checks recorded in cycles 23–25; this cycle changes documentation only. Scoped
cleanup kept the rule in the campaign acceptance procedure. M1-03d4b is checked;
the M1 milestone itself remains unverified. No inference, charges, deployments
or reference checkout acquisition. Next: qualify current free OpenRouter models
through actual application interfaces. Open count: 58.
Release observation: `/tmp/coscientist-cycle26-release.json` confirms latest
API/MCP SUCCESS at `7dce086dd483831b40a12532a84cf7321f058e52`.

### 2026-09-19 — Cycle 27, M1-04a complete; M1-04a1 discovered

Starting commit `2a898f82`; previous cycle progressed by closing comparison
requirements. Split model qualification into catalog shortlist, live capability
qualification, and scientific comparison/selection so state survives turns;
the 180-turn authorization is unchanged.

Fresh public catalog admission finds 22 eligible explicit text routes, retained
under `references/external/baseline/model-qualification/catalog.json`. The deployed
minimax primary is absent. Prioritized Nex Pro/Mini, DeepSeek Flash 0731 and Dots
preview based on advertised structured-output/tool/context capabilities; other
eligible candidates remain available. Metadata does not establish quality.
M1-04a is checked; selection and full qualification remain open.

Ran one actual public entailment request via `call_llm_json` in a credential-
isolated subprocess, with fresh free admission, zero-price ceilings, caches off
and one attempt. Nex Pro returned provider 400: native response-format schema
missing `name`. No completion, served-model identity or usage was reported.
The sanitized artifact retains that failure without claiming successful inference
or verified billing totals. The shared admission guard enforces price ceilings
for newly catalogued models even before static pricing registration.

Independent review confirmed the shared native-schema branch forwards bare
schemas unchanged, while callers use both bare and named-envelope forms.
`claim_verifier` supplies a bare `obj(...)` schema; citation-usefulness already
supplies a named envelope. Added M1-04a1 before further capability work: normalize
bare schemas at the native request boundary, preserve existing named envelopes
and the json_object shim, test at the physical request seam, then retry live.
Do not reject Nex for this application compatibility error.

The experiment script, public inputs, caps and failure telemetry are retained.
No paid fallback or tool was used, no production settings changed, and no external
reference acquired. Diff checks pass; no production code changed, so reuse prior
code verification. Scoped cleanup retains only the reusable probe and sanitized
public evidence. Railway snapshot `/tmp/coscientist-cycle27-release.json` confirms
API/MCP latest SUCCESS at `7dce086dd483831b40a12532a84cf7321f058e52`.
Next: M1-04a1 regression and native-schema correction. Open count: 60.

### 2026-09-19 — Cycle 28, M1-04a1 complete

Starting commit `ae23733f`; previous cycle made progress via current catalog
assessment and a live provider failure. Reproduced the bare native-schema
envelope defect at the public `call_llm_json` physical request seam. The shared
builder now wraps bare schemas with a stable provider name and preserves named
envelopes. Review identified unnamed envelopes; a second failing wire test
preceded filling their absent name. This follows existing local schema-unwrapping
semantics rather than sending different schemas to provider and local validator.

Native/local validation, named-envelope and json_object-shim regressions pass
with wrapper tests (31 tests). Ruff, strict mypy and diff checks pass. Scoped
cleanup changes only the native response-format branch and reuses the existing
public-boundary fixtures. No assertion or scientific threshold was weakened.

Live retry through fresh zero-cost admission returned valid JSON from the
requested Nex Pro model in one physical call, with usage retained. Overall
probe flag remains false because the exact quote removed a source line break;
the artifact is not rewritten as a passing scientific trial. The provider 400
is resolved. Reasoning remained present despite requested disabled mode, which
is expected for a model not yet declared in gateway reasoning settings and
remains part of M1-04b. No selected model/fallback or production setting changed.

Evidence and the official envelope source are recorded in the model-qualification
README. Railway snapshot `/tmp/coscientist-cycle28-release.json` retains current
release observation; no deployment or reference acquisition. Next: M1-04b full
capability trials including reasoning, tools, streaming and long inputs.
Open count: 59.

### 2026-09-19 — Cycle 29, M1-04b partial

Starting commit `2ca151e8`; previous cycle progressed by correcting and verifying
native schema envelopes. Tested Nex Pro through actual engine structured output,
tool-loop and app streaming interfaces using isolated campaign credentials,
disabled caches and guarded zero-price requests. Public synthetic fixtures and
sanitized observations are retained under model-qualification. No production
code changed; no candidate is selected or declared scientifically improved.

Short JSON passes with caller thinking flags off/on; both actually reasoned.
A 126,555-character prompt passes label and verbatim quote checks, with evidence
at its end. App streaming yields ten content deltas and stop plus SDK model and
usage. These are compatibility checks, not full-context or browser verification.

Initial tool test returned a malformed tool-result message from our experiment
executor, caught by free-request admission before a second transport. Corrected
the probe to return the existing tool-role protocol and retained the failure.
The corrected live trial executes exactly one expected local lookup and reports
its result across two observed Nex requests. No engine policy was relaxed.

Independent approach review informed single-invocation checks, explicit stream
metadata and bounded trials. No production test suite rerun is needed for this
experiment-only change; diff checks pass, artifacts are sanitized, and temporary
logs stay outside the repository. Current probe/fixtures remain reproducible;
new artifacts record the script hash. Initial trial used the earlier executor
and intentionally remains documented as superseded for tool capability.

M1-04b remains open: qualify other shortlisted models and effective reasoning/
budget behavior, then M1-04c scientific panels and selection. Railway state is
retained in `/tmp/coscientist-cycle29-release.json`; no deployment performed.
Open count: 59.

### 2026-09-19 — Cycle 30, M1-04b partial

Starting commit `ef2a7a41`; previous cycle made progress through Nex Pro live
capability evidence. Ran the unchanged committed probe sequentially for Nex Mini,
DeepSeek Flash 0731 and Dots Preview, each in a fresh isolated process with
explicit model and fresh campaign eligibility. Retained all checkpointed reports;
no rate limit, paid fallback, configuration change or deployment occurred.

Mini and Dots passed all five basic cases. DeepSeek passed both short JSON modes,
local tool execution and app streaming, but its disabled-reasoning long trial
returned the wrong label plus a fabricated quote. It remains inconclusive for
selection; one failed task is not a scientific-quality rejection. Independent
review clarified actual mode semantics: Nex flags currently send no distinct
reasoning control, DeepSeek uses its existing JSON-object/enable-disable path,
and Dots maps disabled requests to bounded mandatory reasoning. Observed model
and usage evidence is retained with its stream-specific limits.

No production code or probe changed; prior code checks remain applicable. Diff
checks pass and scoped cleanup retains only reports and findings. Railway latest
API/MCP remain SUCCESS at `7dce086dd483831b40a12532a84cf7321f058e52`, snapshot
`/tmp/coscientist-cycle30-release.json`. No temporary reference acquired.

Next within M1-04b: qualify explicit Nex reasoning/budget profiles through the
shared request seam and realistic complex-schema calls; follow up DeepSeek's
long-output failure without weakening the check. Scientific model comparison
and production selection remain M1-04c. Open count: 59.

### 2026-09-19 — Cycle 31, M1-04b partial

Starting commit `aadef4a4`; previous cycle progressed via three additional live
model trials. Nex variants spend reasoning tokens while undeclared, so the
existing token floor/control selection missed them. Four failing public LLM
request regressions preceded explicit model profiles using the shared bounded
minimal-reasoning behavior and token floor. No default, fallback chain or BYOK
behavior changed. Profiles do not assert unverified disable support.

Review identified the associated native-schema to JSON-object path change;
regressions now assert that request format and retain local validation. Reran
all five live probes for both explicit profiles: all pass. Actual non-secret
physical kwargs are retained for every call, including both tool rounds and
streaming: zero price caps, exact requested model, no fallback, 18k allowance.
The live recorder forwards real transport unchanged and contains no credentials.

The broader pricing invariant caught missing static estimate entries; added
catalog-verified zero rates for the new declarations, preserving fresh catalog
admission as the authority. Existing live artifacts retain their earlier unknown
static estimates. Final targeted routing, free-admission and mandatory-reasoning
suite: 93 passed; Ruff, strict mypy and diff checks pass. Scoped cleanup reused
GatewayModel and the existing budget machinery, with no new runtime abstraction.

No production configuration changed or deployment performed. Railway observation
is `/tmp/coscientist-cycle31-release.json`. No external checkout acquired.
M1-04b stays open for representative complex scientific schemas and follow-up of
DeepSeek's long-input failure. M1-04c remains scientific comparison and selection.
Open count: 59.
Final evidence review required a resolvable source identity: profile artifacts
now identify base commit `aadef4a4` in full plus the retained routing-only patch
and SHA256. That recreates the exact code used before static pricing was added;
the probe script's own hash is retained separately.

### 2026-09-19 — Cycle 32, M1-04b partial; M1-04b1 discovered

Starting commit `e0bc71af`; prior cycle progressed through tested Nex profiles.
Used the existing 30-case citation challenge to exercise realistic nested
scientific schemas, after independent review distinguished it from the easy
regression panel. Declared unchanged recall/accuracy gates and three-trial
selection procedure before results, with model/routing as the explicit selection
intervention and all other controls held fixed. The paced first live Mini trial
failed: accuracy .433, contradiction recall 0, 32 observed requests, no recorded
deterministic fallback. Offline deterministic results .033/0 are separately
labeled and retained. No failed result is converted to acceptance.

Independent code/data review and a retained per-item prompt-hash diagnostic show
all ten challenge contradiction passages lack the guard's required lexical
marker. Correct directional/numeric contradiction drafts therefore cannot pass;
some raw model verdicts are also insufficient. Added M1-04b1 before more model
selection: preserve subject, quote and historical false-positive safeguards,
but resolve genuine semantic opposition through behavioral tests and matched
live evidence. Thresholds and dataset remain unchanged; do not fit a word list
merely to pass. Defer repeated selection trials while this structural barrier
remains, rather than rejecting promising models for a shared product limitation.

Three DeepSeek long-input mode pairs completed. Enabled reasoning passes all
three; disabled reasoning has two observation timeouts and a wrong label/fake
quote. Attempted physical controls are retained alongside telemetry, which omits
cancelled responses and must not be interpreted as no request. No rate-limit
exception observed and no paid substitution used. Processes were polled by their
live handles until confirmed finished. No background trial is left running.

No production code changed. Public input artifacts, script hashes, exact source
commits and sanitized observations are retained; diff checks pass. Existing
production checks are reusable for this experiment-only change. No deployment,
production configuration change or reference checkout. Railway observation:
`/tmp/coscientist-cycle32-release.json`. Next: M1-04b1. Open count: 60.
Final review completed diagnostic provenance: every contradiction row now retains
its exact prompt SHA256 and zero-based physical-request index in the source trial;
all new trial source commits are resolved to full Git identifiers.

### 2026-09-19 — Cycle 33, M1-04b1a; scientific acceptance remains open

Starting commit `14e8c599`. Cycle 32 produced live failure evidence; the intervening
goal-prompt response made no repository progress. Revalidated the clean branch
and Railway state before resuming the first unchecked investigation. Split
M1-04b1 into tested implementation, paired scientific acceptance, and per-edge
verification provenance. The split preserves all acceptance work and the
180-turn limit.

Reproduced genuine directional opposition becoming insufficient through the
single public assessor, then numeric/directional opposition through the batch
public assessor. Both failed before their respective integration. Added shared
`claim_verifier_opposition`: canonical source-span resolution and the existing
coverage floor precede a separate semantic request only for markerless drafts.
The ordinary lexical-founded path and deterministic assessor remain conservative.
Batch candidates share one request; single-claim panels may add one per claim.
The request uses the existing credential, free-admission, reasoning, budget and
telemetry machinery. Unavailable verification never becomes deterministic
fallback; errors and physical calls are retained in a verification subphase.

Decision: use a separately prompted, same-model semantic check as an experimental
candidate. It is correlated evidence, not independent scientific proof. Adding
benchmark-specific markers, trusting a same-response certificate, and lowering
gates were rejected. Extra verified-free calls spend time and call budget, not
money. No live inference occurred this cycle and no scientific improvement is
claimed. M1-04b1b requires three paired trials plus historical negative controls;
M1-04b1c retains the review finding that per-edge method provenance must be
persisted before adoption.

Read-only review found that a valid answer plus an unknown index could still
confirm a contradiction. Reproduced that leak, then required an exact, typed,
complete index envelope. Malformed envelopes leave the verification wave
insufficient. Final independent review found no remaining blocker to committing
the experimental candidate. Scoped cleanup removed the superseded lexical-only
LLM guard, reused existing span and telemetry helpers, and checked changed files
with Ruff; no UI changed or temporary repository artifacts remain.

Verification: 111 app claim tests pass (`app/tests/test_claim*.py`), including
historical quote/subject safeguards, single and batched opposition, invalid
indices, malformed extras, verifier failures, and budget/rate-limit propagation.
Ruff lint/format and diff checks pass. Changed modules have no mypy errors;
the invocation still fails on the previously recorded 19 safety-type errors in
`human_input.py` and `hypothesis_screening.py`, pending baseline repair. No checks
were weakened or skipped to pass. No merge/deployment/reference acquisition.
Railway API `a6ddd7f0-3bb5-4ad1-bed8-14809846e88e` and MCP
`0d49864d-782b-421f-ab8b-02b608a9c5d4` remain SUCCESS (observation
`/tmp/coscientist-cycle33-release.json`). Next: M1-04b1b matched live panels.

### 2026-09-19 — Cycle 34, M1-04b1b partial; three failed Mini pairs retained

Starting commit `06a17a70`; cycle 33 was progress (tested semantic candidate).
Ran three matched live baseline/candidate challenge pairs using archive-only
snapshots of `14e8c59950204c96cdfa2195594885383d1d5720` and
`06a17a70e9aaf7d3f51bbc8c5c8157825c82c368`. Fixed Nex Mini route, explicit
credential isolation, fresh catalog eligibility, disabled caches and identical
inputs. Actual imported module hashes prove snapshot execution. All six panel
and control identities, observer hashes and dependency versions match; explicit
allowed assessor changes are listed separately from unchanged request/evaluator
code. The observer retains per-assessment labels and physical-request indices.

Baseline accuracy: .367/.433/.400, recall 0/0/0. Candidate accuracy:
.667/.567/.667, recall .8/.6/.6. The candidate improves each paired result but
fails the .75 accuracy gate every time and the .80 recall gate twice. No
acceptance, model selection or production-quality claim. All 30 full-live
historical negative assessments remain non-contradictory, without pretending
they exercised the new branch. Three separately labeled controlled-primary
cases did exercise actual candidate verifier calls; all explicitly rejected a
confirmatory GBM quote as opposition. Simulated primary completions are excluded
from physical request lists and live panel telemetry.

All 248 actual physical requests observed Nex Mini, with zero provider-price
ceilings and no recorded deterministic fallback in either challenge or control
panels. Intra- and inter-process four-second spacing was checked. No rate-limit
park occurred. Session 99372 completed with exit 0; no trial remains running.
Retained artifacts and comparison checker live under
`references/external/baseline/model-qualification/`; comparison reports complete
three-pair evidence and accepted=false. Imported-source records and full commit
identifiers were tightened after independent review. Scripts compile, artifact
identity/cap/pacing assertions and diff checks pass. Product code is unchanged,
so cycle 33's targeted behavioral checks remain applicable; full release checks
are still pending their items.

Decision: keep M1-04b1b open. Next compare the already capability-tested Nex Pro
route on the same frozen code, rerunning both arms for three pairs. Its scientific
performance is unverified. Lowering gates, relabeling dataset cases, deploying
the partial result, or changing prompts before separating model effects were
rejected. Mini results also show insufficient-evidence cases labeled partial;
the first candidate misses include strict condition matching and the retained
subject-coverage floor. Preserve those diagnostics while investigating; do not
fit a marker list to the benchmark. M1-04b1c still requires per-edge method
provenance before adoption. No merge, deployment or external checkout.
Railway read-only observation: `/tmp/coscientist-cycle34-release.json`.

Final independent review found no remaining evidence blocker. The retained
checker also asserts same-arm imported-source hashes across all three trials.
Credential-value scans of new artifacts pass. Scoped cleanup removed the
completed temporary source snapshots, launch/analysis scratch scripts and raw
provider logs; sanitized evidence and reproducible checker remain. Open count: 61.

### 2026-09-19 — Cycle 35, M1-04b1b in progress

Starting commit `f9a00439`. The preceding user-question turn clarified status
but changed no execution state (no progress); resume the recorded next action.
Status notation now means completed/total plus remaining, never completed/open
presented as a fraction. M1 remains 27/36 completed, nine open; the campaign has
61 open checkboxes. Splitting tasks is not an overall completion percentage.

Prepared three Nex Pro pairs using the same baseline `14e8c599` and candidate
`06a17a70` archive snapshots, unchanged retained probe and historical controls.
Both arms use `openrouter/nex-agi/nex-n2.5-pro:free`; all other settings and
acceptance gates remain fixed. Runtime Python and every installed package match
`opposition-runtime.json`. Explicit child environments isolate credentials,
disable caches/dotenv, and require fresh free eligibility and zero price caps.
Launcher `/tmp/coscientist-pro35.py` refuses artifact overwrites and stops on
recorded errors; artifact prefix is `opposition-pro-`. No result is accepted
merely because a process exits successfully.

Read-only Railway status succeeded: latest deployment IDs
`a6ddd7f0-3bb5-4ad1-bed8-14809846e88e` and
`0d49864d-782b-421f-ab8b-02b608a9c5d4` report SUCCESS. No release performed.
Preserved the concurrent uncommitted AGENTS.md change.

Reproduced pending size-gate failures (pytest exit 1) under the existing baseline
verification item: function code-line counts arm_identity 63,
MCPToolClient.initialize 47, elo_concordance_eval.run 43, summarize_usage 43,
citation_eval.run 41 against 40; test_llm_free_eligibility.py 524 against 500.
These require behavior-preserving repairs before release, not threshold changes.
Log: `/tmp/coscientist-cycle35-size.log`. No new acceptance scope or checkboxes.

Independent pre-launch review required binding snapshot contents to commits,
not merely labeling them. The launcher now verifies every archived Git blob
against the full pinned revision before inference, and verifies each recorded
imported module SHA256 against `git show` after each child. Both snapshots passed
preflight. Pro-specific artifact checker prepared at
`/tmp/coscientist-compare-pro35.py`; it reads only `opposition-pro-*` and writes
`opposition-pro-paired-summary.json`, preserving Mini evidence.

Batch launched in unified exec session **50677**, confirmed running baseline
trial 1. Resume by polling that same handle; never restart on an observation
timeout. Launcher and snapshots must remain until the batch terminates. No trial
results yet at this checkpoint; M1-04b1b remains open. After completion, validate
all six artifacts with the Pro checker, verify unchanged runtime, retain sanitized
evidence and remove scratch files. If a rate limit parks execution, record the
actual reset and resume outstanding trials only. No production changes.

### 2026-09-19 — Cycle 36, M1-04b1b running; baseline size repairs

Starting commit `ee80ddba`. Previous cycle was progress: pinned the Pro batch,
started a real process and retained its resume handle. Polled session 50677;
baseline trial 1 completed and candidate trial 1 started without restarting.
Baseline artifact records 33 physical Pro requests with zero price caps, accuracy
.467 and contradiction recall 0; historical controls pass. This is one arm,
not a completed pair or model qualification. Remaining batch still runs in
session 50677, using frozen source snapshots untouched by this cycle's edits.

While waiting, repaired four reproduced evaluation function-size failures under
the existing baseline-suite item. Extracted baseline/model-policy assembly,
missing-usage counts and assessor selection; used an ordered comprehension for
Elo's three offline controls. No threshold, dataset, provider or scientific
behavior changed. Independent approach review preceded edits. The same 60
targeted tests passed before and after: comparison identity/drift/groups,
panel comparison/admission/usage, usage evidence, citation and Elo evaluation.
Ruff and diff checks pass. Explicit repository size tests still exit 1, now only
for MCPToolClient.initialize (47 code lines) and test_llm_free_eligibility.py
(524 lines); these remain pending within baseline verification.

Final review found comparator-factory timing had moved before the first two
controls. Restored its original creation/evaluation order; no lazy-factory
abstraction added. Mypy found an Any-return boundary from the ignored app import;
a typed baseline local resolves it without a cast or behavior change. All four
changed modules now pass mypy and Ruff, and 29 affected identity/drift/Elo/panel
usage tests pass after those final edits. The function-size gate confirms only
the previously recorded engine method remains oversized. Independent final
review reports no remaining findings. Scoped cleanup/deslop found no further
code changes; deleted the completed edit scratch script. No UI changed.
Live session 50677 remains active on candidate trial 1; preserve its scratch
launcher, comparator and snapshots. No acceptance checkbox changed, no release.

### 2026-09-19 — Cycle 37, first Pro pair verified; size gates repaired

Starting commit `b9e9114d`. Previous cycle was progress: four evaluator repairs
committed while the existing live process continued. Resumed session 50677,
never relaunched it. First Pro pair is complete: baseline accuracy .467 / recall
0 (33 physical requests), candidate .767 / .8 (43 requests). Artifact checker
passes all seven pair criteria, including unchanged production thresholds,
historical controls, actual negative verifier output, no new false
contradictions and no recorded deterministic fallback. Summary remains
complete=false, accepted=false: two further pairs are mandatory. No model
selection, semantic adoption, workflow qualification or deployment is implied.

Finished the remaining size repairs under the existing baseline-suite item.
MCP initialization now delegates its unchanged guarded body to a private method;
the same lock and both readiness checks remain in the public method. Moved
catalog helpers and the module-local autouse reset fixture to a test helper,
preserving all test IDs and assertions and the override of the broader conftest
fixture. Independent approach and final reviews found no semantic blockers.
128 targeted engine tests pass before and after; both repository size test files
now pass (four tests). Ruff and diff checks pass. Mypy exposed an existing
heterogeneous request-dict inference in the moved-helper suite; added its explicit
dict[str, Any] annotation without changing runtime behavior or assertions.

Final mypy passes all three changed engine files, and all 62 eligibility cases
pass after the annotation correction. Retained first-pair JSON and partial
summary pass an exact credential-value scan. Scoped cleanup/deslop added no
changes; live launcher/snapshots/comparison script remain necessary. No UI
changed. Batch session 50677 is confirmed active on baseline trial 2. Next poll
that handle, complete all pairs and rerun the Pro checker before making any
acceptance decision. Fresh open count remains 61 (M1 27/36 complete).

### 2026-09-19 — Cycle 38, baseline type repairs during Pro trials

Starting commit `d91cfa8c`. Previous cycle was progress (first passing Pro pair
retained, all size checks repaired). Session 50677 remains live on baseline
trial 2; no restart or new inference process. No production changes.

Ran required `make typecheck` directly: exit 2, 27 app errors. Corrected the
canonical safety compatibility exports with explicit TypeAlias annotations,
imported RateLimitError from litellm.exceptions, and replaced two partial
SimpleNamespace stream inputs with real isolated store-created RunRow fixtures.
No runtime policy, stream contract, gate threshold or assertion changed.
Independent approach review preceded edits. App mypy now passes all 489 files;
57 targeted safety/human-input/claim/free-model/offline tests pass. Ruff and
format checks pass on changed files.

Baseline failures discovered before edits remain explicit: the broader safety
selection gave 63 passes and three failures in test_hypothesis_safety_escalation
(model allow, model raise, admission model raise). Each logs `zero-cost model
is not an explicit catalog route`, so its expected fake model response is never
reached. Repair the fixtures at the real boundary without bypassing admission
or weakening assertions; these three were not included in the subsequent
57-test passing selection and are NOT claimed fixed.

The repeated full `make typecheck` proceeds beyond app but still exits 2 on nine
engine test errors: test_workspace_campaign (union result inference and three
missing annotations), test_mcp_campaign_admission (heterogeneous changes map and
transport TypedDict narrowing), test_campaign_node_cache (expanded string dict
inferred as potentially supplying bool force). These remain under the existing
baseline-suite item. No new checkboxes or acceptance scope. Logs:
`/tmp/coscientist-cycle38-typecheck.log`,
`/tmp/coscientist-cycle38-after-typecheck.log`,
`/tmp/coscientist-cycle38-before.log`,
`/tmp/coscientist-cycle38-after-tests.log`.

Independent final review reports no findings: canonical class identity,
stream/offline guards and transport mocking are preserved; created run fixtures
write only isolated test databases. Scoped cleanup/deslop found no further
changes or disposable source files. Preserve all active Pro batch scratch and
snapshots. Next poll 50677, then repair the recorded engine type errors and
safety test setup while waiting as needed. No item checked complete.

### 2026-09-19 — Cycle 39, complete typecheck gate; Pro pair two running

Starting commit `ca490f11`. Previous cycle was progress: app type fixes committed.
Polled existing batch session 50677. Pro baseline trial 2 finished with accuracy
.433, contradiction recall 0 and 33 physical requests; candidate trial 2 started.
No restart, selection or acceptance decision. First pair remains the only
completed passing pair; the required total is three.

Repaired nine engine test typing errors with precise result unions, fixture
parameter/map annotations, explicit default force=False on baseline cache calls,
and a transport discriminator assertion before its HTTP-only factory field.
No implementation, existing assertion or confinement behavior changed.
31 tests pass before and after on the host. The first sandboxed invocation had
three failures because the outer sandbox prohibits sandbox-exec sandbox_apply;
authorized host execution exercised the real macOS confinement successfully.
No skip or mocked replacement of confinement was introduced.

The complete typecheck then exposed four evaluation-test annotation errors;
added generic parameters and a typed identity local at the ignored app-import
boundary. `make typecheck` now exits 0 across app (489 files), engine (559) and
evaluations (60). 13 targeted evaluation/size checks pass. Ruff and diff checks
pass. No type ignores, casts, relaxed thresholds or disabled tests added.
Remaining baseline safety-escalation fixture failures from cycle 38 are still
open, as are live qualification/full workflow/release criteria.

Independent final review found no semantic regressions across the five test
files. Scoped cleanup/deslop found no additional changes or obsolete scratch
from this repair. Preserve active trial files and the unrelated AGENTS.md edit.
Next poll 50677 (candidate trial 2), repair the recorded safety-test setup, and
continue baseline verification. Fresh open-item count remains 61.

### 2026-09-19 — Cycle 40, safety fixture repair; full suite running

Starting commit `56f2aae7`. Previous cycle was progress (complete typecheck gate).
Resumed session 50677, still running candidate trial 2. Never restarted a trial.
Reproduced safety escalation failures again: three failed/six passed. These
fixtures faked completion but relied on a real default free model's catalog
eligibility, so allow/raise outcomes never reached the fake. Added a module-local
synthetic explicit free route with a mocked zero-priced text catalog, resetting
the snapshot while preserving actual request admission. No production policy or
outcome assertions changed. All nine tests pass after the fixture correction.
The provider-error test now records physical fake requests and asserts model/
zero caps outside the fail-closed catch, proving the fake was reached and
preventing swallowed assertion errors from masquerading as provider failures.
Positive fake responses also assert model/caps before returning their verdicts.

Independent approach and final reviews found no remaining issues. Targeted
mypy and Ruff pass. Required `make lint` exited 0 across Python and frontend;
it introduced no unrelated tracked changes. Started required `make test-all`
in host-capable unified exec session **18752**, output at
`/tmp/coscientist-cycle40-test-all.log`. It is still running the engine suite;
resume that handle before running any other app/engine pytest process. The final
provider-error assertion relocation and settings import were made during that
run, so rerun the nine targeted tests after it terminates regardless of whether
its collection saw the final file. No full-suite pass is claimed yet.

Engine phase completed: 3124 passed, two existing skips in 116.22s. Session
18752 has advanced to the app phase and remains live. Keep the full baseline
item open until every required phase/gate holds. Scoped cleanup/deslop retained
only the fixture fix; no UI changed. Preserve both running processes and their
scratch. Next poll 18752 and 50677; targeted final fixture rerun remains due.

### 2026-09-19 — Cycle 41, offline baseline gates complete; Pro pair 2 fails

Starting commit `403134a4`. The intervening user clarification turn changed no
execution state; this cycle resumed the same live handles, without restarting.
Session 18752 completed `make test-all` with exit 0. Build, offline smoke,
frontend tests (718), and browser E2E (9) all exited 0. Final safety fixture
regression rerun passed nine tests. Lint/typecheck successes from cycles 39–40
remain applicable; see `references/external/baseline/verification-cycle41.md`.
Independent review confirmed this proves the offline baseline suite/browser
item, not live or production acceptance. Checked only that item. Corrected a
stale safety-test docstring claiming contextual review could never clear a hold;
existing behavioral tests already prove it can. No runtime behavior changed.

Session 50677 completed Pro candidate trial 2: accuracy .70, contradiction
recall .80, 44 physical requests; baseline trial 2 accuracy .433, recall 0,
33 requests. The candidate misses the unchanged .75 accuracy gate. Retained
both artifacts and refreshed the two-pair summary (complete=false,
accepted=false). Known credential-value scan passes and installed runtime
matches the pinned runtime manifest. Batch advanced to baseline trial 3;
continue polling 50677, never restart completed trials. The scratch comparator
`/tmp/coscientist-compare-pro35.py` and source snapshots remain needed.

Scoped cleanup/deslop found no obsolete artifacts to remove; active trial
scratch and unrelated AGENTS.md edits are preserved. No UI code changed.
Reflog shows expected sequential commits and stash list is empty. No PR,
merge or deployment occurred. Report counts as completed/total: M1 28/36,
eight remaining; campaign 60 open. Next finish the third pair, preserve failed
qualification evidence, and resolve scientific qualification without lowering
gates; remaining provenance and publication-safety work stays open.

### 2026-09-20 — Cycle 42, trace Pro qualification failures

Starting commit `9fb275fc`; previous goal cycle was progress (offline gates and
retained second pair). Session 50677 remains live on baseline trial 3; no trial
was restarted. Read current plan/worktree and inspected the actual candidate
source and retained physical-response artifacts. Independent fresh-context
review agreed with the nine-error decomposition. Retained analysis in
`references/external/baseline/model-qualification/pro-failure-analysis.md`.

Five pair-2 errors originate in primary PARTIAL judgments (species/time/topic),
two are pre-model zero-overlap retrieval omissions, one is the .25 lexical
opposition eligibility floor rejecting .20 coverage, and one is an actual
secondary-model opposition denial. Pure offline calls reproduced retrieval and
coverage outcomes. No inference was performed outside the existing batch.
The source files inspected have no diff from pinned candidate `06a17a70`.
This evidence changes the next investigation: switching models alone cannot
resolve the deterministic pre-model omissions. After the unchanged third pair,
inspect representative identifier/paraphrase claims and partial-support
semantics before choosing a general correction. No benchmark-specific rules,
label changes, gate reductions or adoption were made.

Cleanup/deslop was documentation-only; retained active scratch/snapshots and
unrelated AGENTS.md work. No runtime/UI changes, no test rerun needed for this
analysis, no PR or release. M1 remains 28/36, eight open; campaign 60 open.
Next resume 50677, finish/retain the third pair, and use the failure analysis to
scope a test-first correction without treating model judgments as proof.

Final poll: baseline trial 3 completed (.433 accuracy, 0 contradiction recall,
33 physical requests), retained after JSON/known-credential validation. Session
50677 advanced to candidate trial 3; this is now the active child to resume.

### 2026-09-20 — Cycle 43, persisted verification methods; Pro trials complete

Starting commit `92938ee3`; previous cycle was progress (failure diagnosis).
Worked on independent M1-04b1c while the unchanged final live trial ran in
its pinned snapshot. Reproduced missing single/batch metadata, absent stored
API/report metadata, loss on reused assessments, and custom-assessor empty
retrieval misclassification with failing behavioral tests before corrections.

Added `verification_method` from draft through assessment, gate enrichment and
recovery, append-only claim-evidence rows, API/report payloads and Markdown.
An additive idempotent SQLite migration leaves existing rows `legacy_unknown`.
Known paths distinguish no evidence, deterministic lexical fallback, primary
model judgment, lexical-founded contradiction, guard rejection, unconfirmed
opposition request and separately model-verified opposition. Reports explicitly
say the separate model check is not scientific validation. Requested assessor
identity remains separate and unchanged. No entailment labels or publication
thresholds changed. Production migration still requires a verified backup at
release; no production database was touched.

Independent approach and final review caught and resolved the generic empty-
evidence case and confirmed final propagation/compatibility. 83 targeted tests
pass, including API reopen, migration twice, report output, gate reuse,
single/batch and failure cases. All four explicit size checks pass. `make lint`
and `make typecheck` exit 0; nine browser E2E tests pass (exit 0, 34.3s).
Logs: `/tmp/coscientist-cycle43-{final-targeted,lint,final-types,e2e}.log`.
The prior full-suite result predates this metadata change; rerun affected/full
required checks before release. Completed M1-04b1c only, not model qualification.

Session 50677 exited 0 after candidate trial 3 (.700 accuracy, .90 recall,
43 requests). The three Pro pairs are complete but unaccepted: trials 2 and 3
miss .75 accuracy. All three pass other declared criteria; total 229 physical
requests. Final artifact known-secret scan and pinned runtime comparison pass.
Retained candidate3 and full summary. The maintained comparator now accepts
`--series opposition-pro`; default Mini and Pro both regenerate complete=true,
accepted=false without inference. No trial remains active. README and campaign
state now reflect both completed failed model qualifications. Investigation
must address the recorded retrieval/semantic limitations, not lower gates.

Scoped cleanup/deslop removed no required artifacts; active/reference snapshots
are retained for the next controlled experiment. No UI component changed;
Markdown report behavior is covered by public report tests and browser flow.
Preserved unrelated AGENTS.md edits. No PR/merge/deployment. M1 is 29/36,
seven open; campaign 59 open. Next scope a general, test-first correction from
the stage-level failure analysis and compare it with matched frozen evidence.

### 2026-09-20 — Cycle 44, short-term retrieval candidate

Starting commit `37bfc0f0`; previous cycle was progress (durable method
provenance and completed Pro comparison). Split the demonstrated retrieval
omission into M1-04b1b-r1 before implementation; the scientific qualification
item remains open. Four unseen identifier examples now reach the public
assessment boundary (p53, DNA, Protein H, J/K). The first three failed before
the correction. A separate failing case reproduced admission from only
long function words (this/with), then passed after stopword filtering.

Added a retrieval-only token set retaining short letter-bearing alphanumeric
terms and excluding an explicit common function-word set. The deterministic
verdict tokenizer, scores, thresholds and contradiction guard are unchanged.
Shared-term counts preserve stable ranking for unchanged tokens; top-k remains
bounded. Single, batch and freshness paths share the correction. Added an X
to the existing batch passage-number fixture so its documented tied relevance
remains true; its expected resolved source and label are unchanged.

Independent design/final review endorsed the bounded correction and required
honest limitations: any identifier colliding with the case-folded stopword
set is still excluded; hyphen variants are not normalized. No entity allowlist,
new dependency, semantic-search service or live inference was introduced.
Retained rationale and hashed offline retrieval artifact under model-qualification/
`retrieval-candidate.md` and `retrieval-candidate-offline.json`. All 30 frozen
challenge items now provide candidate passages; this is not scientific evidence
of improved labels. Both prior live model qualifications remain failed.

76 targeted tests pass, including bounded ordering, no identifier-only support,
recovery fingerprint changes and the existing contradiction regressions. All
four explicit size checks pass. `make lint`, `make typecheck` and
`make eval-smoke` exit 0. The broader `make test-app` is STILL RUNNING in
session **93694**, log `/tmp/coscientist-cycle44-app.log`; latest confirmed
live poll showed progress beyond 81 percent. Resume the same handle before
starting another app/engine suite; do not restart from silence. No full app
pass is claimed. Relevant logs use `/tmp/coscientist-cycle44-*`.

Scoped cleanup/deslop kept the explicit stopword list separate to respect
module size, found no obsolete runtime code, and preserved unrelated AGENTS.md
changes and experiment sources. No UI changed, no PR/release/deployment.
M1 is 30/37 (seven remaining); campaign 59 open. Next finish the regression
suite, then freeze a matched evaluation protocol for the updated candidate.
The original evaluator differs only by extracting its assessor-selection helper;
compare the actual metric/gate code and declare all source deltas before any
new live comparison. Do not reuse old live answers as new-arm results.

Cycle 44 final suite result supersedes the running status above: session 93694
exited 2, with 1843 tests passing and one strict report-output fixture failing.
That fixture predated cycle 43's intentional legacy-method disclosure. Added
only the expected `Assessment method: not recorded.` line, preserving the
full ordered-output assertion. Independent review verified the fixture lacks
method metadata and the fallback is correct. All 12 report/provenance tests
now pass; Ruff and diff checks pass. No process remains active. The full app
command did not exit 0, so retain its actual outcome and run the required
release gates after subsequent changes rather than claiming a green full run.
Next prepare matched live qualification from committed source; no inference
batch has been started for the retrieval candidate.


**2026-09-20 — Cycle 45, M1-04b1b preparation (open).** Starting commit
94107aed. Previous turn made authoritative progress by recording the user's
post-M1 orchestration instruction; it did not advance scientific acceptance.
Recorded the independently reviewed composite comparison protocol in
model-qualification/retrieval-trial-protocol.md. Both arms use the same pinned
baseline evaluation subtree; app/engine are baseline14e8c599 and candidate94107aed.
Counterbalanced trial order replaces always-baseline-first; unchanged per-trial
accuracy/contradiction-recall gates remain mandatory. No new inference ran.

Retained preparation and offline preflight scripts verify the frozen runtime,
all 1647/1653 source blobs and all 301/302 imported project modules respectively.
Both offline challenge executions completed with isolated credential-free
environments; retrieval-preflight.json records results as offline only. Final
snapshots and full manifest: /tmp/coscientist-retrieval45-reviewed/. The earlier
/tmp/coscientist-retrieval45/ was superseded after formatting the preparer; use
the final directory. This is compatibility evidence, not scientific acceptance.
Ruff and diff checks pass. No running trial, deployment, PR or model selection.

Next extend the existing live observer/comparator with transitive source checks,
per-request usage and composite identities, then fresh catalog admission and
three counterbalanced pairs. Preserve prior failed results. M1 remains30/37,
seven remaining; total59 open. User AGENTS.md changes remain untouched.

Independent preflight review identified ephemeral manifest retention and missing
runner/runtime provenance. Embedded the entire source manifest in the retained
artifact, added runner SHA and actual runtime/environment policy, checked the
frozen executable path, and replaced optimizable assertions with explicit errors.
Recreated reviewed snapshots and reran both offline panels successfully. Earlier
45 and 45-final snapshot directories are superseded. No acceptance box changed.

**2026-09-20 — Cycle 46, M1-04b1b live launch preparation.** Previous cycle
made progress: pinned composite snapshots and retained successful offline
compatibility evidence. Starting commit9f86b47c. Extended the existing observer
with transitive source verification before physical calls and after completion,
actual response usage/identity, runtime and verification-method evidence. New
runner binds manifest and controls to retained preflight, rechecks every source
file and frozen runtime, uses pinned zero-cost admission, counterbalances the
three pairs, and refuses existing trial/catalog/log outputs. Comparator keeps
prior failed series byte-identical and validates the new composite source,
usage, historical-control, method and item-level evidence without loosening gates.

Source-guard valid/altered/escaped cases and a fake transport's usage/identity
capture passed offline. Initial temporary-directory test needed canonicalizing
macOS's /var alias; production snapshot roots were already canonicalized.
Independent Terra review found manifest/control binding and log preservation
holes; fixed both before launch. Ruff and diff checks pass. Current public
catalog lists Nex Pro :free at zero prompt/completion prices; the pinned engine
admission contract handles omitted ancillary rates for explicit free routes.
No product source changed; candidate remains94107aed. New inference series is
opposition-retrieval-pro. Running-handle/result evidence follows below.

Cycle46 launch: instrumentation committed9f7e4708. The sequential six-arm
batch is LIVE in exec session **91986**, confirmed by a successful poll with
`Starting baseline trial 1` and live assessor responses in
/tmp/coscientist-retrieval45-reviewed/baseline-1.log. Resume this exact handle;
do not relaunch because an artifact has not yet been written. Probe artifacts
are written only when each child finishes. Runner logs remain in the reviewed
snapshot directory; retained catalog1 records current zero-price eligibility
and runner/probe/comparator/source-guard hashes. No trial is yet complete.
The empty paired-summary artifact is an explicitly incomplete comparator
preflight result, not a live result. Next poll91986, retain terminal results,
and run the composite comparator after complete pairs. No deployment occurred.
M1 remains30/37, seven remaining; campaign59 open.


**2026-09-20 — Cycle47, M1-09 locally verified; M1-04b1b live.** Previous
cycle made progress by committing verified instrumentation and starting the
confirmed live batch. Starting18bc688f. Batch91986 remains live; baseline1
completed with accuracy.433/contradictionrecall0, 33 physical requests, all
zero caps and expected served model with usage, 307 source-verified imports.
Candidate1 started in the same process. Retained sanitized baseline artifact.
Do not restart the batch or overwrite any prior trial/log.

Reproduced three release-evaluator defects with failing public-interface tests:
missing final screen, final block without review flag, and blocked legacy/pending
hypothesis content were incorrectly released. Corrected the evaluator using
the exact pure classifier called by live publication, without its audit writes,
and the highest-ID final safety record. Hold/block/unknown/missing final records
withhold; allow and redaction-with-matches follow live finalization. Approval
of an old hold alone is not a new successful screen. Removed the incorrect
all-stage unresolved-review veto: a held hypothesis excludes that idea, while
a final redaction may publish despite its review flag. No app source changed.

24 evaluator tests and45 combined evaluator/public-finalization/redaction/drain
tests passed. Evaluation mypy passed60 source files; Ruff/diff checks passed.
Independent approach and final reviews found no blocker. Missing legacy statement
is an explicit artifact-integrity precondition, not a new production policy.
Malformed redaction matches and export authenticity remain documented limits:
this evaluator consumes the public audit shape, cannot authenticate exports,
and does not claim to prove scrubbing independently of the app integration tests.
No UI change or new dependency; scoped cleanup kept the correction in the evaluator.

Full evaluation suite is still LIVE in session36810, log
/tmp/coscientist-cycle47-evaluations.log. Resume this handle before starting
another test suite; focused safety suite2145 and mypy67368 exited0. Full-suite
success is not claimed. Next poll91986 and36810, compare complete live pairs,
and retain actual outcomes. M1 now31/37, six remaining; campaign58 open.
No merge, deployment, selected model or scientific adoption occurred.

**2026-09-20 — Cycle48, verification and observed waits.** Previous cycle
made progress by fixing the release evaluator and retaining baseline1 evidence.
Read actual tree (only unrelated AGENTS.md edit), resumed91986 and36810.
Evaluation suite36810 exited0. Live candidate1 remains running in91986; no
restart and no new acceptance claim. Broader checks at source3bbb65d4:
lint/typecheck/build/eval-smoke and718 frontend tests (119 files) all passed,
combined session96871 exited0. Retained verification-cycle48.json.

Full suite48458 exited2 in engine:3102 passed,22 failed,2 skipped. Failures
show nested macOS sandbox_apply denied by this session's outer sandbox;
unchanged suite relaunched with approved host execution as session**15594**,
log /tmp/coscientist-cycle48-test-all-host.log. Original failed log retained.
This is a confirmed terminal failure followed by an environment correction,
not a restart on observation timeout. Browser e2e is independently running
in session**2658**, log /tmp/coscientist-cycle48-e2e.log. Poll both handles;
do not start another app/engine suite while15594 runs. No green full-suite
or browser result claimed yet.

Read-only Railway/Vercel deployment refresh confirms the prior API/MCP
SUCCESS IDs and Vercel READY deployment on7dce086d; record releases-cycle48.json.
Railway status returned null replicas, so current replica configuration is not
inferred. Vercel project lookup has a connector argument mismatch; deployment
lookup by production domain succeeded instead. No services/config were changed.
Next resume91986,15594,2658; retain results and diagnose actual failures without
changing assertions. M1 remains31/37;58 campaign items open.

**2026-09-20 — Cycle49, required verification complete; live pair pending.**
Previous cycle progressed by completing checks, confirming production state,
and correcting the test environment after an observed terminal failure.
Resumed all three authoritative handles. Host test-all15594 exited0:
3124 engine tests passed (2 existing skips),1844 app tests passed,274 MCP
tests passed, MCP types and parity/evaluation suite passed. The previous
outer-sandbox22 failures disappear without code or assertion changes.

Browser2658 exited2 after browser-cache lock EPERM and Chromium MachPort
registration denial (nine browser launch failures). Read-only process/source
inspection established Playwright's installer was retrying its cache lock for
up to ten minutes; no restart occurred while that handle remained live. After
terminal failure, host browser19672 ran the unchanged suite:9 passed, exit0.
All required ordinary verification commands are now green for product source
3bbb65d4; subsequent commits change records only. Updated verification-cycle48.json
with terminal outcomes and retained result lines/log hashes. No new skips,
threshold changes or product edits. Linux confinement checks from earlier work
remain unchanged; no confinement source changed this cycle.

Read-only detailed Railway API config confirms one sfo replica and /app/data
mount; retained api-invariants-cycle49.json. No environment values requested,
no release or configuration mutation. Rechecked baseline1's manifest/control,
all307 imported-source hashes and all33 physical-request usage records against
frozen evidence successfully. Live batch91986 remains active on candidate1;
its recorded reasoning-budget exhaustion entered the existing raised-budget
retry, not a restarted experiment. Poll91986 next and run the paired comparator
when a pair completes. No other test process remains live. M1 remains31/37,
six remaining;58 campaign items open. No scientific adoption claimed.

**2026-09-20 — Cycle50, failed live pair and scope candidate (open).** Previous
cycle progressed by completing full/browser verification and recording current
production invariants. Startingf3b1166a. Resumed91986: retrieval-candidate1
finished22/30=.733 accuracy and.90 contradiction recall,46 physical requests.
Paired baseline was.433/0. Comparator verified improved metrics, historical
controls, live secondary-verifier negative control, no new false contradictions
and no recorded deterministic fallback, but the unchanged.75 accuracy gate
failed. Retained candidate1, pair1 summary and catalog2, with secret-value scan.
Batch91986 continues unchanged on candidate2 (counterbalanced order); still
incomplete and not accepted. Do not stop/restart or modify its shared observers.

Seven primary-model errors label species/time/endpoint mismatches PARTIAL;
the remaining error is the existing contradiction subject-coverage guard.
All six support paraphrases now succeed. Independent review traced the seven
to instructions explicitly permitting adjacent findings/narrower conditions.
Added concrete open itemM1-04b1b-s1 and implemented a prompt-only candidate in
both single/batch assessors: partial must address a component/result within the
claim's explicit scope, without inventing absent restrictions. Four labels,
quote validation, contradiction guard, budgets and publication gates unchanged.
This is a local design choice, not Google-backed private implementation evidence.

Prospective synthetic scope controls protect same-scope partial, broad claims,
full support and same-scope contradiction against overcorrection, alongside
population/model/dose/time/endpoint negatives. They are not blind hold-outs or
expert scientific judgments.59 targeted public-assessor/provenance/gate tests
passed after final edit; Ruff/diff passed. No live call used the new prompts.
Independent final review approved the prompt/control semantics but requires
wiring scope-control hashes, per-item/quote evidence and comparator gates before
future trial launch. That wiring is intentionally pending while the existing
runner remains active; candidate item stays unchecked. Prior full-suite green
results apply to pre-prompt source3bbb65d4, not a release claim for this candidate.

Next poll91986 and retain remaining unchanged pairs. After terminal completion,
extend the retained probe/runner/comparator for the prospective scope controls,
freeze new sources and run fresh matched trials. Do not reuse old answers as
new-arm results. M1 is31/38 (seven remaining); campaign59 open. No deployment,
model selection or scientific adoption. Unrelated AGENTS.md edit preserved.


**2026-09-20 — Cycle51, prospective scope-control evaluator.** Starting03ea8484.
The preceding instruction-acknowledgment turn changed no campaign evidence;
revalidated the next safe action. Polled session91986 and confirmed it remains
live on baseline2; no restart or shared observer edits. Retained candidate2:
26/30 accuracy (.867), .90 contradiction recall,45 physical requests. Its
paired baseline is pending and pair1 failed, so the series remains unaccepted.

Added separate scope-control helper and10 offline tests through public single
and batch assessor interfaces. Controls retain source-located spans, reject
wrong labels, invented quotes, empty evidence and deterministic fallback.
Independent review identified unknown provenance falsely passing: three red
regressions reproduced it; explicit recognized model methods now required.
All10 tests and Ruff pass. The helper makes no inference calls or credential
loads. Single-claim batch controls preserve evidence isolation; full multi-claim
verification remains required. Legacy baseline methods must remain unknown,
with candidate acceptance distinguished from observational baseline results.

No acceptance checkbox completed: wire helper/input hashes/telemetry/comparator
after91986 terminates, then run the new matched candidate. Current frozen scripts
remain untouched. No model selected, PR, deployment or production mutation.
M1 remains31/38 and campaign59 open. User AGENTS.md changes preserved.

**2026-09-20 — Cycle52, second matched pair retained.** Starting7de388e9.
Previous cycle was progress: reviewed scope evaluator and tests committed.
Confirmed session91986 live; baseline2 finished and baseline3 started. Existing
unchanged comparator validates pair2: baseline .433 accuracy/0 recall against
candidate .867/.90, all seven acceptance predicates true,33 versus45 physical
requests. Pair1 still fails accuracy; two pairs are incomplete and unaccepted.
Retained baseline2, pair summary and third fresh catalog, configured secret-value
scan passed. No observer/runner/source snapshot edits or restarted inference.

Offline prospective scope-control preflight confirms all10 inputs retrieve
nonempty evidence through both public single and one-claim batch interfaces.
Retained scope-controls-retrieval-preflight.json explicitly labels simulated
verdicts and no inference; it proves retrieval admission only, not model quality.
No checkbox completed and no production changes. Next finish live pair3, then
wire prospective scope controls into a new frozen matched comparison. Current
session91986 is the exact live handle; preserve artifacts and do not restart
on observation silence. M1 remains31/38, campaign59 open.

**2026-09-20 — Cycle53, post-prompt release verification.** Startingc46cd6f5.
Previous cycle progressed matched live evidence. Re-read current open items and
confirmed91986 live on baseline3. Frozen inference scripts remain unchanged.
Required lint, typecheck (492 app/559 engine/60 evaluator files) and offline
safety/citation smoke pass against current prompts. Started required full suite
with host sandbox permissions: session50595, log
/tmp/coscientist-cycle53-test-all.log. Confirmed handle and OS process live;
quiet output is not failure. Do not launch a competing suite or restart it.
Retained verification-cycle53.json with log hashes and explicit running state.

Only product delta from prior full verification is the two assessor prompt
strings. Prior frontend build/tests remain applicable; no frontend code,
dependencies or evaluation inputs changed. Current full suite and live
qualification still need terminal evidence; no checkbox marked and no release
claimed. Next observe50595 and91986, retain outcomes, then integrate scope
controls after the frozen batch terminates. M1 remains31/38, campaign59 open.

**2026-09-20 — Cycle54, full post-prompt verification passed.** Starting509a6063.
Previous cycle made progress and retained live handles. Resumed50595 through
terminal exit0: engine3124 passed/2 existing skips, app1844 passed, MCP274 passed
and strict types71 files, parity115 rows valid, evaluation tests complete.
Required isolated browser suite91901 also exited0 with9 tests passed. Updated
verification-cycle53.json with hashes and results; prior lint/typecheck/smoke
passed at identical product source. Frontend build/tests reused only because
their code/dependencies/inputs are unchanged. No tests weakened or new skips.

Session91986 remains live: baseline3 completed .367 accuracy/0 contradiction
recall,33 requests, no error. Retained artifact after configured-secret scan;
full paired admission awaits candidate3, now running. Do not restart or modify
its shared scripts. Pair1 remains failed; no scientific acceptance inferred
from green software tests. Next finish candidate3 and comparator, then integrate
scope controls and freeze the new prompt candidate for fresh matched trials.
M1 remains31/38 and59 campaign items open. No deployment or model selection.

**2026-09-20 — Cycle55, scope-panel integration prepared.** Startingac62456d.
Previous cycle progressed full verification and third baseline evidence.
Confirmed91986 still live on candidate3; no frozen shared script edits. Added
prospective evaluate_model_scope_controls to the separate scope helper: lazy
real single/batch factories, separate existing capture_panel usage scopes,
results assembled after capture completion. Regression failed before wrapper
existed;11 tests now pass, Ruff/diff pass. No inference in these tests.

Independent review found no wrapper blocker, reiterated caller-owned acceptance:
require both mode keys/all individual controls, physical model/usage evidence,
zero fallback, and helper/control/source hashes. Single-claim batch limitation
remains explicit. Added these requirements to partial-support-candidate.md.
Do not mistake live_requested or a method string for verified physical inference.
Next retain terminal candidate3 and full comparator; then wire this wrapper into
the probe/manifest/comparator and launch new frozen prompt trials. No checkbox
completed, model selection or deployment. M1 remains31/38; campaign59 open.

**2026-09-20 — Cycle56, frozen live comparison closed without acceptance.**
Starting3e8a798b. Previous cycle progressed scope wrapper. Repeated bounded
observations confirmed91986 live until terminal exit0; no restarts. Candidate3
completed .867 accuracy/.90 contradiction recall,46 physical calls. Unchanged
comparator now reports complete=true, accepted=false, three pairs. Pair1 .733
accuracy misses .75; pair2/3 .867 pass; all have .90 recall. Baselines are
.433/.433/.367 accuracy and zero recall. All pairs improve both metrics and
pass historical/secondary negative controls, no new false contradictions and
no recorded deterministic fallback. All236 physical calls retain matched/free
request evidence. Candidate3 configured-secret scan passed. Committed complete
summary and final arm; existing failures remain visible, not averaged away.

No inference used the revised scope prompts. The active-script freeze is now
lifted because the process is terminal. Next integrate scope wrapper into
probe/manifest/runner/comparator with both-mode and physical-telemetry gates,
freeze new candidate source and execute three fresh matched pairs. Preserve old
series and all its artifacts; do not reuse responses. M1 remains31/38, campaign
59 open. No model selected, PR, merge, deployment or production mutation.

**2026-09-20 — Cycle57, scope comparison integrated and qualified for launch.**
Starting87f678a7; previous cycle progressed terminal three-pair evidence.
Added distinct opposition-scope-pro paths to existing preparer/preflight/runner/
observer/comparator, preserving prior defaults and artifacts. Pin baseline14e8c599,
candidate03ea8484 and evaluations14e8c599 for both. Scope helper/input hashes
bound into manifest, checked before physical calls and by comparator. Both
single and one-claim batch modes have separate usage capture/physical phases.
Candidate acceptance requires both modes/all input IDs, allowed labels, located
quotes, recognized provenance, actual model/usage evidence and no fallback.
Baseline legacy-unknown stays observational; no acceptance provenance invented.
Original challenge, historical and hybrid gates remain unchanged.

Five red helper-gate tests preceded implementation;16 targeted tests now pass.
Real historical telemetry exposed routed-model prefix mismatch; regression
reproduced and fixed it. Offline preflight caught invalid None assessor stubs;
replaced with valid inconclusive drafts compatible with old baseline. Final
preflight verifies both pinned APIs/all10 nonempty retrievals and304/306 imported
source hashes without credentials or inference. Snapshot manifest:
/private/tmp/coscientist-scope57-reviewed/source-manifest.json. Earlier scope57
snapshot is superseded; do not use it. Historical summaries regenerate unchanged.
Ruff/diff checks pass; independent final review recommends launch. Product code
unchanged since its full green verification. No scientific acceptance yet.
Next run frozen scope series, preserve all results, and compare three fresh pairs.
M1 remains31/38; campaign59 open. No model selection/deployment.

Cycle57 launch evidence: committed integration9acebec9; runner session41647
confirmed live and started baseline1 after fresh catalog admission. Catalog1
retained. Freeze observer/helper/comparator/runner and scope inputs until this
six-arm batch is terminal. Logs under /private/tmp/coscientist-scope57-reviewed/.
Do not restart on silence; poll41647. Old session91986 is terminal, not resumable.

**2026-09-20 — Cycle58, migration release readiness while live trials run.**
Starting619fdb71; previous cycle progressed integrated/frozen live launch.
Polled41647, confirmed still live on baseline1. Shared qualification code and
inputs remain unchanged. Independent read-only review found no code-level
blocker in the sole persistent change: additive claim_evidence.verification_method
with legacy_unknown default, idempotent migration and old named-column inserts
compatible. Existing real-store tests cover migration/reopen/report provenance.

Ran a synthetic local WAL backup drill using SQLite online backup from a read-only
connection. Committed WAL row captured; backup quick_check ok; migration twice
preserved row/default; old named-column insert worked; backup retained old schema.
Temporary synthetic DBs removed. Retained backup-readiness-cycle58.json, explicitly
not a production backup or full old-application compatibility proof. Expanded
campaign release procedures: verify consistent backup before auto-deploying merge,
check existing storage capacity, retain only non-private metadata, avoid serving
VACUUM, preserve additive column on code rollback, and prepare a genuinely free
recovery code/config target. Actual production backup/rollback evidence stays open.

No code or inference changes, no deployment, no checklist completion. Next poll
41647 and retain scope-arm evidence when terminal. M1 remains31/38;59 open items.

**2026-09-20 — Cycle59, verified wait.** Starting842df5cf. Previous cycle
progressed migration readiness. Repeated bounded polls confirm session41647 live
on baseline1; log reached historical controls, no terminal artifact or error.
No restart, shared-script edit, new inference batch or acceptance change. Next
poll41647 and retain its complete arm; M1 remains31/38 and59 campaign items open.

**2026-09-20 — Cycle60, first scope baseline retained.** Starting2fbfac92.
Previous cycle was a verified wait; resumed41647 through baseline1 completion.
Baseline challenge .40 accuracy/0 contradiction recall,53 physical requests;
runner is confirmed live on candidate1. Both scope modes produced10 physical
calls with complete recorded model/usage evidence. Single labels match8/10:
changed-model and changed-follow-up incorrectly partial. One-claim batch matches
10/10. Provenance remains legacy_unknown, so candidate-only acceptance correctly
returns false for baseline; do not relabel it as model-qualified provenance.
Source/control/helper identities, all zero-price caps, served model and configured
secret-value scan passed. Full paired source/metric comparison awaits candidate1.
No shared script edits, restart, new model selection or production change. Next
poll41647; retain candidate1 and run unchanged scope-series comparator. M1 remains
31/38,59 open. Current live logs: /private/tmp/coscientist-scope57-reviewed/.

**2026-09-20 — Cycle61, release security preflight attempted.** Startingc3cdef26.
Previous cycle progressed first baseline evidence. Session41647 confirmed live
on candidate1; frozen scripts unchanged. Started required pre-release security
DIFF scan for exact7dce086d..c3cdef26, ID37397870-2c59-4fa1-b638-30445fd598f6.
Scan directory /private/var/folders/sn/2cg90mwd5fsdyrdzxp0t4rfc0000gn/T/codex-security-scans-MVfosz/co-scientist/c3cdef26769aefc4bd877755871473cc7e0b36e8_20260919T235409Z_6oel70jc.
Dedicated preflight worker spawn failed (agent thread limit reached); prescribed
parent fallback ran helper. Exit2: agents.max_threads cannot be set when
multi_agent_v2 is enabled. No concrete remediation patches returned; no user
configuration changed. Raw result /tmp/coscientist-security-preflight61.json.
Saved exact command/error in authoritative scan context. Scan remains in preflight,
not failed/cancelled; no substantive security coverage claimed. Recover this
same scan before release, never create a replacement. This scan-specific setup
issue does not stop live scientific qualification or establish campaign blockage.
Next poll41647 and retain candidate1. M1 remains31/38;59 open.

**2026-09-20 — Cycle62, preflight diagnosis and verified live wait.**
Starting7f151962. Previous cycle established scan setup failure. Read-only
inspection confirms helper error source: /Users/guy/.codex/config.toml has
features.multi_agent_v2=true (line41) and agents.max_threads=6 (line562).
The helper rejects that combination at config_preflight.py:542 before returning
capability results or concrete remediation. No configuration edits or fabricated
runtime overrides; existing scan remains recoverable in preflight. This is host
setup evidence, not a product vulnerability or completed security review.
Session41647 repeatedly confirmed live on candidate1; no terminal artifact,
restart, source changes or new inference batch. Next collect candidate1 and
compare the pair. M1 remains31/38;59 open items.

**2026-09-20 — Cycle63, verified candidate wait.** Starting8a2e519d.
Previous cycle diagnosed the security setup issue. Repeated bounded polls of
41647 confirm candidate1 is still running; no terminal result/error. No new
inference, restart, frozen-source edit or acceptance change. Next observe the
same handle and validate the first completed pair. M1 remains31/38;59 open.

**2026-09-20 — Cycle64, first candidate and evaluator defect evidenced.**
Startinge5a569a1. Previous cycle verified wait. Polled41647 through candidate1
completion: .933 accuracy/.80 recall,64 physical calls; candidate2 now live.
Original comparator validates all seven prior gates but rejects scope controls.
All20 scope labels are correct; sole false predicate in each mode is the
explicit-negation control's lexical_founded method, absent from helper allowlist.
Raw served-model completions contain correct CONTRADICTS and located quotes.
Independent review confirms this is a primary model verdict retained by the
subject/negation guard, not deterministic fallback. Actual fallback events zero.
Secret-value scan passed; retained candidate1/catalog2/original paired summary.

Added focused red regression (1 expected failure,16 passes) without editing any
frozen shared observer. No weakened tests or skipped failure. Existing M1 scope
qualification item includes correcting this evaluator defect after batch ends.
Preserve raw artifacts/original failed summary; recompute controlled predicates
with audited correction rather than fabricate provenance or reuse answers for a
new model comparison. No original scientific threshold changes. Whole series
remains unaccepted. Next observe41647 candidate2 and preserve frozen scripts.
M1 remains31/38;59 open. No model selection or deployment.

**2026-09-20 — Cycle65, auditable post-evaluation correction.** Starting0be9284e.
Previous cycle progressed first pair and reproduced evaluator bug. Confirmed41647
live on candidate2. Independent review supports correcting deterministic scoring
of retained responses without rerunning inference: lexical_founded is guarded
model output, not fallback. Implemented separate scope_correction.py; no frozen
observer/helper/runner/comparator changes. Original summary and per-control checks
retained verbatim in separate corrected receipt, all raw artifact hashes verified,
helper/input/correction digests bound. Only candidate_scope_controls is corrected;
every original non-scope criterion survives. Only lexical_founded contradictions
with allowed labels, independently located quotes, nonempty calls and complete
no-fallback telemetry qualify. Other original method results stay unchanged.

Red import preceded implementation;9 correction tests pass, including mutated
raw artifact rejection and preservation of an unrelated failed gate. Ruff/diff
pass. Independent semantic review found no broadened scientific criterion and
requested the two receipt tests now included. First corrected pair passes;
whole corrected series remains incomplete/unaccepted. Original frozen evaluator's
focused red regression remains pending batch termination (not skipped). This
separate correction permits progress without breaking the live-source freeze.
Next poll41647, retain remaining arms and regenerate original plus correction
receipts. M1 remains31/38,59 open. No deployment or model selection.

**2026-09-20 — Cycle66, second candidate retained.** Startingbb047c79.
Previous cycle progressed auditable provenance correction. Resumed41647 through
candidate2 completion: .933 accuracy/.80 contradiction recall,64 physical calls,
no error. Both scope modes have10 calls/all10 labels correct; separate corrected
scope predicate passes without changing the original artifacts. All requests
carry zero-price caps and expected served-model identity; secret-value scan passed.
Matched baseline2 now running under same handle, so pair2 acceptance remains
pending. Original and corrected series summaries still contain only pair1.
No frozen-source changes, additional batch, model selection or deployment.
Next poll41647; retain baseline2 and run both original and corrected comparisons.
M1 remains31/38;59 open items.

**2026-09-20 — Cycle67, verified matched-baseline wait.** Startinge553b441.
Previous cycle retained candidate2. Bounded repeated polls confirm41647 remains
live on baseline2, with challenge-panel log activity and no terminal artifact.
No restart, extra inference, source edit or acceptance change. Next observe the
same handle, then validate original/corrected pair2. M1 remains31/38;59 open.

**2026-09-20 — Cycle68, live provider timeout retained.** Starting690543c6.
Previous cycle verified wait. Session41647 remains live on baseline2. Log records
attempt1 timeout: litellm.Timeout / OpenrouterException, max_tokens18000 (callsite
6000). Existing bounded retry policy is still executing; no agent restart or
replacement inference. Final raw request/usage evidence is not yet available.
Retain this failed attempt and assess evidence completeness before pair2 can
qualify; do not silently discard it or claim a served model for an unanswered
request. No source/gate changes or acceptance advancement. Next poll41647 and
inspect completed artifact/error. M1 remains31/38;59 open items.

**2026-09-20 — Cycle69, verified retry progress.** Startingba164d56.
Previous goal cycle was a verified wait; intervening user instruction was checked
against the persisted post-M1 orchestration rule. Session41647 is confirmed live
on baseline2. A second provider timeout is now recorded, followed by two new
assessor output messages; the bounded runner continues. No terminal artifact yet.
Preserve both failed attempts when validating physical-request completeness;
no restart, frozen-source mutation, model selection or acceptance advancement.
Next poll the same handle and retain the terminal arm evidence before comparing.
M1 remains31/38; fresh checkbox count59. User AGENTS.md changes remain untouched.

**2026-09-20 — Cycle70, verified wait and telemetry diagnosis.** Starting4b104bc9.
Previous cycle was a verified wait. Repeated bounded polls confirm41647 remains
live, with new assessment output beyond the two timeouts; baseline2 artifact is
not yet written. Read-only inspection establishes that observed_transport appends
its request before awaiting transport but attaches usage/model only on success.
The original comparator requires numeric usage and served model for every request
(compare_opposition_panels.py:151-168). Thus timeout records are expected to
fail closed even if subsequent retries succeed; inspect terminal evidence before
concluding. No request was dropped, no gate relaxed, no frozen source changed.
Next preserve baseline2 and exact comparator failure or result, then finish the
existing batch without restarting it. M1 remains31/38;59 open. No release.

**2026-09-20 — Cycle71, local workflow documentation correction.** Startingb35eaeb8.
Previous cycle was a verified wait with telemetry diagnosis. Session41647 remains
live on baseline2; no restart or frozen-source edit. While awaiting completion,
checked the public-workflow setup against current local instructions and found
RUNNING-LOCALLY.md still claimed missing ENTREZ_EMAIL disables PubMed. Corrected
that stale statement as follow-through on completed M1-03c3a: email is optional,
anonymous access proceeds, and a real canary determines availability. Verified
against initialize_entrez, check_pubmed_available, and the existing anonymous
reachability regression; independent read-only review agrees. Documentation only,
no inference or runtime change. Diff check passed. Next retain the current arm
and compare without discarding timeout evidence. M1 remains31/38;59 open.

**2026-09-20 — Cycle72, baseline2 retained with evidence gap.** Starting365637a6.
Previous cycle progressed the local setup documentation. Session41647 completed
baseline2 and started baseline3 without intervention. Baseline2 accuracy .400,
contradiction recall0,55 physical requests; candidate2 .933/.80,64 requests.
Original comparison exits1 with RuntimeError: Missing physical request usage
evidence. Raw indices11 and12 lack usage and served model, matching the two
observed timeout attempts. Every physical request still carries binding zero
price caps; every returned model is the expected Nex Pro free model. Retained
raw baseline2, fresh catalog3, and a hash-bound pair2 evidence-gap receipt;
configured secret-value scan passed. Pair2 is inconclusive, not accepted or a
scientific rejection. No raw requests discarded, no provenance invented and no
comparison gate relaxed. Original/corrected summaries remain at pair1. Finish
the existing batch before deciding matched rerun; promising candidate stays open.
M1 remains31/38; fresh count59. No model selection, release, or frozen-source edit.
Independent read-only review confirmed the receipt against raw and aggregate
telemetry (two timeouts/unobserved calls/unreported usage records); no factual
flaw found. Final session poll confirms41647 still live on baseline3.

**2026-09-20 — Cycle73, transport continuation rule recorded.** Starting72149031.
Previous cycle progressed retained pair2 evidence. Session41647 confirmed live
on baseline3 by repeated bounded polls, with new assessor output. Independently
reviewed the minimal response to pair2's missing transport evidence. Recorded
in partial-support-candidate.md: finish current batch first; permit one new
matched attempt of both incomplete arms with identical frozen identities and
predeclared candidate-first pair2 order; retain original attempts and failures;
never rerun a completed scientific failure just to obtain a pass. Another
transport gap requires investigation, not automatic looping. Configuration or
scientific scoring changes require a fresh full series. No inference launched,
observer changed, threshold relaxed, model selected or deployment performed.
Next await baseline3/candidate3 terminal evidence and apply the recorded rule.
M1 remains31/38; fresh open count59. Diff check passed.

**2026-09-20 — Cycle74, verified third-baseline wait.** Startingeaf99e0e.
Previous cycle progressed the continuation protocol. Repeated bounded polls over
several minutes confirm41647 is live on baseline3, with log progression through
historical controls into batch scope controls. No terminal arm artifact yet;
latest output shows no new timeout. No restart, additional inference batch,
frozen-source mutation, or acceptance change. Next retain baseline3 on completion
and continue observing candidate3 under the same runner. M1 remains31/38;59 open.

**2026-09-20 — Cycle75, third baseline retained.** Starting81ced2a9.
Previous cycle was a verified wait. Session41647 completed baseline3 and started
candidate3. Baseline3 .400 accuracy/0 contradiction recall,53 physical requests,
no terminal error. All53 have numeric usage, expected served model, and exact
zero-price caps. Both scope modes retain10 checks/10 physical calls. Manifest
and probe identities match frozen records; configured secret-value scan passed.
Retained raw artifact without altering any source or prior pair. Pair3 acceptance
awaits candidate3; pair2 still inconclusive and all M1 acceptance items stay open.
Next await candidate3 and terminal runner, then reconcile pairs and execute only
the recorded transport continuation if applicable. M1 remains31/38;59 open.

**2026-09-20 — Cycle76, verified candidate3 wait.** Startingceafebe7.
Previous cycle retained complete baseline3 evidence. Session41647 confirmed live
on candidate3 with new assessment output; no terminal artifact or new reported
failure. Read existing runner continuation mechanics: it rejects any existing
arm/log/catalog and hashes execution sources before each child. Preserve those
safeguards; a transport continuation needs explicit new artifact names and bound
source identities after this batch terminates. No active source changed or
additional experiment started. Next await candidate3, reconcile complete pairs,
and address pair2 under the cycle73 protocol. M1 remains31/38;59 open.

**2026-09-20 — Cycle77, verified final-arm wait.** Starting41ebfd05.
Previous cycle was a verified wait. Repeated bounded polls over several minutes
confirm41647 remains live on candidate3; new supporting-assessment log output
appeared after the contradiction-assessment output. No terminal artifact or new
reported error. No restart, source mutation, extra batch, or acceptance change.
Next retain candidate3 and confirm runner termination before reconciliation and
the recorded transport continuation. M1 remains31/38; fresh open count59.

**2026-09-20 — Cycle78, interrupted-run recovery.** Startingb64c9bfa.
Previous completed cycle was a verified wait; subsequent observation was user-
interrupted before a cycle log. Session41647 now reports Unknown process id;
its temporary logs/snapshots are absent. Escalated OS process inspection finds
neither runner nor probe. Thus the batch is stopped, not merely silent. Five
committed arms survive; candidate3 has no result and its in-flight requests
cannot be reconstructed or claimed complete. Rebuilt3300 snapshot files from
pinned Git objects using existing preparer; manifest byte hash exactly matches
retained preflight. Python, executable and package versions also match. Retained
scope-interruption-recovery.json. No inference restarted. Pair3 now requires
explicit matched recovery alongside transport-incomplete pair2, preserving all
original evidence and reporting missing interrupted observations. Next implement
minimal non-overwriting recovery using existing guards, with fresh free admission
before either arm; keep scoring and model settings fixed. M1 remains31/38;59 open.

**2026-09-20 — Cycle79, explicit recovery runner verified.** Startingda27ea01.
Previous execution cycle progressed reconstruction; cleanup follow-up preserved
intentional user AGENTS changes. Applied ponytail/tdd/karpathy to recovery.
Added the minimal schedule and existing-runner CLI for exactly recovery1 pairs
2,3, preserving C/B then B/C ordering. Every output/log/catalog is suffixed;
all collision checks run before credential loading/network. Catalog records
bind attempt, selected trials, manifest hash, original artifact names/hashes or
missing status, and execution identities including scheduler. Plan-only exits
without inference. Red missing-module test preceded implementation;8 focused
schedule/CLI tests now pass, including collision refusal and original schedule;
Ruff format/check and diff check pass. Independent review found no blocking
cost/preservation/default regression. Actual plan-only run matched retained
manifest19896e07... and selected only pairs2/3. No inference launched.
Next extend comparator and separate correction receipt with explicit recovery
namespaces: original pair1 identities must match Git9acebec9 plus its catalog;
recovery pairs must match new catalog identities and retain recovery_of metadata.
Scientific observer/helper/input bytes and every acceptance gate stay fixed.
This completes runner preparation only, not live qualification. Original scope
helper regression remains pending; no claim all helper tests are green.
M1 remains31/38; fresh open count59. No model selection or release.

**2026-09-20 — Cycle80, recovery comparison integrated.** Startinga4887e54.
Previous cycle progressed the tested runner. Added explicit recovery comparison:
pair1 uses original artifacts and Git9acebec9 observer hashes matched against
its catalog; pairs2/3 require both suffixed replacement arms, fresh catalogs,
current orchestration identities and frozen scientific observers/inputs. Missing
replacement cannot fall back. Original recovery_of hashes/missing status are
validated and retained in separate paired/corrected summaries. Receipt namespace
work delegated to bounded Terra worker; primary integrated comparator. Red
missing-module/namespace tests preceded code;25 focused tests pass. One combined
CLI test exposed inherited PYTHONPATH changing package enumeration; its subprocess
now uses the real launcher environment, preserving the runtime check. Ruff/diff
pass; independent review found no weakened gate or preservation/cost blocker.
Dry-run reproduces exact manifest/order with no inference. Next launch explicit
recovery1 after this commit; record handle and free admission before yielding.
No original artifact or scientific observer changed. M1 remains31/38;59 open.
Recovery launch after f052d77a: exec session28291 is live, starting candidate2.
Fresh recovery catalog2 admits nex-agi/nex-n2.5-pro:free with zero prompt and
completion rates via the existing fail-closed admission policy. Retained catalog
binds all execution sources and original-artifact hashes. Frozen four-arm order:
candidate2,baseline2,baseline3,candidate3. No additional attempt is authorized if
this one is inconclusive without investigation. Next poll28291; never restart
solely on silence. Preserve frozen runner/comparator/helpers until terminal.

**2026-09-20 — Cycle81, verified recovery wait.** Startingede5590c.
Previous cycle progressed recovery integration and launch. Session28291 remains
live on recovery candidate2; schema validation failed on attempt1 (empty string
not valid under schema), followed by new supporting-assessment output under
existing retries. No terminal artifact; retain retry evidence at completion.
GitHub main currently7dce086dd483831b40a12532a84cf7321f058e52, so campaign remains
unmerged. Read-only host check confirms prior security preflight conflict persists
(multi_agent_v2=true plus agents.max_threads=6); no scan completion claimed or
host configuration changed. No frozen-source edit, extra inference batch or
acceptance change. Next poll28291 and retain the completed recovery arm.
M1 remains31/38; fresh open count59.

**2026-09-20 — Cycle82, verified recovery candidate wait.** Starting263f37d4.
Previous cycle was a verified wait. Repeated bounded polls across several minutes
confirm28291 remains live on recovery candidate2, with additional supporting and
contradicting assessment output after the recorded schema retry. No terminal
artifact or new reported error. No restart, extra batch, frozen-source change or
acceptance advancement. Next retain the completed arm and assess full telemetry
before comparing. M1 remains31/38; fresh open count59.

**2026-09-20 — Cycle83, recovery candidate2 retained.** Starting9b07472f.
Previous cycle was a verified wait. Session28291 completed recovery candidate2:
accuracy.933, contradiction recall.80,65 physical requests, no terminal error.
All65 requests retain numeric usage, expected served model and exact zero-price
caps, including the schema retry. Both scope modes pass the separate corrected
predicate; configured secret-value scan passed. Retained raw candidate under
its recovery namespace; original candidate unchanged. Runner now confirmed live
on recovery baseline2. Matched pair and campaign acceptance remain pending;
no source changes, new model selection or release. Next poll28291, preserve
baseline2 and the two remaining arms, then run recovery comparison/correction.
M1 remains31/38; fresh open count59.

**2026-09-20 — Cycle84, verified recovery baseline wait.** Startingf117667b.
Previous cycle progressed retained candidate2 evidence. Repeated bounded polls
confirm28291 remains live on recovery baseline2, with advancing assessment output
and no new reported timeout or terminal artifact. No restart, extra batch,
frozen-source mutation or acceptance change. Next retain baseline2 when complete
and continue the same runner through pair3. M1 remains31/38; fresh open count59.

**2026-09-20 — Cycle85, recovery baseline2 retained.** Startingde10a4ad.
Previous cycle was a verified wait. Session28291 completed recovery baseline2:
accuracy.433, contradiction recall0,53 physical requests, no terminal error.
All53 have numeric usage, expected served model and exact zero-price caps;
probe/manifest identities match recovery catalog2. Configured secret-value scan
passed for baseline artifact and fresh recovery catalog3. Original timeout-bearing
baseline remains retained. Recovery comparator processes pairs1/2 then exits1
with Missing recovery artifacts for trial3, preserving its fail-closed full-series
requirement; no recovered summary or acceptance claimed. Runner is now live on
recovery baseline3. Next retain both pair3 arms and run paired/corrected receipts
once terminal. M1 remains31/38; fresh open count59. No source edits or release.

**2026-09-20 — Cycle86, verified third recovery baseline wait.** Starting17b89f70.
Previous cycle progressed retained baseline2 evidence. Repeated bounded polls
confirm28291 remains live on recovery baseline3 with new assessment output and
no terminal artifact or new reported error. No restart, additional attempt,
frozen-source mutation or acceptance change. Next retain baseline3 and then
candidate3 from the same runner before full recovered comparison. M1 remains
31/38; fresh open count59.

**2026-09-20 — Cycle87, verified baseline3 continuation.** Startingf632360a.
Previous cycle was a verified wait. Repeated bounded polls confirm28291 remains
live on recovery baseline3 with new assessment output; no terminal artifact or
new reported error. No source changes, restart, extra batch or acceptance claim.
Next preserve baseline3 on completion and continue the same runner to candidate3.
M1 remains31/38; fresh open count59.

**2026-09-20 — Cycle88, recovery baseline3 retained.** Starting47ff417d.
Previous cycle was a verified wait. Session28291 completed recovery baseline3:
accuracy.400, contradiction recall0,53 physical requests, no terminal error.
All53 have complete numeric usage, expected served model and exact zero-price
caps. Probe/manifest identities match recovery catalog3; secret-value scan passed.
Retained the recovery artifact without replacing original baseline3. Runner is
confirmed live on final recovery candidate3. Next retain candidate3 and confirm
terminal status, then execute recovery paired comparison and separate correction
receipt. No acceptance item checked prematurely. M1 remains31/38; fresh count59.

**2026-09-20 — Cycle89, current qualification index restored.** Startingb8e85823.
Previous cycle retained complete recovery baseline3. Session28291 confirmed live
on recovery candidate3 with new assessment output. Updated model-qualification
README, whose last comparison account was cycle43, to link current scope and
recovery protocols/receipts and retained metrics without claiming acceptance.
Explicitly preserved outstanding ranking/usefulness, fallback qualification and
full-workflow requirements. Independent read-only review verified metrics,
telemetry and statuses; clarified that only the evaluations subtree is shared
at baseline revision. Documentation-only; no frozen execution source changed.
Next retain final candidate3 and execute recovered comparison/correction after
terminal status. M1 remains31/38; fresh open count59. Diff check passed.

**2026-09-20 — Cycle90, verified final recovery wait.** Starting24057213.
Previous cycle progressed the qualification index. Repeated bounded polls
confirm28291 remains live on recovery candidate3 with advancing assessment
output and no terminal artifact or new reported error. No source mutation,
restart, extra inference batch or acceptance change. Next retain candidate3,
confirm terminal status and run full recovery comparison/correction. M1 remains
31/38; fresh open count59.

**2026-09-20 — Cycle91, recovery completed but not accepted.** Startingd8fccab1.
Previous cycle was a verified wait. Session28291 terminal exit0. Final candidate3
accuracy.900/recall.80,64 requests; every request has usage, expected model and
zero-price caps. Secret scans passed for raw artifact and summaries. Both recovery
comparison and correction commands exit0 with complete=true, acceptance=false.
Pairs1/2 pass all corrected criteria. Pair3 fails only candidate_scope_controls:
same_scope_unspecified_magnitude returns insufficient rather than required partial
in both modes. Inspected source dataset, primary prompt text and actual response
bodies: complete cessation claim versus reduction with magnitude unreported;
both models return insufficient and no quotes. This is not the lexical_founded
provenance issue. All other paired gates pass. Retain failure, no blind rerun or
threshold/label change. Next investigate minimal general magnitude-contract
correction under existing M1-04b1b-s1, then fresh matched evidence if changed.
M1 remains31/38; fresh open count59. No model selection or release.

**2026-09-20 — Cycle92, general magnitude-contract clarification.** Startingc223b9ae.
Previous reply only acknowledged preferences (no progress); revalidated actual
working tree, completed failed series and source prompts. Independent Terra
semantic review found an ambiguity between partial effect magnitude and untested
claim-defining conditions. Added matching general wording to primary single/batch
prompts: matching scope plus established direction with unreported extent is
partial; measured extent contradicts only if it entails negation. Preserved all
labels, scope controls, scientific gates and prior failures. Existing retained
live failures supply red evidence; 45 targeted offline tests pass, Ruff/diff checks
pass. Scoped cleanup/deslop found no leftovers or new abstractions; user's
AGENTS.md remains untouched/uncommitted. Reflog inspected; stash list empty.
This candidate is not scientifically verified; no checkbox completed, inference,
model selection, PR or deployment. Next pin a separate candidate series and run
three fresh matched pairs with verified zero-cost routing, preserving old frozen
observer identities and receipts. M1 remains31/38; fresh open count59.

**2026-09-20 — Cycle93, fresh magnitude comparison prepared.** Startinge57ad3cf.
Previous cycle progressed the general prompt correction. Added distinct magnitude
series through existing preparation, runner, comparator and correction interfaces;
no changed scientific observer, dataset, threshold or raw-result relabeling.
Worker tests red then green; parent inspected diff and reproduced old recovery
summary exactly in isolated output. Historical recovery orchestration pinned to
f052d77a, preserving evidence after helper evolution. Offline snapshots verify
1647/1653 files and304/306 imports with no calls. Manifest501510f81e0954ab06019ecfc8d425f80a40d5e55108b51752bb3d28f88c85b5.
Plan-only schedules six new arms. Independent launch review required immutable
execution provenance: runner now verifies tracked source bytes against HEAD before
credentials and records execution_revision in catalog. Actual precommit refusal
verified; no credentials loaded or inference performed by that check. Current
public Nex Pro catalog passes admission with zero prompt/completion pricing;
runner rechecks per pair. Named size gates4pass; focused runner/correction tests
26pass, Ruff and diff checks pass. Main remains7dce086d. User AGENTS preserved.
No item accepted or deployment performed. Next commit execution sources and launch
the pinned fresh series, retain live evidence and verify all three pairs. M1
remains31/38; fresh open count59.

Cycle93 launch update: independent re-review confirmed provenance blocker closed.
Committed execution revisionb77878324e1170866007eee24480f073bc10aa66. Runner26568
confirmed live with Starting baseline trial1; catalog1 records that exact revision,
all three selected trials, the retained manifest hash and Nex Pro zero pricing.
No completed arm or scientific acceptance yet. Continue observing the same handle;
do not restart on an observation timeout. Snapshots/logs:
/private/tmp/coscientist-magnitude93/. No frozen execution source may change while
this batch runs. Next retain baseline1/candidate1 results and continue all pairs.

**2026-09-20 — Cycle 94, hermetic app verification corrected; baseline 1 retained.**
Starting commit 11beaa71. Previous cycle progressed by preparing and launching
fresh magnitude trials. Runner 26568 remained live, completed baseline 1, and
started candidate 1. Baseline accuracy .433, recall 0, 53 requests: every request
has numeric usage, expected served model, zero-price caps and reported cost zero.
Source identities and secret-value scan passed; retained the raw artifact.

The required offline suite exposed 18 app failures with dotenv disabled: mocked
requests inherited default free routes and fetched current catalog metadata,
which no longer contains that default. Reproduced two failures in isolation.
Added M1-05a before fixing it. An initial test-model override passed targeted tests
but independent review rejected it because it stopped exercising free admission;
its intermediate full-suite attempt was deliberately cancelled (exit 130).
Final correction uses the existing engine synthetic-catalog fixture pattern in
app tests and an OpenRouter dummy credential. Production defaults, request
admission and fake transport boundaries remain intact. Dedicated policy tests
still provide their own catalog/env overrides. This is local test infrastructure,
not a new product mode or a live catalog claim.

Final evidence: 103 targeted tests pass; make test-all exit 0 (engine 3124 passed,
2 existing skips; app 1844 passed; MCP 274 passed plus strict mypy; parity evidence
and its tests pass); make lint, make typecheck, make eval-smoke and both named
size gates pass; make e2e passes all 9 tests. Build and 718 frontend tests reused
from cycle 48 after verifying unchanged frontend/Makefile trees. Details and
failed-run provenance: references/external/baseline/verification-cycle94.json.
Independent final review found no issue. Scoped cleanup retained failed evidence,
removed the superseded model override, and found no other session leftovers;
user AGENTS.md remains untouched. Reflog checked; no stashes. Checked M1-05a.

M1 is now 32/39: one discovered item added and completed, leaving 59 open overall.
The magnitude series is still unaccepted; no production change or model selection.
Next continue the same live handle 26568 on candidate 1 and retain all six arms
before paired acceptance. Do not mutate frozen execution sources during the batch.

Cycle 94 completion update: candidate 1 also completed, accuracy .967 and recall
.9 with 65 physical requests. All requests have usage, expected model, zero caps
and reported zero cost; source checks and secret-value scan pass. Both comparison
commands exit 0: one complete pair, full-series complete=false/accepted=false.
The separate established provenance correction passes every pair-1 criterion,
including magnitude scope in both modes. Raw matching-scope contradictions retain
the known lexical_founded observer false flag; the correction verifies their real
located primary-model evidence. No changed labels or thresholds. Retained raw
candidate 1, pair-1 summaries and fresh pair-2 catalog. Runner 26568 confirmed
live on candidate 2. Next preserve both pair-2 arms, then pair 3 from that handle.

**2026-09-20 — Cycle 95, verified candidate-2 wait.** Starting a62db70e.
Previous cycle progressed hermetic test verification and retained magnitude pair 1.
Repeated bounded polls confirm runner 26568 remains live on candidate trial 2;
the current log contains ongoing assessment output, with no completed arm artifact
or terminal error. No restart, new inference batch, source mutation, repeated suite,
or acceptance change. User AGENTS.md remains untouched. M1 remains 32/39; fresh
open count 59. Next retain candidate 2 and its matched baseline from this runner,
then pair 3 before evaluating full-series acceptance.

**2026-09-20 — Cycle 96, magnitude candidate 2 retained.** Starting b84cb219.
Previous cycle was a verified wait. Repeated bounded polls of runner 26568
confirmed continued execution, then candidate 2 completed with accuracy .933,
contradiction recall .8 and 64 requests. All requests have numeric usage, the
expected served model, binding zero-price caps and reported zero cost; source
identities and secret-value scan passed. All corrected scope controls pass in
both modes. Raw matching-scope contradiction flags retain the known
lexical_founded observer classification issue; no label or threshold changed.
Candidate 2 alone does not establish a matched pair or full-series acceptance.
Runner 26568 is now confirmed live on baseline 2. Retained the raw candidate
artifact; no execution source changes, restart or additional inference batch.
M1 remains 32/39; fresh open count 59. Next retain baseline 2 and assess the pair,
then continue the same runner through both arms of pair 3.

**2026-09-20 — Cycle 97, qualification index updated during baseline-2 wait.**
Starting 6f816d56. Previous cycle retained candidate 2. Repeated bounded polls
confirm runner 26568 remains live on baseline 2, with assessment output and no
completed artifact or reported terminal error. Updated the qualification README,
which still described the magnitude series as awaiting launch, to link its
current paired receipt and distinguish complete pair 1 from the unmatched
candidate 2. No scientific acceptance, source mutation, restart, or repeated test
suite. User AGENTS.md remains untouched. M1 remains 32/39; fresh open count 59.
Next retain baseline 2 and compare the completed pair, then observe pair 3 from
the same runner before full-series acceptance.
